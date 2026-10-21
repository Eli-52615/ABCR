"""On-demand exact-evidence auditor backed by the fenced ABCR-Work queue."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from abcr.audit.evidence import audit_evidence
from abcr.control.contracts import ContractError, require_id, require_sha, strict_object
from abcr.control.work_spool import WORK_ID, SpoolError, WorkSpool
from abcr.explore.item_pool import DevBundleRef


class AuditServiceError(RuntimeError):
    """Configuration or queue-layout defect (safe to report by class only)."""


DEFAULT_CONFIG_PATH = Path(
    "/Library/Application Support/ABCR-Bootstrap/config/auditor.json")
CONFIG_ENV = "ABCR_AUDITOR_CONFIG_PATH"
PATH_ENVS = frozenset({
    "ABCR_WORK_ROOT", "ABCR_DEVBUNDLE_ROOT", "ABCR_ITEMPOOL_SEALER_PUBLIC_KEY",
    "ABCR_AUDITOR_PRIVATE_KEY", "ABCR_AUDITOR_PUBLIC_KEY", CONFIG_ENV,
})


@dataclass(frozen=True)
class AuditServiceConfig:
    work_root: Path
    trusted_dev_bundle_root: Path
    bundle_sealer_public_key: Path
    auditor_private_key: Path
    auditor_public_key: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AuditServiceConfig":
        source = os.environ if env is None else env

        def required(name: str) -> Path:
            value = source.get(name)
            if not isinstance(value, str) or not value.strip():
                raise AuditServiceError(f"missing trusted setting: {name}")
            return Path(value)

        return cls(
            work_root=required("ABCR_WORK_ROOT"),
            trusted_dev_bundle_root=required("ABCR_DEVBUNDLE_ROOT"),
            bundle_sealer_public_key=required("ABCR_ITEMPOOL_SEALER_PUBLIC_KEY"),
            auditor_private_key=required("ABCR_AUDITOR_PRIVATE_KEY"),
            auditor_public_key=required("ABCR_AUDITOR_PUBLIC_KEY"),
        )

    @classmethod
    def from_secure_file(cls, path: Path, *, owner_uid: int) -> "AuditServiceConfig":
        obj = strict_object(
            _read_secure_json(path, owner_uid=owner_uid),
            required={"work_root", "trusted_dev_bundle_root", "bundle_sealer_public_key",
                      "auditor_private_key", "auditor_public_key"},
        )
        if not all(isinstance(value, str) and value for value in obj.values()):
            raise AuditServiceError("trusted config paths must be non-empty strings")
        return cls(**{name: Path(value) for name, value in obj.items()})

    def validate(self) -> None:
        _require_directory(self.work_root, "work root")
        _require_directory(self.work_root / "audit" / "ready", "audit ready queue")
        _require_directory(self.trusted_dev_bundle_root, "trusted dev-bundle root")
        _require_regular(self.bundle_sealer_public_key, "bundle sealer public key")
        _require_regular(self.auditor_private_key, "auditor private key", private=True)
        _require_regular(self.auditor_public_key, "auditor public key")


def _require_directory(path: Path, label: str) -> None:
    try:
        info = Path(path).lstat()
    except OSError as exc:
        raise AuditServiceError(f"missing {label}") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise AuditServiceError(f"unsafe {label}")


def _require_regular(path: Path, label: str, *, private: bool = False) -> None:
    try:
        info = Path(path).lstat()
    except OSError as exc:
        raise AuditServiceError(f"missing {label}") from exc
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_nlink != 1):
        raise AuditServiceError(f"unsafe {label}")
    if private and stat.S_IMODE(info.st_mode) & 0o077:
        raise AuditServiceError(f"unsafe permissions for {label}")


def _read_secure_json(path: Path, *, owner_uid: int) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise AuditServiceError("cannot open trusted auditor config") from exc
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != owner_uid
                or stat.S_IMODE(before.st_mode) not in {0o600, 0o440}
                or before.st_size > 64 * 1024):
            raise AuditServiceError("unsafe trusted auditor config")
        chunks: list[bytes] = []
        remaining = before.st_size + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_nlink,
                                 info.st_uid, stat.S_IMODE(info.st_mode))
        if len(raw) != before.st_size or identity(before) != identity(after):
            raise AuditServiceError("trusted auditor config changed while reading")
    finally:
        os.close(fd)

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise AuditServiceError("duplicate key in trusted auditor config")
            out[key] = value
        return out

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditServiceError("invalid trusted auditor config") from exc
    if not isinstance(value, dict):
        raise AuditServiceError("trusted auditor config must be an object")
    return value


def load_config(env: Mapping[str, str] | None = None) -> AuditServiceConfig:
    source = os.environ if env is None else env
    if source.get("ABCR_SERVICE_LABEL"):
        if any(source.get(name) for name in PATH_ENVS):
            raise AuditServiceError("environment override forbidden for launched service")
        return AuditServiceConfig.from_secure_file(DEFAULT_CONFIG_PATH, owner_uid=0)
    if source.get(CONFIG_ENV):
        return AuditServiceConfig.from_secure_file(Path(source[CONFIG_ENV]),
                                                   owner_uid=os.getuid())
    if any(source.get(name) for name in PATH_ENVS - {CONFIG_ENV}):
        return AuditServiceConfig.from_env(source)
    return AuditServiceConfig.from_secure_file(DEFAULT_CONFIG_PATH, owner_uid=0)


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if (not isinstance(value, list) or not value
            or not all(isinstance(item, str) and item for item in value)
            or len(value) != len(set(value))):
        raise ContractError("invalid_sequence", f"{field} 必须是不重复的非空字符串数组")
    return tuple(value)


def _seed_tuple(value: Any) -> tuple[int, ...]:
    if (not isinstance(value, list) or not value
            or not all(type(item) is int for item in value)
            or len(value) != len(set(value))):
        raise ContractError("invalid_sequence", "seeds 必须是不重复的整数数组")
    return tuple(value)


def _rows(value: Any, field: str, *, step: bool = False) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ContractError("invalid_rows", f"{field} 必须是非空对象数组")
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict) or not all(isinstance(key, str) for key in row):
            raise ContractError("invalid_row", f"{field}[{index}] 必须是字符串键对象")
        for key in ("item_id", "condition"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ContractError("invalid_row", f"{field}[{index}].{key} 类型不合法")
        if type(row.get("random_seed")) is not int:
            raise ContractError("invalid_row", f"{field}[{index}].random_seed 类型不合法")
        if step:
            if not isinstance(row.get("prompt_hash"), str) or not row["prompt_hash"]:
                raise ContractError("invalid_row", f"{field}[{index}].prompt_hash 类型不合法")
            if not isinstance(row.get("output_text"), str) or not row["output_text"]:
                raise ContractError("invalid_row", f"{field}[{index}].output_text 类型不合法")
        rows.append(dict(row))
    return rows


def _dev_bundle(value: Any, trusted_root: Path) -> DevBundleRef:
    obj = strict_object(
        value,
        required={"bundle_id", "manifest_hash", "item_ids", "source_hash"},
    )
    require_sha(obj["bundle_id"], "dev_bundle.bundle_id")
    require_sha(obj["manifest_hash"], "dev_bundle.manifest_hash")
    require_sha(obj["source_hash"], "dev_bundle.source_hash")
    item_ids = _string_tuple(obj["item_ids"], "dev_bundle.item_ids")
    # Deliberately derive root here.  A payload field named root/path is unknown and rejected.
    return DevBundleRef(obj["bundle_id"], trusted_root / obj["bundle_id"],
                        obj["manifest_hash"], item_ids, obj["source_hash"])


def parse_request(payload: Any, config: AuditServiceConfig) -> dict[str, Any]:
    obj = strict_object(
        payload,
        required={"batch_id", "item_ids", "seeds", "conditions", "steps", "scores",
                  "sidecars", "dev_bundle"},
    )
    require_id(obj["batch_id"], "batch_id")
    return {
        "batch_id": obj["batch_id"],
        "item_ids": _string_tuple(obj["item_ids"], "item_ids"),
        "seeds": _seed_tuple(obj["seeds"]),
        "conditions": _string_tuple(obj["conditions"], "conditions"),
        "steps": _rows(obj["steps"], "steps", step=True),
        "scores": _rows(obj["scores"], "scores"),
        "sidecars": _rows(obj["sidecars"], "sidecars"),
        "dev_bundle": _dev_bundle(obj["dev_bundle"], config.trusted_dev_bundle_root),
    }


def handle(payload: Any, config: AuditServiceConfig) -> dict[str, Any]:
    request = parse_request(payload, config)
    attestation = audit_evidence(
        **request,
        trusted_dev_bundle_root=config.trusted_dev_bundle_root,
        bundle_sealer_public_key=config.bundle_sealer_public_key,
        auditor_private_key=config.auditor_private_key,
        auditor_public_key=config.auditor_public_key,
    )
    return asdict(attestation)


def process_once(spool: WorkSpool, work_id: str, config: AuditServiceConfig) -> bool:
    claim = spool.claim("audit", work_id)
    if claim is None:
        return False
    try:
        result = {"ok": True, "result": handle(claim.payload, config)}
    except Exception as exc:
        code = exc.code if isinstance(exc, ContractError) else type(exc).__name__
        result = {"ok": False, "error_code": code}
    spool.submit_result(claim, result, consumer="abcr-auditor")
    spool.ack(claim)
    return True


def inspect_ready(config: AuditServiceConfig) -> tuple[tuple[str, ...], tuple[Path, ...]]:
    ready = config.work_root / "audit" / "ready"
    out: list[str] = []
    blocked: list[Path] = []
    for path in sorted(ready.iterdir(), key=lambda candidate: candidate.name):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if (not path.name.startswith(".") and path.suffix == ".json"
                and WORK_ID.fullmatch(path.stem) is not None
                and stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                and info.st_nlink == 1):
            out.append(path.stem)
        else:
            blocked.append(path)
    return tuple(out), tuple(blocked)


def ready_work_ids(config: AuditServiceConfig) -> tuple[str, ...]:
    return inspect_ready(config)[0]


def _quarantine_invalid(config: AuditServiceConfig, paths: tuple[Path, ...]) -> int:
    quarantine = config.work_root / "audit" / "quarantine"
    moved = 0
    for path in paths:
        digest = hashlib.sha256(path.name.encode("utf-8", errors="surrogateescape")).hexdigest()[:16]
        target = quarantine / f"invalid-{digest}-{uuid.uuid4().hex}.entry"
        try:
            os.rename(path, target)
            moved += 1
        except FileNotFoundError:
            continue
    return moved


def run(config: AuditServiceConfig, *, once: bool = False) -> int:
    config.validate()
    work_ids, invalid = inspect_ready(config)
    if once:
        work_ids = work_ids[:1]
    spool = WorkSpool(config.work_root)
    _quarantine_invalid(config, invalid)
    for work_id in work_ids:
        try:
            process_once(spool, work_id, config)
        except SpoolError:
            continue
    return len(work_ids)


def doctor(config: AuditServiceConfig) -> dict[str, Any]:
    """Read-only semantic check; no WorkSpool construction and no network access."""
    config.validate()
    _, invalid = inspect_ready(config)
    return {"ok": not invalid, "service": "abcr-auditor", "queue": "audit",
            "blocked_entries": len(invalid)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--doctor", action="store_true")
    mode.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config()
        if args.doctor:
            print(json.dumps(doctor(config), ensure_ascii=False, sort_keys=True))
            return 0
        run(config, once=args.once)
        return 0
    except (AuditServiceError, ContractError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "service": "abcr-auditor",
                          "error_code": type(exc).__name__}, sort_keys=True), file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
