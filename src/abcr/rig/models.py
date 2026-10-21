"""abcr.rig.models — 模型加载 + revision 钉死 + chat_template 哈希 + 三样例逐字节检（B2-1）。

架构位置：rig(B) 核心。load_model(config) → (model, tokenizer, ModelInfo)。
模板静默漂移是 harness 最常见杀手：每次加载对三条钉死样例做逐字节比对，不符拒跑。

torch/transformers 惰性导入（模块可在无 torch 环境 import，供纯逻辑/脚本引用与单测）。
Mac 结果一律 non-citable（MPS 数值怪癖）；正式证据要云 CUDA bf16。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# 三条钉死样例（B 包定义权；期望渲染值按 Qwen2.5 模板预写，未实测——定稿以实际渲染为准）
TEMPLATE_SAMPLES = [
    {"id": "S1", "messages": [
        {"role": "system", "content": "你是 ABCR 实验助手。"},
        {"role": "user", "content": "请输出OK。"}]},
    {"id": "S2", "messages": [
        {"role": "user", "content": "hello"}]},
    {"id": "S3", "messages": [
        {"role": "system", "content": "You are a test assistant."},
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "1"},
        {"role": "user", "content": "two"}]},
]

SAMPLES_PATH = Path("data/benchmarks/chat_template_samples.json")


@dataclass
class ModelInfo:
    model_id: str
    revision: str
    chat_template_hash: str
    dtype: str
    device: str
    engine: str = "transformers"
    engine_version: str = ""
    torch_version: Optional[str] = None


def chat_template_hash(template: str) -> str:
    """sha256(tokenizer.chat_template.encode())——写入 manifest 与 step 记录。"""
    return hashlib.sha256(template.encode()).hexdigest()


def render_samples(tokenizer) -> list[dict]:
    """用 tokenizer 渲染三样例（add_generation_prompt=True，tokenize=False）。"""
    out = []
    for s in TEMPLATE_SAMPLES:
        rendered = tokenizer.apply_chat_template(
            s["messages"], tokenize=False, add_generation_prompt=True)
        out.append({"id": s["id"], "messages": s["messages"], "rendered": rendered})
    return out


def verify_template_samples(tokenizer, samples_path: Path = SAMPLES_PATH) -> None:
    """逐字节比对三样例渲染值与冻结值；不符拒跑（模板漂移）。缺冻结文件亦拒跑。"""
    samples_path = Path(samples_path)
    if not samples_path.exists():
        raise FileNotFoundError(
            f"缺冻结样例 {samples_path}（先跑 scripts/b_freeze_template_samples.py）")
    frozen = {s["id"]: s["rendered"] for s in json.loads(samples_path.read_text(encoding="utf-8"))["samples"]}
    for s in render_samples(tokenizer):
        exp = frozen.get(s["id"])
        if exp is None:
            raise ValueError(f"冻结样例缺 {s['id']}")
        if s["rendered"] != exp:
            raise ValueError(
                f"chat_template 样例 {s['id']} 逐字节不符（模板漂移）：\n期望={exp!r}\n实得={s['rendered']!r}")


def _select_dtype_device(device: Optional[str], dtype: Optional[str]):
    """Mac：MPS→float16、CPU→float32；云 CUDA→bfloat16。torch 惰性导入。"""
    import torch
    if device is None:
        if torch.cuda.is_available():
            device = "cuda:0"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
    if dtype is None:
        dtype = "bfloat16" if device.startswith("cuda") else (
            "float16" if device == "mps" else "float32")
    torch_dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16,
                   "float32": torch.float32}[dtype]
    return device, dtype, torch_dtype


def _local_model_fingerprint(model_dir: str | Path) -> Optional[str]:
    """本地模型的内容指纹（信任根，根因①）：哈希元数据文件全文 + 权重文件名与字节数
    （不读权重全文，避免 GB 级 IO）。任一元数据文件都不存在 → None（无可指纹化目标）。
    记入 model_revision 取代此前无意义的 'local' 字面值——影子换权重/换配置会改变指纹。"""
    p = Path(model_dir)
    h = hashlib.sha256()
    found = False
    for name in ("config.json", "generation_config.json", "tokenizer_config.json",
                 "tokenizer.json", "model.safetensors.index.json", "pytorch_model.bin.index.json"):
        fp = p / name
        if fp.exists():
            found = True
            h.update(name.encode())
            h.update(fp.read_bytes())
    for pat in ("*.safetensors", "*.bin"):
        for wf in sorted(p.glob(pat)):
            h.update(wf.name.encode())
            h.update(str(wf.stat().st_size).encode())
    if not found:
        return None
    return "local-sha256:" + h.hexdigest()[:16]


def load_model_by_id(model_id: str, revision: Optional[str], device: Optional[str] = None,
                     dtype: Optional[str] = None, verify_samples: bool = True):
    """加载 tokenizer+model；远端 revision 必填（缺失拒跑）。本地模型不走 HF revision，
    改用内容指纹作信任根（根因①：不再把无意义的 'local' 当身份）。返回 (model, tokenizer, ModelInfo)。"""
    import torch  # noqa: F401
    import transformers
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # 双保险（.env 已设）

    is_local = Path(model_id).exists()
    if not is_local and not revision:
        raise ValueError(f"revision 必填（{model_id}）——首次下载后钉入 configs/models/；缺失拒跑")

    recorded_revision = revision
    if is_local and not revision:
        recorded_revision = _local_model_fingerprint(model_id)
        if recorded_revision is None:
            raise ValueError(
                f"本地模型 {model_id} 无可指纹化的元数据（config.json 等缺失）——无信任根，拒跑")

    device, dtype, torch_dtype = _select_dtype_device(device, dtype)
    tok_kwargs: dict[str, Any] = {}
    mdl_kwargs: dict[str, Any] = {"torch_dtype": torch_dtype}
    if revision and not is_local:
        tok_kwargs["revision"] = revision
        mdl_kwargs["revision"] = revision

    tokenizer = transformers.AutoTokenizer.from_pretrained(model_id, **tok_kwargs)
    if verify_samples:
        verify_template_samples(tokenizer)
    model = transformers.AutoModelForCausalLM.from_pretrained(model_id, **mdl_kwargs)
    if device != "cpu":
        model = model.to(device)
    model.eval()

    ct_hash = chat_template_hash(tokenizer.chat_template) if tokenizer.chat_template else ""
    info = ModelInfo(model_id=model_id, revision=recorded_revision or "local",
                     chat_template_hash=ct_hash, dtype=dtype, device=device,
                     engine="transformers", engine_version=transformers.__version__,
                     torch_version=torch.__version__)
    return model, tokenizer, info


def _config_lookup(name: str) -> dict:
    p = Path("configs/models") / f"{name}.json"
    if not p.exists():
        raise FileNotFoundError(f"缺 {p}（首次下载后钉 revision 入此文件）")
    return json.loads(p.read_text(encoding="utf-8"))


def load_model(config: dict, verify_samples: bool = True):
    """从 run config 的 model 段加载。config 例：
    {"model": {"model_id": "...", "revision": "...", "dtype": "bfloat16", "device": "cuda:0"}}。"""
    m = config["model"] if "model" in config else config
    model_id = m["model_id"]
    revision = m.get("revision")
    if revision in (None, "", "PIN-AT-CLOUD-PROVISION") and not Path(model_id).exists():
        raise ValueError(f"revision 未钉死（{model_id}）：{revision!r}——缺失拒跑（B2-1）")
    return load_model_by_id(model_id, revision, device=m.get("device"),
                            dtype=m.get("dtype"), verify_samples=verify_samples)
