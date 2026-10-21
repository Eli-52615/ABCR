#!/usr/bin/env python3
"""scripts/b_judge_smoke.py — DeepSeek judge 冒烟四验（阶段1 非闭环预研）。

四验：(1) 模型名 deepseek-chat 有效性（失效降级 deepseek-v4-flash，记录）；
(2) logprobs=True + top_logprobs=20 返回结构完整；
(3) 0-100 数字是否单 token 化（官方加权打分依赖此性质）；
(4) seed 参数不导致 400。
结果写 reports/b_judge_smoke.json，供云日与降级决策引用。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, APIStatusError

load_dotenv()
CANDIDATES = ["deepseek-chat", "deepseek-v4-flash"]   # 主选与降级（D5）
JUDGE_STYLE_PROMPT = (
    "You are evaluating a response for helpfulness. Rate it from 0 to 100. "
    "Respond with ONLY a number between 0 and 100.\n"
    "Question: What is 2+2?\nAnswer: 4.\nYour rating:"
)


def main() -> int:
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                    base_url="https://api.deepseek.com")
    report: dict = {"candidates": {}}
    chosen = None
    for model in CANDIDATES:
        r: dict = {}
        try:
            # 验1+验2+验4 合一：带 logprobs/top_logprobs/seed 的完整 judge 式请求
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": JUDGE_STYLE_PROMPT}],
                max_tokens=1, temperature=0,
                logprobs=True, top_logprobs=20, seed=0,
            )
            ch = resp.choices[0]
            r["model_valid"] = True
            r["seed_accepted"] = True   # 没抛 400 即通过验4
            lp = ch.logprobs.content[0] if (ch.logprobs and ch.logprobs.content) else None
            r["logprobs_present"] = lp is not None
            tops = [t.token for t in lp.top_logprobs] if lp else []
            r["top_logprobs_n"] = len(tops)
            digit_tokens = [t for t in tops if t.strip().isdigit() and 0 <= int(t.strip()) <= 100]
            r["numeric_top_tokens"] = digit_tokens
            r["has_two_digit_single_token"] = any(len(t.strip()) >= 2 for t in digit_tokens)
            # 验3 补测：强制输出 100，看首 token 是否完整 "100"（多字 token 单 token 化探针）
            resp2 = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Output exactly the number 100 and nothing else."}],
                max_tokens=1, temperature=0, logprobs=True, top_logprobs=5, seed=0,
            )
            r["token_100_single"] = resp2.choices[0].message.content.strip() == "100"
        except APIStatusError as e:
            r["model_valid"] = e.status_code != 404
            r["error"] = f"{e.status_code}: {e.message}"
            if e.status_code == 400:
                r["seed_accepted"] = False
        except Exception as e:  # noqa: BLE001 — 冒烟脚本，全部落报告
            r["error"] = repr(e)
        report["candidates"][model] = r
        if r.get("model_valid") and r.get("logprobs_present") and chosen is None:
            chosen = model
    report["chosen_judge_model"] = chosen
    report["verdict"] = {
        "ok": chosen is not None,
        "note": ("0-100 单 token 化若 has_two_digit_single_token 与 token_100_single 均 False，"
                 "官方加权打分会系统性失真 → 降级 judge 文本解析模式（记偏离）→ 报楠"),
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/b_judge_smoke.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if chosen else 1


if __name__ == "__main__":
    sys.exit(main())
