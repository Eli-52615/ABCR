#!/usr/bin/env python3
"""One-time, human/root genesis for the otherwise receipt-gated ABCR runtime.

This is not a second installer.  It may establish exactly one authority-bound
seal-broker LKG using a receipt marked ``genesis_pending``.  The normal runtime
installer rejects that marker.  The LKG broker must then confirm the same
release bytes before this ceremony removes the marker and immediately invokes
the ordinary receipt-gated installer.  No launchd job is loaded or started.

The root trust assumption is finite and explicit: a human installs one
root-owned authority statement at the fixed path below after reviewing the Git
commit, canonical release manifest, and the hashes of the listed bootstrap TCB
bytes.  A checkout, branch name, or caller-selected path is never authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable


AUTHORITY_SHA = "40fd5fb21ff33d7da84648562c6dc12d68f15444dfea60379132af820510d0d1"
POLICY_SHA = "22c93bc8d45f391d701df58df98942468708981b51e5f7116c960178d1ba4e3b"
CEREMONY = "abcr-human-root-genesis-v1"
AUTHORITY_PATH = Path("/Library/Application Support/ABCR-Trust/genesis-authority-v1.json")
COMPLETION_PATH = Path("/Library/Application Support/ABCR-Trust/genesis-completed-v1.json")
REVIEW_ROOT = Path("/Library/Application Support/ABCR-Genesis/reviewed")
RELEASE_ROOT = Path("/Users/superagent/.abcr/releases")
RECEIPT_ROOT = Path("/Library/Application Support/ABCR-Attest/release-receipts")
COMPONENT_ROOT = Path("/Library/Application Support/ABCR-Bootstrap/components")
SELECTOR_PATH = Path("/usr/local/libexec/abcr-bootstrap-selector")
ACTIVE_PATH = Path("/Users/superagent/.abcr/active.json")
POLICY_RELPATH = "ops/install/genesis-authority-v1.json"
REVIEWED_SOURCE_RELPATH = "reviewed-source.json"
GENESIS_RELPATH = "scripts/bootstrap_abcr_genesis.py"
SELECTOR_RELPATH = "scripts/abcr-bootstrap-selector"
INSTALLER_RELPATH = "scripts/install_abcr_runtime.py"
LAUNCHER_RELPATH = "scripts/abcr-launch"
PYTHON_RELPATH = "env/bin/python"
BROKER_MODULE = "abcr.control.seal_broker"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
RELEASE_ID = re.compile(r"^REL-[0-9a-f]{64}$")
EX_CONFIG = 78

AUTHORITY_FIELDS = {
    "schema_version", "ceremony", "authority_sha256", "policy_sha256",
    "authority_id", "human_approved", "reviewed_commit",
    "reviewed_release_path", "release_id", "release_manifest_sha256",
    "source_tree_hash", "broker_seal_nonce", "expected_receipt_id", "tcb",
}
TCB_FIELDS = {
    "genesis_script", "stable_selector", "runtime_installer", "launcher",
    "python", "broker_module", "broker_payload_tree_hash",
}
RECEIPT_FIELDS = {
    "receipt_id", "operation", "nonce", "object_id", "tree_hash",
    "sealed_tree_hash", "sealed_path", "created_at",
}


class GenesisBlocked(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: bytes | Any) -> str:
    raw = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GenesisBlocked("duplicate JSON key")
        result[key] = value
    return result


def _safe_relpath(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise GenesisBlocked("invalid release relative path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise GenesisBlocked("invalid release relative path")
    return pure.as_posix()


def _read_regular(path: Path, *, owner_uid: int | None = None,
                  exact_mode: int | None = None,
                  max_bytes: int = 128 * 1024 * 1024) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise GenesisBlocked(f"trusted file unavailable: {path}") from exc
    try:
        before = os.fstat(fd)
        mode = stat.S_IMODE(before.st_mode)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or (owner_uid is not None and before.st_uid != owner_uid)
                or mode & 0o022 or (exact_mode is not None and mode != exact_mode)
                or before.st_size > max_bytes):
            raise GenesisBlocked(f"unsafe trusted file: {path}")
        chunks: list[bytes] = []
        remaining = before.st_size + 1
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk); remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_nlink,
                                 item.st_uid, item.st_gid, stat.S_IMODE(item.st_mode))
        if len(raw) != before.st_size or identity(before) != identity(after):
            raise GenesisBlocked(f"trusted file changed while reading: {path}")
        return raw
    finally:
        os.close(fd)


def _parse_json(raw: bytes, *, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_unique,
                           parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise GenesisBlocked(f"invalid trusted JSON: {path}") from exc
    if not isinstance(value, dict):
        raise GenesisBlocked(f"trusted JSON is not an object: {path}")
    return value


def _read_json(path: Path, *, owner_uid: int | None = None,
               exact_mode: int | None = None, canonical: bool = False,
               max_bytes: int = 4 * 1024 * 1024) -> dict[str, Any]:
    raw = _read_regular(path, owner_uid=owner_uid, exact_mode=exact_mode,
                        max_bytes=max_bytes)
    value = _parse_json(raw, path=path)
    if canonical and raw != _canonical(value) + b"\n":
        raise GenesisBlocked(f"trusted JSON is not canonical: {path}")
    return value


def _secure_dir(path: Path, *, owner_uid: int, exact_mode: int | None = None) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise GenesisBlocked(f"trusted directory unavailable: {path}") from exc
    mode = stat.S_IMODE(info.st_mode)
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != owner_uid or mode & 0o022
            or (exact_mode is not None and mode != exact_mode)):
        raise GenesisBlocked(f"unsafe trusted directory: {path}")
    return info


def _scan_tree(root: Path, *, owner_uid: int | None = None) -> list[dict[str, Any]]:
    root_info = root.lstat()
    if (not stat.S_ISDIR(root_info.st_mode) or root.is_symlink()
            or (owner_uid is not None and root_info.st_uid != owner_uid)
            or stat.S_IMODE(root_info.st_mode) & 0o022):
        raise GenesisBlocked("reviewed release root is unsafe")
    entries: list[dict[str, Any]] = []
    inodes: set[tuple[int, int]] = set()
    for dir_name, dir_names, file_names in os.walk(root, followlinks=False):
        current = Path(dir_name)
        info = current.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_dev != root_info.st_dev
                or (owner_uid is not None and info.st_uid != owner_uid)
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise GenesisBlocked("reviewed release contains an unsafe directory")
        for name in sorted(dir_names):
            child = current / name
            child_info = child.lstat()
            if (child.is_symlink() or not stat.S_ISDIR(child_info.st_mode)
                    or child_info.st_dev != root_info.st_dev):
                raise GenesisBlocked("reviewed release crosses a mount or contains a symlink")
        for name in sorted(file_names):
            child = current / name
            child_info = child.lstat()
            inode = (child_info.st_dev, child_info.st_ino)
            if (child.is_symlink() or not stat.S_ISREG(child_info.st_mode)
                    or child_info.st_nlink != 1 or child_info.st_dev != root_info.st_dev
                    or inode in inodes
                    or (owner_uid is not None and child_info.st_uid != owner_uid)
                    or stat.S_IMODE(child_info.st_mode) & 0o022):
                raise GenesisBlocked("reviewed release contains an unsafe file")
            inodes.add(inode)
            raw = _read_regular(child, owner_uid=owner_uid)
            entries.append({"path": child.relative_to(root).as_posix(),
                            "mode": stat.S_IMODE(child_info.st_mode),
                            "size": len(raw), "sha256": _digest(raw)})
    return sorted(entries, key=lambda item: item["path"])


def _manifest(source: Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    manifest_path = source / "release-manifest.json"
    raw = _read_regular(manifest_path)
    value = _parse_json(raw, path=manifest_path)
    if raw != _canonical(value) + b"\n":
        raise GenesisBlocked("release manifest must be canonical JSON")
    release_id = value.get("release_id")
    core_fields = ("tree_hash", "runtime_digest", "lock_hash",
                   "service_config_hash", "verification_hash")
    if (not isinstance(release_id, str) or RELEASE_ID.fullmatch(release_id) is None
            or any(not isinstance(value.get(field), str) or HEX64.fullmatch(value[field]) is None
                   for field in core_fields)
            or release_id != "REL-" + _digest({field: value[field] for field in core_fields})):
        raise GenesisBlocked("release manifest identity is invalid")
    declared = value.get("tree_entries")
    actual = [item for item in entries if item["path"] != "release-manifest.json"]
    if (not isinstance(declared, list) or declared != actual
            or any(not isinstance(item, dict)
                   or set(item) != {"path", "mode", "size", "sha256"}
                   for item in declared)):
        raise GenesisBlocked("release manifest tree does not match reviewed bytes")
    # The release id binds this field, but that is useless if the field itself
    # is allowed to be a caller-selected digest.  Recompute the exact candidate
    # tree (the release manifest is the sole derived/excluded file), matching
    # ``abcr.control.worktree.tree_hash`` / the release finalizer.
    if value["tree_hash"] != _digest(actual):
        raise GenesisBlocked("release manifest tree hash does not bind reviewed bytes")
    return value


def _reviewed_source_commit(source: Path, manifest: dict[str, Any],
                            entries: dict[str, dict[str, Any]]) -> str:
    """Derive commit identity only from the manifest-bound source export.

    ``reviewed-source.json`` is produced from the exact Git commit before the
    candidate is tested.  It is itself a member of ``manifest.tree_entries``;
    consequently its bytes are covered by the candidate tree hash, signed
    verifier attestation, release id and the genesis source-tree hash.  A CLI
    string is never an authority source.
    """
    source_record = entries.get(REVIEWED_SOURCE_RELPATH)
    declared = {item["path"]: item for item in manifest["tree_entries"]}
    if source_record is None or declared.get(REVIEWED_SOURCE_RELPATH) != source_record:
        raise GenesisBlocked("release manifest lacks the reviewed source identity")
    path = source / REVIEWED_SOURCE_RELPATH
    raw = _read_regular(path)
    value = _parse_json(raw, path=path)
    if raw != _canonical(value) + b"\n":
        raise GenesisBlocked("reviewed source identity must be canonical JSON")
    expected_fields = {
        "schema_version", "kind", "reviewed_commit", "builder_policy_sha256",
        "entries", "review_verifier", "resource_mirrors",
    }
    commit = value.get("reviewed_commit")
    if (set(value) != expected_fields or value.get("schema_version") != 1
            or value.get("kind") != "abcr-reviewed-source-export"
            or not isinstance(commit, str) or COMMIT.fullmatch(commit) is None
            or not isinstance(value.get("entries"), list) or not value["entries"]
            or not isinstance(value.get("review_verifier"), dict)
            or not isinstance(value.get("resource_mirrors"), list)):
        raise GenesisBlocked("reviewed source identity is invalid")

    # Bind every Git-export record to an actual member of the signed candidate
    # tree.  Finalization additionally compares the Git object ids to the
    # reviewed repository; genesis intentionally needs no checkout or Git.
    record_fields = {
        "git_path", "candidate_path", "git_mode", "git_blob", "sha256",
        "size", "candidate_mode",
    }
    seen_git: set[str] = set()
    seen_candidate: set[str] = set()
    for record in value["entries"]:
        if not isinstance(record, dict) or set(record) != record_fields:
            raise GenesisBlocked("reviewed source export record is invalid")
        git_path = _safe_relpath(record["git_path"])
        candidate_path = _safe_relpath(record["candidate_path"])
        git_mode = record["git_mode"]
        expected_mode = 0o555 if git_mode == "100755" else 0o444
        actual = declared.get(candidate_path)
        if (git_path in seen_git or candidate_path in seen_candidate
                or git_mode not in {"100644", "100755"}
                or not isinstance(record["git_blob"], str)
                or COMMIT.fullmatch(record["git_blob"]) is None
                or not isinstance(record["sha256"], str)
                or HEX64.fullmatch(record["sha256"]) is None
                or type(record["size"]) is not int or record["size"] < 0
                or record["candidate_mode"] != expected_mode
                or actual is None
                or {key: actual[key] for key in ("mode", "size", "sha256")} != {
                    "mode": record["candidate_mode"], "size": record["size"],
                    "sha256": record["sha256"],
                }):
            raise GenesisBlocked("reviewed source export is not bound to candidate bytes")
        seen_git.add(git_path)
        seen_candidate.add(candidate_path)
    return commit


def _file_record(entries: dict[str, dict[str, Any]], relative: str) -> dict[str, Any]:
    try:
        item = entries[_safe_relpath(relative)]
    except KeyError as exc:
        raise GenesisBlocked(f"reviewed release lacks TCB file: {relative}") from exc
    return {"path": relative, "sha256": item["sha256"]}


def build_authority_statement(source: Path, reviewed_commit: str | None = None, *,
                              human_approved: bool) -> dict[str, Any]:
    """Build a read-only review draft.  The output itself grants no authority.

    ``reviewed_commit`` is retained only as an optional human comparison
    assertion.  The authority-bearing value is always derived from the frozen
    release's manifest-bound ``reviewed-source.json``.
    """
    source = Path(source).resolve()
    entries = _scan_tree(source)
    manifest = _manifest(source, entries)
    release_id = manifest["release_id"]
    if source != REVIEW_ROOT / release_id:
        raise GenesisBlocked("reviewed release must use the fixed root/release-id path")
    by_path = {item["path"]: item for item in entries}
    derived_commit = _reviewed_source_commit(source, manifest, by_path)
    if reviewed_commit is not None:
        if (not isinstance(reviewed_commit, str)
                or COMMIT.fullmatch(reviewed_commit) is None):
            raise GenesisBlocked(
                "reviewed commit assertion must be an exact 40/64 character Git object id")
        if reviewed_commit != derived_commit:
            raise GenesisBlocked(
                "caller reviewed commit assertion differs from reviewed-source.json")
    policy = _file_record(by_path, POLICY_RELPATH)
    if policy["sha256"] != POLICY_SHA:
        raise GenesisBlocked("genesis policy bytes do not match the fixed policy")
    payloads = manifest.get("service_payloads")
    payload = payloads.get(BROKER_MODULE) if isinstance(payloads, dict) else None
    if not isinstance(payload, dict):
        raise GenesisBlocked("release manifest lacks the seal-broker payload")
    module_path = payload.get("module_relpath")
    payload_files = payload.get("payload_files")
    if (not isinstance(module_path, str) or not isinstance(payload_files, list)
            or not payload_files or any(not isinstance(item, str) for item in payload_files)):
        raise GenesisBlocked("seal-broker payload is incomplete")
    declared = {item["path"]: item for item in manifest["tree_entries"]}
    try:
        payload_entries = sorted((declared[_safe_relpath(item)] for item in payload_files),
                                 key=lambda item: item["path"])
    except KeyError as exc:
        raise GenesisBlocked("seal-broker payload references undeclared bytes") from exc
    payload_hash = _digest(payload_entries)
    if payload_hash != payload.get("payload_tree_hash"):
        raise GenesisBlocked("seal-broker payload tree hash is invalid")
    tcb = {
        "genesis_script": _file_record(by_path, GENESIS_RELPATH),
        "stable_selector": _file_record(by_path, SELECTOR_RELPATH),
        "runtime_installer": _file_record(by_path, INSTALLER_RELPATH),
        "launcher": _file_record(by_path, LAUNCHER_RELPATH),
        "python": _file_record(by_path, PYTHON_RELPATH),
        "broker_module": _file_record(by_path, module_path),
        "broker_payload_tree_hash": payload_hash,
    }
    bootstrap = _read_json(source / "ops/install/bootstrap-v1.json")
    if bootstrap.get("stable_selector_sha256") != tcb["stable_selector"]["sha256"]:
        raise GenesisBlocked("bootstrap manifest does not pin the reviewed selector")
    source_hash = _digest(entries)
    nonce = f"genesis:{AUTHORITY_SHA}:{derived_commit}:{release_id}"
    receipt_core = {"operation": "seal_release", "nonce": nonce,
                    "tree_hash": source_hash, "object_id": release_id}
    core: dict[str, Any] = {
        "schema_version": 1, "ceremony": CEREMONY,
        "authority_sha256": AUTHORITY_SHA, "policy_sha256": POLICY_SHA,
        "human_approved": human_approved, "reviewed_commit": derived_commit,
        "reviewed_release_path": str(source), "release_id": release_id,
        "release_manifest_sha256": by_path["release-manifest.json"]["sha256"],
        "source_tree_hash": source_hash, "broker_seal_nonce": nonce,
        "expected_receipt_id": _digest(receipt_core), "tcb": tcb,
    }
    return {**core, "authority_id": _digest(core)}


def load_authority(expected_id: str, *, authority_path: Path = AUTHORITY_PATH,
                   owner_uid: int = 0) -> dict[str, Any]:
    if HEX64.fullmatch(expected_id) is None:
        raise GenesisBlocked("exact genesis authority id is required")
    authority = _read_json(authority_path, owner_uid=owner_uid,
                           exact_mode=0o444, canonical=True)
    if (set(authority) != AUTHORITY_FIELDS or authority.get("authority_id") != expected_id
            or authority.get("schema_version") != 1 or authority.get("ceremony") != CEREMONY
            or authority.get("authority_sha256") != AUTHORITY_SHA
            or authority.get("policy_sha256") != POLICY_SHA
            or authority.get("human_approved") is not True
            or set(authority.get("tcb", {})) != TCB_FIELDS):
        raise GenesisBlocked("root genesis authority statement is invalid")
    core = {key: value for key, value in authority.items() if key != "authority_id"}
    if _digest(core) != expected_id:
        raise GenesisBlocked("genesis authority id does not bind its statement")
    source = Path(authority["reviewed_release_path"])
    expected = build_authority_statement(source, authority["reviewed_commit"],
                                         human_approved=True)
    if expected != authority:
        raise GenesisBlocked("reviewed release bytes drifted from human authority")
    _scan_tree(source, owner_uid=owner_uid)
    return authority


def _atomic_bytes(path: Path, raw: bytes, *, owner_uid: int, group_gid: int,
                  mode: int) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise GenesisBlocked(f"unsafe output target: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.chown(temporary, owner_uid, group_gid); os.chmod(temporary, mode)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _mkdir(path: Path, *, owner_uid: int, group_gid: int, mode: int) -> None:
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if (path.is_symlink() or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != owner_uid or info.st_gid != group_gid
                or stat.S_IMODE(info.st_mode) != mode):
            raise GenesisBlocked(f"unsafe existing genesis directory: {path}")
        return
    path.mkdir(mode=mode)
    os.chown(path, owner_uid, group_gid); os.chmod(path, mode)


def _apply_release_policy(root: Path, *, owner_uid: int, release_gid: int) -> None:
    for dir_name, dir_names, file_names in os.walk(root, topdown=False, followlinks=False):
        current = Path(dir_name)
        for name in file_names:
            child = current / name
            info = child.lstat()
            if child.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise GenesisBlocked("copied release contains an unsafe file")
            executable = bool(stat.S_IMODE(info.st_mode) & 0o111)
            os.chown(child, owner_uid, release_gid)
            os.chmod(child, 0o550 if executable else 0o440)
        for name in dir_names:
            child = current / name
            if child.is_symlink() or not child.is_dir():
                raise GenesisBlocked("copied release contains an unsafe directory")
            os.chown(child, owner_uid, release_gid); os.chmod(child, 0o550)
    os.chown(root, owner_uid, release_gid); os.chmod(root, 0o550)


def stage_reviewed_release(authority: dict[str, Any], *, release_root: Path,
                           owner_uid: int, release_gid: int) -> Path:
    source = Path(authority["reviewed_release_path"])
    final = release_root / authority["release_id"]
    if final.exists() or final.is_symlink():
        if final.is_symlink() or not final.is_dir():
            raise GenesisBlocked("existing genesis release target is unsafe")
        source_content = [(item["path"], item["size"], item["sha256"])
                          for item in _scan_tree(source, owner_uid=owner_uid)]
        final_content = [(item["path"], item["size"], item["sha256"])
                         for item in _scan_tree(final, owner_uid=owner_uid)]
        if source_content != final_content:
            raise GenesisBlocked("existing genesis release differs from reviewed bytes")
        return final
    temporary = release_root / f".{authority['release_id']}.genesis.tmp"
    if temporary.exists() or temporary.is_symlink():
        raise GenesisBlocked("stale genesis staging target requires human review")
    shutil.copytree(source, temporary, symlinks=True)
    try:
        copied = _scan_tree(temporary)
        expected = _scan_tree(source, owner_uid=owner_uid)
        if [(x["path"], x["size"], x["sha256"]) for x in copied] != [
                (x["path"], x["size"], x["sha256"]) for x in expected]:
            raise GenesisBlocked("genesis release copy drifted")
        _apply_release_policy(temporary, owner_uid=owner_uid, release_gid=release_gid)
        os.rename(temporary, final)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return final


def _receipt(authority: dict[str, Any], final: Path, *, pending: bool,
             owner_uid: int) -> dict[str, Any]:
    sealed_hash = _digest(_scan_tree(final, owner_uid=owner_uid))
    value: dict[str, Any] = {
        "receipt_id": authority["expected_receipt_id"], "operation": "seal_release",
        "nonce": authority["broker_seal_nonce"], "object_id": authority["release_id"],
        "tree_hash": authority["source_tree_hash"], "sealed_tree_hash": sealed_hash,
        "sealed_path": str(final),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
    }
    if pending:
        value["genesis_pending"] = {"authority_id": authority["authority_id"],
                                    "reviewed_commit": authority["reviewed_commit"]}
    return value


def ensure_pending_receipt(authority: dict[str, Any], final: Path, *, receipt_root: Path,
                           owner_uid: int, release_gid: int) -> dict[str, Any]:
    unexpected = [item for item in receipt_root.iterdir()
                  if item.name != f"{authority['expected_receipt_id']}.json"]
    if unexpected:
        raise GenesisBlocked("genesis is forbidden after any unrelated broker receipt exists")
    receipt_path = receipt_root / f"{authority['expected_receipt_id']}.json"
    expected_core = {"operation": "seal_release", "nonce": authority["broker_seal_nonce"],
                     "tree_hash": authority["source_tree_hash"],
                     "object_id": authority["release_id"]}
    if receipt_path.exists():
        value = _read_json(receipt_path, owner_uid=owner_uid, exact_mode=0o440,
                           canonical=True)
        core = {key: value.get(key) for key in expected_core}
        if (core != expected_core or value.get("receipt_id") != _digest(core)
                or value.get("sealed_path") != str(final)
                or value.get("sealed_tree_hash") != _digest(_scan_tree(final, owner_uid=owner_uid))
                or set(value) not in (RECEIPT_FIELDS, RECEIPT_FIELDS | {"genesis_pending"})):
            raise GenesisBlocked("existing genesis receipt conflicts with reviewed authority")
        return value
    value = _receipt(authority, final, pending=True, owner_uid=owner_uid)
    _atomic_bytes(receipt_path, _canonical(value) + b"\n", owner_uid=owner_uid,
                  group_gid=release_gid, mode=0o440)
    return value


def _broker_slot_record(authority: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    payload = manifest["service_payloads"][BROKER_MODULE]
    return {
        "schema_version": 1, "component": "seal-broker", "generation": 1,
        "release_id": authority["release_id"],
        "receipt_id": authority["expected_receipt_id"],
        "target_relpath": payload["module_relpath"],
        "target_sha256": payload["module_sha256"],
        "python_relpath": payload["python_relpath"],
        "python_sha256": payload["python_sha256"], "module": BROKER_MODULE,
        "payload_tree_hash": payload["payload_tree_hash"],
    }


def establish_broker_lkg(authority: dict[str, Any], final: Path, *,
                         component_root: Path, selector_path: Path,
                         owner_uid: int, wheel_gid: int,
                         selector_probe: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
                         ) -> None:
    selector_raw = _read_regular(final / SELECTOR_RELPATH, owner_uid=owner_uid)
    if _digest(selector_raw) != authority["tcb"]["stable_selector"]["sha256"]:
        raise GenesisBlocked("reviewed selector bytes drifted")
    if selector_path.exists() or selector_path.is_symlink():
        if (selector_path.is_symlink()
                or _digest(_read_regular(selector_path, owner_uid=owner_uid,
                                         exact_mode=0o555)) != _digest(selector_raw)):
            raise GenesisBlocked("existing outer selector is not the reviewed genesis selector")
    else:
        _atomic_bytes(selector_path, selector_raw, owner_uid=owner_uid,
                      group_gid=wheel_gid, mode=0o555)
    # manifest 内嵌全部树条目(真实 release 20,417 条、约 23 MiB),远超 4/8 MiB 的
    # 防呆上限——那个上限会让**任何真实 release** 在此被拒。同文件读运行时字节用的
    # 就是 128 MiB,这里取同一口径。
    manifest = _read_json(final / "release-manifest.json", owner_uid=owner_uid,
                          max_bytes=128 * 1024 * 1024,
                          exact_mode=0o440, canonical=True)
    record = _broker_slot_record(authority, manifest)
    pointer = {"schema_version": 1, "component": "seal-broker", "slot": "slot-a",
               "generation": 1, "probation": False}
    for component in ("launcher", "seal-broker", "test-controller"):
        root = component_root / component
        _mkdir(root, owner_uid=owner_uid, group_gid=wheel_gid, mode=0o755)
        for slot in ("slot-a", "slot-b"):
            _mkdir(root / slot, owner_uid=owner_uid, group_gid=wheel_gid, mode=0o555)
    broker_root = component_root / "seal-broker"
    for target, value in ((broker_root / "slot-a/slot.json", record),
                          (broker_root / "active-slot.json", pointer),
                          (broker_root / "last-known-good.json", pointer)):
        if target.exists():
            if _read_json(target, owner_uid=owner_uid, exact_mode=0o444,
                          canonical=True) != value:
                raise GenesisBlocked("existing broker LKG conflicts with reviewed authority")
        else:
            _atomic_bytes(target, _canonical(value) + b"\n", owner_uid=owner_uid,
                          group_gid=wheel_gid, mode=0o444)
    outcome = selector_probe([str(selector_path), "--resolve-only", "seal-broker"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, timeout=30, check=False,
                             env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    if outcome.returncode != 0:
        raise GenesisBlocked("reviewed selector could not resolve the genesis broker LKG")


def broker_confirm(authority: dict[str, Any], *, release_root: Path, receipt_root: Path,
                   owner_uid: int, release_gid: int) -> dict[str, Any]:
    """Run the actual LKG SealBroker primitive against the exact authority source."""
    from abcr.control.seal_broker import SealBroker

    source = Path(authority["reviewed_release_path"])
    policy = {"owner_uid": owner_uid, "group_gid": release_gid,
              "directory_mode": 0o550, "file_mode": 0o440,
              "executable_file_mode": 0o550}
    broker = SealBroker({"seal_release": release_root}, receipt_root,
                        source_roots={"seal_release": source.parent},
                        operation_policies={"seal_release": policy},
                        authority_uid=owner_uid, receipt_owner_uid=owner_uid,
                        receipt_group_gid=release_gid)
    return broker.seal_tree("seal_release", source,
                            nonce=authority["broker_seal_nonce"],
                            expected_tree_hash=authority["source_tree_hash"],
                            object_id=authority["release_id"])


def _run_lkg_broker_confirm(final: Path, authority: dict[str, Any]
                            ) -> dict[str, Any]:
    """Enter through the reviewed final runtime, not the caller's checkout."""
    # -B 必须显式给出:-I 隐含 -E,会让 env 里的 PYTHONDONTWRITEBYTECODE 失效,而
    # root 无视只读目录位;缺少 -B 时解释器启动就把 __pycache__ 写进封印树,随后
    # 所有全树校验 fail-closed 且不可重试。
    argv = [str(final / PYTHON_RELPATH), "-I", "-B", str(final / GENESIS_RELPATH),
            "--broker-confirm-only", authority["authority_id"], "--human-required"]
    outcome = subprocess.run(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, timeout=120, check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
             "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1", "LC_ALL": "C"})
    if outcome.returncode != 0:
        raise GenesisBlocked("genesis broker LKG confirmation process failed")
    try:
        response = json.loads(outcome.stdout)
    except json.JSONDecodeError as exc:
        raise GenesisBlocked("genesis broker LKG returned invalid JSON") from exc
    if (not isinstance(response, dict) or response.get("ok") is not True
            or not isinstance(response.get("receipt"), dict)):
        raise GenesisBlocked("genesis broker LKG rejected the release")
    return response["receipt"]


