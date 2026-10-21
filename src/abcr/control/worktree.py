"""Plain-tree export and trusted diff reconstruction without candidate Git access."""
from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from abcr.control.contracts import ContractError, sha256
from abcr.control.policy import normalize_changed_path

VCS_NAMES = frozenset({".git", ".hg", ".svn"})


@dataclass(frozen=True)
class TreeEntry:
    path: str
    mode: int
    size: int
    sha256: str


def _read_regular(path: Path, expected: os.stat_result) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        observed = os.fstat(fd)
        if ((observed.st_dev, observed.st_ino, observed.st_size, observed.st_nlink)
                != (expected.st_dev, expected.st_ino, expected.st_size, expected.st_nlink)):
            raise ContractError("tree_toctou", "tree entry changed during scan", {"path": str(path)})
        with os.fdopen(fd, "rb", closefd=False) as fh: return fh.read()
    finally: os.close(fd)


def scan_tree(root: Path, *, exclude_vcs: bool = False) -> tuple[TreeEntry, ...]:
    raw_root = Path(root)
    if raw_root.is_symlink():
        raise ContractError("unsafe_tree_root", "tree root 不能是 symlink")
    root = raw_root.resolve()
    root_info = root.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or root.is_symlink():
        raise ContractError("unsafe_tree_root", "tree root 必须是真实目录")
    out: list[TreeEntry] = []
    inodes: set[tuple[int, int]] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        current_info = current.lstat()
        if not stat.S_ISDIR(current_info.st_mode) or current_info.st_dev != root_info.st_dev:
            raise ContractError("tree_mount_crossing", "tree 目录跨 mount 或类型异常")
        accepted_dirs = []
        for name in sorted(dirnames):
            path = current / name
            rel = path.relative_to(root).as_posix()
            if name in VCS_NAMES:
                if exclude_vcs: continue
                raise ContractError("git_metadata_forbidden", "plain tree 禁止 VCS metadata", {"path": rel})
            info = path.lstat()
            if path.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_dev != root_info.st_dev:
                raise ContractError("unsafe_tree_directory", "tree 只允许同 mount 真实目录", {"path": rel})
            accepted_dirs.append(name)
        dirnames[:] = accepted_dirs
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = normalize_changed_path(path.relative_to(root).as_posix())
            if name in VCS_NAMES:
                if exclude_vcs: continue
                raise ContractError("git_metadata_forbidden", "plain tree 禁止 VCS metadata", {"path": rel})
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_dev != root_info.st_dev:
                raise ContractError("unsafe_tree_entry", "tree 只允许单链接 regular file", {"path": rel})
            identity = (info.st_dev, info.st_ino)
            if identity in inodes: raise ContractError("tree_hardlink", "tree 包含 hardlink", {"path": rel})
            inodes.add(identity)
            raw = _read_regular(path, info)
            out.append(TreeEntry(rel, stat.S_IMODE(info.st_mode), len(raw), sha256(raw)))
    return tuple(out)


def tree_hash(entries: Iterable[TreeEntry]) -> str:
    return sha256([entry.__dict__ for entry in sorted(entries, key=lambda x: x.path)])


def export_plain_tree(source: Path, destination: Path) -> str:
    source = Path(source).resolve(); destination = Path(destination)
    if destination.exists(): raise ContractError("destination_exists", "plain tree 目标必须不存在")
    destination.mkdir(parents=True, mode=0o700)
    for entry in scan_tree(source, exclude_vcs=True):
        src = source / entry.path; dst = destination / entry.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        with src.open("rb") as inp, dst.open("xb") as out: shutil.copyfileobj(inp, out)
        os.chmod(dst, entry.mode)
    return tree_hash(scan_tree(destination))


def reconstruct_diff(base: Path, candidate: Path, *, allowed_globs: tuple[str, ...]) -> dict:
    import fnmatch
    before = {x.path: x for x in scan_tree(base)}
    after = {x.path: x for x in scan_tree(candidate)}
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    violations = [path for path in changed if not any(fnmatch.fnmatch(path, glob) for glob in allowed_globs)]
    if violations: raise ContractError("changed_path_forbidden", "candidate 修改了 allowlist 外路径",
                                       {"paths": violations})
    return {"base_tree_hash": tree_hash(before.values()), "candidate_tree_hash": tree_hash(after.values()),
            "changed_paths": changed, "deleted_paths": sorted(set(before) - set(after)),
            "added_paths": sorted(set(after) - set(before))}
