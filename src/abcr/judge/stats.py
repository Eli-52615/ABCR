"""abcr.judge.stats — judge 侧统计小工具（纯 stdlib，不依赖 scipy/numpy）。

Cohen's d（表达检效应量）、Spearman/Pearson 相关（judge 一致性）、方向一致率。
"""
from __future__ import annotations

import math
from typing import Optional, Sequence


def mean(xs: Sequence[float]) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def variance(xs: Sequence[float], ddof: int = 1) -> float:
    xs = list(xs)
    n = len(xs)
    if n - ddof <= 0:
        return 0.0
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (n - ddof)


def std(xs: Sequence[float], ddof: int = 1) -> float:
    return math.sqrt(variance(xs, ddof))


def cohens_d(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """d = (mean_a - mean_b) / pooled_std（样本方差 ddof=1）。

    根因②对抗：样本不足（任一组 n<2）或无组内变异（pooled==0）→ **None**（证据不足/
    未定义），**绝不返回 0.0**——0.0 是合法的"零效应"值，会把"没数据"伪装成"测过、无效应"。
    None 的语义与 evidence_floor 对齐：任何门见 None 必须判 FAIL / 方向不清晰，
    不得当作 0 参与 `d > 0` 比较（None > 0 会 TypeError，静默通过被切断）。
    """
    a, b = list(a), list(b)
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    va, vb = variance(a), variance(b)
    denom = na + nb - 2
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / denom) if denom > 0 else 0.0
    if pooled == 0.0:
        return None
    return (mean(a) - mean(b)) / pooled


def _rankdata(xs: Sequence[float]) -> list[float]:
    """平均秩（并列取平均秩）。"""
    xs = list(xs)
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based 平均秩
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    x, y = list(x), list(y)
    n = len(x)
    if n < 2 or n != len(y):
        return 0.0
    mx, my = mean(x), mean(y)
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    dx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    dy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    """Spearman 秩相关 = 秩上的 Pearson。"""
    if len(x) < 2 or len(x) != len(y):
        return 0.0
    return pearson(_rankdata(x), _rankdata(y))
