from __future__ import annotations

import os
from pathlib import Path

import pytest

from abcr.control.attestation import DOMAIN_VERIFICATION, sign_attestation
from abcr.control.black_box_oracle import SigningIdentity
from abcr.control.canary_controller import run_canary
from abcr.control.contracts import ContractError, sha256
from abcr.control.ed25519 import generate_keypair
from abcr.control.release import activate_release, prepare_release, stage_release
from abcr.control.seal_broker import SealBroker
from abcr.control.verifier import VerificationAttestation
from abcr.control.worktree import export_plain_tree, reconstruct_diff, scan_tree, tree_hash
from tests.control.release_fixture_support import add_bootstrap_payload

SANDBOXED = "sandbox-exec:" + "e" * 64
ROOT = Path(__file__).resolve().parents[2]


def make_tree(path, value="old"):
    (path / "src").mkdir(parents=True); (path / "src" / "x.py").write_text(value)


def add_release_material(path):
    python = path / "env/bin/python"; python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 99\n"); python.chmod(0o500)
    module = path / "env/lib/python3.12/site-packages/abcr/control/panel.py"
    module.parent.mkdir(parents=True)
    module.write_text("def main():\n    return 0\n"); module.chmod(0o400)
    (path / "requirements.lock").write_text("fixture==1 --hash=sha256:" + "a" * 64 + "\n")
    topology = path / "configs/control/service-topology-v1.json"
    topology.parent.mkdir(parents=True)
    topology.write_bytes((ROOT / "configs/control/service-topology-v1.json").read_bytes())
    add_bootstrap_payload(path)


def identity(tmp_path) -> SigningIdentity:
    keys = tmp_path / "keys"; keys.mkdir(parents=True, exist_ok=True)
    private, public = keys / "verifier.key", keys / "verifier.pub"
    generate_keypair(private, public)
    return SigningIdentity(private, public)


def attestation(candidate_hash, signer, *, verdict="PASS", isolation=SANDBOXED):
    core = dict(mission_id="m", fencing_token=1, base_tree_hash="b" * 64,
                candidate_tree_hash=candidate_hash, profile_hash="p" * 64,
                oracle_set_hash="o" * 64, changed_paths=["src/x.py"],
                verdict=verdict, verified_at="now", isolation=isolation)
    sealed = sign_attestation(private_key=signer.private_key, public_key=signer.public_key,
                              domain=DOMAIN_VERIFICATION, core=core)
    return VerificationAttestation(**{**core, "changed_paths": ("src/x.py",)},
                                   attestation_hash=sha256(core), sealed=sealed)


def test_plain_tree_diff_and_symlink_reject(tmp_path):
    base = tmp_path / "base"; candidate = tmp_path / "candidate"; make_tree(base)
    export_plain_tree(base, candidate); (candidate / "src" / "x.py").write_text("new")
    diff = reconstruct_diff(base, candidate, allowed_globs=("src/**",))
    assert diff["changed_paths"] == ["src/x.py"]
    (candidate / "src" / "link").symlink_to(candidate / "src" / "x.py")
    with pytest.raises(ContractError): scan_tree(candidate)
    (candidate / "src" / "link").unlink()
    (candidate / "dir-target").mkdir(); (candidate / "src" / "dir-link").symlink_to(candidate / "dir-target")
    with pytest.raises(ContractError): scan_tree(candidate)
    (candidate / "src" / "dir-link").unlink()
    (candidate / ".git").write_text("gitdir: escape")
    with pytest.raises(ContractError): scan_tree(candidate)


def test_seal_canary_activate_and_cas_rollback_guard(tmp_path):
    candidate = tmp_path / "candidate"; make_tree(candidate, "new"); add_release_material(candidate)
    signer = identity(tmp_path)
    c_hash = tree_hash(scan_tree(candidate)); verify = attestation(c_hash, signer)
    manifest = prepare_release(candidate, verify, verifier_public_key=signer.public_key)
    staging_root = tmp_path / "staging"
    staged, staged_hash = stage_release(candidate, staging_root, manifest,
                                        service_payloads={"abcr.control.panel": {}})
    releases = tmp_path / "releases"; receipts = tmp_path / "receipts"
    active = tmp_path / "active.json"
    broker = SealBroker({"seal_release": releases}, receipts,
                        source_roots={"seal_release": staging_root}, active_path=active)
    receipt = broker.seal_tree("seal_release", staged, nonce="n1", expected_tree_hash=staged_hash,
                               object_id=manifest.release_id)
    canary = run_canary(manifest.release_id, "v1", lambda: ("v1", True, "ok"))
    record = activate_release(broker, active_path=active, old_release=None, manifest=manifest,
                              seal_receipt=receipt, canary=canary)
    assert record["release_id"] == manifest.release_id
    with pytest.raises(ContractError):
        broker.activate(active, expected_old="wrong", new_release="other", release_receipt=receipt,
                        verification_hash="v", canary_hash="c")
    outside = tmp_path / "outside"
    outside.mkdir(); (outside / "x").write_text("x")
    with pytest.raises(ContractError):
        broker.seal_tree("seal_release", outside, nonce="n2",
                         expected_tree_hash=tree_hash(scan_tree(outside)), object_id="REL-outside")
