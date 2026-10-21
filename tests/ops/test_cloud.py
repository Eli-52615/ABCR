"""tests/ops/test_cloud —— 云实例生命周期账本登记 + 链校验（B2-8）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from abcr.common.ledger_ref import RunLedger
from abcr.ops import cloud


def test_full_lifecycle_events(tmp_path: Path):
    ld = tmp_path / "ledger"
    cloud.register("autodl-1", "autodl", "RTX4090-24G", 2.5, "B-x-0001", ledger_dir=ld)
    cloud.start("autodl-1", ledger_dir=ld)
    stopped, cost = cloud.stop("autodl-1", 18.6, "ssh拒连+控制台已停+账单读数", ledger_dir=ld)

    ins = RunLedger(ld, "instances")
    events = [e["event"] for e in ins.events()]
    assert events == ["instance_registered", "instance_started", "instance_stopped"]
    ins.verify_chain()

    # instance_stopped payload
    assert stopped["subject_id"] == "autodl-1"
    assert stopped["amount_cny"] == 18.6
    assert "verified" in stopped

    # costs 链 run_cost_actual（键名 AMENDMENT-9：subject_id/amount_cny/basis/batch_id/instance_id）
    costs = RunLedger(ld, "costs")
    ca = costs.events(event="run_cost_actual")
    assert len(ca) == 1
    assert ca[0]["subject_id"] == "autodl-1"
    assert ca[0]["amount_cny"] == 18.6
    assert ca[0]["basis"] == cloud.COST_BASIS
    assert ca[0]["instance_id"] == "autodl-1"
    costs.verify_chain()


def test_registered_fields(tmp_path: Path):
    ld = tmp_path / "ledger"
    cloud.register("autodl-2", "autodl", "A100-40G", 6.0, "B-y-0002", ledger_dir=ld)
    reg = RunLedger(ld, "instances").events(event="instance_registered")[0]
    assert reg["vendor"] == "autodl"
    assert reg["spec"] == "A100-40G"
    assert reg["price_cny_per_h"] == 6.0
    assert reg["batch_id"] == "B-y-0002"


def test_start_copies_registered_keys(tmp_path: Path):
    ld = tmp_path / "ledger"
    cloud.register("autodl-3", "autodl", "RTX4090-24G", 2.5, "B-z-0003", ledger_dir=ld)
    started = cloud.start("autodl-3", ledger_dir=ld)
    for k in ("vendor", "spec", "price_cny_per_h", "batch_id"):
        assert k in started


def test_start_without_register_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        cloud.start("ghost", ledger_dir=tmp_path / "ledger")


def test_idle_sim_actor_drill(tmp_path: Path):
    ld = tmp_path / "ledger"
    rec = cloud.idle_sim("autodl-4", ledger_dir=ld)
    assert rec["event"] == "instance_idle_alert"
    assert rec["actor"] == "drill"   # AMENDMENT-17：演练账目可识别
    RunLedger(ld, "instances").verify_chain()
