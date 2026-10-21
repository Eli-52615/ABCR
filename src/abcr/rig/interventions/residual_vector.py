"""abcr.rig.interventions.residual_vector — condition=inject/ablate 的 hook 规格。

加载 vector_path 的 .pt（形状 [num_layers+1, hidden]，取第 layer 行），返回 ResidualHook
规格 (vector, layer, mode, coef)。加载用 torch.load(weights_only=True)（安全默认；官方 .pt 是纯 tensor）。
torch 惰性导入（模块可在无 torch 环境 import）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional


def _file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_vector(vector_path: str | Path, layer: int, *, expected_sha256: Optional[str] = None):
    """取 [num_layers+1, hidden] 的第 layer 行；weights_only=True 安全加载。

    信任根（根因①）：若 config 声明了 vector_sha256，先逐字节比对文件摘要——不符即拒跑，
    影子/被替换向量在入口就被掐断，绝不"读到什么算什么"。
    数值健全（根因①）：拒收含 NaN/±Inf 的向量（静默注入 NaN 会安静毁坏整批而无 FAIL）。
    """
    p = Path(vector_path)
    if not p.exists():
        raise FileNotFoundError(f"向量文件不存在：{p}")
    if expected_sha256:
        actual = _file_sha256(p)
        if actual != expected_sha256:
            raise ValueError(
                f"向量 sha256 不符（信任根失配）：声明={expected_sha256} 实得={actual}（{p}）")
    import torch
    tensor = torch.load(str(p), weights_only=True)
    if tensor.dim() != 2:
        raise ValueError(f"向量文件须为 2 维 [num_layers+1, hidden]，得到 {tuple(tensor.shape)}")
    if not (0 <= layer < tensor.shape[0]):
        raise IndexError(f"layer={layer} 超界（0..{tensor.shape[0] - 1}）")
    if not bool(torch.isfinite(tensor).all()):
        raise ValueError(f"向量含 NaN/±Inf，拒收（{p}）")
    return tensor[layer].clone()


def resolve_coef(iv: dict, cond: str) -> float:
    """注入类臂（inject / inject_random）的系数必须【显式声明且非零】——缺失或 0 即"无干预
    却被记成干预臂"（根因②：空/缺失被当成功）。fail-closed 抛 ValueError，绝不默认 0.0 恒等注入。
    消融类臂（ablate / ablate_random）的系数不参与投影消融运算，允许缺省（记 0.0，不承重）。"""
    raw = iv.get("coefficient")
    is_inject = cond in ("inject", "inject_random")
    if is_inject:
        if raw is None:
            raise ValueError(
                f"{cond} 臂缺 coefficient：注入系数必填，不得默认 0.0 恒等注入（根因② fail-closed）")
        coef = float(raw)
        if coef == 0.0:
            raise ValueError(f"{cond} 臂 coefficient=0 等于无干预，却被声明为注入臂（fail-closed）")
        return coef
    return float(raw) if raw is not None else 0.0


def spec_from_config(config: dict) -> dict[str, Any]:
    """config.condition ∈ {inject, ablate}，config.intervention 提供 vector_path/layer/coefficient。
    返回 ResidualHook 构造参数字典 {vector, layer, mode, coef}。"""
    cond = config["condition"]
    if cond not in ("inject", "ablate"):
        raise ValueError(f"residual_vector 仅处理 inject/ablate，得到 {cond}")
    iv = config["intervention"]
    layer = iv["layer"]
    vector = load_vector(iv["vector_path"], layer, expected_sha256=iv.get("vector_sha256"))
    mode = "inject" if cond == "inject" else "ablate"
    coef = resolve_coef(iv, cond)
    return {"vector": vector, "layer": layer, "mode": mode, "coef": coef}
