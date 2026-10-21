"""Feishu human gateway and its isolated production runtime.

The domain object remains transport independent.  The runtime at the bottom of
this module is deliberately small: it reads only the dedicated ABCR human-domain
files, admits an authenticated event, durably journals the reply, and only then
asks the Feishu transport to send it.  It never imports or reads AILH state.
"""
from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import sqlite3
import stat
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from abcr.control.contracts import ActionResult, CommandState, ContractError, sha256
from abcr.control.feishu_transport import FeishuTransport, load_credentials
from abcr.control.frontdoor import FrontDoor, RouteResult
from abcr.control.identity import IdentityPolicy
from abcr.control.store import ControlStore, SCHEMA_VERSION
from abcr.control.bridge import BRIDGE_ROOT, BridgeError, HumanBridge
from abcr.control.human_approval import (APPROVAL_BUNDLE_ROOT, APPROVAL_PUBLIC_KEY,
                                         HUMAN_PRIVATE_KEY, VALIDATOR_PUBLIC_KEY,
                                         find_approval_request,
                                         make_human_decision)
from abcr.control.store import StoreError


class HumanGateway:
    #: Feishu event type stamped on inbox rows when the event omits its own.
    DEFAULT_EVENT_TYPE = "im.message.receive_v1"

    def __init__(self, store: ControlStore, identity: IdentityPolicy,
                 bridge: HumanBridge | None = None, *,
                 approval_private_key: Path = HUMAN_PRIVATE_KEY,
                 approval_public_key: Path = APPROVAL_PUBLIC_KEY,
                 validator_public_key: Path = VALIDATOR_PUBLIC_KEY,
                 approval_root: Path = APPROVAL_BUNDLE_ROOT,
                 trust_root_gid: int = 0,
                 approval_root_uid: int = 0):
        self.store = store; self.identity = identity; self.frontdoor = FrontDoor(store)
        self.bridge = bridge
        self.approval_private_key = Path(approval_private_key)
        self.approval_public_key = Path(approval_public_key)
        self.validator_public_key = Path(validator_public_key)
        self.approval_root = Path(approval_root)
        self.trust_root_gid = trust_root_gid
        self.approval_root_uid = approval_root_uid

    def ingest(self, event: dict[str, Any]) -> ActionResult:
        actor = self.identity.actor_from_event(event)
        message_id = event.get("message_id")
        text = event.get("text")
        if not isinstance(message_id, str) or not isinstance(text, str):
            raise ContractError("message_invalid", "消息缺少 message_id 或文字")
        scope = {"app": self.identity.app_id, "tenant": actor.tenant_key,
                 "chat": actor.chat_id, "type": actor.chat_type}
        payload = {"text": text}
        event_type = str(event.get("event_type") or self.DEFAULT_EVENT_TYPE)
        event_id = event.get("event_id")
        event_id = event_id if isinstance(event_id, str) and event_id else message_id
        stripped = text.strip()
        upload = self.store.open_upload(actor.open_id)
        if upload is not None and stripped not in {"开始导入提案", "结束导入提案"}:
            # Proposal body: admit and append in one transaction so a rejected part
            # leaves no inbox row to make its redelivery look already-handled.
            session_id = str(upload["session_id"])
            dedupe, inserted, seq, part_inserted = self.frontdoor.receive_part(
                actor, session_id, message_id, text, scope=scope, payload=payload,
                event_type=event_type, event_id=event_id)
            if not inserted and not part_inserted:
                return ActionResult(dedupe, CommandState.SUCCEEDED, "duplicate_ignored",
                                    "这条消息已经处理过，不会重复执行。")
            return ActionResult(dedupe, CommandState.SUCCEEDED, "upload_part_saved",
                                f"已安全保存第 {seq} 段；可继续发送，或发送“结束导入提案”。",
                                {"session_id": session_id, "part": seq})
        dedupe, inserted = self.store.receive(message_id=message_id, sender_id=actor.open_id,
                                              scope=scope, payload=payload,
                                              event_type=event_type, event_id=event_id)
        if stripped == "开始导入提案":
            if upload is not None:
                if not inserted:
                    return ActionResult(dedupe, CommandState.SUCCEEDED, "duplicate_ignored",
                                        "这条消息已经处理过，不会重复执行。")
                return ActionResult(dedupe, CommandState.NEEDS_CLARIFICATION,
                                    "upload_already_open",
                                    "已有提案正在导入；请继续发送正文，或发送“结束导入提案”。",
                                    {"session_id": upload["session_id"]})
            session_id = "PS-" + sha256({"actor": actor.open_id, "message": message_id})[:18]
            prior_session = self.store.upload_session(session_id, actor.open_id)
            if prior_session is None:
                session_id = self.frontdoor.begin_upload(actor, message_id)
            return ActionResult(dedupe, CommandState.SUCCEEDED, "upload_started",
                                "提案导入已开始。请逐条发送原文，完成后发送“结束导入提案”。",
                                {"session_id": session_id, "max_parts": 64,
                                 "max_total_bytes": 65536})
        if upload is not None and stripped == "结束导入提案":
            proposal_id, raw = self.frontdoor.finish_upload(actor, str(upload["session_id"]))
            return ActionResult(dedupe, CommandState.SUCCEEDED, "proposal_imported",
                                f"提案已原样保存：{proposal_id}。请检查后发送“确认提案 {proposal_id}”。",
                                {"proposal_id": proposal_id,
                                 "raw_sha256": sha256(raw.encode("utf-8"))})
        command = self.frontdoor.command(actor, message_id, text)
        if isinstance(command, RouteResult):
            if not inserted:
                return ActionResult(dedupe, CommandState.SUCCEEDED, "duplicate_ignored",
                                    "这条消息已经处理过，不会重复执行。")
            return ActionResult(dedupe, CommandState.NEEDS_CLARIFICATION, "needs_clarification",
                                "\n".join(command.clarification))
        if command.intent in {"approve", "reject"}:
            if self.bridge is None:
                return ActionResult(dedupe, CommandState.NEEDS_CLARIFICATION,
                                    "approval_runtime_unavailable",
                                    "审批未执行：Human 签名桥尚未就绪。")
            try:
                if command.intent == "approve":
                    row = find_approval_request(
                        self.store, request_id=command.payload["request_id"],
                        request_version=command.payload["version"],
                        envelope_prefix=command.payload["envelope_prefix"],
                    )
                    decision = make_human_decision(
                        self.store, row, decision="approve", event=event,
                        identity=self.identity,
                        private_key=self.approval_private_key,
                        approval_public_key=self.approval_public_key,
                        approval_root=self.approval_root,
                        receipt_root=self.bridge.receipt_root,
                        validator_public_key=self.validator_public_key,
                        human_gid=self.bridge.human_gid,
                        receipt_group_gid=self.bridge.receipt_group_gid,
                        trust_root_gid=self.trust_root_gid,
                        root_uid=self.approval_root_uid,
                    )
                    code = "approval_signed"
                    message = (f"已签署批准：{decision['request_id']} v"
                               f"{decision['request_version']}。Operator 只会接收可验签事实。")
                else:
                    row = find_approval_request(
                        self.store, request_id=command.payload["request_id"])
                    decision = make_human_decision(
                        self.store, row, decision="reject", event=event,
                        identity=self.identity, reason=command.payload["reason"],
                        private_key=self.approval_private_key,
                        approval_public_key=self.approval_public_key,
                        approval_root=self.approval_root,
                        receipt_root=self.bridge.receipt_root,
                        validator_public_key=self.validator_public_key,
                        human_gid=self.bridge.human_gid,
                        receipt_group_gid=self.bridge.receipt_group_gid,
                        trust_root_gid=self.trust_root_gid,
                        root_uid=self.approval_root_uid,
                    )
                    code = "approval_rejected"
                    message = (f"已拒绝：{decision['request_id']} v"
                               f"{decision['request_version']}。未生成 approve token。")
                # DB fact precedes the deterministic bridge file. A Feishu replay
                # repairs this export without creating a second signature/decision.
                self.bridge.export_approval_decision(decision)
                return ActionResult(dedupe, CommandState.SUCCEEDED, code, message,
                                    {"request_id": decision["request_id"],
                                     "request_version": decision["request_version"],
                                     "decision_id": decision["decision_id"]})
            except (ContractError, StoreError, BridgeError, OSError) as exc:
                code = exc.code if isinstance(exc, ContractError) else type(exc).__name__
                return ActionResult(dedupe, CommandState.NEEDS_CLARIFICATION,
                                    code, "审批未执行：请求引用、指纹或签名信任链校验失败。")
        prepared = self.store.prepare_action(effect_id=command.effect_id, command_id=command.command_id,
                                             intent=command.intent, payload=command.payload,
                                             actor={"open_id": command.actor.open_id,
                                                    "tenant_key": command.actor.tenant_key,
                                                    "chat_id": command.actor.chat_id,
                                                    "chat_type": command.actor.chat_type})
        # Export after journalling, with a deterministic filename.  If the process
        # crashed between those steps, Feishu redelivery reaches this call again and
        # repairs the missing file without duplicating the operator action.
        if self.bridge is not None:
            artifacts: list[dict[str, Any]] = []
            if command.intent == "confirm_proposal":
                rows = [row for row in self.store.rows("proposals")
                        if row["proposal_id"] == command.payload.get("proposal_id")]
                if len(rows) != 1:
                    raise ContractError("proposal_missing", "待确认提案不存在")
                row = rows[0]
                artifacts.append({"kind": "proposal", "proposal_id": row["proposal_id"],
                                  "raw_text": row["raw_text"], "raw_hash": row["raw_hash"],
                                  "actor_id": row["actor_id"]})
            self.bridge.export_command(command, artifacts)
        if not inserted and not prepared:
            return ActionResult(dedupe, CommandState.SUCCEEDED, "duplicate_ignored",
                                "这条消息已经处理过，不会重复执行。")
        return ActionResult(command.effect_id, CommandState.QUEUED, "queued",
                            "已收到并安全入箱，等待执行。" if inserted else
                            "检测到上次入箱后的中断，动作已安全恢复并进入队列。",
                            {"command_id": command.command_id, "intent": command.intent})


