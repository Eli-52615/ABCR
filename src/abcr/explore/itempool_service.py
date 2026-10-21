"""On-demand, queue-fenced adapter for the privileged dev item pool.

The queue payload describes only *what* to select.  Every path and signing key is
loaded from the launcher's trusted environment, so an untrusted producer cannot
redirect the item-pool process to another dataset, split, output tree, or key.

``process_once``/``run`` are explicit in-process fixture adapters.  The production
``main`` never constructs or enumerates :class:`WorkSpool`; it consumes opaque
claims exclusively through the peer-credential broker.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from abcr.control.contracts import ContractError, require_id, require_sha, strict_object
from abcr.control.worktree import scan_tree, tree_hash
from abcr.control.work_spool import WORK_ID, SpoolError, WorkSpool
from abcr.explore.item_pool import SelectionRequest, build_dev_bundle, verify_dev_bundle


class ItemPoolServiceError(RuntimeError):
    """Configuration or queue-layout defect (never includes secret material)."""


DEFAULT_CONFIG_PATH = Path(
    "/Library/Application Support/ABCR-Bootstrap/config/itempool.json")
CONFIG_ENV = "ABCR_ITEMPOOL_CONFIG_PATH"
PATH_ENVS = frozenset({
    "ABCR_WORK_ROOT", "ABCR_ITEMPOOL_DATASET_PATH", "ABCR_ITEMPOOL_SPLIT_PATH",
    "ABCR_DEVBUNDLE_ROOT", "ABCR_ITEMPOOL_SEALER_PRIVATE_KEY",
    "ABCR_ITEMPOOL_SEALER_PUBLIC_KEY", CONFIG_ENV,
})


@dataclass(frozen=True)
class ItemPoolServiceConfig:
    work_root: Path
    dataset_path: Path
    split_path: Path
    output_root: Path
    sealer_private_key: Path
    sealer_public_key: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ItemPoolServiceConfig":
        source = os.environ if env is None else env

        def required(name: str) -> Path:
            value = source.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ItemPoolServiceError(f"missing trusted setting: {name}")
            return Path(value)

        return cls(
            work_root=required("ABCR_WORK_ROOT"),
            dataset_path=required("ABCR_ITEMPOOL_DATASET_PATH"),
            split_path=required("ABCR_ITEMPOOL_SPLIT_PATH"),
            output_root=required("ABCR_DEVBUNDLE_ROOT"),
            sealer_private_key=required("ABCR_ITEMPOOL_SEALER_PRIVATE_KEY"),
            sealer_public_key=required("ABCR_ITEMPOOL_SEALER_PUBLIC_KEY"),
        )

    @classmethod
    def from_secure_file(cls, path: Path, *, owner_uid: int) -> "ItemPoolServiceConfig":
        obj = strict_object(
            _read_secure_json(path, owner_uid=owner_uid),
            required={"work_root", "dataset_path", "split_path", "output_root",
                      "sealer_private_key", "sealer_public_key"},
        )
        if not all(isinstance(value, str) and value for value in obj.values()):
            raise ItemPoolServiceError("trusted config paths must be non-empty strings")
        return cls(**{name: Path(value) for name, value in obj.items()})

    def validate(self) -> None:
        _require_directory(self.work_root, "work root")
        _require_directory(self.work_root / "itempool" / "ready", "itempool ready queue")
        self.validate_resources()

    def validate_resources(self) -> None:
        """Validate only this UID's trusted scientific resources (not ABCR-Work)."""
        _require_directory(self.output_root, "dev-bundle output root")
        _require_owned_private_directory(self.output_root, "dev-bundle output root")
        _require_access(self.output_root, os.R_OK | os.W_OK | os.X_OK,
                        "dev-bundle output root")
        _require_regular(self.dataset_path, "dataset")
        _require_access(self.dataset_path, os.R_OK, "dataset")
        _require_regular(self.split_path, "split")
        _require_access(self.split_path, os.R_OK, "split")
        _require_regular(self.sealer_private_key, "sealer private key", private=True)
        _require_access(self.sealer_private_key, os.R_OK, "sealer private key")
        _require_regular(self.sealer_public_key, "sealer public key")
        _require_access(self.sealer_public_key, os.R_OK, "sealer public key")


def _require_directory(path: Path, label: str) -> None:
    try:
        info = Path(path).lstat()
    except OSError as exc:
        raise ItemPoolServiceError(f"missing {label}") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ItemPoolServiceError(f"unsafe {label}")


def _require_regular(path: Path, label: str, *, private: bool = False) -> None:
    try:
        info = Path(path).lstat()
    except OSError as exc:
        raise ItemPoolServiceError(f"missing {label}") from exc
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_nlink != 1):
        raise ItemPoolServiceError(f"unsafe {label}")
    if private and (stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.geteuid()):
        raise ItemPoolServiceError(f"unsafe owner or permissions for {label}")


