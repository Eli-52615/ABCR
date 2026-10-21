"""On-demand exact-evidence auditor backed by the fenced ABCR-Work queue.

Direct :class:`WorkSpool` helpers are explicit fixtures.  Production ``main`` sees
only opaque broker claims and never opens or enumerates the spool hierarchy.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from abcr.audit.evidence import _production_expected_keys, audit_evidence
from abcr.control.contracts import (ContractError, canonical_json, require_id,
                                    require_sha, sha256, strict_object)
from abcr.control.ed25519 import ApprovalRequestBundle
from abcr.control.validated_approval_bundle import validator_validate_and_sign
from abcr.control.work_spool import WORK_ID, SpoolError, WorkSpool
from abcr.control.worktree import scan_tree, tree_hash
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
    research_repo: Path | None = None
    anchor_ledger: Path | None = None
    anchor_seal_path: Path | None = None
    anchor_sealer_public_key: Path | None = None
    approval_staging_root: Path | None = None
    validator_private_key: Path | None = None
    validator_public_key: Path | None = None
    anchor_ledger_owner_uid: int | None = None
    anchor_seal_owner_uid: int | None = None
    evidence_runs_root: Path | None = None
    audit_staging_root: Path | None = None

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
        self.validate_resources()

    def validate_resources(self) -> None:
        """Validate the auditor UID's keys and read-only evidence roots only."""
        _require_directory(self.trusted_dev_bundle_root, "trusted dev-bundle root")
        _require_access(self.trusted_dev_bundle_root, os.R_OK | os.X_OK,
                        "trusted dev-bundle root")
        _require_regular(self.bundle_sealer_public_key, "bundle sealer public key")
        _require_access(self.bundle_sealer_public_key, os.R_OK, "bundle sealer public key")
        _require_regular(self.auditor_private_key, "auditor private key", private=True)
        _require_access(self.auditor_private_key, os.R_OK, "auditor private key")
        _require_regular(self.auditor_public_key, "auditor public key")
        _require_access(self.auditor_public_key, os.R_OK, "auditor public key")

    def validate_evidence_resources(self) -> None:
        if self.evidence_runs_root is None or self.audit_staging_root is None:
            raise AuditServiceError("evidence audit trusted settings missing")
        _require_directory(Path(self.evidence_runs_root), "evidence runs root")
        _require_access(Path(self.evidence_runs_root), os.R_OK | os.X_OK,
                        "evidence runs root")
        _require_directory(Path(self.audit_staging_root), "audit staging root")
        staging = Path(self.audit_staging_root).lstat()
        if (staging.st_uid != os.geteuid() or stat.S_IMODE(staging.st_mode) & 0o077):
            raise AuditServiceError("unsafe owner or permissions for audit staging root")
        _require_access(Path(self.audit_staging_root), os.R_OK | os.W_OK | os.X_OK,
                        "audit staging root")

    def validate_approval_resources(self) -> None:
        fields = {
            "research repo": self.research_repo,
            "anchor ledger": self.anchor_ledger,
            "anchor external seal": self.anchor_seal_path,
            "anchor sealer public key": self.anchor_sealer_public_key,
            "approval staging root": self.approval_staging_root,
            "validator private key": self.validator_private_key,
            "validator public key": self.validator_public_key,
        }
        if any(path is None for path in fields.values()):
            raise AuditServiceError("approval validator trusted settings missing")
        if (type(self.anchor_ledger_owner_uid) is not int
                or type(self.anchor_seal_owner_uid) is not int
                or self.anchor_ledger_owner_uid < 0 or self.anchor_seal_owner_uid < 0):
            raise AuditServiceError("approval validator owner ids invalid")
        _require_directory(Path(self.research_repo), "research repo")
        _require_access(Path(self.research_repo), os.R_OK | os.X_OK, "research repo")
        _require_directory(Path(self.approval_staging_root), "approval staging root")
        staging_info = Path(self.approval_staging_root).lstat()
        if (staging_info.st_uid != os.geteuid()
                or stat.S_IMODE(staging_info.st_mode) & 0o022):
            raise AuditServiceError("unsafe owner or permissions for approval staging root")
        _require_access(Path(self.approval_staging_root), os.R_OK | os.W_OK | os.X_OK,
                        "approval staging root")
        for path, label, private in (
            (self.anchor_ledger, "anchor ledger", False),
            (self.anchor_seal_path, "anchor external seal", False),
            (self.anchor_sealer_public_key, "anchor sealer public key", False),
            (self.validator_private_key, "validator private key", True),
            (self.validator_public_key, "validator public key", False),
        ):
            _require_regular(Path(path), label, private=private)
            _require_access(Path(path), os.R_OK, label)


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
    if private and (stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.geteuid()):
        raise AuditServiceError(f"unsafe owner or permissions for {label}")


