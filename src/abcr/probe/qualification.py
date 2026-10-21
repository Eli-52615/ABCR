"""Honest 20-item LIVE qualification for the local probe model/SLO boundary.

This module deliberately qualifies only the frozen local engine + trusted
DevBundle path.  Running it directly does not prove launchd, broker, Feishu, or
reconciliation E2E; the emitted evidence keeps that deployment layer BLOCKED.
"""
from __future__ import annotations

import json
import os
import stat
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from abcr.control.contracts import canonical_json, sha256, utc_now
from abcr.control.ed25519 import public_fingerprint
from abcr.explore.item_pool import DevBundleRef, iter_bundle_items, verify_dev_bundle
from abcr.probe.contracts import EngineOutput, ProbePersona, ProbeRequest
from abcr.probe.engine import ProbeEngine, run_probe
from abcr.probe.notebook import ProbeNotebook
from abcr.probe.ollama_engine import OllamaProbeEngine


REQUIRED_ITEM_COUNT = 20
REQUIRED_PERSONA_COUNT = 2
SLO_SECONDS = 40 * 60

_ROW_FIELDS = frozenset({
    "schema_version", "probe_id", "cell_id", "goal_hash", "bundle_id",
    "item_id", "arm_id", "arm_kind", "persona_ref", "persona_sha256",
    "prediction", "seed", "model_profile", "prompt_hash", "output_text",
    "input_tokens", "output_tokens", "latency_ms", "engine_version",
    "citable", "engine_fingerprint", "engine_fingerprint_sha256",
    "evidence_class", "length_control_3l", "row_hash",
})


class QualificationError(RuntimeError):
    """A malformed prerequisite or qualification invariant."""


@dataclass(frozen=True)
class QualificationConfig:
    profile_path: Path
    trusted_dev_bundle_root: Path
    bundle_id: str
    bundle_sealer_public_key: Path
    lab_root: Path
    evidence_path: Path
    personas: tuple[ProbePersona, ...]
    prediction: str
    seed: int
    max_output_tokens: int = 256
    bundle_authority: Literal["production_itempool", "qualification_fixture"] = \
        "qualification_fixture"
    with_length_control: bool = False
    length_controls: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        for name in ("profile_path", "trusted_dev_bundle_root",
                     "bundle_sealer_public_key", "lab_root", "evidence_path"):
            object.__setattr__(self, name, Path(getattr(self, name)))
        if (len(self.bundle_id) != 64
                or any(char not in "0123456789abcdef" for char in self.bundle_id)):
            raise QualificationError("bundle_id must be 64 lowercase hex characters")
        if len(self.personas) != REQUIRED_PERSONA_COUNT:
            raise QualificationError("LIVE qualification requires exactly 2 personas")
        # Reuse the production contract to enforce prediction/seed/persona shape.
        if (not isinstance(self.prediction, str) or not self.prediction.strip()
                or "\n" in self.prediction or "\r" in self.prediction):
            raise QualificationError("LIVE qualification requires one prediction line")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise QualificationError("seed must be an integer")
        if (isinstance(self.max_output_tokens, bool)
                or not isinstance(self.max_output_tokens, int)
                or not 1 <= self.max_output_tokens <= 4096):
            raise QualificationError("max_output_tokens must be in [1, 4096]")
        if self.bundle_authority not in {
                "production_itempool", "qualification_fixture"}:
            raise QualificationError("bundle_authority is not a reviewed value")
        if not isinstance(self.with_length_control, bool):
            raise QualificationError("with_length_control must be boolean")
        if not isinstance(self.length_controls, tuple):
            raise QualificationError("length_controls must be a tuple")
        if self.with_length_control != bool(self.length_controls):
            raise QualificationError("requested ③L requires precompiled controls")


