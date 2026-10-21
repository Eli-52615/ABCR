"""abcr.judge.consistency — n=50 双 judge 一致性抽样（B2-10）。

量化 judge 替换（官方 OpenAI judge → DeepSeek）引入的评分漂移。
主 judge = DeepSeek（logprobs 加权法）；第二家族 = 本地 ollama gemma3
（异构：非 Qwen 非 Llama 非 DeepSeek；OpenAI 兼容端点 http://localhost:11434/v1）。

方法偏离（记入产物 deviation）：ollama 不支持 logprobs → 第二家族用文本解析模式
（生成 ≤8 token，正则提取 0–100 整数，提取失败 None）。双 judge 侧均落 judge_calls.jsonl
留痕（AMENDMENT-8）。统计：Spearman 相关、方向一致率、分差分布。

产物：reports/b_judge_consistency_n50.json（b_ 前缀——AMENDMENT-31）。

⚠️ 实跑 = 50×2 次 API 调用，属云日/经楠同意动作；本模块默认只备好，mock 验证通路。
被试是 Qwen，第二 judge 须异构（禁 Qwen 家族 / 禁 DASHSCOPE）。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Optional

from abcr.common import evidence_floor
from abcr.judge import stats
from abcr.judge.deepseek_client import (JudgeClient, OLLAMA_BASE_URL, default_model)

DEVIATION = ("ollama 无 logprobs → 第二家族用文本解析模式（≤8 token 正则提取 0–100，失败记 None）；"
             "主 judge 用官方 logprobs 加权法。两法不同源，分差含方法差异分量。")

# Spearman 至少需要的配对数：n=2 时秩相关恒 ±1（trivially 完美），不构成一致性证据。
_MIN_PAIRED_SPEARMAN = 3
# 已知的被试家族（Qwen）——第二 judge 必须异构于被试，禁 Qwen/DASHSCOPE。
_SUBJECT_FAMILIES = ("qwen", "dashscope")
_KNOWN_FAMILIES = ("qwen", "llama", "deepseek", "gemma", "gpt", "mistral", "yi", "glm", "phi", "claude")


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def _family(model: str) -> str:
    m = (model or "").strip().lower()
    for fam in _KNOWN_FAMILIES:
        if fam in m:
            return fam
    return m  # 认不出的模型以其自身串为家族（宁可判异构失败也不放行）


def _assert_heterogeneous(primary: JudgeClient, secondary: JudgeClient) -> None:
    """根因③④对抗：判据接线——运行时强校验双 judge 真异构，不靠文档自律、不靠自述。

    旧版任意两 client（含同一个 client 传两遍）都放行，一致率/相关会被同模型自相关虚高
    （"验船师问运动员"的同款：拿运动员自己当裁判）。此处 fail-closed 拦在入口。
    """
    pm = (primary.model or "").strip().lower()
    sm = (secondary.model or "").strip().lower()
    if not pm or not sm:
        raise ValueError("judge model 未设置，无法核验异构性（fail-closed）")
    if pm == sm:
        raise ValueError(f"双 judge 同模型 '{primary.model}'：同源自比不构成一致性证据")
    if _family(pm) == _family(sm):
        raise ValueError(f"双 judge 同家族（{_family(pm)}）：须跨模型家族才算异构")
    sec_url = (getattr(secondary, "base_url", "") or "").lower()
    if any(f in sm or f in sec_url for f in _SUBJECT_FAMILIES):
        raise ValueError("第二 judge 属被试家族（Qwen/DASHSCOPE）：judge 须异构于被试")


def run_consistency(pool: list[dict], eval_prompt: str, judge_primary: JudgeClient,
                    judge_secondary: JudgeClient, n: int = 50, seed: int = 20260714) -> dict:
    """pool: [{question_id, question, answer}]。抽 n 条双 judge 打分并统计。"""
    _assert_heterogeneous(judge_primary, judge_secondary)
    rng = random.Random(seed)
    sample = pool if len(pool) <= n else rng.sample(pool, n)
    records: list[dict] = []
    for i, r in enumerate(sample):
        iid = f"cons-{i:04d}"
        p = judge_primary.score(iid, r["question"], r["answer"], eval_prompt)
        s = judge_secondary.score(iid, r["question"], r["answer"], eval_prompt)
        records.append({"question_id": r.get("question_id", ""), "item_id": iid,
                        "primary": p, "secondary": s})

    paired = [(x["primary"], x["secondary"]) for x in records
              if x["primary"] is not None and x["secondary"] is not None]
    px = [a for a, _ in paired]
    sx = [b for _, b in paired]
    diffs = [abs(a - b) for a, b in paired]

    # 方向一致率：同 question_id 内两两响应排序，主/次 judge 符号一致占比
    by_q: dict[str, list[dict]] = {}
    for x in records:
        if x["primary"] is not None and x["secondary"] is not None:
            by_q.setdefault(x["question_id"], []).append(x)
    agree, total = 0, 0
    for rows in by_q.values():
        for a in range(len(rows)):
            for b in range(a + 1, len(rows)):
                dp = _sign(rows[a]["primary"] - rows[b]["primary"])
                ds = _sign(rows[a]["secondary"] - rows[b]["secondary"])
                total += 1
                if dp == ds:
                    agree += 1

    return {
        "n_sampled": len(sample),
        "n_paired": len(paired),
        "n_primary_none": sum(1 for x in records if x["primary"] is None),
        "n_secondary_none": sum(1 for x in records if x["secondary"] is None),
        # n=2 秩相关恒 ±1，不构成证据 → None（根因②：证据不足不得报数值）。
        "spearman": stats.spearman(px, sx) if len(paired) >= _MIN_PAIRED_SPEARMAN else None,
        "n_direction_pairs": total,
        # total==0（如全 distinct question_id）→ None，绝不 1.0；门见 None 须判 FAIL。
        "direction_agreement_rate": evidence_floor.agreement_or_none(agree, total),
        # 空 diffs（无配对）→ mean/max 为 None，绝不 0.0（0.0 会伪装成"双 judge 完全一致"）。
        "score_diff": {"mean": evidence_floor.mean_or_none(diffs),
                       "std": stats.std(diffs) if len(diffs) >= 2 else None,
                       "max": max(diffs) if diffs else None},
        "primary_model": judge_primary.model,
        "secondary_model": judge_secondary.model,
        "deviation": DEVIATION,
        "records": records,
        "note": "exploratory / rig-validation —— judge 一致性抽样，non-citable",
    }


def write_report(result: dict, out_dir: Path = Path("reports")) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 文件名按【实际】抽样数命名，不再固定 n50 谎报（根因：文档/命名与实数据脱节）。
    n = int(result.get("n_sampled", 0))
    path = out_dir / f"b_judge_consistency_n{n}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _load_pool(path: Path) -> tuple[list[dict], str]:
    """pool 文件 = {eval_prompt?, samples:[{question_id,question,answer}]} 或裸列表。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, "{question}\n{answer}\nRate 0-100:"
    return data.get("samples", data.get("items", [])), data.get("eval_prompt", "{question}\n{answer}\nRate 0-100:")


def main() -> int:
    ap = argparse.ArgumentParser(description="n=50 双 judge 一致性抽样（默认备好，实跑需 --run）")
    ap.add_argument("--pool", required=True, help="表达检样本池 JSON")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--run", action="store_true", help="真实调用双 judge（50×2 次；默认不实跑）")
    a = ap.parse_args()
    pool, eval_prompt = _load_pool(Path(a.pool))
    if not a.run:
        print(f"[dry] pool={len(pool)} 条，n={a.n}；加 --run 触发真实双 judge 调用"
              f"（{a.n}×2 次，属云日/经楠同意动作）")
        return 0
    log = Path("data/runs/consistency/logs/judge_calls.jsonl")
    primary = JudgeClient(model=default_model(), mode="logprobs", log_path=log)
    secondary = JudgeClient(model="gemma3", base_url=OLLAMA_BASE_URL, api_key_env="OLLAMA_API_KEY",
                            mode="text_parse", log_path=log)
    result = run_consistency(pool, eval_prompt, primary, secondary, n=a.n)
    path = write_report(result)
    print(f"written {path}: spearman={result['spearman']} "
          f"agreement={result['direction_agreement_rate']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
