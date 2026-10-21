from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "scripts/abcr-bootstrap-selector"
    loader = importlib.machinery.SourceFileLoader("abcr_bootstrap_selector", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _release(base: Path, suffix: str, script: bytes) -> tuple[str, str]:
    release_id = "REL-" + suffix * 64
    release = base / "releases" / release_id
    (release / "scripts").mkdir(parents=True)
    target = release / "scripts/abcr-launch"
    target.write_bytes(script); target.chmod(0o500)
    (release / "release-manifest.json").write_text(
        json.dumps({"release_id": release_id}), encoding="utf-8")
    core = {"operation": "seal_release", "nonce": "n-" + suffix,
            "tree_hash": suffix * 64, "object_id": release_id}
    receipt_id = hashlib.sha256(_canonical(core)).hexdigest()
    receipt = {**core, "receipt_id": receipt_id, "sealed_path": str(release)}
    receipts = base / "receipts"; receipts.mkdir(exist_ok=True)
    (receipts / f"{receipt_id}.json").write_text(json.dumps(receipt), encoding="utf-8")
    return release_id, receipt_id


def _slot(root: Path, name: str, generation: int, release_id: str,
          receipt_id: str, target_hash: str):
    directory = root / "launcher" / name; directory.mkdir(parents=True)
    record = {"schema_version": 1, "component": "launcher", "generation": generation,
              "release_id": release_id, "receipt_id": receipt_id,
              "target_relpath": "scripts/abcr-launch", "target_sha256": target_hash,
              "python_relpath": None, "python_sha256": None, "module": None,
              "payload_tree_hash": None}
    (directory / "slot.json").write_text(json.dumps(record), encoding="utf-8")


def _pointer(root: Path, name: str, slot: str, generation: int, probation: bool):
    value = {"schema_version": 1, "component": "launcher", "slot": slot,
             "generation": generation, "probation": probation}
    path = root / "launcher" / name
    path.write_text(json.dumps(value), encoding="utf-8"); path.chmod(0o444)


def test_probation_doctor_promotes_candidate_to_active_and_lkg(tmp_path):
    selector = _load(); components = tmp_path / "components"
    (components / "launcher").mkdir(parents=True)
    release_id, receipt_id = _release(tmp_path, "a", b"#!/bin/sh\nexit 0\n")
    digest = hashlib.sha256(b"#!/bin/sh\nexit 0\n").hexdigest()
    _slot(components, "slot-a", 1, release_id, receipt_id, digest)
    _pointer(components, "active-slot.json", "slot-a", 1, True)

    command, _env, rolled_back = selector.resolve_with_rollback(
        "launcher", [], component_root=components,
        release_root=tmp_path / "releases", receipt_root=tmp_path / "receipts",
        owner_uid=os.getuid(),
        doctor=lambda *a, **k: subprocess.CompletedProcess(a, 0, b"", b""))

    assert command == [str(tmp_path / "releases" / release_id / "scripts/abcr-launch")]
    assert rolled_back is False
    assert json.loads((components / "launcher/active-slot.json").read_text())["probation"] is False
    assert json.loads((components / "launcher/last-known-good.json").read_text())["slot"] == "slot-a"


def test_bad_candidate_bytes_roll_back_without_running_candidate_doctor(tmp_path):
    selector = _load(); components = tmp_path / "components"
    (components / "launcher").mkdir(parents=True)
    old_id, old_receipt = _release(tmp_path, "a", b"#!/bin/sh\nexit 0\n")
    bad_id, bad_receipt = _release(tmp_path, "b", b"#!/bin/sh\nexit 1\n")
    old_hash = hashlib.sha256(b"#!/bin/sh\nexit 0\n").hexdigest()
    _slot(components, "slot-a", 1, old_id, old_receipt, old_hash)
    _slot(components, "slot-b", 2, bad_id, bad_receipt, "0" * 64)
    _pointer(components, "last-known-good.json", "slot-a", 1, False)
    _pointer(components, "active-slot.json", "slot-b", 2, True)
    calls = []

    command, _env, rolled_back = selector.resolve_with_rollback(
        "launcher", ["com.abcr.panel"], component_root=components,
        release_root=tmp_path / "releases", receipt_root=tmp_path / "receipts",
        owner_uid=os.getuid(), doctor=lambda *a, **k: calls.append(a))

    assert rolled_back is True and calls == []
    assert old_id in command[0]
    assert json.loads((components / "launcher/active-slot.json").read_text())["slot"] == "slot-a"


def test_candidate_doctor_failure_rolls_back_to_lkg(tmp_path):
    selector = _load(); components = tmp_path / "components"
    (components / "launcher").mkdir(parents=True)
    old_bytes = b"#!/bin/sh\nexit 0\n"; new_bytes = b"#!/bin/sh\nexit 2\n"
    old_id, old_receipt = _release(tmp_path, "a", old_bytes)
    new_id, new_receipt = _release(tmp_path, "b", new_bytes)
    _slot(components, "slot-a", 1, old_id, old_receipt,
          hashlib.sha256(old_bytes).hexdigest())
    _slot(components, "slot-b", 2, new_id, new_receipt,
          hashlib.sha256(new_bytes).hexdigest())
    _pointer(components, "last-known-good.json", "slot-a", 1, False)
    _pointer(components, "active-slot.json", "slot-b", 2, True)
    calls = []

    def reject(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, b"", b"bad")

    command, _env, rolled_back = selector.resolve_with_rollback(
        "launcher", [], component_root=components,
        release_root=tmp_path / "releases", receipt_root=tmp_path / "receipts",
        owner_uid=os.getuid(), doctor=reject)

    assert rolled_back is True and old_id in command[0]
    assert len(calls) == 1 and calls[0][-1] == "--bootstrap-doctor"


def test_installer_publishes_one_active_pointer_per_component(tmp_path, monkeypatch):
    """Regression: the planning-loop ``active_path`` must not leak into publish."""
    path = ROOT / "scripts/install_abcr_runtime.py"
    loader = importlib.machinery.SourceFileLoader("abcr_runtime_installer", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    installer = importlib.util.module_from_spec(spec)
    loader.exec_module(installer)

    release = tmp_path / "release"
    (release / "scripts").mkdir(parents=True)
    selector_bytes = b"#!/bin/sh\nexit 0\n"
    (release / "scripts/abcr-bootstrap-selector").write_bytes(selector_bytes)
    components = tmp_path / "components"
    for component in ("launcher", "seal-broker", "test-controller"):
        for slot in ("slot-a", "slot-b"):
            (components / component / slot).mkdir(parents=True)
    selector_target = tmp_path / "libexec/abcr-bootstrap-selector"
    selector_target.parent.mkdir()
    monkeypatch.setattr(installer, "COMPONENT_ROOT", components)
    monkeypatch.setattr(installer, "SELECTOR_PATH", selector_target)
    monkeypatch.setattr(installer, "load_release_json", lambda *args: {
        "stable_selector": str(selector_target),
        "stable_selector_sha256": hashlib.sha256(selector_bytes).hexdigest(),
    })
    monkeypatch.setattr(installer, "_component_record",
                        lambda component, *_args: {
                            "schema_version": 1, "component": component, "generation": 1})
    monkeypatch.setattr(installer, "uid", lambda name: os.getuid())
    monkeypatch.setattr(installer, "gid", lambda name: os.getgid())
    monkeypatch.setattr(installer, "require_real_dir", lambda *args, **kwargs: None)

    selected = installer.install_bootstrap_slots(
        release, {"receipt_id": "a" * 64}, {"release_id": "REL-" + "b" * 64})

    assert set(selected) == {"launcher", "seal-broker", "test-controller"}
    for component in selected:
        pointer = json.loads(
            (components / component / "active-slot.json").read_text(encoding="utf-8"))
        assert pointer["component"] == component
        assert pointer["slot"] == selected[component]
