"""Typed, fenced, content-addressed work queues between OS principals."""
from __future__ import annotations

import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from abcr.control.contracts import canonical_json, sha256, utc_now

STAGES = ("itempool", "probe", "audit", "mission-build", "test", "verify",
          "release-prepare", "canary", "activate")
STATES = ("ready", "inflight", "results", "acks", "quarantine", "archive")
WORK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


class SpoolError(RuntimeError):
    pass


@dataclass(frozen=True)
class Claim:
    stage: str
    work_id: str
    attempt: int
    fencing_token: int
    path: Path
    payload: dict[str, Any]


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class WorkSpool:
    def __init__(self, root: Path):
        self.root = Path(root)
        for stage in STAGES:
            for state in STATES:
                (self.root / stage / state).mkdir(parents=True, exist_ok=True)

    def _dir(self, stage: str, state: str) -> Path:
        if stage not in STAGES or state not in STATES:
            raise SpoolError("unknown stage/state")
        return self.root / stage / state

    def enqueue(self, stage: str, work_id: str, payload: dict[str, Any], *, attempt: int = 1,
                fencing_token: int = 1, producer: str = "operator") -> Path:
        if WORK_ID.fullmatch(work_id) is None:
            raise SpoolError("invalid work_id")
        if isinstance(attempt, bool) or attempt < 1 or fencing_token < 1:
            raise SpoolError("attempt and fencing_token must be positive integers")
        envelope = {"schema_version": 1, "stage": stage, "work_id": work_id,
                    "attempt": attempt, "fencing_token": fencing_token,
                    "producer": producer, "payload": payload, "payload_hash": sha256(payload),
                    "created_at": utc_now()}
        raw = canonical_json(envelope) + b"\n"
        ready = self._dir(stage, "ready")
        dst = ready / f"{work_id}.json"
        if dst.exists():
            old = json.loads(dst.read_text(encoding="utf-8"))
            comparable = {k: old.get(k) for k in envelope if k != "created_at"}
            expected = {k: v for k, v in envelope.items() if k != "created_at"}
            if comparable != expected:
                raise SpoolError("conflicting replay")
            return dst
        tmp = ready / f".{work_id}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            with tmp.open("xb") as fh:
                fh.write(raw)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, dst)
            _sync_dir(ready)
        finally:
            tmp.unlink(missing_ok=True)
        return dst

    def claim(self, stage: str, work_id: str) -> Claim | None:
        src = self._dir(stage, "ready") / f"{work_id}.json"
        dst = self._dir(stage, "inflight") / f"{work_id}.json"
        try:
            os.rename(src, dst)
            _sync_dir(dst.parent)
        except FileNotFoundError:
            return None
        try:
            info = dst.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise SpoolError("work envelope is not a single-link regular file")
            env = json.loads(dst.read_text(encoding="utf-8"))
            if env.get("stage") != stage or env.get("work_id") != work_id:
                raise SpoolError("envelope identity mismatch")
            if env.get("payload_hash") != sha256(env.get("payload")):
                raise SpoolError("payload hash mismatch")
            return Claim(stage, work_id, int(env["attempt"]), int(env["fencing_token"]),
                         dst, env["payload"])
        except Exception as exc:
            quarantine = self._dir(stage, "quarantine") / dst.name
            os.replace(dst, quarantine)
            raise SpoolError(f"poison work quarantined: {exc}") from exc

    def submit_result(self, claim: Claim, result: dict[str, Any], *, consumer: str) -> Path:
        expected_parent = self._dir(claim.stage, "inflight").resolve()
        if claim.path.parent.resolve() != expected_parent or claim.path.is_symlink():
            raise SpoolError("claim path is outside its inflight stage")
        current = json.loads(claim.path.read_text(encoding="utf-8"))
        if (current["attempt"], current["fencing_token"]) != (claim.attempt, claim.fencing_token):
            raise SpoolError("stale fencing result")
        envelope = {"schema_version": 1, "stage": claim.stage, "work_id": claim.work_id,
                    "attempt": claim.attempt, "fencing_token": claim.fencing_token,
                    "consumer": consumer, "result": result, "result_hash": sha256(result),
                    "completed_at": utc_now()}
        out = self._dir(claim.stage, "results") / f"{claim.work_id}.json"
        raw = canonical_json(envelope) + b"\n"
        if out.exists():
            old = json.loads(out.read_text(encoding="utf-8"))
            comparable = {k: old.get(k) for k in envelope if k != "completed_at"}
            expected = {k: v for k, v in envelope.items() if k != "completed_at"}
            if comparable != expected: raise SpoolError("conflicting result replay")
        if not out.exists():
            tmp = out.with_name(f".{out.name}.{uuid.uuid4().hex}.tmp")
            try:
                with tmp.open("xb") as fh:
                    fh.write(raw); fh.flush(); os.fsync(fh.fileno())
                os.replace(tmp, out); _sync_dir(out.parent)
            finally:
                tmp.unlink(missing_ok=True)
        return out

    def ack(self, claim: Claim) -> Path:
        result = self._dir(claim.stage, "results") / f"{claim.work_id}.json"
        if not result.exists():
            raise SpoolError("cannot ack before result")
        ack = self._dir(claim.stage, "acks") / f"{claim.work_id}.json"
        raw = canonical_json({"work_id": claim.work_id, "attempt": claim.attempt,
                              "fencing_token": claim.fencing_token,
                              "result_hash": sha256(result.read_bytes()),
                              "acked_at": utc_now()}) + b"\n"
        tmp = ack.with_name(f".{ack.name}.{uuid.uuid4().hex}.tmp")
        try:
            with tmp.open("xb") as fh:
                fh.write(raw); fh.flush(); os.fsync(fh.fileno())
            os.replace(tmp, ack); _sync_dir(ack.parent)
        finally: tmp.unlink(missing_ok=True)
        os.replace(claim.path, self._dir(claim.stage, "archive") / claim.path.name)
        return ack
