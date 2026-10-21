"""RunLedger 外部锚接线测试（批次/成本链收口 seal × external_seal）。

覆盖：seal_chain 收口、verify_external_seal 只认规范锚、head_and_length；
攻击：尾截断（内部 verify_chain 仍绿）、整链 genesis 重算、缺锚 fail-closed。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from abcr.common.external_seal import ANCHOR_STORE_ENV
from abcr.common.ledger_ref import GENESIS_HASH, RunLedger


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "anchors" / "seals.jsonl"
    monkeypatch.setenv(ANCHOR_STORE_ENV, str(p))
    return p


def _chain(root: Path, name: str, n: int, tag: str = "r") -> RunLedger:
    lg = RunLedger(root, name, shared=True)
    for i in range(n):
        lg.append("run_cost_actual", subject_id=f"{tag}{i}", amount=i * 1.5)
    return lg


def test_head_and_length(store: Path, tmp_path: Path) -> None:
    lg = RunLedger(tmp_path / "ledger", "costs")
    assert lg.head_and_length() == (GENESIS_HASH, 0)     # 空链明确形状
    lg.append("run_cost_actual", subject_id="r0")
    head, length = lg.head_and_length()
    assert length == 1 and head == lg.snapshot_digest() != GENESIS_HASH


def test_seal_chain_then_verify_ok(store: Path, tmp_path: Path) -> None:
    lg = _chain(tmp_path / "ledger", "costs", 3)
    rec = lg.seal_chain()
    assert rec["kind"] == "ledger_chain" and rec["subject_id"] == "costs"
    assert rec["length"] == 3
    assert rec["extra"]["chain_tail"] == lg.snapshot_digest()
    ok, reason = lg.verify_external_seal()
    assert ok is True and reason == "ok"


def test_no_seal_fail_closed(store: Path, tmp_path: Path) -> None:
    lg = _chain(tmp_path / "ledger", "batches", 2)
    assert lg.verify_chain() is True                     # 内部自洽
    ok, reason = lg.verify_external_seal()
    assert ok is False and "no external seal" in reason


def test_attack_tail_truncation_detected(store: Path, tmp_path: Path) -> None:
    """成本链尾截断：内部 verify_chain 仍 True，外部锚 length 失配 → False。

    这正是被审出的旧洞：截掉最后一条 run_cost_actual，verify_chain 照绿。
    """
    lg = _chain(tmp_path / "ledger", "costs", 4)
    lg.seal_chain()
    lines = lg.path.read_text(encoding="utf-8").splitlines()
    lg.path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

    lg2 = RunLedger(tmp_path / "ledger", "costs")
    assert lg2.verify_chain() is True                    # 旧弱语义：内部照样绿
    ok, reason = lg2.verify_external_seal()
    assert ok is False
    assert "length mismatch" in reason


def test_attack_full_rechain_from_genesis_detected(
        store: Path, tmp_path: Path) -> None:
    """整链从 genesis 重算洗账（自洽）→ 外部锚失配 → False。"""
    victim = _chain(tmp_path / "ledger", "costs", 4, tag="honest")
    victim.seal_chain()

    forged = _chain(tmp_path / "forge", "costs", 2, tag="washed")
    shutil.copyfile(forged.path, victim.path)
    lg2 = RunLedger(tmp_path / "ledger", "costs")
    assert lg2.verify_chain() is True                    # 自洽伪链
    ok, reason = lg2.verify_external_seal()
    assert ok is False and "length mismatch" in reason

    # 变体：同条目数、内容洗过 → digest 失配
    forged2 = _chain(tmp_path / "forge2", "costs", 4, tag="washed2")
    shutil.copyfile(forged2.path, victim.path)
    lg3 = RunLedger(tmp_path / "ledger", "costs")
    ok, reason = lg3.verify_external_seal()
    assert ok is False and "digest mismatch" in reason


def test_internal_tamper_reported_via_external_verify(
        store: Path, tmp_path: Path) -> None:
    """内部断链（改字段没重算哈希）→ verify_external_seal 也 False（先内后外）。"""
    import json
    lg = _chain(tmp_path / "ledger", "batches", 3)
    lg.seal_chain()
    lines = lg.path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1]); rec["subject_id"] = "tampered"
    lines[1] = json.dumps(rec, ensure_ascii=False)
    lg.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, reason = RunLedger(tmp_path / "ledger", "batches").verify_external_seal()
    assert ok is False and "internal chain invalid" in reason


def test_reseal_after_more_appends(store: Path, tmp_path: Path) -> None:
    """收口后又有合法追加 → 旧锚失配（提示需重封）；重封后恢复 True。"""
    lg = _chain(tmp_path / "ledger", "costs", 2)
    lg.seal_chain()
    lg.append("run_cost_actual", subject_id="r-late")
    ok, reason = lg.verify_external_seal()
    assert ok is False and "length mismatch" in reason
    lg.seal_chain()                                      # 重封（append-only，最后一条为准）
    assert lg.verify_external_seal()[0] is True
