"""tests/drills/test_profiles.py —— A2-5 profile 字符串生成（平台无关，sandbox 不可用也跑）。"""
from __future__ import annotations

import os
from pathlib import Path

from abcr.sandboxing import profiles


def test_frozen_profile_has_three_deny_realpath_absolute(tmp_path: Path) -> None:
    prof = profiles.frozen_profile(tmp_path)
    assert prof.startswith("(version 1)\n(allow default)\n")
    deny_lines = [l for l in prof.splitlines() if l.startswith("(deny file-write*")]
    # 三冻结子树 subpath deny
    sub_lines = [l for l in deny_lines if "(subpath" in l]
    assert len(sub_lines) == 3
    for rel in ("data/golden", "data/splits", "data/traits"):
        rp = os.path.realpath(str(tmp_path / rel))
        assert any(rp in l for l in sub_lines), (rel, sub_lines)
    # 父节点 literal deny（防 `mv data data.bak` 换入伪冻结子树）——三区父节点均为 <root>/data
    lit_lines = [l for l in deny_lines if "(literal" in l]
    data_parent = os.path.realpath(str(tmp_path / "data"))
    assert any(data_parent in l for l in lit_lines), lit_lines
    # 所有 deny 路径为绝对路径（realpath 展开）
    for l in deny_lines:
        assert "~" not in l and os.path.isabs(l.split('"')[1])


def test_frozen_profile_last_match_deny_after_allow(tmp_path: Path) -> None:
    """last-match-wins：deny 行必须全部排在 (allow default) 之后。"""
    lines = profiles.frozen_profile(tmp_path).splitlines()
    allow_idx = lines.index("(allow default)")
    deny_idxs = [i for i, l in enumerate(lines) if l.startswith("(deny file-write*")]
    assert all(i > allow_idx for i in deny_idxs)


def test_whitelist_profile_denies_default_then_allows_workroot(tmp_path: Path) -> None:
    prof = profiles.whitelist_profile(tmp_path)
    lines = prof.splitlines()
    assert "(deny file-write*)" in lines
    root = os.path.realpath(str(tmp_path))
    assert any(f'(allow file-write* (subpath "{root}"))' == l for l in lines)
    # 冻结区 deny 排在 workroot allow 之后（last-match-wins）
    allow_root_idx = next(i for i, l in enumerate(lines)
                          if l == f'(allow file-write* (subpath "{root}"))')
    frozen_deny_idxs = [i for i, l in enumerate(lines)
                        if "data/golden" in l or "data/splits" in l or "data/traits" in l]
    assert all(i > allow_root_idx for i in frozen_deny_idxs)


def test_available_respects_disable_env(monkeypatch) -> None:
    monkeypatch.setenv("ABCR_SANDBOX_DISABLED", "1")
    assert profiles.available() is False


def test_wrap_passthrough_when_unavailable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ABCR_SANDBOX_DISABLED", "1")
    cmd = ["echo", "hi"]
    assert profiles.wrap(cmd, tmp_path) == cmd  # 原样返回，不静默包裹
