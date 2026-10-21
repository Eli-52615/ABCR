"""tests/rig/test_golden_gate —— 黄金测试四件 + 合成 2-step 轨迹（B2-6，R2 硬门）。

torch-free（进常规套件）：③ 已知答案检（golden10）、⑤ 合成 2-step 轨迹。
需 torch+model（@pytest.mark.golden，`pytest -m golden`）：① hook 注入检、② 消融检、④ 双跑一致检。
Mac MPS 红且逻辑无误 → PROGRESS 记录 + 云 CUDA 复验（Mac 结果 non-citable）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from abcr.common.ledger_ref import RunLedger, append_record
from abcr.ledger.schema import validate_step
from abcr.rig import scorer

REPO = Path(__file__).resolve().parents[2]

try:
    import torch
    HAS_TORCH = True
except ImportError:
    torch = None
    HAS_TORCH = False

CACHED_3B = Path("/Users/superagent/.cache/modelscope/models/Qwen--Qwen2.5-3B-Instruct/snapshots/master")
CACHED_05B = Path("/Users/superagent/.cache/modelscope/models/Qwen--Qwen2.5-0.5B-Instruct/snapshots/master")
_MODEL = CACHED_05B if CACHED_05B.exists() else CACHED_3B
needs_model = pytest.mark.skipif(
    not (HAS_TORCH and _MODEL.exists()),
    reason="需 torch + 本地 Qwen 缓存（Mac 免装大件时跳过；装 torch 后 -m golden 跑）")


# ───────────────────────── ③ 已知答案检（golden10，torch-free）─────────────────────────
def test_known_answer_golden10():
    golden = json.loads((REPO / "data/golden/golden10.json").read_text(encoding="utf-8"))["items"]
    passed = 0
    for it in golden:
        assert scorer.score_golden(it["id"], it["pass_sample"]) is True
        assert scorer.score_golden(it["id"], it["fail_sample"]) is False
        passed += 2
    assert passed == 20   # 10×2 全对


# ───────────────────────── ⑤ 合成 2-step 轨迹（torch-free）─────────────────────────
def _synthetic_step(run_id, traj_id, step_id, action, obs_hash, snap_ref,
                    remaining_budget, traj_stop):
    """构造过 schema 的 48 字段 step（多轮语义字段非 null）。"""
    import hashlib
    return {
        "schema_version": "1.0", "run_id": run_id, "trajectory_id": traj_id, "step_id": step_id,
        "parent_run": None, "git_commit": "synth", "model_id": "fake/deterministic-v1",
        "model_revision": "fixture", "dtype": "none", "quantization": None, "device": "none",
        "engine": "fake", "engine_version": "1.0", "torch_version": None, "cuda_version": None,
        "benchmark": "golden10", "split_hash": "fixture", "item_id": "syn01",
        "condition": "synthetic_test", "trait": None, "trait_pole": None, "method": None,
        "layer": None, "coefficient": None, "intervention_strength": None, "random_seed": 0,
        "env_seed": 0, "prompt_hash": hashlib.sha256(b"p").hexdigest(),
        "chat_template_hash": "fixture", "config_hash": "c" * 12, "action": action,
        "obs_hash": obs_hash, "remaining_budget": remaining_budget, "output_text": "step out",
        "parsed_answer": "step out", "is_correct": None, "latency_ms": 10, "input_tokens": 1,
        "output_tokens": 1, "stop_reason": "fake", "trajectory_stop_reason": traj_stop,
        "trait_score": None, "fluency_score": None, "safety_flags": [],
        "activation_summary": None, "state_snapshot_ref": snap_ref,
        "protocol_ref": "W1-V0.9", "env_lock_ref": "requirements-mac.txt",
    }


def test_synthetic_two_step_trajectory(tmp_path: Path):
    import hashlib
    steps_path = tmp_path / "steps.jsonl"
    traj = "traj-synth-1"
    s0 = _synthetic_step("r-synth", traj, 0, "explore", hashlib.sha256(b"o0").hexdigest(),
                         "state/snap0.json", 5.0, None)          # 中间步 trajectory_stop_reason=null
    s1 = _synthetic_step("r-synth", traj, 1, "finish", hashlib.sha256(b"o1").hexdigest(),
                         "state/snap1.json", 4.0, "task_done")   # 末步 task_done
    # 非 null 关键字段
    for s in (s0, s1):
        assert s["action"] and s["obs_hash"] and s["state_snapshot_ref"] and s["remaining_budget"] is not None
    # 过 schema
    assert validate_step(s0).ok, validate_step(s0).summary()
    assert validate_step(s1).ok, validate_step(s1).summary()
    # 写入 → 挂链
    append_record(steps_path, s0)
    append_record(steps_path, s1)
    RunLedger(tmp_path, "steps").verify_chain()
    # 读回 → 按 trajectory 重放解析
    rows = [json.loads(l) for l in steps_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_traj: dict[str, list[dict]] = {}
    for r in rows:
        by_traj.setdefault(r["trajectory_id"], []).append(r)
    seq = sorted(by_traj[traj], key=lambda x: x["step_id"])
    assert [x["step_id"] for x in seq] == [0, 1]
    assert seq[0]["trajectory_stop_reason"] is None            # 中间步 null
    assert seq[-1]["trajectory_stop_reason"] == "task_done"    # 末步 task_done
    assert seq[0]["state_snapshot_ref"] and seq[1]["state_snapshot_ref"]  # 写读非 null


# ───────────────────────── ① hook 注入检（torch+model，golden）─────────────────────────
@pytest.fixture(scope="module")
def small_model():
    from abcr.rig import models
    model, tok, info = models.load_model_by_id(
        str(_MODEL), revision=None, device="cpu", dtype="float32", verify_samples=False)
    hidden = model.config.hidden_size
    n_layers = model.config.num_hidden_layers
    return model, tok, hidden, n_layers


def _last_hidden_at(model, tok, layer, prompt, hook=None):
    from contextlib import nullcontext
    inputs = tok(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad(), (hook or nullcontext()):
        out = model(**inputs, output_hidden_states=True)
    return out.hidden_states[layer][0, -1, :].float()


@pytest.mark.golden
@needs_model
def test_hook_injection_check(small_model):
    from abcr.rig.hooks import ResidualHook
    model, tok, hidden, n_layers = small_model
    layer = min(18, n_layers // 2)
    torch.manual_seed(42)
    v = torch.randn(hidden)
    v = v / v.norm()
    c = 4.0
    prompt = "请简单回答：你好。"
    h_base = _last_hidden_at(model, tok, layer, prompt)
    h_steer = _last_hidden_at(model, tok, layer, prompt,
                              hook=ResidualHook(model, v, layer, "inject", coef=c))
    delta = (h_steer - h_base).float()
    cos = torch.nn.functional.cosine_similarity(delta, v, dim=0).item()
    ratio = delta.norm().item() / (c * v.norm().item())
    assert cos > 0.99, f"cos={cos}"
    assert 0.95 <= ratio <= 1.05, f"ratio={ratio}"


@pytest.mark.golden
@needs_model
def test_hook_ablation_check(small_model):
    from abcr.rig.hooks import ResidualHook
    model, tok, hidden, n_layers = small_model
    layer = min(18, n_layers // 2)
    torch.manual_seed(7)
    v = torch.randn(hidden)
    v = v / v.norm()
    prompt = "请简单回答：你好。"
    vhat = v / v.norm()
    h_base = _last_hidden_at(model, tok, layer, prompt)
    proj_before = (h_base @ vhat).item()
    h_ablate = _last_hidden_at(model, tok, layer, prompt,
                               hook=ResidualHook(model, v, layer, "ablate"))
    proj_after = (h_ablate @ vhat).item()
    if abs(proj_before) < 1e-3:
        assert abs(proj_after) < 1e-3
    else:
        assert abs(proj_after) / abs(proj_before) < 0.02, f"ratio={abs(proj_after)/abs(proj_before)}"


@pytest.mark.golden
@needs_model
def test_double_run_temp0_consistency(small_model):
    from abcr.rig.runner import generate_once
    model, tok, hidden, n_layers = small_model
    rendered = tok.apply_chat_template(
        [{"role": "user", "content": "只输出数字 5。"}], tokenize=False, add_generation_prompt=True)
    t1, *_ = generate_once(model, tok, rendered, temperature=0.0, max_new_tokens=8)
    t2, *_ = generate_once(model, tok, rendered, temperature=0.0, max_new_tokens=8)
    assert t1 == t2   # temp0 双跑逐字节一致
