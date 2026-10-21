"""abcr.judge.blind_protocol — 五检之②表达检的 W1 盲评实现（B2-9）。

判定：盲评下 steered-pos 的 trait 分明显高于 baseline 与 steered-neg
（方向清晰 + 效应量 Cohen's d + 逐题分布图）。规格：n=20 评测题 × 每题 ≥2 响应 × 正负两向 + baseline。

盲化纪律（A 审计"judge 输入结构检查"硬项）：judge 只看到 (question, answer)，
一切条件字段（condition/trait/coef/question_id）在送 judge 前剥离；解盲靠加密索引回填。
judge 走 deepseek_client（自动 AMENDMENT-8 留痕）。
"""
from __future__ import annotations

import hashlib
import json
import random
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from abcr.common import evidence_floor
from abcr.judge import stats
from abcr.judge.deepseek_client import JudgeClient

CONDITIONS = ("baseline", "steered_pos", "steered_neg")

# 方向清晰的运行时判据（根因④：判据接线，不只写文档）。
# Cohen 惯例 d≈0.8 为"大效应"；"方向清晰"是强断言，两向 d 均须达大效应量，
# 且各条件须有实质样本（否则 None/微效应不得判清晰）。
DIRECTION_MIN_D = 0.8
DIRECTION_MIN_N = 2


@dataclass
class BlindItem:
    """盲化后送 judge 的载荷——只含 question/answer（无条件字段）。"""
    blind_id: str
    question: str
    answer: str


@dataclass
class BlindResult:
    trait: str
    per_condition: dict = field(default_factory=dict)   # condition -> [scores]
    effect_sizes: dict = field(default_factory=dict)     # 名称 -> d
    per_question: dict = field(default_factory=dict)     # question_id -> {condition: [scores]}
    n_judged: int = 0
    n_none: int = 0


def _opaque_blind_id(seed_blind: int, position: int, question: str, answer: str) -> str:
    """不可逆推的盲 id：以（保密的）seed_blind 为 key 对位置+内容哈希。

    根因（解盲）对抗：旧版 ``b{i:05d}`` 是顺序十进制明文——配合"已知的默认 seed + 已知
    输入分组次序"，judge 端可复现 shuffle 把 id 映回 condition。改为 seed 派生哈希后，
    不掌握 seed_blind 的一方（judge 只见 question/answer/blind_id）无法从 id 反推位置/次序，
    id 也不再泄露样本计数与排布。给定 seed 仍确定（可复现盲化供审计对账）。
    """
    h = hashlib.sha256(f"{seed_blind}|{position}|{question}|{answer}".encode("utf-8")).hexdigest()
    return "b" + h[:16]


def blind(groups: dict[str, list[dict]], seed_blind: int) -> tuple[list[BlindItem], dict[str, dict]]:
    """groups: {condition: [{question_id, question, answer}]}。
    返回 (打乱后的 BlindItem 列表, blind_id → {condition, question_id} 解盲映射)。

    ⚠️ seed_blind 是解盲根：绝不可送 judge、绝不可写入公开报告（index_map 才是留存的解盲件）。"""
    flat: list[tuple[str, dict]] = []
    for cond, rows in groups.items():
        for r in rows:
            flat.append((cond, r))
    rng = random.Random(seed_blind)
    rng.shuffle(flat)
    blinded: list[BlindItem] = []
    index_map: dict[str, dict] = {}
    for i, (cond, r) in enumerate(flat):
        bid = _opaque_blind_id(seed_blind, i, r["question"], r["answer"])
        blinded.append(BlindItem(blind_id=bid, question=r["question"], answer=r["answer"]))
        index_map[bid] = {"condition": cond, "question_id": r.get("question_id", "")}
    return blinded, index_map


