"""Direct typed probe execution; no planner, approval, cloud or ledger imports."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from abcr.control.contracts import sha256, utc_now
from abcr.explore.item_pool import iter_bundle_items
from abcr.probe.contracts import EngineOutput, ProbeRequest


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
    for item in iter_bundle_items(request.dev_bundle, trusted_dev_bundle_root,
                                  sealer_public_key=bundle_sealer_public_key):
        prompt = f"{request.persona_text}\n\n任务：\n{item.get('prompt', item.get('instruction', ''))}"
        output = engine.generate(prompt=prompt, seed=request.seed,
                                 max_output_tokens=request.max_output_tokens)
        core = {
            "schema_version": 1, "probe_id": request.probe_id,
            "goal_hash": request.goal_hash, "bundle_id": request.dev_bundle.bundle_id,
            "item_id": item["item_id"], "persona_ref": request.persona_ref,
            "prediction": request.prediction, "seed": request.seed,
            "model_profile": request.model_profile, "prompt_hash": sha256(prompt.encode()),
            "output_text": output.text, "input_tokens": output.input_tokens,
            "output_tokens": output.output_tokens, "latency_ms": output.latency_ms,
            "engine_version": output.engine_version, "citable": False,
            "engine_fingerprint": engine_fingerprint,
            "engine_fingerprint_sha256": engine_fingerprint_sha256,
            "evidence_class": "exploratory_learning_only",
        }
        rows.append(dict(core, row_hash=sha256(core)))
    return ProbeRun(request.probe_id, tuple(rows), started, utc_now())
