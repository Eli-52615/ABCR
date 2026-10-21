from __future__ import annotations

import importlib.machinery
import importlib.util
import importlib
import json
import os
import plistlib
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

AUTHORITATIVE_MODULES = {
    "com.abcr.human-gateway": "abcr.control.human_gateway",
    "com.abcr.operator-reconciler": "abcr.control.operator",
    "com.abcr.probe-worker": "abcr.probe.service",
    "com.abcr.itempool": "abcr.explore.itempool_service",
    "com.abcr.auditor": "abcr.audit.service",
    "com.abcr.mission-builder": "abcr.control.mission_worker",
    "com.abcr.test-controller": "abcr.control.test_controller",
    "com.abcr.verifier": "abcr.control.verifier",
    "com.abcr.canary-controller": "abcr.control.canary_controller",
    "com.abcr.release-activator": "abcr.control.release",
    "com.abcr.panel": "abcr.control.panel",
    "com.abcr.seal-broker": "abcr.control.seal_broker",
}


def test_all_json_configs_parse_and_schemas_are_strict():
    for path in sorted((ROOT / "configs").rglob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
    for path in (ROOT / "configs" / "schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text())
        assert schema["$schema"].endswith("2020-12/schema")
        assert schema["type"] == "object" and schema["additionalProperties"] is False
    expected = {
        "implementation-manifest-v1.schema.json", "control-command-v1.schema.json",
        "action-result-v1.schema.json", "spool-envelope-v1.schema.json",
        "approval-token-v2.schema.json", "approval-request-bundle-v1.schema.json",
        "seal-request-v1.schema.json", "work-envelope-v1.schema.json",
        "dataset-manifest-v1.schema.json", "experiment-goal-v1.schema.json",
        "persona-artifact-v1.schema.json", "mission-v1.schema.json",
        "acceptance-profile-v1.schema.json", "round-index-v1.schema.json",
    }
    assert expected.issubset({path.name for path in (ROOT / "configs/schemas").glob("*.json")})


def test_twelve_plists_match_topology_and_contain_no_secrets():
    topology = json.loads((ROOT / "configs/control/service-topology-v1.json").read_text())
    configured = {x["label"]: x["module"] for x in topology["services"]}
    assert configured == AUTHORITATIVE_MODULES
    expected = set(configured)
    plists = sorted((ROOT / "ops/launchd").glob("com.abcr.*.plist"))
    assert len(expected) == len(plists) == 12
    observed = set()
    for path in plists:
        raw = path.read_bytes(); data = plistlib.loads(raw)
        label = data["Label"]
        observed.add(label)
        assert data["ProgramArguments"] == ["/usr/local/libexec/abcr-launch", label]
        lowered = raw.lower()
        assert b"secret" not in lowered and b"token" not in lowered and b"private_key" not in lowered
        if "QueueDirectories" in data:
            # launchd.plist(5): array of strings; the dict-of-path form parses but never
            # subscribes fsevents, so the on-demand service would silently never start.
            queue_dirs = data["QueueDirectories"]
            assert isinstance(queue_dirs, list) and queue_dirs, label
            assert all(isinstance(d, str) and d.startswith("/") for d in queue_dirs), label
    assert observed == expected


def test_all_twelve_service_modules_expose_callable_main():
    """A syntactically valid plist is not a runnable service.

    Collect every defect in one failure so a missing module or a library-only module
    cannot hide behind the first import error and let deployment be reported green.
    """
    defects = []
    for label, module_name in AUTHORITATIVE_MODULES.items():
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # report all twelve entrypoints in one assertion
            defects.append(f"{label}: cannot import {module_name}: {type(exc).__name__}: {exc}")
            continue
        if not callable(getattr(module, "main", None)):
            defects.append(f"{label}: {module_name} has no callable main()")
    assert not defects, "service entrypoint defects:\n" + "\n".join(defects)


def load_service_runner():
    path = ROOT / "scripts/abcr-service"
    loader = importlib.machinery.SourceFileLoader("abcr_service", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module); return module


def test_service_doctor_rejects_module_without_callable_main(monkeypatch):
    runner = load_service_runner()
    monkeypatch.setattr(runner.importlib, "import_module", lambda _: SimpleNamespace())
    monkeypatch.setattr(sys, "argv", ["abcr-service", "fixture.no_main", "--doctor"])
    with pytest.raises(SystemExit, match=r"fixture\.no_main has no callable main\(\)"):
        runner.main()


def test_service_doctor_validates_but_does_not_run_main(monkeypatch, capsys):
    runner = load_service_runner(); called = []
    fake = SimpleNamespace(main=lambda: called.append(True))
    monkeypatch.setattr(runner.importlib, "import_module", lambda _: fake)
    monkeypatch.setattr(sys, "argv", ["abcr-service", "fixture.valid", "--doctor"])
    assert runner.main() == 0
    assert called == []
    assert json.loads(capsys.readouterr().out) == {
        "ok": True, "module": "fixture.valid", "entrypoint": "main"}


def test_seven_deny_default_sandbox_profiles():
    profiles = sorted((ROOT / "ops/sandbox").glob("*.sb"))
    assert len(profiles) == 7
    for path in profiles:
        text = path.read_text()
        assert "(deny default)" in text and "(allow default)" not in text
    candidate = (ROOT / "ops/sandbox/abcr-candidate.sb").read_text()
    assert "RESULT" not in candidate and "network" in candidate


def load_launcher():
    path = ROOT / "scripts/abcr-launch"
    loader = importlib.machinery.SourceFileLoader("abcr_launch", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module); return module


def test_stable_launcher_rejects_symlink_and_resolves_regular_active(tmp_path):
    launcher = load_launcher(); releases = tmp_path / "releases"; release = releases / "REL-fixture"
    (release / "env/bin").mkdir(parents=True); python = release / "env/bin/python"
    python.write_text("fixture"); python.chmod(0o500)
    (release / "release-manifest.json").write_text(json.dumps({"release_id": "REL-fixture",
                                                                "service_payloads": {"abcr.control.panel": {}}}))
    active = tmp_path / "active.json"; active.write_text(json.dumps({"release_id": "REL-fixture"})); active.chmod(0o444)
    resolved, manifest = launcher.resolve_active(active, releases)
    assert resolved == release.resolve() and manifest["release_id"] == "REL-fixture"
    link = tmp_path / "active-link.json"; link.symlink_to(active)
    with pytest.raises(RuntimeError): launcher.resolve_active(link, releases)


def test_work_stage_and_acl_manifests_are_complete():
    stages = json.loads((ROOT / "configs/control/work-stages-v1.json").read_text())
    assert len(stages["stages"]) == 9 and len(set(stages["stages"])) == 9
    acl = json.loads((ROOT / "ops/acl/acl-manifest-v1.json").read_text())
    assert "candidate_cannot_read_test_results" in acl["negative_probes"]
