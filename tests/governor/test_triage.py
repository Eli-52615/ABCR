"""C1-5 triage 测试（§C1-5 测试要求）。用 RunLedger 往 tmp 账本写 6-run 剧本。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from abcr.common.ledger_ref import RunLedger
from abcr.governor import triage


def make_fixture_ledger(tmp_path: Path) -> Path:
    """6 run 剧本（§C1-5）：4 正常 SCORED；1 failed→resumed→completed→scored（已收敛）；
    1 started 后无事件（停摆，测试注入 now=+1h）。run_registered payload 含 batch_id。"""
    ldir = tmp_path / "ledger"
    led = RunLedger(ldir, "runs_index")
    bid = "B-20260714T000000Z-0001"

    def normal_run(rid):
        led.append("run_registered", subject_id=rid, batch_id=bid)
        led.append("run_queued", subject_id=rid)
        led.append("run_started", subject_id=rid)
        led.append("step_progress", subject_id=rid, steps_done=5, items_done=5)
        led.append("run_completed", subject_id=rid)
        led.append("run_scored", subject_id=rid)

    for i in range(4):
        normal_run(f"run-normal-{i}")

    # 已收敛：failed → resumed → completed → scored
    rc = "run-converged"
    led.append("run_registered", subject_id=rc, batch_id=bid)
    led.append("run_queued", subject_id=rc)
    led.append("run_started", subject_id=rc)
    led.append("run_failed", subject_id=rc)
    led.append("run_resumed", subject_id=rc)
    led.append("run_completed", subject_id=rc)
    led.append("run_scored", subject_id=rc)

    # 停摆：started 后无事件
    rs = "run-stalled"
    led.append("run_registered", subject_id=rs, batch_id=bid)
    led.append("run_queued", subject_id=rs)
    led.append("run_started", subject_id=rs)
    return ldir


def test_triage_buckets(tmp_path):
    ldir = make_fixture_ledger(tmp_path)
    now = datetime.now(timezone.utc) + timedelta(hours=1)   # 注入未来，使停摆 run 无心跳>1800s
    buckets = triage.triage(ldir, envdir=tmp_path / "noenv",
                            alerts_dir=tmp_path / "noalerts", now=now)
    assert len(buckets["停摆"]) == 1, buckets["停摆"]
    assert len(buckets["已收敛偏差"]) == 1, buckets["已收敛偏差"]
    assert len(buckets["失败未收敛"]) == 0, buckets["失败未收敛"]
    assert len(buckets["正常"]) == 4, buckets["正常"]
    # 停摆 severity = A
    assert buckets["停摆"][0]["severity"] == "A"


def test_triage_md(tmp_path):
    ldir = make_fixture_ledger(tmp_path)
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    out = triage.run(ldir, tmp_path / "reports", now=now,
                     envdir=tmp_path / "noenv", alerts_dir=tmp_path / "noalerts")
    md = out.read_text(encoding="utf-8")
    # 正常桶只占一行
    normal_lines = [ln for ln in md.splitlines() if ln.startswith("- 正常 run")]
    assert len(normal_lines) == 1 and "4 个" in normal_lines[0]
    # 尾部计数行
    assert "今日 A+B 告警数" in md
    # 停摆段存在
    assert "## 停摆" in md


def test_triage_empty_ledger(tmp_path):
    """空账本不炸：各桶空 + 正常 0 + 计数行。"""
    (tmp_path / "ledger").mkdir()
    now = datetime.now(timezone.utc)
    out = triage.run(tmp_path / "ledger", tmp_path / "reports", now=now,
                     envdir=tmp_path / "noenv", alerts_dir=tmp_path / "noalerts")
    md = out.read_text(encoding="utf-8")
    assert "正常 run 0 个" in md
    assert "今日 A+B 告警数 0/3" in md


def test_triage_instance_idle_alert_is_A(tmp_path):
    """C2-6 ②：云实例空转 instance_idle_alert → A 级紧急桶。"""
    ldir = tmp_path / "ledger"
    inst = RunLedger(ldir, "instances")
    inst.append("instance_registered", subject_id="inst-1")
    inst.append("instance_started", subject_id="inst-1")
    inst.append("instance_idle_alert", subject_id="inst-1")
    buckets = triage.triage(ldir, envdir=tmp_path / "noenv",
                            alerts_dir=tmp_path / "noalerts",
                            now=datetime.now(timezone.utc))
    idle = [e for e in buckets["A级紧急"] if e["subject_id"] == "inst-1"]
    assert idle and idle[0]["severity"] == "A"
    assert "instance_idle_alert" in idle[0]["evidence"]


def test_triage_budget_actual_over_85_is_A(tmp_path):
    """C2-6 ①：实耗 ≥ 85%×150 → A 级紧急（熔断）。"""
    ldir = tmp_path / "ledger"
    costs = RunLedger(ldir, "costs")
    costs.append("run_cost_actual", subject_id="run-x", amount_cny=130.0, basis="act")  # >127.5
    buckets = triage.triage(ldir, envdir=tmp_path / "noenv",
                            alerts_dir=tmp_path / "noalerts",
                            now=datetime.now(timezone.utc))
    assert any(e["subject_id"] == "W1" and e["severity"] == "A" for e in buckets["A级紧急"])


def test_triage_pending_draft_envelope(tmp_path):
    """待批 DRAFT 信封入待决桶。"""
    (tmp_path / "ledger").mkdir()
    envdir = tmp_path / "envelopes"
    envdir.mkdir()
    (envdir / "d.json").write_text('{"batch_id":"B-20260714T000000Z-0009"}', encoding="utf-8")
    buckets = triage.triage(tmp_path / "ledger", envdir=envdir,
                            alerts_dir=tmp_path / "noalerts",
                            now=datetime.now(timezone.utc))
    assert any("0009" in e["subject_id"] for e in buckets["待决"])
