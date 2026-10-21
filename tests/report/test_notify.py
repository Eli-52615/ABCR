"""§7.1 notify mock 单测（零网络；§8.2 C-R2-8）。

monkeypatch abcr.notify._send_feishu 为记录桩 + ABCR_NOTIFY_ENABLED=1 + ABCR_STATE_DIR=tmp。
覆盖：开关关静默 / 首发+冷却文件 / 冷却内 suppressed / 发送失败不记冷却 / 冷却文件损坏放行 /
不同 kind 互不影响。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from abcr import notify


class _Stub:
    def __init__(self, ret: bool = True):
        self.ret = ret
        self.calls: list[str] = []

    def __call__(self, text: str) -> bool:
        self.calls.append(text)
        return self.ret


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ABCR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ABCR_NOTIFY_ENABLED", "1")
    stub = _Stub(True)
    monkeypatch.setattr(notify, "_send_feishu", stub)
    return {"stub": stub, "state": tmp_path / "state" / "alert-cooldown.json", "mp": monkeypatch}


def test_switch_off_silent(env):
    """① 开关关（0）→ 返回 False 且桩未被调。"""
    env["mp"].setenv("ABCR_NOTIFY_ENABLED", "0")
    assert notify.alert("budget:W1", "x") is False
    assert env["stub"].calls == []


def test_switch_unset_silent(env):
    env["mp"].delenv("ABCR_NOTIFY_ENABLED", raising=False)
    assert notify.alert("budget:W1", "x") is False
    assert env["stub"].calls == []


def test_first_send_true_and_cooldown_written(env):
    """② 首发 True 且冷却文件生成。"""
    assert notify.alert("budget:W1", "超预算") is True
    assert len(env["stub"].calls) == 1
    assert env["state"].exists()
    state = json.loads(env["state"].read_text(encoding="utf-8"))
    assert "budget:W1" in state


def test_same_kind_suppressed(env):
    """③ 同 kind 立刻再发 → False（suppressed）且桩只调过一次。"""
    assert notify.alert("budget:W1", "a") is True
    assert notify.alert("budget:W1", "b") is False
    assert len(env["stub"].calls) == 1


def test_send_failure_not_recorded_retries(env):
    """④ 桩返回 False（发送失败）→ 不记冷却，再调仍会尝试。"""
    env["stub"].ret = False
    assert notify.alert("budget:W1", "a") is False
    assert not env["state"].exists()          # 未记冷却
    assert len(env["stub"].calls) == 1
    assert notify.alert("budget:W1", "b") is False   # 再调仍尝试
    assert len(env["stub"].calls) == 2


def test_corrupt_cooldown_file_passes(env):
    """⑤ 冷却文件预置垃圾 → 不崩、按空状态放行。"""
    env["state"].parent.mkdir(parents=True, exist_ok=True)
    env["state"].write_text("{not json!!!", encoding="utf-8")
    assert notify.alert("budget:W1", "a") is True
    assert len(env["stub"].calls) == 1


def test_different_kinds_independent(env):
    """⑥ 不同 kind 互不影响（各自冷却）。"""
    assert notify.alert("budget:W1", "a") is True
    assert notify.alert("quarantined:B-1", "b") is True
    assert len(env["stub"].calls) == 2


def test_alert_silent_when_disabled_by_default():
    """§8.2 C-R2-8：ABCR_NOTIFY_ENABLED=0（或未设）下 alert 静默——不依赖任何桩。"""
    import os
    # 未 monkeypatch _send_feishu：若真去发送会因缺凭据返回 False；但开关关时应更早短路。
    prev = os.environ.pop("ABCR_NOTIFY_ENABLED", None)
    try:
        assert notify.alert("budget:W1", "x") is False
    finally:
        if prev is not None:
            os.environ["ABCR_NOTIFY_ENABLED"] = prev
