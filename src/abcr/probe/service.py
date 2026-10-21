"""On-demand probe worker.

The work payload names scientific inputs, never runtime trust roots.  The latter are
fixed when the service starts so an otherwise valid queue producer cannot redirect
the worker to an attacker-controlled bundle, key, model profile, or notebook.

The direct-spool functions in this module are fixture APIs.  Production ``main``
claims and settles opaque work only through the peer-credential broker.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from abcr.common.paths import RuntimeRoots
from abcr.control.contracts import require_sha
from abcr.control.ed25519 import public_fingerprint
from abcr.control.work_spool import STATES, WORK_ID, SpoolError, WorkSpool
from abcr.explore.item_pool import DevBundleRef
from abcr.probe.contracts import ProbePersona, ProbeRequest
from abcr.probe.engine import ProbeEngine, run_probe
from abcr.probe.notebook import ProbeNotebook
from abcr.probe.ollama_engine import OllamaProbeEngine


_REQUEST_FIELDS = frozenset({
    "probe_id", "goal_hash", "dev_bundle", "personas", "prediction", "seed",
    "model_profile", "max_output_tokens", "with_length_control",
})
_OPTIONAL_REQUEST_FIELDS = frozenset({"length_controls"})
_BUNDLE_FIELDS = frozenset({
    "bundle_id", "manifest_hash", "item_ids", "source_hash",
})
_PERSONA_FIELDS = frozenset({"persona_ref", "persona_text"})
# In an immutable release the interpreter prefix is `<release>/env`; this locates
# the sealed profile at `<release>/configs/...` without PYTHONPATH or caller env.
# In the development venv the same rule resolves to the repository root.
_DEFAULT_PROFILE = (Path(sys.prefix).parent / "configs" / "probe" /
                    "profiles" / "qwen25-7b-q4-v1.json")
_DEFAULT_SEALER_PUBLIC_KEY = (Path("/Library/Application Support/ABCR-Trust") /
                              "dev-bundle-sealer.pub")


class ProbeServiceError(RuntimeError):
    """A fail-closed service configuration or payload error."""


@dataclass(frozen=True)
class ServiceConfig:
    work_root: Path
    profile_path: Path
    trusted_dev_bundle_root: Path
    bundle_sealer_public_key: Path
    lab_root: Path

    def __post_init__(self) -> None:
        for name in ("work_root", "profile_path", "trusted_dev_bundle_root",
                     "bundle_sealer_public_key", "lab_root"):
            object.__setattr__(self, name, Path(getattr(self, name)))


EngineFactory = Callable[[Path], ProbeEngine]


def _exact_object(value: Any, fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ProbeServiceError(f"{name} fields mismatch")
    return value


def _nonempty_string(value: Any, name: str, *, max_length: int = 65536) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ProbeServiceError(f"invalid {name}")
    return value


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProbeServiceError(f"invalid {name}")
    return value


def _request_from_payload(payload: Any, config: ServiceConfig,
                          engine: ProbeEngine) -> ProbeRequest:
    """Build the typed request while deriving all authority-bearing paths locally."""
    if (not isinstance(payload, dict)
            or not _REQUEST_FIELDS.issubset(payload)
            or set(payload) - _REQUEST_FIELDS - _OPTIONAL_REQUEST_FIELDS):
        raise ProbeServiceError("probe payload fields mismatch")
    obj = payload
    bundle_obj = _exact_object(obj["dev_bundle"], _BUNDLE_FIELDS, "dev_bundle")

    bundle_id = _nonempty_string(bundle_obj["bundle_id"], "bundle_id", max_length=64)
    manifest_hash = _nonempty_string(
        bundle_obj["manifest_hash"], "manifest_hash", max_length=64)
    source_hash = _nonempty_string(bundle_obj["source_hash"], "source_hash", max_length=64)
    for value, name in ((bundle_id, "bundle_id"),
                        (manifest_hash, "manifest_hash"),
                        (source_hash, "source_hash")):
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ProbeServiceError(f"invalid {name}")
    item_ids = bundle_obj["item_ids"]
    if (not isinstance(item_ids, list) or not item_ids
            or len(item_ids) > 10000
            or any(not isinstance(item_id, str) or not item_id or len(item_id) > 256
                   for item_id in item_ids)
            or len(item_ids) != len(set(item_ids))):
        raise ProbeServiceError("invalid dev_bundle item_ids")

    # Deliberately ignore no caller path: the direct child is derived from the
    # configured sealed root.  A `root` field would already have failed exact fields.
    bundle = DevBundleRef(
        bundle_id=bundle_id,
        root=config.trusted_dev_bundle_root / bundle_id,
        manifest_hash=manifest_hash,
        item_ids=tuple(item_ids),
        source_hash=source_hash,
    )
    goal_hash = _nonempty_string(obj["goal_hash"], "goal_hash", max_length=64)
    require_sha(goal_hash, "goal_hash")
    model_profile = _nonempty_string(
        obj["model_profile"], "model_profile", max_length=128)
    if model_profile != engine.profile_id:
        raise ProbeServiceError("model_profile does not match frozen service profile")
    persona_objects = obj["personas"]
    if not isinstance(persona_objects, list) or not 1 <= len(persona_objects) <= 3:
        raise ProbeServiceError("probe requires 1-3 personas")
    personas = tuple(
        ProbePersona(
            persona_ref=_nonempty_string(
                _exact_object(value, _PERSONA_FIELDS, "persona")["persona_ref"],
                "persona_ref", max_length=512),
            persona_text=_nonempty_string(value["persona_text"], "persona_text"),
        )
        for value in persona_objects
    )
    with_length_control = obj["with_length_control"]
    if not isinstance(with_length_control, bool):
        raise ProbeServiceError("invalid with_length_control")
    length_controls = obj.get("length_controls", [])
    if not isinstance(length_controls, list):
        raise ProbeServiceError("invalid length_controls")
    try:
        return ProbeRequest(
            probe_id=_nonempty_string(obj["probe_id"], "probe_id", max_length=128),
            goal_hash=goal_hash,
            dev_bundle=bundle,
            personas=personas,
            prediction=_nonempty_string(obj["prediction"], "prediction"),
            seed=_integer(obj["seed"], "seed"),
            model_profile=model_profile,
            max_output_tokens=_integer(obj["max_output_tokens"], "max_output_tokens"),
            with_length_control=with_length_control,
            length_controls=tuple(length_controls),
        )
    except (ValueError, TypeError) as exc:
        raise ProbeServiceError("invalid ③L request contract") from exc


def _run_payload(payload: Any, config: ServiceConfig, engine: ProbeEngine,
                 notebook: ProbeNotebook) -> dict[str, Any]:
    request = _request_from_payload(payload, config, engine)
    probe_run = run_probe(
        request, engine,
        trusted_dev_bundle_root=config.trusted_dev_bundle_root,
        bundle_sealer_public_key=config.bundle_sealer_public_key,
    )
    row_hashes: list[str] = []
    row_index: list[dict[str, Any]] = []
    for row in probe_run.rows:
        notebook.append(row)
        row_hashes.append(row["row_hash"])
        # Return only identity metadata to Operator. Generated text remains in the
        # probe-owned notebook; this index is sufficient for inert promotion drafts.
        row_index.append({
            "row_hash": row["row_hash"], "cell_id": row["cell_id"],
            "goal_hash": row["goal_hash"], "item_id": row["item_id"],
            "seed": row["seed"], "arm_id": row["arm_id"],
            "arm_kind": row["arm_kind"], "persona_ref": row["persona_ref"],
            "engine_fingerprint_sha256": row["engine_fingerprint_sha256"],
        })
    fingerprint_hashes = {row["engine_fingerprint_sha256"] for row in probe_run.rows}
    if len(fingerprint_hashes) != 1:
        raise ProbeServiceError("probe rows do not share one frozen engine fingerprint")
    return {
        "schema_version": 2,
        "receipt_type": "ProbeResultReceipt",
        "probe_id": probe_run.probe_id,
        "model_profile": request.model_profile,
        "engine_fingerprint_sha256": next(iter(fingerprint_hashes)),
        "item_ids": list(request.dev_bundle.item_ids),
        "arm_ids": list(request.arm_ids),
        "row_count": len(row_hashes),
        "row_hashes": row_hashes,
        "rows": row_index,
        "citable": False,
        "label": probe_run.label,
        "started_at": probe_run.started_at,
        "completed_at": probe_run.completed_at,
        "length_control_3l": {
            "requested": request.with_length_control,
            "status": "PASS" if request.with_length_control else "NOT_REQUESTED",
        },
    }


def process_once(spool: WorkSpool, work_id: str, handler) -> bool:
    """Claim, settle, and acknowledge one queue item.

    Scientific/runtime failures are durable negative results, not daemon crashes.  No
    exception text or payload is copied into the result boundary.
    """
    _fixture_spool_guard()
    claim = spool.claim("probe", work_id)
    if claim is None:
        return False
    try:
        result = handler(claim.payload)
        spool.submit_result(claim, {"ok": True, "result": result},
                            consumer="abcr-probe")
    except Exception as exc:
        spool.submit_result(claim, {"ok": False, "error_code": type(exc).__name__},
                            consumer="abcr-probe")
    spool.ack(claim)
    return True


def _ready_work_ids(work_root: Path) -> tuple[str, ...]:
    _fixture_spool_guard()
    ready = work_root / "probe" / "ready"
    # Do not silently skip oddly named poison: claim() will either validate it or
    # quarantine it.  Skipping would leave QueueDirectories permanently asserted.
    return tuple(sorted(path.name[:-5] for path in ready.glob("*.json")))


def _invalid_work_id(_payload: Any) -> dict[str, Any]:
    raise ProbeServiceError("invalid work_id")


def process_ready(config: ServiceConfig, *, once: bool = False,
                  engine_factory: EngineFactory | None = None) -> dict[str, int]:
    _fixture_spool_guard()
    spool = WorkSpool(config.work_root)
    engine_factory = engine_factory or OllamaProbeEngine
    engine = engine_factory(config.profile_path)
    notebook = ProbeNotebook(config.lab_root)
    handled = 0
    claim_errors = 0
    for work_id in _ready_work_ids(config.work_root):
        try:
            handler = (_invalid_work_id if WORK_ID.fullmatch(work_id) is None else
                       lambda payload: _run_payload(payload, config, engine, notebook))
            if process_once(
                    spool, work_id, handler):
                handled += 1
        except SpoolError:
            # WorkSpool quarantines poison encountered during claim.  Continue so a
            # single bad item cannot wedge QueueDirectories and all later work.
            claim_errors += 1
        if once and handled:
            break
    return {"handled": handled, "claim_errors": claim_errors}


def _real_directory(path: Path, name: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ProbeServiceError(f"{name} is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ProbeServiceError(f"{name} must be a real directory")


def _single_regular_file(path: Path, name: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ProbeServiceError(f"{name} is unavailable") from exc
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_nlink != 1):
        raise ProbeServiceError(f"{name} must be a single-link regular file")


def _require_access(path: Path, mode: int, name: str) -> None:
    if not os.access(path, mode):
        raise ProbeServiceError(f"{name} access is unavailable")


def _fixture_spool_guard() -> None:
    if os.environ.get("ABCR_SERVICE_LABEL"):
        raise ProbeServiceError("direct spool fixture forbidden for launched service")


def doctor(config: ServiceConfig, *, offline: bool = False,
           engine_factory: EngineFactory | None = None) -> dict[str, Any]:
    """Fixture-only direct-spool validation; offline makes no daemon request."""
    _fixture_spool_guard()
    _real_directory(config.work_root, "work root")
    _real_directory(config.work_root / "probe", "probe work stage")
    for state in STATES:
        path = config.work_root / "probe" / state
        _real_directory(path, f"probe {state} queue")
        _require_access(path, os.R_OK | os.W_OK | os.X_OK, f"probe {state} queue")
    _real_directory(config.trusted_dev_bundle_root, "trusted DevBundle root")
    _require_access(config.trusted_dev_bundle_root, os.R_OK | os.X_OK,
                    "trusted DevBundle root")
    _real_directory(config.lab_root, "lab root")
    lab_info = config.lab_root.lstat()
    if lab_info.st_uid != os.geteuid() or stat.S_IMODE(lab_info.st_mode) & 0o022:
        raise ProbeServiceError("lab root owner or permissions are unsafe")
    _require_access(config.lab_root, os.R_OK | os.W_OK | os.X_OK, "lab root")
    _single_regular_file(config.profile_path, "frozen model profile")
    _require_access(config.profile_path, os.R_OK, "frozen model profile")
    _single_regular_file(config.bundle_sealer_public_key, "bundle sealer public key")
    _require_access(config.bundle_sealer_public_key, os.R_OK,
                    "bundle sealer public key")
    key_id = public_fingerprint(config.bundle_sealer_public_key)
    engine = (engine_factory or OllamaProbeEngine)(config.profile_path)
    if not isinstance(engine.profile_id, str) or not engine.profile_id:
        raise ProbeServiceError("engine profile_id is invalid")
    result: dict[str, Any] = {
        "ok": True,
        "offline": offline,
        "profile_id": engine.profile_id,
        "bundle_sealer_key_id": key_id,
    }
    if not offline:
        fingerprint = engine.fingerprint()
        if fingerprint.get("profile_id") != engine.profile_id:
            raise ProbeServiceError("live engine fingerprint profile_id mismatch")
        result["engine_fingerprint"] = fingerprint
    return result


def validate_resources(config: ServiceConfig, *,
                       engine_factory: EngineFactory | None = None) -> None:
    """Validate only the probe UID's frozen inputs and writable lab domain.

    This deliberately does not inspect ABCR-Work and performs no network request;
    the production doctor obtains queue health from ``work_list`` on the broker.
    """
    _real_directory(config.trusted_dev_bundle_root, "trusted DevBundle root")
    _require_access(config.trusted_dev_bundle_root, os.R_OK | os.X_OK,
                    "trusted DevBundle root")
    _real_directory(config.lab_root, "lab root")
    lab_info = config.lab_root.lstat()
    if lab_info.st_uid != os.geteuid() or stat.S_IMODE(lab_info.st_mode) & 0o022:
        raise ProbeServiceError("lab root owner or permissions are unsafe")
    _require_access(config.lab_root, os.R_OK | os.W_OK | os.X_OK, "lab root")
    _single_regular_file(config.profile_path, "frozen model profile")
    _require_access(config.profile_path, os.R_OK, "frozen model profile")
    _single_regular_file(config.bundle_sealer_public_key, "bundle sealer public key")
    _require_access(config.bundle_sealer_public_key, os.R_OK,
                    "bundle sealer public key")
    public_fingerprint(config.bundle_sealer_public_key)
    engine = (engine_factory or OllamaProbeEngine)(config.profile_path)
    if not isinstance(engine.profile_id, str) or not engine.profile_id:
        raise ProbeServiceError("engine profile_id is invalid")


def _config_from_args(args: argparse.Namespace) -> ServiceConfig:
    return ServiceConfig(
        work_root=Path(args.work_root),
        profile_path=Path(args.profile),
        trusted_dev_bundle_root=Path(args.dev_bundle_root),
        bundle_sealer_public_key=Path(args.bundle_sealer_public_key),
        lab_root=Path(args.lab_root),
    )


def fixture_main(argv: list[str] | None = None) -> int:
    """Explicit legacy fixture CLI; never called by the launchd entrypoint."""
    _fixture_spool_guard()
    roots = RuntimeRoots.from_env()
    parser = argparse.ArgumentParser(description="ABCR on-demand local probe worker")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--doctor", action="store_true",
                       help="read-only filesystem and live Ollama fingerprint check")
    modes.add_argument("--offline-doctor", action="store_true",
                       help="read-only filesystem/profile check without network")
    modes.add_argument("--once", action="store_true",
                       help="settle at most one ready work item")
    parser.add_argument("--work-root", default=str(roots.work))
    parser.add_argument("--profile", default=os.environ.get(
        "ABCR_PROBE_PROFILE", str(_DEFAULT_PROFILE)))
    parser.add_argument("--dev-bundle-root", default=str(roots.dev_bundles))
    parser.add_argument("--bundle-sealer-public-key", default=os.environ.get(
        "ABCR_DEVBUNDLE_SEALER_PUBLIC_KEY", str(_DEFAULT_SEALER_PUBLIC_KEY)))
    parser.add_argument("--lab-root", default=str(roots.lab))
    args = parser.parse_args(argv)
    try:
        config = _config_from_args(args)
        if args.doctor or args.offline_doctor:
            print(json.dumps(doctor(config, offline=args.offline_doctor),
                             ensure_ascii=False, sort_keys=True))
        else:
            print(json.dumps({"ok": True, **process_ready(config, once=args.once)},
                             sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__},
                         sort_keys=True), file=sys.stderr)
        return 1


def _queue_domain_config(config: dict[str, Any]) -> ServiceConfig:
    from abcr.control.contracts import strict_object

    settings = strict_object(
        config["settings"],
        required={"profile_path", "trusted_dev_bundle_root",
                  "bundle_sealer_public_key", "lab_root"},
    )
    if not all(isinstance(value, str) and Path(value).is_absolute()
               for value in settings.values()):
        raise ProbeServiceError("trusted probe resource paths must be absolute")
    # ``work_root`` is retained solely for process_ready()/doctor() fixtures.
    return ServiceConfig(
        work_root=Path("/broker-managed/no-spool-access"),
        profile_path=Path(settings["profile_path"]),
        trusted_dev_bundle_root=Path(settings["trusted_dev_bundle_root"]),
        bundle_sealer_public_key=Path(settings["bundle_sealer_public_key"]),
        lab_root=Path(settings["lab_root"]),
    )


def main(argv: list[str] | None = None) -> int:
    """Consume probe work only through the root broker."""
    from abcr.control.queue_runtime import queue_main

    # Backward-compatible *explicit* fixture CLI: path-bearing argv is never
    # accepted in a launched service, while existing unit harnesses stay usable.
    fixture_flags = {"--offline-doctor", "--work-root", "--profile",
                     "--dev-bundle-root", "--bundle-sealer-public-key", "--lab-root"}
    if (not os.environ.get("ABCR_SERVICE_LABEL") and argv is not None
            and any(argument in fixture_flags for argument in argv)):
        return fixture_main(argv)

    def preflight(config: dict[str, Any]) -> None:
        validate_resources(_queue_domain_config(config))

    def make_handler(config: dict[str, Any]):
        domain = _queue_domain_config(config)
        engine = OllamaProbeEngine(domain.profile_path)
        notebook = ProbeNotebook(domain.lab_root)

        def broker_handle(payload: Any, _work_id: str, _fencing_token: int) -> dict[str, Any]:
            return _run_payload(payload, domain, engine, notebook)

        return broker_handle

    return queue_main(argv, service="probe-worker", stage="probe",
                      consumer="abcr-probe", preflight=preflight,
                      make_handler=make_handler)


if __name__ == "__main__":
    raise SystemExit(main())
