#!/usr/bin/env python3
"""scripts/b_freeze_template_samples.py — 一次性冻结三条 chat_template 样例（B2-1）。

首次加载钉死 revision 的 tokenizer → 渲染三样例 → 与文档预期比对并打印 diff →
人（你）目检确认语义正确（im_start 结构、system 注入、generation prompt）→ 把**实际渲染值**
写入 data/benchmarks/chat_template_samples.json（含 model_id/revision/chat_template_hash/
三样例输入与渲染串）→ commit。此后 models.py 每次加载做逐字节比对。

若实际与文档预期不符：以实际为准，PROGRESS.md 记一行，不算异常（预期值本就标注未实测）。

用法：
  PYTHONPATH=src python scripts/b_freeze_template_samples.py --model Qwen/Qwen2.5-3B-Instruct [--revision <hash>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from abcr.rig import models

# 文档预写期望（Qwen2.5-Instruct 已知模板格式，未实测；仅供目检参考）
DOC_EXPECT = {
    "S1": ("<|im_start|>system\n你是 ABCR 实验助手。<|im_end|>\n"
           "<|im_start|>user\n请输出OK。<|im_end|>\n<|im_start|>assistant\n"),
    "S2": ("<|im_start|>system\nYou are Qwen, created by Alibaba Cloud. You are a helpful assistant."
           "<|im_end|>\n<|im_start|>user\nhello<|im_end|>\n<|im_start|>assistant\n"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="model_id 或本地路径")
    ap.add_argument("--revision", default=None)
    ap.add_argument("--out", default=str(models.SAMPLES_PATH))
    a = ap.parse_args()

    import transformers
    tok_kwargs = {}
    if a.revision and not Path(a.model).exists():
        tok_kwargs["revision"] = a.revision
    tok = transformers.AutoTokenizer.from_pretrained(a.model, **tok_kwargs)

    rendered = models.render_samples(tok)
    ct_hash = models.chat_template_hash(tok.chat_template) if tok.chat_template else ""

    print(f"chat_template_hash = {ct_hash}")
    for s in rendered:
        print(f"\n==== {s['id']} 实际渲染 ====")
        print(repr(s["rendered"]))
        if s["id"] in DOC_EXPECT:
            match = s["rendered"] == DOC_EXPECT[s["id"]]
            print(f"[{'MATCH' if match else 'DIFF'}] 对文档预期"
                  f"{'（以实际为准，正常）' if not match else ''}")

    doc = {"model_id": a.model, "revision": a.revision, "chat_template_hash": ct_hash,
           "samples": rendered}
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwritten {out}（目检语义正确后 commit）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
