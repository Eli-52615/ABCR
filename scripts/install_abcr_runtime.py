#!/usr/bin/env python3
"""Reviewed, receipt-gated ABCR production runtime installer.

This bootstrap is intentionally standalone (stdlib only).  In install mode it
must itself be executing from the broker-sealed release named by ``receipt_id``.
It never imports application code and it never starts a launchd job.  The only
effects are finite account-independent filesystem/config/plist installation.
"""
from __future__ import annotations

import argparse
import bz2
import gzip
import hashlib
import io
import json
import lzma
import os
import plistlib
import pwd
import grp
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable, Iterable


AUTHORITY_SHA = "40fd5fb21ff33d7da84648562c6dc12d68f15444dfea60379132af820510d0d1"
RECEIPT_ROOT = Path("/Library/Application Support/ABCR-Attest/release-receipts")
RELEASE_ROOT = Path("/Users/superagent/.abcr/releases")
BOOTSTRAP_ROOT = Path("/Library/Application Support/ABCR-Bootstrap")
CONFIG_ROOT = BOOTSTRAP_ROOT / "config"
TRUST_ROOT = Path("/Library/Application Support/ABCR-Trust")
WORK_ROOT = Path("/Library/Application Support/ABCR-Work")
BRIDGE_ROOT = Path("/Library/Application Support/ABCR-Bridge")
ATTEST_ROOT = Path("/Library/Application Support/ABCR-Attest")
APPROVAL_ROOT = Path("/Library/Application Support/ABCR-ApprovalBundles")
DATASET_ROOT = Path("/Library/Application Support/ABCR-Datasets")
DATASET_AUTHORITY_REL = "ops/install/dataset-authority-ifeval-zh-v1.json"
DATASET_AUTHORITY_SHA256 = "5b15465d247d2374d188eaf0665164b11e97537632fa223370665299924d05b1"
STAGING_ROOT = BOOTSTRAP_ROOT / "staging"
COMPONENT_ROOT = BOOTSTRAP_ROOT / "components"
SELECTOR_PATH = Path("/usr/local/libexec/abcr-bootstrap-selector")
SOCKET_PATH = "/var/run/abcr-seal-broker.sock"
ACTIVE_PATH = "/Users/superagent/.abcr/active.json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RELEASE_ID = re.compile(r"^REL-[0-9a-f]{64}$")
STAGES = (
    "itempool", "probe", "audit", "mission-build", "test", "verify",
    "release-prepare", "canary", "activate",
)
STATES = ("ready", "inflight", "results", "acks", "quarantine", "archive")
SERVICES = {
    "human-gateway": "abcr-human",
    "operator-reconciler": "abcr-operator",
    "probe-worker": "abcr-probe",
    "itempool": "abcr-itempool",
    "auditor": "abcr-auditor",
    "mission-builder": "abcr-builder",
    "test-controller": "root",
    "verifier": "abcr-verifier",
    "canary-controller": "abcr-canary",
    "release-activator": "abcr-activator",
    "panel": "abcr-panel",
    "seal-broker": "root",
}
LABELS = {f"com.abcr.{name}": user for name, user in SERVICES.items()}
QUEUE_SERVICES = SERVICES.keys() - {"human-gateway", "panel"}
FROZEN_SCIENTIFIC_SHA256 = frozenset({
    "25cf6d9d5a2c8e8bb3eccc162ec26e4fc144e9dc42a03f37e0316ad886d6b0e6",
    "a79087c91a76c157eeb2133527640b4599988a123d26678e30d0d36c4bd62413",
    "d0642d787cab167485e718c41c5c01e454d5a623ce5ef85b1b39402730c5799f",
    "7d5d6426b953296251d6665d6639a9df10379d270bf9ce217d7bc0db7845babd",
    "6934a00d98571cc07b08db8602b12c5e2a7531ed8e3df665d7aaa3c7f0876875",
    "06dce6ab1d4026c475c0aeb010a8b3b70ca0aca87f4e18d9911edbdfb357e486",
    "95be69231c2183b44fbdcdedb38398fcb48c699f8d573644ee31028c4db27b03",
    "794935d2a2be40119bd6685cf7a3faf3be0a790185f33d8c2f9d9866c74d2cca",
    "4e4a2f7b6bf4390cd3c4828bd7f59fe9edbc78e71405ea682f3afdc0acd20d42",
})
_SCIENTIFIC_SEGMENTS = frozenset({
    "benchmark", "benchmarks", "golden", "goldens", "golden_answers",
    "split", "splits",
})
_SCIENTIFIC_DATA_SUFFIXES = frozenset({
    ".arrow", ".bin", ".csv", ".json", ".jsonl", ".npy", ".npz",
    ".parquet", ".pt", ".safetensors", ".tsv", ".txt", ".yaml", ".yml",
})
_POLICY_MAX_MEMBERS = 100_000
_POLICY_MAX_MEMBER_BYTES = 128 * 1024 * 1024
_POLICY_MAX_TOTAL_BYTES = 512 * 1024 * 1024
_POLICY_MAX_ARCHIVE_DEPTH = 2
_POLICY_UNSUPPORTED_ARCHIVE_MAGIC = (
    b"\x28\xb5\x2f\xfd", b"\x37\x7a\xbc\xaf\x27\x1c",
    b"Rar!\x1a\x07", b"\x04\x22\x4d\x18",
)
_DATASET_ACL_SENSITIVE = frozenset({
    "read", "read_data", "list", "list_directory", "search", "execute",
})
_DATASET_ACL_ENTRY = re.compile(r"^\s*\d+:\s+(user|group):([^\s]+)\s+(.+)$")
_DATASET_READER_GROUP = "abcr-dataset-read"
_DIRECTORY_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class InstallBlocked(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: bytes | Any) -> str:
    raw = value if isinstance(value, bytes) else canonical(value)
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InstallBlocked("duplicate JSON key")
        result[key] = value
    return result


def read_json(path: Path, *, owner_uid: int = 0, max_bytes: int = 4 * 1024 * 1024
              ) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise InstallBlocked(f"trusted file unavailable: {path}") from exc
    try:
        before = os.fstat(fd)
        mode = stat.S_IMODE(before.st_mode)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != owner_uid or mode & 0o022
                or before.st_size > max_bytes):
            raise InstallBlocked(f"unsafe trusted file: {path}")
        raw = b""
        while len(raw) <= before.st_size:
            chunk = os.read(fd, before.st_size + 1 - len(raw))
            if not chunk:
                break
            raw += chunk
        after = os.fstat(fd)
        identity = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_nlink,
                              x.st_uid, stat.S_IMODE(x.st_mode))
        if len(raw) != before.st_size or identity(before) != identity(after):
            raise InstallBlocked(f"trusted file changed: {path}")
    finally:
        os.close(fd)
    try:
        value = json.loads(raw, object_pairs_hook=unique_object,
                           parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    except (UnicodeDecodeError, ValueError) as exc:
        raise InstallBlocked(f"invalid trusted JSON: {path}") from exc
    if not isinstance(value, dict):
        raise InstallBlocked(f"trusted JSON is not an object: {path}")
    return value


def uid(name: str) -> int:
    try:
        return 0 if name == "root" else pwd.getpwnam(name).pw_uid
    except KeyError as exc:
        raise InstallBlocked(f"required account missing: {name}") from exc


def gid(name: str) -> int:
    try:
        return grp.getgrnam(name).gr_gid
    except KeyError as exc:
        raise InstallBlocked(f"required group missing: {name}") from exc


def require_real_dir(path: Path, *, owner_uid: int | None = None,
                     writable_mask: int = 0o022) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise InstallBlocked(f"required directory unavailable: {path}") from exc
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or (owner_uid is not None and info.st_uid != owner_uid)
            or stat.S_IMODE(info.st_mode) & writable_mask):
        raise InstallBlocked(f"unsafe directory: {path}")
    return info


def tree_entries(root: Path) -> list[dict[str, Any]]:
    root_info = require_real_dir(root, owner_uid=0)
    entries: list[dict[str, Any]] = []
    inodes: set[tuple[int, int]] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        info = require_real_dir(current, owner_uid=0)
        if info.st_dev != root_info.st_dev:
            raise InstallBlocked("sealed release crosses a mount")
        for name in sorted(dirnames):
            child = current / name
            child_info = require_real_dir(child, owner_uid=0)
            if child_info.st_dev != root_info.st_dev:
                raise InstallBlocked("sealed release crosses a mount")
        for name in sorted(filenames):
            path = current / name
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            try:
                before = os.fstat(fd)
                inode = (before.st_dev, before.st_ino)
                if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                        or before.st_uid != 0 or before.st_dev != root_info.st_dev
                        or inode in inodes):
                    raise InstallBlocked(f"unsafe sealed entry: {path}")
                inodes.add(inode)
                raw = b""
                while len(raw) <= before.st_size:
                    chunk = os.read(fd, before.st_size + 1 - len(raw))
                    if not chunk:
                        break
                    raw += chunk
                after = os.fstat(fd)
                if (len(raw) != before.st_size
                        or (before.st_dev, before.st_ino, before.st_size, before.st_nlink)
                        != (after.st_dev, after.st_ino, after.st_size, after.st_nlink)):
                    raise InstallBlocked(f"sealed entry changed: {path}")
            finally:
                os.close(fd)
            entries.append({"path": path.relative_to(root).as_posix(),
                            "mode": stat.S_IMODE(before.st_mode), "size": len(raw),
                            "sha256": digest(raw)})
    return sorted(entries, key=lambda item: item["path"])


