"""Upload sessions under concurrency: ordering, clean failure, and the limits.

The concurrency scenario below was reproduced against the pre-fix code first.  With
the sequence number read in a separate transaction from the append, six concurrent
parts produced three StoreErrors *after* their inbox rows had already committed;
redelivery then appended those messages at the tail and the human's text came back
permanently reordered (observed: line-5/4/2/6/3/1 for input line-1..6).
"""
from __future__ import annotations

import threading

import pytest

from abcr.control.contracts import Actor, sha256
from abcr.control.frontdoor import FrontDoor
from abcr.control.human_gateway import HumanGateway
from abcr.control.identity import IdentityPolicy
from abcr.control.store import ControlStore, StoreError

POLICY = IdentityPolicy("owner", "chat", "tenant", "app")
ACTOR = Actor("owner", "tenant", "chat")


def event(message_id, text):
    return {"sender_open_id": "owner", "chat_id": "chat", "tenant_key": "tenant", "app_id": "app",
            "chat_type": "p2p", "message_id": message_id, "text": text}


def _raw(store, session_id):
    parts = sorted(
        ((int(r["seq"]), r["content"]) for r in _parts(store, session_id)), key=lambda p: p[0])
    return "\n".join(content for _seq, content in parts)


def _parts(store, session_id):
    with store.connect() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM upload_parts WHERE session_id=?", (session_id,))]


