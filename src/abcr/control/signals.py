"""Typed desired-state controls for pause, resume and abort."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from abcr.control.contracts import ContractError, canonical_json, sha256, utc_now

DESIRED = frozenset({"running", "paused", "aborted"})


@dataclass(frozen=True)
class DesiredRunState:
    run_id: str
    desired: str
    generation: int
    release_id: str
    actor_id: str
    reason: str
    updated_at: str
    record_hash: str


class RunControl:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        if not run_id or "/" in run_id or ".." in run_id:
            raise ContractError("bad_run_id", "run_id 不合法")
        return self.root / f"{run_id}.json"

    def read(self, run_id: str) -> DesiredRunState | None:
        path = self._path(run_id)
        if not path.exists(): return None
        row = json.loads(path.read_text(encoding="utf-8"))
        digest = row.pop("record_hash")
        if sha256(row) != digest: raise ContractError("run_control_tampered", "运行控制记录损坏")
        return DesiredRunState(**row, record_hash=digest)

    def set(self, run_id: str, desired: str, *, release_id: str, actor_id: str,
            reason: str) -> DesiredRunState:
        if desired not in DESIRED: raise ContractError("bad_desired_state", "目标运行状态不合法")
        old = self.read(run_id)
        if old and old.desired == "aborted" and desired != "aborted":
            raise ContractError("abort_terminal", "已中止 run 不能恢复")
        if old and old.release_id != release_id:
            raise ContractError("release_pin_mismatch", "恢复不能更换原 run 的 release")
        core = {"run_id": run_id, "desired": desired,
                "generation": (old.generation + 1) if old else 1,
                "release_id": release_id, "actor_id": actor_id, "reason": reason,
                "updated_at": utc_now()}
        row = dict(core, record_hash=sha256(core))
        path = self._path(run_id); tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with tmp.open("xb") as fh:
                fh.write(canonical_json(row) + b"\n"); fh.flush(); os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally: tmp.unlink(missing_ok=True)
        return DesiredRunState(**row)
