"""Trusted preparation of a plain, read-only base tree for mission builders.

The launchd ``abcr-builder`` service must never use a sealed release as its
application-level input.  The trusted Operator resolves the fixed release ID,
rejects VCS/private material, exports a tree without Git metadata, normalizes it
to a read-only group view, and only then enqueues its content hash.  The mutable
builder derives the path from ``work_id`` and its root-owned config; a queue
payload can never select an arbitrary source path.
"""
from __future__ import annotations

import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from abcr.control.contracts import ContractError, require_id
from abcr.control.work_spool import WORK_ID
from abcr.control.worktree import (TreeEntry, export_plain_tree, scan_tree,
                                   tree_hash)


_PRIVATE_BASENAMES = frozenset({
    ".env", "id_rsa", "id_ed25519", "credentials", "credentials.json",
})
_PRIVATE_SUFFIXES = (".key", ".pem", ".p12", ".pfx")
_PRIVATE_PREFIXES = (
    "data/benchmarks/", "data/splits/", "evidence/", "ledger/", "runs/",
)


@dataclass(frozen=True)
class PreparedMissionBase:
    mission_id: str
    release_id: str
    base_tree_hash: str


def _real_directory(path: Path, *, owner_uid: int, group_gid: int | None,
                    modes: set[int], code: str) -> Path:
    raw = Path(path)
    try:
        resolved = raw.resolve(strict=True)
        info = raw.lstat()
    except OSError as exc:
        raise ContractError(code, "mission base directory 不可用") from exc
    if (not raw.is_absolute() or raw.is_symlink() or resolved != raw.absolute()
            or not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid
            or (group_gid is not None and info.st_gid != group_gid)
            or stat.S_IMODE(info.st_mode) not in modes):
        raise ContractError(code, "mission base directory owner/mode/path 不安全")
    return resolved


def _normalized_entry(entry: TreeEntry) -> TreeEntry:
    mode = 0o550 if entry.mode & 0o111 else 0o440
    return TreeEntry(entry.path, mode, entry.size, entry.sha256)


def _validate_immutable_release_tree(root: Path, *, owner_uid: int) -> None:
    root_info = root.lstat()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        for path in (current, *(current / name for name in dirnames),
                     *(current / name for name in filenames)):
            info = path.lstat()
            if (path.is_symlink() or info.st_uid != owner_uid
                    or info.st_dev != root_info.st_dev
                    or stat.S_IMODE(info.st_mode) & 0o222):
                raise ContractError("mission_base_release_unsafe",
                                    "base release 必须是同 mount、同 owner 的不可写 plain tree")


def _reject_private_material(entries: tuple[TreeEntry, ...]) -> None:
    rejected: list[str] = []
    for entry in entries:
        lowered = entry.path.lower()
        basename = lowered.rsplit("/", 1)[-1]
        if (basename in _PRIVATE_BASENAMES or basename.startswith(".env.")
                or basename.endswith(_PRIVATE_SUFFIXES)
                or any(lowered.startswith(prefix) for prefix in _PRIVATE_PREFIXES)):
            rejected.append(entry.path)
    if rejected:
        raise ContractError("mission_base_private_material",
                            "builder plain base 含私钥、账本或科学数据",
                            {"paths": rejected[:32], "count": len(rejected)})


def _make_read_only(root: Path, *, reader_gid: int) -> None:
    """Normalize the export without following links or crossing a mount."""
    root_info = root.lstat()
    for dirpath, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
        current = Path(dirpath)
        for name in filenames:
            path = current / name
            info = path.lstat()
            if (path.is_symlink() or not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1 or info.st_dev != root_info.st_dev):
                raise ContractError("mission_base_export_unsafe",
                                    "plain base 只允许同 mount 单链接 regular file")
            os.chown(path, -1, reader_gid)
            os.chmod(path, 0o550 if stat.S_IMODE(info.st_mode) & 0o111 else 0o440)
        for name in dirnames:
            path = current / name
            info = path.lstat()
            if path.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_dev != root_info.st_dev:
                raise ContractError("mission_base_export_unsafe",
                                    "plain base 只允许同 mount 真实目录")
            os.chown(path, -1, reader_gid)
            os.chmod(path, 0o550)
    # Keep the unpublished temporary root private and owner-writable so macOS
    # can atomically rename it.  The caller exposes it to the reader group only
    # after publication; child entries are already immutable at this point.
    os.chmod(root, 0o700)