def _policy_name(value: str, *, container: str) -> PurePosixPath:
    if not value or "\\" in value or "\x00" in value:
        raise InstallBlocked(f"scientific policy invalid path in {container}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise InstallBlocked(f"scientific policy escaping path in {container}")
    return pure


def _reject_scientific_name(value: str, *, container: str) -> None:
    pure = _policy_name(value, container=container)
    parts = tuple(part.casefold() for part in pure.parts)
    basename = parts[-1]
    leaf = PurePosixPath(basename)
    if (any(part in _SCIENTIFIC_SEGMENTS for part in parts)
            or (leaf.suffix in _SCIENTIFIC_DATA_SUFFIXES
                and (leaf.stem.startswith("golden")
                     or leaf.stem in {"split", "splits", "benchmark", "benchmarks"}))):
        raise InstallBlocked(
            f"sealed release contains forbidden scientific path: {container}!/{value}")


def _policy_limit(condition: bool, *, container: str) -> None:
    if condition:
        raise InstallBlocked(f"scientific policy archive limit exceeded: {container}")


def _scan_policy_zip(raw: bytes, *, container: str, depth: int) -> bool:
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            _policy_limit(len(members) > _POLICY_MAX_MEMBERS, container=container)
            total = 0
            for member in members:
                if member.is_dir():
                    continue
                _reject_scientific_name(member.filename, container=container)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode) or member.flag_bits & 0x1:
                    raise InstallBlocked(
                        f"scientific policy unsafe zip member: {container}!/{member.filename}")
                _policy_limit(member.file_size > _POLICY_MAX_MEMBER_BYTES,
                              container=container)
                total += member.file_size
                _policy_limit(total > _POLICY_MAX_TOTAL_BYTES, container=container)
                member_raw = archive.read(member)
                if len(member_raw) != member.file_size:
                    raise InstallBlocked(f"scientific policy zip member drift: {container}")
                if digest(member_raw) in FROZEN_SCIENTIFIC_SHA256:
                    raise InstallBlocked(
                        f"sealed release contains frozen scientific bytes: {container}")
                _scan_policy_archive(
                    member_raw, container=f"{container}!/{member.filename}", depth=depth + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        if isinstance(exc, InstallBlocked):
            raise
        raise InstallBlocked(f"scientific policy invalid zip: {container}") from exc
    return True


def _scan_policy_tar(raw: bytes, *, container: str, depth: int) -> bool:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(raw), mode="r:*")
    except tarfile.ReadError:
        return False
    try:
        members = archive.getmembers()
        _policy_limit(len(members) > _POLICY_MAX_MEMBERS, container=container)
        # 与 release_policy._scan_tar 逐条对齐:先建归一化名字映射并拒绝重名成员;
        # hardlink 成员要靠它把 linkname 解析成归档内的真实 target。
        by_name: dict[str, tarfile.TarInfo] = {}
        for member in members:
            normalized = _policy_name(member.name, container=container).as_posix()
            if normalized in by_name:
                raise InstallBlocked(
                    f"scientific policy duplicate tar member: {container}!/{member.name}")
            by_name[normalized] = member
        total = 0
        for member in members:
            if member.isdir():
                continue
            _reject_scientific_name(member.name, container=container)
            if member.issym() or not (member.isfile() or member.islnk()):
                raise InstallBlocked(
                    f"scientific policy unsafe tar member: {container}!/{member.name}")
            expected_size = member.size
            if member.islnk():
                # dateutil 一类标准依赖合法使用 tar hardlink 成员(真实封印 release 内
                # dateutil-zoneinfo.tar.gz 含 245 个)。语义与 release_policy 相同:
                # 把归档当数据、从不重建链接;target 必须是归档内唯一确定的普通成员,
                # 其解析后的字节在别名下再扫一次。hardlink 成员自身 size 为 0,
                # 校验必须用 target 的 size,否则读到内容会被判成 drift。
                target_name = _policy_name(
                    member.linkname, container=container).as_posix()
                target = by_name.get(target_name)
                if target is None or not target.isfile():
                    raise InstallBlocked(
                        "scientific policy unsafe tar hardlink target: "
                        f"{container}!/{member.name}")
                expected_size = target.size
            _policy_limit(expected_size > _POLICY_MAX_MEMBER_BYTES, container=container)
            total += expected_size
            _policy_limit(total > _POLICY_MAX_TOTAL_BYTES, container=container)
            stream = archive.extractfile(member)
            if stream is None:
                raise InstallBlocked(f"scientific policy unreadable tar member: {container}")
            member_raw = stream.read(_POLICY_MAX_MEMBER_BYTES + 1)
            if len(member_raw) != expected_size:
                raise InstallBlocked(f"scientific policy tar member drift: {container}")
            if digest(member_raw) in FROZEN_SCIENTIFIC_SHA256:
                raise InstallBlocked(
                    f"sealed release contains frozen scientific bytes: {container}")
            _scan_policy_archive(
                member_raw, container=f"{container}!/{member.name}", depth=depth + 1)
    except (OSError, tarfile.TarError) as exc:
        if isinstance(exc, InstallBlocked):
            raise
        raise InstallBlocked(f"scientific policy invalid tar: {container}") from exc
    finally:
        archive.close()
    return True


def _scan_policy_stream_compression(raw: bytes, *, container: str,
                                    depth: int) -> bool:
    if raw.startswith(b"\x1f\x8b"):
        opener = gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb")
    elif raw.startswith(b"BZh"):
        opener = bz2.BZ2File(io.BytesIO(raw), mode="rb")
    elif raw.startswith(b"\xfd7zXZ\x00"):
        opener = lzma.LZMAFile(io.BytesIO(raw), mode="rb")
    else:
        return False
    try:
        with opener as stream:
            expanded = stream.read(_POLICY_MAX_MEMBER_BYTES + 1)
            if len(expanded) > _POLICY_MAX_MEMBER_BYTES or stream.read(1):
                raise InstallBlocked(
                    f"scientific policy compressed stream limit exceeded: {container}")
    except (OSError, EOFError, lzma.LZMAError) as exc:
        if isinstance(exc, InstallBlocked):
            raise
        raise InstallBlocked(
            f"scientific policy invalid compressed stream: {container}") from exc
    if digest(expanded) in FROZEN_SCIENTIFIC_SHA256:
        raise InstallBlocked(
            f"sealed release contains frozen scientific bytes: {container}")
    _scan_policy_archive(
        expanded, container=f"{container}!/<compressed-stream>", depth=depth + 1)
    return True


def _scan_policy_archive(raw: bytes, *, container: str, depth: int = 0) -> None:
    if depth > _POLICY_MAX_ARCHIVE_DEPTH:
        nested = (zipfile.is_zipfile(io.BytesIO(raw))
                  or raw.startswith((b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00"))
                  or raw.startswith(_POLICY_UNSUPPORTED_ARCHIVE_MAGIC))
        if not nested:
            try:
                probe = tarfile.open(fileobj=io.BytesIO(raw), mode="r:*")
            except (OSError, tarfile.TarError):
                pass
            else:
                nested = True
                probe.close()
        if nested:
            raise InstallBlocked(f"scientific policy archive nesting exceeded: {container}")
        return
    if _scan_policy_zip(raw, container=container, depth=depth):
        return
    if _scan_policy_tar(raw, container=container, depth=depth):
        return
    if _scan_policy_stream_compression(raw, container=container, depth=depth):
        return
    if raw.startswith(_POLICY_UNSUPPORTED_ARCHIVE_MAGIC):
        raise InstallBlocked(
            f"scientific policy unsupported compressed format: {container}")


def _read_policy_entry(root: Path, entry: dict[str, Any], *, owner_uid: int) -> bytes:
    path = root / entry["path"]
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
                 | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != owner_uid or before.st_size != entry["size"]
                or stat.S_IMODE(before.st_mode) != entry["mode"]):
            raise InstallBlocked(f"scientific policy entry drift: {entry['path']}")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size,
                                 item.st_nlink, item.st_uid, stat.S_IMODE(item.st_mode))
        if (len(raw) != before.st_size or identity(before) != identity(after)
                or digest(raw) != entry["sha256"]):
            raise InstallBlocked(f"scientific policy hash drift: {entry['path']}")
        return raw
    finally:
        os.close(fd)


def enforce_release_scientific_content_policy(
        root: Path, observed: list[dict[str, Any]], *, owner_uid: int = 0) -> None:
    """Standalone stdlib port of the release scientific-content policy.

    The root installer deliberately does not import or execute candidate Python
    modules.  It independently reopens every receipt-bound inode and repeats the
    same path, frozen-byte and nested-archive exclusions immediately before any
    root-owned runtime files are installed.
    """
    for entry in observed:
        if (not isinstance(entry, dict)
                or set(entry) != {"path", "mode", "size", "sha256"}):
            raise InstallBlocked("scientific policy received malformed tree entry")
        _reject_scientific_name(entry["path"], container="release-tree")
        if entry["sha256"] in FROZEN_SCIENTIFIC_SHA256:
            raise InstallBlocked("sealed release contains frozen scientific bytes")
        raw = _read_policy_entry(root, entry, owner_uid=owner_uid)
        _scan_policy_archive(raw, container=entry["path"])


