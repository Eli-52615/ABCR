"""tests/rig/test_splits —— 确定性切分协议（契约 §2.7 / §3.5）。"""
from __future__ import annotations

import hashlib

from abcr.rig.splits import SALT, assign_split, split_hash


def test_assign_split_deterministic():
    assert assign_split("fam", "x1") == assign_split("fam", "x1")


def test_assign_split_matches_formula():
    fam, item = "ifeval_zh_v1", "ifzh-0001"
    h = int(hashlib.sha256(f"{fam}:{item}:{SALT}".encode()).hexdigest()[:8], 16) % 100
    expected = "dev" if h < 20 else ("calibration" if h < 60 else "holdout")
    assert assign_split(fam, item) == expected


def test_assign_split_only_three_buckets():
    got = {assign_split("ifeval_zh_v1", f"ifzh-{i:04d}") for i in range(1, 251)}
    assert got <= {"dev", "calibration", "holdout"}


def test_split_hash_order_independent():
    a = {"i2": "dev", "i1": "holdout"}
    b = {"i1": "holdout", "i2": "dev"}
    assert split_hash(a) == split_hash(b)


def test_salt_matches_constants():
    from abcr.common import constants
    assert SALT == constants.SPLIT_SALT
