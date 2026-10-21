"""evidence_floor 单元测试（根因②：空/缺失被当成功）。"""
from __future__ import annotations

import pytest

from abcr.common.evidence_floor import (
    EvidenceError, agreement_or_none, mean_or_none, require_substantive)


def test_agreement_zero_total_is_none_never_full_score() -> None:
    """total==0 → None。绝不 1.0："零证据零分歧"≠"完全一致"。"""
    out = agreement_or_none(0, 0)
    assert out is None
    assert out != 1.0


def test_agreement_normal() -> None:
    assert agreement_or_none(3, 4) == pytest.approx(0.75)
    assert agreement_or_none(0, 4) == 0.0
    assert agreement_or_none(4, 4) == 1.0


def test_agreement_corrupt_counts_fail_closed() -> None:
    with pytest.raises(ValueError):
        agreement_or_none(-1, 3)
    with pytest.raises(ValueError):
        agreement_or_none(1, -3)
    with pytest.raises(ValueError):
        agreement_or_none(5, 3)


def test_mean_empty_is_none_never_zero() -> None:
    out = mean_or_none([])
    assert out is None
    assert out != 0.0
    assert mean_or_none(iter([])) is None      # 一次性迭代器同样安全


def test_mean_normal() -> None:
    assert mean_or_none([1.0, 2.0, 3.0]) == pytest.approx(2.0)
    assert mean_or_none(iter([2.0, 4.0])) == pytest.approx(3.0)


def test_require_substantive_raises_below_minimum() -> None:
    with pytest.raises(EvidenceError) as ei:
        require_substantive(0, "judged items")
    assert ei.value.n_effective == 0 and ei.value.minimum == 1
    assert "judged items" in str(ei.value)
    with pytest.raises(EvidenceError):
        require_substantive(2, "pairs", minimum=3)


def test_require_substantive_passes_and_returns_value() -> None:
    assert require_substantive(1, "x") == 1
    assert require_substantive(7, "x", minimum=3) == 7


def test_none_is_not_orderable_as_score() -> None:
    """约定固化：None 到不了数值比较——门若误把 None 当分数会立刻 TypeError，
    而不是静默当 0 通过（fail-closed 的兜底面）。"""
    val = agreement_or_none(0, 0)
    with pytest.raises(TypeError):
        _ = val >= 0.5  # type: ignore[operator]
