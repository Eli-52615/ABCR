from __future__ import annotations

import os
from pathlib import Path

import pytest

from abcr.control import bridge
from abcr.control.bridge import HumanBridge, OperatorBridge
from abcr.control.contracts import Actor, ControlCommand
from abcr.control.store import ControlStore
from abcr.control.work_spool import STATES, STAGES, SpoolError, WorkSpool


def test_production_spool_open_never_creates_missing_layout(tmp_path: Path) -> None:
    root = tmp_path / "absent"
    with pytest.raises(SpoolError):
        WorkSpool(root, create=False)
    assert not root.exists()


def test_preprovisioned_spool_open_is_read_only(tmp_path: Path) -> None:
    for stage in STAGES:
        for state in STATES:
            (tmp_path / stage / state).mkdir(parents=True, exist_ok=True)
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    WorkSpool(tmp_path, create=False)
    assert sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*")) == before


def test_bridge_reconciles_crash_windows_without_cross_database_reads(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inbound = tmp_path / "human-to-operator"
    outbound = tmp_path / "operator-to-human"
    status = tmp_path / "operator-status" / "public-snapshot.json"
    inbound.mkdir(); outbound.mkdir(); status.parent.mkdir()
    uid = os.getuid()
    gid = os.getgid()
    monkeypatch.setattr(bridge, "_require_dir", lambda *args, **kwargs: None)
    human = HumanBridge(human_uid=uid, operator_uid=uid, human_gid=gid,
                        operator_gid=gid, root=tmp_path)
    operator = OperatorBridge(human_uid=uid, operator_uid=uid, human_gid=gid,
                              operator_gid=gid, root=tmp_path)
    human_store = ControlStore(tmp_path / "human.db")
    operator_store = ControlStore(tmp_path / "operator.db")
    actor = Actor("ou-owner", "tenant", "chat", "p2p")
    command = ControlCommand("CMD-1", "MSG-1", actor, "status", {})

    human.export_command(command)
    human.export_command(command)  # crash/retry is byte-identical
    assert operator.import_commands(operator_store) == 1
    assert operator.import_commands(operator_store) == 0
    assert operator_store.claim_action(command.effect_id, "operator")
    operator_store.finish_action(command.effect_id, worker_id="operator", state="succeeded",
                                 result={"code": "ok"})
    operator.export_results_and_status(operator_store)
    operator.export_results_and_status(operator_store)
    assert human.import_results(human_store, "chat") == 1
    assert human.import_results(human_store, "chat") == 0


def test_launchd_socket_activation_contract_is_frozen() -> None:
    text = Path("ops/launchd/com.abcr.seal-broker.plist").read_text(encoding="utf-8")
    assert "<key>Listener</key>" in text
    assert "<integer>432</integer>" in text  # root:abcr-broker-clients 0660
    assert "Installer MUST add integer SockPathGroup" in text
    assert "<key>SockPathGroup</key>" not in text
    source = Path("src/abcr/control/seal_broker.py").read_text(encoding="utf-8")
    assert "launch_activate_socket" in source
    assert "if launched:" in source


def test_bridge_canonical_path_is_frozen() -> None:
    assert bridge.BRIDGE_ROOT == Path("/Library/Application Support/ABCR-Bridge")
