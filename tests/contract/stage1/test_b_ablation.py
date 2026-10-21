"""S1 Contract Test: projection ablation.

After ablation hook, the hidden state at the target layer must have
near-zero projection onto v_hat (atol 1e-5, per position).
"""
import sys
import pathlib

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from abcr.interventions.projection_ablation import build as build_abl


def test_ablation():
    model_path = ROOT / "tests" / "fixtures" / "tinyqwen"
    tok = AutoTokenizer.from_pretrained(str(model_path))
    model = AutoModelForCausalLM.from_pretrained(str(model_path), torch_dtype=torch.float32)
    model.eval()

    prompt = "Hello, what is 2+2?"
    inputs = tok(prompt, return_tensors="pt")

    vector_dir = ROOT / "tests" / "fixtures" / "vector_tiny"
    pt = torch.load(vector_dir / "response_avg_diff.pt", map_location="cpu", weights_only=True)
    v = pt[2]
    v_hat = v / torch.linalg.norm(v)

    spec = {
        "method": "projection_ablation",
        "vector_dir": str(vector_dir),
        "layer": 2,
        "positions": "all",
    }
    iv = build_abl(spec, "tinyqwen")

    with torch.no_grad():
        with iv.context(model):
            out = model(**inputs, output_hidden_states=True)

    hs_layer2 = out.hidden_states[2]  # (1, seq_len, hidden)
    projections = (hs_layer2[0] * v_hat.unsqueeze(0)).sum(dim=-1)

    assert projections.abs().max().item() <= 1e-5, (
        f"Ablation incomplete: max |projection| = {projections.abs().max().item()}"
    )


if __name__ == "__main__":
    test_ablation()
    print("PASS: test_b_ablation")