def load_persona_config(path: Path) -> tuple[ProbePersona, ProbePersona]:
    """Load a finite exact-shape two-persona qualification file."""
    path = Path(path)
    info = path.lstat()
    if (path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_size > 256 * 1024):
        raise QualificationError("persona config must be a small single-link regular file")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "personas"}:
        raise QualificationError("persona config fields mismatch")
    if raw["schema_version"] != 1 or not isinstance(raw["personas"], list) \
            or len(raw["personas"]) != REQUIRED_PERSONA_COUNT:
        raise QualificationError("persona config must contain exactly 2 personas")
    personas: list[ProbePersona] = []
    for value in raw["personas"]:
        if not isinstance(value, dict) or set(value) != {"persona_ref", "persona_text"}:
            raise QualificationError("persona entry fields mismatch")
        personas.append(ProbePersona(value["persona_ref"], value["persona_text"]))
    if len({persona.persona_ref for persona in personas}) != REQUIRED_PERSONA_COUNT:
        raise QualificationError("qualification persona refs must be distinct")
    return personas[0], personas[1]


def _load_verified_bundle(config: QualificationConfig) -> DevBundleRef:
    root = config.trusted_dev_bundle_root
    bundle_root = root / config.bundle_id
    manifest_path = bundle_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    item_ids = manifest.get("item_ids")
    if (manifest.get("bundle_id") != config.bundle_id
            or not isinstance(item_ids, list)
            or len(item_ids) != REQUIRED_ITEM_COUNT
            or len(item_ids) != len(set(item_ids))
            or manifest.get("item_count") != REQUIRED_ITEM_COUNT
            or manifest.get("split") != "dev"):
        raise QualificationError(
            "qualification requires one sealed dev bundle with exactly 20 unique items")
    ref = DevBundleRef(
        bundle_id=config.bundle_id,
        root=bundle_root,
        manifest_hash=sha256(manifest),
        item_ids=tuple(item_ids),
        source_hash=manifest.get("source_sha256"),
    )
    verify_dev_bundle(ref, root, sealer_public_key=config.bundle_sealer_public_key)
    return ref


def _bundle_authority(config: QualificationConfig, bundle: DevBundleRef) -> dict[str, Any]:
    """Describe, and for production strictly prove, the DevBundle trust root.

    A caller-supplied public key can prove internal cryptographic consistency but
    cannot by itself prove that the production item-pool selected the items.  The
    evidence therefore distinguishes a qualification fixture from the fixed,
    root-owned production trust paths instead of calling both simply "trusted".
    """
    key = config.bundle_sealer_public_key
    root = config.trusted_dev_bundle_root
    try:
        key_info = key.lstat()
        root_info = root.lstat()
        bundle_info = bundle.root.lstat()
    except OSError as exc:
        raise QualificationError("DevBundle authority path is unavailable") from exc
    if (key.is_symlink() or not stat.S_ISREG(key_info.st_mode) or key_info.st_nlink != 1
            or root.is_symlink() or not stat.S_ISDIR(root_info.st_mode)
            or bundle.root.is_symlink() or not stat.S_ISDIR(bundle_info.st_mode)):
        raise QualificationError("DevBundle authority paths are not regular/real")
    try:
        key_id = public_fingerprint(key)
        key_bytes_sha256 = sha256(key.read_bytes())
    except Exception as exc:
        raise QualificationError("DevBundle sealer public key is invalid") from exc

    production = config.bundle_authority == "production_itempool"
    if production:
        expected_root = Path("/Library/Application Support/ABCR-DevBundles")
        expected_key = Path("/Library/Application Support/ABCR-Trust/dev-bundle-sealer.pub")
        if root != expected_root or key != expected_key:
            raise QualificationError(
                "production_itempool authority requires the fixed production paths")
        if (root_info.st_uid != 0 or bundle_info.st_uid != 0 or key_info.st_uid != 0
                or stat.S_IMODE(root_info.st_mode) & 0o022
                or stat.S_IMODE(bundle_info.st_mode) & 0o022
                or stat.S_IMODE(key_info.st_mode) != 0o444):
            raise QualificationError(
                "production_itempool authority owner/mode proof failed")
    return {
        "authority_class": config.bundle_authority,
        "production_itempool_proven": production,
        "sealer_key_id": key_id,
        "sealer_public_key_bytes_sha256": key_bytes_sha256,
        "bundle_root_realpath": str(root.resolve()),
        "bundle_directory_owner_uid": bundle_info.st_uid,
        "bundle_directory_mode": format(stat.S_IMODE(bundle_info.st_mode), "04o"),
    }