# ---------------------------------------------------------------------------
# Dedicated human-domain runtime

DEFAULT_HUMAN_DIR = Path("/Users/abcr-human/Library/Application Support/ABCR-Human")
ENV_FEISHU_PATH = "ABCR_HUMAN_FEISHU_ENV"
ENV_OWNER_PATH = "ABCR_HUMAN_OWNER_JSON"
ENV_SQLITE_PATH = "ABCR_HUMAN_SQLITE"
ENV_BRIDGE_ROOT = "ABCR_HUMAN_BRIDGE_ROOT"
_REQUIRED_DB_TABLES = frozenset({"migrations", "inbox", "actions", "outbox",
                                 "proposals", "upload_sessions"})


@dataclass(frozen=True)
class RuntimePaths:
    feishu_env: Path
    owner_json: Path
    sqlite_path: Path
    bridge_root: Path = BRIDGE_ROOT

    @classmethod
    def from_environ(cls, environ: dict[str, str] | os._Environ[str] | None = None
                     ) -> "RuntimePaths":
        env = os.environ if environ is None else environ
        bridge_override = env.get(ENV_BRIDGE_ROOT)
        if env.get("ABCR_SERVICE_LABEL") and bridge_override:
            raise RuntimeError("human bridge path override forbidden for launched service")
        return cls(
            Path(env.get(ENV_FEISHU_PATH, str(DEFAULT_HUMAN_DIR / "feishu.env"))),
            Path(env.get(ENV_OWNER_PATH, str(DEFAULT_HUMAN_DIR / "discovered-owner.json"))),
            Path(env.get(ENV_SQLITE_PATH, str(DEFAULT_HUMAN_DIR / "human.db"))),
            Path(bridge_override or BRIDGE_ROOT),
        )


