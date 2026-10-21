"""abcr.common.evidence_floor —— 空/缺失即失败（对抗根因②：空被当成功）。

约定（全仓冻结语义，所有消费组对齐）
------------------------------------
1. **None 一律代表「未定义/证据不足」**，不是 0、不是满分、不是通过。
   - ``agreement_or_none(0 matches, 0 total)`` → None（绝不 1.0——
     "零证据零分歧"不等于"完全一致"）。
   - ``mean_or_none([])`` → None（绝不 0.0——空集没有均值）。
2. **任何门（gate）见 None 必须判 FAIL**，不得把 None 当 0 参与比较、
   不得跳过该判据。要"跳过"必须显式走豁免路径并留痕。
3. 需要"有实质证据才继续"的入口用 ``require_substantive``：
   证据量低于下限直接抛 ``EvidenceError``（fail-closed，不返回哨兵值）。

等价攻击自问：换一个"空输入/缺键/零样本"的变体还绕得过吗？
—— 绕不过：本模块从值域上取消了"空 → 好分数"这条路径；门端只要
遵守约定 1/2，空集只能得到 None/异常，永远到不了 PASS。
"""
from __future__ import annotations

from typing import Iterable, Optional


class EvidenceError(Exception):
    """实质证据不足（n_effective < minimum）。fail-closed：抛出而非返回哨兵。"""

    def __init__(self, what: str, n_effective: int, minimum: int) -> None:
        self.what = what
        self.n_effective = n_effective
        self.minimum = minimum
        super().__init__(
            f"insufficient evidence for {what}: "
            f"n_effective={n_effective} < minimum={minimum}")


def agreement_or_none(matches: int, total: int) -> Optional[float]:
    """一致率。total==0 → None（绝不 return 1.0）；否则 matches/total。

    negative/超界输入视为损坏的统计，同样 fail-closed 抛 ValueError。
    """
    if total < 0 or matches < 0:
        raise ValueError(f"negative counts: matches={matches} total={total}")
    if matches > total:
        raise ValueError(f"matches={matches} > total={total}")
    if total == 0:
        return None
    return matches / total


def mean_or_none(xs: Iterable[float]) -> Optional[float]:
    """均值。空序列 → None（绝不 0.0）。"""
    vals = list(xs)
    if not vals:
        return None
    return sum(vals) / len(vals)


def require_substantive(n_effective: int, what: str, minimum: int = 1) -> int:
    """要求实质证据量：n_effective < minimum → 抛 EvidenceError；否则原值返回。

    用在门/评分入口，把"空集走完全程拿满分"在入口处掐断。
    """
    if n_effective < minimum:
        raise EvidenceError(what, n_effective, minimum)
    return n_effective
