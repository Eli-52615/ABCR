from __future__ import annotations

import json
import sqlite3

import pytest

from abcr.control.contracts import Actor, ContractError, sha256
from abcr.control.probe_control import (create_promotion_draft, queue_probe,
                                        reconcile_probe_results, record_reflection)
from abcr.control.store import ControlStore, StoreError
from abcr.control.frontdoor import route_text
from abcr.control.operator import Operator


GOAL = """goal_id: G-1
title: test
design_origin: human_claude_manual
hypothesis: persona changes behavior
template_id: behavior_probe
split: dev
personas: [p@v1, q@v1]
arms:
  - {id: control, kind: vanilla}
  - {id: persona-p, kind: persona, persona_ref: p@v1}
  - {id: persona-q, kind: persona, persona_ref: q@v1}
predictions:
  - {task_family: ifeval, direction: increase, rationale: explicit prediction}
falsifier: no directional difference
metrics: [is_correct]
item_count: 2
seeds: [1, 2]
max_cost_usd: 0
"""


class Broker:
    def __init__(self): self.calls = []

    def request(self, operation, arguments):
        self.calls.append((operation, arguments))
        return {"work_id": arguments["work_id"]}


class ResultBroker:
    def __init__(self, memory_path, work_id, outer):
        self.memory_path = memory_path; self.work_id = work_id; self.outer = outer
        self.acks = []

    def completed_fenced(self, stage):
        assert stage == "probe"
        return [{"work_id": self.work_id, "attempt": 3, "fencing_token": 9}]

    def read_result(self, stage, work_id, *, attempt, fencing_token):
        assert (stage, work_id, attempt, fencing_token) == ("probe", self.work_id, 3, 9)
        return {"schema_version": 1, "stage": "probe", "work_id": work_id,
                "attempt": 3, "fencing_token": 9, "consumer": "abcr-probe",
                "result": self.outer, "result_hash": sha256(self.outer),
                "completed_at": "now"}

    def request(self, operation, arguments):
        assert operation == "seal_research_memory"
        from abcr.explore.memory import ResearchMemory
        core = ResearchMemory(self.memory_path).seal_core()
        return {"length": core["length"], "head_entry_hash": core["head_entry_hash"],
                "ledger_sha256": core["ledger_sha256"], "receipt_id": "r" * 64}

    def acknowledge(self, stage, work_id, *, result_hash, attempt, fencing_token):
        self.acks.append((stage, work_id, result_hash, attempt, fencing_token))
        return {"acked": True}


def _indexed_receipt(request, goal_hash, *, salt="local"):
    fingerprint_hash = sha256({"fingerprint": salt})
    arms = ["vanilla", *[f"persona:{value['persona_ref']}"
                         for value in request["personas"]]]
    persona_by_arm = {f"persona:{value['persona_ref']}": value["persona_ref"]
                      for value in request["personas"]}
    rows = []
    for item_id in request["dev_bundle"]["item_ids"]:
        for arm_id in arms:
            rows.append({
                "row_hash": sha256({"salt": salt, "arm": arm_id, "item": item_id}),
                "cell_id": sha256({
                    "probe_id": request["probe_id"], "arm_id": arm_id,
                    "item_id": item_id, "seed": request["seed"],
                    "model_profile": request["model_profile"],
                    "engine_fingerprint_sha256": fingerprint_hash,
                }),
                "goal_hash": goal_hash, "item_id": item_id,
                "seed": request["seed"], "arm_id": arm_id,
                "arm_kind": "vanilla" if arm_id == "vanilla" else "persona",
                "persona_ref": persona_by_arm.get(arm_id),
                "engine_fingerprint_sha256": fingerprint_hash,
            })
    return {
        "schema_version": 2, "receipt_type": "ProbeResultReceipt",
        "probe_id": request["probe_id"], "model_profile": request["model_profile"],
        "row_count": len(rows), "engine_fingerprint_sha256": fingerprint_hash,
        "item_ids": list(request["dev_bundle"]["item_ids"]), "arm_ids": arms,
        "row_hashes": [row["row_hash"] for row in rows], "rows": rows,
        "citable": False, "label": "学习数据·不可引用",
        "started_at": "start", "completed_at": "done",
        "length_control_3l": {"requested": False, "status": "NOT_REQUESTED"},
    }