def _assert_broker_lkg(authority: dict[str, Any], *, final: Path,
                       component_root: Path, selector_path: Path,
                       receipt_root: Path, owner_uid: int) -> None:
    if Path(__file__).resolve() != final / GENESIS_RELPATH:
        raise GenesisBlocked("broker confirmation must execute inside the staged final release")
    if (_digest(_read_regular(selector_path, owner_uid=owner_uid, exact_mode=0o555))
            != authority["tcb"]["stable_selector"]["sha256"]):
        raise GenesisBlocked("broker confirmation selector is not the reviewed LKG selector")
    pointer = {"schema_version": 1, "component": "seal-broker", "slot": "slot-a",
               "generation": 1, "probation": False}
    broker_root = component_root / "seal-broker"
    for name in ("active-slot.json", "last-known-good.json"):
        if _read_json(broker_root / name, owner_uid=owner_uid,
                      exact_mode=0o444, canonical=True) != pointer:
            raise GenesisBlocked("broker confirmation has no exact genesis LKG")
    # manifest 内嵌全部树条目(真实 release 20,417 条、约 23 MiB),远超 4/8 MiB 的
    # 防呆上限——那个上限会让**任何真实 release** 在此被拒。同文件读运行时字节用的
    # 就是 128 MiB,这里取同一口径。
    manifest = _read_json(final / "release-manifest.json", owner_uid=owner_uid,
                          max_bytes=128 * 1024 * 1024,
                          exact_mode=0o440, canonical=True)
    if (_read_json(broker_root / "slot-a/slot.json", owner_uid=owner_uid,
                   exact_mode=0o444, canonical=True)
            != _broker_slot_record(authority, manifest)):
        raise GenesisBlocked("broker confirmation slot differs from reviewed release")
    pending = _read_json(
        receipt_root / f"{authority['expected_receipt_id']}.json",
        owner_uid=owner_uid, exact_mode=0o440, canonical=True)
    if set(pending) != RECEIPT_FIELDS | {"genesis_pending"}:
        raise GenesisBlocked("broker confirmation requires the pending receipt state")


