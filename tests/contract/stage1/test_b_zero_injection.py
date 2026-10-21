"""S1 Contract Test: zero injection equivalence.

coef=0 with hook attached vs no hook: greedy generation of 20 tokens
must produce identical token id sequences.
"""
import sys
import pathlib

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from abcr.interventions.residual_vector import build as build_rv


def test_zero_injection_equivalence():
    model_path = ROOT / "tests" / "fixtures" / "tinyqwen"
    assert model_path.exists(), f"tinyqwen fixture not found at {model_path}"

    tok = AutoTokenizer.from_pretrained(str(model_path))
    model = AutoModelForCausalLM.from_pretrained(str(model_path), torch_dtype=torch.float32)
    model.eval()

    prompt = "Hello, what is 2+2?"
    inputs = tok(prompt, return_tensors="pt")

    # Generate without hook
    with torch.no_grad():
        out_plain = model.generate(
            **inputs, max_new_tokens=20, do_sample=False,
            pad_token_id=tok.pad_token_id or tok.eos_token_id,
        )

    # Generate with hook (coef=0)
    vector_dir = ROOT / "tests" / "fixtures" / "vector_tiny"
    assert vector_dir.exists(), f"vector_tiny fixture not found at {vector_dir}"

    spec = {
        "method": "residual_vector",
        "vector_dir": str(vector_dir),
        "layer": 2,
        "coefficient": 0.0,
        "positions": "all",
    }
    iv = build_rv(spec, "tinyqwen")
    with torch.no_grad():
        with iv.context(model):
            out_hooked = model.generate(
                **inputs, max_new_tokens=20, do_sample=False,
                pad_token_id=tok.pad_token_id or tok.eos_token_id,
            )

    plain_ids = out_plain[0].tolist()
    hooked_ids = out_hooked[0].tolist()
    assert plain_ids == hooked_ids, (
        f"Zero-injection altered output!\n"
        f"  plain:  {plain_ids}\n"
        f"  hooked: {hooked_ids}"
    )


if __name__ == "__main__":
    test_zero_injection_equivalence()
    print("PASS: test_b_zero_injection")