def _require_access(path: Path, mode: int, label: str) -> None:
    if not os.access(path, mode):
        raise ItemPoolServiceError(f"unavailable access for {label}")


def _require_owned_private_directory(path: Path, label: str) -> None:
    info = Path(path).lstat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise ItemPoolServiceError(f"unsafe owner or permissions for {label}")


def _read_secure_json(path: Path, *, owner_uid: int) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ItemPoolServiceError("cannot open trusted itempool config") from exc
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != owner_uid
                or stat.S_IMODE(before.st_mode) not in {0o600, 0o440}
                or before.st_size > 64 * 1024):
            raise ItemPoolServiceError("unsafe trusted itempool config")
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
            raise ItemPoolServiceError("trusted itempool config changed while reading")
    finally:
        os.close(fd)

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ItemPoolServiceError("duplicate key in trusted itempool config")
            out[key] = value
        return out

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ItemPoolServiceError("invalid trusted itempool config") from exc
    if not isinstance(value, dict):
        raise ItemPoolServiceError("trusted itempool config must be an object")
    return value


def load_config(env: Mapping[str, str] | None = None) -> ItemPoolServiceConfig:
    """Load production config from the frozen root-owned path.

    A non-launchd test may explicitly point at a secure fixture config or provide
    individual path variables.  Once ``ABCR_SERVICE_LABEL`` is present, every such
    override is a configuration error rather than a way around the bootstrap TCB.
    """
    source = os.environ if env is None else env
    if source.get("ABCR_SERVICE_LABEL"):
        raise ItemPoolServiceError(
            "environment override forbidden: fixture spool config in launched service")
    if source.get(CONFIG_ENV):
        return ItemPoolServiceConfig.from_secure_file(Path(source[CONFIG_ENV]),
                                                      owner_uid=os.getuid())
    if any(source.get(name) for name in PATH_ENVS - {CONFIG_ENV}):
        return ItemPoolServiceConfig.from_env(source)
    return ItemPoolServiceConfig.from_secure_file(DEFAULT_CONFIG_PATH, owner_uid=0)


