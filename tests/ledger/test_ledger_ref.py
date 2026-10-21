"""tests/ledger/test_ledger_ref.py —— A1-1 防回归测试（8 用例，覆盖 §A1-1 补测用例）。"""
from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from abcr.common.ledger_ref import GENESIS_HASH, LedgerTampered, RunLedger


def _fresh(tmp_path: Path, shared: bool = True) -> RunLedger:
    return RunLedger(tmp_path, "runs_index", shared=shared)


def test_append_verify_snapshot(tmp_path: Path) -> None:
    """用例1：空链 append 3 条 → verify True，snapshot == 第3条 entry_hash。"""
    lg = _fresh(tmp_path)
    recs = [lg.append("run_registered", subject_id="r1"),
            lg.append("run_queued", subject_id="r1"),
            lg.append("run_started", subject_id="r1")]
    assert lg.verify_chain() is True
    assert lg.snapshot_digest() == recs[2]["entry_hash"]
    assert recs[0]["prev_hash"] == GENESIS_HASH


def test_tamper_field_entry_hash_mismatch(tmp_path: Path) -> None:
    """用例2：手改第2条字段 → raise，index==1，reason 含 entry_hash mismatch。"""
    lg = _fresh(tmp_path)
    for i in range(3):
        lg.append("run_queued", subject_id=f"r{i}")
    lines = lg.path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1])
    rec["subject_id"] = "tampered"
    lines[1] = json.dumps(rec, ensure_ascii=False)
    lg.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(LedgerTampered) as ei:
        lg.verify_chain()
    assert ei.value.index == 1
    assert "entry_hash mismatch" in ei.value.reason


def test_delete_record_prev_hash_break(tmp_path: Path) -> None:
    """用例3：删第2条 → raise，reason 含 prev_hash break。"""
    lg = _fresh(tmp_path)
    for i in range(3):
        lg.append("run_queued", subject_id=f"r{i}")
    lines = lg.path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    lg.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(LedgerTampered) as ei:
        lg.verify_chain()
    assert "prev_hash break" in ei.value.reason


def test_truncate_tail_digest_drift(tmp_path: Path) -> None:
    """用例4：截断最后一条 → verify_against_digest(旧链尾) raise，index==-1。"""
    lg = _fresh(tmp_path)
    for i in range(3):
        lg.append("run_queued", subject_id=f"r{i}")
    old_tail = lg.snapshot_digest()
    lines = lg.path.read_text(encoding="utf-8").splitlines()
    lg.path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(LedgerTampered) as ei:
        lg.verify_against_digest(old_tail)
    assert ei.value.index == -1


def test_insert_forged_record(tmp_path: Path) -> None:
    """用例5：插入伪造条（整体重排）→ raise。"""
    lg = _fresh(tmp_path)
    r0 = lg.append("run_registered", subject_id="r0")
    lg.append("run_queued", subject_id="r1")
    lines = lg.path.read_text(encoding="utf-8").splitlines()
    forged = {"ts": r0["ts"], "run_id": "runs_index", "event": "run_started",
              "subject_id": "forged", "prev_hash": r0["entry_hash"],
              "entry_hash": "deadbeef" * 8}
    lines.insert(1, json.dumps(forged, ensure_ascii=False))
    lg.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(LedgerTampered):
        lg.verify_chain()


def test_reserved_payload_key_guard(tmp_path: Path) -> None:
    """用例6：payload 用保留键 run_id → 显式 ValueError（维护性守卫）。"""
    lg = _fresh(tmp_path)
    for reserved in ("run_id", "ts", "prev_hash", "entry_hash"):
        with pytest.raises(ValueError):
            lg.append("run_started", **{reserved: "x"})


def test_reopen_process_chain_intact(tmp_path: Path) -> None:
    """用例7：重开实例续 append → 链不断。"""
    lg1 = _fresh(tmp_path)
    lg1.append("run_registered", subject_id="r0")
    lg1.append("run_queued", subject_id="r0")
    lg2 = _fresh(tmp_path)                 # 新实例（模拟重开进程）
    lg2.append("run_started", subject_id="r0")
    assert lg2.verify_chain() is True
    assert len(lg2.events()) == 3


def _worker(root_str: str, tag: str, n: int) -> None:
    lg = RunLedger(Path(root_str), "runs_index", shared=True)
    for i in range(n):
        lg.append("step_progress", subject_id=tag, steps_done=i, items_done=i)


def test_concurrent_shared_append_no_fork(tmp_path: Path) -> None:
    """用例8：两进程交错 append 各 20 条到同一全局链 → verify True、行数 40、无分叉。"""
    # fork：子进程继承内存（规避 spawn 重导入测试模块的 PYTHONPATH 脆弱）；
    # flock 是进程级锁，fork 才能真正验证跨进程写互斥（AMENDMENT-15）。
    ctx = mp.get_context("fork")
    p1 = ctx.Process(target=_worker, args=(str(tmp_path), "A", 20))
    p2 = ctx.Process(target=_worker, args=(str(tmp_path), "B", 20))
    p1.start(); p2.start()
    p1.join(); p2.join()
    assert p1.exitcode == 0 and p2.exitcode == 0
    lg = RunLedger(tmp_path, "runs_index", shared=True)
    assert lg.verify_chain() is True
    assert len(lg.events()) == 40
