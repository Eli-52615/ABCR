from __future__ import annotations

from pathlib import Path

import pytest

from abcr.control.contracts import sha256
from abcr.explore.item_pool import DevBundleRef
from abcr.explore.length_control import (generate_task_expansion_control,
                                         load_task_expansion_library)
from abcr.probe.contracts import EngineOutput, ProbePersona, ProbeRequest
from abcr.probe.engine import FakeProbeEngine, run_probe


ROOT = Path(__file__).resolve().parents[2]
LIBRARY = load_task_expansion_library(
    ROOT / "configs" / "research" / "length-control" / "task_expansion_zh_v1.json")


def _encode(text: str) -> list[int]:
    return [ord(char) for char in text]


def _render(system: str, item: str) -> str:
    return f"{system}\n\n任务：\n{item}"


def _request() -> ProbeRequest:
    persona_text = "甲" * len(LIBRARY.fragments[0]["text"])
    item_prompts = {"d1": "题一", "d2": "题二"}
    plan = generate_task_expansion_control(
        persona_text, item_prompts, encode=_encode, render_chat=_render,
        tokenizer_sha256=sha256(b"fixture-tokenizer"),
        chat_template_sha256=sha256(b"fixture-template"), library=LIBRARY)
    bundle = DevBundleRef("a" * 64, ROOT, "b" * 64, tuple(item_prompts), "c" * 64)
    return ProbeRequest(
        "P-3L", "d" * 64, bundle, (ProbePersona("p@v1", persona_text),),
        "increase", 7, "fixture", 16, True,
        ({"persona_ref": "p@v1", "plan": plan},))


def test_fast_lane_runs_vanilla_persona_and_every_precompiled_3l(monkeypatch):
    request = _request()
    monkeypatch.setattr(
        "abcr.probe.engine.iter_bundle_items",
        lambda *_args, **_kwargs: iter((
            {"item_id": "d1", "prompt": "题一"},
            {"item_id": "d2", "prompt": "题二"},
        )))
    run = run_probe(request, FakeProbeEngine(), trusted_dev_bundle_root=ROOT,
                    bundle_sealer_public_key=ROOT / "unused")
    assert request.arm_ids == ("vanilla", "persona:p@v1", "length:p@v1")
    assert len(run.rows) == 6
    for item_id in request.dev_bundle.item_ids:
        item_rows = [row for row in run.rows if row["item_id"] == item_id]
        assert {row["arm_id"] for row in item_rows} == set(request.arm_ids)
        paired = [row for row in item_rows if row["arm_id"] != "vanilla"]
        assert paired[0]["input_tokens"] == paired[1]["input_tokens"]


def test_fast_lane_refuses_missing_arm_drift_and_unqualified_external_engine(monkeypatch):
    request = _request()
    with pytest.raises(ValueError, match="one precompiled"):
        ProbeRequest(
            request.probe_id, request.goal_hash, request.dev_bundle, request.personas,
            request.prediction, request.seed, request.model_profile,
            request.max_output_tokens, True, ())

    monkeypatch.setattr(
        "abcr.probe.engine.iter_bundle_items",
        lambda *_args, **_kwargs: iter(({"item_id": "d1", "prompt": "题一"},)))

    class Unqualified(FakeProbeEngine):
        def fingerprint(self):
            value = super().fingerprint()
            value.pop("exact_tokenizer_qualified")
            return value

    with pytest.raises(ValueError, match="external BLOCKED"):
        run_probe(request, Unqualified(), trusted_dev_bundle_root=ROOT,
                  bundle_sealer_public_key=ROOT / "unused")

    class Drifting(FakeProbeEngine):
        def generate(self, *, prompt, seed, max_output_tokens):
            original = super().generate(prompt=prompt, seed=seed,
                                        max_output_tokens=max_output_tokens)
            return EngineOutput(original.text, original.input_tokens + 1,
                                original.output_tokens, original.latency_ms,
                                original.engine_version)

    with pytest.raises(ValueError, match="runtime prompt"):
        run_probe(request, Drifting(), trusted_dev_bundle_root=ROOT,
                  bundle_sealer_public_key=ROOT / "unused")
