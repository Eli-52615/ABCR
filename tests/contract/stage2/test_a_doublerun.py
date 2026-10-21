"""Contract test: temp0 double-run determinism — same config → same output byte-for-byte."""

import sys
import torch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from abcr.models import load

PROMPTS = [
    "What is the capital of France?",
    "List two prime numbers.",
]


def _generate_temp0(model, tokenizer, prompt: str) -> str:
    messages = [{"role": "user", "content": prompt}]
    rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    torch.manual_seed(0)
    inputs = tokenizer(rendered, return_tensors="pt").to(model.device)
    input_len = inputs["input_ids"].shape[1]
    with torch.no_grad():
        out = model.generate(
            **inputs, do_sample=False, max_new_tokens=64,
            pad_token_id=tokenizer.eos_token_id,
        )
    return tokenizer.decode(out[0][input_len:], skip_special_tokens=True)


def test_doublerun_05b():
    model, tokenizer, _ = load("qwen2.5-0.5b-instruct")
    for prompt in PROMPTS:
        out1 = _generate_temp0(model, tokenizer, prompt)
        out2 = _generate_temp0(model, tokenizer, prompt)
        assert out1 == out2, f"0.5B CPU temp0 non-deterministic for: {prompt[:30]}"


def test_doublerun_3b():
    model, tokenizer, meta = load("qwen2.5-3b-instruct")
    for prompt in PROMPTS:
        out1 = _generate_temp0(model, tokenizer, prompt)
        out2 = _generate_temp0(model, tokenizer, prompt)
        assert out1 == out2, f"3B temp0 non-deterministic for: {prompt[:30]}"