class _TimedEngine:
    def __init__(self, delegate: ProbeEngine):
        self.delegate = delegate
        self.profile_id = delegate.profile_id
        self.generations: list[dict[str, Any]] = []

    def fingerprint(self) -> dict:
        return self.delegate.fingerprint()

    def generate(self, *, prompt: str, seed: int,
                 max_output_tokens: int) -> EngineOutput:
        started = time.monotonic()
        try:
            output = self.delegate.generate(
                prompt=prompt, seed=seed, max_output_tokens=max_output_tokens)
        except Exception:
            self.generations.append({
                "completed": False,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            })
            raise
        self.generations.append({
            "completed": True,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "backend_latency_ms": output.latency_ms,
            "input_tokens": output.input_tokens,
            "output_tokens": output.output_tokens,
        })
        return output


def _validate_qualification_rows(
    rows: tuple[dict[str, Any], ...],
    *,
    request: ProbeRequest,
    fingerprint: dict[str, Any],
    trusted_dev_bundle_root: Path,
    bundle_sealer_public_key: Path,
) -> None:
    """Re-derive every scientific cell before publishing qualification evidence.

    This intentionally does not trust ``run_probe`` merely because it returned 60
    dictionaries.  It catches a regressed/forged old-schema producer, duplicated
    cells, arm relabelling, persona-tainted vanilla prompts, and identity drift.
    """
    expected_row_count = REQUIRED_ITEM_COUNT * len(request.arm_ids)
    if len(rows) != expected_row_count:
        raise QualificationError("strict qualification cell count invariant failed")
    expected_fingerprint_hash = sha256(fingerprint)
    persona_by_arm = {persona.arm_id: persona for persona in request.personas}
    persona_by_arm.update({f"length:{persona.persona_ref}": persona
                           for persona in request.personas
                           if request.with_length_control})
    control_by_ref = {value["persona_ref"]: value["plan"]
                      for value in request.length_controls}
    expected_arms = set(request.arm_ids)
    items = iter_bundle_items(
        request.dev_bundle, trusted_dev_bundle_root,
        sealer_public_key=bundle_sealer_public_key,
    )
    prompt_by_item: dict[str, str] = {}
    for item in items:
        item_id = item.get("item_id")
        prompt = item.get("prompt", item.get("instruction", ""))
        if not isinstance(item_id, str) or not isinstance(prompt, str) or not prompt:
            raise QualificationError("verified qualification item identity/prompt invalid")
        prompt_by_item[item_id] = prompt
    if set(prompt_by_item) != set(request.dev_bundle.item_ids):
        raise QualificationError("verified qualification item set drifted")

    seen_cells: set[tuple[str, str, int]] = set()
    seen_hashes: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_FIELDS:
            raise QualificationError("qualification row fields/schema mismatch")
        arm_id = row.get("arm_id")
        item_id = row.get("item_id")
        seed = row.get("seed")
        if arm_id not in expected_arms or item_id not in prompt_by_item \
                or seed != request.seed:
            raise QualificationError("qualification row cell is outside the fixed design")
        cell = (arm_id, item_id, seed)
        if cell in seen_cells:
            raise QualificationError("qualification contains a duplicate cell")
        seen_cells.add(cell)

        persona = persona_by_arm.get(arm_id)
        expected_kind = ("vanilla" if persona is None else
                         ("length_control" if arm_id.startswith("length:") else "persona"))
        expected_persona_ref = None if persona is None else persona.persona_ref
        expected_persona_hash = (None if persona is None else
                                 sha256(persona.persona_text.encode("utf-8")))
        item_prompt = prompt_by_item[item_id]
        # Vanilla must be byte-for-byte the original task prompt.  In particular it
        # must not pass through the persona separator with an empty pseudo-persona.
        if persona is None:
            expected_prompt = item_prompt
        elif expected_kind == "length_control":
            expected_prompt = (f"{control_by_ref[persona.persona_ref]['prompt_text']}"
                               f"\n\n任务：\n{item_prompt}")
        else:
            expected_prompt = f"{persona.persona_text}\n\n任务：\n{item_prompt}"
        expected_length_status = (
            "not_requested" if not request.with_length_control else
            ("exact_task_expansion_control" if expected_kind == "length_control"
             else "paired_design_member"))
        expected_cell_id = sha256({
            "probe_id": request.probe_id,
            "arm_id": arm_id,
            "item_id": item_id,
            "seed": request.seed,
            "model_profile": request.model_profile,
            "engine_fingerprint_sha256": expected_fingerprint_hash,
        })
        numeric_fields = ("input_tokens", "output_tokens", "latency_ms")
        if (row["schema_version"] != 2
                or row["probe_id"] != request.probe_id
                or row["goal_hash"] != request.goal_hash
                or row["bundle_id"] != request.dev_bundle.bundle_id
                or row["arm_kind"] != expected_kind
                or row["persona_ref"] != expected_persona_ref
                or row["persona_sha256"] != expected_persona_hash
                or row["prediction"] != request.prediction
                or row["model_profile"] != request.model_profile
                or row["prompt_hash"] != sha256(expected_prompt.encode("utf-8"))
                or row["cell_id"] != expected_cell_id
                or row["engine_fingerprint"] != fingerprint
                or row["engine_fingerprint_sha256"] != expected_fingerprint_hash
                or row["citable"] is not False
                or row["evidence_class"] != "exploratory_learning_only"
                or row["length_control_3l"] != expected_length_status
                or not isinstance(row["output_text"], str)
                or not isinstance(row["engine_version"], str)
                or not row["engine_version"]
                or any(isinstance(row[name], bool) or not isinstance(row[name], int)
                       or row[name] < 0 for name in numeric_fields)):
            raise QualificationError("qualification row binding/content invariant failed")
        core = {key: value for key, value in row.items() if key != "row_hash"}
        if row["row_hash"] != sha256(core) or row["row_hash"] in seen_hashes:
            raise QualificationError("qualification row hash invariant failed")
        seen_hashes.add(row["row_hash"])

    expected_cells = {(arm_id, item_id, request.seed)
                      for item_id in request.dev_bundle.item_ids
                      for arm_id in request.arm_ids}
    if seen_cells != expected_cells:
        raise QualificationError("strict qualification cell coverage invariant failed")


