from __future__ import annotations

import threading

import pytest

from abcr.control.contracts import Actor, ContractError
from abcr.control.frontdoor import FrontDoor, route_text
from abcr.control.human_gateway import HumanGateway
from abcr.control.identity import IdentityPolicy
from abcr.control.store import ControlStore, StoreError


def test_store_migration_dedupe_and_concurrent_claim(tmp_path):
    store = ControlStore(tmp_path / "control.db"); store.migrate(); store.quick_check()
    key, first = store.receive(message_id="m1", sender_id="u1", scope={"chat": "c"}, payload={"x": 1})
    assert first and store.receive(message_id="m1", sender_id="u1", scope={"chat": "c"}, payload={"x": 1}) == (key, False)
    with pytest.raises(StoreError):
        store.receive(message_id="m1", sender_id="u1", scope={"chat": "c"}, payload={"x": 2})
    assert store.prepare_action(effect_id="e1", command_id="c1", intent="status", payload={})
    wins = []
    threads = [threading.Thread(target=lambda i=i: wins.append(store.claim_action("e1", f"w{i}"))) for i in range(8)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert wins.count(True) == 1


def test_upload_is_ordered_limited_and_durable(tmp_path):
    store = ControlStore(tmp_path / "control.db"); front = FrontDoor(store)
    actor = Actor("owner", "tenant", "chat")
    sid = front.begin_upload(actor, "m1")
    assert front.upload_part(actor, sid, "m2", 1, "goal_id: G")
    assert not front.upload_part(actor, sid, "m2", 1, "goal_id: G")
    with pytest.raises(StoreError): front.upload_part(actor, sid, "m4", 3, "bad order")
    assert front.upload_part(actor, sid, "m3", 2, "title: T")
    pid, raw = front.finish_upload(actor, sid)
    assert pid.startswith("PROP-") and raw == "goal_id: G\ntitle: T"


def test_router_never_guesses():
    assert route_text("状态").intent == "status"
    assert route_text("批准 APR-1 abcdef v2").payload["version"] == 2
    unknown = route_text("帮我随便设计并运行一个实验")
    assert unknown.intent is None and len(unknown.clarification) <= 3
    assert route_text("x" * 9000).intent is None


def test_gateway_identity_and_restart_dedupe(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    gateway = HumanGateway(store, IdentityPolicy("owner", "chat", "tenant", "app"))
    event = {"sender_open_id": "owner", "chat_id": "chat", "tenant_key": "tenant",
             "app_id": "app", "chat_type": "p2p", "message_id": "m1", "text": "状态"}
    assert gateway.ingest(event).code == "queued"
    assert HumanGateway(ControlStore(tmp_path / "control.db"), gateway.identity).ingest(event).code == "duplicate_ignored"
    with pytest.raises(ContractError): gateway.ingest(dict(event, sender_open_id="attacker", message_id="m2"))


def test_gateway_conversational_proposal_upload(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    gateway = HumanGateway(store, IdentityPolicy("owner", "chat", "tenant", "app"))

    def event(message_id, text):
        return {"sender_open_id": "owner", "chat_id": "chat", "tenant_key": "tenant", "app_id": "app",
                "chat_type": "p2p", "message_id": message_id, "text": text}

    started = gateway.ingest(event("m1", "开始导入提案"))
    assert started.code == "upload_started"
    assert gateway.ingest(event("m2", "goal_id: G1")).data["part"] == 1
    assert gateway.ingest(event("m3", "template_id: behavior_probe")).data["part"] == 2
    completed = gateway.ingest(event("m4", "结束导入提案"))
    assert completed.code == "proposal_imported"
    proposal = store.rows("proposals")[0]
    assert proposal["raw_text"] == "goal_id: G1\ntemplate_id: behavior_probe"
    assert gateway.ingest(event("m4", "结束导入提案")).code == "duplicate_ignored"


def test_gateway_upload_is_one_per_actor(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    gateway = HumanGateway(store, IdentityPolicy("owner", "chat", "tenant", "app"))

    def event(message_id, text):
        return {"sender_open_id": "owner", "chat_id": "chat", "tenant_key": "tenant", "app_id": "app",
                "chat_type": "p2p", "message_id": message_id, "text": text}

    gateway.ingest(event("m1", "开始导入提案"))
    second = gateway.ingest(event("m2", "开始导入提案"))
    assert second.code == "upload_already_open"
    assert len([r for r in store.rows("upload_sessions") if r["state"] == "open"]) == 1


def test_gateway_recovers_inbox_to_action_crash_window(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    gateway = HumanGateway(store, IdentityPolicy("owner", "chat", "tenant", "app"))
    event = {"sender_open_id": "owner", "chat_id": "chat", "tenant_key": "tenant",
             "app_id": "app", "chat_type": "p2p", "message_id": "m1", "text": "状态"}
    actor = gateway.identity.actor_from_event(event)
    scope = {"app": "app", "tenant": actor.tenant_key, "chat": actor.chat_id,
             "type": actor.chat_type}
    # Seed the inbox exactly as the gateway would, so this still simulates a crash
    # after admission but before the action was prepared.
    store.receive(message_id="m1", sender_id="owner", scope=scope, payload={"text": "状态"},
                  event_type=HumanGateway.DEFAULT_EVENT_TYPE)
    recovered = gateway.ingest(event)
    assert recovered.code == "queued" and "安全恢复" in recovered.human_message
    assert len(store.rows("actions")) == 1
