"""tests/ops/test_heartbeat —— 每 5 item 落一条 step_progress；flush 补尾。"""
from __future__ import annotations

from abcr.ops.heartbeat import Heartbeat


def _recorder():
    events: list[dict] = []

    def append(event, *, subject_id, **payload):
        events.append({"event": event, "subject_id": subject_id, **payload})
    return events, append


def test_ten_items_two_progress_no_flush():
    events, append = _recorder()
    hb = Heartbeat(append, "r1")
    for _ in range(10):
        hb.tick()
    assert len(events) == 2                      # item 5、item 10
    hb.flush()
    assert len(events) == 2                      # 10%5==0，flush 不追加
    assert events[-1]["items_done"] == 10


def test_seven_items_one_tick_one_flush():
    events, append = _recorder()
    hb = Heartbeat(append, "r1")
    for _ in range(7):
        hb.tick()
    assert len(events) == 1                      # item 5
    hb.flush()
    assert len(events) == 2                      # 7%5!=0，flush 补一条
    assert events[-1]["items_done"] == 7


def test_start_items_resume_continuity():
    """续跑：start_items=4，再 tick 6 次到全局 10 → 恰 2 条（item5、item10）。"""
    events, append = _recorder()
    hb = Heartbeat(append, "r1", start_items=4)
    for _ in range(6):
        hb.tick()
    assert [e["items_done"] for e in events] == [5, 10]
    hb.flush()
    assert len(events) == 2
