"""Direct typed probe execution; no planner, approval, cloud or ledger imports."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from abcr.control.contracts import sha256, utc_now
from abcr.explore.item_pool import iter_bundle_items
from abcr.probe.contracts import EngineOutput, ProbePersona, ProbeRequest


class ProbeEngine(Protocol):
    profile_id: str

    def fingerprint(self) -> dict: ...

    def generate(self, *, prompt: str, seed: int, max_output_tokens: int) -> EngineOutput: ...


class FakeProbeEngine:
    """Deterministic zero-network engine used by CODE_RC and crash tests."""
    profile_id = "fixture"

    def fingerprint(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "engine": "fake-probe-v1",
            "decoding": {"temperature": 0.0},
            "tokenizer_sha256": sha256(b"fixture-tokenizer"),
            "chat_template_sha256": sha256(b"fixture-template"),
            "exact_tokenizer_qualified": True,
        }

    def generate(self, *, prompt: str, seed: int, max_output_tokens: int) -> EngineOutput:
        digest = hashlib.sha256(f"{seed}:{prompt}".encode()).hexdigest()
        text = f"fixture:{digest[:24]}"
        return EngineOutput(text, len(prompt), len(text), 1, "fake-probe-v1")


@dataclass(frozen=True)
class ProbeRun:
    probe_id: str
    rows: tuple[dict, ...]
    started_at: str
    completed_at: str
    citable: bool = False
    label: str = "学习数据·不可引用"


def run_probe(request: ProbeRequest, engine: ProbeEngine, *,
              trusted_dev_bundle_root: Path, bundle_sealer_public_key: Path) -> ProbeRun:
    """`trusted_dev_bundle_root` and `bundle_sealer_public_key` are keyword-only and
    mandatory (no default = no backdoor).

    Both are threaded into `iter_bundle_items`, which routes the read through
    `verify_dev_bundle`; a bundle outside the sealed root, one whose manifest is not
    ``split == "dev"``, or one lacking a valid itempool seal, can no longer reach the
    engine. The seal is what stops a self-built holdout bundle mislabelled as dev.
    """
    if request.model_profile != engine.profile_id:
        raise ValueError(
            f"probe model_profile mismatch: request={request.model_profile!r} "
            f"engine={engine.profile_id!r}")
    # 每个 run 开始时重验一次完整指纹。不能只依赖长寿命 engine 对象第一次
    # generate() 时的缓存，否则 daemon/profile 在两次 run 之间漂移会静默混入。
    engine_fingerprint = engine.fingerprint()
    if engine_fingerprint.get("profile_id") != request.model_profile:
        raise ValueError("engine fingerprint profile_id mismatch")
    engine_fingerprint_sha256 = sha256(engine_fingerprint)
    started = utc_now()
    rows = []
    items = iter_bundle_items(request.dev_bundle, trusted_dev_bundle_root,
                              sealer_public_key=bundle_sealer_public_key)
    controls = {value["persona_ref"]: value["plan"] for value in request.length_controls}
    if request.with_length_control:
        if engine_fingerprint.get("exact_tokenizer_qualified") is not True:
            raise ValueError(
                "probe ③L external BLOCKED: engine has no qualified exact tokenizer/renderer")
        for plan in controls.values():
            if (plan["tokenizer_sha256"] != engine_fingerprint.get("tokenizer_sha256")
                    or plan["chat_template_sha256"]
                    != engine_fingerprint.get("chat_template_sha256")):
                raise ValueError("probe ③L frozen tokenizer/chat-template fingerprint mismatch")
    arms: tuple[tuple[str, str, ProbePersona | None, dict | None], ...] = (
        ("vanilla", "vanilla", None, None),
        *((persona.arm_id, "persona", persona, None) for persona in request.personas),
        *((f"length:{persona.persona_ref}", "length_control", persona,
           controls[persona.persona_ref]) for persona in request.personas
          if request.with_length_control),
    )
    for item in items:
        item_prompt = item.get("prompt", item.get("instruction", ""))
        if not isinstance(item_prompt, str) or not item_prompt:
            raise ValueError(f"probe item {item.get('item_id')!r} has no prompt")
        item_rows: list[dict] = []
        observed_inputs: dict[str, int] = {}
        for arm_id, arm_kind, persona, length_plan in arms:
            # Vanilla is the original task prompt, not an empty pseudo-persona
            # followed by the persona separator.  This keeps the baseline pure.
            if persona is None:
                prompt = item_prompt
            elif length_plan is None:
                prompt = f"{persona.persona_text}\n\n任务：\n{item_prompt}"
            else:
                prompt = f"{length_plan['prompt_text']}\n\n任务：\n{item_prompt}"
            output = engine.generate(prompt=prompt, seed=request.seed,
                                     max_output_tokens=request.max_output_tokens)
            observed_inputs[arm_id] = output.input_tokens
            if arm_kind == "persona" and request.with_length_control:
                paired = controls[persona.persona_ref]
                item_id = item["item_id"]
                if (sha256(prompt.encode("utf-8"))
                        != paired["target_rendered_prompt_sha256s"][item_id]
                        or output.input_tokens
                        != paired["target_rendered_prompt_token_counts"][item_id]):
                    raise ValueError("probe persona runtime prompt drifted from its ③L plan")
            if length_plan is not None:
                item_id = item["item_id"]
                persona_arm = f"persona:{persona.persona_ref}"
                if (sha256(prompt.encode("utf-8"))
                        != length_plan["rendered_prompt_sha256s"][item_id]
                        or output.input_tokens
                        != length_plan["rendered_prompt_token_counts"][item_id]
                        or observed_inputs.get(persona_arm)
                        != length_plan["target_rendered_prompt_token_counts"][item_id]):
                    raise ValueError("probe ③L runtime final prompt is not exact-token paired")
            cell_core = {
                "probe_id": request.probe_id,
                "arm_id": arm_id,
                "item_id": item["item_id"],
                "seed": request.seed,
                "model_profile": request.model_profile,
                "engine_fingerprint_sha256": engine_fingerprint_sha256,
            }
            core = {
                "schema_version": 2, "probe_id": request.probe_id,
                "cell_id": sha256(cell_core),
                "goal_hash": request.goal_hash, "bundle_id": request.dev_bundle.bundle_id,
                "item_id": item["item_id"], "arm_id": arm_id,
                "arm_kind": arm_kind,
                "persona_ref": None if persona is None else persona.persona_ref,
                "persona_sha256": None if persona is None else
                    sha256(persona.persona_text.encode("utf-8")),
                "prediction": request.prediction, "seed": request.seed,
                "model_profile": request.model_profile, "prompt_hash": sha256(prompt.encode()),
                "output_text": output.text, "input_tokens": output.input_tokens,
                "output_tokens": output.output_tokens, "latency_ms": output.latency_ms,
                "engine_version": output.engine_version, "citable": False,
                "engine_fingerprint": engine_fingerprint,
                "engine_fingerprint_sha256": engine_fingerprint_sha256,
                "evidence_class": "exploratory_learning_only",
                "length_control_3l": (
                    "not_requested" if not request.with_length_control else
                    ("exact_task_expansion_control" if length_plan is not None else
                     "paired_design_member")),
            }
            item_rows.append(dict(core, row_hash=sha256(core)))
        rows.extend(item_rows)
    return ProbeRun(request.probe_id, tuple(rows), started, utc_now())
