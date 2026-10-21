"""tests/ledger/test_statemachine.py —— A1-3 三层状态机测试。"""
from __future__ import annotations

from abcr.ledger import statemachine as sm


# ---------- 合法迁移逐条 True ----------

def test_run_legal_transitions_all_true() -> None:
    for cur, targets in sm.RUN_TRANSITIONS.items():
        for new in targets:
            ok, why = sm.validate_transition("run", cur, new)
            assert ok, f"run {cur}->{new} 应合法: {why}"


def test_batch_legal_transitions_all_true() -> None:
    for cur, targets in sm.BATCH_TRANSITIONS.items():
        for new in targets:
            assert sm.validate_transition("batch", cur, new)[0]


def test_protocol_legal_transitions_all_true() -> None:
    for cur, targets in sm.PROTOCOL_TRANSITIONS.items():
        for new in targets:
            assert sm.validate_transition("protocol", cur, new)[0]


def test_audit_exempt_transitions() -> None:
    """AMENDMENT-16：COMPLETED/FAILED/SCORED → AUDITED 均合法。"""
    for cur in ("COMPLETED", "FAILED", "SCORED"):
        assert sm.validate_transition("run", cur, "AUDITED")[0]


# ---------- 非法迁移 ≥8 条 False ----------

def test_illegal_transitions_rejected() -> None:
    illegal = [
        ("run", "RUNNING", "SCORED"), ("run", "COMPLETED", "RUNNING"),
        ("run", "QUEUED", "COMPLETED"), ("run", "ACCEPTED", "RUNNING"),
        ("batch", "DRAFT", "SETTLED"), ("batch", "REPORTED", "DRAFT"),
        ("protocol", "FROZEN", "REVIEW"), ("protocol", "SUPERSEDED", "FROZEN"),
        ("run", "AUDITED", "COMPLETED"),
    ]
    for kind, cur, new in illegal:
        ok, why = sm.validate_transition(kind, cur, new)
        assert not ok, f"{kind} {cur}->{new} 应非法"
        assert "非法迁移" in why


def test_unknown_kind_and_state() -> None:
    assert sm.validate_transition("nope", "A", "B") == (False, "未知对象层 'nope'")
    assert not sm.validate_transition("run", "BOGUS", "QUEUED")[0]
    assert not sm.validate_transition("run", "QUEUED", "BOGUS")[0]


# ---------- derive_run_state ----------

def test_derive_legal_sequence() -> None:
    evs = [{"event": e} for e in (
        "run_registered", "run_queued", "run_started", "step_progress",
        "step_progress", "run_completed", "run_scored", "run_audited")]
    state, violations = sm.derive_run_state(evs)
    assert state == "AUDITED"
    assert violations == []


def test_derive_out_of_order_reports_violations() -> None:
    evs = [{"event": e} for e in ("run_started", "run_completed")]  # 首事件非 registered
    state, violations = sm.derive_run_state(evs)
    assert violations, "乱序序列应报违规"


def test_derive_step_progress_outside_running() -> None:
    evs = [{"event": "run_registered"}, {"event": "step_progress"}]
    _, violations = sm.derive_run_state(evs)
    assert any("step_progress" in v for v in violations)


# ---------- TTL env 覆盖 ----------

def test_ttl_defaults() -> None:
    ttl = sm.ttl_seconds()
    assert ttl["QUEUED"] == 3600 and ttl["RUNNING_HEARTBEAT"] == 1800
    assert ttl["COMPLETED"] == 7200 and ttl["SCORED"] == 7200


def test_ttl_env_override(monkeypatch) -> None:
    monkeypatch.setenv("ABCR_TTL_QUEUED_S", "111")
    monkeypatch.setenv("ABCR_TTL_RUNNING_HEARTBEAT_S", "222")
    ttl = sm.ttl_seconds()
    assert ttl["QUEUED"] == 111 and ttl["RUNNING_HEARTBEAT"] == 222
