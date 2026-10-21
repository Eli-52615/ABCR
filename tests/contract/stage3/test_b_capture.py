"""S3 Contract Test: capture npz legality and summary fields.

Residual vector arm with capture_path set produces a valid npz file
containing proj (float32 array) and meta (JSON with required fields).
Summary statistics (proj_mean, proj_p50, proj_p90) are finite.
"""
import sys
import pathlib
import tempfile

import torch
import numpy as np
from transformers import AutoTokenizer, AutoModelForCausalLM

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from abcr.interventions.residual_vector import build as build_rv
from abcr.interventions.capture import load_capture


def test_capture_npz():
    model_path = ROOT / "tests" / "fixtures" / "tinyqwen"
    tok = AutoTokenizer.from_pretrained(str(model_path))
    model = AutoModelForCausalLM.from_pretrained(str(model_path), torch_dtype=torch.float32)
    model.eval()

    vector_dir = ROOT / "tests" / "fixtures" / "vector_tiny"
    spec = {
        "method": "residual_vector",
        "vector_dir": str(vector_dir),
        "layer": 2,
        "coefficient": 3.0,
        "positions": "response",
    }
    iv = build_rv(spec, "tinyqwen")

    with tempfile.TemporaryDirectory() as tmpdir:
        capture_file = str(pathlib.Path(tmpdir) / "capture.npz")
        iv.capture_path = capture_file

        prompt = "Hello, what is 2+2?"
        inputs = tok(prompt, return_tensors="pt")
        with torch.no_grad():
            with iv.context(model):
                model.generate(
                    **inputs,
                    max_new_tokens=10,
                    do_sample=False,
                )

        assert pathlib.Path(capture_file).exists(), "capture npz not created"

        cap = load_capture(capture_file)

        assert isinstance(cap["proj"], np.ndarray), "proj is not ndarray"
        assert cap["proj"].dtype == np.float32, f"proj dtype = {cap['proj'].dtype}"
        assert len(cap["proj"]) > 0, "proj array is empty"

        meta = cap["meta"]
        assert meta["layer"] == 2
        assert meta["direction_source"] == "residual_vector"
        assert "coefficient" in meta
        assert "n_tokens" in meta
        assert meta["n_tokens"] == len(cap["proj"])

        summary = cap["summary"]
        for key in ["proj_mean", "proj_p50", "proj_p90"]:
            assert key in summary, f"missing summary field: {key}"
            assert np.isfinite(summary[key]), f"{key} is not finite: {summary[key]}"

        assert summary["layer"] == 2
        print(f"  proj shape: {cap['proj'].shape}")
        print(f"  summary: mean={summary['proj_mean']:.4f} p50={summary['proj_p50']:.4f} p90={summary['proj_p90']:.4f}")


if __name__ == "__main__":
    test_capture_npz()
    print("PASS: test_b_capture")