def normalize_broker_receipt(authority: dict[str, Any], confirmed: dict[str, Any], *,
                             receipt_root: Path, owner_uid: int, release_gid: int) -> dict[str, Any]:
    path = receipt_root / f"{authority['expected_receipt_id']}.json"
    on_disk = _read_json(path, owner_uid=owner_uid, exact_mode=0o440, canonical=True)
    if confirmed != on_disk or set(on_disk) != RECEIPT_FIELDS | {"genesis_pending"}:
        raise GenesisBlocked("LKG broker did not confirm the exact pending genesis receipt")
    marker = on_disk["genesis_pending"]
    if marker != {"authority_id": authority["authority_id"],
                  "reviewed_commit": authority["reviewed_commit"]}:
        raise GenesisBlocked("pending receipt is not bound to the human authority")
    normal = {key: on_disk[key] for key in RECEIPT_FIELDS}
    _atomic_bytes(path, _canonical(normal) + b"\n", owner_uid=owner_uid,
                  group_gid=release_gid, mode=0o440)
    return normal


def _run_normal_installer(final: Path, authority: dict[str, Any]
                          ) -> subprocess.CompletedProcess[str]:
    # 同 _run_lkg_broker_confirm:root 子进程必须带 -B,防止启动期字节码缓存
    # 污染封印树。
    argv = [str(final / PYTHON_RELPATH), "-I", "-B", str(final / INSTALLER_RELPATH),
            "--install-reviewed", AUTHORITY_SHA,
            "--receipt-id", authority["expected_receipt_id"]]
    return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, timeout=600, check=False,
                          env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
                               "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1", "LC_ALL": "C"})


