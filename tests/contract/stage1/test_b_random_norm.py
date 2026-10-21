"""S1 Contract Test: random direction norm preservation and orthogonality.

100 direction_seeds: each random vector must match the reference norm
within 1e-6. Mean |cos(r, v)| < 0.2 and max < 0.6 (dim=64 stats).
Same seed must reproduce same vector.
"""
import sys
import pathlib

import torch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from abcr.interventions.random_direction import _generate_random_vector


def test_random_norm_and_orthogonality():
    vector_dir = ROOT / "tests" / "fixtures" / "vector_tiny"
    pt = torch.load(vector_dir / "response_avg_diff.pt", map_location="cpu", weights_only=True)
    v = pt[2]  # layer 2
    ref_norm = torch.linalg.norm(v).item()
    v_unit = v / torch.linalg.norm(v)
    dim = v.shape[0]  # 64

    # seed 0 is the fixture vector's own seed, so cos(r,v)=1.0 trivially; use 1-100
    cosines = []
    for seed in range(1, 101):
        r = _generate_random_vector(dim, seed, ref_norm)
        r_norm = torch.linalg.norm(r).item()
        assert abs(r_norm - ref_norm) <= 1e-6, (
            f"seed={seed}: norm {r_norm} != ref {ref_norm} (diff={abs(r_norm-ref_norm)})"
        )
        cos = abs((r / r_norm * v_unit).sum().item())
        cosines.append(cos)

    mean_cos = sum(cosines) / len(cosines)
    max_cos = max(cosines)
    assert mean_cos < 0.2, f"Mean |cos| = {mean_cos} >= 0.2"
    assert max_cos < 0.6, f"Max |cos| = {max_cos} >= 0.6"

    # Reproducibility check
    for seed in [1, 42, 99]:
        r1 = _generate_random_vector(dim, seed, ref_norm)
        r2 = _generate_random_vector(dim, seed, ref_norm)
        assert torch.equal(r1, r2), f"seed={seed}: not reproducible"


if __name__ == "__main__":
    test_random_norm_and_orthogonality()
    print("PASS: test_b_random_norm")
