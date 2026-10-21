"""Fail-closed scientific-data exclusion for immutable code releases.

Code releases are shared by principals that must never receive the frozen
benchmark, split or golden answers.  A per-service ``payload_files`` manifest is
not an access-control boundary: the sealed directory still exists on disk.
This module therefore checks the *whole* candidate/release tree, including
package archives, before either the activator or the root seal broker accepts it.
"""
from __future__ import annotations

import bz2
import gzip
import io
import lzma
import os
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable

from abcr.control.contracts import ContractError, sha256
from abcr.control.worktree import TreeEntry, scan_tree


# Current W1 frozen scientific inputs.  Path checks catch canonical and ordinary
# package-resource locations; these byte identities catch exact renamed copies.
# Adding/replacing a frozen dataset requires a reviewed code/contract update.
FROZEN_SCIENTIFIC_SHA256 = frozenset({
    # Authority-normalized immutable item-pool inputs.  These are every bit as
    # sensitive as the reviewed source bytes and must not re-enter a code
    # release after a harmless-looking rename or archive wrap.
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

_SENSITIVE_SEGMENTS = frozenset({
    "benchmark", "benchmarks", "golden", "goldens", "golden_answers",
    "split", "splits",
})
_DATA_SUFFIXES = frozenset({
    ".arrow", ".bin", ".csv", ".json", ".jsonl", ".npy", ".npz",
    ".parquet", ".pt", ".safetensors", ".tsv", ".txt", ".yaml", ".yml",
})
_MAX_ARCHIVE_MEMBERS = 100_000
_MAX_ARCHIVE_MEMBER_BYTES = 128 * 1024 * 1024
_MAX_ARCHIVE_TOTAL_BYTES = 512 * 1024 * 1024
_MAX_ARCHIVE_DEPTH = 2
_UNSUPPORTED_ARCHIVE_MAGIC = (
    b"\x28\xb5\x2f\xfd",       # zstd
    b"\x37\x7a\xbc\xaf\x27\x1c",  # 7z
    b"Rar!\x1a\x07",           # rar4/rar5
    b"\x04\x22\x4d\x18",       # lz4 frame
)


def _safe_name(value: str, *, container: str) -> PurePosixPath:
    if not value or "\\" in value or "\x00" in value:
        raise ContractError("release_archive_path_invalid",
                            "release archive member path 不合法",
                            {"container": container})
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ContractError("release_archive_path_invalid",
                            "release archive member path 逃逸",
                            {"container": container})
    return pure


def _scientific_path(value: str, *, container: str) -> None:
    pure = _safe_name(value, container=container)
    parts = tuple(part.casefold() for part in pure.parts)
    basename = parts[-1]
    stem = PurePosixPath(basename).stem
    suffix = PurePosixPath(basename).suffix
    sensitive = any(part in _SENSITIVE_SEGMENTS for part in parts)
    data_named = (suffix in _DATA_SUFFIXES
                  and (stem.startswith("golden")
                       or stem in {"split", "splits", "benchmark", "benchmarks"}))
    if sensitive or data_named:
        raise ContractError("release_scientific_path_forbidden",
                            "code release 禁止包含 benchmark/split/golden resource",
                            {"path": value, "container": container})


def _check_digest(raw: bytes, *, name: str, container: str) -> None:
    if sha256(raw) in FROZEN_SCIENTIFIC_SHA256:
        raise ContractError("release_scientific_bytes_forbidden",
                            "code release 含冻结科学数据的重命名副本",
                            {"path": name, "container": container})


def _archive_limit(condition: bool, *, container: str) -> None:
    if condition:
        raise ContractError("release_archive_limits",
                            "release archive 超出受审扫描上限",
                            {"container": container})


def _scan_zip(raw: bytes, *, container: str, depth: int) -> bool:
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            _archive_limit(len(members) > _MAX_ARCHIVE_MEMBERS, container=container)
            total = 0
            for member in members:
                if member.is_dir():
                    continue
                _scientific_path(member.filename, container=container)
                # Unix-mode symlinks and encrypted entries are never legitimate
                # immutable Python package resources.
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode) or member.flag_bits & 0x1:
                    raise ContractError("release_archive_member_unsafe",
                                        "release archive 含 symlink/encrypted member",
                                        {"container": container})
                _archive_limit(member.file_size > _MAX_ARCHIVE_MEMBER_BYTES,
                               container=container)
                total += member.file_size
                _archive_limit(total > _MAX_ARCHIVE_TOTAL_BYTES, container=container)
                member_raw = archive.read(member)
                if len(member_raw) != member.file_size:
                    raise ContractError("release_archive_member_unsafe",
                                        "release archive member 长度漂移",
                                        {"container": container})
                _check_digest(member_raw, name=member.filename, container=container)
                _scan_archive(member_raw,
                              container=f"{container}!/{member.filename}",
                              depth=depth + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("release_archive_invalid",
                            "release zip/wheel resource 无法完整扫描",
                            {"container": container}) from exc
    return True


def _scan_tar(raw: bytes, *, container: str, depth: int) -> bool:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(raw), mode="r:*")
    except tarfile.ReadError:
        return False
    try:
        members = archive.getmembers()
        _archive_limit(len(members) > _MAX_ARCHIVE_MEMBERS, container=container)
        by_name: dict[str, tarfile.TarInfo] = {}
        for member in members:
            normalized = _safe_name(member.name, container=container).as_posix()
            if normalized in by_name:
                raise ContractError("release_archive_member_unsafe",
                                    "release tar resource 含重复 member",
                                    {"container": container})
            by_name[normalized] = member
        total = 0
        for member in members:
            if member.isdir():
                continue
            _scientific_path(member.name, container=container)
            if member.issym() or not (member.isfile() or member.islnk()):
                raise ContractError("release_archive_member_unsafe",
                                    "release tar resource 含 symlink/特殊文件",
                                    {"container": container})
            expected_size = member.size
            if member.islnk():
                # Python packages such as dateutil legitimately use tar
                # hardlink members.  Treat the archive as data, never recreate
                # links: the target must be one unambiguous in-archive regular
                # member and its resolved bytes are scanned again under the
                # alias name.  This retains renamed-dataset detection without
                # rejecting a stock frozen dependency.
                target_name = _safe_name(
                    member.linkname, container=container).as_posix()
                target = by_name.get(target_name)
                if target is None or not target.isfile():
                    raise ContractError("release_archive_member_unsafe",
                                        "release tar hardlink target 不安全",
                                        {"container": container})
                expected_size = target.size
            _archive_limit(expected_size > _MAX_ARCHIVE_MEMBER_BYTES,
                           container=container)
            total += expected_size
            _archive_limit(total > _MAX_ARCHIVE_TOTAL_BYTES, container=container)
            stream = archive.extractfile(member)
            if stream is None:
                raise ContractError("release_archive_member_unsafe",
                                    "release tar member 不可读取",
                                    {"container": container})
            member_raw = stream.read(_MAX_ARCHIVE_MEMBER_BYTES + 1)
            if len(member_raw) != expected_size:
                raise ContractError("release_archive_member_unsafe",
                                    "release tar member 长度漂移",
                                    {"container": container})
            _check_digest(member_raw, name=member.name, container=container)
            _scan_archive(member_raw,
                          container=f"{container}!/{member.name}",
                          depth=depth + 1)
    except (OSError, tarfile.TarError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("release_archive_invalid",
                            "release tar resource 无法完整扫描",
                            {"container": container}) from exc
    finally:
        archive.close()
    return True


def _scan_stream_compression(raw: bytes, *, container: str, depth: int) -> bool:
    """Open common single-stream compression with the same finite limit.

    A gzip/bzip2/xz stream is just as capable of hiding a renamed frozen input
    as a wheel or tarball.  Read through bounded stdlib file objects so a
    compression bomb is rejected before recursive inspection.
    """
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
            expanded = stream.read(_MAX_ARCHIVE_MEMBER_BYTES + 1)
            if len(expanded) > _MAX_ARCHIVE_MEMBER_BYTES or stream.read(1):
                raise ContractError("release_archive_limits",
                                    "release 压缩流超出受审扫描上限",
                                    {"container": container})
    except (OSError, EOFError, lzma.LZMAError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("release_archive_invalid",
                            "release 压缩流无法完整扫描",
                            {"container": container}) from exc
    _check_digest(expanded, name=container, container=container)
    _scan_archive(expanded, container=f"{container}!/<compressed-stream>",
                  depth=depth + 1)
    return True


def _scan_archive(raw: bytes, *, container: str, depth: int = 0) -> None:
    if depth > _MAX_ARCHIVE_DEPTH:
        # Ordinary members at the deepest reviewed level are fine.  Another
        # archive is not: silently stopping recursion would create a trivial
        # archive-in-archive bypass for scientific resources.
        nested_archive = (zipfile.is_zipfile(io.BytesIO(raw))
                          or raw.startswith((b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00"))
                          or raw.startswith(_UNSUPPORTED_ARCHIVE_MAGIC))
        if not nested_archive:
            try:
                probe = tarfile.open(fileobj=io.BytesIO(raw), mode="r:*")
            except (OSError, tarfile.TarError):
                pass
            else:
                nested_archive = True
                probe.close()
        if nested_archive:
            raise ContractError("release_archive_limits",
                                "release archive 嵌套层级超限",
                                {"container": container})
        return
    if _scan_zip(raw, container=container, depth=depth):
        return
    if _scan_tar(raw, container=container, depth=depth):
        return
    if _scan_stream_compression(raw, container=container, depth=depth):
        return
    if raw.startswith(_UNSUPPORTED_ARCHIVE_MAGIC):
        raise ContractError("release_archive_unsupported",
                            "release 含无法受审展开的压缩格式",
                            {"container": container})


def _read_exact(root: Path, entry: TreeEntry) -> bytes:
    path = root / entry.path
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
                 | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size != entry.size
                or stat.S_IMODE(before.st_mode) != entry.mode):
            raise ContractError("release_policy_file_drift",
                                "release policy 扫描时 inode 漂移")
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
                                 item.st_nlink, stat.S_IMODE(item.st_mode))
        if identity(before) != identity(after) or len(raw) != entry.size:
            raise ContractError("release_policy_file_drift",
                                "release policy 扫描时文件发生变化")
        return raw
    finally:
        os.close(fd)


def enforce_release_content_policy(
        root: Path, entries: Iterable[TreeEntry] | None = None) -> None:
    """Reject scientific data in the entire plain/sealed release tree."""
    root = Path(root)
    observed = tuple(scan_tree(root) if entries is None else entries)
    for entry in observed:
        _scientific_path(entry.path, container="release-tree")
        if entry.sha256 in FROZEN_SCIENTIFIC_SHA256:
            raise ContractError("release_scientific_bytes_forbidden",
                                "code release 含冻结科学数据的重命名副本",
                                {"path": entry.path, "container": "release-tree"})
        raw = _read_exact(root, entry)
        if sha256(raw) != entry.sha256:
            raise ContractError("release_policy_file_drift",
                                "release policy 扫描 hash 漂移")
        _scan_archive(raw, container=entry.path)
