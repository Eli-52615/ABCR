from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from abcr.control.contracts import ContractError, canonical_json, sha256
from abcr.control.seal_broker import SealBroker
from abcr.control.worktree import scan_tree, tree_hash


ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str, name: str):
    path = ROOT / relative
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def test_genesis_cli_is_human_root_only_and_never_mutates_on_this_host():
    result = subprocess.run(
        [os.environ.get("PYTHON", "python3"), str(ROOT / "scripts/bootstrap_abcr_genesis.py"),
         "--genesis-reviewed", "a" * 64],
        text=True, capture_output=True, check=False)
    assert result.returncode == 78
    assert "--human-required" in result.stderr


def test_normal_installer_rejects_pending_genesis_receipt(tmp_path, monkeypatch):
    installer = _load("scripts/install_abcr_runtime.py", "abcr_installer_genesis_test")
    receipts = tmp_path / "receipts"; receipts.mkdir()
    monkeypatch.setattr(installer, "RECEIPT_ROOT", receipts)
    monkeypatch.setattr(installer, "read_json", lambda path, **kwargs: json.loads(path.read_text()))
    core = {"operation": "seal_release", "nonce": "n", "tree_hash": "a" * 64,
            "object_id": "REL-" + "b" * 64}
    receipt_id = hashlib.sha256(_canonical(core)).hexdigest()
    receipt = {**core, "receipt_id": receipt_id, "sealed_tree_hash": "c" * 64,
               "sealed_path": "/fixed", "created_at": "now",
               "genesis_pending": {"authority_id": "d" * 64,
                                   "reviewed_commit": "e" * 40}}
    (receipts / f"{receipt_id}.json").write_text(json.dumps(receipt))
    monkeypatch.setattr(installer, "require_real_dir", lambda *args, **kwargs: None)
    with pytest.raises(installer.InstallBlocked, match="pending genesis"):
        installer.verify_receipt(receipt_id)


def test_pending_receipt_requires_lkg_broker_before_normalization(tmp_path):
    genesis = _load("scripts/bootstrap_abcr_genesis.py", "abcr_genesis_transition_test")
    owner = os.getuid(); group = os.getgid()
    receipt_root = tmp_path / "receipts"; receipt_root.mkdir()
    authority = {"expected_receipt_id": "a" * 64, "authority_id": "b" * 64,
                 "reviewed_commit": "c" * 40}
    receipt = {"receipt_id": "a" * 64, "operation": "seal_release", "nonce": "n",
               "object_id": "REL-" + "d" * 64, "tree_hash": "e" * 64,
               "sealed_tree_hash": "f" * 64, "sealed_path": "/sealed",
               "created_at": "now",
               "genesis_pending": {"authority_id": "b" * 64,
                                   "reviewed_commit": "c" * 40}}
    path = receipt_root / ("a" * 64 + ".json")
    path.write_bytes(_canonical(receipt) + b"\n"); path.chmod(0o440)

    with pytest.raises(genesis.GenesisBlocked, match="did not confirm"):
        genesis.normalize_broker_receipt(
            authority, {**receipt, "sealed_tree_hash": "0" * 64},
            receipt_root=receipt_root, owner_uid=owner, release_gid=group)
    assert "genesis_pending" in json.loads(path.read_text())

    normal = genesis.normalize_broker_receipt(
        authority, receipt, receipt_root=receipt_root,
        owner_uid=owner, release_gid=group)
    assert set(normal) == genesis.RECEIPT_FIELDS
    assert "genesis_pending" not in json.loads(path.read_text())


def test_authority_rejects_arbitrary_checkout_path(tmp_path, monkeypatch):
    genesis = _load("scripts/bootstrap_abcr_genesis.py", "abcr_genesis_path_test")
    monkeypatch.setattr(genesis, "REVIEW_ROOT", tmp_path / "fixed-review-root")
    arbitrary = tmp_path / "ordinary-checkout"; arbitrary.mkdir()
    with pytest.raises(genesis.GenesisBlocked):
        genesis.build_authority_statement(arbitrary, "a" * 40, human_approved=False)