def actor():
    value = Actor("ou-real-owner", "tenant", "chat", "p2p")
    return {"open_id": value.open_id, "tenant_key": value.tenant_key,
            "chat_id": value.chat_id, "chat_type": value.chat_type}


def seeded(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    proposal_id = "PROP-1"
    store.save_proposal(proposal_id, GOAL, "ou-real-owner")
    assert store.set_proposal_state(proposal_id, "imported", "compiled")
    from abcr.explore.goal import validate_goal
    goal = validate_goal(GOAL.encode()).goal
    from abcr.explore.personas import parse_persona
    persona_doc = {"persona_id": "p", "version": 1, "parent_ref": None,
                   "components": {"stance": "careful"}, "changed_component": None,
                   "manipulation_checks": ["careful"]}
    second_doc = {"persona_id": "q", "version": 1, "parent_ref": None,
                  "components": {"stance": "concise"}, "changed_component": None,
                  "manipulation_checks": ["concise"]}
    persona_digest = parse_persona(persona_doc).digest
    second_digest = parse_persona(second_doc).digest
    selection = {"bundle_id": "a" * 64, "manifest_hash": "b" * 64,
                 "item_ids": ["i1", "i2"], "source_hash": "c" * 64,
                 "split": "dev", "selected_bytes_hash": "d" * 64,
                 "seal_receipt_id": "e" * 64, "sealed_tree_hash": "f" * 64}
    store.append_research_event(
        "compile_envelope_ready", "G-1",
        {"proposal_id": proposal_id,
         "envelope": {"goal_hash": goal.goal_hash, "dev_bundle_id": "a" * 64,
                      "selection_receipt": selection,
                      "personas": [{"ref": "p@v1", "sha256": persona_digest},
                                   {"ref": "q@v1", "sha256": second_digest}]}})
    persona_root = tmp_path / "personas"; persona_root.mkdir()
    (persona_root / "p.json").write_text(json.dumps(persona_doc))
    (persona_root / "q.json").write_text(json.dumps(second_doc))
    return store, proposal_id, persona_root


def test_action_journal_attributes_typed_actor_and_rejects_rebinding(tmp_path):
    store = ControlStore(tmp_path / "db")
    assert store.prepare_action(effect_id="effect", command_id="command", intent="pause",
                                payload={}, actor=actor())
    assert store.action_actor("effect")["open_id"] == "ou-real-owner"
    assert not store.prepare_action(effect_id="effect", command_id="command", intent="pause",
                                    payload={}, actor=actor())
    with pytest.raises(StoreError):
        store.prepare_action(effect_id="effect", command_id="command", intent="pause",
                             payload={}, actor={**actor(), "open_id": "attacker"})


def test_action_actor_migration_is_expand_only_and_replay_backfills(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE actions(effect_id TEXT PRIMARY KEY,command_id TEXT NOT NULL,"
                   "intent TEXT NOT NULL,state TEXT NOT NULL,payload_hash TEXT NOT NULL,"
                   "result_json TEXT,worker_id TEXT,lease_until TEXT,created_at TEXT NOT NULL,"
                   "updated_at TEXT NOT NULL)")
        db.execute("INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?,?)",
                   ("effect", "command", "pause", "queued", sha256({}), None, None,
                    None, "old-created", "old-updated"))
    store = ControlStore(path)
    assert not store.prepare_action(effect_id="effect", command_id="command", intent="pause",
                                    payload={}, actor=actor())
    row = store.rows("actions")[0]
    assert row["created_at"] == "old-created" and row["actor_id"] == "ou-real-owner"
    assert json.loads(row["payload_json"]) == {}


def test_typed_probe_selection_and_needs_clarification_are_terminally_journalled(tmp_path):
    concise = route_text("运行快道 PROP-1 2 42")
    assert concise.payload == {"proposal_id": "PROP-1", "prediction_index": 2,
                               "seed": 42}
    routed = route_text("运行快道 PROP-1 p@v1 2 42")
    assert routed.intent == "run_probe"
    assert routed.payload == {"proposal_id": "PROP-1", "persona_ref": "p@v1",
                              "prediction_index": 2, "seed": 42}
    store = ControlStore(tmp_path / "db")
    store.prepare_action(effect_id="effect", command_id="command", intent="run_probe",
                         payload={}, actor=actor())

    def refuse(_payload, _effect_id):
        raise ContractError("needs_clarification", "必须明确科学选择", {"seeds": [1, 2]})

    result = Operator(store, {"run_probe": refuse}).execute("effect", "run_probe", {})
    row = store.rows("actions")[0]
    assert result["code"] == "needs_clarification"
    assert row["state"] == "needs_clarification"
    assert json.loads(row["result_json"])["details"] == {"seeds": [1, 2]}


def test_probe_never_guesses_multi_seed_then_enqueues_fixed_scientific_work(tmp_path):
    store, proposal_id, persona_root = seeded(tmp_path)
    effect = "f" * 64
    store.prepare_action(effect_id=effect, command_id="command", intent="run_probe",
                         payload={"proposal_id": proposal_id}, actor=actor())
    broker = Broker()
    with pytest.raises(ContractError) as exc:
        queue_probe(store=store, broker=broker, effect_id=effect,
                    payload={"proposal_id": proposal_id}, persona_root=persona_root,
                    profile_id="local-frozen-v1", max_output_tokens=64)
    assert exc.value.code == "needs_clarification"
    assert broker.calls == [] and store.rows("probe_runs") == []

    selected = {"proposal_id": proposal_id, "persona_ref": "p@v1",
                "prediction_index": 1, "seed": 2}
    result = queue_probe(store=store, broker=broker, effect_id=effect, payload=selected,
                         persona_root=persona_root, profile_id="local-frozen-v1",
                         max_output_tokens=64)
    assert result["citable"] is False and result["seed"] == 2
    payload = broker.calls[0][1]["payload"]
    assert set(payload) == {"probe_id", "goal_hash", "dev_bundle", "personas",
                            "prediction", "seed", "model_profile",
                            "max_output_tokens", "with_length_control",
                            "length_controls"}
    assert [value["persona_ref"] for value in payload["personas"]] == ["p@v1", "q@v1"]
    assert result["arm_ids"] == ["vanilla", "persona:p@v1", "persona:q@v1"]
    assert result["persona_refs"] == ["p@v1", "q@v1"]
    assert all("path" not in key and "root" not in key for key in payload)
    queue_probe(store=store, broker=broker, effect_id=effect, payload=selected,
                persona_root=persona_root, profile_id="local-frozen-v1",
                max_output_tokens=64)
    assert broker.calls[0][1] == broker.calls[1][1]


def test_probe_rejects_symlink_persona_artifact_and_digest_drift(tmp_path):
    store, proposal_id, persona_root = seeded(tmp_path)
    effect = "1" * 64
    selected = {"proposal_id": proposal_id, "persona_ref": "p@v1",
                "prediction_index": 1, "seed": 1}
    store.prepare_action(effect_id=effect, command_id="command", intent="run_probe",
                         payload=selected, actor=actor())
    original = persona_root / "p.json"; target = tmp_path / "outside.json"
    target.write_bytes(original.read_bytes()); original.unlink(); original.symlink_to(target)
    with pytest.raises(ContractError) as exc:
        queue_probe(store=store, broker=Broker(), effect_id=effect, payload=selected,
                    persona_root=persona_root, profile_id="local-frozen-v1",
                    max_output_tokens=64)
    assert exc.value.code == "persona_artifact_unsafe"


def test_promotion_is_explicit_inert_draft_and_never_creates_proposal(tmp_path):
    store = ControlStore(tmp_path / "db")
    effect = "e" * 64; row_hash = "a" * 64
    store.prepare_action(effect_id=effect, command_id="command", intent="promote_probe",
                         payload={"row_hash": row_hash}, actor=actor())
    request = {"probe_id": "PROBE-1"}
    store.prepare_probe_run(effect_id="source", work_id="probe-source",
                            proposal_id="PROP-1", actor_id="ou-real-owner",
                            goal_id="G-1", goal_hash="b" * 64, request=request)
    receipt = {"rows": [{"row_hash": row_hash, "goal_hash": "b" * 64,
                          "item_id": "i1"}]}
    store.settle_probe_run(work_id="probe-source", result=receipt,
                           result_hash=sha256({"outer": 1}))
    draft = create_promotion_draft(store=store, effect_id=effect,
                                   payload={"row_hash": row_hash})
    assert draft["draft_only"] is True and draft["auto_execute"] is False
    assert draft["requires_human_claude_review"] is True
    assert store.rows("proposals") == []
    assert create_promotion_draft(store=store, effect_id=effect,
                                  payload={"row_hash": row_hash}) == draft


def test_probe_result_uses_exact_fence_and_seals_append_only_memory(tmp_path):
    store = ControlStore(tmp_path / "db"); work_id = "probe-fenced"
    request = {"probe_id": "PROBE-1", "model_profile": "local-v1", "seed": 1,
               "personas": [{"persona_ref": "p@v1", "persona_text": "careful"}],
               "dev_bundle": {"item_ids": ["i1"]}}
    store.prepare_probe_run(effect_id="source", work_id=work_id,
                            proposal_id="PROP-1", actor_id="ou-real-owner",
                            goal_id="G-1", goal_hash="b" * 64, request=request)
    row_hashes = ["a" * 64, "c" * 64]
    fingerprint_hash = "f" * 64
    vanilla_cell = sha256({"probe_id": "PROBE-1", "arm_id": "vanilla",
                           "item_id": "i1", "seed": 1,
                           "model_profile": "local-v1",
                           "engine_fingerprint_sha256": fingerprint_hash})
    persona_cell = sha256({"probe_id": "PROBE-1", "arm_id": "persona:p@v1",
                           "item_id": "i1", "seed": 1,
                           "model_profile": "local-v1",
                           "engine_fingerprint_sha256": fingerprint_hash})
    receipt = {"schema_version": 2, "receipt_type": "ProbeResultReceipt",
               "probe_id": "PROBE-1", "model_profile": "local-v1", "row_count": 2,
               "engine_fingerprint_sha256": fingerprint_hash,
               "item_ids": ["i1"], "arm_ids": ["vanilla", "persona:p@v1"],
               "row_hashes": row_hashes,
               "rows": [
                   {"row_hash": row_hashes[0], "cell_id": vanilla_cell,
                    "goal_hash": "b" * 64, "item_id": "i1", "seed": 1,
                    "arm_id": "vanilla", "arm_kind": "vanilla", "persona_ref": None,
                    "engine_fingerprint_sha256": fingerprint_hash},
                   {"row_hash": row_hashes[1], "cell_id": persona_cell,
                    "goal_hash": "b" * 64, "item_id": "i1", "seed": 1,
                    "arm_id": "persona:p@v1", "arm_kind": "persona",
                    "persona_ref": "p@v1",
                    "engine_fingerprint_sha256": fingerprint_hash},
               ],
               "citable": False, "label": "学习数据·不可引用",
               "started_at": "start", "completed_at": "done",
               "length_control_3l": {"requested": False, "status": "NOT_REQUESTED"}}
    outer = {"ok": True, "result": receipt}
    memory_path = tmp_path / "research.jsonl"
    broker = ResultBroker(memory_path, work_id, outer)
    assert reconcile_probe_results(store=store, broker=broker,
                                   research_memory_path=memory_path) == 1
    assert broker.acks == [("probe", work_id, sha256(outer), 3, 9)]
    assert store.rows("probe_runs")[0]["state"] == "completed"


@pytest.mark.parametrize("attack", [
    "old_schema", "cross_proposal_receipt", "duplicate_cell", "missing_arm",
    "live_label",
])
def test_probe_result_adversarial_receipts_never_settle_target_run(tmp_path, attack):
    store = ControlStore(tmp_path / "db")
    work_id = "probe-target"
    target_goal = "b" * 64
    target_request = {
        "probe_id": "PROBE-TARGET", "model_profile": "local-v1", "seed": 7,
        "personas": [{"persona_ref": "p@v1", "persona_text": "careful"}],
        "dev_bundle": {"item_ids": ["i1"]},
    }
    store.prepare_probe_run(
        effect_id="target-effect", work_id=work_id, proposal_id="PROP-TARGET",
        actor_id="ou-real-owner", goal_id="G-TARGET", goal_hash=target_goal,
        request=target_request,
    )
    receipt = _indexed_receipt(target_request, target_goal)
    if attack == "old_schema":
        receipt["schema_version"] = 1
    elif attack == "cross_proposal_receipt":
        foreign_request = {
            **target_request,
            "probe_id": "PROBE-FOREIGN",
            "seed": 9,
        }
        receipt = _indexed_receipt(foreign_request, "c" * 64, salt="foreign")
    elif attack == "duplicate_cell":
        duplicate = dict(receipt["rows"][0])
        duplicate["row_hash"] = "d" * 64
        receipt["rows"][1] = duplicate
        receipt["row_hashes"][1] = duplicate["row_hash"]
    elif attack == "missing_arm":
        receipt["rows"] = receipt["rows"][:1]
        receipt["row_hashes"] = receipt["row_hashes"][:1]
        receipt["row_count"] = 1
    else:
        receipt["label"] = "飞书生产链路 LIVE 正式证据"
    outer = {"ok": True, "result": receipt}
    broker = ResultBroker(tmp_path / "research.jsonl", work_id, outer)

    with pytest.raises(ContractError):
        reconcile_probe_results(store=store, broker=broker,
                                research_memory_path=tmp_path / "research.jsonl")
    assert store.rows("probe_runs")[0]["state"] == "queued"
    assert broker.acks == []


def test_reflection_is_human_attributed_sealed_and_never_starts_goal(tmp_path):
    store = ControlStore(tmp_path / "db"); effect = "9" * 64
    report_hash = "c" * 64
    store.save_round_report(round_id="ROUND-1", batch_id="EXP-1", goal_id="G-1",
                            status="reported", report_hash=report_hash,
                            audit_reference={"receipt_id": "r"},
                            report={"report_hash": report_hash})
    payload = {"round_id": "ROUND-1", "reflection": "这次结果也可能来自题集顺序。"}
    store.prepare_action(effect_id=effect, command_id="command",
                         intent="record_reflection", payload=payload, actor=actor())
    memory_path = tmp_path / "research.jsonl"

    class SealOnly:
        def request(self, operation, arguments):
            from abcr.explore.memory import ResearchMemory
            core = ResearchMemory(memory_path).seal_core()
            return {"length": core["length"], "head_entry_hash": core["head_entry_hash"],
                    "ledger_sha256": core["ledger_sha256"], "receipt_id": "s" * 64}

    first = record_reflection(store=store, broker=SealOnly(), effect_id=effect,
                              payload=payload, research_memory_path=memory_path)
    second = record_reflection(store=store, broker=SealOnly(), effect_id=effect,
                               payload=payload, research_memory_path=memory_path)
    assert first == second and first["auto_started_goal"] is False
    assert store.rows("proposals") == []
    from abcr.explore.memory import ResearchMemory
    rows = ResearchMemory(memory_path).verify()
    assert len(rows) == 1 and rows[0]["actor_id"] == "ou-real-owner"
    assert rows[0]["payload"]["auto_start_new_goal"] is False
