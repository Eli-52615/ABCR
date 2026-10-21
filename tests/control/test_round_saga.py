from __future__ import annotations

import json
import os
from dataclasses import asdict

import pytest

from abcr.audit.evidence import AuditAttestation, audit_attestation_core
from abcr.audit.service import AuditServiceConfig, _production_request
from abcr.control.attestation import DOMAIN_AUDIT, sign_attestation
from abcr.control.contracts import ContractError, canonical_json, sha256
from abcr.control.ed25519 import generate_keypair
from abcr.control.round_saga import _read_receipt, reconcile_evidence_audits
from abcr.control.store import ControlStore


def test_auditor_rejects_caller_selected_evidence_path(tmp_path):
    config = AuditServiceConfig(tmp_path, tmp_path, tmp_path / "pub",
                                tmp_path / "priv", tmp_path / "audit-pub",
                                evidence_runs_root=tmp_path / "runs",
                                audit_staging_root=tmp_path / "staging")
    payload = {
        "kind": "evidence_from_runs", "batch_id": "EXP-safe",
        "dispatch_effect_id": "effect-safe", "dispatch_event_id": "event-safe",
        "envelope_hash": "a" * 64, "compile_envelope": {}, "dev_bundle": {},
        "evidence_path": "/tmp/attacker",
    }
    with pytest.raises(ContractError) as exc:
        _production_request(payload, config)
    assert exc.value.code == "unknown_fields"


def test_operator_rejects_non_root_broker_receipt(tmp_path):
    receipts = tmp_path / "receipts"; receipts.mkdir()
    sealed = tmp_path / "sealed"; sealed.mkdir()
    core = {"operation": "seal_audit_result", "nonce": "work-1",
            "tree_hash": "1" * 64, "object_id": "audit-1"}
    receipt_id = sha256(core)
    receipt = {"receipt_id": receipt_id, **core, "sealed_tree_hash": "2" * 64,
               "sealed_path": str(sealed / "audit-1"), "created_at": "now"}
    path = receipts / f"{receipt_id}.json"
    path.write_bytes(canonical_json(receipt) + b"\n"); path.chmod(0o440)
    ref = {"operation": "seal_audit_result", "receipt_id": receipt_id,
           "object_id": "audit-1", "sealed_tree_hash": "2" * 64}
    assert path.stat().st_uid != 0, "fixture must exercise the non-root owner rejection"
    with pytest.raises(ContractError) as exc:
        _read_receipt(ref, receipt_root=receipts, sealed_root=sealed,
                      receipt_group_gid=os.getgid())
    assert exc.value.code == "audit_receipt_unsafe"


class _Broker:
    def __init__(self, work_id, result):
        self.work_id = work_id; self.result = result; self.acks = 0

    def completed_fenced(self, stage):
        assert stage == "audit"
        return [{"work_id": self.work_id, "attempt": 1, "fencing_token": 1}]

    def read_result(self, stage, work_id, *, attempt, fencing_token):
        outer = {"ok": True, "result": self.result}
        return {"schema_version": 1, "stage": stage, "work_id": work_id,
                "attempt": attempt, "fencing_token": fencing_token,
                "consumer": "abcr-auditor", "result": outer,
                "result_hash": sha256(outer), "completed_at": "2026-07-21T00:00:00+00:00"}

    def acknowledge(self, *args, **kwargs):
        self.acks += 1
        return {"acked": True}

    def request(self, operation, arguments):
        assert operation == "seal_research_memory"
        return {"length": arguments["expected_length"],
                "head_entry_hash": arguments["expected_head_entry_hash"],
                "ledger_sha256": arguments["expected_ledger_sha256"],
                "receipt_id": "3" * 64}


