"""Contract test: real model smoke — 0.5B and 3B generate valid steps."""

import json
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from abcr.models import load
from abcr.logging.schema import validate_step, SCHEMA_VERSION


def _generate_and_validate(model_key: str, items: list[dict], seed: int = 42):
    model, tokenizer, meta = load(model_key)
    import torch
    for item in items:
        messages = [{"role": "user", "content": item["prompt"]}]
        rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        import hashlib
        prompt_hash = hashlib.sha256(rendered.encode()).hexdigest()

        torch.manual_seed(seed)
        inputs = tokenizer(rendered, return_tensors="pt").to(model.device)
        input_len = inputs["input_ids"].shape[1]

        import time
        t0 = time.monotonic()
        with torch.no_grad():
            out = model.generate(
                **inputs,
                do_sample=True, temperature=0.7, top_p=1.0,
                max_new_tokens=64, pad_token_id=tokenizer.eos_token_id,
            )
        latency = (time.monotonic() - t0) * 1000

        new_tokens = out[0][input_len:]
        output_text = tokenizer.decode(new_tokens, skip_special_tokens=True)

        assert len(output_text) > 0, f"empty output for {model_key}"
        assert latency > 0, f"zero latency for {model_key}"
        assert len(new_tokens) > 0, f"zero output tokens for {model_key}"

        step = {
            "schema_version": SCHEMA_VERSION,
            "run_id": f"smoke-{model_key}",
            "trajectory_id": f"smoke:{item['id']}:{seed}",
            "step_id": 0,
            "parent_run": None,
            "git_commit": "smoke",
            "config_hash": "smoke",
            "protocol_ref": "smoke",
            "env_lock_ref": "smoke",
            "model_id": model_key,
            "model_revision": "smoke",
            "dtype": meta["dtype"],
            "quantization": None,
            "device": str(model.device),
            "device_backend": meta["device_backend"],
            "engine": "transformers",
            "engine_version": meta["engine_version"],
            "torch_version": meta["torch_version"],
            "cuda_version": None,
            "chat_template_hash": "smoke",
            "benchmark": "smoke",
            "split_hash": "smoke",
            "item_id": item["id"],
            "condition": "vanilla",
            "trait": None,
            "trait_pole": None,
            "method": "none",
            "layer": None,
            "coefficient": None,
            "intervention_strength": None,
            "env_seed": None,
            "action": None,
            "obs_hash": None,
            "remaining_budget": None,
            "stop_reason": "eos" if out[0][-1] == tokenizer.eos_token_id else "max_new_tokens",
            "state_snapshot_ref": None,
            "random_seed": seed,
            "prompt_hash": prompt_hash,
            "output_text": output_text,
            "parsed_answer": None,
            "is_correct": None,
            "latency_ms": round(latency, 1),
            "input_tokens": input_len,
            "output_tokens": len(new_tokens),
            "trait_score": None,
            "fluency_score": None,
            "safety_flags": [],
            "activation_summary": None,
            "citable": False,
            "prev_hash": "0" * 64,
            "entry_hash": "0" * 64,
        }
        validate_step(step)


SMOKE_ITEMS = [
    {"id": "smoke_01", "prompt": "What is 2+2? Answer briefly."},
    {"id": "smoke_02", "prompt": "Name three colors."},
]


def test_qwen_05b_smoke():
    _generate_and_validate("qwen2.5-0.5b-instruct", SMOKE_ITEMS)


@pytest.mark.slow
def test_qwen_3b_smoke():
    _generate_and_validate("qwen2.5-3b-instruct", SMOKE_ITEMS)