def _write_evidence_once(path: Path, value: dict[str, Any]) -> None:
    """Atomically publish immutable evidence without overwriting an older run."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise QualificationError(f"evidence path already exists: {path}")
    payload = canonical_json(value) + b"\n"
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # link(2) fails if another process won the same evidence name and therefore
        # gives us atomic no-clobber publication.
        os.link(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if tmp.exists():
            tmp.unlink()


def qualify_local_probe(
    config: QualificationConfig,
    *,
    engine: ProbeEngine,
    mode: Literal["live", "test"] = "live",
) -> dict[str, Any]:
    """Run and atomically record the strict 2-persona + vanilla x 20 gate.

    ``mode='test'`` exists solely for no-network contract tests and can never emit
    PASS.  The public CLI always supplies the real ``OllamaProbeEngine`` in live
    mode.
    """
    if mode not in {"live", "test"}:
        raise QualificationError("invalid qualification mode")
    if mode == "live" and type(engine) is not OllamaProbeEngine:
        # A protocol-compatible fixture or subclass can be useful for tests, but it
        # must never turn a fake backend into LIVE PASS evidence.
        raise QualificationError("LIVE qualification requires exact OllamaProbeEngine")

    started_at = utc_now()
    t0 = time.monotonic()
    stage = "fingerprint_preflight"
    timings: dict[str, float] = {}
    fingerprint: dict[str, Any] | None = None
    bundle_authority: dict[str, Any] | None = None
    timed = _TimedEngine(engine)
    rows: tuple[dict[str, Any], ...] = ()
    outcome = "BLOCKED"
    failure: dict[str, Any] | None = None
    bundle: DevBundleRef | None = None
    try:
        mark = time.monotonic()
        fingerprint = engine.fingerprint()
        timings[stage] = round((time.monotonic() - mark) * 1000, 3)
        if fingerprint.get("profile_id") != engine.profile_id:
            raise QualificationError("fingerprint profile_id mismatch")
        if config.with_length_control and fingerprint.get("exact_tokenizer_qualified") is not True:
            stage = "length_control_prerequisite"
            raise QualificationError(
                "③L external BLOCKED: frozen engine exposes no qualified exact tokenizer/renderer")

        stage = "dev_bundle_verification"
        mark = time.monotonic()
        bundle = _load_verified_bundle(config)
        bundle_authority = _bundle_authority(config, bundle)
        timings[stage] = round((time.monotonic() - mark) * 1000, 3)

        stage = "model_generation"
        qualification_input = {
            "bundle_id": bundle.bundle_id,
            "bundle_authority": bundle_authority,
            "personas": [{"persona_ref": persona.persona_ref,
                          "persona_text_sha256": sha256(
                              persona.persona_text.encode("utf-8"))}
                         for persona in config.personas],
            "prediction": config.prediction,
            "seed": config.seed,
            "profile": engine.profile_id,
            "engine_fingerprint_sha256": sha256(fingerprint),
            "max_output_tokens": config.max_output_tokens,
            "with_length_control": config.with_length_control,
            "length_control_plan_hashes": [sha256(value["plan"])
                                            for value in config.length_controls],
        }
        qualification_hash = sha256(qualification_input)
        request = ProbeRequest(
            probe_id="LIVEQUAL-" + qualification_hash[:24],
            # A qualification is not a confirmed research goal.  Use a distinct,
            # deterministic input hash rather than a fabricated research anchor.
            goal_hash=qualification_hash,
            dev_bundle=bundle,
            personas=config.personas,
            prediction=config.prediction,
            seed=config.seed,
            model_profile=engine.profile_id,
            max_output_tokens=config.max_output_tokens,
            with_length_control=False,
            length_controls=(),
        )
        if config.with_length_control:
            request = ProbeRequest(
                probe_id=request.probe_id, goal_hash=request.goal_hash,
                dev_bundle=request.dev_bundle, personas=request.personas,
                prediction=request.prediction, seed=request.seed,
                model_profile=request.model_profile,
                max_output_tokens=request.max_output_tokens,
                with_length_control=True, length_controls=config.length_controls)
        mark = time.monotonic()
        probe_run = run_probe(
            request, timed,
            trusted_dev_bundle_root=config.trusted_dev_bundle_root,
            bundle_sealer_public_key=config.bundle_sealer_public_key,
        )
        timings[stage] = round((time.monotonic() - mark) * 1000, 3)
        rows = probe_run.rows

        stage = "shape_validation"
        mark = time.monotonic()
        _validate_qualification_rows(
            rows, request=request, fingerprint=fingerprint,
            trusted_dev_bundle_root=config.trusted_dev_bundle_root,
            bundle_sealer_public_key=config.bundle_sealer_public_key,
        )
        timings[stage] = round((time.monotonic() - mark) * 1000, 3)

        stage = "notebook_publish"
        mark = time.monotonic()
        notebook = ProbeNotebook(config.lab_root)
        for row in rows:
            notebook.append(row)
        timings[stage] = round((time.monotonic() - mark) * 1000, 3)

        elapsed = time.monotonic() - t0
        if mode == "test":
            outcome = "TEST_ONLY"
        else:
            outcome = "PASS" if elapsed <= SLO_SECONDS else "FAIL"
            if outcome == "FAIL":
                failure = {"stage": "slo", "error_type": "SLOExceeded",
                           "reason": "completed without shrinking, but exceeded 40 minutes"}
    except Exception as exc:
        elapsed = time.monotonic() - t0
        outcome = "TEST_ONLY_FAILED" if mode == "test" else (
            "FAIL" if stage in {"model_generation", "shape_validation",
                                "notebook_publish", "slo"}
            else "BLOCKED")
        failure = {"stage": stage, "error_type": type(exc).__name__,
                   "reason": str(exc)[:1000]}

    completed_generations = [item for item in timed.generations if item["completed"]]
    slowest = max(completed_generations, key=lambda item: item["elapsed_ms"], default=None)
    total_elapsed = time.monotonic() - t0
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "evidence_type": "ABCRLocalProbeLiveQualification",
        "qualification_scope": (
            "local_frozen_model_plus_production_itempool_devbundle_slo"
            if config.bundle_authority == "production_itempool" else
            "local_frozen_model_plus_cryptographic_fixture_devbundle_slo"),
        "scope_status": outcome,
        "started_at": started_at,
        "completed_at": utc_now(),
        "elapsed_seconds": round(total_elapsed, 3),
        "slo_seconds": SLO_SECONDS,
        "slo_met": (outcome == "PASS" if mode == "live" else None),
        "strict_shape": {
            "item_count_required": REQUIRED_ITEM_COUNT,
            "persona_count_required": REQUIRED_PERSONA_COUNT,
            "vanilla_required": True,
            "arm_count_required": 5 if config.with_length_control else 3,
            "generation_count_required": 100 if config.with_length_control else 60,
            "items_observed": 0 if bundle is None else len(bundle.item_ids),
            "rows_published": len(rows),
            "generations_completed": len(completed_generations),
            "shrinking_permitted": False,
        },
        "inputs": {
            "profile_id": engine.profile_id,
            "bundle_id": config.bundle_id,
            "bundle_authority": bundle_authority,
            "bundle_split": None if bundle is None else "dev",
            "bundle_item_ids": [] if bundle is None else list(bundle.item_ids),
            "persona_refs": [persona.persona_ref for persona in config.personas],
            "persona_text_sha256": [sha256(persona.persona_text.encode("utf-8"))
                                    for persona in config.personas],
            "prediction": config.prediction,
            "seed": config.seed,
            "max_output_tokens": config.max_output_tokens,
            "with_length_control": config.with_length_control,
        },
        "fingerprint_verified_before_generation": fingerprint is not None,
        "engine_fingerprint": fingerprint,
        "engine_fingerprint_sha256": None if fingerprint is None else sha256(fingerprint),
        "notebook": {
            "citable": False,
            "label": "学习数据·不可引用",
            "row_hashes": [row["row_hash"] for row in rows],
        },
        "length_control_3l": {
            "requested": config.with_length_control,
            "status": ("NOT_REQUESTED" if not config.with_length_control else
                       ("PASS" if outcome in {"PASS", "TEST_ONLY"} else
                        "BLOCKED_EXTERNAL" if failure is not None
                        and failure.get("stage") == "length_control_prerequisite"
                        else "FAIL")),
            "claim": ("not requested in this qualification" if not config.with_length_control
                      else "complete persona+own-③L multi-arm design; no approximation"),
        },
        "timing": {
            "stages_ms": timings,
            "generation_elapsed_ms_sum": round(sum(
                item["elapsed_ms"] for item in timed.generations), 3),
            "slowest_generation": slowest,
            "bottleneck_stage": (max(timings, key=timings.get) if timings else stage),
        },
        "failure": failure,
        "deployment_e2e": {
            "status": "BLOCKED",
            "reason_code": "DIRECT_QUALIFICATION_DOES_NOT_EXERCISE_DEPLOYED_QUEUE_OR_FEISHU",
            "required_followup": "Feishu -> Operator -> broker -> probe worker -> reconcile",
        },
        "autonomous_qualification_claimed": False,
        "test_mode": mode == "test",
    }
    evidence["evidence_sha256"] = sha256(evidence)
    _write_evidence_once(config.evidence_path, evidence)
    return evidence


def live_engine(profile_path: Path) -> OllamaProbeEngine:
    """Small factory kept separate so tests never need to touch the daemon."""
    return OllamaProbeEngine(profile_path)