@dataclass(frozen=True)
class GatewayRuntimeConfig:
    paths: RuntimePaths
    identity: IdentityPolicy
    app_secret: str = field(repr=False)


def _read_private_json(path: Path) -> dict[str, Any]:
    """Read one owner-controlled 0600 regular file without following links."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError("identity file is not a regular file")
        if info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise RuntimeError("identity file ownership or link count is unsafe")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise RuntimeError("identity file mode must be 0600")
        if info.st_size > 65536:
            raise RuntimeError("identity file exceeds the size limit")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            value = json.load(stream)
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(value, dict):
        raise RuntimeError("identity file must contain a JSON object")
    return value


def _load_config(paths: RuntimePaths) -> GatewayRuntimeConfig:
    app_id, app_secret = load_credentials(str(paths.feishu_env))
    owner = _read_private_json(paths.owner_json)
    required = ("open_id", "chat_id", "tenant_key", "chat_type")
    if any(not isinstance(owner.get(key), str) or not owner[key]
           for key in required):
        raise RuntimeError("owner identity is missing required string fields")
    if owner["chat_type"] != "p2p":
        raise RuntimeError("owner identity must name a p2p chat")
    identity = IdentityPolicy(owner_open_id=owner["open_id"],
                              owner_chat_id=owner["chat_id"],
                              tenant_key=owner["tenant_key"], app_id=app_id)
    return GatewayRuntimeConfig(paths=paths, identity=identity, app_secret=app_secret)


def _check_db_target(path: Path) -> None:
    """Fail closed before allowing SQLite to create or open a writable DB."""
    parent = path.parent
    parent_info = os.lstat(parent)
    if not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode):
        raise RuntimeError("human database parent must be a real directory")
    if parent_info.st_uid != os.geteuid():
        raise RuntimeError("human database parent must belong to the service euid")
    if stat.S_IMODE(parent_info.st_mode) & 0o077:
        raise RuntimeError("human database parent must not be accessible by group/other")
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_nlink != 1 or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise RuntimeError("human database must be an euid-owned 0600 regular file")


def _open_store(path: Path) -> ControlStore:
    _check_db_target(path)
    previous = os.umask(0o077)
    try:
        store = ControlStore(path)
    finally:
        os.umask(previous)
    os.chmod(path, 0o600)
    return store


def _doctor(paths: RuntimePaths) -> dict[str, Any]:
    """Perform semantic checks without creating, migrating or journalling anything."""
    config = _load_config(paths)
    info = os.lstat(paths.sqlite_path)
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_nlink != 1 or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise RuntimeError("human database safety check failed")
    uri = f"file:{quote(str(paths.sqlite_path), safe='/')}?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        check = db.execute("PRAGMA quick_check").fetchone()
        if check is None or check[0] != "ok":
            raise RuntimeError("human database quick_check failed")
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not _REQUIRED_DB_TABLES.issubset(tables):
            raise RuntimeError("human database schema is incomplete")
        version = db.execute("SELECT MAX(version) FROM migrations").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise RuntimeError("human database schema version is not current")
    finally:
        db.close()
    human_account = pwd.getpwuid(os.geteuid())
    operator_account = pwd.getpwnam("abcr-operator")
    HumanBridge(human_uid=os.geteuid(), operator_uid=operator_account.pw_uid,
                human_gid=human_account.pw_gid, operator_gid=operator_account.pw_gid,
                root=paths.bridge_root,
                receipt_group_gid=grp.getgrnam("abcr-release-read").gr_gid)
    return {"ok": True, "app_id": config.identity.app_id,
            "database": str(paths.sqlite_path), "schema_version": SCHEMA_VERSION,
            "mode": "read_only"}


def _initialize_database(paths: RuntimePaths) -> dict[str, Any]:
    """Create/migrate the private human DB without starting network transport.

    This is an explicit deployment action, separate from ``--doctor`` so a
    health check can never create state. Credential and owner identity safety
    are validated first; ``_open_store`` confines the database to an euid-owned
    private directory.
    """
    config = _load_config(paths)
    store = _open_store(paths.sqlite_path)
    with store.connect() as db:
        check = db.execute("PRAGMA quick_check").fetchone()
        version = db.execute("SELECT MAX(version) FROM migrations").fetchone()[0]
    if check is None or check[0] != "ok" or version != SCHEMA_VERSION:
        raise RuntimeError("initialized human database failed semantic validation")
    return {"ok": True, "app_id": config.identity.app_id,
            "database": str(paths.sqlite_path), "schema_version": SCHEMA_VERSION,
            "mode": "initialized"}


class HumanReplyOutbox:
    """Single-launchd-instance durable sender for the existing outbox schema.

    The schema has no fencing/lease columns, so this worker intentionally assumes
    launchd's one-process-per-label invariant.  It provides at-least-once delivery:
    a crash after Feishu accepts a message but before ``sent`` is committed may
    duplicate that acknowledgement, but can never repeat an experiment effect.
    """

    def __init__(self, store: ControlStore, transport: FeishuTransport,
                 owner_chat_id: str):
        self.store = store
        self.transport = transport
        self.owner_chat_id = owner_chat_id
        self._lock = threading.Lock()

    def enqueue(self, event: dict[str, Any], result: ActionResult) -> bool:
        event_id = event.get("event_id") or event.get("message_id")
        effect_id = sha256({"kind": "human_reply", "app_id": event.get("app_id"),
                            "tenant_key": event.get("tenant_key"),
                            "event_type": event.get("event_type")
                            or HumanGateway.DEFAULT_EVENT_TYPE,
                            "event_id": event_id})
        payload = {"type": "text", "text": result.human_message,
                   "receive_id_type": "chat_id"}
        return self.store.enqueue_outbox(effect_id, self.owner_chat_id, payload)

    def drain(self, *, limit: int = 32) -> int:
        sent = 0
        with self._lock:
            with self.store.connect() as db:
                rows = db.execute(
                    "SELECT effect_id,destination,payload_json,attempts FROM outbox "
                    "WHERE state='pending' AND next_attempt_at<=? "
                    "ORDER BY created_at LIMIT ?", (_utc_now(), limit)).fetchall()
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                    if (row["destination"] != self.owner_chat_id
                            or not isinstance(payload, dict)
                            or set(payload) != {"type", "text", "receive_id_type"}
                            or payload["type"] != "text"
                            or payload["receive_id_type"] != "chat_id"
                            or not isinstance(payload["text"], str)
                            or not payload["text"] or len(payload["text"]) > 10000):
                        self._mark_invalid(row["effect_id"])
                        continue
                    self.transport.send_text(receive_id=self.owner_chat_id,
                                             text=payload["text"],
                                             receive_id_type="chat_id")
                except Exception as exc:  # network failure: retry only this outbox row
                    self._mark_retry(row["effect_id"], int(row["attempts"]), exc)
                else:
                    with self.store.immediate() as db:
                        db.execute("UPDATE outbox SET state='sent',sent_at=?,last_error=NULL "
                                   "WHERE effect_id=? AND state='pending'",
                                   (_utc_now(), row["effect_id"]))
                    sent += 1
        return sent

    def retry_until_stopped(self, stop: threading.Event, *, interval_seconds: float = 1.0
                            ) -> None:
        """Retry due rows independently of incoming chat traffic.

        A failed reply must not wait for the owner to send another command.  Errors
        remain confined to the durable outbox row; this loop never re-ingests the
        Feishu event and therefore cannot repeat an experiment effect.
        """
        while not stop.wait(interval_seconds):
            try:
                self.drain()
            except Exception:
                # Row-level network errors are already persisted by drain().  A
                # database-level error is retried on the next bounded tick without
                # logging paths, payloads or exception text.
                continue

    def _mark_invalid(self, effect_id: str) -> None:
        with self.store.immediate() as db:
            db.execute("UPDATE outbox SET state='failed',attempts=attempts+1,"
                       "last_error='payload_invalid' WHERE effect_id=? AND state='pending'",
                       (effect_id,))

    def _mark_retry(self, effect_id: str, attempts: int, exc: Exception) -> None:
        delay = min(300, 2 ** min(attempts, 8))
        retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
        # Persist only the exception class.  urllib/SDK messages may contain URLs,
        # headers or short-lived credentials and therefore never cross this boundary.
        safe_error = f"send_failed:{type(exc).__name__}"
        with self.store.immediate() as db:
            db.execute("UPDATE outbox SET attempts=attempts+1,next_attempt_at=?,last_error=? "
                       "WHERE effect_id=? AND state='pending'",
                       (retry_at, safe_error, effect_id))


class HumanGatewayRuntime:
    def __init__(self, gateway: HumanGateway, outbox: HumanReplyOutbox):
        self.gateway = gateway
        self.outbox = outbox

    def reconcile_bridge(self) -> int:
        if self.gateway.bridge is None:
            return 0
        return self.gateway.bridge.import_results(self.gateway.store,
                                                  self.gateway.identity.owner_chat_id)

    def bridge_until_stopped(self, stop: threading.Event, *, interval_seconds: float = 1.0) -> None:
        while not stop.wait(interval_seconds):
            try: self.reconcile_bridge(); self.outbox.drain()
            except Exception: continue

    def handle_event(self, event: dict[str, Any], *, send: bool = True
                     ) -> ActionResult | None:
        try:
            result = self.gateway.ingest(event)
        except ContractError:
            # Identity and format failures are intentionally silent.  Replying would
            # confirm the private control channel to an attacker or malformed sender.
            return None
        self.outbox.enqueue(event, result)
        if send:
            self.outbox.drain()
        return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_runtime(paths: RuntimePaths) -> tuple[HumanGatewayRuntime, FeishuTransport]:
    config = _load_config(paths)
    store = _open_store(paths.sqlite_path)
    transport = FeishuTransport(config.identity.app_id, config.app_secret)
    human_account = pwd.getpwuid(os.geteuid())
    operator_account = pwd.getpwnam("abcr-operator")
    gateway = HumanGateway(store, config.identity,
                           HumanBridge(human_uid=os.geteuid(),
                                       operator_uid=operator_account.pw_uid,
                                       human_gid=human_account.pw_gid,
                                       operator_gid=operator_account.pw_gid,
                                       receipt_group_gid=grp.getgrnam(
                                           "abcr-release-read").gr_gid,
                                       root=paths.bridge_root))
    return HumanGatewayRuntime(
        gateway, HumanReplyOutbox(store, transport, config.identity.owner_chat_id)), transport


def _load_fixture(path: str) -> dict[str, Any]:
    if path == "-":
        value = json.load(sys.stdin)
    else:
        with open(path, "r", encoding="utf-8") as stream:
            value = json.load(stream)
    if not isinstance(value, dict):
        raise RuntimeError("fixture must contain one JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ABCR isolated human gateway")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--doctor", action="store_true",
                      help="read-only credential/identity/database semantic check")
    mode.add_argument("--init-db", action="store_true",
                      help="initialize/migrate the private DB without network")
    mode.add_argument("--once-fixture", metavar="JSON",
                      help="ingest one fixture and queue its reply without network")
    args = parser.parse_args(argv)
    paths = RuntimePaths.from_environ()
    try:
        if args.doctor:
            print(json.dumps(_doctor(paths), ensure_ascii=False, sort_keys=True))
            return 0
        if args.init_db:
            print(json.dumps(_initialize_database(paths), ensure_ascii=False,
                             sort_keys=True))
            return 0
        runtime, transport = _build_runtime(paths)
        if args.once_fixture:
            result = runtime.handle_event(_load_fixture(args.once_fixture), send=False)
            payload = ({"ok": True, "accepted": False, "reply_queued": False}
                       if result is None else
                       {"ok": True, "accepted": True, "reply_queued": True,
                        "code": result.code, "state": result.state.value})
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0
        runtime.outbox.drain()  # retry durable replies left by a prior crash
        runtime.reconcile_bridge()
        stop_retry = threading.Event()
        retry_thread = threading.Thread(
            target=runtime.outbox.retry_until_stopped,
            args=(stop_retry,), name="abcr-human-outbox", daemon=True)
        retry_thread.start()
        bridge_thread = threading.Thread(target=runtime.bridge_until_stopped,
                                         args=(stop_retry,), name="abcr-human-bridge",
                                         daemon=True)
        bridge_thread.start()

        def on_event(event: dict[str, Any]) -> None:
            try:
                runtime.handle_event(event, send=True)
            except Exception as exc:
                # Never log event content or exception text at this boundary.
                print(f"human-gateway event failed: {type(exc).__name__}", file=sys.stderr)

        try:
            # Discovery may use the transport's staging default, but the live
            # human-domain service must keep SDK logs inside its own private
            # directory.  Otherwise Path.home()-based staging would point at a
            # non-provisioned or cross-domain location under launchd.
            transport.start_long_connection(
                on_event, lark_log_path=paths.feishu_env.parent / "lark-ws.log")
        finally:
            stop_retry.set()
            bridge_thread.join(timeout=2)
            retry_thread.join(timeout=2.0)
        return 0
    except Exception as exc:
        code = exc.code if isinstance(exc, ContractError) else "runtime_unavailable"
        print(json.dumps({"ok": False, "code": code,
                          "error_type": type(exc).__name__}, sort_keys=True),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
