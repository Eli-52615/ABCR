"""Exactly-once across restarts: the crash window that lost proposals, and the
dedupe dimensions that must distinguish events rather than collide them.

Both scenarios below were reproduced against the pre-fix code before being turned
into assertions; the docstrings record the observed pre-fix behaviour.
"""
from __future__ import annotations

import sqlite3

import pytest

from abcr.control.human_gateway import HumanGateway
from abcr.control.identity import IdentityPolicy
from abcr.control.store import ControlStore, StoreError

POLICY = IdentityPolicy("owner", "chat", "tenant", "app")


def event(message_id, text, **over):
    base = {"sender_open_id": "owner", "chat_id": "chat", "tenant_key": "tenant", "app_id": "app",
            "chat_type": "p2p", "message_id": message_id, "text": text}
    base.update(over)
    return base


def _gateway(path):
    return HumanGateway(ControlStore(path), POLICY)


def test_crash_between_session_seal_and_proposal_write_loses_nothing(tmp_path):
    """Pre-fix: session ended up 'complete' with zero proposals, and the replay was
    answered 'duplicate_ignored' -- the human's text was gone while the system
    claimed it had been handled."""
    db = tmp_path / "control.db"
    gateway = _gateway(db)
    gateway.ingest(event("m1", "开始导入提案"))
    gateway.ingest(event("m2", "goal_id: G1"))
    gateway.ingest(event("m3", "template_id: behavior_probe"))

    def crash(raw):
        raise RuntimeError("crash after session sealed, before proposal written")

    gateway.frontdoor.proposal_id = crash
    with pytest.raises(RuntimeError):
        gateway.ingest(event("m4", "结束导入提案"))

    # The seal must have rolled back with the proposal write; a half-applied
    # completion is exactly what made the text unrecoverable.
    store = ControlStore(db)
    assert [r["state"] for r in store.rows("upload_sessions")] == ["open"]
    assert store.rows("proposals") == []

    # Restart and replay the same Feishu delivery.
    restarted = _gateway(db)
    replayed = restarted.ingest(event("m4", "结束导入提案"))
    assert replayed.code == "proposal_imported", "must not report duplicate_ignored after a crash"
    proposals = ControlStore(db).rows("proposals")
    assert len(proposals) == 1
    assert proposals[0]["raw_text"] == "goal_id: G1\ntemplate_id: behavior_probe"

    # Replaying again after the successful commit stays at exactly one proposal.
    again = _gateway(db).ingest(event("m4", "结束导入提案"))
    assert again.code == "duplicate_ignored"
    assert len(ControlStore(db).rows("proposals")) == 1


def test_crash_replay_does_not_duplicate_upload_parts(tmp_path):
    db = tmp_path / "control.db"
    gateway = _gateway(db)
    gateway.ingest(event("m1", "开始导入提案"))
    gateway.ingest(event("m2", "goal_id: G1"))

    # Redeliver the body message after a simulated restart: it is already stored,
    # so it must not be appended a second time.
    replay = _gateway(db).ingest(event("m2", "goal_id: G1"))
    assert replay.code == "duplicate_ignored"
    session = ControlStore(db).rows("upload_sessions")[0]
    assert int(session["part_count"]) == 1

    pid, raw = _gateway(db).frontdoor.finish_upload(
        POLICY.actor_from_event(event("m3", "x")), str(session["session_id"]))
    assert raw == "goal_id: G1"


def test_same_message_id_from_different_app_or_tenant_are_distinct_events(tmp_path):
    """Pre-fix: the unique index was (sender_id, message_id), so the second app's
    event raised StoreError('message_id replayed with different scope or payload')
    instead of being admitted as its own event."""
    store = ControlStore(tmp_path / "control.db")
    first, ok1 = store.receive(message_id="m1", sender_id="u1",
                               scope={"app": "appA", "tenant": "t1"}, payload={"text": "hi"})
    second, ok2 = store.receive(message_id="m1", sender_id="u1",
                                scope={"app": "appB", "tenant": "t1"}, payload={"text": "hi"})
    third, ok3 = store.receive(message_id="m1", sender_id="u1",
                               scope={"app": "appA", "tenant": "t2"}, payload={"text": "hi"})
    assert ok1 and ok2 and ok3
    assert len({first, second, third}) == 3
    assert len(store.rows("inbox")) == 3

    # Within one app+tenant the same event is still admitted exactly once...
    assert store.receive(message_id="m1", sender_id="u1",
                         scope={"app": "appA", "tenant": "t1"}, payload={"text": "hi"}) == (first, False)
    # ...and tampering with the payload under a settled key is still refused.
    with pytest.raises(StoreError):
        store.receive(message_id="m1", sender_id="u1",
                      scope={"app": "appA", "tenant": "t1"}, payload={"text": "changed"})


