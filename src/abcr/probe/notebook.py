"""Append-only notebook with one atomically published finite-tree bundle per row."""
from __future__ import annotations

import json
import fcntl
import os
import uuid
from pathlib import Path
from typing import Any

from abcr.control.contracts import ContractError, canonical_json, sha256, utc_now


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


class ProbeNotebook:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.rows = self.root / "rows"
        self.rows.mkdir(parents=True, exist_ok=True)
        self.index = self.root / "lab-notebook.jsonl"

    def append(self, row: dict[str, Any]) -> Path:
        if row.get("citable") is not False or row.get("evidence_class") != "exploratory_learning_only":
            raise ContractError("probe_citable_forbidden", "probe 行必须永久标记不可引用")
        supplied = row.get("row_hash")
        core = {k: v for k, v in row.items() if k != "row_hash"}
        expected = sha256(core)
        if supplied != expected:
            raise ContractError("probe_row_hash", "row_hash 必须排除自身后重算")
        final = self.rows / expected
        manifest = {"schema_version": 1, "row_hash": expected,
                    "files": [{"path": "row.json", "sha256": sha256(canonical_json(row)),
                               "size": len(canonical_json(row))}], "created_at": utc_now()}
        if not final.exists():
            tmp = self.rows / f".{expected}.{uuid.uuid4().hex}.tmp"
            tmp.mkdir(mode=0o700)
            try:
                (tmp / "row.json").write_bytes(canonical_json(row))
                (tmp / "manifest.json").write_bytes(canonical_json(manifest))
                for child in tmp.iterdir():
                    with child.open("rb") as fh: os.fsync(fh.fileno())
                _fsync_dir(tmp)
                os.rename(tmp, final)
                _fsync_dir(self.rows)
            finally:
                if tmp.exists():
                    for child in tmp.iterdir(): child.unlink()
                    tmp.rmdir()
        else:
            if self.read(expected) != row:
                raise ContractError("probe_row_collision", "已有 row bundle 与重放内容冲突")
        lock_path = self.root / "lab-notebook.lock"
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            if not self._indexed(expected):
                entry = {"row_hash": expected, "bundle": str(final.name), "indexed_at": utc_now()}
                with self.index.open("ab") as fh:
                    fh.write(canonical_json(entry) + b"\n"); fh.flush(); os.fsync(fh.fileno())
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return final

    def _indexed(self, row_hash: str) -> bool:
        if not self.index.exists(): return False
        return any(json.loads(line).get("row_hash") == row_hash for line in self.index.read_bytes().splitlines())

    def read(self, row_hash: str) -> dict[str, Any]:
        if len(row_hash) != 64 or any(c not in "0123456789abcdef" for c in row_hash):
            raise ContractError("bad_row_hash", "row hash 格式不合法")
        path = self.rows / row_hash / "row.json"
        row = json.loads(path.read_text(encoding="utf-8"))
        core = {k: v for k, v in row.items() if k != "row_hash"}
        if row.get("row_hash") != sha256(core):
            raise ContractError("probe_row_tampered", "probe notebook 行已被修改")
        return row
