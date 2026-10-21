"""Typed, fenced, content-addressed work queues between OS principals."""
from __future__ import annotations

import json
import os
import re
import stat
import uuid
from datetime import datetime, timedelta, timezone
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
    def __init__(self, root: Path, *, create: bool = True):
        self.root = Path(root)
        for stage in STAGES:
            for state in STATES:
                path = self.root / stage / state
                if create:
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    try:
                        info = path.lstat()
                    except OSError as exc:
                        raise SpoolError("pre-provisioned spool directory missing") from exc
                    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                        raise SpoolError("pre-provisioned spool directory unsafe")

    def _dir(self, stage: str, state: str) -> Path:
        if stage not in STAGES or state not in STATES:
            raise SpoolError("unknown stage/state")
        return self.root / stage / state

    def enqueue(self, stage: str, work_id: str, payload: dict[str, Any], *, attempt: int = 1,
                fencing_token: int = 1, producer: str = "operator") -> Path:
        if WORK_ID.fullmatch(work_id) is None:
            raise SpoolError("invalid work_id")
        if (type(attempt) is not int or type(fencing_token) is not int
                or attempt < 1 or fencing_token < 1):
            raise SpoolError("attempt and fencing_token must be positive integers")
        if not isinstance(payload, dict):
            raise SpoolError("payload must be an object")
        envelope = {"schema_version": 1, "stage": stage, "work_id": work_id,
                    "attempt": attempt, "fencing_token": fencing_token,
                    "producer": producer, "payload": payload, "payload_hash": sha256(payload),
                    "created_at": utc_now()}
        raw = canonical_json(envelope) + b"\n"
        ready = self._dir(stage, "ready")
        dst = ready / f"{work_id}.json"
        # A producer may replay after its predecessor crashed just after enqueue.
        # Compare every lifecycle location so replay cannot recreate work that is
        # already inflight or archived.
        existing = [self._dir(stage, state) / dst.name
                    for state in ("ready", "inflight", "archive")
                    if (self._dir(stage, state) / dst.name).exists()]
        if len(existing) > 1:
            raise SpoolError("work identity exists in multiple states")
        if existing:
            current = existing[0]
            info = current.lstat()
            if current.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise SpoolError("existing work envelope unsafe")
            old = json.loads(current.read_text(encoding="utf-8"))
            comparable = {k: old.get(k) for k in envelope if k != "created_at"}
            expected = {k: v for k, v in envelope.items() if k != "created_at"}
            if comparable != expected:
                raise SpoolError("conflicting replay")
            return current
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
            required = {"schema_version", "stage", "work_id", "attempt", "fencing_token",
                        "producer", "payload", "payload_hash", "created_at"}
            keys = set(env) if isinstance(env, dict) else set()
            if (not isinstance(env, dict)
                    or (keys != required and keys != required | {"heartbeat_at"})
                    or env.get("schema_version") != 1
                    or type(env.get("attempt")) is not int
                    or type(env.get("fencing_token")) is not int
                    or env["attempt"] < 1 or env["fencing_token"] < 1
                    or not isinstance(env.get("producer"), str)
                    or not isinstance(env.get("payload"), dict)):
                raise SpoolError("envelope schema invalid")
            if env.get("stage") != stage or env.get("work_id") != work_id:
                raise SpoolError("envelope identity mismatch")
            if env.get("payload_hash") != sha256(env.get("payload")):
                raise SpoolError("payload hash mismatch")
            env["heartbeat_at"] = utc_now()
            tmp = dst.with_name(f".{dst.name}.{uuid.uuid4().hex}.tmp")
            try:
                with tmp.open("xb") as stream:
                    stream.write(canonical_json(env) + b"\n")
                    stream.flush(); os.fsync(stream.fileno())
                os.replace(tmp, dst); _sync_dir(dst.parent)
            finally:
                tmp.unlink(missing_ok=True)
            return Claim(stage, work_id, env["attempt"], env["fencing_token"],
                         dst, env["payload"])
        except Exception as exc:
            quarantine = self._dir(stage, "quarantine") / dst.name
            os.replace(dst, quarantine)
            raise SpoolError(f"poison work quarantined: {exc}") from exc

    def recover_expired(self, stage: str, *, lease_seconds: int,
                        max_attempts: int, now: datetime | None = None) -> tuple[int, int]:
        """Requeue stale uncompleted claims with a fresh fence; quarantine poison/exhausted."""
        if (stage not in STAGES or type(lease_seconds) is not int or lease_seconds < 10
                or type(max_attempts) is not int or max_attempts < 1):
            raise SpoolError("invalid recovery policy")
        current_time = now or datetime.now(timezone.utc)
        cutoff = current_time - timedelta(seconds=lease_seconds)
        requeued = quarantined = 0
        inflight = self._dir(stage, "inflight")
        for path in sorted(inflight.glob("*.json")):
            if (self._dir(stage, "results") / path.name).exists():
                continue
            try:
                info = path.lstat()
                envelope = json.loads(path.read_text(encoding="utf-8"))
                required = {"schema_version", "stage", "work_id", "attempt",
                            "fencing_token", "producer", "payload", "payload_hash",
                            "created_at"}
                keys = set(envelope) if isinstance(envelope, dict) else set()
                if (not isinstance(envelope, dict)
                        or (keys != required and keys != required | {"heartbeat_at"})
                        or envelope.get("schema_version") != 1
                        or envelope.get("stage") != stage
                        or envelope.get("work_id") != path.stem
                        or not isinstance(envelope.get("producer"), str)
                        or not isinstance(envelope.get("payload"), dict)
                        or envelope.get("payload_hash") != sha256(envelope.get("payload"))):
                    raise ValueError("invalid inflight envelope")
                stamp = envelope.get("heartbeat_at") or envelope.get("created_at")
                observed = datetime.fromisoformat(stamp)
                if (path.is_symlink() or not stat.S_ISREG(info.st_mode)
                        or info.st_nlink != 1 or observed.tzinfo is None):
                    raise ValueError("unsafe inflight envelope")
                if observed > cutoff:
                    continue
                if (type(envelope.get("attempt")) is not int
                        or type(envelope.get("fencing_token")) is not int):
                    raise ValueError("invalid fence")
                if envelope["attempt"] >= max_attempts:
                    os.replace(path, self._dir(stage, "quarantine") / path.name)
                    quarantined += 1
                    continue
                envelope["attempt"] += 1
                envelope["fencing_token"] += 1
                envelope.pop("heartbeat_at", None)
                envelope["created_at"] = current_time.isoformat()
                tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
                try:
                    with tmp.open("xb") as stream:
                        stream.write(canonical_json(envelope) + b"\n")
                        stream.flush(); os.fsync(stream.fileno())
                    os.replace(tmp, path)
                finally:
                    tmp.unlink(missing_ok=True)
                destination = self._dir(stage, "ready") / path.name
                if destination.exists():
                    raise ValueError("ready identity already exists")
                os.replace(path, destination)
                requeued += 1
            except Exception:
                if path.exists():
                    quarantine = self._dir(stage, "quarantine") / path.name
                    if quarantine.exists():
                        quarantine = quarantine.with_name(
                            f"{quarantine.stem}.{uuid.uuid4().hex}.json")
                    os.replace(path, quarantine)
                quarantined += 1
        if requeued:
            _sync_dir(self._dir(stage, "ready"))
        if quarantined:
            _sync_dir(self._dir(stage, "quarantine"))
        return requeued, quarantined

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

    def read_result(self, stage: str, work_id: str, *, attempt: int,
                    fencing_token: int) -> dict[str, Any]:
        """Return one immutable result after rechecking its complete fence binding."""
        if stage not in STAGES or WORK_ID.fullmatch(work_id) is None:
            raise SpoolError("invalid result identity")
        path = self._dir(stage, "results") / f"{work_id}.json"
        try:
            info = path.lstat()
            if (path.is_symlink() or not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1 or info.st_size > 16 * 1024 * 1024):
                raise SpoolError("result envelope metadata unsafe")
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SpoolError("result envelope unavailable") from exc
        required = {"schema_version", "stage", "work_id", "attempt", "fencing_token",
                    "consumer", "result", "result_hash", "completed_at"}
        if (not isinstance(envelope, dict) or set(envelope) != required
                or envelope.get("schema_version") != 1
                or (envelope.get("stage"), envelope.get("work_id")) != (stage, work_id)
                or (envelope.get("attempt"), envelope.get("fencing_token"))
                != (attempt, fencing_token)
                or not isinstance(envelope.get("consumer"), str)
                or not isinstance(envelope.get("result"), dict)
                or envelope.get("result_hash") != sha256(envelope.get("result"))):
            raise SpoolError("result envelope binding invalid")
        return envelope

    def ack(self, claim: Claim, *, expected_result_hash: str | None = None) -> Path:
        envelope = self.read_result(claim.stage, claim.work_id, attempt=claim.attempt,
                                    fencing_token=claim.fencing_token)
        if (expected_result_hash is not None
                and envelope["result_hash"] != expected_result_hash):
            raise SpoolError("producer ack result hash mismatch")
        result = self._dir(claim.stage, "results") / f"{claim.work_id}.json"
        ack = self._dir(claim.stage, "acks") / f"{claim.work_id}.json"
        raw = canonical_json({"work_id": claim.work_id, "attempt": claim.attempt,
                              "fencing_token": claim.fencing_token,
                              "result_hash": envelope["result_hash"],
                              "acked_at": utc_now()}) + b"\n"
        tmp = ack.with_name(f".{ack.name}.{uuid.uuid4().hex}.tmp")
        try:
            with tmp.open("xb") as fh:
                fh.write(raw); fh.flush(); os.fsync(fh.fileno())
            os.replace(tmp, ack); _sync_dir(ack.parent)
        finally: tmp.unlink(missing_ok=True)
        os.replace(claim.path, self._dir(claim.stage, "archive") / claim.path.name)
        return ack
