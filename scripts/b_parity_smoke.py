#!/usr/bin/env python3
"""scripts/b_parity_smoke.py — 20 题 temp0 双引擎 parity 烟检（B2-12；云日 #2 内执行）。

dev split 前 20 题（排序后 item_id），temp0、vanilla 臂：
  引擎 A = transformers（rig runner 通路）
  引擎 B = vLLM（LLM(model=..., enforce_eager=True)，官方 venv 现成 vllm 0.8.5.post1，
           greedy SamplingParams(temperature=0, max_tokens=512)）
逐题比对：output_text 精确一致率、is_correct 一致率、分歧样例全文。
产物 reports/b_parity_smoke_20.json（b_ 前缀——AMENDMENT-31）。

**预期就是会有分歧**（vLLM 默认非确定性/数值路径不同）——这不是失败，是给 W2
分引擎设计的事实依据；如实记录即可。

⚠️ vLLM 仅云上（Mac 无）。本脚本 Mac 上只备好；实跑在云日 #2 official venv。
比对核心 compare_parity() 为纯函数，Mac 上单测覆盖。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from abcr.rig import scorer
from abcr.rig.splits import assign_split

BENCH = Path("data/benchmarks/ifeval_zh_v1.json")


def dev_first_n(n: int = 20) -> list[dict]:
    """dev split 的排序前 n 题。"""
    items = json.loads(BENCH.read_text(encoding="utf-8"))["items"]
    dev = [it for it in items if assign_split("ifeval_zh_v1", it["item_id"]) == "dev"]
    dev.sort(key=lambda it: it["item_id"])
    return dev[:n]


def compare_parity(items: list[dict], out_a: dict[str, str], out_b: dict[str, str]) -> dict:
    """纯比对：out_a/out_b = {item_id: output_text}。返回逐题 + 两一致率。"""
    records = []
    exact_match = 0
    correct_match = 0
    for it in items:
        iid = it["item_id"]
        ta, tb = out_a.get(iid, ""), out_b.get(iid, "")
        ca = scorer.check_ifeval(it, ta)
        cb = scorer.check_ifeval(it, tb)
        is_exact = ta == tb
        is_cmatch = ca == cb
        exact_match += int(is_exact)
        correct_match += int(is_cmatch)
        rec = {"item_id": iid, "check_type": it["check_type"],
               "engine_a_correct": ca, "engine_b_correct": cb,
               "output_exact_match": is_exact}
        if not is_exact:
            rec["engine_a_output"] = ta
            rec["engine_b_output"] = tb
        records.append(rec)
    n = len(items) or 1
    return {
        "n": len(items),
        "output_exact_match_rate": exact_match / n,
        "is_correct_match_rate": correct_match / n,
        "engine_a": "transformers", "engine_b": "vllm",
        "expectation": "预期会有分歧（vLLM 非确定性/数值路径不同）；分歧非失败，是 W2 分引擎设计依据",
        "records": records,
        "note": "exploratory / rig-validation —— parity 烟检，non-citable",
    }


def write_report(result: dict, out_dir: Path = Path("reports")) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "b_parity_smoke_20.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _gen_transformers(items, model_id, revision):
    from abcr.rig import models, runner  # 云上才有 torch
    model, tok, _ = models.load_model_by_id(model_id, revision)
    out = {}
    for it in items:
        out[it["item_id"]] = runner.generate_once(model, tok, it["prompt"], temperature=0.0)
    return out


def _gen_vllm(items, model_id):
    from vllm import LLM, SamplingParams  # 仅云上
    llm = LLM(model=model_id, enforce_eager=True)
    sp = SamplingParams(temperature=0, max_tokens=512)
    outs = {}
    for it in items:
        # 官方模板：apply_chat_template 由 vLLM chat 接口或手工渲染；此处交云日实装细化
        res = llm.generate([it["prompt"]], sp)
        outs[it["item_id"]] = res[0].outputs[0].text
    return outs


def main() -> int:
    ap = argparse.ArgumentParser(description="双引擎 parity 烟检（云日 #2；Mac 无 vLLM）")
    ap.add_argument("--model-id", default="Qwen/Qwen2.5-7B-Instruct")
    ap.add_argument("--revision", default=None)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--run", action="store_true", help="实跑双引擎（需云上 transformers+vllm）")
    a = ap.parse_args()
    items = dev_first_n(a.n)
    if not a.run:
        print(f"[dry] dev 前 {len(items)} 题就位；加 --run 于云日 official venv 触发双引擎实跑")
        return 0
    out_a = _gen_transformers(items, a.model_id, a.revision)
    out_b = _gen_vllm(items, a.model_id)
    result = compare_parity(items, out_a, out_b)
    path = write_report(result)
    print(f"written {path}: exact={result['output_exact_match_rate']:.2f} "
          f"correct={result['is_correct_match_rate']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
