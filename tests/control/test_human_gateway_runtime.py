from __future__ import annotations

import json
import os
from pathlib import Path

from abcr.control.human_gateway import (
    GatewayRuntimeConfig,
    HumanGateway,
    HumanGatewayRuntime,
    HumanReplyOutbox,
    RuntimePaths,
    _doctor,
    _load_config,
    _open_store,
    main,
)
from abcr.control.identity import IdentityPolicy


OWNER = {"open_id": "ou_owner", "chat_id": "oc_owner", "tenant_key": "tk_owner",
         "chat_type": "p2p", "others": []}


class FakeTransport:
    def __init__(self, store=None, *, fail=False):
        self.store = store
        self.fail = fail
        self.calls = []

    def send_text(self, **kwargs):
        # The durable row must exist before any network-send equivalent is attempted.
        if self.store is not None:
            assert len(self.store.rows("outbox")) == 1
            assert self.store.rows("outbox")[0]["state"] == "pending"
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("must-not-persist secret=top-secret token=temporary")
        return {"code": 0}


def private_file(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def runtime_paths(tmp_path: Path, *, create_db: bool = True) -> RuntimePaths:
    tmp_path.chmod(0o700)
    env = tmp_path / "feishu.env"
    owner = tmp_path / "discovered-owner.json"
    db = tmp_path / "human.db"
    private_file(env, "ABCR_FEISHU_APP_ID=cli_abcr\nABCR_FEISHU_APP_SECRET=secret-value\n")
    private_file(owner, json.dumps(OWNER))
    if create_db:
        _open_store(db)
    return RuntimePaths(env, owner, db)


def owner_event(**over):
    value = {"sender_open_id": "ou_owner", "chat_id": "oc_owner",
             "tenant_key": "tk_owner", "app_id": "cli_abcr", "chat_type": "p2p",
             "sender_type": "user", "message_id": "om_1", "event_id": "ev_1",
             "event_type": "im.message.receive_v1", "text": "状态"}
    value.update(over)
    return value


def test_config_loads_only_explicit_human_domain_files(tmp_path):
    paths = runtime_paths(tmp_path)
    config = _load_config(paths)
    assert isinstance(config, GatewayRuntimeConfig)
    assert config.identity == IdentityPolicy("ou_owner", "oc_owner", "tk_owner", "cli_abcr")
    assert "secret-value" not in repr(config)


def test_doctor_is_read_only_and_never_constructs_transport(tmp_path, monkeypatch):
    paths = runtime_paths(tmp_path)
    before = paths.sqlite_path.stat().st_mtime_ns
    before_rows = {table: _open_store(paths.sqlite_path).rows(table)
                   for table in ("inbox", "actions", "outbox")}

    def forbidden(*args, **kwargs):
        raise AssertionError("doctor must not construct or call network transport")

    monkeypatch.setattr("abcr.control.human_gateway.FeishuTransport", forbidden)
    report = _doctor(paths)
    assert report == {"ok": True, "app_id": "cli_abcr",
                      "database": str(paths.sqlite_path), "schema_version": 2,
                      "mode": "read_only"}
    assert paths.sqlite_path.stat().st_mtime_ns == before
    store = _open_store(paths.sqlite_path)
    assert {table: store.rows(table) for table in before_rows} == before_rows


def test_authorized_ingest_journals_reply_before_sending_and_dedupes(tmp_path):
    paths = runtime_paths(tmp_path)
    store = _open_store(paths.sqlite_path)
    transport = FakeTransport(store)
    gateway = HumanGateway(store, IdentityPolicy("ou_owner", "oc_owner", "tk_owner", "cli_abcr"))
    runtime = HumanGatewayRuntime(gateway, HumanReplyOutbox(store, transport, "oc_owner"))

    first = runtime.handle_event(owner_event())
    assert first is not None and first.code == "queued"
    assert transport.calls == [{"receive_id": "oc_owner", "text": first.human_message,
                                "receive_id_type": "chat_id"}]
    row = store.rows("outbox")[0]
    assert row["state"] == "sent" and row["sent_at"]

    # A redelivery has the same stable reply key, so it cannot send a second ack.
    second = runtime.handle_event(owner_event())
    assert second is not None and second.code == "duplicate_ignored"
    assert len(transport.calls) == 1
    assert len(store.rows("outbox")) == 1


def test_identity_and_format_rejections_are_silent(tmp_path):
    paths = runtime_paths(tmp_path)
    store = _open_store(paths.sqlite_path)
    transport = FakeTransport(store)
    runtime = HumanGatewayRuntime(
        HumanGateway(store, IdentityPolicy("ou_owner", "oc_owner", "tk_owner", "cli_abcr")),
        HumanReplyOutbox(store, transport, "oc_owner"))

    assert runtime.handle_event(owner_event(sender_open_id="ou_attacker", message_id="bad1")) is None
    malformed = owner_event(message_id="bad2")
    del malformed["text"]
    assert runtime.handle_event(malformed) is None
    assert transport.calls == []
    assert store.rows("inbox") == []
    assert store.rows("outbox") == []


def test_send_failure_retries_without_persisting_exception_text(tmp_path):
    paths = runtime_paths(tmp_path)
    store = _open_store(paths.sqlite_path)
    transport = FakeTransport(store, fail=True)
    runtime = HumanGatewayRuntime(
        HumanGateway(store, IdentityPolicy("ou_owner", "oc_owner", "tk_owner", "cli_abcr")),
        HumanReplyOutbox(store, transport, "oc_owner"))
    assert runtime.handle_event(owner_event()) is not None
    row = store.rows("outbox")[0]
    assert row["state"] == "pending" and row["attempts"] == 1
    assert row["last_error"] == "send_failed:RuntimeError"
    assert "secret" not in row["last_error"] and "token" not in row["last_error"]


def test_once_fixture_queues_without_network(tmp_path, monkeypatch, capsys):
    paths = runtime_paths(tmp_path, create_db=False)
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(owner_event()), encoding="utf-8")
    monkeypatch.setenv("ABCR_HUMAN_FEISHU_ENV", str(paths.feishu_env))
    monkeypatch.setenv("ABCR_HUMAN_OWNER_JSON", str(paths.owner_json))
    monkeypatch.setenv("ABCR_HUMAN_SQLITE", str(paths.sqlite_path))

    def no_network(*args, **kwargs):
        raise AssertionError("--once-fixture must not perform network IO")

    monkeypatch.setattr("abcr.control.feishu_transport.FeishuTransport.send_text", no_network)
    monkeypatch.setattr("abcr.control.feishu_transport.FeishuTransport.start_long_connection",
                        no_network)
    assert main(["--once-fixture", str(fixture)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["accepted"] is True and report["reply_queued"] is True
    store = _open_store(paths.sqlite_path)
    assert len(store.rows("inbox")) == 1
    assert len(store.rows("outbox")) == 1
    assert store.rows("outbox")[0]["state"] == "pending"
