"""tests/rig/test_models —— 模板哈希 + 三样例逐字节检 + revision 缺失拒跑（B2-1）。

torch-free：用 FakeTokenizer 覆盖 apply_chat_template；load_model 的 revision 缺失检查
在 torch 导入前，故可无 torch 验证。真实模型加载 + 模板冻结走 b_freeze_template_samples.py（云/装 torch）。
"""
from __future__ import annotations

import json

import pytest

from abcr.rig import models


class FakeTokenizer:
    """确定性 apply_chat_template（im_start 结构近似 Qwen2.5）。"""
    chat_template = "{% for m in messages %}<|im_start|>{{m.role}}\n{{m.content}}<|im_end|>\n{% endfor %}"

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        s = ""
        for m in messages:
            s += f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n"
        if add_generation_prompt:
            s += "<|im_start|>assistant\n"
        return s


def test_chat_template_hash_deterministic():
    h1 = models.chat_template_hash("abc")
    h2 = models.chat_template_hash("abc")
    assert h1 == h2 and len(h1) == 64
    assert models.chat_template_hash("abc") != models.chat_template_hash("abd")


def test_render_samples_shape():
    rendered = models.render_samples(FakeTokenizer())
    assert [s["id"] for s in rendered] == ["S1", "S2", "S3"]
    assert all(s["rendered"].endswith("<|im_start|>assistant\n") for s in rendered)


def test_verify_template_samples_match(tmp_path):
    tok = FakeTokenizer()
    rendered = models.render_samples(tok)
    path = tmp_path / "samples.json"
    path.write_text(json.dumps({"samples": rendered}, ensure_ascii=False), encoding="utf-8")
    models.verify_template_samples(tok, samples_path=path)   # 不抛即通过


def test_verify_template_samples_drift_raises(tmp_path):
    tok = FakeTokenizer()
    rendered = models.render_samples(tok)
    rendered[0]["rendered"] += "DRIFT"     # 制造漂移
    path = tmp_path / "samples.json"
    path.write_text(json.dumps({"samples": rendered}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="逐字节不符"):
        models.verify_template_samples(tok, samples_path=path)


def test_verify_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        models.verify_template_samples(FakeTokenizer(), samples_path=tmp_path / "nope.json")


def test_load_model_rejects_unpinned_revision():
    cfg = {"model": {"model_id": "Qwen/Qwen2.5-7B-Instruct", "revision": "PIN-AT-CLOUD-PROVISION"}}
    with pytest.raises(ValueError, match="revision 未钉死"):
        models.load_model(cfg)
    cfg2 = {"model": {"model_id": "Qwen/Qwen2.5-7B-Instruct", "revision": None}}
    with pytest.raises(ValueError):
        models.load_model(cfg2)
