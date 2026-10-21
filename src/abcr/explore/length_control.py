"""Deterministic exact-token 3L persona variants with manipulation checks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from abcr.control.contracts import ContractError, sha256


@dataclass(frozen=True)
class LengthVariant:
    label: str
    text: str
    token_count: int
    text_hash: str
    checks: tuple[str, ...]


def exact_length(text: str, target_tokens: int, *, encode: Callable[[str], list[int]],
                 padding_units: tuple[str, ...]) -> str:
    """Find a deterministic exact-token extension without guessing tokenizer behavior."""
    if isinstance(target_tokens, bool) or not isinstance(target_tokens, int) or not 1 <= target_tokens <= 4096:
        raise ContractError("bad_target_tokens", "target_tokens 必须为 1..4096 的整数")
    base_count = len(encode(text))
    if base_count > target_tokens:
        raise ContractError("persona_too_long", "人格正文已超过目标 token 数",
                            {"actual": base_count, "target": target_tokens})
    if base_count == target_tokens:
        return text
    frontier = [text]
    seen = {text}
    for _ in range(target_tokens - base_count + 2):
        next_frontier: list[str] = []
        for current in frontier:
            for unit in padding_units:
                candidate = current + unit
                if candidate in seen:
                    continue
                seen.add(candidate)
                count = len(encode(candidate))
                if count == target_tokens:
                    return candidate
                if count < target_tokens:
                    next_frontier.append(candidate)
        frontier = next_frontier[:4096]
        if not frontier:
            break
    raise ContractError("exact_token_unreachable", "冻结 padding_units 无法得到精确 token 长度")


def build_3l(base_text: str, targets: dict[str, int], *, encode: Callable[[str], list[int]],
             padding_units: tuple[str, ...], required_markers: tuple[str, ...]) -> tuple[LengthVariant, ...]:
    if set(targets) != {"short", "medium", "long"}:
        raise ContractError("bad_3l_targets", "3L targets 必须恰为 short/medium/long")
    counts = [targets[k] for k in ("short", "medium", "long")]
    if counts != sorted(set(counts)):
        raise ContractError("bad_3l_order", "3L token 数必须严格递增")
    out = []
    for label in ("short", "medium", "long"):
        text = exact_length(base_text, targets[label], encode=encode, padding_units=padding_units)
        checks = tuple(marker for marker in required_markers if marker in text)
        if checks != required_markers:
            raise ContractError("manipulation_check_failed", f"{label} 缺少冻结 manipulation marker",
                                {"expected": required_markers, "observed": checks})
        out.append(LengthVariant(label, text, len(encode(text)), sha256(text.encode()), checks))
    return tuple(out)