def test_concurrent_parts_are_ordered_and_leave_no_residue(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    gateway = HumanGateway(store, POLICY)
    gateway.ingest(event("m0", "开始导入提案"))
    session_id = store.rows("upload_sessions")[0]["session_id"]

    n = 6
    results: list = [None] * n
    barrier = threading.Barrier(n)

    def send(i):
        barrier.wait()
        try:
            res = gateway.ingest(event(f"m{i + 1}", f"line-{i + 1}"))
            results[i] = ("ok", res.code, res.data.get("part"))
        except Exception as exc:  # noqa: BLE001 - the point of the test
            results[i] = ("exc", type(exc).__name__, str(exc))

    threads = [threading.Thread(target=send, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    failures = [r for r in results if r[0] != "ok"]
    assert failures == [], f"concurrent parts must not fail: {failures}"
    assert all(r[1] == "upload_part_saved" for r in results)

    # Sequence numbers form a contiguous 1..n with no gap, duplicate or collision.
    seqs = sorted(r[2] for r in results)
    assert seqs == list(range(1, n + 1))
    stored = _parts(store, session_id)
    assert sorted(int(p["seq"]) for p in stored) == list(range(1, n + 1))
    assert len({p["message_id"] for p in stored}) == n
    assert int(store.rows("upload_sessions")[0]["part_count"]) == n

    # Every message that reached the store also reached the inbox, and nothing else did.
    assert len(store.rows("inbox")) == n + 1  # + the 开始导入提案 command

    # Each message keeps the slot it won, so redelivery is a no-op and the bytes
    # are unchanged -- the failure mode was redelivery re-appending at the tail.
    before = _raw(store, session_id)
    before_sha = sha256(before.encode("utf-8"))
    for i in range(n):
        assert gateway.ingest(event(f"m{i + 1}", f"line-{i + 1}")).code == "duplicate_ignored"
    assert _raw(store, session_id) == before
    assert sha256(_raw(store, session_id).encode("utf-8")) == before_sha
    assert int(store.rows("upload_sessions")[0]["part_count"]) == n
    assert len(store.rows("inbox")) == n + 1

    completed = gateway.ingest(event("mz", "结束导入提案"))
    assert completed.code == "proposal_imported"
    assert completed.data["raw_sha256"] == before_sha
    assert store.rows("proposals")[0]["raw_text"] == before


def test_sequential_parts_keep_send_order_verbatim(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    gateway = HumanGateway(store, POLICY)
    gateway.ingest(event("m0", "开始导入提案"))
    lines = ["goal_id: G1", "template_id: behavior_probe", "  indented  ", "尾行"]
    for i, line in enumerate(lines):
        assert gateway.ingest(event(f"m{i + 1}", line)).data["part"] == i + 1
    completed = gateway.ingest(event("mz", "结束导入提案"))
    assert store.rows("proposals")[0]["raw_text"] == "\n".join(lines)
    assert completed.data["raw_sha256"] == sha256("\n".join(lines).encode("utf-8"))


def test_rejected_part_leaves_no_inbox_row(tmp_path):
    """A part that fails its limit check must not be admitted to the inbox; an
    orphan inbox row would make the redelivery look already-handled and get the
    text re-appended at the tail."""
    store = ControlStore(tmp_path / "control.db")
    gateway = HumanGateway(store, POLICY)
    gateway.ingest(event("m0", "开始导入提案"))
    gateway.ingest(event("m1", "goal_id: G1"))
    inbox_before = len(store.rows("inbox"))

    oversized = "x" * 70000
    with pytest.raises(StoreError):
        gateway.ingest(event("m2", oversized))

    assert len(store.rows("inbox")) == inbox_before
    assert not any(r["message_id"] == "m2" for r in store.rows("inbox"))
    assert len(_parts(store, store.rows("upload_sessions")[0]["session_id"])) == 1


def test_store_enforces_part_and_byte_limits(tmp_path):
    """Both limits reject, repeatably, and never over-count the session.

    NOTE: the limit branch also runs ``UPDATE ... SET state='rejected'``, but it then
    raises, and ``immediate()`` rolls the whole transaction back -- so the session
    stays 'open'.  That mark has never been reachable (it predates this change) and
    is asserted here as it actually behaves, not as it reads.  Rejection is still
    enforced on every subsequent attempt, so the limit itself holds.
    """
    store = ControlStore(tmp_path / "control.db")
    front = FrontDoor(store)
    sid = front.begin_upload(ACTOR, "m1")
    for i in range(3):
        assert store.append_upload_part(sid, "owner", f"p{i}", None, "x", max_parts=3) == (i + 1, True)
    for attempt in range(2):
        with pytest.raises(StoreError, match="upload limits exceeded"):
            store.append_upload_part(sid, "owner", f"over{attempt}", None, "x", max_parts=3)
    assert int(store.upload_session(sid, "owner")["part_count"]) == 3
    assert len(_parts(store, sid)) == 3

    store2 = ControlStore(tmp_path / "b.db")
    sid2 = FrontDoor(store2).begin_upload(ACTOR, "m1")
    with pytest.raises(StoreError, match="upload limits exceeded"):
        store2.append_upload_part(sid2, "owner", "p0", None, "y" * 100, max_total_bytes=50)
    assert int(store2.upload_session(sid2, "owner")["total_bytes"]) == 0
    assert _parts(store2, sid2) == []


def test_explicit_seq_still_asserts_contiguous_order(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    front = FrontDoor(store)
    sid = front.begin_upload(ACTOR, "m1")
    assert front.upload_part(ACTOR, sid, "m2", 1, "goal_id: G")
    with pytest.raises(StoreError, match="contiguous and ordered"):
        front.upload_part(ACTOR, sid, "m4", 3, "bad order")
    assert front.upload_part(ACTOR, sid, "m3", 2, "title: T")
    assert _raw(store, sid) == "goal_id: G\ntitle: T"


def test_replay_with_different_content_is_refused(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    sid = FrontDoor(store).begin_upload(ACTOR, "m1")
    assert store.append_upload_part(sid, "owner", "m2", None, "original") == (1, True)
    assert store.append_upload_part(sid, "owner", "m2", None, "original") == (1, False)
    with pytest.raises(StoreError, match="different sequence or content"):
        store.append_upload_part(sid, "owner", "m2", None, "tampered")


def test_cross_actor_and_expired_sessions_are_refused(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    sid = FrontDoor(store).begin_upload(ACTOR, "m1")
    with pytest.raises(StoreError, match="upload session unavailable"):
        store.append_upload_part(sid, "intruder", "m2", None, "steal")

    expired = ControlStore(tmp_path / "c.db")
    expired.create_upload("PS-exp", "owner", ttl_seconds=-1)
    with pytest.raises(StoreError, match="expired"):
        expired.append_upload_part("PS-exp", "owner", "m2", None, "late")


def test_one_open_upload_per_actor_under_concurrency(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    gateway = HumanGateway(store, POLICY)
    outcomes: list = [None] * 8
    barrier = threading.Barrier(8)

    def start(i):
        barrier.wait()
        try:
            outcomes[i] = gateway.ingest(event(f"s{i}", "开始导入提案")).code
        except Exception as exc:  # noqa: BLE001
            outcomes[i] = type(exc).__name__

    threads = [threading.Thread(target=start, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len([r for r in store.rows("upload_sessions") if r["state"] == "open"]) == 1
    assert outcomes.count("upload_started") >= 1