def test_policy_declares_exact_finite_tcb_and_order():
    policy = json.loads((ROOT / "ops/install/genesis-authority-v1.json").read_text())
    assert policy["ordinary_checkout_installable"] is False
    assert policy["pending_receipt_installable"] is False
    assert policy["human_required"] is True and policy["root_required"] is True
    assert policy["finite_tcb_fields"] == [
        "genesis_script", "stable_selector", "runtime_installer", "launcher",
        "python", "broker_module", "broker_payload_tree_hash"]
    assert policy["ordered_phases"].index("establish-selector-and-seal-broker-lkg") < \
        policy["ordered_phases"].index("lkg-broker-confirms-same-release") < \
        policy["ordered_phases"].index("run-normal-receipt-gated-installer")


def test_prepare_genesis_roots_creates_missing_libexec_leaf(tmp_path):
    genesis = _load("scripts/bootstrap_abcr_genesis.py", "abcr_genesis_roots_test")
    owner = os.getuid(); group = os.getgid()
    users = tmp_path / "Users"; users.mkdir()
    home = users / "superagent"; home.mkdir()
    library = tmp_path / "Library"; library.mkdir()
    support = library / "Application Support"; support.mkdir()
    trust = support / "ABCR-Trust"; trust.mkdir()
    local = tmp_path / "usr/local"; local.mkdir(parents=True)

    genesis.prepare_genesis_roots(
        release_root=home / ".abcr/releases",
        receipt_root=support / "ABCR-Attest/release-receipts",
        component_root=support / "ABCR-Bootstrap/components",
        selector_path=local / "libexec/abcr-bootstrap-selector",
        completion_path=trust / "genesis-completed-v1.json",
        owner_uid=owner, release_gid=group, wheel_gid=group)

    assert (local / "libexec").is_dir()
    assert stat.S_IMODE((local / "libexec").stat().st_mode) == 0o755


def test_lkg_broker_replay_rechecks_release_mode_policy(tmp_path):
    owner = os.getuid(); group = os.getgid()
    source_parent = tmp_path / "reviewed"; source_parent.mkdir()
    release_id = "REL-" + "a" * 64
    source = source_parent / release_id; source.mkdir()
    (source / "x").write_text("reviewed")
    source_hash = tree_hash(scan_tree(source))
    release_root = tmp_path / "releases"; release_root.mkdir()
    final = release_root / release_id
    shutil.copytree(source, final)
    final.chmod(0o550); (final / "x").chmod(0o440)
    receipt_root = tmp_path / "receipts"; receipt_root.mkdir()
    nonce = "genesis"
    core = {"operation": "seal_release", "nonce": nonce,
            "tree_hash": source_hash, "object_id": release_id}
    receipt_id = sha256(core)
    # Attacker repairs the self-reported sealed hash after weakening a mode.
    (final / "x").chmod(0o640)
    receipt = {**core, "receipt_id": receipt_id,
               "sealed_tree_hash": tree_hash(scan_tree(final)),
               "sealed_path": str(final), "created_at": "now",
               "genesis_pending": {"authority_id": "b" * 64,
                                   "reviewed_commit": "c" * 40}}
    receipt_path = receipt_root / f"{receipt_id}.json"
    receipt_path.write_bytes(canonical_json(receipt) + b"\n"); receipt_path.chmod(0o440)
    broker = SealBroker(
        {"seal_release": release_root}, receipt_root,
        source_roots={"seal_release": source_parent},
        operation_policies={"seal_release": {
            "owner_uid": owner, "group_gid": group, "directory_mode": 0o550,
            "file_mode": 0o440, "executable_file_mode": 0o550}},
        receipt_owner_uid=owner, receipt_group_gid=group)
    with pytest.raises(ContractError) as exc:
        broker.seal_tree("seal_release", source, nonce=nonce,
                         expected_tree_hash=source_hash, object_id=release_id)
    assert exc.value.code == "sealed_tree_policy_drift"
