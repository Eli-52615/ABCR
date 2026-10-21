#!/usr/bin/env python3
"""Build and finalize a plain, offline ABCR runtime from an exact Git commit.

This tool deliberately has no authority to say that a candidate passed tests.
``build`` exports reviewed Git blobs and materializes an already-present Python
runtime into a symlink-free candidate.  ``finalize`` accepts only a genuine,
signed verifier attestation and delegates release identity construction to
``abcr.control.release``.  No mode seals, installs, loads, or starts anything.

The first-deployment trust boundary is therefore explicit::

    exact reviewed commit + observed local runtime -> untrusted candidate
    candidate + real sandbox test + verifier signature -> canonical staging
    human/root review copy -> genesis ceremony -> broker receipt -> installer

The local runtime is an input, not an implicit trust root.  Every selected byte
is copied as a regular file, inventoried in ``requirements.lock``, included in
the candidate tree hash, and must subsequently be covered by the verifier's
signature.  Network access and package/model installation are never attempted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import asdict
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from abcr.control.contracts import ContractError, canonical_json, sha256
from abcr.control.release import prepare_release, stage_release
from abcr.control.verifier import VerificationAttestation
from abcr.control.worktree import TreeEntry, scan_tree, tree_hash


EX_CONFIG = 78
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RELEASE_ID = re.compile(r"^REL-[0-9a-f]{64}$")

# Only production code/config/bootstrap bytes enter a runtime candidate.  In
# particular, data/, fixtures/, tests/, reports/, VCS metadata and working-tree
# files are not exported.  Application modules are mapped into site-packages so
# ``python -I -m <service>`` never depends on PYTHONPATH or a checkout.
GIT_PREFIXES = (
    "src/abcr/",
    "configs/control/",
    "ops/acl/",
    "ops/install/",
    "ops/launchd/",
    "ops/sandbox/",
)
GIT_EXACT = frozenset({
    "configs/protocol_ref.txt",
    "configs/probe/profiles/qwen25-7b-q4-v1.json",
    "configs/research/length-control/task_expansion_zh_v1.json",
    "configs/research/templates/registry.json",
    "requirements-mac.txt",
    "scripts/abcr-bootstrap-selector",
    "scripts/abcr-launch",
    "scripts/abcr_genesis_canary_probe.py",
    "scripts/bootstrap_abcr_accounts.sh",
    "scripts/bootstrap_abcr_genesis.py",
    "scripts/bootstrap_abcr_human.sh",
    "scripts/bootstrap_abcr_service_keys.sh",
    "scripts/bootstrap_research_memory_seal.sh",
    "scripts/build_reviewed_runtime.py",
    "scripts/check_human_signature_domain.sh",
    "scripts/qualify_abcr_genesis_probation.py",
    "scripts/install_abcr_runtime.py",
    "scripts/import_abcr_dataset.py",
})
RESOURCE_MIRRORS = (
    ("configs/research/length-control/task_expansion_zh_v1.json",
     "src/abcr/explore/resources/task_expansion_zh_v1.json"),
    ("configs/research/templates/registry.json",
     "src/abcr/explore/resources/template_registry_v1.json"),
)
RUNTIME_SITE = PurePosixPath("env/lib/python3.12/site-packages")
RUNTIME_PYTHON = PurePosixPath("env/bin/python")
REVIEW_VERIFIER_KEY = PurePosixPath("trust/review-verifier-attestation.pub")
GENESIS_REVIEW_ROOT = Path("/Library/Application Support/ABCR-Genesis/reviewed")
DERIVED_FILES = frozenset({"requirements.lock", "reviewed-source.json"})
IGNORED_RUNTIME_NAMES = frozenset({".DS_Store"})
IGNORED_VENV_FILES = frozenset({"_virtualenv.pth", "_virtualenv.py"})
GENESIS_AUTHORITY_FIELDS = frozenset({
    "schema_version", "ceremony", "authority_sha256", "policy_sha256",
    "authority_id", "human_approved", "reviewed_commit",
    "reviewed_release_path", "release_id", "release_manifest_sha256",
    "source_tree_hash", "broker_seal_nonce", "expected_receipt_id", "tcb",
})


class BuildBlocked(RuntimeError):
    """A fail-closed build/finalization precondition was not satisfied."""


def _canonical(value: Any) -> bytes:
    return canonical_json(value) + b"\n"


def _strict_json(path: Path) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise BuildBlocked(f"duplicate JSON key in {path}")
            result[key] = value
        return result

    try:
        info = path.lstat()
        if (path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise BuildBlocked(f"unsafe JSON input: {path}")
        raw = path.read_bytes()
        value = json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, BuildBlocked):
            raise
        raise BuildBlocked(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise BuildBlocked(f"JSON input is not an object: {path}")
    return value


def _run(argv: list[str], *, cwd: Path | None = None,
         input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            argv, cwd=cwd, input=input_bytes, stdin=subprocess.DEVNULL if input_bytes is None else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=120,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BuildBlocked(f"trusted command unavailable or timed out: {argv[0]}") from exc


def _git_path() -> str:
    for value in ("/opt/homebrew/bin/git", "/usr/local/bin/git", "/usr/bin/git"):
        path = Path(value)
        if path.is_file() and os.access(path, os.X_OK):
            return value
    raise BuildBlocked("reviewed git binary is unavailable")


def _exact_commit(repo: Path, supplied: str) -> str:
    if HEX40.fullmatch(supplied) is None:
        raise BuildBlocked("reviewed commit must be an exact 40-character lowercase SHA-1")
    repo = Path(repo)
    if repo.is_symlink() or not repo.is_dir():
        raise BuildBlocked("repository path must be a real directory")
    outcome = _run([_git_path(), "-C", str(repo), "rev-parse", "--verify",
                    f"{supplied}^{{commit}}"])
    resolved = outcome.stdout.decode("ascii", "strict").strip() if outcome.returncode == 0 else ""
    if resolved != supplied:
        raise BuildBlocked("reviewed commit is unavailable or does not resolve exactly")
    return resolved


def _selected_git_path(path: str) -> bool:
    return path in GIT_EXACT or any(path.startswith(prefix) for prefix in GIT_PREFIXES)


def _candidate_path(git_path: str) -> str:
    if git_path.startswith("src/abcr/"):
        suffix = git_path[len("src/abcr/"):]
        return (RUNTIME_SITE / "abcr" / PurePosixPath(suffix)).as_posix()
    return git_path


def _git_entries(repo: Path, commit: str) -> tuple[dict[str, Any], ...]:
    outcome = _run([_git_path(), "-C", str(repo), "ls-tree", "-rz", "--full-tree", commit])
    if outcome.returncode != 0:
        raise BuildBlocked("cannot enumerate reviewed commit")
    result: list[dict[str, Any]] = []
    destinations: set[str] = set()
    for row in outcome.stdout.split(b"\0"):
        if not row:
            continue
        try:
            metadata, raw_path = row.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split(" ", 2)
            git_path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise BuildBlocked("git tree contains an invalid entry") from exc
        if not _selected_git_path(git_path):
            continue
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise BuildBlocked(f"reviewed source is not a regular file: {git_path}")
        pure = PurePosixPath(git_path)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise BuildBlocked("reviewed source path is unsafe")
        destination = _candidate_path(git_path)
        if destination in destinations or destination in DERIVED_FILES:
            raise BuildBlocked("reviewed source destination collision")
        destinations.add(destination)
        result.append({"git_path": git_path, "candidate_path": destination,
                       "git_mode": mode, "git_blob": object_id})
    missing = sorted(path for path in GIT_EXACT
                     if not any(item["git_path"] == path for item in result))
    if missing or not any(item["git_path"].startswith("src/abcr/") for item in result):
        raise BuildBlocked(f"reviewed commit lacks mandatory runtime source: {missing}")
    return tuple(sorted(result, key=lambda item: item["candidate_path"]))


def _git_blob(repo: Path, object_id: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{40,64}", object_id):
        raise BuildBlocked("invalid reviewed Git blob identity")
    outcome = _run([_git_path(), "-C", str(repo), "cat-file", "blob", object_id])
    if outcome.returncode != 0:
        raise BuildBlocked("cannot read reviewed Git blob")
    return outcome.stdout


def _write_regular(path: Path, raw: bytes, mode: int) -> None:
    if mode not in {0o444, 0o555}:
        raise BuildBlocked("builder output mode is not frozen")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise BuildBlocked(f"builder destination collision: {path}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                 mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    finally:
        os.chmod(path, mode)


def _safe_source_file(path: Path, *, allowed_root: Path,
                      permit_internal_symlink: bool) -> tuple[bytes, int]:
    raw_path = Path(path)
    try:
        initial = raw_path.lstat()
    except OSError as exc:
        raise BuildBlocked(f"runtime source unavailable: {path}") from exc
    if stat.S_ISLNK(initial.st_mode):
        if not permit_internal_symlink:
            raise BuildBlocked(f"site-packages symlink is forbidden: {path}")
        resolved = raw_path.resolve(strict=True)
        try:
            resolved.relative_to(allowed_root.resolve(strict=True))
        except ValueError as exc:
            raise BuildBlocked("Python-home symlink escapes the frozen source") from exc
        raw_path = resolved
        initial = raw_path.lstat()
    if not stat.S_ISREG(initial.st_mode) or initial.st_nlink < 1:
        raise BuildBlocked(f"runtime source is not a regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(raw_path, flags)
    except OSError as exc:
        raise BuildBlocked(f"cannot nofollow-open runtime source: {path}") from exc
    try:
        before = os.fstat(fd)
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk); remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_nlink,
                                 stat.S_IMODE(item.st_mode))
        if identity(before) != identity(after) or len(raw) != before.st_size:
            raise BuildBlocked(f"runtime source changed while reading: {path}")
        return raw, (0o555 if stat.S_IMODE(before.st_mode) & 0o111 else 0o444)
    finally:
        os.close(fd)


def _iter_runtime_files(root: Path, *, site_packages: bool) -> Iterable[tuple[Path, str]]:
    root = Path(root).resolve(strict=True)
    for directory, names, files in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        accepted: list[str] = []
        for name in sorted(names):
            child = current / name
            relative = child.relative_to(root)
            if name == "__pycache__" or name in IGNORED_RUNTIME_NAMES:
                continue
            if child.is_symlink():
                if site_packages:
                    raise BuildBlocked(f"site-packages directory symlink is forbidden: {relative}")
                # Python-home directory symlinks make the selected tree
                # ambiguous.  Only regular-file symlinks are materialized.
                raise BuildBlocked(f"Python-home directory symlink is forbidden: {relative}")
            accepted.append(name)
        names[:] = accepted
        for name in sorted(files):
            path = current / name
            relative = path.relative_to(root).as_posix()
            if (name in IGNORED_RUNTIME_NAMES or name.endswith((".pyc", ".pyo"))
                    or (site_packages and name in IGNORED_VENV_FILES)):
                continue
            if site_packages and name.endswith(".pth"):
                raise BuildBlocked(f"executable .pth file is forbidden: {relative}")
            yield path, relative


def _runtime_source_records(python_home: Path, site_packages: Path
                            ) -> tuple[dict[str, Any], ...]:
    raw_python_home = Path(python_home)
    raw_site_packages = Path(site_packages)
    if raw_python_home.is_symlink() or raw_site_packages.is_symlink():
        raise BuildBlocked("runtime source roots must be real directories")
    python_home = raw_python_home.resolve(strict=True)
    site_packages = raw_site_packages.resolve(strict=True)
    if not (python_home / "bin/python3.12").exists():
        raise BuildBlocked("Python home lacks bin/python3.12")
    if site_packages.name != "site-packages" or site_packages.parent.name != "python3.12":
        raise BuildBlocked("site-packages must be a CPython 3.12 site-packages directory")

    records: list[dict[str, Any]] = []
    # The runtime is a complete relocatable Python home, but excludes build
    # headers, command wrappers, man pages and the base install's site-packages.
    selections: list[tuple[Path, str, bool]] = [(python_home / "bin/python3.12",
                                                 RUNTIME_PYTHON.as_posix(), True)]
    lib_root = python_home / "lib"
    for path, relative in _iter_runtime_files(lib_root, site_packages=False):
        if relative == "python3.12/site-packages" or relative.startswith(
                "python3.12/site-packages/"):
            continue
        selections.append((path, (PurePosixPath("env/lib") / relative).as_posix(), True))
    for path, relative in _iter_runtime_files(site_packages, site_packages=True):
        if relative == "abcr" or relative.startswith("abcr/"):
            raise BuildBlocked("runtime source already contains an unreviewed abcr package")
        selections.append((path, (RUNTIME_SITE / relative).as_posix(), False))

    destinations: set[str] = set()
    for source, destination, internal_links in sorted(selections, key=lambda item: item[1]):
        if destination in destinations:
            raise BuildBlocked("runtime source destination collision")
        destinations.add(destination)
        raw, mode = _safe_source_file(source, allowed_root=(python_home if internal_links
                                                            else site_packages),
                                      permit_internal_symlink=internal_links)
        records.append({"source": source, "candidate_path": destination,
                        "mode": mode, "size": len(raw), "sha256": sha256(raw),
                        "raw": raw})
    return tuple(records)


def _distribution_inventory(site_packages_root: Path) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for metadata in sorted(Path(site_packages_root).glob("*.dist-info/METADATA")):
        raw = metadata.read_bytes()
        parsed = BytesParser().parsebytes(raw)
        name = parsed.get("Name")
        version = parsed.get("Version")
        if not name or not version:
            raise BuildBlocked(f"distribution metadata is incomplete: {metadata}")
        result.append({"name": name, "version": version, "metadata_sha256": sha256(raw)})
    if not result:
        raise BuildBlocked("runtime contains no distribution metadata")
    normalized = [item["name"].lower().replace("_", "-") for item in result]
    if len(normalized) != len(set(normalized)):
        raise BuildBlocked("runtime contains duplicate distribution identities")
    return sorted(result, key=lambda item: (item["name"].lower(), item["version"]))


def _policy_hash() -> str:
    return sha256({"git_prefixes": list(GIT_PREFIXES), "git_exact": sorted(GIT_EXACT),
                   "resource_mirrors": [list(item) for item in RESOURCE_MIRRORS],
                   "runtime_site": RUNTIME_SITE.as_posix(),
                   "runtime_python": RUNTIME_PYTHON.as_posix(),
                   "review_verifier_key": REVIEW_VERIFIER_KEY.as_posix(),
                   "ignored_runtime_names": sorted(IGNORED_RUNTIME_NAMES),
                   "ignored_venv_files": sorted(IGNORED_VENV_FILES)})


def build_candidate(*, repo: Path, reviewed_commit: str, python_home: Path,
                    site_packages: Path, review_verifier_public_key: Path,
                    output: Path) -> dict[str, Any]:
    """Create an untrusted but deterministic, symlink-free candidate tree."""
    commit = _exact_commit(repo, reviewed_commit)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise BuildBlocked("candidate output must not already exist")
    git_entries = _git_entries(repo, commit)
    runtime_records = _runtime_source_records(python_home, site_packages)
    verifier_path = Path(review_verifier_public_key)
    verifier_info = verifier_path.lstat()
    if (verifier_path.is_symlink() or not stat.S_ISREG(verifier_info.st_mode)
            or verifier_info.st_nlink != 1 or stat.S_IMODE(verifier_info.st_mode) & 0o022):
        raise BuildBlocked("review verifier public key must be a non-writable regular file")
    verifier_raw, _ = _safe_source_file(
        verifier_path, allowed_root=verifier_path.parent,
        permit_internal_symlink=False)
    output.mkdir(parents=True, mode=0o700)
    try:
        source_records: list[dict[str, Any]] = []
        for entry in git_entries:
            raw = _git_blob(repo, entry["git_blob"])
            mode = 0o555 if entry["git_mode"] == "100755" else 0o444
            _write_regular(output / entry["candidate_path"], raw, mode)
            source_records.append({**entry, "sha256": sha256(raw), "size": len(raw),
                                   "candidate_mode": mode})
        for record in runtime_records:
            _write_regular(output / record["candidate_path"], record["raw"], record["mode"])
        _write_regular(output / REVIEW_VERIFIER_KEY, verifier_raw, 0o444)

        # configs/research is the human-reviewed authority location.  The
        # package copy is only an addressable mirror for installed ``python
        # -I``; it must never become a second independently drifting policy.
        resource_mirrors: list[dict[str, Any]] = []
        for authority_git, runtime_git in RESOURCE_MIRRORS:
            authority = output / _candidate_path(authority_git)
            runtime = output / _candidate_path(runtime_git)
            authority_raw = authority.read_bytes()
            runtime_raw = runtime.read_bytes()
            if authority_raw != runtime_raw:
                raise BuildBlocked(
                    f"packaged runtime resource differs from reviewed config: {runtime_git}")
            resource_mirrors.append({
                "authority_path": _candidate_path(authority_git),
                "runtime_path": _candidate_path(runtime_git),
                "sha256": sha256(authority_raw),
            })

        runtime_entries = tuple(item for item in scan_tree(output)
                                if item.path.startswith("env/"))
        runtime_lock = {
            "schema_version": 1, "kind": "abcr-frozen-runtime-inventory",
            "builder_policy_sha256": _policy_hash(),
            "python_relpath": RUNTIME_PYTHON.as_posix(),
            "python_sha256": next(item["sha256"] for item in runtime_records
                                  if item["candidate_path"] == RUNTIME_PYTHON.as_posix()),
            "runtime_tree_hash": tree_hash(runtime_entries),
            "distributions": _distribution_inventory(output / RUNTIME_SITE),
        }
        source_manifest = {
            "schema_version": 1, "kind": "abcr-reviewed-source-export",
            "reviewed_commit": commit, "builder_policy_sha256": _policy_hash(),
            "entries": source_records,
            "review_verifier": {"path": REVIEW_VERIFIER_KEY.as_posix(),
                                "sha256": sha256(verifier_raw),
                                "size": len(verifier_raw)},
            "resource_mirrors": resource_mirrors,
        }
        _write_regular(output / "requirements.lock", _canonical(runtime_lock), 0o444)
        _write_regular(output / "reviewed-source.json", _canonical(source_manifest), 0o444)
        for directory, names, _ in os.walk(output, topdown=False, followlinks=False):
            for name in names:
                child = Path(directory) / name
                if child.is_symlink():
                    raise BuildBlocked("builder produced a directory symlink")
                os.chmod(child, 0o555)
        os.chmod(output, 0o555)
        entries = scan_tree(output)
        return {"ok": True, "status": "UNTRUSTED_CANDIDATE",
                "reviewed_commit": commit, "candidate_path": str(output),
                "candidate_tree_hash": tree_hash(entries),
                "runtime_tree_hash": runtime_lock["runtime_tree_hash"],
                "resource_mirrors": resource_mirrors,
                "file_count": len(entries),
                "next_gate": "REAL_SANDBOX_TEST_AND_SIGNED_VERIFIER_ATTESTATION"}
    except Exception:
        # A partial directory is intentionally retained for forensic review;
        # never silently reuse it on retry.
        raise


def _source_manifest(candidate: Path) -> dict[str, Any]:
    value = _strict_json(candidate / "reviewed-source.json")
    if (set(value) != {"schema_version", "kind", "reviewed_commit",
                       "builder_policy_sha256", "entries", "review_verifier",
                       "resource_mirrors"}
            or value["schema_version"] != 1
            or value["kind"] != "abcr-reviewed-source-export"
            or value["builder_policy_sha256"] != _policy_hash()
            or HEX40.fullmatch(str(value["reviewed_commit"])) is None
            or not isinstance(value["entries"], list)
            or not isinstance(value["resource_mirrors"], list)
            or not isinstance(value["review_verifier"], dict)
            or set(value["review_verifier"]) != {"path", "sha256", "size"}
            or value["review_verifier"].get("path") != REVIEW_VERIFIER_KEY.as_posix()
            or HEX64.fullmatch(str(value["review_verifier"].get("sha256"))) is None
            or type(value["review_verifier"].get("size")) is not int
            or value["review_verifier"]["size"] < 1):
        raise BuildBlocked("reviewed source manifest is invalid")
    expected_paths = [(_candidate_path(authority), _candidate_path(runtime))
                      for authority, runtime in RESOURCE_MIRRORS]
    if len(value["resource_mirrors"]) != len(expected_paths):
        raise BuildBlocked("reviewed source resource mirror manifest is invalid")
    for item, (authority_path, runtime_path) in zip(
            value["resource_mirrors"], expected_paths):
        if (not isinstance(item, dict)
                or set(item) != {"authority_path", "runtime_path", "sha256"}
                or item["authority_path"] != authority_path
                or item["runtime_path"] != runtime_path
                or HEX64.fullmatch(str(item["sha256"])) is None):
            raise BuildBlocked("reviewed source resource mirror manifest is invalid")
    return value


def _verify_source_export(candidate: Path, source: dict[str, Any],
                          entries: Iterable[TreeEntry]) -> None:
    """Bind source-export claims to exact candidate members.

    Git object resolution is performed when ``repo`` is supplied to the
    candidate/release doctors.  This structural half is deliberately usable at
    the later human/root boundary where no checkout is authoritative.
    """
    by_path = {item.path: item for item in entries}
    fields = {"git_path", "candidate_path", "git_mode", "git_blob",
              "sha256", "size", "candidate_mode"}
    observed_order: list[str] = []
    git_paths: set[str] = set()
    candidate_paths: set[str] = set()
    for item in source["entries"]:
        if not isinstance(item, dict) or set(item) != fields:
            raise BuildBlocked("reviewed source export record is invalid")
        git_path = item.get("git_path")
        candidate_path = item.get("candidate_path")
        git_mode = item.get("git_mode")
        if (not isinstance(git_path, str) or not isinstance(candidate_path, str)
                or git_mode not in {"100644", "100755"}
                or not isinstance(item.get("git_blob"), str)
                or HEX40.fullmatch(item["git_blob"]) is None
                or not isinstance(item.get("sha256"), str)
                or HEX64.fullmatch(item["sha256"]) is None
                or type(item.get("size")) is not int or item["size"] < 0):
            raise BuildBlocked("reviewed source export record is invalid")
        try:
            expected_path = _candidate_path(git_path)
            pure_git = PurePosixPath(git_path)
            pure_candidate = PurePosixPath(candidate_path)
        except (TypeError, ValueError) as exc:
            raise BuildBlocked("reviewed source export path is invalid") from exc
        if (pure_git.is_absolute() or pure_candidate.is_absolute()
                or any(part in {"", ".", ".."} for part in pure_git.parts)
                or any(part in {"", ".", ".."} for part in pure_candidate.parts)
                or candidate_path != expected_path
                or git_path in git_paths or candidate_path in candidate_paths):
            raise BuildBlocked("reviewed source export path is invalid")
        expected_mode = 0o555 if git_mode == "100755" else 0o444
        actual = by_path.get(candidate_path)
        if (item.get("candidate_mode") != expected_mode or actual is None
                or actual.mode != expected_mode or actual.size != item["size"]
                or actual.sha256 != item["sha256"]):
            raise BuildBlocked("reviewed source export differs from candidate bytes")
        git_paths.add(git_path); candidate_paths.add(candidate_path)
        observed_order.append(candidate_path)
    if not observed_order or observed_order != sorted(observed_order):
        raise BuildBlocked("reviewed source export is empty or not canonical")


def _verify_resource_mirrors(candidate: Path, source: dict[str, Any]) -> None:
    """Prove the runtime-addressable copy is the authoritative config bytes."""
    for item in source["resource_mirrors"]:
        authority = Path(candidate) / item["authority_path"]
        runtime = Path(candidate) / item["runtime_path"]
        try:
            authority_raw = authority.read_bytes()
            runtime_raw = runtime.read_bytes()
        except OSError as exc:
            raise BuildBlocked("reviewed source resource mirror is unavailable") from exc
        if (authority_raw != runtime_raw
                or sha256(authority_raw) != item["sha256"]):
            raise BuildBlocked("packaged runtime resource drifted from reviewed config")


def _runtime_lock(candidate: Path) -> dict[str, Any]:
    value = _strict_json(candidate / "requirements.lock")
    fields = {"schema_version", "kind", "builder_policy_sha256", "python_relpath",
              "python_sha256", "runtime_tree_hash", "distributions"}
    if (set(value) != fields or value["schema_version"] != 1
            or value["kind"] != "abcr-frozen-runtime-inventory"
            or value["builder_policy_sha256"] != _policy_hash()
            or value["python_relpath"] != RUNTIME_PYTHON.as_posix()
            or HEX64.fullmatch(str(value["python_sha256"])) is None
            or HEX64.fullmatch(str(value["runtime_tree_hash"])) is None
            or not isinstance(value["distributions"], list)):
        raise BuildBlocked("frozen runtime inventory is invalid")
    return value


def doctor_candidate(candidate: Path, *, repo: Path | None = None,
                     reviewed_commit: str | None = None) -> dict[str, Any]:
    candidate = Path(candidate)
    entries = scan_tree(candidate)
    source = _source_manifest(candidate)
    _verify_source_export(candidate, source, entries)
    _verify_resource_mirrors(candidate, source)
    lock = _runtime_lock(candidate)
    runtime_entries = tuple(item for item in entries if item.path.startswith("env/"))
    python_entry = next((item for item in runtime_entries
                         if item.path == RUNTIME_PYTHON.as_posix()), None)
    if (python_entry is None or not python_entry.mode & 0o111
            or python_entry.sha256 != lock["python_sha256"]
            or tree_hash(runtime_entries) != lock["runtime_tree_hash"]):
        raise BuildBlocked("frozen runtime bytes drifted from requirements.lock")
    if any(item.path.endswith(".pth") or "/__pycache__/" in "/" + item.path
           or item.path.endswith((".pyc", ".pyo")) for item in runtime_entries):
        raise BuildBlocked("runtime contains executable path hooks or bytecode cache")
    review_key = next((item for item in entries
                       if item.path == REVIEW_VERIFIER_KEY.as_posix()), None)
    if (review_key is None
            or review_key.sha256 != source["review_verifier"]["sha256"]
            or review_key.size != source["review_verifier"]["size"]):
        raise BuildBlocked("embedded review verifier public key drifted")
    if repo is not None or reviewed_commit is not None:
        if repo is None or reviewed_commit is None:
            raise BuildBlocked("repo and reviewed_commit must be supplied together")
        commit = _exact_commit(repo, reviewed_commit)
        if source["reviewed_commit"] != commit:
            raise BuildBlocked("candidate reviewed commit does not match requested commit")
        expected = _git_entries(repo, commit)
        observed = source["entries"]
        compact = [{key: item[key] for key in ("git_path", "candidate_path", "git_mode", "git_blob")}
                   for item in observed if isinstance(item, dict)
                   and all(key in item for key in ("git_path", "candidate_path", "git_mode", "git_blob"))]
        if compact != list(expected) or len(compact) != len(observed):
            raise BuildBlocked("candidate source manifest differs from reviewed Git tree")
        by_path = {item.path: item for item in entries}
        for item in observed:
            actual = by_path.get(item["candidate_path"])
            if (actual is None or actual.sha256 != item.get("sha256")
                    or actual.size != item.get("size")
                    or actual.mode != item.get("candidate_mode")):
                raise BuildBlocked("candidate source byte differs from reviewed Git blob")
    # Full release-policy/bootstrap/runtime checks are centralized here.
    from abcr.control.release import _material_evidence
    evidence = _material_evidence(candidate, runtime_root="env",
                                  lock_path="requirements.lock",
                                  service_config_path="configs/control/service-topology-v1.json")
    return {"ok": True, "status": "BLOCKED",
            "blocking_gate": "SIGNED_VERIFICATION_REQUIRED",
            "reviewed_commit": source["reviewed_commit"],
            "candidate_tree_hash": tree_hash(entries),
            "runtime_tree_hash": evidence.runtime_digest,
            "resource_mirrors": source["resource_mirrors"],
            "file_count": len(entries)}


def _decode_attestation(path: Path) -> VerificationAttestation:
    document = _strict_json(path)
    raw = document.get("attestation") if isinstance(document.get("attestation"), dict) else document
    fields = {"mission_id", "fencing_token", "base_tree_hash", "candidate_tree_hash",
              "profile_hash", "oracle_set_hash", "changed_paths", "verdict",
              "verified_at", "attestation_hash", "isolation", "sealed"}
    if set(raw) != fields or not isinstance(raw["changed_paths"], list):
        raise BuildBlocked("verification attestation shape is invalid")
    try:
        return VerificationAttestation(**{**raw, "changed_paths": tuple(raw["changed_paths"])})
    except TypeError as exc:
        raise BuildBlocked("verification attestation values are invalid") from exc


def _all_service_payloads(candidate: Path) -> dict[str, dict]:
    topology = _strict_json(candidate / "configs/control/service-topology-v1.json")
    services = topology.get("services")
    if not isinstance(services, list) or len(services) != 12:
        raise BuildBlocked("reviewed topology must declare exactly twelve services")
    result: dict[str, dict] = {}
    for item in services:
        if not isinstance(item, dict) or not isinstance(item.get("module"), str):
            raise BuildBlocked("reviewed topology service is incomplete")
        if item["module"] in result:
            raise BuildBlocked("reviewed topology contains duplicate service modules")
        result[item["module"]] = {}
    return result


def finalize_release(*, candidate: Path, attestation_path: Path,
                     verifier_public_key: Path, staging_root: Path,
                     repo: Path, reviewed_commit: str) -> dict[str, Any]:
    candidate = Path(candidate)
    doctor = doctor_candidate(candidate, repo=repo, reviewed_commit=reviewed_commit)
    embedded_key = candidate / REVIEW_VERIFIER_KEY
    supplied_key = Path(verifier_public_key)
    # A byte-identical external copy is accepted as an explicit human input,
    # but cryptographic verification below always opens the immutable embedded
    # key that is already covered by the candidate tree hash.
    supplied_info = supplied_key.lstat()
    if (supplied_key.is_symlink() or not stat.S_ISREG(supplied_info.st_mode)
            or supplied_info.st_nlink != 1 or stat.S_IMODE(supplied_info.st_mode) & 0o022
            or sha256(supplied_key.read_bytes()) != sha256(embedded_key.read_bytes())):
        raise BuildBlocked("verifier key differs from candidate-embedded review key")
    attestation = _decode_attestation(Path(attestation_path))
    if (attestation.candidate_tree_hash != doctor["candidate_tree_hash"]
            or attestation.verdict != "PASS"):
        raise BuildBlocked("signed verification does not PASS this exact candidate")
    manifest = prepare_release(candidate, attestation,
                               verifier_public_key=embedded_key)
    destination, staged_hash = stage_release(
        candidate, Path(staging_root), manifest,
        service_payloads=_all_service_payloads(candidate))
    manifest_path = destination / "release-manifest.json"
    return {"ok": True, "status": "READY_FOR_HUMAN_ROOT_REVIEW_COPY",
            "reviewed_commit": _source_manifest(candidate)["reviewed_commit"],
            "candidate_tree_hash": manifest.tree_hash,
            "verification_hash": manifest.verification_hash,
            "release_id": manifest.release_id, "staging_path": str(destination),
            "staged_tree_hash": staged_hash,
            "release_manifest_sha256": sha256(manifest_path.read_bytes()),
            "services": sorted(_all_service_payloads(candidate)),
            "next_gate": "HUMAN_COMPARE_AND_ROOT_OWNED_REVIEW_COPY"}


def doctor_release(release: Path, *, attestation_path: Path,
                   verifier_public_key: Path, repo: Path,
                   reviewed_commit: str) -> dict[str, Any]:
    release = Path(release)
    manifest_path = release / "release-manifest.json"
    manifest = _strict_json(manifest_path)
    if manifest_path.read_bytes() != _canonical(manifest):
        raise BuildBlocked("release manifest is not canonical JSON")
    fields = ("tree_hash", "runtime_digest", "lock_hash",
              "service_config_hash", "verification_hash")
    core = {field: manifest.get(field) for field in fields}
    if (any(not isinstance(value, str) or HEX64.fullmatch(value) is None
            for value in core.values())
            or manifest.get("release_id") != "REL-" + sha256(core)):
        raise BuildBlocked("release manifest identity is invalid")
    observed = sorted(
        (asdict(item) for item in scan_tree(release)
         if item.path != "release-manifest.json"),
        key=lambda item: item["path"])
    if manifest.get("tree_entries") != observed or tree_hash(
            TreeEntry(**item) for item in observed) != manifest["tree_hash"]:
        raise BuildBlocked("release manifest does not describe exact staged bytes")
    payloads = manifest.get("service_payloads")
    topology = _strict_json(release / "configs/control/service-topology-v1.json")
    modules = {item["module"] for item in topology.get("services", [])
               if isinstance(item, dict) and isinstance(item.get("module"), str)}
    if not isinstance(payloads, dict) or set(payloads) != modules or len(modules) != 12:
        raise BuildBlocked("release manifest lacks the exact twelve service payloads")
    declared = {item["path"]: item for item in observed}
    for module, payload in payloads.items():
        if not isinstance(payload, dict) or payload.get("module") != module:
            raise BuildBlocked("release service payload identity is invalid")
        paths = payload.get("payload_files")
        if not isinstance(paths, list) or any(path not in declared for path in paths):
            raise BuildBlocked("release service payload references undeclared bytes")
        if payload.get("payload_tree_hash") != sha256([declared[path] for path in sorted(paths)]):
            raise BuildBlocked("release service payload tree hash is invalid")
    attestation = _decode_attestation(Path(attestation_path))
    if (attestation.attestation_hash != manifest["verification_hash"]
            or attestation.candidate_tree_hash != manifest["tree_hash"]):
        raise BuildBlocked("release manifest is not bound to supplied verification")
    source = _source_manifest(release)
    _verify_source_export(release, source, (TreeEntry(**item) for item in observed))
    embedded_key = release / REVIEW_VERIFIER_KEY
    supplied_key = Path(verifier_public_key)
    supplied_info = supplied_key.lstat()
    if (supplied_key.is_symlink() or not stat.S_ISREG(supplied_info.st_mode)
            or supplied_info.st_nlink != 1 or stat.S_IMODE(supplied_info.st_mode) & 0o022
            or sha256(supplied_key.read_bytes()) != source["review_verifier"]["sha256"]
            or sha256(embedded_key.read_bytes()) != source["review_verifier"]["sha256"]):
        raise BuildBlocked("release verification key is not the embedded reviewed key")
    # Re-run cryptographic verification and all material-policy checks against
    # the staged bytes (manifest excluded by the ReleaseManifest tree).  Only
    # the manifest-bound embedded key is used for the signature decision.
    from abcr.control.verifier import verify_verification_attestation
    ok, reason = verify_verification_attestation(attestation, public_key=embedded_key)
    if not ok:
        raise BuildBlocked(f"release verification signature rejected: {reason}")
    if source["reviewed_commit"] != _exact_commit(repo, reviewed_commit):
        raise BuildBlocked("release source commit differs from reviewed commit")
    from abcr.control.release_policy import enforce_release_content_policy
    enforce_release_content_policy(release, scan_tree(release))
    return {"ok": True, "status": "READY_FOR_HUMAN_ROOT_REVIEW_COPY",
            "reviewed_commit": source["reviewed_commit"],
            "release_id": manifest["release_id"],
            "candidate_tree_hash": manifest["tree_hash"],
            "verification_hash": manifest["verification_hash"],
            "release_manifest_sha256": sha256(manifest_path.read_bytes()),
            "staged_tree_hash": tree_hash(scan_tree(release)),
            "services": sorted(modules)}


def approve_authority_draft(draft_path: Path, output: Path, *,
                            human_reviewed: bool) -> dict[str, Any]:
    """Canonicalize one compared genesis draft after an explicit human act.

    This helper cannot grant authority: root must still install its output at
    the single fixed trust path.  It only removes error-prone hand editing and
    hash arithmetic after the human has compared the commit/release/tree/TCB
    fields displayed by ``--authority-draft``.
    """
    if human_reviewed is not True:
        raise BuildBlocked("authority approval requires explicit --human-reviewed")
    draft = _strict_json(Path(draft_path))
    if (set(draft) != GENESIS_AUTHORITY_FIELDS
            or draft.get("schema_version") != 1
            or draft.get("ceremony") != "abcr-human-root-genesis-v1"
            or draft.get("human_approved") is not False
            or HEX40.fullmatch(str(draft.get("reviewed_commit"))) is None
            or RELEASE_ID.fullmatch(str(draft.get("release_id"))) is None
            or any(HEX64.fullmatch(str(draft.get(name))) is None for name in (
                "authority_sha256", "policy_sha256", "release_manifest_sha256",
                "source_tree_hash", "expected_receipt_id"))
            or not isinstance(draft.get("tcb"), dict)):
        raise BuildBlocked("genesis authority draft is incomplete or already approved")
    original_core = {key: value for key, value in draft.items() if key != "authority_id"}
    if draft.get("authority_id") != sha256(original_core):
        raise BuildBlocked("genesis authority draft identity is invalid")
    _validate_authority_release_binding(draft)
    core = {**original_core, "human_approved": True}
    approved = {**core, "authority_id": sha256(core)}
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise BuildBlocked("approved authority output must not already exist")
    _write_regular(output, _canonical(approved), 0o444)
    return {"ok": True, "status": "READY_FOR_ROOT_AUTHORITY_INSTALL",
            "authority_id": approved["authority_id"],
            "reviewed_commit": approved["reviewed_commit"],
            "release_id": approved["release_id"], "output": str(output),
            "next_gate": "ROOT_INSTALL_EXACT_BYTES_AT_FIXED_AUTHORITY_PATH"}


def _validate_authority_release_binding(draft: dict[str, Any]) -> None:
    """Re-derive the draft's commit/release/tree identity from reviewed bytes.

    Approval is a canonicalization aid, not an alternate authority channel.
    In particular, a self-consistent draft that merely *claims* commit B must
    not be approvable for a release exported from commit A.
    """
    release_id = draft["release_id"]
    raw_path = draft.get("reviewed_release_path")
    if not isinstance(raw_path, str):
        raise BuildBlocked("genesis authority reviewed release path is invalid")
    expected_path = GENESIS_REVIEW_ROOT / release_id
    release = Path(raw_path)
    try:
        resolved = release.resolve(strict=True)
    except OSError as exc:
        raise BuildBlocked("genesis authority reviewed release is unavailable") from exc
    if release != expected_path or resolved != expected_path or release.is_symlink():
        raise BuildBlocked("genesis authority is not bound to the fixed reviewed release")
    try:
        all_entries = scan_tree(release)
    except ContractError as exc:
        raise BuildBlocked("genesis authority reviewed release tree is unsafe") from exc
    manifest_path = release / "release-manifest.json"
    manifest = _strict_json(manifest_path)
    if manifest_path.read_bytes() != _canonical(manifest):
        raise BuildBlocked("genesis authority release manifest is not canonical")
    core_names = ("tree_hash", "runtime_digest", "lock_hash",
                  "service_config_hash", "verification_hash")
    core = {name: manifest.get(name) for name in core_names}
    if (any(not isinstance(value, str) or HEX64.fullmatch(value) is None
            for value in core.values())
            or manifest.get("release_id") != "REL-" + sha256(core)
            or manifest["release_id"] != release_id):
        raise BuildBlocked("genesis authority release manifest identity is invalid")
    candidate_entries = tuple(sorted(
        (item for item in all_entries if item.path != "release-manifest.json"),
        key=lambda item: item.path))
    declared = [asdict(item) for item in candidate_entries]
    if (manifest.get("tree_entries") != declared
            or manifest.get("tree_hash") != tree_hash(candidate_entries)):
        raise BuildBlocked("genesis authority release manifest does not bind candidate tree")
    source = _source_manifest(release)
    _verify_source_export(release, source, candidate_entries)
    if (draft.get("reviewed_commit") != source["reviewed_commit"]
            or draft.get("release_manifest_sha256") != sha256(manifest_path.read_bytes())
            or draft.get("source_tree_hash") != tree_hash(all_entries)):
        raise BuildBlocked(
            "genesis authority draft differs from reviewed source/release/tree identity")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_reviewed_runtime.py")
    sub = parser.add_subparsers(dest="mode", required=True)

    build = sub.add_parser("build")
    build.add_argument("--repo", type=Path, required=True)
    build.add_argument("--reviewed-commit", required=True)
    build.add_argument("--python-home", type=Path, required=True)
    build.add_argument("--site-packages", type=Path, required=True)
    build.add_argument("--review-verifier-public-key", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)

    candidate = sub.add_parser("doctor-candidate")
    candidate.add_argument("--candidate", type=Path, required=True)
    candidate.add_argument("--repo", type=Path)
    candidate.add_argument("--reviewed-commit")

    finalize = sub.add_parser("finalize")
    finalize.add_argument("--candidate", type=Path, required=True)
    finalize.add_argument("--attestation", type=Path, required=True)
    finalize.add_argument("--verifier-public-key", type=Path, required=True)
    finalize.add_argument("--staging-root", type=Path, required=True)
    finalize.add_argument("--repo", type=Path, required=True)
    finalize.add_argument("--reviewed-commit", required=True)

    release = sub.add_parser("doctor-release")
    release.add_argument("--release", type=Path, required=True)
    release.add_argument("--attestation", type=Path, required=True)
    release.add_argument("--verifier-public-key", type=Path, required=True)
    release.add_argument("--repo", type=Path, required=True)
    release.add_argument("--reviewed-commit", required=True)

    approve = sub.add_parser("approve-authority")
    approve.add_argument("--draft", type=Path, required=True)
    approve.add_argument("--output", type=Path, required=True)
    approve.add_argument("--human-reviewed", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.mode == "build":
            result = build_candidate(repo=args.repo, reviewed_commit=args.reviewed_commit,
                                     python_home=args.python_home,
                                     site_packages=args.site_packages,
                                     review_verifier_public_key=args.review_verifier_public_key,
                                     output=args.output)
        elif args.mode == "doctor-candidate":
            result = doctor_candidate(args.candidate, repo=args.repo,
                                      reviewed_commit=args.reviewed_commit)
        elif args.mode == "finalize":
            result = finalize_release(candidate=args.candidate,
                                      attestation_path=args.attestation,
                                      verifier_public_key=args.verifier_public_key,
                                      staging_root=args.staging_root, repo=args.repo,
                                      reviewed_commit=args.reviewed_commit)
        elif args.mode == "doctor-release":
            result = doctor_release(args.release, attestation_path=args.attestation,
                                    verifier_public_key=args.verifier_public_key,
                                    repo=args.repo, reviewed_commit=args.reviewed_commit)
        else:
            result = approve_authority_draft(args.draft, args.output,
                                             human_reviewed=args.human_reviewed)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return EX_CONFIG if result.get("status") == "BLOCKED" else 0
    except Exception as exc:
        code = exc.code if isinstance(exc, ContractError) else type(exc).__name__
        print(json.dumps({"ok": False, "status": "BLOCKED", "error_code": code,
                          "message": str(exc)}, ensure_ascii=False,
                         sort_keys=True), file=sys.stderr)
        return EX_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
