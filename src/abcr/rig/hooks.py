"""abcr.rig.hooks — 残差流干预 hook（注入 / 投影消融）。

架构位置：rig(B) 核心。语义与官方 activation_steer.py 的 --steering_type response
对齐：只作用于每次 forward 输出的最后位置（prefill 最后 prompt token + 逐步生成 token）。
层号约定：layer 指 hidden_states[layer]，hook 挂 model.layers[layer-1] 输出。
正确性判据见契约 §2.11（注入检 cos>0.99、模长比 0.95–1.05；消融检 proj 比 <0.02）。

最危险模块（错得安静）：① fp32 做消融投影内积再 cast（bf16 精度不足过 <0.02）；
② hook 必须 context manager 化，臂间切换泄漏是 mini 环 manifest 死罪；
③ KV cache 下 decode 步 seq_len==1，h[:, -1, :] 即当前 token。
"""
from __future__ import annotations

from typing import Literal

import torch


def _get_layers(model: torch.nn.Module) -> torch.nn.ModuleList:
    for attr_chain in (("model", "layers"), ("transformer", "h"), ("gpt_neox", "layers")):
        obj = model
        try:
            for a in attr_chain:
                obj = getattr(obj, a)
            return obj
        except AttributeError:
            continue
    raise AttributeError("无法定位 decoder 层列表（Qwen2.5 应命中 model.layers）")


# §2.11 正确性判据阈值（协议常量，运行时校验用；此前只在 docstring，从不接线）
INJECT_COS_MIN = 0.99        # 注入位移方向须与 v 对齐：|cos| > 0.99
INJECT_NORM_LO = 0.95        # 位移模长 / (|coef|·‖v‖) ∈ [0.95, 1.05]
INJECT_NORM_HI = 1.05
ABLATE_PROJ_MAX = 0.02       # 消融后残留投影 / 原投影 < 0.02


class ResidualHook:
    """context manager：with ResidualHook(model, v, layer, "inject", coef=2.0): model.generate(...)

    verify=True（默认）时把契约 §2.11 判据【接线到运行时】：注入检位移方向 cos>0.99 且模长比
    ∈[0.95,1.05]；消融检残留投影比 <0.02。判据在【首个 forward】用 fp32 复算（bf16/fp16 精度不足
    的消融会安静失败，故投影一律 fp32）。不达标记入 self.verify_error，退出上下文后由
    raise_if_unverified() 抛出——判据从"文档里的话"变成"跑不过就 FAIL"（根因④）。
    """

    def __init__(self, model: torch.nn.Module, vector: torch.Tensor, layer: int,
                 mode: Literal["inject", "ablate"], coef: float = 0.0,
                 verify: bool = True) -> None:
        if vector.dim() != 1:
            raise ValueError(f"vector 须为 1 维 [hidden]，得到 {tuple(vector.shape)}")
        self.model, self.layer, self.mode, self.coef = model, layer, mode, coef
        self.vector = vector
        self.verify = verify
        self.verify_error: str | None = None
        self._verified_once = False
        self._handle = None

    def _run_verify(self, before: torch.Tensor, after: torch.Tensor, v: torch.Tensor) -> None:
        """在最后位置的 (before, after) 上复算 §2.11 判据；不达标写 self.verify_error。fp32 复算。"""
        b = before.to(torch.float32)
        a = after.to(torch.float32)
        vf = v.to(torch.float32)
        if self.mode == "inject":
            delta = a - b                                   # 应 ≈ coef·v
            target = self.coef * vf
            tnorm = target.norm(dim=-1).clamp_min(1e-30)
            dnorm = delta.norm(dim=-1).clamp_min(1e-30)
            cos = (delta * target).sum(dim=-1) / (dnorm * tnorm)
            nrm_ratio = delta.norm(dim=-1) / tnorm
            cos_min = float(cos.abs().min().item())
            nrm = float(nrm_ratio.mean().item())
            if cos_min < INJECT_COS_MIN or not (INJECT_NORM_LO <= nrm <= INJECT_NORM_HI):
                self.verify_error = (
                    f"注入未达 §2.11：|cos|={cos_min:.4f}(min>{INJECT_COS_MIN}) "
                    f"模长比={nrm:.4f}(∈[{INJECT_NORM_LO},{INJECT_NORM_HI}])")
        else:  # ablate
            vhat = vf / vf.norm().clamp_min(1e-30)
            proj_before = (b @ vhat).abs()
            proj_after = (a @ vhat).abs()
            ratio = float((proj_after / proj_before.clamp_min(1e-30)).max().item())
            if ratio >= ABLATE_PROJ_MAX:
                self.verify_error = f"消融未达 §2.11：残留投影比={ratio:.4f}(须<{ABLATE_PROJ_MAX})"

    def _hook(self, module, args, output):
        h = output[0] if isinstance(output, tuple) else output
        v = self.vector.to(dtype=h.dtype, device=h.device)
        do_verify = self.verify and not self._verified_once
        before = h[:, -1, :].detach().clone() if do_verify else None
        if self.mode == "inject":
            h[:, -1, :] = h[:, -1, :] + self.coef * v
        else:  # ablate：把最后位置在 v 方向上的分量投影清零
            vhat = (v / v.norm()).to(h.dtype)
            proj = (h[:, -1, :].to(torch.float32) @ vhat.to(torch.float32))
            h[:, -1, :] = h[:, -1, :] - proj.unsqueeze(-1).to(h.dtype) * vhat
        if do_verify:
            self._verified_once = True
            self._run_verify(before, h[:, -1, :].detach(), v)
        if isinstance(output, tuple):
            return (h,) + tuple(output[1:])
        return h

    def raise_if_unverified(self) -> None:
        """生成完毕后调用：§2.11 判据不达标即 fail-closed 抛出（根因④，判据真接线）。"""
        if self.verify and self.verify_error:
            raise ValueError(f"干预 §2.11 校验失败（layer={self.layer} mode={self.mode}）：{self.verify_error}")

    def __enter__(self) -> "ResidualHook":
        layers = _get_layers(self.model)
        if not (1 <= self.layer <= len(layers)):
            raise ValueError(f"layer={self.layer} 超界（1..{len(layers)}）")
        self._verified_once = False
        self.verify_error = None
        self._handle = layers[self.layer - 1].register_forward_hook(self._hook)
        return self

    def __exit__(self, *exc) -> None:
        if self._handle is not None:
            self._handle.remove()
            self._handle = None
