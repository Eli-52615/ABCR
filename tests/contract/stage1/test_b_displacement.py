"""S1 Contract Test: residual displacement.

positions='all', coef=3.0, layer=2: hidden states at layer 2 after
hook must differ from plain by exactly 3.0 * v (atol 1e-5).
Downstream layers (index > 2) must change; upstream (index < 2) must not.
"""
import sys
import pathlib

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from abcr.interventions.residual_vector import build as build_rv


def test_displacement():
    model_path = ROOT / "tests" / "fixtures" / "tinyqwen"
    tok = AutoTokenizer.from_pretrained(str(model_path))
    model = AutoModelForCausalLM.from_pretrained(str(model_path), torch_dtype=torch.float32)
    model.eval()

    prompt = "Hello, what is 2+2?"
    inputs = tok(prompt, return_tensors="pt")

    # Forward without hook
    with torch.no_grad():
        out_plain = model(**inputs, output_hidden_states=True)
    hs_plain = [h.clone() for h in out_plain.hidden_states]

    # Forward with hook
    vector_dir = ROOT / "tests" / "fixtures" / "vector_tiny"
    spec = {
        "method": "residual_vector",
        "vector_dir": str(vector_dir),
        "layer": 2,
        "coefficient": 3.0,
        "positions": "all",
    }
    iv = build_rv(spec, "tinyqwen")
    with torch.no_grad():
        with iv.context(model):
            out_hooked = model(**inputs, output_hidden_states=True)
    hs_hooked = [h.clone() for h in out_hooked.hidden_states]

    # Load vector for comparison
    pt = torch.load(vector_dir / "response_avg_diff.pt", map_location="cpu", weights_only=True)
    v = pt[2]  # layer 2

    # Assert: hooked[2] - plain[2] ≈ 3.0 * v
    diff = hs_hooked[2] - hs_plain[2]
    expected = 3.0 * v
    assert torch.allclose(diff, expected.unsqueeze(0).unsqueeze(0).expand_as(diff), atol=1e-5), (
        f"Displacement mismatch: max diff = {(diff - expected).abs().max().item()}"
    )

    # Upstream layers (index < 2) unchanged
    for i in range(2):
        assert torch.allclose(hs_hooked[i], hs_plain[i], atol=1e-6), (
            f"Upstream layer {i} changed unexpectedly"
        )

    # Downstream layers (index > 2) must have changed
    for i in range(3, len(hs_plain)):
        assert not torch.allclose(hs_hooked[i], hs_plain[i], atol=1e-6), (
            f"Downstream layer {i} did NOT change (hook not propagating)"
        )


if __name__ == "__main__":
    test_displacement()
    print("PASS: test_b_displacement")