def _discard_export(root: Path) -> None:
    """Make only this coordinator-created temporary tree removable."""
    if root.is_symlink() or not root.name.startswith("."):
        raise ContractError("mission_base_cleanup_unsafe", "拒绝清理非临时 mission base")
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        os.chmod(current, 0o700)
        for name in filenames:
            path = current / name
            if path.is_symlink():
                path.unlink()
            else:
                os.chmod(path, 0o600)
        for name in dirnames:
            path = current / name
            if path.is_symlink():
                path.unlink()
            else:
                os.chmod(path, 0o700)
    shutil.rmtree(root)


@dataclass(frozen=True)
class TrustedMissionCoordinator:
    """Operator-only sealed-release resolver and plain-tree exporter."""

    release_root: Path
    prepared_root: Path
    coordinator_uid: int
    reader_gid: int
    release_owner_uid: int = 0

    def prepare(self, *, mission_id: str, release_id: str) -> PreparedMissionBase:
        require_id(mission_id, "mission_id")
        require_id(release_id, "release_id")
        if WORK_ID.fullmatch(mission_id) is None or WORK_ID.fullmatch(release_id) is None:
            raise ContractError("mission_base_identity_invalid", "mission/release identity 不合法")
        releases = _real_directory(
            Path(self.release_root), owner_uid=self.release_owner_uid, group_gid=None,
            modes={0o750, 0o550, 0o755, 0o555}, code="mission_release_root_unsafe")
        prepared = _real_directory(
            Path(self.prepared_root), owner_uid=self.coordinator_uid,
            group_gid=self.reader_gid, modes={0o750}, code="mission_input_root_unsafe")

        source = releases / release_id
        try:
            source_info = source.lstat()
        except OSError as exc:
            raise ContractError("mission_base_release_missing", "固定 base release 不存在") from exc
        if (source.is_symlink() or source.resolve() != source.absolute()
                or source.parent.resolve() != releases
                or not stat.S_ISDIR(source_info.st_mode)
                or source_info.st_uid != self.release_owner_uid
                or stat.S_IMODE(source_info.st_mode) & 0o222):
            raise ContractError("mission_base_release_unsafe", "固定 base release owner/mode/path 不安全")

        # export_plain_tree excludes VCS metadata.  Everything else is inspected
        # first, so a release cannot smuggle keys, evidence or frozen datasets
        # into the builder's otherwise plain candidate view.
        _validate_immutable_release_tree(source, owner_uid=self.release_owner_uid)
        source_entries = scan_tree(source, exclude_vcs=True)
        _reject_private_material(source_entries)
        expected_hash = tree_hash(_normalized_entry(item) for item in source_entries)
        destination = prepared / mission_id
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_dir():
                raise ContractError("mission_base_replay_conflict", "已有 mission base 类型冲突")
            destination_info = destination.lstat()
            if (destination_info.st_uid != self.coordinator_uid
                    or destination_info.st_gid != self.reader_gid
                    or stat.S_IMODE(destination_info.st_mode) != 0o550):
                raise ContractError("mission_base_replay_conflict",
                                    "已有 mission base owner/mode 漂移")
            if tree_hash(scan_tree(destination)) != expected_hash:
                raise ContractError("mission_base_replay_conflict", "已有 mission base 内容冲突")
            return PreparedMissionBase(mission_id, release_id, expected_hash)

        temporary = prepared / f".{mission_id}.{uuid.uuid4().hex}.tmp"
        try:
            export_plain_tree(source, temporary)
            _make_read_only(temporary, reader_gid=self.reader_gid)
            if tree_hash(scan_tree(temporary)) != expected_hash:
                raise ContractError("mission_base_export_drift", "plain base 导出后 hash 漂移")
            try:
                os.rename(temporary, destination)
                os.chown(destination, -1, self.reader_gid)
                os.chmod(destination, 0o550)
            except FileExistsError:
                if destination.is_symlink() or not destination.is_dir():
                    raise ContractError("mission_base_replay_conflict", "并发 base 类型冲突")
                if tree_hash(scan_tree(destination)) != expected_hash:
                    raise ContractError("mission_base_replay_conflict", "并发 base 内容冲突")
        finally:
            if temporary.exists():
                # A failed finite-tree export contains no secret material, but it
                # must not remain mutable/readable to the worker.
                _discard_export(temporary)
        return PreparedMissionBase(mission_id, release_id, expected_hash)
