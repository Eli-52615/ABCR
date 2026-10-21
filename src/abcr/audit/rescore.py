"""abcr.audit.rescore —— 独立复评器 rescore_v1（审计六项之"重评分比对"的数据源）。

架构位置：包A·验船师侧。与 B 的 deterministic_v1 有意双实现（对冲同源 bug）。
输入：data/runs/<run_id>/steps.jsonl 的原始 output_text（铁律：一切重算不依赖重新生成）。
输出：同目录 scores.jsonl 追加行，scorer_id="rescore_v1"。

铁律（坑12）：本模块 import 列表不得出现 abcr.rig——禁止复用 B 的判分代码。
golden10 判分规则以 §3.9 表和 data/golden/golden10.json 为共同真值，独立实现。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from abcr.common import constants

RESCORER_ID = "rescore_v1"
RESCORER_VERSION = "1.0.0"


def _strip_fence(t: str) -> str:
    """剥 ```json 围栏（g05 用）。"""
    s = t.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        s = s.rstrip()
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def _g05(t: str) -> int:
    try:
        return int(json.loads(_strip_fence(t)) == {"a": 1, "b": 2})
    except (ValueError, TypeError):
        return 0


GOLDEN_RULES: dict[str, Callable[[str], int]] = {
    "g01": lambda t: int((lambda ls: len(ls) == 3 and all(l.startswith("- ") for l in ls))
                         (t.strip().split("\n"))),
    "g02": lambda t: int(t.strip() == "391"),
    "g03": lambda t: int(t.strip() == "hello,hello,hello,hello,hello"),
    "g04": lambda t: int(t.count("可复现") >= 2),
    "g05": _g05,
    "g06": lambda t: int(t.strip() == "ABCDE"),
    "g07": lambda t: int(t.strip() == "3"),
    "g08": lambda t: int(t.strip() == "rcba"),
    "g09": lambda t: int(t.strip()[:1] == "A"),
    "g10": lambda t: int((lambda s: s.startswith("数据") and s.endswith("。") and len(s) <= 20)
                         (t.strip())),
}

# manipulation-check 词表与句切分符集 —— 已裁决（AMENDMENT-6/21）：从 constants 取用。
HEDGING_WORDS: tuple[str, ...] = constants.HEDGING_WORDS
SELF_CHECK_MARKERS: tuple[str, ...] = constants.SELF_CHECK_MARKERS
_SENT_SEPS = constants.SENTENCE_SEPARATORS   # AMENDMENT-21 冻结符集


def _sentences(t: str) -> list[str]:
    out, buf = [], []
    for ch in t:
        buf.append(ch)
        if ch in _SENT_SEPS or ch == "\n":
            s = "".join(buf).strip()
            if s:
                out.append(s)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _marker_rate(t: str, words: tuple[str, ...]) -> float:
    """含至少一个词表词的句子占比；空文本 = 0.0。"""
    sents = _sentences(t)
    if not sents:
        return 0.0
    hit = sum(1 for s in sents if any(w.lower() in s.lower() for w in words))
    return hit / len(sents)


def rescore_step(step: dict) -> list[dict]:
    """对一条 step 记录产出 rescore_v1 的 scores 行（能力指标 + manipulation-check 分列）。"""
    text: str = step["output_text"]
    base = {
        "schema_version": "1.0",
        "run_id": step["run_id"], "item_id": step["item_id"],
        "trajectory_id": step["trajectory_id"], "step_id": step["step_id"],
        "condition": step["condition"], "random_seed": step["random_seed"],
        "scorer_id": RESCORER_ID, "scorer_version": RESCORER_VERSION,
        "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    rows: list[dict] = []

    def emit(name: str, value: float | int) -> None:
        rows.append({**base, "metric_name": name, "metric_value": value})

    rule = GOLDEN_RULES.get(step["item_id"])
    if rule is not None:                       # golden10 之外的任务族：W1 只 golden10，
        emit("is_correct", rule(text))         # ifeval_zh_v1 判分规则由 B 定稿后（阶段2）
    emit("parse_ok", int(bool(text.strip())))  # 同步给你一份纯函数规则表（走契约广播）
    emit("output_len_chars", len(text))
    emit("output_len_tokens", int(step["output_tokens"]))  # 转录 step 记录值（不可独立重算）
    emit("hedging_rate", round(_marker_rate(text, HEDGING_WORDS), 6))
    emit("self_check_marker_rate", round(_marker_rate(text, SELF_CHECK_MARKERS), 6))
    return rows


def rescore_run(run_dir: Path) -> int:
    """整 run 复评：读 steps.jsonl → 逐条 rescore → 追加 scores.jsonl。幂等：
    已存在 rescore_v1 行的 (item_id, step_id, seed, metric) 跳过。返回新增行数。"""
    steps_p, scores_p = run_dir / "steps.jsonl", run_dir / "scores.jsonl"
    steps = [json.loads(l) for l in steps_p.read_text(encoding="utf-8").splitlines() if l.strip()]
    seen: set[tuple] = set()
    if scores_p.exists():
        for l in scores_p.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            if r.get("scorer_id") == RESCORER_ID:
                seen.add((r["item_id"], r["step_id"], r["random_seed"], r["metric_name"]))
    n = 0
    with scores_p.open("a", encoding="utf-8") as f:
        for st in steps:
            for row in rescore_step(st):
                key = (row["item_id"], row["step_id"], row["random_seed"], row["metric_name"])
                if key in seen:
                    continue
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                n += 1
    return n
