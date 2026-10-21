"""S2 Contract Test: 0.5B end-to-end PV pipeline smoke check.

optimistic trait, --limit-instructions 2 --limit-questions 5 --n-per-q 1
× dual pole (20 generations, CPU float32)
→ two CSVs → patched generate_vec.py → assert .pt exists, shape correct.
"""
import subprocess
import sys
import pathlib
import os
import hashlib

import pytest
import torch

ROOT = pathlib.Path(__file__).resolve().parents[3]
VENV_PV = ROOT / ".venv-pv" / "bin" / "python"
PV_DIR = ROOT / "third_party" / "persona_vectors"

# V17 成本闸：本文件把 deepseek key 塞进 env 交给 subprocess（真计费路径）。
# 凭据读取只允许发生在 _paid_env() 内、且在闸判定之后；全局闸见 tests/conftest.py。
pytestmark = pytest.mark.paid

APPROVE_ENV = "APPROVE_COST"
_DEEPSEEK_KEY_PATH = "~/oc-boss-state/deepseek.key"


def _cost_approved() -> bool:
    return os.environ.get(APPROVE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _paid_env() -> dict:
    """成本闸 → 凭据读取 → 子进程 env。未批准时凭据文件根本不会被打开。"""
    if not _cost_approved():
        raise RuntimeError(
            f"cost gate: test_pv_e2e_05b spawns subprocesses that issue billable "
            f"deepseek calls; set {APPROVE_ENV}=1 to authorize."
        )
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = open(os.path.expanduser(_DEEPSEEK_KEY_PATH)).read().strip()
    env["OPENAI_BASE_URL"] = "https://api.deepseek.com"
    return env


def _get_model_path(model_key: str) -> str:
    import yaml
    models = yaml.safe_load((ROOT / "configs" / "models.yaml").read_text()).get("models", {})
    return models[model_key]["model_id"]


def _run(cmd: list[str], env: dict | None = None, cwd: str | None = None):
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd, timeout=600)
    if result.returncode != 0:
        print(f"STDOUT: {result.stdout[-500:]}")
        print(f"STDERR: {result.stderr[-500:]}")
        raise RuntimeError(f"Command failed: {' '.join(cmd[:5])}")
    return result


def test_pv_e2e_05b():
    out_dir = ROOT / "pv_bridge" / "out" / "test_e2e_05b"
    out_dir.mkdir(parents=True, exist_ok=True)

    env = _paid_env()   # 成本闸；未批准即 RuntimeError，key 文件从未被打开

    # Generate pos and neg CSVs
    for pole in ["pos", "neg"]:
        csv_path = out_dir / f"optimistic_{pole}.csv"
        if csv_path.exists():
            print(f"  {pole} CSV already exists, skipping generation")
            continue
        _run([
            str(VENV_PV), str(ROOT / "pv_bridge" / "extract_mac.py"),
            "--model-key", "qwen2.5-0.5b-instruct",
            "--trait", "optimistic",
            "--artifact", str(ROOT / "artifacts" / "traits" / "optimistic" / "extract.json"),
            "--pole", pole,
            "--n-per-q", "1",
            "--out-csv", str(csv_path),
            "--device", "cpu",
            "--dtype", "float32",
            "--limit-instructions", "2",
            "--limit-questions", "5",
        ], env=env)
        assert csv_path.exists(), f"CSV not created: {csv_path}"
        print(f"  {pole} CSV: {csv_path}")

    # Run patched generate_vec.py
    vec_out = out_dir / "vectors"
    vec_out.mkdir(exist_ok=True)

    _run([
        str(VENV_PV), str(PV_DIR / "generate_vec.py"),
        "--model_name", _get_model_path("qwen2.5-0.5b-instruct"),
        "--pos_path", str(out_dir / "optimistic_pos.csv"),
        "--neg_path", str(out_dir / "optimistic_neg.csv"),
        "--trait", "optimistic",
        "--save_dir", str(vec_out),
        "--threshold", "50",
        "--dtype", "float32",
    ], env=env, cwd=str(PV_DIR))

    # If threshold 50 produced empty set, retry at 30
    pt_path = vec_out / "optimistic_response_avg_diff.pt"
    if not pt_path.exists():
        print("  threshold=50 empty, retrying at 30 (0.5B weak expressiveness expected)")
        _run([
            str(VENV_PV), str(PV_DIR / "generate_vec.py"),
            "--model_name", _get_model_path("qwen2.5-0.5b-instruct"),
            "--pos_path", str(out_dir / "optimistic_pos.csv"),
            "--neg_path", str(out_dir / "optimistic_neg.csv"),
            "--trait", "optimistic",
            "--save_dir", str(vec_out),
            "--threshold", "30",
            "--dtype", "float32",
        ], env=env, cwd=str(PV_DIR))
        with open(ROOT / "DEVIATIONS.md", "a") as f:
            f.write("[B] 2026-07-11 0.5B e2e烟检: threshold降至30（0.5B表达力弱属预期，烟检只验管线）\n")

    # Assertions
    assert pt_path.exists(), f"Vector .pt not created: {pt_path}"
    vec = torch.load(pt_path, map_location="cpu", weights_only=True)
    expected_shape = (25, 896)  # 24 layers + 1, hidden=896
    assert vec.shape == expected_shape, f"shape {vec.shape} != {expected_shape}"
    assert torch.isfinite(vec).all(), "Vector contains non-finite values"
    assert (vec.abs() > 0).any(), "Vector is all zeros"

    print(f"  PASS: .pt exists, shape={vec.shape}, all finite, non-zero")


if __name__ == "__main__":
    test_pv_e2e_05b()
    print("PASS: test_b_pv_e2e_05b")
