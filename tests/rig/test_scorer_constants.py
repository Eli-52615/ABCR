"""tests/rig/test_scorer_constants —— 锁定 scorer 内联词表 == constants.py（AMENDMENT-20/21）。

scorer.py 保持 stdlib 自包含（不 import abcr.common.constants），值共享靠本测试锁定：
内联的 HEDGING_WORDS / SELF_CHECK_MARKERS / SENTENCE_SEPARATORS 必须与 constants 逐项相等。
A/B 共享词表常量、独立实现计数（auditor item2 逐格比对）。
"""
from __future__ import annotations

from abcr.common import constants
from abcr.rig import scorer


def test_hedging_words_match_constants():
    assert scorer.HEDGING_WORDS == constants.HEDGING_WORDS


def test_self_check_markers_match_constants():
    assert scorer.SELF_CHECK_MARKERS == constants.SELF_CHECK_MARKERS


def test_sentence_separators_match_constants():
    assert scorer.SENTENCE_SEPARATORS == constants.SENTENCE_SEPARATORS