def prepare_genesis_roots(*, release_root: Path, receipt_root: Path,
                          component_root: Path, selector_path: Path,
                          completion_path: Path, owner_uid: int,
                          release_gid: int, wheel_gid: int) -> None:
    """Create only the finite leaf roots needed before the normal installer."""
    for parent in {release_root.parent.parent, receipt_root.parent.parent,
                   component_root.parent.parent, selector_path.parent.parent,
                   completion_path.parent}:
        info = parent.lstat()
        if (parent.is_symlink() or not stat.S_ISDIR(info.st_mode)
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise GenesisBlocked(f"unsafe genesis parent: {parent}")
    _mkdir(release_root.parent, owner_uid=owner_uid, group_gid=wheel_gid, mode=0o755)
    _mkdir(release_root, owner_uid=owner_uid, group_gid=release_gid, mode=0o750)
    _mkdir(receipt_root.parent, owner_uid=owner_uid, group_gid=wheel_gid, mode=0o755)
    _mkdir(receipt_root, owner_uid=owner_uid, group_gid=release_gid, mode=0o750)
    _mkdir(component_root.parent, owner_uid=owner_uid, group_gid=wheel_gid, mode=0o755)
    _mkdir(component_root, owner_uid=owner_uid, group_gid=wheel_gid, mode=0o755)
    _mkdir(selector_path.parent, owner_uid=owner_uid, group_gid=wheel_gid, mode=0o755)


def ceremony(authority: dict[str, Any], *, release_root: Path = RELEASE_ROOT,
             receipt_root: Path = RECEIPT_ROOT, component_root: Path = COMPONENT_ROOT,
             selector_path: Path = SELECTOR_PATH, active_path: Path = ACTIVE_PATH,
             completion_path: Path = COMPLETION_PATH, owner_uid: int = 0,
             release_gid: int, wheel_gid: int,
             selector_probe: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
             confirmer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
             normal_installer: Callable[[Path, dict[str, Any]], subprocess.CompletedProcess[str]]
             = _run_normal_installer) -> dict[str, Any]:
    if completion_path.exists() or completion_path.is_symlink():
        raise GenesisBlocked("genesis is one-time; a completion record already exists")
    if active_path.exists() or active_path.is_symlink():
        raise GenesisBlocked("genesis is forbidden when an active release already exists")
    prepare_genesis_roots(release_root=release_root, receipt_root=receipt_root,
                          component_root=component_root, selector_path=selector_path,
                          completion_path=completion_path, owner_uid=owner_uid,
                          release_gid=release_gid, wheel_gid=wheel_gid)
    final = stage_reviewed_release(authority, release_root=release_root,
                                   owner_uid=owner_uid, release_gid=release_gid)
    receipt = ensure_pending_receipt(authority, final, receipt_root=receipt_root,
                                     owner_uid=owner_uid, release_gid=release_gid)
    establish_broker_lkg(authority, final, component_root=component_root,
                         selector_path=selector_path, owner_uid=owner_uid,
                         wheel_gid=wheel_gid, selector_probe=selector_probe)
    if "genesis_pending" in receipt:
        confirmed = (confirmer(authority) if confirmer is not None else
                     _run_lkg_broker_confirm(final, authority))
        receipt = normalize_broker_receipt(authority, confirmed,
                                           receipt_root=receipt_root,
                                           owner_uid=owner_uid, release_gid=release_gid)
    elif set(receipt) != RECEIPT_FIELDS:
        raise GenesisBlocked("genesis receipt has an invalid transition state")
    outcome = normal_installer(final, authority)
    if outcome.returncode != 0:
        raise GenesisBlocked("normal receipt-gated installer failed; LKG and receipt remain retryable")
    completion = {
        "schema_version": 1, "ceremony": CEREMONY,
        "authority_id": authority["authority_id"],
        "reviewed_commit": authority["reviewed_commit"],
        "release_id": authority["release_id"],
        "receipt_id": receipt["receipt_id"],
        "normal_installer_stdout_sha256": _digest(outcome.stdout.encode("utf-8")),
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "launchd_loaded": False, "services_started": False,
    }
    _atomic_bytes(completion_path, _canonical(completion) + b"\n",
                  owner_uid=owner_uid, group_gid=wheel_gid, mode=0o444)
    return completion


def abort_probation(authority: dict[str, Any], *,
                    active_path: Path = ACTIVE_PATH,
                    release_root: Path = RELEASE_ROOT,
                    receipt_root: Path = RECEIPT_ROOT,
                    component_root: Path = COMPONENT_ROOT,
                    selector_path: Path = SELECTOR_PATH,
                    authority_path: Path = AUTHORITY_PATH,
                    completion_path: Path = COMPLETION_PATH,
                    attest_root: Path = Path("/Library/Application Support/ABCR-Attest"),
                    work_root: Path = Path("/Library/Application Support/ABCR-Work"),
                    library_quarantine_root: Path = Path(
                        "/Library/Application Support/ABCR-Genesis/aborted"),
                    user_quarantine_root: Path = Path("/Users/superagent/.abcr/.aborted"),
                    job_probe: Callable[[str], bool] | None = None,
                    socket_probe: Callable[[], bool] | None = None) -> dict[str, Any]:
    """显式放弃一次未激活的 genesis:归档现场,重开一次性名额。

    只在 probation 期间合法(active.json 存在即拒绝——激活后只能走正式
    release rollback)。全部动作是同卷 rename 归档,绝不删除字节;每步跳过
    已不存在的来源。归档 AUTHORITY_PATH 是最后一步,因此中途失败后重跑仍能
    load_authority 收敛;authority 已归档则本次 abort 视为已完成。
    """
    import socket as socket_module
    import uuid

    def _default_job_probe(label: str) -> bool:
        probe = subprocess.run(["/bin/launchctl", "print", f"system/{label}"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, check=False, timeout=30)
        return probe.returncode == 0

    def _default_socket_probe() -> bool:
        try:
            with socket_module.socket(socket_module.AF_UNIX,
                                      socket_module.SOCK_STREAM) as channel:
                channel.settimeout(2)
                channel.connect("/var/run/abcr-seal-broker.sock")
            return True
        except OSError:
            return False

    job_probe = job_probe or _default_job_probe
    socket_probe = socket_probe or _default_socket_probe
    if active_path.exists() or active_path.is_symlink():
        raise GenesisBlocked("abort refuses after activation; use release rollback")
    for label in ("com.abcr.seal-broker", "com.abcr.canary-controller",
                  "com.abcr.release-activator"):
        if job_probe(label):
            raise GenesisBlocked(f"abort requires bootout first: {label}")
    if socket_probe():
        raise GenesisBlocked("abort requires bootout first: seal-broker listener is live")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    quarantine_name = f"{authority['authority_id']}.{stamp}.{uuid.uuid4().hex[:8]}"
    library_quarantine = library_quarantine_root / quarantine_name
    user_quarantine = user_quarantine_root / quarantine_name
    for root in (library_quarantine, user_quarantine):
        root.mkdir(parents=True, mode=0o700, exist_ok=True)

    archived: list[str] = []

    def _archive(source: Path, quarantine: Path, relative: str) -> None:
        if source.is_symlink() or source.exists():
            destination = quarantine / relative
            destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            try:
                os.rename(source, destination)
            except OSError as exc:
                raise GenesisBlocked(
                    f"abort archive rename failed (cross-device or busy): {source}") from exc
            archived.append(str(source))

    _archive(completion_path, library_quarantine, "genesis-completed-v1.json")
    # 归档 receipt-root 下**所有**条目(含崩溃遗留的 .*.tmp),否则 re-genesis 的
    # ensure_pending_receipt 会因"存在无关 broker receipt"永久拒绝。
    if receipt_root.is_dir():
        for path in sorted(receipt_root.iterdir()):
            _archive(path, library_quarantine, f"release-receipts/{path.name}")
    release_id = authority["release_id"]
    _archive(release_root / release_id, user_quarantine, f"releases/{release_id}")
    for bucket in ("attestations", "canary-results"):
        base = attest_root / bucket
        if base.is_dir():
            for path in sorted(base.iterdir()):
                _archive(path, library_quarantine, f"{bucket}/{path.name}")
    for stage in ("canary", "activate"):
        for state in ("ready", "inflight", "results", "acks", "archive", "quarantine"):
            base = work_root / stage / state
            if base.is_dir():
                for path in sorted(base.glob("*.json")):
                    _archive(path, library_quarantine, f"work/{stage}/{state}/{path.name}")
    for component in ("launcher", "seal-broker", "test-controller"):
        base = component_root / component
        if base.is_dir():
            for path in sorted(base.rglob("*.json")):
                relative = path.relative_to(component_root).as_posix()
                _archive(path, library_quarantine, f"components/{relative}")
    _archive(selector_path, library_quarantine, "abcr-bootstrap-selector")
    _archive(authority_path, library_quarantine, "genesis-authority-v1.json")

    record = {"schema_version": 1, "ceremony": CEREMONY, "state": "ABORTED",
              "aborted_authority_id": authority["authority_id"],
              "release_id": release_id, "archived": archived,
              "library_quarantine": str(library_quarantine),
              "user_quarantine": str(user_quarantine),
              "aborted_at": datetime.now(timezone.utc).isoformat(timespec="microseconds")}
    record_path = library_quarantine / "abort-record.json"
    with record_path.open("xb") as stream:
        stream.write(_canonical(record) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(record_path, 0o444)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bootstrap_abcr_genesis.py")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--authority-draft", action="store_true")
    modes.add_argument("--genesis-reviewed", metavar="AUTHORITY_ID")
    modes.add_argument("--broker-confirm-only", metavar="AUTHORITY_ID")
    modes.add_argument("--abort-probation", metavar="AUTHORITY_ID")
    parser.add_argument("--reviewed-commit")
    parser.add_argument("--human-required", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.authority_draft:
            source = Path(__file__).resolve().parents[1]
            draft = build_authority_statement(source, args.reviewed_commit,
                                              human_approved=False)
            print(json.dumps(draft, ensure_ascii=False, sort_keys=True, indent=2))
            return 0
        if not args.human_required:
            raise GenesisBlocked("genesis requires the explicit --human-required acknowledgement")
        if sys.platform != "darwin" or os.geteuid() != 0:
            raise GenesisBlocked("genesis requires macOS root")
        import grp
        authority_id = (args.genesis_reviewed or args.broker_confirm_only
                        or args.abort_probation)
        authority = load_authority(authority_id)
        if args.abort_probation:
            record = abort_probation(authority)
            print(json.dumps({"ok": True, **record}, sort_keys=True))
            return 0
        if args.broker_confirm_only:
            final = RELEASE_ROOT / authority["release_id"]
            _assert_broker_lkg(authority, final=final,
                               component_root=COMPONENT_ROOT,
                               selector_path=SELECTOR_PATH,
                               receipt_root=RECEIPT_ROOT, owner_uid=0)
            receipt = broker_confirm(
                authority, release_root=RELEASE_ROOT, receipt_root=RECEIPT_ROOT,
                owner_uid=0, release_gid=grp.getgrnam("abcr-release-read").gr_gid)
            print(json.dumps({"ok": True, "receipt": receipt}, sort_keys=True))
            return 0
        completion = ceremony(authority, release_gid=grp.getgrnam("abcr-release-read").gr_gid,
                              wheel_gid=grp.getgrnam("wheel").gr_gid)
        print(json.dumps({"ok": True, **completion}, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__,
                          "message": str(exc)}, sort_keys=True), file=sys.stderr)
        return EX_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