def _round_fixture(tmp_path, monkeypatch, *, verdict):
    store = ControlStore(tmp_path / "control.db")
    envelope_core = {"schema_version": "exploration-1", "goal_id": "GOAL-1",
                     "goal_hash": "a" * 64, "goal_receipt_id": "receipt-1",
                     "research_commit": "b" * 40, "deployment_id": "fixture",
                     "protocol_ref": "protocol", "split": "dev",
                     "dev_bundle_id": "c" * 64, "dev_bundle_manifest_hash": "d" * 64,
                     "item_ids": ["item-1"], "seeds": [1],
                     "personas": [], "arms": [{"id": "vanilla"}], "metrics": [],
                     "predictions": [], "falsifier": "f", "max_cost_usd": 0,
                     "created_at": "2026-07-21T00:00:00+00:00",
                     "selection_receipt": {"source_hash": "e" * 64},
                     "scope": {}, "run_configs": []}
    envelope = {**envelope_core, "batch_id": "EXP-" + sha256(envelope_core)[:20]}
    request = {"schema_version": 1, "kind": "dispatch_request", "effect_id": "effect-1",
               "batch_id": envelope["batch_id"], "envelope_hash": sha256(envelope),
               "release_id": "REL-1", "claim_id": "claim-1", "token_id": "token-1",
               "claim_receipt_hash": "f" * 64, "dispatch_event_id": "dispatch-1",
               "envelope": envelope, "run_configs": []}
    store.prepare_dispatch_request(request)
    for state in ("enqueued", "running", "completed"):
        store.set_dispatch_request_state("effect-1", state=state)
    work_id = "evidence-work-1"
    store.append_research_event(
        "evidence_audit_enqueued", envelope["batch_id"],
        {"work_id": work_id, "dispatch_effect_id": "effect-1",
         "dispatch_event_id": "dispatch-1", "compile_event_id": "compile-1",
         "envelope_hash": sha256(envelope)})
    private, public = tmp_path / "auditor.pem", tmp_path / "auditor.pub"
    generate_keypair(private, public)
    audit = AuditAttestation(
        batch_id=envelope["batch_id"], expected_keys_hash="1" * 64,
        steps_hash="2" * 64, scores_hash="3" * 64, sidecars_hash="4" * 64,
        verdict=verdict, defects=() if verdict == "PASS" else ("scores_expected_set_mismatch",),
        created_at="2026-07-21T00:00:00+00:00", attestation_hash="",
        goal_id="GOAL-1", compile_envelope_sha256=sha256(envelope),
        compile_envelope=envelope, sealed=None)
    core = audit_attestation_core(audit)
    audit = AuditAttestation(**{**asdict(audit), "attestation_hash": sha256(core),
                                "sealed": sign_attestation(
                                    private_key=private, public_key=public,
                                    domain=DOMAIN_AUDIT, core=core)})
    reference = {"operation": "seal_audit_result", "receipt_id": "5" * 64,
                 "object_id": "audit-object-1", "sealed_tree_hash": "6" * 64}
    result = {"kind": "evidence_audit", "batch_id": envelope["batch_id"],
              "dispatch_event_id": "dispatch-1", "audit_ref": reference}
    monkeypatch.setattr("abcr.control.round_saga._read_receipt", lambda *a, **k: {})
    monkeypatch.setattr("abcr.control.round_saga.load_json_artifact",
                        lambda *a, **k: json.loads(canonical_json(asdict(audit))))
    return store, _Broker(work_id, result), public


def test_round_reconcile_is_idempotent_and_draft_stays_inert(tmp_path, monkeypatch):
    store, broker, public = _round_fixture(tmp_path, monkeypatch, verdict="PASS")
    args = dict(store=store, broker=broker, sealed_audit_root=tmp_path,
                receipt_root=tmp_path, receipt_group_gid=os.getgid(),
                auditor_public_key=public, research_memory_path=tmp_path / "memory.jsonl",
                research_owner_uid=os.geteuid(), ledger_root=tmp_path / "ledger")
    assert reconcile_evidence_audits(**args) == 2
    assert reconcile_evidence_audits(**args) == 0
    assert len(store.rows("round_reports")) == 1
    drafts = store.rows("goal_drafts")
    assert len(drafts) == 1 and drafts[0]["state"] == "awaiting_human_claude"
    assert not store.rows("proposals")
    assert broker.acks == 2


def test_failed_audit_is_not_beautified_into_next_goal(tmp_path, monkeypatch):
    store, broker, public = _round_fixture(tmp_path, monkeypatch, verdict="FAIL")
    reconcile_evidence_audits(
        store=store, broker=broker, sealed_audit_root=tmp_path,
        receipt_root=tmp_path, receipt_group_gid=os.getgid(),
        auditor_public_key=public, research_memory_path=tmp_path / "memory.jsonl",
        research_owner_uid=os.geteuid(), ledger_root=tmp_path / "ledger")
    report = json.loads(store.rows("round_reports")[0]["report_json"])
    assert report["status"] == "quarantined"
    assert report["citable"] is False
    assert report["observations"][0]["verdict"] == "FAIL"
    assert store.rows("goal_drafts") == []