def validate_release_manifest(manifest: dict[str, Any],
                              observed: list[dict[str, Any]]) -> None:
    """Bind the deployment manifest to the entire receipt-sealed tree.

    The broker receipt authenticates the sealed bytes, not claims written
    inside ``release-manifest.json``.  Recompute the release identity here,
    before root-owned config/plist/slot mutation, so a stale or forged manifest
    cannot select unbound deployment bytes.
    """
    fields = {
        "release_id", "tree_hash", "runtime_digest", "lock_hash",
        "service_config_hash", "verification_hash", "tree_entries",
        "runtime_relpath", "lock_relpath", "service_config_relpath",
        "service_payloads",
    }
    if not isinstance(manifest, dict) or set(manifest) != fields:
        raise InstallBlocked("release manifest shape is invalid")
    for name in ("tree_hash", "runtime_digest", "lock_hash",
                 "service_config_hash", "verification_hash"):
        if not isinstance(manifest[name], str) or HEX64.fullmatch(manifest[name]) is None:
            raise InstallBlocked(f"release manifest {name} is invalid")
    release_id = manifest["release_id"]
    core = {name: manifest[name] for name in (
        "tree_hash", "runtime_digest", "lock_hash",
        "service_config_hash", "verification_hash")}
    if (not isinstance(release_id, str) or RELEASE_ID.fullmatch(release_id) is None
            or release_id != "REL-" + digest(core)):
        raise InstallBlocked("release manifest identity is invalid")
    for name in ("runtime_relpath", "lock_relpath", "service_config_relpath"):
        if not isinstance(manifest[name], str):
            raise InstallBlocked(f"release manifest {name} is invalid")
        _policy_name(manifest[name], container="release-manifest")
    if not isinstance(manifest["service_payloads"], dict):
        raise InstallBlocked("release service payload manifest is invalid")

    declared = manifest["tree_entries"]
    if not isinstance(declared, list) or not declared:
        raise InstallBlocked("release manifest has no declared tree")
    paths: list[str] = []
    for item in declared:
        if (not isinstance(item, dict)
                or set(item) != {"path", "mode", "size", "sha256"}
                or type(item["mode"]) is not int or item["mode"] < 0
                or type(item["size"]) is not int or item["size"] < 0
                or not isinstance(item["path"], str)
                or not isinstance(item["sha256"], str)
                or HEX64.fullmatch(item["sha256"]) is None):
            raise InstallBlocked("release manifest tree entry is invalid")
        paths.append(_policy_name(item["path"], container="release-manifest").as_posix())
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise InstallBlocked("release manifest tree paths are not unique and sorted")
    if digest(declared) != manifest["tree_hash"]:
        raise InstallBlocked("release manifest declared tree hash is invalid")

    actual = [item for item in observed if item["path"] != "release-manifest.json"]
    if len(actual) != len(declared):
        raise InstallBlocked("sealed release tree differs from release manifest")
    for expected, current in zip(declared, actual, strict=True):
        # The broker deliberately changes 0444/0555 into 0440/0550.  Content,
        # path and executable class remain invariant across that policy step.
        if ({key: expected[key] for key in ("path", "size", "sha256")}
                != {key: current[key] for key in ("path", "size", "sha256")}
                or bool(expected["mode"] & 0o111) != bool(current["mode"] & 0o111)):
            raise InstallBlocked("sealed release tree differs from release manifest")


def verify_receipt(receipt_id: str) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    if HEX64.fullmatch(receipt_id) is None:
        raise InstallBlocked("receipt id must be lowercase SHA-256")
    require_real_dir(RECEIPT_ROOT, owner_uid=0)
    receipt = read_json(RECEIPT_ROOT / f"{receipt_id}.json")
    # Genesis may create a temporary authority-bound receipt solely so the
    # stable selector can establish the first seal-broker LKG.  It is not a
    # broker-qualified install capability.  Only the exact ordinary broker
    # receipt shape is accepted here; the genesis ceremony removes its pending
    # marker only after the LKG broker has revalidated the same release.
    receipt_fields = {
        "receipt_id", "operation", "nonce", "object_id", "tree_hash",
        "sealed_tree_hash", "sealed_path", "created_at",
    }
    if set(receipt) != receipt_fields:
        raise InstallBlocked("release receipt is pending genesis or has unknown fields")
    core = {"operation": receipt.get("operation"), "nonce": receipt.get("nonce"),
            "tree_hash": receipt.get("tree_hash"), "object_id": receipt.get("object_id")}
    release_id = receipt.get("object_id")
    if (receipt.get("receipt_id") != receipt_id or digest(core) != receipt_id
            or receipt.get("operation") != "seal_release"
            or not isinstance(release_id, str) or RELEASE_ID.fullmatch(release_id) is None):
        raise InstallBlocked("release receipt identity is invalid")
    release = RELEASE_ROOT / release_id
    if receipt.get("sealed_path") != str(release):
        raise InstallBlocked("release receipt path is not the frozen release root")
    observed = tree_entries(release)
    if digest(observed) != receipt.get("sealed_tree_hash"):
        raise InstallBlocked("sealed release bytes drifted from broker receipt")
    enforce_release_scientific_content_policy(release, observed, owner_uid=0)
    # manifest 内嵌全部树条目(真实 release 约 23 MiB),4/8 MiB 的防呆上限会让
    # **任何真实 release** 在此被拒;同文件读运行时字节用的即 128 MiB。
    manifest = read_json(release / "release-manifest.json", max_bytes=128 * 1024 * 1024)
    validate_release_manifest(manifest, observed)
    if manifest["release_id"] != release_id:
        raise InstallBlocked("sealed release manifest identity mismatch")
    by_path = {item.get("path"): item for item in observed if isinstance(item, dict)}
    installer_rel = "scripts/install_abcr_runtime.py"
    if installer_rel not in by_path:
        raise InstallBlocked("receipt-sealed release does not contain this installer")
    running = Path(__file__).resolve()
    expected = release / installer_rel
    if running != expected:
        raise InstallBlocked("install mode must run the installer inside the sealed release")
    return receipt, release, manifest


def make_dir(path: Path, owner: str, group: str, mode: int) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_dir():
            raise InstallBlocked(f"refusing unsafe existing path: {path}")
    else:
        path.mkdir(parents=False, mode=mode)
    os.chown(path, uid(owner), gid(group))
    os.chmod(path, mode)


def ensure_search_acl(path: Path, *, kind: str, name: str) -> None:
    """Add one exact macOS search ACE without changing ordinary mode bits."""
    if kind not in {"user", "group"} or not name or "\n" in name:
        raise InstallBlocked("invalid parent traverse ACL")
    require_real_dir(path)
    ace = f"{kind}:{name} allow search"
    observed = subprocess.run(["/bin/ls", "-lde", str(path)], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              text=True).stdout
    if ace not in observed:
        subprocess.run(["/bin/chmod", "+a", ace, str(path)], check=True,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)


