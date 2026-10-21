"""abcr.rig.splits — 确定性 split 工具（契约 §2.7 切分协议）。

架构位置：rig(B)。切分完全由 item_id 的 sha256 哈希决定，与顺序/时间无关，
故 split_hash 可入 git 冻结。salt 为协议常量（constants.SPLIT_SALT 同值）。
"""
from __future__ import annotations

import hashlib

SALT = "abcr-w1-v1"   # 协议常量，constants.py 有同值以其为准


def assign_split(family: str, item_id: str) -> str:
    h = int(hashlib.sha256(f"{family}:{item_id}:{SALT}".encode()).hexdigest()[:8], 16) % 100
    return "dev" if h < 20 else ("calibration" if h < 60 else "holdout")


def split_hash(assignments: dict[str, str]) -> str:
    """assignments: {item_id: split}"""
    joined = "\n".join(sorted(f"{i}\t{s}" for i, s in assignments.items()))
    return hashlib.sha256(joined.encode()).hexdigest()