def _require_access(path: Path, mode: int, label: str) -> None:
    if not os.access(path, mode):
        raise AuditServiceError(f"unavailable access for {label}")


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
        raise AuditServiceError(
            "environment override forbidden: fixture spool config in launched service")
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
                  "sidecars", "dev_bundle", "compile_envelope"},
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
        "compile_envelope": obj["compile_envelope"],
    }


def _approval_bundle(value: Any) -> ApprovalRequestBundle:
    obj = strict_object(value, required={
        "request_id", "goal_bytes_b64", "goal_sha256", "research_commit",
        "artifact_frozen_receipt", "envelope", "envelope_sha256",
        "anchor_prefix_proof",
    })
    if (not isinstance(obj["artifact_frozen_receipt"], dict)
            or not isinstance(obj["envelope"], dict)
            or not isinstance(obj["anchor_prefix_proof"], list)
            or any(not isinstance(item, str) or not item
                   for item in obj["anchor_prefix_proof"])):
        raise ContractError("approval_request_wire_invalid",
                            "ApprovalRequestBundle wire 不合法")
    return ApprovalRequestBundle(
        obj["request_id"], obj["goal_bytes_b64"], obj["goal_sha256"],
        obj["research_commit"], obj["artifact_frozen_receipt"], obj["envelope"],
        obj["envelope_sha256"], tuple(obj["anchor_prefix_proof"]),
    )


def _validate_approval(payload: Any, config: AuditServiceConfig) -> dict[str, Any]:
    obj = strict_object(payload, required={"kind", "bundle"})
    if obj["kind"] != "approval_validation":
        raise ContractError("audit_kind_unknown", "audit kind 不合法")
    config.validate_approval_resources()
    return validator_validate_and_sign(
        _approval_bundle(obj["bundle"]),
        research_repo=Path(config.research_repo),
        anchor_ledger=Path(config.anchor_ledger),
        anchor_ledger_owner_uid=config.anchor_ledger_owner_uid,
        anchor_seal_path=Path(config.anchor_seal_path),
        anchor_sealer_public_key=Path(config.anchor_sealer_public_key),
        anchor_seal_owner_uid=config.anchor_seal_owner_uid,
        validator_private_key=Path(config.validator_private_key),
        validator_public_key=Path(config.validator_public_key),
    )


def _handle_evidence(payload: Any, config: AuditServiceConfig) -> dict[str, Any]:
    request = parse_request(payload, config)
    attestation = audit_evidence(
        **request,
        trusted_dev_bundle_root=config.trusted_dev_bundle_root,
        bundle_sealer_public_key=config.bundle_sealer_public_key,
        auditor_private_key=config.auditor_private_key,
        auditor_public_key=config.auditor_public_key,
    )
    return asdict(attestation)


MAX_COMPILE_ENVELOPE_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_FILE_BYTES = 64 * 1024 * 1024
MAX_EVIDENCE_ROWS = 250_000