def atomic_bytes(path: Path, raw: bytes, *, owner: str, group: str, mode: int) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise InstallBlocked(f"refusing unsafe output target: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, uid(owner), gid(group))
        os.chmod(temporary, mode)
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


def atomic_json(path: Path, value: dict[str, Any], *, group: str) -> None:
    atomic_bytes(path, canonical(value) + b"\n", owner="root", group=group, mode=0o440)


def load_release_json(release: Path, relative: str) -> dict[str, Any]:
    return read_json(release / relative)


def _dataset_acl_text(path: Path) -> str:
    try:
        result = subprocess.run(
            ["/bin/ls", "-lde", "--", str(path)], check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallBlocked(f"cannot inspect immutable dataset ACL: {path}") from exc
    if result.returncode != 0:
        raise InstallBlocked(f"cannot inspect immutable dataset ACL: {path}")
    return result.stdout


def _dataset_acl_entries(raw: str) -> tuple[tuple[str, str, str, frozenset[str]], ...]:
    entries: list[tuple[str, str, str, frozenset[str]]] = []
    for line in raw.splitlines()[1:]:
        if not re.match(r"^\s*\d+:", line):
            continue
        match = _DATASET_ACL_ENTRY.fullmatch(line)
        if match is None:
            raise InstallBlocked("unrecognized immutable dataset ACL entry")
        kind, principal, tail = match.groups()
        words = tail.split()
        try:
            action_index = next(index for index, word in enumerate(words)
                                if word in {"allow", "deny"})
        except StopIteration as exc:
            raise InstallBlocked("unrecognized immutable dataset ACL action") from exc
        if action_index == len(words) - 1:
            raise InstallBlocked("empty immutable dataset ACL permission set")
        permissions = frozenset(
            token for word in words[action_index + 1:] for token in word.split(",") if token)
        entries.append((kind, principal, words[action_index], permissions))
    return tuple(entries)


_GID_MODULUS = 1 << 32
_GID_C_INT_MAX = 0x7FFFFFFF


def _canonical_gid(value: int) -> int:
    """Unsigned 32-bit spelling of a gid (see import_abcr_dataset for the
    macOS ``nobody`` sentinel rationale); ``grp`` accepts only this form."""
    return value % _GID_MODULUS


def _c_int_gid(value: int) -> int:
    """Signed C int spelling required by ``os.getgrouplist``."""
    canonical = _canonical_gid(value)
    return canonical - _GID_MODULUS if canonical > _GID_C_INT_MAX else canonical


def _dataset_identity(name: str) -> tuple[str, int, frozenset[str]]:
    try:
        account = pwd.getpwnam(name)
        gids = os.getgrouplist(name, _c_int_gid(account.pw_gid))
    except (KeyError, OSError, OverflowError, ValueError) as exc:
        raise InstallBlocked(f"immutable dataset ACL identity unavailable: {name}") from exc
    groups: set[str] = {str(_canonical_gid(gid)) for gid in gids}
    for group_id in gids:
        try:
            groups.add(grp.getgrgid(_canonical_gid(group_id)).gr_name)
        except KeyError:
            continue
    return name, account.pw_uid, frozenset(groups)


def _dataset_directory_plist(record: str,
                             attributes: tuple[str, ...]) -> dict[str, Any]:
    """Independent installer-side OpenDirectory reader."""
    try:
        result = subprocess.run(
            ["/usr/bin/dscl", "-plist", ".", "-read", record, *attributes],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallBlocked(f"cannot inspect immutable dataset group record: {record}") from exc
    if result.returncode != 0 or len(result.stdout) > 64 * 1024:
        raise InstallBlocked(f"cannot inspect immutable dataset group record: {record}")
    try:
        value = plistlib.loads(result.stdout)
    except (plistlib.InvalidFileException, ValueError) as exc:
        raise InstallBlocked(f"invalid immutable dataset group record: {record}") from exc
    if not isinstance(value, dict):
        raise InstallBlocked(f"invalid immutable dataset group record: {record}")
    return value


def _dataset_record_values(record: dict[str, Any], attribute: str) -> tuple[str, ...]:
    raw = record.get(f"dsAttrTypeStandard:{attribute}", [])
    if (not isinstance(raw, list) or any(not isinstance(item, str) or not item
                                         for item in raw)
            or len(raw) != len(set(raw))):
        raise InstallBlocked(f"invalid immutable dataset group attribute: {attribute}")
    return tuple(raw)


def _installed_dataset_group_record(_group: str) -> tuple[tuple[str, ...],
                                                           tuple[str, ...],
                                                           tuple[str, ...]]:
    record = _dataset_directory_plist(
        f"/Groups/{_group}", ("GroupMembership", "GroupMembers", "NestedGroups"))
    return (_dataset_record_values(record, "GroupMembership"),
            _dataset_record_values(record, "GroupMembers"),
            _dataset_record_values(record, "NestedGroups"))


def _installed_dataset_user_guid(name: str) -> str:
    if _DIRECTORY_NAME.fullmatch(name) is None:
        raise InstallBlocked(f"invalid immutable dataset reader identity: {name}")
    record = _dataset_directory_plist(f"/Users/{name}", ("GeneratedUID",))
    values = _dataset_record_values(record, "GeneratedUID")
    if len(values) != 1:
        raise InstallBlocked(f"immutable dataset reader GUID unavailable: {name}")
    return values[0]


def _installed_visible_directory_users() -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ["/usr/bin/dscl", "/Search", "-list", "/Users", "UniqueID"],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallBlocked("cannot enumerate immutable dataset directory users") from exc
    if result.returncode != 0 or len(result.stdout) > 4 * 1024 * 1024:
        raise InstallBlocked("cannot enumerate immutable dataset directory users")
    users: list[str] = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if (len(fields) != 2 or _DIRECTORY_NAME.fullmatch(fields[0]) is None
                or re.fullmatch(r"-?[0-9]+", fields[1]) is None):
            raise InstallBlocked("invalid immutable dataset user enumeration")
        users.append(fields[0])
    if not users or len(users) != len(set(users)):
        raise InstallBlocked("ambiguous immutable dataset user enumeration")
    return tuple(users)


def _installed_effective_groups(name: str) -> frozenset[str]:
    return _dataset_identity(name)[2]


def validate_exact_dataset_reader_group(
        access: dict[str, Any], *,
        group_record_reader: Callable[[str], tuple[tuple[str, ...],
                                                    tuple[str, ...],
                                                    tuple[str, ...]]] = _installed_dataset_group_record,
        user_guid_resolver: Callable[[str], str] = _installed_dataset_user_guid,
        visible_users_resolver: Callable[[], tuple[str, ...]] = _installed_visible_directory_users,
        effective_groups_resolver: Callable[[str], frozenset[str]] = _installed_effective_groups,
) -> None:
    """Fail before mutation unless the dataset reader group is exactly reviewed."""
    readers = access.get("readers")
    group = access.get("group")
    if group != _DATASET_READER_GROUP or readers != ["abcr-itempool", "abcr-auditor"]:
        raise InstallBlocked("immutable dataset reader authority mismatch")
    expected = frozenset(readers)
    try:
        direct_names, direct_guids, nested_guids = group_record_reader(group)
        expected_guids = tuple(user_guid_resolver(name) for name in readers)
        visible_users = visible_users_resolver()
    except InstallBlocked:
        raise
    except Exception as exc:
        raise InstallBlocked("immutable dataset reader group inspection failed") from exc
    for label, values in (("direct names", direct_names),
                          ("direct GUIDs", direct_guids),
                          ("nested groups", nested_guids),
                          ("visible users", visible_users)):
        if (not isinstance(values, tuple)
                or any(not isinstance(item, str) or not item for item in values)
                or len(values) != len(set(values))):
            raise InstallBlocked(f"invalid immutable dataset reader {label}")
    if frozenset(direct_names) != expected:
        raise InstallBlocked("immutable dataset reader direct membership is not exact")
    if nested_guids:
        raise InstallBlocked("immutable dataset reader group contains nested membership")
    if (len(expected_guids) != len(set(expected_guids))
            or frozenset(direct_guids) != frozenset(expected_guids)):
        raise InstallBlocked("immutable dataset reader GUID membership is not exact")

    effective: set[str] = set()
    for name in tuple(dict.fromkeys((*visible_users, *readers))):
        try:
            groups = effective_groups_resolver(name)
        except InstallBlocked:
            raise
        except Exception as exc:
            raise InstallBlocked(
                f"effective immutable dataset group membership unavailable: {name}") from exc
        if not isinstance(groups, frozenset) or any(
                not isinstance(item, str) or not item for item in groups):
            raise InstallBlocked(
                f"invalid effective immutable dataset group membership: {name}")
        if group in groups:
            effective.add(name)
    if effective != expected:
        raise InstallBlocked("immutable dataset reader effective membership is not exact")


def require_no_dataset_acl_grant(
        paths: Iterable[Path], must_deny: Iterable[str], *,
        acl_reader: Callable[[Path], str] = _dataset_acl_text,
        identity_resolver: Callable[[str], tuple[str, int, frozenset[str]]] = _dataset_identity,
        posix_reader_groups: Iterable[str] = (),
) -> None:
    """Independent root-side rejection of named/inherited ACL exposure."""
    identities = []
    for name in must_deny:
        try:
            identity = identity_resolver(name)
        except InstallBlocked:
            raise
        except Exception as exc:
            raise InstallBlocked(f"immutable dataset ACL identity unavailable: {name}") from exc
        if (not isinstance(identity, tuple) or len(identity) != 3
                or identity[0] != name or type(identity[1]) is not int
                or not isinstance(identity[2], frozenset)):
            raise InstallBlocked(f"invalid immutable dataset ACL identity: {name}")
        identities.append(identity)
    reader_groups = frozenset(posix_reader_groups)
    for name, _uid, groups in identities:
        if groups & reader_groups:
            raise InstallBlocked(
                f"immutable dataset POSIX reader group includes must-deny identity {name}")
    for path in paths:
        try:
            entries = _dataset_acl_entries(acl_reader(path))
        except InstallBlocked:
            raise
        except Exception as exc:
            raise InstallBlocked(f"cannot inspect immutable dataset ACL: {path}") from exc
        for kind, principal, action, permissions in entries:
            if action != "allow" or not permissions & _DATASET_ACL_SENSITIVE:
                continue
            for name, uid, groups in identities:
                if ((kind == "user" and principal in {name, str(uid)})
                        or (kind == "group"
                            and (principal == "everyone" or principal in groups))):
                    raise InstallBlocked(
                        f"immutable dataset ACL grants must-deny identity {name}: {path}")


def _require_dataset_acl(paths: Iterable[Path], must_deny: Iterable[str], *,
                         enforce_acl: bool | None,
                         acl_reader: Callable[[Path], str] | None,
                         identity_resolver: Callable[[str], tuple[str, int, frozenset[str]]] | None,
                         posix_reader_groups: Iterable[str] = (),
                         ) -> bool:
    checked = tuple(paths)
    production = (sys.platform == "darwin" and os.geteuid() == 0
                  and any(path == DATASET_ROOT or DATASET_ROOT in path.parents
                          for path in checked))
    required = production if enforce_acl is None else enforce_acl
    if not required:
        return False
    require_no_dataset_acl_grant(
        checked, must_deny,
        acl_reader=_dataset_acl_text if acl_reader is None else acl_reader,
        identity_resolver=_dataset_identity if identity_resolver is None else identity_resolver,
        posix_reader_groups=posix_reader_groups,
    )
    return True


def _dataset_file(path: Path, *, owner_uid: int, group_gid: int,
                  size: int | None = None, sha: str | None = None) -> bytes:
    """Reopen one immutable dataset inode with stricter policy than code files."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise InstallBlocked(f"dataset file unavailable: {path}") from exc
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != owner_uid or before.st_gid != group_gid
                or stat.S_IMODE(before.st_mode) != 0o440
                or (size is not None and before.st_size != size)):
            raise InstallBlocked(f"unsafe immutable dataset file: {path}")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size,
                                 item.st_nlink, item.st_uid, item.st_gid,
                                 stat.S_IMODE(item.st_mode))
        if (len(raw) != before.st_size or identity(before) != identity(after)
                or (sha is not None and digest(raw) != sha)):
            raise InstallBlocked(f"immutable dataset file drift: {path}")
        return raw
    finally:
        os.close(fd)


def load_dataset_authority(release: Path) -> dict[str, Any]:
    path = release / DATASET_AUTHORITY_REL
    raw = path.read_bytes()
    if path.is_symlink() or digest(raw) != DATASET_AUTHORITY_SHA256:
        raise InstallBlocked("sealed dataset authority identity mismatch")
    authority = load_release_json(release, DATASET_AUTHORITY_REL)
    required = {
        "schema_version", "authority_id", "reviewed_authority_sha256",
        "dataset_family", "source_commit", "source_combined_sha256",
        "source_staging_root", "dataset_root", "sources", "invariants",
        "output", "access_policy",
    }
    output = authority.get("output")
    if (set(authority) != required or authority.get("schema_version") != 1
            or authority.get("reviewed_authority_sha256") != AUTHORITY_SHA
            or authority.get("dataset_root") != str(DATASET_ROOT)
            or not isinstance(output, dict)
            or set(output) != {"dataset_sha256", "items_path", "items_size",
                              "items_sha256", "split_path", "split_size",
                              "split_sha256"}
            or output.get("items_path") != "items.json"
            or output.get("split_path") != "split.json"
            or any(HEX64.fullmatch(str(output.get(name, ""))) is None
                   for name in ("dataset_sha256", "items_sha256", "split_sha256"))):
        raise InstallBlocked("sealed dataset authority contract mismatch")
    access = authority.get("access_policy")
    if (not isinstance(access, dict)
            or set(access) != {"owner", "group", "directory_mode", "file_mode",
                               "readers", "must_deny"}
            or access.get("owner") != "root"
            or access.get("group") != "abcr-dataset-read"
            or access.get("directory_mode") != "0550"
            or access.get("file_mode") != "0440"
            or access.get("readers") != ["abcr-itempool", "abcr-auditor"]
            or not isinstance(access.get("must_deny"), list)
            or not access["must_deny"]
            or len(access["must_deny"]) != len(set(access["must_deny"]))
            or set(access["readers"]) & set(access["must_deny"])):
        raise InstallBlocked("sealed dataset access policy mismatch")
    return authority


def validate_installed_dataset(dataset_root: Path, authority: dict[str, Any], *,
                               owner_uid: int, dataset_gid: int,
                               enforce_acl: bool | None = None,
                               acl_reader: Callable[[Path], str] | None = None,
                               identity_resolver: Callable[[str], tuple[str, int, frozenset[str]]] | None = None,
                               ) -> Path:
    if not dataset_root.is_absolute() or dataset_root.resolve(strict=False) != dataset_root:
        raise InstallBlocked("dataset root contains a symlinked path component")
    root_info = require_real_dir(dataset_root, owner_uid=owner_uid)
    if stat.S_IMODE(root_info.st_mode) != 0o550 or root_info.st_gid != dataset_gid:
        raise InstallBlocked("dataset root ownership/mode mismatch")
    output = authority["output"]
    final = dataset_root / output["dataset_sha256"]
    final_info = require_real_dir(final, owner_uid=owner_uid)
    if stat.S_IMODE(final_info.st_mode) != 0o550 or final_info.st_gid != dataset_gid:
        raise InstallBlocked("immutable dataset directory ownership/mode mismatch")
    if {item.name for item in final.iterdir()} != {"items.json", "split.json", "manifest.json"}:
        raise InstallBlocked("immutable dataset file set mismatch")
    _require_dataset_acl(
        (dataset_root, final, final / "items.json", final / "split.json",
         final / "manifest.json"), authority["access_policy"]["must_deny"],
        enforce_acl=enforce_acl, acl_reader=acl_reader,
        identity_resolver=identity_resolver,
        posix_reader_groups=(authority["access_policy"]["group"],),
    )
    items_raw = _dataset_file(final / "items.json", owner_uid=owner_uid,
                              group_gid=dataset_gid, size=output["items_size"],
                              sha=output["items_sha256"])
    split_raw = _dataset_file(final / "split.json", owner_uid=owner_uid,
                              group_gid=dataset_gid, size=output["split_size"],
                              sha=output["split_sha256"])
    if digest(items_raw + b"\0" + split_raw) != output["dataset_sha256"]:
        raise InstallBlocked("immutable dataset content-address mismatch")
    manifest_raw = _dataset_file(final / "manifest.json", owner_uid=owner_uid,
                                 group_gid=dataset_gid)
    try:
        manifest = json.loads(manifest_raw, object_pairs_hook=unique_object,
                              parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise InstallBlocked("immutable dataset manifest invalid") from exc
    invariants = authority["invariants"]
    required_manifest = {
        "schema_version", "dataset_sha256", "dataset_family", "source_commit",
        "sources", "source_sha256", "item_count", "split_counts", "split_hash",
        "files", "access_policy",
    }
    if (not isinstance(manifest, dict) or set(manifest) != required_manifest
            or manifest.get("schema_version") != 1
            or manifest.get("dataset_sha256") != output["dataset_sha256"]
            or manifest.get("dataset_family") != authority["dataset_family"]
            or manifest.get("source_commit") != authority["source_commit"]
            or manifest.get("sources") != authority["sources"]
            or manifest.get("source_sha256") != authority["source_combined_sha256"]
            or manifest.get("item_count") != invariants["item_count"]
            or manifest.get("split_counts") != invariants["split_counts"]
            or manifest.get("split_hash") != invariants["split_hash"]
            or manifest.get("access_policy") != authority["access_policy"]
            or manifest.get("files") != [
                {"path": "items.json", "size": len(items_raw), "sha256": digest(items_raw)},
                {"path": "split.json", "size": len(split_raw), "sha256": digest(split_raw)},
            ]):
        raise InstallBlocked("immutable dataset manifest binding mismatch")
    return final


def install_directories() -> None:
    # Parents supplied by macOS are checked, never recursively chowned.
    require_real_dir(Path("/Library/Application Support"), owner_uid=0)
    require_real_dir(Path("/Users/superagent"))
    make_dir(BOOTSTRAP_ROOT, "root", "wheel", 0o755)
    make_dir(CONFIG_ROOT, "root", "wheel", 0o755)
    make_dir(STAGING_ROOT, "root", "wheel", 0o700)
    make_dir(BOOTSTRAP_ROOT / "seal-broker", "root", "wheel", 0o700)
    make_dir(BOOTSTRAP_ROOT / "adapters", "root", "wheel", 0o755)
    make_dir(BOOTSTRAP_ROOT / "adapters/mission-builder",
             "root", "abcr-builder", 0o550)
    make_dir(COMPONENT_ROOT, "root", "wheel", 0o755)
    for component in ("launcher", "seal-broker", "test-controller"):
        make_dir(COMPONENT_ROOT / component, "root", "wheel", 0o755)
        make_dir(COMPONENT_ROOT / component / "slot-a", "root", "wheel", 0o555)
        make_dir(COMPONENT_ROOT / component / "slot-b", "root", "wheel", 0o555)
    make_dir(TRUST_ROOT, "root", "wheel", 0o555)
    make_dir(WORK_ROOT, "root", "wheel", 0o755)
    for stage in STAGES:
        stage_root = WORK_ROOT / stage
        make_dir(stage_root, "root", "wheel", 0o700)
        for state in STATES:
            make_dir(stage_root / state, "root", "wheel", 0o700)

    make_dir(BRIDGE_ROOT, "root", "wheel", 0o755)
    make_dir(BRIDGE_ROOT / "operator-to-human", "abcr-operator", "abcr-human", 0o750)
    make_dir(BRIDGE_ROOT / "human-to-operator", "abcr-human", "abcr-operator", 0o750)
    make_dir(BRIDGE_ROOT / "operator-status", "abcr-operator", "abcr-human", 0o750)

    make_dir(ATTEST_ROOT, "root", "wheel", 0o755)
    attest_children = {
        "test-results": "abcr-verifier", "attestations": "abcr-activator",
        "audit-results": "abcr-operator", "canary-results": "abcr-activator",
        "release-receipts": "abcr-release-read",
        "generic-attestations": "abcr-release-read",
    }
    for child, group in attest_children.items():
        make_dir(ATTEST_ROOT / child, "root", group, 0o750)
    make_dir(APPROVAL_ROOT, "root", "abcr-human", 0o550)

    make_dir(Path("/Library/Application Support/ABCR-DevBundles"),
             "root", "abcr-devread", 0o750)
    make_dir(DATASET_ROOT,
             "root", "abcr-dataset-read", 0o550)
    make_dir(RELEASE_ROOT.parent, "root", "wheel", 0o755)
    make_dir(RELEASE_ROOT, "root", "abcr-release-read", 0o750)
    make_dir(Path("/Users/superagent/.abcr-build"), "root", "wheel", 0o711)
    make_dir(Path("/Users/superagent/.abcr-build/candidates"),
             "abcr-builder", "abcr-builder", 0o700)
    make_dir(Path("/Users/superagent/.abcr-build/builder-tmp"),
             "abcr-builder", "abcr-builder", 0o700)
    make_dir(Path("/Users/superagent/.abcr-build/mission-inputs"),
             "abcr-operator", "abcr-builder-input", 0o750)
    make_dir(Path("/Users/superagent/.abcr-build/candidate-runs"),
             "root", "wheel", 0o711)
    # Existing user parents are never chowned/chmodded.  Precise named search
    # ACEs expose traversal only; they do not expose directory listings.
    user_parents = (Path("/Users/superagent"), Path("/Users/superagent/Library"),
                    Path("/Users/superagent/Library/Application Support"))
    for parent in user_parents:
        require_real_dir(parent, owner_uid=uid("superagent"), writable_mask=0)
    for account in ("abcr-operator", "abcr-auditor", "abcr-panel"):
        for parent in user_parents:
            ensure_search_acl(parent, kind="user", name=account)
    ensure_search_acl(Path("/Users/superagent"), kind="group", name="abcr-release-read")
    make_dir(Path("/Users/superagent/Library/Application Support/ABCR-Control"),
             "abcr-operator", "abcr-panel-read", 0o750)
    make_dir(Path("/Users/superagent/Library/Application Support/ABCR-Evidence"),
             "abcr-operator", "abcr-auditor-read", 0o750)
    for child in ("ledger", "dispatch-queue", "dispatch-state", "runs"):
        make_dir(Path("/Users/superagent/Library/Application Support/ABCR-Evidence") / child,
                 "abcr-operator", "abcr-auditor-read", 0o750)
    for state in ("pending", "running", "done", "failed"):
        make_dir(Path("/Users/superagent/Library/Application Support/ABCR-Evidence") /
                 "dispatch-queue" / state,
                 "abcr-operator", "abcr-auditor-read", 0o750)
    make_dir(Path("/Users/superagent/Library/Application Support/ABCR-Evidence") /
             "dispatch-state" / "runs",
             "abcr-operator", "abcr-auditor-read", 0o750)
    make_dir(Path("/Users/superagent/Library/Application Support/ABCR-Research"),
             "abcr-operator", "abcr-research-read", 0o750)
    make_dir(Path("/Users/superagent/Library/Application Support/ABCR-Research/personas"),
             "abcr-operator", "abcr-research-read", 0o750)
    make_dir(Path("/Users/abcr-probe/Library"), "abcr-probe", "abcr-probe", 0o700)
    make_dir(Path("/Users/abcr-probe/Library/Application Support"),
             "abcr-probe", "abcr-probe", 0o700)
    make_dir(Path("/Users/abcr-probe/Library/Application Support/ABCR-Lab"),
             "abcr-probe", "abcr-lab-read", 0o750)

    staging_owners = {
        "seal_dev_bundle": "abcr-itempool", "seal_test_result": "root",
        "seal_verification": "abcr-verifier", "seal_canary": "abcr-canary",
        "seal_release": "abcr-activator", "seal_approval_bundle": "abcr-auditor",
        "seal_audit_result": "abcr-auditor", "seal_attestation": "abcr-verifier",
    }
    for operation, owner in staging_owners.items():
        make_dir(STAGING_ROOT / operation, owner,
                 "wheel" if owner == "root" else owner, 0o700)
        if owner != "root":
            ensure_search_acl(STAGING_ROOT, kind="user", name=owner)


def queue_config(service: str, settings: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": 1, "service": service, "broker_socket": SOCKET_PATH,
            "settings": settings}


def install_configs(release: Path, dataset_dir: Path) -> None:
    users = {name: uid(name) for name in set(SERVICES.values()) | {"abcr-candidate"}}
    groups = {name: gid(name) for name in (
        "abcr-human", "abcr-operator", "abcr-candidate", "abcr-broker-clients")}
    research_root = Path("/Users/superagent/Library/Application Support/ABCR-Research")
    trust = str(TRUST_ROOT)
    bootstrap = str(BOOTSTRAP_ROOT)
    dev_bundles = "/Library/Application Support/ABCR-DevBundles"
    profile_document = load_release_json(release, "configs/control/test-profiles-v1.json")
    try:
        test_profile = profile_document["profiles"]["status-card-v1"]
    except (KeyError, TypeError) as exc:
        raise InstallBlocked("sealed release lacks frozen status-card test profile") from exc
    path_document = load_release_json(release, "configs/control/path-risk-v1.json")
    if not isinstance(path_document.get("paths"), dict):
        raise InstallBlocked("sealed release path-risk registry is invalid")
    protocol_path = release / "configs/protocol_ref.txt"
    protocol_ref = protocol_path.read_text(encoding="utf-8").strip()
    if not protocol_ref or len(protocol_ref) > 4096:
        raise InstallBlocked("sealed protocol_ref is invalid")
    probe_profile = load_release_json(
        release, "configs/probe/profiles/qwen25-7b-q4-v1.json")
    probe_profile_id = probe_profile.get("profile_id")
    if not isinstance(probe_profile_id, str) or not probe_profile_id:
        raise InstallBlocked("sealed probe profile lacks profile_id")
    builder_profile_source = release / "ops/sandbox/abcr-builder.sb"
    if builder_profile_source.is_symlink() or not builder_profile_source.is_file():
        raise InstallBlocked("sealed release lacks fixed mission-builder sandbox profile")
    builder_profile_raw = builder_profile_source.read_bytes()
    builder_profile_path = CONFIG_ROOT / "mission-builder.sb"
    atomic_bytes(builder_profile_path, builder_profile_raw,
                 owner="root", group="abcr-builder", mode=0o440)

    config: dict[str, dict[str, Any]] = {}
    config["operator-reconciler"] = queue_config("operator-reconciler", {
        "store_path": "/Users/superagent/Library/Application Support/ABCR-Control/control.sqlite3",
        "interval_seconds": 1.0,
        "human_uid": users["abcr-human"], "operator_uid": users["abcr-operator"],
        "human_gid": groups["abcr-human"], "operator_gid": groups["abcr-operator"],
        "research_repo": str(research_root / "repo"),
        "research_memory_path": str(research_root / "research-memory.jsonl"),
        "artifact_receipt_private_key": f"{bootstrap}/artifact-receipt/private.pem",
        "artifact_receipt_public_key": f"{trust}/artifact-receipt.pub",
        "approval_public_key": f"{trust}/approval.pub",
        "ledger_root": "/Users/superagent/Library/Application Support/ABCR-Evidence/ledger",
        "dispatch_queue_root": "/Users/superagent/Library/Application Support/ABCR-Evidence/dispatch-queue",
        "dispatch_state_root": "/Users/superagent/Library/Application Support/ABCR-Evidence/dispatch-state",
        "evidence_runs_root": "/Users/superagent/Library/Application Support/ABCR-Evidence/runs",
        "sealed_audit_root": str(ATTEST_ROOT / "audit-results"),
        "broker_receipt_root": str(RECEIPT_ROOT),
        "broker_receipt_group_gid": gid("abcr-release-read"),
        "auditor_public_key": f"{trust}/auditor-attestation.pub",
        "dispatch_supervisor_qualified": False,
        "release_id": release.name,
        # Qualification writes a complete sealed profile into this root-owned
        # config.  Null is an explicit compile BLOCKED state, never a local-model
        # substitution or a permission to spend cloud budget.
        "execution_profile": None,
        "persona_root": str(research_root / "personas"),
        "trusted_dev_bundle_root": dev_bundles,
        "bundle_sealer_public_key": f"{trust}/dev-bundle-sealer.pub",
        "research_group_gid": gid("abcr-research-read"),
        "deployment_id": "abcr-w1-macmini", "protocol_ref": protocol_ref,
        "probe_profile_id": probe_profile_id,
        "probe_max_output_tokens": 256,
        "trusted_release_root": str(RELEASE_ROOT),
        "mission_input_root": "/Users/superagent/.abcr-build/mission-inputs",
        "mission_input_group_gid": gid("abcr-builder-input"),
    })
    config["probe-worker"] = queue_config("probe-worker", {
        "profile_path": str(release / "configs/probe/profiles/qwen25-7b-q4-v1.json"),
        "trusted_dev_bundle_root": dev_bundles,
        "bundle_sealer_public_key": f"{trust}/dev-bundle-sealer.pub",
        "lab_root": "/Users/abcr-probe/Library/Application Support/ABCR-Lab",
    })
    config["itempool"] = queue_config("itempool", {
        "dataset_path": str(dataset_dir / "items.json"),
        "split_path": str(dataset_dir / "split.json"),
        "output_root": str(STAGING_ROOT / "seal_dev_bundle"),
        "sealer_private_key": f"{bootstrap}/keys/itempool/sealer.pem",
        "sealer_public_key": f"{trust}/dev-bundle-sealer.pub",
    })
    config["auditor"] = queue_config("auditor", {
        "trusted_dev_bundle_root": dev_bundles,
        "bundle_sealer_public_key": f"{trust}/dev-bundle-sealer.pub",
        "auditor_private_key": f"{bootstrap}/keys/auditor/attestation.pem",
        "auditor_public_key": f"{trust}/auditor-attestation.pub",
        "research_repo": str(research_root / "repo"),
        "anchor_ledger": str(research_root / "research-memory.jsonl"),
        "anchor_seal_path": f"{trust}/research-memory.seal.json",
        "anchor_sealer_public_key": f"{trust}/research-memory-sealer.pub",
        "approval_staging_root": str(STAGING_ROOT / "seal_approval_bundle"),
        "validator_private_key": f"{bootstrap}/keys/approval-validator/attestation.pem",
        "validator_public_key": f"{trust}/approval-validator.pub",
        "anchor_ledger_owner_uid": users["abcr-operator"],
        "anchor_seal_owner_uid": 0,
        "evidence_runs_root": "/Users/superagent/Library/Application Support/ABCR-Evidence/runs",
        "audit_staging_root": str(STAGING_ROOT / "seal_audit_result"),
    })
    config["mission-builder"] = queue_config("mission-builder", {
        "prepared_base_root": "/Users/superagent/.abcr-build/mission-inputs",
        "prepared_base_owner_uid": users["abcr-operator"],
        "prepared_base_group_gid": gid("abcr-builder-input"),
        "candidate_root": "/Users/superagent/.abcr-build/candidates",
        "sandbox_tmp_root": "/Users/superagent/.abcr-build/builder-tmp",
        "sandbox_profile": str(builder_profile_path),
        "sandbox_profile_sha256": digest(builder_profile_raw),
        "adapter_runtime_root": str(BOOTSTRAP_ROOT / "adapters/mission-builder"),
        "adapter_runtime_owner_uid": 0,
        # No mutable desktop Codex binary is silently trusted.  Qualification
        # must install a finite root-owned adapter, freeze argv/bytes, and bind a
        # root-owned Unix egress-broker policy.  Until then the fixed profile
        # still denies all network and the service doctor remains BLOCKED.
        "codex_argv": [], "codex_argv_sha256": None,
        "codex_executable_sha256": None,
        "autonomous_qualified": False,
        "egress_mode": "deny", "egress_qualified": False,
        "egress_socket": None, "egress_policy_path": None,
        "egress_policy_sha256": None,
    })
    config["test-controller"] = queue_config("test-controller", {
        "profile": test_profile,
        "candidate_argv_template": [
            "{candidate_root}/env/bin/python", "-I", "-m",
            "abcr.control.candidate_oracle_adapter"],
        "oracle_assertions": [{"oracle_id": "status-card-v1", "version": "1",
                               "kind": "equality"}],
        "sandbox_profile": str(release / "ops/sandbox/abcr-candidate.sb"),
        "controller_private_key": f"{bootstrap}/keys/test-controller/attestation.pem",
        "controller_public_key": f"{trust}/test-controller-attestation.pub",
        "candidate_uid": users["abcr-candidate"], "candidate_gid": groups["abcr-candidate"],
        "result_root": str(STAGING_ROOT / "seal_test_result"),
        "trusted_candidate_root": str(ATTEST_ROOT / "generic-attestations"),
        "candidate_run_root": "/Users/superagent/.abcr-build/candidate-runs",
    })
    config["verifier"] = queue_config("verifier", {
        "controller_public_key": f"{trust}/test-controller-attestation.pub",
        "verifier_private_key": f"{bootstrap}/keys/verifier/attestation.pem",
        "verifier_public_key": f"{trust}/verifier-attestation.pub",
        "path_registry": path_document["paths"],
        "trusted_test_result_root": str(ATTEST_ROOT / "test-results"),
        "verification_staging_root": str(STAGING_ROOT / "seal_verification"),
    })
    config["canary-controller"] = queue_config("canary-controller", {
        # 真实封印探针替代旧的显式失败占位;-B 防 root/canary 侧字节码写入。
        "probe_argv": [str(release / "env/bin/python"), "-I", "-B",
                       str(release / "scripts/abcr_genesis_canary_probe.py")],
        "trusted_release_root": str(RELEASE_ROOT),
        "canary_staging_root": str(STAGING_ROOT / "seal_canary"),
    })
    topology = load_release_json(release, "configs/control/service-topology-v1.json")
    topology_services = topology.get("services")
    if not isinstance(topology_services, list):
        raise InstallBlocked("sealed service topology is invalid")
    payload_specs = {item["label"]: {} for item in topology_services
                     if isinstance(item, dict) and isinstance(item.get("label"), str)}
    if set(payload_specs) != set(LABELS):
        raise InstallBlocked("sealed service topology differs from reviewed labels")
    config["release-activator"] = queue_config("release-activator", {
        "verifier_public_key": f"{trust}/verifier-attestation.pub",
        "trusted_candidate_root": str(ATTEST_ROOT / "generic-attestations"),
        "staging_root": str(STAGING_ROOT / "seal_release"),
        "service_payloads": payload_specs, "active_path": ACTIVE_PATH,
        "trusted_verification_root": str(ATTEST_ROOT / "attestations"),
        "trusted_canary_root": str(ATTEST_ROOT / "canary-results"),
        "trusted_release_root": str(RELEASE_ROOT),
    })

    operation_roots = {
        "seal_dev_bundle": dev_bundles,
        "seal_test_result": str(ATTEST_ROOT / "test-results"),
        "seal_verification": str(ATTEST_ROOT / "attestations"),
        "seal_canary": str(ATTEST_ROOT / "canary-results"),
        "seal_release": str(RELEASE_ROOT),
        "seal_approval_bundle": str(APPROVAL_ROOT),
        "seal_audit_result": str(ATTEST_ROOT / "audit-results"),
        "seal_attestation": str(ATTEST_ROOT / "generic-attestations"),
    }
    source_roots = {name: str(STAGING_ROOT / name) for name in operation_roots}
    source_roots["seal_attestation"] = "/Users/superagent/.abcr-build/candidates"
    source_owner_names = {
        "seal_dev_bundle": "abcr-itempool", "seal_test_result": "root",
        "seal_verification": "abcr-verifier", "seal_canary": "abcr-canary",
        "seal_release": "abcr-activator", "seal_approval_bundle": "abcr-auditor",
        "seal_audit_result": "abcr-auditor", "seal_attestation": "abcr-builder",
    }
    source_policies = {
        operation: {"owner_uid": users[owner],
                    "group_gid": gid("wheel" if owner == "root" else owner),
                    "directory_mode": 0o700}
        for operation, owner in source_owner_names.items()
    }
    operation_groups = {
        "seal_dev_bundle": "abcr-devread",
        "seal_test_result": "abcr-verifier",
        "seal_verification": "abcr-activator",
        "seal_canary": "abcr-activator",
        "seal_release": "abcr-release-read",
        "seal_approval_bundle": "abcr-human",
        "seal_audit_result": "abcr-operator",
        "seal_attestation": "abcr-release-read",
    }
    operation_policies = {
        operation: {"owner_uid": 0, "group_gid": gid(group),
                    "directory_mode": 0o550, "file_mode": 0o440,
                    "executable_file_mode": 0o550}
        for operation, group in operation_groups.items()
    }
    allowed = {
        "seal_dev_bundle": [users["abcr-itempool"]],
        "seal_test_result": [users["root"]],
        "seal_verification": [users["abcr-verifier"]],
        "seal_canary": [users["abcr-canary"]],
        "seal_release": [users["abcr-activator"]],
        "seal_approval_bundle": [users["abcr-auditor"]],
        "seal_audit_result": [users["abcr-auditor"]],
        "seal_attestation": [users["abcr-builder"]],
        "activate_release": [users["abcr-activator"]],
        "restart_generation": [users["abcr-operator"]],
        "seal_research_memory": [users["abcr-operator"]],
    }
    stage_names = {
        "itempool": ({"abcr-operator"}, {"abcr-itempool"}),
        "probe": ({"abcr-operator"}, {"abcr-probe"}),
        "audit": ({"abcr-operator"}, {"abcr-auditor"}),
        "mission-build": ({"abcr-operator"}, {"abcr-builder"}),
        "test": ({"abcr-operator"}, {"root"}),
        "verify": ({"abcr-operator"}, {"abcr-verifier"}),
        "release-prepare": ({"abcr-operator"}, {"abcr-activator"}),
        "canary": ({"abcr-operator"}, {"abcr-canary"}),
        "activate": ({"abcr-operator"}, {"abcr-activator"}),
    }
    work_acl = {}
    for stage, (producers, consumers) in stage_names.items():
        work_acl[stage] = {
            "producers": {str(users[name]): name for name in sorted(producers)},
            "consumers": {str(users[name]): name for name in sorted(consumers)},
        }
    config["seal-broker"] = queue_config("seal-broker", {
        "operation_roots": operation_roots, "source_roots": source_roots,
        "operation_policies": operation_policies,
        "source_policies": source_policies,
        "receipt_root": str(RECEIPT_ROOT), "active_path": ACTIVE_PATH,
        "receipt_owner_uid": 0, "receipt_group_gid": gid("abcr-release-read"),
        "socket_path": SOCKET_PATH, "socket_gid": gid("abcr-broker-clients"),
        "work_lease_seconds": 90, "work_max_attempts": 3,
        "allowed_peer_uids": allowed, "work_root": str(WORK_ROOT),
        "work_stage_acl": work_acl,
        "approval_validator_public_key": f"{trust}/approval-validator.pub",
        "restart_generations": {
            "control-plane": [
                {"label": "com.abcr.human-gateway", "uid": users["abcr-human"]},
                {"label": "com.abcr.operator-reconciler", "uid": users["abcr-operator"]},
                {"label": "com.abcr.panel", "uid": users["abcr-panel"]},
            ],
        },
        "research_memory_seal": {
            "ledger_path": str(research_root / "research-memory.jsonl"),
            "seal_path": f"{trust}/research-memory.seal.json",
            "private_key": f"{bootstrap}/seal-broker/research-memory-ed25519.pem",
            "public_key": f"{trust}/research-memory-sealer.pub",
            "ledger_owner_uid": users["abcr-operator"], "trust_owner_uid": 0,
        },
    })

    for service in sorted(config):
        atomic_json(CONFIG_ROOT / f"{service}.json", config[service],
                    group="wheel" if SERVICES[service] == "root" else SERVICES[service])


def verify_release_read_policy(release: Path, manifest: dict[str, Any] | None = None) -> None:
    """Broker must have applied policy before installer accepts the release."""
    release_gid = gid("abcr-release-read")
    declared_modes: dict[str, int] = {}
    if manifest is not None:
        for item in manifest.get("tree_entries", ()):
            if (not isinstance(item, dict) or not isinstance(item.get("path"), str)
                    or type(item.get("mode")) is not int):
                raise InstallBlocked("sealed release manifest entry is invalid")
            declared_modes[item["path"]] = item["mode"]
    for dirpath, dirnames, filenames in os.walk(release, followlinks=False):
        current = Path(dirpath)
        info = current.lstat()
        if (current.is_symlink() or info.st_uid != 0 or info.st_gid != release_gid
                or stat.S_IMODE(info.st_mode) != 0o550):
            raise InstallBlocked("sealed release directory policy is not root:release-read 0550")
        for name in (*dirnames, *filenames):
            path = current / name
            info = path.lstat()
            if (path.is_symlink() or info.st_uid != 0 or info.st_gid != release_gid):
                raise InstallBlocked("sealed release contains a symlink")
            # 封印策略按可执行位分流:seal_broker._apply_policy 用
            # executable_file_mode(0o550)封任何带 x 位的条目,file_mode(0o440)封其余;
            # 而 release.prepare 又**要求** env/bin/python 必须带 x 位。此处若一律要求
            # 0o440,就与这两条硬约束直接矛盾,使**任何合法封印 release 都被拒**、
            # genesis 永远无法完成。期望模式必须与 abcr-launch 的权威口径一致:
            # 由 manifest 声明的源模式派生(有 x 位 → 0o550,否则 0o440)。
            if stat.S_ISDIR(info.st_mode):
                expected = 0o550
            else:
                relative = path.relative_to(release).as_posix()
                declared = declared_modes.get(relative)
                if declared is None:
                    if relative != "release-manifest.json":
                        raise InstallBlocked(
                            f"sealed release contains an undeclared file: {relative}")
                    expected = 0o440
                else:
                    expected = 0o550 if declared & 0o111 else 0o440
            if stat.S_IMODE(info.st_mode) != expected:
                raise InstallBlocked("sealed release mode policy is incomplete")


def initialization_status(release: Path) -> dict[str, Any]:
    human_db = Path("/Users/abcr-human/Library/Application Support/ABCR-Human/human.db")
    operator_db = Path("/Users/superagent/Library/Application Support/ABCR-Control/control.sqlite3")
    ledger = Path("/Users/superagent/Library/Application Support/ABCR-Research/research-memory.jsonl")
    blocked: list[dict[str, str]] = []
    def safe_state(path: Path, owner: str, modes: set[int]) -> bool:
        try:
            info = path.lstat()
        except OSError:
            return False
        return (not path.is_symlink() and stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and info.st_uid == uid(owner) and stat.S_IMODE(info.st_mode) in modes)

    if not safe_state(human_db, "abcr-human", {0o600}):
        blocked.append({"state": "human_db_missing_or_unsafe",
                        "command": (f"sudo -u abcr-human {release}/env/bin/python -I -m "
                                    "abcr.control.human_gateway --init-db")})
    if not safe_state(operator_db, "abcr-operator", {0o600}):
        blocked.append({"state": "operator_db_missing_or_unsafe",
                        "command": (f"sudo -u abcr-operator {release}/env/bin/python -I "
                                    "-m abcr.control.operator --init-db")})
    if not safe_state(ledger, "abcr-operator", {0o600, 0o640}):
        blocked.append({"state": "research_ledger_uninitialized",
                        "command": "由首个 owner-confirmed goal saga 创建；此前审批链保持 BLOCKED"})
    return {"launch_ready": not any(item["state"].startswith(("human_db", "operator_db"))
                                    for item in blocked),
            "blocked_before_launchd": blocked}


def _component_record(component: str, release: Path, receipt: dict[str, Any],
                      manifest: dict[str, Any], generation: int) -> dict[str, Any]:
    modules = {"seal-broker": "abcr.control.seal_broker",
               "test-controller": "abcr.control.test_controller"}
    if component == "launcher":
        target_rel = "scripts/abcr-launch"
        python_rel = python_sha = payload_hash = module = None
    else:
        module = modules[component]
        payloads = manifest.get("service_payloads")
        payload = payloads.get(module) if isinstance(payloads, dict) else None
        if not isinstance(payload, dict):
            raise InstallBlocked(f"release lacks {component} service payload")
        target_rel = payload.get("module_relpath")
        python_rel = payload.get("python_relpath")
        python_sha = payload.get("python_sha256")
        payload_hash = payload.get("payload_tree_hash")
        if (not isinstance(target_rel, str) or not isinstance(python_rel, str)
                or not isinstance(python_sha, str) or not isinstance(payload_hash, str)):
            raise InstallBlocked(f"release has invalid {component} service payload")
    target = release / target_rel
    if target.is_symlink() or not target.is_file():
        raise InstallBlocked(f"release component target missing: {component}")
    target_sha = digest(target.read_bytes())
    if component != "launcher" and target_sha != payload.get("module_sha256"):
        raise InstallBlocked(f"release component target hash mismatch: {component}")
    if python_rel is not None:
        python = release / python_rel
        if python.is_symlink() or not python.is_file() or digest(python.read_bytes()) != python_sha:
            raise InstallBlocked(f"release component interpreter mismatch: {component}")
    return {"schema_version": 1, "component": component, "generation": generation,
            "release_id": manifest["release_id"], "receipt_id": receipt["receipt_id"],
            "target_relpath": target_rel, "target_sha256": target_sha,
            "python_relpath": python_rel, "python_sha256": python_sha,
            "module": module, "payload_tree_hash": payload_hash}


def install_bootstrap_slots(release: Path, receipt: dict[str, Any],
                            manifest: dict[str, Any]) -> dict[str, str]:
    selector = release / "scripts/abcr-bootstrap-selector"
    if selector.is_symlink() or not selector.is_file():
        raise InstallBlocked("sealed bootstrap selector unavailable")
    selector_raw = selector.read_bytes()
    bootstrap_contract = load_release_json(release, "ops/install/bootstrap-v1.json")
    if (bootstrap_contract.get("stable_selector") != str(SELECTOR_PATH)
            or bootstrap_contract.get("stable_selector_sha256") != digest(selector_raw)):
        raise InstallBlocked("sealed bootstrap selector is not bound to bootstrap manifest")
    # Keep the directory mechanically bound to the reviewed selector target.
    # Production still pins SELECTOR_PATH to /usr/local/libexec; tests and a
    # separately reviewed relocation cannot otherwise validate this helper
    # without accidentally touching the host-wide directory.
    libexec = SELECTOR_PATH.parent
    if not libexec.exists():
        libexec.mkdir(mode=0o755)
    require_real_dir(libexec, owner_uid=0)
    if SELECTOR_PATH.exists() or SELECTOR_PATH.is_symlink():
        if SELECTOR_PATH.is_symlink() or not SELECTOR_PATH.is_file():
            raise InstallBlocked("stable bootstrap selector target is unsafe")
        info = SELECTOR_PATH.lstat()
        if (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o555
                or digest(SELECTOR_PATH.read_bytes()) != digest(selector_raw)):
            raise InstallBlocked(
                "stable selector differs; outer-TCB update requires separate reviewed procedure")
    else:
        atomic_bytes(SELECTOR_PATH, selector_raw,
                     owner="root", group="wheel", mode=0o555)

    selected: dict[str, str] = {}
    plans: list[tuple[str, Path, str, int, dict[str, Any]]] = []
    for component in ("launcher", "seal-broker", "test-controller"):
        root = COMPONENT_ROOT / component
        active_path = root / "active-slot.json"
        active = read_json(active_path) if active_path.exists() else None
        if active is not None and active.get("probation") is True:
            raise InstallBlocked(f"unqualified candidate slot already active: {component}")
        active_slot = active.get("slot") if isinstance(active, dict) else None
        candidate_slot = "slot-b" if active_slot == "slot-a" else "slot-a"
        generations = []
        for name in ("slot-a", "slot-b"):
            record_path = root / name / "slot.json"
            if record_path.exists():
                record = read_json(record_path)
                if type(record.get("generation")) is int:
                    generations.append(record["generation"])
        generation = max(generations, default=0) + 1
        record = _component_record(component, release, receipt, manifest, generation)
        plans.append((component, root, candidate_slot, generation, record))

    # Do not mutate any component until all three old states and all three new
    # records have passed validation; a blocked component cannot leave a mixed
    # generation behind.
    for component, root, candidate_slot, generation, record in plans:
        atomic_bytes(root / candidate_slot / "slot.json", canonical(record) + b"\n",
                     owner="root", group="wheel", mode=0o444)
        pointer = {"schema_version": 1, "component": component,
                   "slot": candidate_slot, "generation": generation, "probation": True}
        atomic_bytes(root / "active-slot.json", canonical(pointer) + b"\n",
                     owner="root", group="wheel", mode=0o444)
        selected[component] = candidate_slot
    return selected


def install_plists(release: Path) -> None:

    daemon_root = Path("/Library/LaunchDaemons")
    require_real_dir(daemon_root, owner_uid=0)
    broker_gid = gid("abcr-broker-clients")
    for label in sorted(LABELS):
        source = release / "ops/launchd" / f"{label}.plist"
        if source.is_symlink() or not source.is_file():
            raise InstallBlocked(f"sealed launchd plist missing: {label}")
        with source.open("rb") as stream:
            document = plistlib.load(stream)
        if not isinstance(document, dict) or document.get("Label") != label:
            raise InstallBlocked(f"launchd label mismatch: {label}")
        component = ("seal-broker" if label == "com.abcr.seal-broker" else
                     "test-controller" if label == "com.abcr.test-controller" else "launcher")
        expected_args = ([str(SELECTOR_PATH), component] if component != "launcher"
                         else [str(SELECTOR_PATH), "launcher", label])
        if document.get("ProgramArguments") != expected_args:
            raise InstallBlocked(f"launchd selector route mismatch: {label}")
        if label == "com.abcr.seal-broker":
            listener = document.get("Sockets", {}).get("Listener")
            if not isinstance(listener, dict):
                raise InstallBlocked("seal-broker Listener is missing")
            listener["SockPathGroup"] = broker_gid
            if type(listener["SockPathGroup"]) is not int:
                raise InstallBlocked("SockPathGroup must be an integer gid")
        atomic_bytes(daemon_root / f"{label}.plist",
                     plistlib.dumps(document, fmt=plistlib.FMT_XML, sort_keys=False),
                     owner="root", group="wheel", mode=0o444)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-reviewed", metavar="AUTHORITY_SHA")
    parser.add_argument("--receipt-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.install_reviewed != AUTHORITY_SHA:
            raise InstallBlocked("reviewed authority SHA is required")
        if sys.platform != "darwin" or os.geteuid() != 0:
            raise InstallBlocked("production runtime install requires macOS root")
        receipt, release, manifest = verify_receipt(args.receipt_id)
        # Accounts and all named groups are a prior, separately reviewed gate.
        for name in set(SERVICES.values()) | {"abcr-candidate"}:
            uid(name)
        for name in (
            "wheel", "staff", "abcr-panel-read", "abcr-auditor-read",
            "abcr-research-read", "abcr-lab-read", "abcr-devread",
            "abcr-dataset-read", "abcr-release-read", "abcr-broker-clients",
            "abcr-builder-input",
        ):
            gid(name)
        verify_release_read_policy(release, manifest)
        # Dataset bytes are intentionally absent from this shared code release.
        # Require the separately reviewed, content-addressed import before the
        # first filesystem mutation so a missing/scientifically stale dataset
        # cannot leave a partially installed production runtime.
        dataset_authority = load_dataset_authority(release)
        # This is an observation-only gate.  An unexpected direct, GUID,
        # nested, primary or otherwise effective member blocks the installer;
        # privileged installation never silently edits directory membership.
        validate_exact_dataset_reader_group(dataset_authority["access_policy"])
        dataset_dir = validate_installed_dataset(
            DATASET_ROOT, dataset_authority, owner_uid=0,
            dataset_gid=gid("abcr-dataset-read"))
        install_directories()
        install_configs(release, dataset_dir)
        slots = install_bootstrap_slots(release, receipt, manifest)
        install_plists(release)
        state = initialization_status(release)
        print(json.dumps({"ok": True, "release_id": manifest["release_id"],
                          "configs": sorted(QUEUE_SERVICES),
                          "bootstrap_candidate_slots": slots,
                          "bootstrap_qualified": False,
                          "launchd_loaded": False, "services_started": False,
                          **state}, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__,
                          "message": str(exc)}, sort_keys=True), file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