def _exact_int(value: Any, field: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:  # bool is deliberately not accepted as an integer
        raise ContractError("invalid_type", f"{field} 必须是整数")
    if minimum is not None and value < minimum:
        raise ContractError("invalid_value", f"{field} 不得小于 {minimum}")
    return value


def parse_request(payload: Any) -> SelectionRequest:
    obj = strict_object(
        payload,
        required={"request_id", "goal_hash", "count", "seed"},
        optional={"excluded_item_ids", "request_created_at"},
    )
    request_id = obj["request_id"]
    goal_hash = obj["goal_hash"]
    require_id(request_id, "request_id")
    require_sha(goal_hash, "goal_hash")
    count = _exact_int(obj["count"], "count", minimum=1)
    seed = _exact_int(obj["seed"], "seed")
    excluded = obj.get("excluded_item_ids", [])
    if (not isinstance(excluded, list)
            or not all(isinstance(item, str) and item for item in excluded)
            or len(excluded) != len(set(excluded))):
        raise ContractError("invalid_excluded_items",
                            "excluded_item_ids 必须是不重复的非空字符串数组")
    created_at = obj.get("request_created_at")
    if created_at is not None and (not isinstance(created_at, str) or not created_at):
        raise ContractError("request_created_at_invalid", "request_created_at 必须是非空字符串")
    return SelectionRequest(request_id, goal_hash, count, seed, tuple(excluded), created_at)


def handle(payload: Any, config: ItemPoolServiceConfig) -> dict[str, Any]:
    request = parse_request(payload)
    ref = build_dev_bundle(
        request,
        dataset_path=config.dataset_path,
        split_path=config.split_path,
        output_root=config.output_root,
        sealer_private_key=config.sealer_private_key,
        sealer_public_key=config.sealer_public_key,
    )
    # Re-open through the same public verification gate used downstream.  The
    # result is a finite selection receipt, not merely a pointer to a directory:
    # both the dev-only label and the exact selected bytes are signed by the
    # item-pool identity and can therefore be copied into every RunConfig.
    manifest = verify_dev_bundle(
        ref, config.output_root, sealer_public_key=config.sealer_public_key)
    # Consumers reconstruct root from their own trusted ABCR_DEVBUNDLE_ROOT.
    return {
        "bundle_id": ref.bundle_id,
        "manifest_hash": ref.manifest_hash,
        "item_ids": list(ref.item_ids),
        "source_hash": ref.source_hash,
        "split": manifest["split"],
        "selected_bytes_hash": manifest["items_sha256"],
    }


def _fixture_spool_guard() -> None:
    if os.environ.get("ABCR_SERVICE_LABEL"):
        raise ItemPoolServiceError("direct spool fixture forbidden for launched service")


def process_once(spool: WorkSpool, work_id: str, config: ItemPoolServiceConfig) -> bool:
    _fixture_spool_guard()
    claim = spool.claim("itempool", work_id)
    if claim is None:
        return False
    try:
        result = {"ok": True, "result": handle(claim.payload, config)}
    except Exception as exc:  # poison input becomes a fenced, acknowledged failure
        code = exc.code if isinstance(exc, ContractError) else type(exc).__name__
        result = {"ok": False, "error_code": code}
    spool.submit_result(claim, result, consumer="abcr-itempool")
    spool.ack(claim)
    return True


def inspect_ready(config: ItemPoolServiceConfig) -> tuple[tuple[str, ...], tuple[Path, ...]]:
    _fixture_spool_guard()
    ready = config.work_root / "itempool" / "ready"
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


def ready_work_ids(config: ItemPoolServiceConfig) -> tuple[str, ...]:
    return inspect_ready(config)[0]


def _quarantine_invalid(config: ItemPoolServiceConfig, paths: tuple[Path, ...]) -> int:
    quarantine = config.work_root / "itempool" / "quarantine"
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


def run(config: ItemPoolServiceConfig, *, once: bool = False) -> int:
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
            # claim() already quarantines malformed/hard-linked envelopes.  One poison
            # item must not hold the launchd QueueDirectories job open forever.
            continue
    return len(work_ids)


def doctor(config: ItemPoolServiceConfig) -> dict[str, Any]:
    """Fixture-only direct-spool doctor retained for unit and migration tests."""
    _fixture_spool_guard()
    config.validate()
    _, invalid = inspect_ready(config)
    return {"ok": not invalid, "service": "abcr-itempool", "queue": "itempool",
            "blocked_entries": len(invalid)}


def _queue_domain_config(config: dict[str, Any]) -> ItemPoolServiceConfig:
    settings = strict_object(
        config["settings"],
        required={"dataset_path", "split_path", "output_root",
                  "sealer_private_key", "sealer_public_key"},
    )
    if not all(isinstance(value, str) and Path(value).is_absolute()
               for value in settings.values()):
        raise ItemPoolServiceError("trusted itempool resource paths must be absolute")
    # ``work_root`` is a fixture-only field.  Production never dereferences it.
    return ItemPoolServiceConfig(
        work_root=Path("/broker-managed/no-spool-access"),
        dataset_path=Path(settings["dataset_path"]),
        split_path=Path(settings["split_path"]),
        output_root=Path(settings["output_root"]),
        sealer_private_key=Path(settings["sealer_private_key"]),
        sealer_public_key=Path(settings["sealer_public_key"]),
    )


def main(argv: list[str] | None = None) -> int:
    """Consume item-pool work only through the root broker."""
    from abcr.control.queue_runtime import WorkBrokerClient, queue_main

    def preflight(config: dict[str, Any]) -> None:
        _queue_domain_config(config).validate_resources()

    def make_handler(config: dict[str, Any]):
        domain = _queue_domain_config(config)
        broker = WorkBrokerClient(Path(config["broker_socket"]))

        def broker_handle(payload: Any, work_id: str, _fencing_token: int) -> dict[str, Any]:
            if not isinstance(payload, dict) or not isinstance(payload.get("request_created_at"), str):
                raise ContractError("request_created_at_required",
                                    "生产 itempool 请求必须携带稳定 request_created_at")
            result = handle(payload, domain)
            source = domain.output_root / result["bundle_id"]
            expected = tree_hash(scan_tree(source))
            receipt = strict_object(
                broker.request("seal_dev_bundle", {
                    "source": str(source), "nonce": work_id,
                    "expected_tree_hash": expected, "object_id": result["bundle_id"],
                }),
                required={"receipt_id", "operation", "nonce", "object_id", "tree_hash",
                          "sealed_tree_hash", "sealed_path", "created_at"},
            )
            for field in ("receipt_id", "tree_hash", "sealed_tree_hash"):
                require_sha(receipt[field], f"broker_receipt.{field}")
            if (receipt["operation"] != "seal_dev_bundle"
                    or receipt["nonce"] != work_id
                    or receipt["object_id"] != result["bundle_id"]
                    or receipt["tree_hash"] != expected):
                raise ContractError("dev_bundle_seal_receipt_mismatch",
                                    "broker DevBundle receipt 与 staging 不一致")
            return {**result, "seal_receipt_id": receipt["receipt_id"],
                    "sealed_tree_hash": receipt["sealed_tree_hash"]}

        return broker_handle

    return queue_main(argv, service="itempool", stage="itempool",
                      consumer="abcr-itempool", preflight=preflight,
                      make_handler=make_handler)


if __name__ == "__main__":
    raise SystemExit(main())
