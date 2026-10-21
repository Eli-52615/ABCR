"""tests/ops/test_runstate —— 断点续跑对账：幂等续跑、item 落盘、孤儿扫描、续跑守卫五分支。"""
from __future__ import annotations

import pytest

from abcr.ops import runstate

ITEMS = ["g01", "g02", "g03"]


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # AMENDMENT-38：状态根改为调用时读 ABCR_STATE_DIR（不再有 RUNS_DIR 模块常量）
    monkeypatch.setenv("ABCR_STATE_DIR", str(tmp_path))


def test_register_idempotent_resume_count():
    runstate.register_run("r1", ITEMS)
    assert runstate.load("r1")["resume_count"] == 0
    runstate.register_run("r1", ITEMS)   # 续跑
    rec = runstate.load("r1")
    assert rec["resume_count"] == 1
    assert rec["status"] == runstate.STATUS_RUNNING


def test_mark_item_done_reduces_pending():
    runstate.register_run("r1", ITEMS)
    assert set(runstate.pending_items("r1")) == set(ITEMS)
    runstate.mark_item_done("r1", "g01")
    assert set(runstate.pending_items("r1")) == {"g02", "g03"}


def test_all_done_sets_status_done():
    runstate.register_run("r1", ITEMS)
    for i in ITEMS:
        runstate.mark_item_done("r1", i)
    assert runstate.load("r1")["status"] == runstate.STATUS_DONE
    assert runstate.pending_items("r1") == []


def test_scan_orphans_dead_pid_and_stale_to_suspended(monkeypatch):
    """F-OPS-01：只有 pid 确证不存活 且 心跳陈旧 才判孤儿。"""
    runstate.register_run("r1", ITEMS)   # status running, pid=os.getpid()（存活）
    monkeypatch.setattr(runstate, "_pid_alive", lambda pid: False)  # 执行进程已消失
    monkeypatch.setattr(runstate, "_age_s", lambda ts: 10 ** 9)     # 心跳陈旧
    orphans = runstate.scan_orphans()
    assert [o["run_id"] for o in orphans] == ["r1"]
    assert runstate.load("r1")["status"] == runstate.STATUS_SUSPENDED


def test_scan_orphans_alive_run_not_killed():
    """F-OPS-01 修复核心：pid 仍存活的 running run 绝不被误杀成孤儿。"""
    runstate.register_run("r1", ITEMS)   # pid=os.getpid()（存活）
    orphans = runstate.scan_orphans()
    assert orphans == []
    assert runstate.load("r1")["status"] == runstate.STATUS_RUNNING


def test_can_resume_no_record():
    ok, _ = runstate.can_resume("nope")
    assert ok is False


def test_can_resume_not_suspended():
    runstate.register_run("r1", ITEMS)   # running
    ok, why = runstate.can_resume("r1")
    assert ok is False and "非 suspended" in why


def test_can_resume_ok():
    runstate.register_run("r1", ITEMS)
    runstate.mark_suspended("r1", "boom")   # rc=0，无冷却
    ok, why = runstate.can_resume("r1")
    assert ok is True and why == "ok"


def test_can_resume_poison_pill():
    for _ in range(6):                      # rc 累加到 5
        runstate.register_run("r1", ITEMS)
    runstate.mark_suspended("r1", "boom")
    ok, why = runstate.can_resume("r1", max_resume=5)
    assert ok is False and "毒丸上限" in why


def test_can_resume_cooldown():
    runstate.register_run("r1", ITEMS)
    runstate.register_run("r1", ITEMS)      # rc=1
    runstate.mark_suspended("r1", "boom")   # updated_at 刚刚
    ok, why = runstate.can_resume("r1", cooldown_s=9999)
    assert ok is False and "冷却" in why
