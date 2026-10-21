from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest

from abcr.control.service_runtime import EX_CONFIG


SERVICES = (
    ("abcr.control.operator", "operator-reconciler", "adapter_intent_registry_missing"),
    ("abcr.control.mission_worker", "mission-builder", "adapter_builder_policy_missing"),
    ("abcr.control.test_controller", "test-controller", "adapter_oracle_binding_missing"),
    ("abcr.control.verifier", "verifier", "adapter_verification_queue_missing"),
    ("abcr.control.canary_controller", "canary-controller", "adapter_external_probe_missing"),
    ("abcr.control.release", "release-activator", "adapter_release_queue_missing"),
    ("abcr.control.seal_broker", "seal-broker", "adapter_peer_socket_missing"),
    ("abcr.probe.service", "probe-worker", "adapter_probe_spool_binding_missing"),
    ("abcr.control.panel", "panel", "adapter_snapshot_source_missing"),
)


def _write_contract(root: Path, service: str, reason: str) -> Path:
    path = root / f"{service}.json"
    path.write_text(json.dumps({"schema_version": 1, "service": service,
                                "state": "blocked", "reason_code": reason}),
                    encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.mark.parametrize("module_name,service,reason", SERVICES)
def test_entrypoint_is_callable_and_doctor_reports_explicit_block(
        module_name: str, service: str, reason: str, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = importlib.import_module(module_name)
    assert callable(module.main)
    _write_contract(tmp_path, service, reason)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    monkeypatch.setenv("ABCR_ENTRYPOINT_CONFIG_ROOT", str(tmp_path))
    monkeypatch.delenv("ABCR_SERVICE_LABEL", raising=False)

    assert module.main(["--doctor"]) == EX_CONFIG

    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    status = json.loads(capsys.readouterr().out)
    assert status == {"ok": False, "service": service, "state": "BLOCKED",
                      "error_code": reason}


@pytest.mark.parametrize("module_name,service,reason", SERVICES)
def test_once_is_bounded_and_never_invokes_domain_mutation(
        module_name: str, service: str, reason: str, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = importlib.import_module(module_name)
    _write_contract(tmp_path, service, reason)
    monkeypatch.setenv("ABCR_ENTRYPOINT_CONFIG_ROOT", str(tmp_path))
    monkeypatch.delenv("ABCR_SERVICE_LABEL", raising=False)

    assert module.main(["--once"]) == EX_CONFIG

    status = json.loads(capsys.readouterr().err)
    assert status["state"] == "BLOCKED"
    assert status["error_code"] == reason


@pytest.mark.parametrize("module_name,service,_reason", SERVICES)
def test_missing_contract_fails_closed_without_creating_files(
        module_name: str, service: str, _reason: str, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = importlib.import_module(module_name)
    monkeypatch.setenv("ABCR_ENTRYPOINT_CONFIG_ROOT", str(tmp_path))
    monkeypatch.delenv("ABCR_SERVICE_LABEL", raising=False)

    assert module.main(["--doctor"]) == EX_CONFIG

    assert list(tmp_path.iterdir()) == []
    status = json.loads(capsys.readouterr().out)
    assert status["service"] == service
    assert status["error_code"] == "trusted_runtime_contract_missing"


def test_launched_service_rejects_environment_contract_override(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    module = importlib.import_module("abcr.control.operator")
    _write_contract(tmp_path, "operator-reconciler", "adapter_intent_registry_missing")
    monkeypatch.setenv("ABCR_SERVICE_LABEL", "com.abcr.operator-reconciler")
    monkeypatch.setenv("ABCR_ENTRYPOINT_CONFIG_ROOT", str(tmp_path))

    assert module.main(["--doctor"]) == EX_CONFIG

    status = json.loads(capsys.readouterr().out)
    assert status["error_code"] == "runtime_contract_override_forbidden"


def test_contract_symlink_and_hardlink_are_rejected(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    module = importlib.import_module("abcr.control.operator")
    source = _write_contract(tmp_path, "source", "adapter_intent_registry_missing")
    target = tmp_path / "operator-reconciler.json"
    target.symlink_to(source)
    monkeypatch.setenv("ABCR_ENTRYPOINT_CONFIG_ROOT", str(tmp_path))
    monkeypatch.delenv("ABCR_SERVICE_LABEL", raising=False)
    assert module.main(["--doctor"]) == EX_CONFIG
    assert json.loads(capsys.readouterr().out)["error_code"] == "trusted_runtime_contract_missing"
    target.unlink()
    os.link(source, target)
    assert module.main(["--doctor"]) == EX_CONFIG
    assert json.loads(capsys.readouterr().out)["error_code"] == "trusted_runtime_contract_unsafe"


@pytest.mark.parametrize("module_name,_service,_reason", SERVICES)
def test_unknown_argument_is_rejected(module_name: str, _service: str, _reason: str) -> None:
    module = importlib.import_module(module_name)
    with pytest.raises(SystemExit) as caught:
        module.main(["--unknown"])
    assert caught.value.code == 2

