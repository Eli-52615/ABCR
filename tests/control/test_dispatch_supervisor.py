from __future__ import annotations

import pytest

from abcr.control import dispatch_supervisor as supervisor
from abcr.control.contracts import ContractError, sha256
from abcr.control.operator import spawn_dispatch_supervisor
from abcr.control.queue_runtime import ServiceRuntimeBlocked
from abcr.control.store import ControlStore, StoreError


def test_false_qualification_never_spawns(monkeypatch):
    monkeypatch.setattr("subprocess.Popen",
                        lambda *args, **kwargs: pytest.fail("Popen must not be called"))
    assert spawn_dispatch_supervisor({"dispatch_supervisor_qualified": False}) is None


def test_spawn_uses_fixed_isolated_module_argv(tmp_path, monkeypatch):
    prefix = tmp_path / "release" / "env"
    executable = prefix / "bin" / "python"
    executable.parent.mkdir(parents=True); executable.write_bytes(b"python")
    executable.chmod(0o755)
    state = tmp_path / "state"; state.mkdir()
    observed = {}

    class Child:
        pass

    def fake_popen(argv, **kwargs):
        observed.update(argv=argv, kwargs=kwargs)
        return Child()

    monkeypatch.setattr("abcr.control.operator.sys.prefix", str(prefix))
    monkeypatch.setattr("abcr.control.operator.sys.executable", str(executable))
    monkeypatch.setattr("abcr.control.operator.subprocess.Popen", fake_popen)
    monkeypatch.setenv("ABCR_RELEASE_ID", "release")
    child = spawn_dispatch_supervisor({
        "dispatch_supervisor_qualified": True,
        "dispatch_state_root": str(state),
        "release_id": "release",
    })
    assert isinstance(child, Child)
    assert observed["argv"] == [str(executable.resolve()), "-I", "-B", "-m",
                                 "abcr.control.dispatch_supervisor"]
    assert observed["kwargs"]["shell"] is False
    assert observed["kwargs"]["start_new_session"] is True
    assert "ABCR_QUEUE_CONFIG_ROOT" not in observed["kwargs"]["env"]


def test_supervisor_rechecks_root_owned_qualification(tmp_path):
    settings = {
        "store_path": str(tmp_path / "control.sqlite3"), "interval_seconds": 1,
        "human_uid": 1, "operator_uid": __import__("os").geteuid(),
        "human_gid": 1, "operator_gid": 1, "deployment_id": "prod",
        "protocol_ref": "p", "research_repo": str(tmp_path),
        "research_memory_path": str(tmp_path / "memory"), "research_group_gid": 1,
        "artifact_receipt_private_key": str(tmp_path / "private"),
        "artifact_receipt_public_key": str(tmp_path / "public"),
        "approval_public_key": str(tmp_path / "approval"), "persona_root": str(tmp_path),
        "trusted_dev_bundle_root": str(tmp_path),
        "bundle_sealer_public_key": str(tmp_path / "bundle.pub"),
        "ledger_root": str(tmp_path), "dispatch_queue_root": str(tmp_path),
        "dispatch_state_root": str(tmp_path), "release_id": "REL-1",
        "dispatch_supervisor_qualified": False, "execution_profile": None,
    }
    with pytest.raises(ServiceRuntimeBlocked, match="not_qualified"):
        supervisor.settings_from_config({"settings": settings})


@pytest.mark.parametrize("model", [
    {"engine": "openai", "model_id": "gpt", "revision": "x"},
    {"engine": "transformers", "model_id": "https://example.invalid/model",
     "revision": "x"},
])
def test_network_or_remote_model_engine_is_rejected(model):
    with pytest.raises(ContractError):
        supervisor._local_engine_guard({"model": model})


def test_queue_claim_drift_rejects_before_bundle_or_model_access(tmp_path):
    for name in ("queue", "state", "ledger", "runs", "controls", "bundles"):
        (tmp_path / name).mkdir()
    settings = supervisor.SupervisorSettings(
        store_path=tmp_path / "control.sqlite3", queue_root=tmp_path / "queue",
        state_root=tmp_path / "state", ledger_root=tmp_path / "ledger",
        runs_root=tmp_path / "runs", run_control_root=tmp_path / "controls",
        dev_bundle_root=tmp_path / "bundles",
        bundle_sealer_public_key=tmp_path / "bundle.pub",
        release_id="REL-1", execution_profile={}, interval_seconds=1,
    )
    request = {"batch_id": "B-1", "dispatch_event_id": "EVT-1",
               "token_id": "tok", "claim_id": "claim", "envelope_hash": "a" * 64,
               "release_id": "REL-1", "run_configs": [], "envelope": {}}
    payload = {"config": {}, "batch_id": "B-1", "run_id": "run",
               "seed": 1, "config_hash": "b" * 64,
               "approval_binding": {"forged": True}, "dispatch_event_id": "EVT-1"}
    with pytest.raises(ContractError, match="claim/release"):
        supervisor.validate_queue_payload(payload, request=request, settings=settings)


def test_completed_dispatch_request_cannot_regress(tmp_path):
    store = ControlStore(tmp_path / "control.sqlite3")
    envelope = {"run_configs": [{"config": "fixed"}]}
    request = {"schema_version": 1, "kind": "dispatch_request", "effect_id": "e" * 64,
               "batch_id": "B-1", "envelope_hash": sha256(envelope), "release_id": "REL-1",
               "claim_id": "CLM-1", "token_id": "tok", "claim_receipt_hash": "b" * 64,
               "dispatch_event_id": "EVT-1", "envelope": envelope,
               "run_configs": envelope["run_configs"]}
    assert store.prepare_dispatch_request(request)
    assert store.set_dispatch_request_state(request["effect_id"], state="enqueued")
    assert store.set_dispatch_request_state(request["effect_id"], state="running")
    assert store.set_dispatch_request_state(request["effect_id"], state="completed")
    with pytest.raises(StoreError):
        store.set_dispatch_request_state(request["effect_id"], state="enqueued")
