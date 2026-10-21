"""abcr.rig.interventions.controls — condition=inject_random/ablate_random 的对照臂。

等范数随机方向（否证标准第 3 条"随机等范数方向产生同等增益"的对照臂）：
  torch.manual_seed(seed_ctrl); r = torch.randn_like(v); r = r / r.norm() * v.norm()
——与 trait 向量同层同系数同范数，唯方向随机。seed_ctrl 记入 config 与 manifest。
随机方向生成后存盘 data/runs/<run_id>/activations/control_dir.pt 供复现。
torch 惰性导入。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from abcr.rig.interventions.residual_vector import load_vector, resolve_coef


def random_direction(v, seed_ctrl: int):
    """等范数随机方向：同 seed 复现同方向，‖r‖==‖v‖。"""
    import torch
    torch.manual_seed(seed_ctrl)
    r = torch.randn_like(v)
    return r / r.norm() * v.norm()


def spec_from_config(config: dict, save_dir: Optional[Path] = None) -> dict[str, Any]:
    """config.condition ∈ {inject_random, ablate_random}。基向量取 intervention.vector_path 的第 layer 行，
    生成等范数随机方向（seed_ctrl 取 intervention.seed_ctrl，缺省 random_seed 或 0），可存盘复现。
    返回 {vector, layer, mode, coef}。"""
    cond = config["condition"]
    if cond not in ("inject_random", "ablate_random"):
        raise ValueError(f"controls 仅处理 inject_random/ablate_random，得到 {cond}")
    iv = config["intervention"]
    layer = iv["layer"]
    base = load_vector(iv["vector_path"], layer, expected_sha256=iv.get("vector_sha256"))
    seed_ctrl = int(iv.get("seed_ctrl", config.get("decoding", {}).get("seeds", [0])[0]))
    r = random_direction(base, seed_ctrl)
    if save_dir is not None:
        import torch
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        torch.save(r, save_dir / "control_dir.pt")
    mode = "inject" if cond == "inject_random" else "ablate"
    coef = resolve_coef(iv, cond)   # 注入类对照臂系数必填非零（根因②）
    return {"vector": r, "layer": layer, "mode": mode, "coef": coef}


def is_noop_for_vanilla(config: dict) -> bool:
    """vanilla 臂三件干预全 no-op（intervention 为 null）。"""
    return config.get("condition") == "vanilla" and not config.get("intervention")