def test_event_type_and_event_id_separate_events_sharing_a_message(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    scope = {"app": "appA", "tenant": "t1"}
    _, ok1 = store.receive(message_id="m1", sender_id="u1", scope=scope,
                           payload={"text": "hi"}, event_type="im.message.receive_v1")
    _, ok2 = store.receive(message_id="m1", sender_id="u1", scope=scope,
                           payload={"text": "hi"}, event_type="im.message.recalled_v1")
    assert ok1 and ok2
    # Distinct event_id under one event_type is a distinct event too.
    _, ok3 = store.receive(message_id="m1", sender_id="u1", scope=scope, payload={"text": "hi"},
                           event_type="im.message.receive_v1", event_id="evt-2")
    assert ok3
    assert len(store.rows("inbox")) == 3


def test_migration_is_idempotent_and_preserves_legacy_rows(tmp_path):
    """Expand-only: a v1 database keeps every original column value, and the event
    dimensions are backfilled into a collision-free legacy namespace."""
    path = tmp_path / "control.db"
    legacy = sqlite3.connect(path)
    legacy.executescript(
        "CREATE TABLE inbox("
        "  dedupe_key TEXT PRIMARY KEY, message_id TEXT NOT NULL, sender_id TEXT NOT NULL,"
        "  payload_hash TEXT NOT NULL, payload_json TEXT NOT NULL, received_at TEXT NOT NULL);"
        "CREATE UNIQUE INDEX one_sender_message ON inbox(sender_id,message_id);"
    )
    # Two senders sharing a message_id -- legal under the retired index, so the
    # backfill must not collide on them.
    legacy.execute("INSERT INTO inbox VALUES('k1','m1','u1','ph1','{\"text\":\"a\"}','t0')")
    legacy.execute("INSERT INTO inbox VALUES('k2','m1','u2','ph2','{\"text\":\"b\"}','t0')")
    legacy.commit(); legacy.close()

    store = ControlStore(path)
    rows = {r["dedupe_key"]: r for r in store.rows("inbox")}
    assert len(rows) == 2
    assert rows["k1"]["message_id"] == "m1" and rows["k1"]["sender_id"] == "u1"
    assert rows["k1"]["payload_json"] == '{"text":"a"}' and rows["k1"]["received_at"] == "t0"
    assert rows["k1"]["event_type"] == "legacy" and rows["k1"]["event_id"] == "u1:m1"
    assert rows["k2"]["event_id"] == "u2:m1"

    # Re-running migration changes nothing.
    store.migrate(); store.migrate()
    assert {r["dedupe_key"]: dict(r) for r in store.rows("inbox")} == {k: dict(v) for k, v in rows.items()}
    store.quick_check()

    with sqlite3.connect(path) as db:
        versions = {row[0] for row in db.execute("SELECT version FROM migrations")}
    assert {1, 2} <= versions


def test_legacy_row_still_dedupes_after_migration(tmp_path):
    """A message admitted before the migration must not be re-admitted after it,
    or the schema change itself would cause a replay."""
    path = tmp_path / "control.db"
    scope = {"app": "app", "tenant": "tenant", "chat": "chat", "type": "p2p"}
    payload = {"text": "状态"}

    store = ControlStore(path)
    key, inserted = store.receive(message_id="m1", sender_id="owner", scope=scope, payload=payload)
    assert inserted

    # Rewrite that row into its pre-v2 shape, then let migration handle it.
    with sqlite3.connect(path) as db:
        db.execute("UPDATE inbox SET app_id='',tenant_key='',event_type='',event_id=''")
        db.execute("DROP INDEX IF EXISTS one_event_per_scope")
    ControlStore(path)

    replayed_key, replayed = ControlStore(path).receive(
        message_id="m1", sender_id="owner", scope=scope, payload=payload)
    assert replayed is False and replayed_key == key
    assert len(ControlStore(path).rows("inbox")) == 1


def test_gateway_restart_dedupe_survives_new_dimensions(tmp_path):
    db = tmp_path / "control.db"
    gateway = _gateway(db)
    assert gateway.ingest(event("m1", "状态")).code == "queued"
    assert _gateway(db).ingest(event("m1", "状态")).code == "duplicate_ignored"
    assert len(ControlStore(db).rows("actions")) == 1
