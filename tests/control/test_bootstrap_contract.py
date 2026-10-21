from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_SHA = "40fd5fb21ff33d7da84648562c6dc12d68f15444dfea60379132af820510d0d1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_acl_install_manifest_is_bound_to_canonical_contract_bytes():
    install = json.loads((ROOT / "ops/acl/acl-manifest-v1.json").read_text())
    assert install["authority_sha256"] == AUTHORITY_SHA
    for name in ("path_ownership", "acl"):
        item = install["contracts"][name]
        path = ROOT / item["path"]
        assert path.is_file() and not path.is_symlink()
        assert _sha(path) == item["sha256"]
        assert json.loads(path.read_text())["authority_sha256"] == AUTHORITY_SHA


def test_acl_contract_check_is_read_only_and_honest():
    before = {path: path.stat().st_mtime_ns for path in (
        ROOT / "ops/acl/acl-manifest-v1.json",
        ROOT / "configs/control/path-ownership-v1.json",
        ROOT / "configs/control/acl-manifest-v1.json",
        ROOT / "configs/control/work-stages-v1.json",
    )}
    result = subprocess.run(
        [str(ROOT / "ops/acl/install-acls.sh"), "--check"],
        text=True, capture_output=True, check=False)
    assert result.returncode == 0
    assert "structurally valid and hash-bound" in result.stdout
    assert "live per-UID ACL probes were not requested" in result.stdout
    assert {path: path.stat().st_mtime_ns for path in before} == before


def test_account_bootstrap_requires_exact_reviewed_authority_for_mutation():
    result = subprocess.run(
        [str(ROOT / "scripts/bootstrap_abcr_accounts.sh"),
         "--install-reviewed", "0" * 64],
        text=True, capture_output=True, check=False)
    assert result.returncode == 64
    assert AUTHORITY_SHA in result.stderr


def test_bootstrap_manifest_never_installs_from_source_checkout():
    manifest = json.loads((ROOT / "ops/install/bootstrap-v1.json").read_text())
    assert manifest["authority_sha256"] == AUTHORITY_SHA
    assert manifest["gates"] == {
        "source_checkout_is_installable": False,
        "sealed_release_required": True,
        "genesis_human_root_ceremony_only": True,
        "reviewed_authority_sha_required": True,
        "launcher_doctor_before_launchctl": True,
        "semantic_doctor_after_launchctl": True,
        "automatic_live_enable": False,
    }
    assert manifest["dual_slot_components"] == [
        "launcher", "seal-broker", "test-controller"]
    assert manifest["stable_selector"] == "/usr/local/libexec/abcr-bootstrap-selector"
    assert manifest["stable_selector_sha256"] == _sha(
        ROOT / "scripts/abcr-bootstrap-selector")
    assert manifest["genesis"] == {
        "policy": "ops/install/genesis-authority-v1.json",
        "policy_sha256": _sha(ROOT / "ops/install/genesis-authority-v1.json"),
        "authority_path": "/Library/Application Support/ABCR-Trust/genesis-authority-v1.json",
        "human_required": True,
        "root_required": True,
        "pending_receipt_installable": False,
    }
    assert "scripts/bootstrap_abcr_genesis.py" in manifest["root_tcb"]


def test_runtime_installer_never_loads_or_starts_launchd_jobs():
    source = (ROOT / "scripts/install_abcr_runtime.py").read_text(encoding="utf-8")
    assert "launchctl" not in source
    assert '"launchd_loaded": False' in source
    assert '"services_started": False' in source


def test_builder_input_group_and_release_read_contract_are_not_self_contradictory():
    bootstrap = json.loads((ROOT / "ops/install/bootstrap-v1.json").read_text())
    assert "abcr-builder-input" in bootstrap["role_groups"]
    accounts = (ROOT / "scripts/bootstrap_abcr_accounts.sh").read_text()
    assert 'ensure_role_group abcr-builder-input' in accounts
    assert '"abcr-operator abcr-builder"' in accounts

    ownership = json.loads(
        (ROOT / "configs/control/path-ownership-v1.json").read_text())
    release = next(item for item in ownership["roots"]
                   if item["path"] == "/Users/superagent/.abcr/releases")
    # The outer service principals need their immutable interpreter/module.
    # Only the untrusted child is denied the whole root.
    assert {"abcr-builder", "abcr-verifier"}.issubset(release["readers"])
    assert not set(release["readers"]) & set(release["must_deny"])
    assert release["must_deny"] == ["abcr-candidate"]
    assert "mission_codex" in release["untrusted_child_boundary"]

    build = next(item for item in ownership["roots"]
                 if item["path"] == "/Users/superagent/.abcr-build")
    mission_input = build["children"]["mission-inputs"]
    assert mission_input["owner"] == "abcr-operator"
    assert mission_input["group"] == "abcr-builder-input"
    assert mission_input["writers"] == ["abcr-operator"]
    assert mission_input["readers"] == ["abcr-operator", "abcr-builder"]
