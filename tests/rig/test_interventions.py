"""tests/rig/test_interventions —— 三件干预（B2-3）。

prompt_persona 纯函数（无 torch）；residual_vector/controls 需 torch（缺则 skip）。
"""
from __future__ import annotations

import pytest

from abcr.rig.interventions import prompt_persona

try:
    import torch
    HAS_TORCH = True
except ImportError:
    torch = None
    HAS_TORCH = False

needs_torch = pytest.mark.skipif(not HAS_TORCH, reason="torch 未装（Mac 免装大件；云上/装 torch 后跑）")


# ───────────────────────── prompt_persona（torch-free）─────────────────────────
def test_build_system_format():
    assert prompt_persona.build_system("Be careful.", "conscientiousness") == \
        "You are a/an conscientiousness assistant. Be careful."


def test_assistant_name_pos_neg_override():
    assert prompt_persona.assistant_name_for("optimistic", "pos") == "optimistic"
    assert prompt_persona.assistant_name_for("optimistic", "neg") == "pessimistic"
    assert prompt_persona.assistant_name_for("weirdtrait", "neg") == "helpful"
    assert prompt_persona.assistant_name_for("optimistic", "pos", override="custom") == "custom"


def test_from_config_selects_pole_and_instruction():
    artifact = {"instruction": [{"pos": "P0", "neg": "N0"}, {"pos": "P1", "neg": "N1"}],
                "questions": [], "eval_prompt": ""}
    cfg_pos = {"intervention": {"trait": "openness", "trait_pole": "pos", "instruction_index": 1}}
    assert prompt_persona.from_config(cfg_pos, artifact) == "You are a/an openness assistant. P1"
    cfg_neg = {"intervention": {"trait": "openness", "trait_pole": "neg"}}
    assert prompt_persona.from_config(cfg_neg, artifact) == "You are a/an closed-minded assistant. N0"


def test_from_config_index_out_of_range():
    artifact = {"instruction": [{"pos": "P0", "neg": "N0"}]}
    with pytest.raises(IndexError):
        prompt_persona.from_config({"intervention": {"trait": "x", "trait_pole": "pos",
                                                     "instruction_index": 9}}, artifact)


# ───────────────────────── residual_vector / controls（torch）─────────────────────────
def _make_vector_file(tmp_path, num_layers=4, hidden=8):
    t = torch.arange(float((num_layers + 1) * hidden)).reshape(num_layers + 1, hidden)
    p = tmp_path / "vec.pt"
    torch.save(t, p)
    return p, t


@needs_torch
def test_load_vector_row(tmp_path):
    from abcr.rig.interventions import residual_vector
    p, t = _make_vector_file(tmp_path)
    row = residual_vector.load_vector(p, 2)
    assert torch.equal(row, t[2])


@needs_torch
def test_residual_spec_mode_mapping(tmp_path):
    from abcr.rig.interventions import residual_vector
    p, _ = _make_vector_file(tmp_path)
    cfg = {"condition": "ablate",
           "intervention": {"vector_path": str(p), "layer": 1, "coefficient": 2.0}}
    spec = residual_vector.spec_from_config(cfg)
    assert spec["mode"] == "ablate" and spec["layer"] == 1 and spec["coef"] == 2.0
    cfg["condition"] = "inject"
    assert residual_vector.spec_from_config(cfg)["mode"] == "inject"


@needs_torch
def test_control_equal_norm_and_reproducible(tmp_path):
    from abcr.rig.interventions import controls
    v = torch.randn(16)
    r1 = controls.random_direction(v, 123)
    r2 = controls.random_direction(v, 123)
    assert torch.allclose(r1, r2)                       # 同 seed 复现
    assert abs(r1.norm().item() - v.norm().item()) < 1e-4   # 等范数


@needs_torch
def test_control_spec_saves_dir(tmp_path):
    from abcr.rig.interventions import controls
    p, _ = _make_vector_file(tmp_path)
    cfg = {"condition": "inject_random",
           "intervention": {"vector_path": str(p), "layer": 1, "coefficient": 2.0, "seed_ctrl": 7}}
    spec = controls.spec_from_config(cfg, save_dir=tmp_path / "act")
    assert spec["mode"] == "inject"
    assert (tmp_path / "act" / "control_dir.pt").exists()
    # 存盘方向与返回一致
    saved = torch.load(tmp_path / "act" / "control_dir.pt", weights_only=True)
    assert torch.allclose(saved, spec["vector"])


def test_vanilla_noop():
    from abcr.rig.interventions import controls
    assert controls.is_noop_for_vanilla({"condition": "vanilla", "intervention": None}) is True
    assert controls.is_noop_for_vanilla({"condition": "inject", "intervention": {}}) is False
