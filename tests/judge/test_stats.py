"""tests/judge/test_stats —— 效应量/相关手算样例校验（纯 stdlib）。"""
from __future__ import annotations

import math

from abcr.judge import stats


def test_cohens_d_hand_computed():
    a = [10.0, 12.0, 14.0]   # mean 12, var=4 (ddof=1)
    b = [4.0, 6.0, 8.0]      # mean 6, var=4
    # pooled_std = sqrt((2*4 + 2*4)/4) = sqrt(4) = 2; d = (12-6)/2 = 3
    assert math.isclose(stats.cohens_d(a, b), 3.0, rel_tol=1e-9)


def test_cohens_d_insufficient_returns_none():
    # 根因②：样本不足是"证据不足"(None)，不是"零效应"(0.0)——0.0 会把没数据伪装成测过无效应。
    assert stats.cohens_d([1.0], [2.0]) is None
    assert stats.cohens_d([1.0, 2.0], []) is None
    # 无组内变异（pooled==0）→ 效应量未定义 → None（而非 0.0）。
    assert stats.cohens_d([5.0, 5.0], [3.0, 3.0]) is None


def test_spearman_perfect_monotonic():
    x = [1.0, 2.0, 3.0, 4.0]
    y = [10.0, 20.0, 33.0, 50.0]   # 单调递增但非线性
    assert math.isclose(stats.spearman(x, y), 1.0, rel_tol=1e-9)


def test_spearman_perfect_inverse():
    x = [1.0, 2.0, 3.0, 4.0]
    y = [4.0, 3.0, 2.0, 1.0]
    assert math.isclose(stats.spearman(x, y), -1.0, rel_tol=1e-9)


def test_pearson_hand():
    x = [1.0, 2.0, 3.0]
    y = [2.0, 4.0, 6.0]
    assert math.isclose(stats.pearson(x, y), 1.0, rel_tol=1e-9)
