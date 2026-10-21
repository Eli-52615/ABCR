"""abcr.rig.scorer — 确定性判分器 deterministic_v1（阶段2 完整版）。

架构位置：rig(B) 的评分 pass。与 A 的 rescore_v1 有意双实现（对冲同源 bug），
两者都必须过黄金十题（契约 §2.10）。评分独立于生成：只读 steps.jsonl。

stdlib 自包含（AMENDMENT-20）：本模块只用 stdlib（json/re/argparse/pathlib/datetime），
不 import torch/numpy/abcr 其他模块——C 的复现包会逐字节复制它做包外独立复算，
import 不了即拒绝出包。故 manipulation 词表与句切分符集在本模块内**内联**
（值与 abcr.common.constants 逐项相等，由 tests/rig/test_scorer_constants.py 锁定）。

判定语义冻结（AMENDMENT-21）：
  parse_ok          = int(bool(output_text.strip()))
  output_len_chars  = len(output_text)          # 原文全文，不 strip
  output_len_tokens = step 记录的 output_tokens
  is_correct        = golden10 → score_golden；ifeval_zh_v1 → 8 类可验证指令判分
  hedging_rate / self_check_marker_rate = 句级命中率（含 ≥1 词表词的句子数 / 总句数）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCORER_ID = "deterministic_v1"
SCORER_VERSION = "1.0"   # 阶段2（B1-6 为 "0.1"）

# ── manipulation-check 词表与句切分符集（AMENDMENT-6/21；内联镜像 constants.py）──
HEDGING_WORDS: tuple[str, ...] = (
    "可能", "也许", "或许", "大概", "不确定", "似乎", "恐怕",
    "maybe", "perhaps", "possibly", "might", "not sure")
SELF_CHECK_MARKERS: tuple[str, ...] = (
    "让我检查", "再确认", "验证一下", "复核", "等等，",
    "double-check", "let me verify", "wait,")
SENTENCE_SEPARATORS: str = "。！？!?.；"   # 换行另行处理（见 _split_sentences）


# ────────────────────────── golden10 判分 ──────────────────────────
def _strip_fence(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL)
    return m.group(1) if m else t


def score_golden(item_id: str, output_text: str) -> bool:
    t = output_text.strip()
    if item_id == "g01":
        lines = t.split("\n")
        return len(lines) == 3 and all(l.startswith("- ") for l in lines)
    if item_id == "g02":
        return t == "391"
    if item_id == "g03":
        return t == "hello,hello,hello,hello,hello"
    if item_id == "g04":
        return output_text.count("可复现") >= 2
    if item_id == "g05":
        try:
            return json.loads(_strip_fence(output_text)) == {"a": 1, "b": 2}
        except (ValueError, TypeError):
            return False
    if item_id == "g06":
        return t == "ABCDE"
    if item_id == "g07":
        return t == "3"
    if item_id == "g08":
        return t == "rcba"
    if item_id == "g09":
        return len(t) > 0 and t[0] == "A"
    if item_id == "g10":
        return t.startswith("数据") and t.endswith("。") and len(t) <= 20
    raise KeyError(f"unknown golden item {item_id}")


# ────────────────────── ifeval_zh_v1 八类可验证指令判分 ──────────────────────
def check_exact_output(output_text: str, args: dict) -> bool:
    return output_text.strip() == args["expected"]


def check_line_count_prefix(output_text: str, args: dict) -> bool:
    lines = output_text.strip().split("\n")
    return len(lines) == args["n"] and all(l.startswith(args["prefix"]) for l in lines)


def check_keyword_min_count(output_text: str, args: dict) -> bool:
    return output_text.count(args["keyword"]) >= args["n"]


def check_forbidden_word(output_text: str, args: dict) -> bool:
    return args["word"] not in output_text and len(output_text.strip()) >= args.get("min_len", 10)


def check_json_object(output_text: str, args: dict) -> bool:
    try:
        return json.loads(_strip_fence(output_text)) == args["expected"]
    except (ValueError, TypeError):
        return False


def check_prefix_suffix_len(output_text: str, args: dict) -> bool:
    t = output_text.strip()
    return t.startswith(args["prefix"]) and t.endswith(args["suffix"]) and len(t) <= args["max_len"]


def check_option_letter(output_text: str, args: dict) -> bool:
    t = output_text.strip()
    return len(t) > 0 and t[0] == args["expected"]


def check_separator_items(output_text: str, args: dict) -> bool:
    parts = output_text.strip().split(args["sep"])
    return len(parts) == args["n"] and all(p.strip() for p in parts)


CHECKERS = {
    "exact_output": check_exact_output,
    "line_count_prefix": check_line_count_prefix,
    "keyword_min_count": check_keyword_min_count,
    "forbidden_word": check_forbidden_word,
    "json_object": check_json_object,
    "prefix_suffix_len": check_prefix_suffix_len,
    "option_letter": check_option_letter,
    "separator_items": check_separator_items,
}


def check_ifeval(item: dict, output_text: str) -> bool:
    ct = item["check_type"]
    if ct not in CHECKERS:
        raise KeyError(f"unknown ifeval check_type {ct}")
    return CHECKERS[ct](output_text, item.get("check_args", {}))


# ────────────────────── manipulation-check 指标 ──────────────────────
def _split_sentences(text: str) -> list[str]:
    """按 SENTENCE_SEPARATORS + 换行切分，去空段（句级命中率的分母）。"""
    pattern = "[" + re.escape(SENTENCE_SEPARATORS) + r"\n]"
    return [s for s in (seg.strip() for seg in re.split(pattern, text)) if s]


def _hit_rate(text: str, vocab: tuple[str, ...]) -> float:
    sents = _split_sentences(text)
    if not sents:
        return 0.0
    hits = sum(1 for s in sents if any(w in s for w in vocab))
    return hits / len(sents)


def manipulation_metrics(output_text: str) -> dict[str, float]:
    # round 到 6 位:与 audit/rescore.py 的 rate 指标口径一致(否则真模型输出命中 2/11 等无限小数时,
    # 存储的 deterministic_v1(全精度)与复算值(舍6位)逐字节不符 → C agreement<1.0)。规范形,防浮点噪声。
    return {
        "hedging_rate": round(_hit_rate(output_text, HEDGING_WORDS), 6),
        "self_check_marker_rate": round(_hit_rate(output_text, SELF_CHECK_MARKERS), 6),
    }


# ────────────────────────── 综合评分 ──────────────────────────
def score_item(family: str, item: dict, output_text: str, output_tokens: int = 0) -> dict:
    """对单 item 产 metric_name→value（确定性指标；judge 指标 trait/coherence 另 pass 产）。"""
    if family == "golden10":
        is_correct = score_golden(item["id"], output_text)
    elif family == "ifeval_zh_v1":
        is_correct = check_ifeval(item, output_text)
    else:
        raise KeyError(f"unknown benchmark family {family}")
    metrics: dict = {
        "is_correct": int(bool(is_correct)),
        "parse_ok": int(bool(output_text.strip())),
        "output_len_chars": len(output_text),
        "output_len_tokens": int(output_tokens),
    }
    metrics.update(manipulation_metrics(output_text))
    return metrics


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def score_steps(steps: list[dict], items_by_id: dict[str, dict] | None = None,
                *, arm_id: str | None = None) -> list[dict]:
    """对一批 step 记录逐条产指标行（契约 §2.5 scores schema）。

    family 取 step 记录 benchmark 字段（缺省 golden10，兼容 B1-6 调用）。
    ifeval_zh_v1 需 items_by_id 提供 item 的 check_type/check_args。
    """
    items_by_id = items_by_id or {}
    rows: list[dict] = []
    for s in steps:
        item_id = s["item_id"]
        output_text = s.get("output_text", "")
        family = s.get("benchmark", "golden10")
        item = items_by_id.get(item_id, {"id": item_id})
        metrics = score_item(family, item, output_text, int(s.get("output_tokens", 0)))
        base = {
            "schema_version": "1.0",
            "run_id": s["run_id"],
            "item_id": item_id,
            "trajectory_id": s.get("trajectory_id", ""),
            "step_id": s.get("step_id", 0),
            "condition": s.get("condition", ""),
            "config_hash": s.get("config_hash", ""),
            "arm_id": arm_id,
            "random_seed": s.get("random_seed", 0),
            "scorer_id": SCORER_ID,
            "scorer_version": SCORER_VERSION,
            "scored_at": _now(),
        }
        for name, value in metrics.items():
            rows.append({**base, "metric_name": name, "metric_value": value})
    return rows


def _load_jsonl(p: Path) -> list[dict]:
    # 缺失即空:steps.jsonl 可能被伪报完成演练(ABCR_FAKETASK_SKIP_LEDGER_WRITES)整个跳过——
    # scorer 优雅返回空、run 照常收尾"完成但无 step",由 A 审计(item1 完整性)拦截并 QUARANTINE
    # (fail-closed 兜底在审计层,坑16 真跑暴露:原实现在此 FileNotFoundError 崩溃)。
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _load_benchmark_items(family: str) -> dict[str, dict]:
    """按 family 定位 benchmark JSON，返回 {item_id: item}。找不到返回空（golden 用 id 判分不需要）。"""
    candidates = {
        "golden10": Path("data/golden/golden10.json"),
        "ifeval_zh_v1": Path("data/benchmarks/ifeval_zh_v1.json"),
    }
    p = candidates.get(family)
    if not p or not p.exists():
        return {}
    items = json.loads(p.read_text(encoding="utf-8"))["items"]
    return {it.get("item_id", it.get("id")): it for it in items}


def score_run(run_dir: Path, *, selected_items: dict[str, dict] | None = None) -> list[dict]:
    """读 run 目录 steps.jsonl → 产 scores 行并追加写 scores.jsonl（幂等），返回新增行。

    幂等（AMENDMENT，B2-4）：同 scorer_id+version 已评过的 (item_id, random_seed, metric_name) 跳过。
    """
    run_dir = Path(run_dir)
    steps = _load_jsonl(run_dir / "steps.jsonl")
    if selected_items is not None:
        # Evidence dispatch supplies the exact verified DevBundle rows.  Never
        # reopen the full benchmark merely to score a selected dev item.
        items_by_id = dict(selected_items)
        observed = {s["item_id"] for s in steps}
        if not observed.issubset(items_by_id):
            raise ValueError("steps item 不在 dispatch 提供的 DevBundle selected_items 中")
    else:
        families = {s.get("benchmark", "golden10") for s in steps}
        items_by_id: dict[str, dict] = {}
        for fam in families:
            items_by_id.update(_load_benchmark_items(fam))
    arm_id: str | None = None
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        config = manifest.get("config")
        if isinstance(config, dict) and "dev_bundle_ref" in config:
            arm_id = config.get("arm_id")
            expected_hash = manifest.get("config_hash")
            if (not isinstance(arm_id, str) or not arm_id
                    or not isinstance(expected_hash, str) or not expected_hash
                    or any(step.get("config_hash") != expected_hash for step in steps)):
                raise ValueError("evidence scorer 缺不可歧义 arm/config binding")
    rows = score_steps(steps, items_by_id, arm_id=arm_id)

    out = run_dir / "scores.jsonl"
    seen: set[tuple] = set()
    if out.exists():
        for r in _load_jsonl(out):
            if r.get("scorer_id") == SCORER_ID and r.get("scorer_version") == SCORER_VERSION:
                seen.add((r["item_id"], r["random_seed"], r["metric_name"]))
    new_rows = [r for r in rows
                if (r["item_id"], r["random_seed"], r["metric_name"]) not in seen]
    with open(out, "a", encoding="utf-8") as f:
        for r in new_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return new_rows


def main() -> int:
    ap = argparse.ArgumentParser(description="deterministic_v1 评分器（读 steps.jsonl 追加 scores.jsonl，幂等）")
    ap.add_argument("--run", required=True, help="run_id（data/runs/<run_id>）或 run 目录路径")
    a = ap.parse_args()
    run_dir = Path(a.run)
    if not run_dir.exists():
        run_dir = Path("data/runs") / a.run
    new_rows = score_run(run_dir)
    print(f"scored {run_dir}: {len(new_rows)} new metric rows "
          f"({SCORER_ID} v{SCORER_VERSION})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
