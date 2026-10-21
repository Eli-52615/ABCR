"""tests/contract_pkgabc/test_chain_and_transition_contract.py ——
契约：哈希链断链检测（tamper）+ 状态机非法迁移拒绝（transition）。

权威语义 = fable 广播 20260715 AMENDMENT-36（A 式 RunLedger(root, chain).append(event,
subject_id=..., **payload)；记录形状 {ts, run_id, event, ...payload, prev_hash, entry_hash}
无 seq；增补 events(event=, subject_id=)/has_event/模块级 append_record）+ AMENDMENT-38
（statemachine 冻结 A 版：validate_transition 不抛 + assert_* 抛 TransitionError）
+ AMENDMENT-13（批次无 REJECTED 态）+ AMENDMENT-16（COMPLETED/FAILED/SCORED→AUDITED 合法，
三处置终态只能自 AUDITED 进入）。

本文件由 A 版 test_chain_and_transition_contract.py 与 B 版 test_chain.py、
test_statemachine.py 合并改写：B 版 read_all() → events()；B 版 seq 断言废（AMENDMENT-36），
改断言"无 seq + prev_hash 链接"；B 版模块级 verify_chain(path) → RunLedger(...).verify_chain()；
B 版空 subject_id ValueError 断言删除（冻结版无此闸，主体约束归 schema/调用方）；
B 版 COMPLETED→CANCELLED / SCORED→CANCELLED 合法性反转为非法断言（AMENDMENT-16）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from abcr.common.ledger_ref import (GENESIS_HASH, LedgerTampered, RunLedger,
                                    append_record)
from abcr.ledger import statemachine as sm


# ================================================================ 哈希链
def test_append_and_verify(tmp_path: Path) -> None:
    led = RunLedger(tmp_path, "runs_index")
    led.append("run_registered", subject_id="r1", batch_id="B-1")
    led.append("run_started", subject_id="r1", batch_id="B-1")
    led.append("step_progress", subject_id="r1", steps_done=5, items_done=5)
    assert led.verify_chain() is True
    evs = led.events()
    assert [e["event"] for e in evs] == ["run_registered", "run_started", "step_progress"]
    assert all("prev_hash" in e and "entry_hash" in e for e in evs)


def test_record_shape_frozen(tmp_path: Path) -> None:
    """记录形状冻结 A 形：{ts, run_id(=链 stem), event, ...payload, prev_hash, entry_hash}，无 seq。"""
    led = RunLedger(tmp_path, "batches")
    rec = led.append("batch_drafted", subject_id="B-1", note="x")
    assert list(rec)[:3] == ["ts", "run_id", "event"]
    assert list(rec)[-2:] == ["prev_hash", "entry_hash"]
    assert rec["run_id"] == "batches"           # 类字段 run_id 语义 = chain_id
    assert "seq" not in rec                     # B 形 seq 字段废（AMENDMENT-36）
    assert rec["prev_hash"] == GENESIS_HASH     # 首条挂创世
    rec2 = led.append("batch_approved", subject_id="B-1")
    assert rec2["prev_hash"] == rec["entry_hash"]


def test_chain_tamper_detected(tmp_path: Path) -> None:
    """哈希链断链检测：改一条即 verify_chain raise LedgerTampered(带 index)。"""
    lg = RunLedger(tmp_path, "runs_index")
    for i in range(3):
        lg.append("run_queued", subject_id=f"r{i}")
    lines = lg.path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1]); rec["subject_id"] = "hacked"
    lines[1] = json.dumps(rec, ensure_ascii=False)
    lg.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(LedgerTampered) as ei:
        lg.verify_chain()
    assert ei.value.index == 1                  # 定位到被改条目
    assert "1" in str(ei.value)


def test_chain_delete_detected(tmp_path: Path) -> None:
    """删首条 → 次条 prev_hash 悬空 → 定位 index 0。"""
    lg = RunLedger(tmp_path, "runs_index")
    for i in range(3):
        lg.append("run_queued", subject_id=f"r{i}")
    lines = lg.path.read_text(encoding="utf-8").splitlines()
    del lines[0]
    lg.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(LedgerTampered) as ei:
        lg.verify_chain()
    assert ei.value.index == 0


@pytest.mark.parametrize("key", ["ts", "run_id", "prev_hash", "entry_hash"])
def test_reserved_payload_key_rejected(tmp_path: Path, key: str) -> None:
    """保留键守卫：payload 不得用 ts/run_id/event/prev_hash/entry_hash（业务主体用 subject_id）。
    注：event 作 kwargs 与位置参数天然冲突（TypeError），不在本参数化内。"""
    led = RunLedger(tmp_path, "runs_index")
    with pytest.raises(ValueError):
        led.append("run_started", **{"subject_id": "r1", key: "x"})


def test_events_filter(tmp_path: Path) -> None:
    """AMENDMENT-36 ①：events(event=, subject_id=) 过滤。"""
    led = RunLedger(tmp_path, "runs_index")
    led.append("run_registered", subject_id="r1")
    led.append("run_registered", subject_id="r2")
    led.append("run_started", subject_id="r1")
    assert len(led.events()) == 3
    assert [e["subject_id"] for e in led.events(event="run_registered")] == ["r1", "r2"]
    assert [e["event"] for e in led.events(subject_id="r1")] == ["run_registered", "run_started"]
    assert [e["event"] for e in led.events(event="run_started", subject_id="r1")] == ["run_started"]
    assert led.events(subject_id="r9") == []


def test_has_event_idempotency_helper(tmp_path: Path) -> None:
    """AMENDMENT-36 ②：has_event(event, subject_id)（dispatch 幂等硬依赖）。"""
    led = RunLedger(tmp_path, "batches")
    assert not led.has_event("batch_settled", "B-1")
    led.append("batch_settled", subject_id="B-1")
    assert led.has_event("batch_settled", "B-1")
    assert not led.has_event("batch_settled", "B-2")
    assert not led.has_event("batch_audited", "B-1")


def test_append_record_generic_chain(tmp_path: Path) -> None:
    """AMENDMENT-36 ③：模块级 append_record —— steps.jsonl 整记录挂链，只补链字段、无 seq。"""
    p = tmp_path / "steps.jsonl"
    r1 = append_record(p, {"item_id": "g01", "random_seed": 1, "run_id": "r-biz"})
    r2 = append_record(p, {"item_id": "g02", "random_seed": 1, "run_id": "r-biz"})
    assert "seq" not in r1 and "seq" not in r2          # B 形 seq 废
    assert r1["run_id"] == "r-biz"                      # 业务 run_id 原样保留
    assert r1["prev_hash"] == GENESIS_HASH
    assert r2["prev_hash"] == r1["entry_hash"]
    # 同文件可用 RunLedger 重放验链（verify_chain 只依赖链字段）
    assert RunLedger(tmp_path, "steps").verify_chain() is True


def test_append_record_rejects_prechained(tmp_path: Path) -> None:
    """拒收已含链字段的记录（AMENDMENT-36 ③ 原文）。"""
    p = tmp_path / "steps.jsonl"
    with pytest.raises(ValueError):
        append_record(p, {"item_id": "g01", "prev_hash": "0" * 64})
    with pytest.raises(ValueError):
        append_record(p, {"item_id": "g01", "entry_hash": "a" * 64})


def test_append_record_tamper_detected(tmp_path: Path) -> None:
    p = tmp_path / "steps.jsonl"
    append_record(p, {"item_id": "g01"})
    append_record(p, {"item_id": "g02"})
    lines = p.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0]); rec["item_id"] = "HACKED"
    lines[0] = json.dumps(rec, ensure_ascii=False)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(LedgerTampered):
        RunLedger(tmp_path, "steps").verify_chain()


# ================================================================ 状态机 · validate_transition（A 式不抛）
@pytest.mark.parametrize("kind,cur,new", [
    ("run", "RUNNING", "SCORED"), ("run", "COMPLETED", "RUNNING"),
    ("batch", "DRAFT", "SETTLED"), ("protocol", "FROZEN", "REVIEW"),
    ("run", "ACCEPTED", "QUEUED"),
])
def test_illegal_transition_rejected(kind: str, cur: str, new: str) -> None:
    ok, why = sm.validate_transition(kind, cur, new)
    assert not ok and "非法迁移" in why


@pytest.mark.parametrize("kind,cur,new", [
    ("run", "COMPLETED", "SCORED"), ("run", "SCORED", "AUDITED"),
    ("run", "AUDITED", "ACCEPTED"), ("batch", "SETTLED", "AUDITED"),
    ("protocol", "REVIEW", "FROZEN"),
])
def test_legal_transition_accepted(kind: str, cur: str, new: str) -> None:
    assert sm.validate_transition(kind, cur, new)[0]


def test_unknown_kind_and_state_rejected() -> None:
    assert not sm.validate_transition("bogus", "DRAFT", "APPROVED")[0]
    assert not sm.validate_transition("run", "NOSUCH", "QUEUED")[0]
    assert not sm.validate_transition("run", "QUEUED", "NOSUCH")[0]


# ================================================================ 状态机 · assert_*（B 式抛 TransitionError）
@pytest.mark.parametrize("src,dst", [
    ("PLANNED", "QUEUED"), ("QUEUED", "RUNNING"), ("RUNNING", "COMPLETED"),
    ("RUNNING", "FAILED"), ("FAILED", "RUNNING"),   # 续跑
    ("COMPLETED", "SCORED"), ("SCORED", "AUDITED"), ("AUDITED", "ACCEPTED"),
    ("AUDITED", "QUARANTINED"), ("RUNNING", "CANCELLED"),
    # AMENDMENT-16 审计豁免迁移
    ("COMPLETED", "AUDITED"), ("FAILED", "AUDITED"),
])
def test_legal_run_transitions(src: str, dst: str) -> None:
    sm.assert_run(src, dst)                    # 不抛


@pytest.mark.parametrize("src,dst", [
    ("PLANNED", "RUNNING"),        # 跳过 QUEUED
    ("QUEUED", "COMPLETED"),       # 跳过 RUNNING
    ("SCORED", "RUNNING"),         # 倒流
    ("ACCEPTED", "RUNNING"),       # 终态不可迁出
    ("AUDITED", "SCORED"),         # 倒流
    # B 版曾断言合法，AMENDMENT-16 冻结后反转为非法（终态只能自 AUDITED 进入；CANCELLED 不例外）
    ("COMPLETED", "CANCELLED"),
    ("SCORED", "CANCELLED"),
])
def test_illegal_run_transitions(src: str, dst: str) -> None:
    with pytest.raises(sm.TransitionError):
        sm.assert_run(src, dst)


def test_batch_transitions() -> None:
    sm.assert_batch("DRAFT", "APPROVED")
    sm.assert_batch("APPROVED", "DISPATCHING")
    sm.assert_batch("DISPATCHING", "SETTLED")
    sm.assert_batch("SETTLED", "AUDITED")
    with pytest.raises(sm.TransitionError):
        sm.assert_batch("DRAFT", "SETTLED")    # 跳步
    with pytest.raises(sm.TransitionError):
        sm.assert_batch("REPORTED", "DRAFT")   # 终态迁出


def test_batch_has_no_rejected_state() -> None:
    """AMENDMENT-13：batch_rejected/batch_dispatch_rejected 是标记事件，不增批次状态枚举。"""
    assert "REJECTED" not in sm.BATCH_TRANSITIONS
    ok, why = sm.validate_transition("batch", "DRAFT", "REJECTED")
    assert not ok and "未知目标状态" in why
    with pytest.raises(sm.TransitionError):
        sm.assert_batch("DRAFT", "REJECTED")


def test_protocol_transitions() -> None:
    sm.assert_protocol("DRAFT", "REVIEW")
    sm.assert_protocol("REVIEW", "FROZEN")
    sm.assert_protocol("FROZEN", "SUPERSEDED")
    with pytest.raises(sm.TransitionError):
        sm.assert_protocol("DRAFT", "FROZEN")  # 跳过 REVIEW