def _bounded_jsonl(path: Path, *, label: str) -> list[dict[str, Any]]:
    """Read one known evidence file without following links or accepting races."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ContractError("evidence_file_unavailable", f"{label} 不可达") from exc
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size <= 0 or before.st_size > MAX_EVIDENCE_FILE_BYTES
                or stat.S_IMODE(before.st_mode) & 0o002):
            raise ContractError("evidence_file_unsafe", f"{label} inode/大小不安全")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk); remaining -= len(chunk)
        after = os.fstat(fd)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_nlink,
                                 item.st_uid, item.st_gid, stat.S_IMODE(item.st_mode))
        raw = b"".join(chunks)
        if len(raw) != before.st_size or identity(before) != identity(after):
            raise ContractError("evidence_file_changed", f"{label} 读取期间变化")
    finally:
        os.close(fd)
    rows: list[dict[str, Any]] = []
    try:
        for index, line in enumerate(raw.splitlines()):
            if index >= MAX_EVIDENCE_ROWS:
                raise ContractError("evidence_rows_exceeded", f"{label} 行数超限")
            value = json.loads(line, object_pairs_hook=lambda pairs: _unique_pairs(pairs, label))
            if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
                raise ValueError("row is not object")
            rows.append(value)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("evidence_jsonl_invalid", f"{label} JSONL 不合法") from exc
    if not rows:
        raise ContractError("evidence_rows_empty", f"{label} 为空")
    return rows


def _unique_pairs(pairs: list[tuple[str, Any]], label: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key in {label}")
        result[key] = value
    return result


def _production_request(payload: Any, config: AuditServiceConfig) -> dict[str, Any]:
    """Resolve evidence solely from compile identities and the configured runs root."""
    obj = strict_object(payload, required={
        "kind", "batch_id", "dispatch_effect_id", "dispatch_event_id",
        "envelope_hash", "compile_envelope", "dev_bundle",
    })
    if obj["kind"] != "evidence_from_runs":
        raise ContractError("audit_kind_unknown", "audit kind 不合法")
    for field in ("batch_id", "dispatch_effect_id", "dispatch_event_id"):
        require_id(obj[field], field)
    require_sha(obj["envelope_hash"], "envelope_hash")
    envelope = obj["compile_envelope"]
    if (not isinstance(envelope, dict)
            or len(canonical_json(envelope)) > MAX_COMPILE_ENVELOPE_BYTES
            or sha256(envelope) != obj["envelope_hash"]
            or envelope.get("batch_id") != obj["batch_id"]):
        raise ContractError("compile_envelope_binding_invalid",
                            "审计请求的 compile envelope 绑定不合法")
    expected = _production_expected_keys(envelope)
    execution_ids = sorted({(key[0], key[1]) for key in expected})
    runs_root = Path(config.evidence_runs_root)
    steps: list[dict[str, Any]] = []
    scores: list[dict[str, Any]] = []
    sidecars: list[dict[str, Any]] = []
    for run_id, config_hash in execution_ids:
        require_id(run_id, "run_id"); require_sha(config_hash, "config_hash")
        run_dir = runs_root / run_id
        try:
            info = run_dir.lstat()
        except OSError as exc:
            raise ContractError("evidence_run_missing", "固定 runs root 中缺 run") from exc
        if (run_dir.is_symlink() or not stat.S_ISDIR(info.st_mode)
                or run_dir.parent.resolve() != runs_root.resolve()):
            raise ContractError("evidence_run_unsafe", "run 目录越界或类型不安全")
        run_steps = _bounded_jsonl(run_dir / "steps.jsonl", label=f"{run_id}/steps")
        run_scores = _bounded_jsonl(run_dir / "scores.jsonl", label=f"{run_id}/scores")
        run_sidecars = _bounded_jsonl(run_dir / "logs" / "rendered_prompts.jsonl",
                                     label=f"{run_id}/sidecars")
        if (any(row.get("run_id") != run_id or row.get("config_hash") != config_hash
                for row in (*run_steps, *run_scores, *run_sidecars))):
            raise ContractError("evidence_run_binding_invalid",
                                "run 证据未绑定 compile run_id/config_hash")
        steps.extend(run_steps); scores.extend(run_scores); sidecars.extend(run_sidecars)
    selection = envelope.get("selection_receipt")
    if not isinstance(selection, dict):
        raise ContractError("dev_bundle_reference_missing", "compile envelope 缺 selection receipt")
    bundle_wire = dict(obj["dev_bundle"])
    if (bundle_wire.get("bundle_id") != envelope.get("dev_bundle_id")
            or bundle_wire.get("manifest_hash") != envelope.get("dev_bundle_manifest_hash")
            or bundle_wire.get("item_ids") != envelope.get("item_ids")
            or bundle_wire.get("source_hash") != selection.get("source_hash")):
        raise ContractError("dev_bundle_reference_mismatch", "DevBundle ref 与信封不一致")
    conditions = tuple(arm.get("id") for arm in envelope.get("arms", []))
    if not conditions or any(not isinstance(item, str) or not item for item in conditions):
        raise ContractError("compile_conditions_invalid", "compile arms 不合法")
    return {"batch_id": obj["batch_id"], "item_ids": tuple(envelope["item_ids"]),
            "seeds": tuple(envelope["seeds"]), "conditions": conditions,
            "steps": steps, "scores": scores, "sidecars": sidecars,
            "dev_bundle": _dev_bundle(bundle_wire, config.trusted_dev_bundle_root),
            "compile_envelope": envelope}


def _handle_production_evidence(payload: Any, config: AuditServiceConfig) -> dict[str, Any]:
    request = _production_request(payload, config)
    attestation = audit_evidence(
        **request, trusted_dev_bundle_root=config.trusted_dev_bundle_root,
        bundle_sealer_public_key=config.bundle_sealer_public_key,
        auditor_private_key=config.auditor_private_key,
        auditor_public_key=config.auditor_public_key)
    return asdict(attestation)


def handle(payload: Any, config: AuditServiceConfig, *,
           allow_legacy_evidence: bool = True) -> dict[str, Any]:
    """Strict tagged production union with an explicit untagged fixture bridge."""
    if not isinstance(payload, dict):
        raise ContractError("audit_payload_invalid", "audit payload 必须是对象")
    kind = payload.get("kind")
    if kind == "approval_validation":
        return _validate_approval(payload, config)
    if kind == "evidence":
        evidence = dict(payload)
        evidence.pop("kind")
        # parse_request supplies the exact-field gate after removing only the tag.
        return _handle_evidence(evidence, config)
    if kind == "evidence_from_runs":
        config.validate_evidence_resources()
        return _handle_production_evidence(payload, config)
    if kind is None and allow_legacy_evidence:
        return _handle_evidence(payload, config)
    raise ContractError("audit_kind_unknown",
                        "audit kind 必须是 evidence_from_runs/evidence/approval_validation")


def _fixture_spool_guard() -> None:
    if os.environ.get("ABCR_SERVICE_LABEL"):
        raise AuditServiceError("direct spool fixture forbidden for launched service")


def process_once(spool: WorkSpool, work_id: str, config: AuditServiceConfig) -> bool:
    _fixture_spool_guard()
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
    _fixture_spool_guard()
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
    _fixture_spool_guard()
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
    """Fixture-only direct-spool doctor retained for unit and migration tests."""
    _fixture_spool_guard()
    config.validate()
    _, invalid = inspect_ready(config)
    return {"ok": not invalid, "service": "abcr-auditor", "queue": "audit",
            "blocked_entries": len(invalid)}


def _queue_domain_config(config: dict[str, Any]) -> AuditServiceConfig:
    settings = strict_object(
        config["settings"],
        required={"trusted_dev_bundle_root", "bundle_sealer_public_key",
                  "auditor_private_key", "auditor_public_key", "research_repo",
                  "anchor_ledger", "anchor_seal_path", "anchor_sealer_public_key",
                  "approval_staging_root", "validator_private_key",
                  "validator_public_key", "anchor_ledger_owner_uid",
                  "anchor_seal_owner_uid", "evidence_runs_root",
                  "audit_staging_root"},
    )
    path_fields = set(settings) - {"anchor_ledger_owner_uid", "anchor_seal_owner_uid"}
    if (not all(isinstance(settings[name], str) and Path(settings[name]).is_absolute()
                for name in path_fields)
            or type(settings["anchor_ledger_owner_uid"]) is not int
            or type(settings["anchor_seal_owner_uid"]) is not int):
        raise AuditServiceError("trusted auditor resource paths must be absolute")
    # ``work_root`` exists only for the direct-spool fixture API.
    return AuditServiceConfig(
        work_root=Path("/broker-managed/no-spool-access"),
        trusted_dev_bundle_root=Path(settings["trusted_dev_bundle_root"]),
        bundle_sealer_public_key=Path(settings["bundle_sealer_public_key"]),
        auditor_private_key=Path(settings["auditor_private_key"]),
        auditor_public_key=Path(settings["auditor_public_key"]),
        research_repo=Path(settings["research_repo"]),
        anchor_ledger=Path(settings["anchor_ledger"]),
        anchor_seal_path=Path(settings["anchor_seal_path"]),
        anchor_sealer_public_key=Path(settings["anchor_sealer_public_key"]),
        approval_staging_root=Path(settings["approval_staging_root"]),
        validator_private_key=Path(settings["validator_private_key"]),
        validator_public_key=Path(settings["validator_public_key"]),
        anchor_ledger_owner_uid=settings["anchor_ledger_owner_uid"],
        anchor_seal_owner_uid=settings["anchor_seal_owner_uid"],
        evidence_runs_root=Path(settings["evidence_runs_root"]),
        audit_staging_root=Path(settings["audit_staging_root"]),
    )


def _stage_validator_document(config: AuditServiceConfig, document: dict[str, Any],
                              work_id: str) -> tuple[Path, str, str]:
    raw = canonical_json(document) + b"\n"
    object_id = sha256(raw)
    root = Path(config.approval_staging_root)
    if WORK_ID.fullmatch(work_id) is None:
        raise ContractError("approval_work_id_invalid", "approval work id 不合法")
    # The stable work-id directory is the durable prepared effect.  A retry after
    # validation but before broker seal reuses the exact validator issued_at/signature.
    final = root / work_id
    # Broker's mechanical verifier accepts exactly this one finite canonical file.
    expected_file = final / "validator.json"
    if final.exists():
        info = final.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or {path.name for path in final.iterdir()} != {expected_file.name}
                or expected_file.is_symlink() or expected_file.read_bytes() != raw):
            raise ContractError("approval_staging_conflict",
                                "validator document staging object 冲突")
    else:
        temporary = root / f".{object_id}.{uuid.uuid4().hex}.tmp"
        temporary.mkdir(mode=0o700)
        try:
            target = temporary / expected_file.name
            with target.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.rename(temporary, final)
        finally:
            if temporary.exists():
                for child in temporary.iterdir():
                    child.unlink()
                temporary.rmdir()
    expected_tree_hash = tree_hash(scan_tree(final))
    return final, object_id, expected_tree_hash


def _recover_validator_document(config: AuditServiceConfig, work_id: str
                                ) -> tuple[dict[str, Any], Path, str, str] | None:
    if WORK_ID.fullmatch(work_id) is None:
        raise ContractError("approval_work_id_invalid", "approval work id 不合法")
    root = Path(config.approval_staging_root)
    final = root / work_id
    if not final.exists():
        return None
    info = final.lstat()
    path = final / "validator.json"
    if (final.is_symlink() or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077
            or {item.name for item in final.iterdir()} != {"validator.json"}):
        raise ContractError("approval_staging_conflict", "prepared validator staging 不安全")
    file_info = path.lstat()
    if (path.is_symlink() or not stat.S_ISREG(file_info.st_mode)
            or file_info.st_uid != os.geteuid() or file_info.st_nlink != 1
            or file_info.st_size > 1024 * 1024):
        raise ContractError("approval_staging_conflict", "prepared validator 文件不安全")
    raw = path.read_bytes()
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("approval_staging_conflict", "prepared validator JSON 损坏") from exc
    if not isinstance(document, dict) or raw != canonical_json(document) + b"\n":
        raise ContractError("approval_staging_conflict", "prepared validator 非 canonical")
    object_id = sha256(raw)
    return document, final, object_id, tree_hash(scan_tree(final))


def main(argv: list[str] | None = None) -> int:
    """Consume evidence-audit work only through the root broker."""
    from abcr.control.queue_runtime import WorkBrokerClient, queue_main

    def preflight(config: dict[str, Any]) -> None:
        domain = _queue_domain_config(config)
        domain.validate_resources()
        domain.validate_approval_resources()
        domain.validate_evidence_resources()

    def make_handler(config: dict[str, Any]):
        domain = _queue_domain_config(config)
        broker = WorkBrokerClient(Path(config["broker_socket"]))

        def broker_handle(payload: Any, work_id: str, _fencing_token: int) -> dict[str, Any]:
            # Production requires the tag even though untagged evidence remains a
            # fixture compatibility surface.
            if not isinstance(payload, dict):
                raise ContractError("audit_payload_invalid", "audit payload 必须是对象")
            if payload.get("kind") == "evidence_from_runs":
                from abcr.control.mission_pipeline import artifact_object_id, seal_json_artifact
                document = handle(payload, domain, allow_legacy_evidence=False)
                object_id = artifact_object_id("audit", document)
                reference = seal_json_artifact(
                    broker, operation="seal_audit_result",
                    staging_root=Path(domain.audit_staging_root), object_id=object_id,
                    filename="audit-result.json", document=document, nonce=work_id)
                return {"kind": "evidence_audit", "batch_id": payload["batch_id"],
                        "dispatch_event_id": payload["dispatch_event_id"],
                        "audit_ref": reference}
            if payload.get("kind") != "approval_validation":
                raise ContractError("audit_kind_unknown", "生产 audit kind 不合法")
            recovered = _recover_validator_document(domain, work_id)
            if recovered is None:
                result = handle(payload, domain, allow_legacy_evidence=False)
                source, object_id, expected = _stage_validator_document(
                    domain, result, work_id)
            else:
                result, source, object_id, expected = recovered
            receipt = strict_object(
                broker.request("seal_approval_bundle", {
                    "source": str(source), "nonce": work_id,
                    "expected_tree_hash": expected, "object_id": object_id,
                }),
                required={"receipt_id", "operation", "nonce", "object_id", "tree_hash",
                          "sealed_tree_hash", "sealed_path", "created_at"},
            )
            for field in ("receipt_id", "tree_hash", "sealed_tree_hash"):
                require_sha(receipt[field], f"broker_receipt.{field}")
            if (receipt["operation"] != "seal_approval_bundle"
                    or receipt["nonce"] != work_id or receipt["object_id"] != object_id
                    or receipt["tree_hash"] != expected):
                raise ContractError("approval_seal_receipt_mismatch",
                                    "broker approval receipt 与 validator document 不一致")
            return {"document": result, "broker_receipt_id": receipt["receipt_id"],
                    "broker_object_id": object_id,
                    "sealed_tree_hash": receipt["sealed_tree_hash"]}

        return broker_handle

    return queue_main(argv, service="auditor", stage="audit",
                      consumer="abcr-auditor", preflight=preflight,
                      make_handler=make_handler)


if __name__ == "__main__":
    raise SystemExit(main())