def run_blind_eval(groups: dict[str, list[dict]], eval_prompt: str, trait: str,
                   judge: JudgeClient, seed_blind: Optional[int] = None) -> BlindResult:
    """盲化 → judge 逐条打分 → 解盲 → 统计（Cohen's d + 逐题分布）。

    seed_blind 默认 **None → 每次抽密码学随机种子**（根因对抗：旧默认 0 是已知常量，
    可被复现 shuffle 解盲）。显式传种子仅供可复现审计/测试；生产不传即随机。
    """
    if seed_blind is None:
        seed_blind = secrets.randbits(63)
    blinded, index_map = blind(groups, seed_blind)
    res = BlindResult(trait=trait)
    for cond in groups:
        res.per_condition.setdefault(cond, [])
    for item in blinded:
        score = judge.score(item.blind_id, item.question, item.answer, eval_prompt)
        res.n_judged += 1
        meta = index_map[item.blind_id]
        cond, qid = meta["condition"], meta["question_id"]
        if score is None:
            res.n_none += 1
            continue
        res.per_condition[cond].append(score)
        res.per_question.setdefault(qid, {}).setdefault(cond, []).append(score)
    # 效应量（steered_pos vs baseline / steered_neg）
    pos = res.per_condition.get("steered_pos", [])
    base = res.per_condition.get("baseline", [])
    neg = res.per_condition.get("steered_neg", [])
    res.effect_sizes = {
        "pos_vs_baseline": stats.cohens_d(pos, base),
        "pos_vs_neg": stats.cohens_d(pos, neg),
    }
    return res


def _summary(res: BlindResult) -> dict:
    # 空条件 → mean/std 为 None（根因②：绝不用 0.0 把空集伪装成"测过、均值 0"）。
    dist = {c: {"n": len(v),
                "mean": evidence_floor.mean_or_none(v),
                "std": stats.std(v) if len(v) >= 2 else None}
            for c, v in res.per_condition.items()}
    d1 = res.effect_sizes.get("pos_vs_baseline")
    d2 = res.effect_sizes.get("pos_vs_neg")
    n_min = min(len(res.per_condition.get(c, [])) for c in CONDITIONS)
    # 方向清晰的运行时判据（根因④接线 + 根因②空即失败）：两向 d 均须存在（非 None）、
    # 达大效应量阈值，且各条件样本充足。任一为 None/微效应/样本不足 → 判"不清晰"（fail-closed）。
    direction_clear = bool(
        d1 is not None and d2 is not None
        and d1 >= DIRECTION_MIN_D and d2 >= DIRECTION_MIN_D
        and n_min >= DIRECTION_MIN_N
    )
    return {
        "trait": res.trait,
        "n_judged": res.n_judged,
        "n_none": res.n_none,
        "distribution": dist,
        "effect_sizes": res.effect_sizes,
        "direction_clear": direction_clear,
        "direction_criteria": {"min_d": DIRECTION_MIN_D, "min_n_per_condition": DIRECTION_MIN_N,
                               "n_min_observed": n_min},
        "note": "exploratory / rig-validation —— 表达检产物，non-citable（Mac/占位）",
    }


def write_report(res: BlindResult, out_dir: Path = Path("reports")) -> dict:
    """写 reports/b_expression_check.json + b_expression_check_<trait>.png（AMENDMENT-31 b_ 前缀）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = _summary(res)
    (out_dir / "b_expression_check.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _plot(res, out_dir / f"b_expression_check_{res.trait}.png")
    return summary


def _plot(res: BlindResult, path: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001 — 无 matplotlib 时跳过绘图不阻塞
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = {"baseline": "#888888", "steered_pos": "#1f77b4", "steered_neg": "#d62728"}
    qids = sorted(res.per_question.keys())
    for xi, qid in enumerate(qids):
        for cond, scores in res.per_question[qid].items():
            xs = [xi + (list(colors).index(cond) - 1) * 0.15] * len(scores)
            ax.scatter(xs, scores, s=18, color=colors.get(cond, "#333"),
                       label=cond if xi == 0 else None, alpha=0.7)
    ax.set_xlabel("question")
    ax.set_ylabel(f"{res.trait} score (0-100)")
    ax.set_title(f"表达检逐题分布 · {res.trait}（exploratory）")
    if qids:
        ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def load_eval_csv(path: Path, trait: str) -> list[dict]:
    """从官方 eval_persona CSV 抽 (question_id, question, answer)（剥条件字段）。"""
    import pandas as pd
    df = pd.read_csv(path)
    return [{"question_id": str(r.get("question_id", i)), "question": str(r["question"]),
             "answer": str(r["answer"])} for i, r in df.iterrows()]
