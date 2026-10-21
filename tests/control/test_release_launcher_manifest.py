"""Real producer -> broker -> active pointer -> stable launcher contract."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path

from abcr.control.attestation import DOMAIN_VERIFICATION, sign_attestation
from abcr.control.black_box_oracle import SigningIdentity
from abcr.control.canary_controller import run_canary
from abcr.control.contracts import sha256
from abcr.control.ed25519 import generate_keypair
from abcr.control.release import activate_release, prepare_release, stage_release
from abcr.control.seal_broker import SealBroker
from abcr.control.verifier import VerificationAttestation
from abcr.control.worktree import scan_tree, tree_hash

ROOT = Path(__file__).resolve().parents[2]
SANDBOXED = "sandbox-exec:" + "e" * 64


def load_launcher():
    path = ROOT / "scripts/abcr-launch"
    loader = importlib.machinery.SourceFileLoader("abcr_release_launcher", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _signer(tmp_path: Path) -> SigningIdentity:
    private = tmp_path / "verifier.key"; public = tmp_path / "verifier.pub"
    generate_keypair(private, public)
    return SigningIdentity(private, public)


def _candidate(tmp_path: Path) -> Path:
    root = tmp_path / "candidate"
    python = root / "env/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 99\n"); python.chmod(0o500)
    module = root / "env/lib/python3.12/site-packages/abcr/control/panel.py"
    module.parent.mkdir(parents=True)
    module.write_text("def main():\n    return 0\n"); module.chmod(0o400)
    (root / "requirements.lock").write_text("fixture==1 --hash=sha256:" + "a" * 64 + "\n")
    topology = root / "configs/control/service-topology-v1.json"
    topology.parent.mkdir(parents=True)
    topology.write_bytes((ROOT / "configs/control/service-topology-v1.json").read_bytes())
    return root


def _attestation(candidate: Path, signer: SigningIdentity) -> VerificationAttestation:
    candidate_hash = tree_hash(scan_tree(candidate))
    core = dict(mission_id="m", fencing_token=1, base_tree_hash="b" * 64,
                candidate_tree_hash=candidate_hash, profile_hash="p" * 64,
                oracle_set_hash="o" * 64, changed_paths=["src/x.py"], verdict="PASS",
                verified_at="now", isolation=SANDBOXED)
    sealed = sign_attestation(private_key=signer.private_key, public_key=signer.public_key,
                              domain=DOMAIN_VERIFICATION, core=core)
    return VerificationAttestation(**{**core, "changed_paths": ("src/x.py",)},
                                   attestation_hash=sha256(core), sealed=sealed)


def test_sealed_release_is_accepted_by_stable_launcher_doctor(tmp_path, capsys):
    launcher = load_launcher()
    signer = _signer(tmp_path)
    candidate = _candidate(tmp_path)
    manifest = prepare_release(candidate, _attestation(candidate, signer),
                               verifier_public_key=signer.public_key)
    staging = tmp_path / "staging"
    staged, staged_hash = stage_release(candidate, staging, manifest,
                                        service_payloads={"com.abcr.panel": {}})
    releases = tmp_path / "releases"; receipts = tmp_path / "receipts"
    active = tmp_path / "active.json"
    broker = SealBroker({"seal_release": releases}, receipts,
                        source_roots={"seal_release": staging}, active_path=active)
    receipt = broker.seal_tree("seal_release", staged, nonce="n",
                               expected_tree_hash=staged_hash, object_id=manifest.release_id)
    canary = run_canary(manifest.release_id, "v1", lambda: ("v1", True, "ok"))
    activate_release(broker, active_path=active, old_release=None, manifest=manifest,
                     seal_receipt=receipt, canary=canary)

    called = []
    assert launcher.run(["com.abcr.panel", "--doctor"], active_path=active,
                        release_root=releases, receipt_root=receipts,
                        owner_uid=os.getuid(), execve=lambda *args: called.append(args)) == 0
    assert called == []
    assert '"ok": true' in capsys.readouterr().out
