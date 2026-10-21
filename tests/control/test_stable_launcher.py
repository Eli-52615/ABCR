from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LABEL = "com.abcr.panel"
MODULE = "abcr.control.panel"


def load_launcher():
    path = ROOT / "scripts/abcr-launch"
    loader = importlib.machinery.SourceFileLoader("abcr_stable_launcher", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _write(path: Path, raw: bytes, mode: int) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)
    import hashlib
    return {"path": "", "mode": mode, "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def make_release(tmp_path: Path):
    launcher = load_launcher()
    tmp_path.mkdir(parents=True, exist_ok=True)
    releases = tmp_path / "releases"
    receipts = tmp_path / "receipts"
    releases.mkdir(mode=0o750)
    receipts.mkdir(mode=0o750)
    staging_id = "REL-pending"
    release = releases / staging_id
    release.mkdir(mode=0o750)

    sources = {
        "env/bin/python": (b"#!/bin/sh\nexit 99\n", 0o500),
        "env/lib/python3.12/site-packages/abcr/control/panel.py": (
            b"raise RuntimeError('doctor must not import me')\n\ndef main():\n    return 0\n", 0o400),
        "requirements.lock": (b"example==1.0 --hash=sha256:" + b"a" * 64 + b"\n", 0o400),
    }
    declared = []
    for rel, (raw, original_mode) in sources.items():
        sealed_mode = 0o550 if original_mode & 0o111 else 0o440
        entry = _write(release / rel, raw, sealed_mode)
        entry["path"] = rel
        entry["mode"] = original_mode
        declared.append(entry)
    declared.sort(key=lambda item: item["path"])
    by_path = {item["path"]: item for item in declared}
    runtime = [item for item in declared if item["path"].startswith("env/")]
    tree_hash = launcher._sha256(declared)
    runtime_digest = launcher._sha256(runtime)
    lock_hash = by_path["requirements.lock"]["sha256"]
    payload_files = sorted(by_path)
    payload = {
        "label": LABEL,
        "module": MODULE,
        "entrypoint": "main",
        "python_relpath": "env/bin/python",
        "python_sha256": by_path["env/bin/python"]["sha256"],
        "module_relpath": "env/lib/python3.12/site-packages/abcr/control/panel.py",
        "module_sha256": by_path["env/lib/python3.12/site-packages/abcr/control/panel.py"]["sha256"],
        "lock_relpath": "requirements.lock",
        "payload_files": payload_files,
        "payload_tree_hash": launcher._sha256(declared),
    }
    core = {"tree_hash": tree_hash, "runtime_digest": runtime_digest,
            "lock_hash": lock_hash, "service_config_hash": launcher.frozen_topology_hash(),
            "verification_hash": "b" * 64}
    release_id = "REL-" + launcher._sha256(core)
    final_release = releases / release_id
    release.rename(final_release)
    release = final_release
    manifest = {"release_id": release_id, **core, "tree_entries": declared,
                "service_payloads": {MODULE: payload}}
    (release / "release-manifest.json").write_bytes(_canonical(manifest) + b"\n")
    (release / "release-manifest.json").chmod(0o440)

    sealed_hash = launcher._sha256(launcher._scan_tree(release, owner_uid=os.getuid()))
    receipt_core = {"operation": "seal_release", "nonce": "fixture",
                    "tree_hash": "c" * 64, "object_id": release_id}
    receipt_id = launcher._sha256(receipt_core)
    receipt = {"receipt_id": receipt_id, **receipt_core,
               "sealed_tree_hash": sealed_hash, "sealed_path": str(release),
               "created_at": "fixture"}
    (receipts / f"{receipt_id}.json").write_bytes(_canonical(receipt) + b"\n")
    (receipts / f"{receipt_id}.json").chmod(0o440)
    active = tmp_path / "active.json"
    active.write_bytes(_canonical({"release_id": release_id,
                                   "release_receipt_id": receipt_id,
                                   "verification_hash": "b" * 64,
                                   "canary_hash": "d" * 64}) + b"\n")
    active.chmod(0o444)
    return launcher, active, releases, receipts, release, manifest


def invoke(rig, *args, execve=None):
    launcher, active, releases, receipts, _, _ = rig
    return launcher.run(list(args), active_path=active, release_root=releases,
                        receipt_root=receipts, owner_uid=os.getuid(),
                        execve=execve or os.execve)


def test_doctor_validates_every_binding_without_import_or_exec(tmp_path, capsys):
    rig = make_release(tmp_path)
    called = []
    assert invoke(rig, LABEL, "--doctor", execve=lambda *args: called.append(args)) == 0
    assert called == []
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert (result["service_label"], result["module"]) == (LABEL, MODULE)
    assert result["release_id"].startswith("REL-")


def test_launcher_frozen_topology_matches_the_reviewed_config():
    launcher = load_launcher()
    topology = json.loads((ROOT / "configs/control/service-topology-v1.json").read_text())
    assert launcher.FROZEN_TOPOLOGY == topology
    assert launcher.DEFAULT_RECEIPT_ROOT == Path(
        "/Library/Application Support/ABCR-Attest/release-receipts")


def test_exec_is_isolated_and_caller_environment_cannot_redirect_roots(tmp_path, monkeypatch):
    rig = make_release(tmp_path)
    captured = []
    monkeypatch.setenv("ABCR_ACTIVE_FILE", "/tmp/attacker-active")
    monkeypatch.setenv("ABCR_RELEASE_ROOT", "/tmp/attacker-releases")
    monkeypatch.setenv("PYTHONPATH", "/tmp/attacker-pythonpath")
    assert invoke(rig, LABEL, execve=lambda *args: captured.append(args)) == 70
    program, argv, env = captured[0]
    assert argv == [program, "-I", "-m", MODULE]
    assert "PYTHONPATH" not in env and "ABCR_ACTIVE_FILE" not in env
    assert env["PATH"] == "/usr/bin:/bin"


def test_unknown_label_cannot_select_an_arbitrary_module(tmp_path, capsys):
    rig = make_release(tmp_path)
    assert invoke(rig, "abcr.control.panel", "--doctor") == 78
    assert "unknown service label" in capsys.readouterr().err


@pytest.mark.parametrize("target", ["active", "manifest", "python"])
def test_nofollow_rejects_symlinked_trust_objects(tmp_path, target):
    rig = make_release(tmp_path)
    _, active, _, _, release, manifest = rig
    if target == "active":
        real = tmp_path / "real-active.json"
        active.rename(real)
        active.symlink_to(real)
    elif target == "manifest":
        path = release / "release-manifest.json"
        real = release / "real-manifest.json"
        path.rename(real)
        path.symlink_to(real)
    else:
        path = release / manifest["service_payloads"][MODULE]["python_relpath"]
        real = path.with_name("python-real")
        path.rename(real)
        path.symlink_to(real)
    assert invoke(rig, LABEL, "--doctor") == 78


def test_release_directory_symlink_is_rejected(tmp_path):
    rig = make_release(tmp_path)
    _, active, releases, _, release, _ = rig
    real = tmp_path / "real-release"
    release.rename(real)
    release.symlink_to(real, target_is_directory=True)
    assert invoke(rig, LABEL, "--doctor") == 78


def test_wrong_owner_or_writable_mode_or_hardlink_fails_closed(tmp_path):
    rig = make_release(tmp_path)
    assert rig[0].run([LABEL, "--doctor"], active_path=rig[1], release_root=rig[2],
                      receipt_root=rig[3], owner_uid=os.getuid() + 1) == 78

    rig = make_release(tmp_path / "mode")
    rig[1].chmod(0o666)
    assert invoke(rig, LABEL, "--doctor") == 78

    rig = make_release(tmp_path / "link")
    second = rig[1].with_name("active-hardlink.json")
    os.link(rig[1], second)
    assert invoke(rig, LABEL, "--doctor") == 78


def test_active_parent_must_be_trusted_not_merely_active_inode(tmp_path):
    rig = make_release(tmp_path)
    tmp_path.chmod(0o777)
    try:
        assert invoke(rig, LABEL, "--doctor") == 78
    finally:
        tmp_path.chmod(0o700)


def test_release_and_receipt_roots_require_trusted_parent_directories(tmp_path):
    # Unit-level assertions isolate the two containing-directory checks; the
    # end-to-end active-parent attack above proves the same rule through run().
    launcher = load_launcher()
    parent = tmp_path / "parent"; parent.mkdir(mode=0o700)
    root = parent / "root"; root.mkdir(mode=0o700)
    parent.chmod(0o777)
    with pytest.raises(launcher.LauncherBlocked):
        launcher._secure_dir(root.parent, owner_uid=os.getuid())


@pytest.mark.parametrize("mutation", ["tree", "runtime", "lock", "payload", "receipt",
                                      "release_id", "active_binding"])
def test_doctor_never_reports_green_when_evidence_is_missing_or_drifted(tmp_path, mutation):
    rig = make_release(tmp_path)
    launcher, active, _, receipts, release, manifest = rig
    manifest_path = release / "release-manifest.json"
    if mutation == "tree":
        path = release / "requirements.lock"
        path.chmod(0o640)
        path.write_bytes(b"changed")
        path.chmod(0o440)
        return_code = invoke(rig, LABEL, "--doctor")
    elif mutation == "receipt":
        receipt_id = json.loads(active.read_text())["release_receipt_id"]
        path = receipts / f"{receipt_id}.json"
        receipt = json.loads(path.read_text())
        receipt["sealed_tree_hash"] = "0" * 64
        path.chmod(0o640); path.write_bytes(_canonical(receipt)); path.chmod(0o440)
        return_code = invoke(rig, LABEL, "--doctor")
    elif mutation == "active_binding":
        record = json.loads(active.read_text())
        record["verification_hash"] = "0" * 64
        active.chmod(0o644); active.write_bytes(_canonical(record)); active.chmod(0o444)
        return_code = invoke(rig, LABEL, "--doctor")
    else:
        if mutation == "runtime":
            manifest["runtime_digest"] = "0" * 64
        elif mutation == "lock":
            manifest["lock_hash"] = "0" * 64
        elif mutation == "payload":
            del manifest["service_payloads"][MODULE]["module_sha256"]
        elif mutation == "release_id":
            manifest["release_id"] = "REL-" + "0" * 64
        manifest_path.chmod(0o640)
        manifest_path.write_bytes(_canonical(manifest) + b"\n")
        manifest_path.chmod(0o440)
        return_code = invoke(rig, LABEL, "--doctor")
    assert return_code == 78


def test_duplicate_json_keys_are_rejected(tmp_path):
    rig = make_release(tmp_path)
    active = rig[1]
    release_id = json.loads(active.read_text())["release_id"]
    active.chmod(0o644)
    active.write_text('{"release_id":"%s","release_id":"%s"}' % (release_id, release_id))
    active.chmod(0o444)
    assert invoke(rig, LABEL, "--doctor") == 78
