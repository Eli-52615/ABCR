"""Durable SQLite inbox/outbox, command journal and mission store.

The database is deliberately separate from the experiment evidence ledger.  It
coordinates effects but can never make a scientific result citable.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from abcr.control.contracts import (MissionState, canonical_json, require_id,
                                    require_sha, sha256, utc_now)

SCHEMA_VERSION = 7

#: Sentinel namespace for inbox rows written before the app/tenant/event dedupe
#: dimensions existed.  Their originating app and tenant are unrecoverable (the
#: scope was only ever hashed into ``dedupe_key``), so migration files them under
#: ``event_type='legacy'`` with ``event_id='<sender_id>:<message_id>'``.  That key
#: reproduces the retired ``one_sender_message`` uniqueness exactly, so the
#: backfill can never collide, and it can never collide with a live row either
#: because live rows carry a real Feishu event type.
LEGACY_EVENT_TYPE = "legacy"

DDL = """
CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS inbox(
  dedupe_key TEXT PRIMARY KEY, message_id TEXT NOT NULL, sender_id TEXT NOT NULL,
  payload_hash TEXT NOT NULL, payload_json TEXT NOT NULL, received_at TEXT NOT NULL,
  app_id TEXT NOT NULL DEFAULT '', tenant_key TEXT NOT NULL DEFAULT '',
  event_type TEXT NOT NULL DEFAULT '', event_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS actions(
  effect_id TEXT PRIMARY KEY, command_id TEXT NOT NULL, intent TEXT NOT NULL,
  state TEXT NOT NULL, payload_hash TEXT NOT NULL, payload_json TEXT, result_json TEXT,
  worker_id TEXT, lease_until TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  actor_id TEXT NOT NULL DEFAULT '', actor_json TEXT
);
CREATE TABLE IF NOT EXISTS outbox(
  effect_id TEXT PRIMARY KEY, destination TEXT NOT NULL, payload_json TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL, last_error TEXT, created_at TEXT NOT NULL, sent_at TEXT
);
CREATE TABLE IF NOT EXISTS proposals(
  proposal_id TEXT PRIMARY KEY, state TEXT NOT NULL, raw_hash TEXT NOT NULL,
  raw_text TEXT NOT NULL, normalized_json TEXT, actor_id TEXT NOT NULL,
  parent_round_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS upload_sessions(
  session_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, state TEXT NOT NULL,
  total_bytes INTEGER NOT NULL DEFAULT 0, part_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, completed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_upload_per_actor
  ON upload_sessions(actor_id) WHERE state='open';
CREATE TABLE IF NOT EXISTS upload_parts(
  session_id TEXT NOT NULL REFERENCES upload_sessions(session_id), seq INTEGER NOT NULL,
  message_id TEXT NOT NULL, content_hash TEXT NOT NULL, content TEXT NOT NULL,
  created_at TEXT NOT NULL, PRIMARY KEY(session_id,seq), UNIQUE(session_id,message_id)
);
CREATE TABLE IF NOT EXISTS research_events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL, subject_id TEXT NOT NULL, payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incidents(
  incident_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL,
  severity TEXT NOT NULL, evidence_json TEXT NOT NULL, action_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_incident
  ON incidents(fingerprint) WHERE state NOT IN ('resolved','quarantined');
CREATE TABLE IF NOT EXISTS missions(
  mission_id TEXT PRIMARY KEY, state TEXT NOT NULL, risk TEXT NOT NULL,
  payload_json TEXT NOT NULL, base_release TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3, worker_id TEXT, fencing_token INTEGER NOT NULL DEFAULT 0,
  lease_until TEXT, heartbeat_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mission_deps(
  mission_id TEXT NOT NULL REFERENCES missions(mission_id),
  depends_on TEXT NOT NULL REFERENCES missions(mission_id), PRIMARY KEY(mission_id, depends_on)
);
CREATE TABLE IF NOT EXISTS services(
  label TEXT PRIMARY KEY, release_id TEXT NOT NULL, status TEXT NOT NULL,
  semantic_ok INTEGER NOT NULL, detail_json TEXT NOT NULL, checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS releases(
  release_id TEXT PRIMARY KEY, manifest_hash TEXT NOT NULL, state TEXT NOT NULL,
  previous_release TEXT, detail_json TEXT NOT NULL, created_at TEXT NOT NULL, activated_at TEXT
);
CREATE TABLE IF NOT EXISTS approval_claims(
  token_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, envelope_hash TEXT NOT NULL,
  decision TEXT NOT NULL, claimed_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_claim_per_batch_envelope
  ON approval_claims(batch_id,envelope_hash);
CREATE TABLE IF NOT EXISTS approval_decisions(
  request_id TEXT PRIMARY KEY, envelope_hash TEXT NOT NULL, decision TEXT NOT NULL,
  token_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approval_requests(
  request_id TEXT NOT NULL, request_version INTEGER NOT NULL,
  envelope_hash TEXT NOT NULL, state TEXT NOT NULL,
  bundle_json TEXT NOT NULL, reference_json TEXT NOT NULL,
  request_hash TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(request_id,request_version)
);
CREATE TABLE IF NOT EXISTS approval_imports(
  request_id TEXT NOT NULL, request_version INTEGER NOT NULL,
  envelope_hash TEXT NOT NULL, decision TEXT NOT NULL,
  decision_hash TEXT NOT NULL, decision_json TEXT NOT NULL,
  imported_at TEXT NOT NULL, PRIMARY KEY(request_id,request_version)
);
CREATE TABLE IF NOT EXISTS dispatch_claims(
  claim_id TEXT PRIMARY KEY, token_id TEXT NOT NULL UNIQUE,
  request_id TEXT NOT NULL, request_version INTEGER NOT NULL,
  batch_id TEXT NOT NULL, envelope_hash TEXT NOT NULL, release_id TEXT NOT NULL,
  approval_event_id TEXT NOT NULL, effect_id TEXT NOT NULL,
  state TEXT NOT NULL, first_claim_at TEXT,
  receipt_hash TEXT NOT NULL, receipt_json TEXT NOT NULL,
  settled_event_id TEXT, settled_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_dispatch_claim_per_target
  ON dispatch_claims(batch_id,envelope_hash,release_id);
CREATE TABLE IF NOT EXISTS dispatch_claim_imports(
  claim_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, request_version INTEGER NOT NULL,
  batch_id TEXT NOT NULL, envelope_hash TEXT NOT NULL, release_id TEXT NOT NULL,
  approval_event_id TEXT NOT NULL, effect_id TEXT NOT NULL,
  state TEXT NOT NULL, document_hash TEXT NOT NULL, document_json TEXT NOT NULL,
  imported_at TEXT NOT NULL, settled_event_id TEXT
);
CREATE TABLE IF NOT EXISTS dispatch_requests(
  effect_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL UNIQUE,
  envelope_hash TEXT NOT NULL, release_id TEXT NOT NULL,
  claim_id TEXT NOT NULL, claim_receipt_hash TEXT NOT NULL,
  dispatch_event_id TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
  request_json TEXT NOT NULL, state TEXT NOT NULL, reason_code TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS round_reports(
  round_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL UNIQUE, goal_id TEXT NOT NULL,
  status TEXT NOT NULL, report_hash TEXT NOT NULL,
  audit_reference_json TEXT NOT NULL, report_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS round_reflections(
  reflection_id TEXT PRIMARY KEY, round_id TEXT NOT NULL REFERENCES round_reports(round_id),
  actor_id TEXT NOT NULL, reflection_text TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS goal_drafts(
  draft_id TEXT PRIMARY KEY, round_id TEXT NOT NULL REFERENCES round_reports(round_id),
  suggestion_id TEXT NOT NULL, state TEXT NOT NULL, origin TEXT NOT NULL,
  draft_json TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(round_id,suggestion_id)
);
CREATE TABLE IF NOT EXISTS probe_runs(
  effect_id TEXT PRIMARY KEY, work_id TEXT NOT NULL UNIQUE,
  proposal_id TEXT NOT NULL, actor_id TEXT NOT NULL, goal_id TEXT NOT NULL,
  goal_hash TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL,
  state TEXT NOT NULL, result_hash TEXT, result_json TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS probe_promotions(
  promotion_id TEXT PRIMARY KEY, effect_id TEXT NOT NULL UNIQUE,
  row_hash TEXT NOT NULL UNIQUE, actor_id TEXT NOT NULL,
  draft_hash TEXT NOT NULL, draft_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


class StoreError(RuntimeError):
    pass


class ControlStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def immediate(self) -> Iterator[sqlite3.Connection]:
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def migrate(self) -> None:
        with self.immediate() as db:
            db.executescript(DDL)
            self._migrate_inbox_event_dimensions(db)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(actions)")}
            if "payload_json" not in columns:
                db.execute("ALTER TABLE actions ADD COLUMN payload_json TEXT")
            if "actor_id" not in columns:
                db.execute("ALTER TABLE actions ADD COLUMN actor_id TEXT NOT NULL DEFAULT ''")
            if "actor_json" not in columns:
                db.execute("ALTER TABLE actions ADD COLUMN actor_json TEXT")
            for version in range(1, SCHEMA_VERSION + 1):
                db.execute("INSERT OR IGNORE INTO migrations(version,applied_at) VALUES(?,?)",
                           (version, utc_now()))

    @staticmethod
    def _migrate_inbox_event_dimensions(db: sqlite3.Connection) -> None:
        """v1->v2: dedupe on app+tenant+event_type+event_id instead of sender+message.

        Expand-only and idempotent: every original column keeps its value, the new
        columns are added with defaults, legacy rows are filed under a collision-free
        sentinel namespace, and re-running is a no-op.
        """
        columns = {row["name"] for row in db.execute("PRAGMA table_info(inbox)")}
        for name, default in (("app_id", "''"), ("tenant_key", "''"),
                              ("event_type", "''"), ("event_id", "''")):
            if name not in columns:
                db.execute(f"ALTER TABLE inbox ADD COLUMN {name} TEXT NOT NULL DEFAULT {default}")
        db.execute(
            "UPDATE inbox SET event_type=?, event_id=sender_id || ':' || message_id "
            "WHERE event_type='' AND event_id=''",
            (LEGACY_EVENT_TYPE,),
        )
        db.execute("DROP INDEX IF EXISTS one_sender_message")
        try:
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_event_per_scope "
                       "ON inbox(app_id,tenant_key,event_type,event_id)")
        except sqlite3.IntegrityError as exc:  # pragma: no cover - unreachable by construction
            raise StoreError(
                "inbox contains duplicate app/tenant/event_type/event_id rows; "
                "refusing to install the dedupe index over ambiguous data"
            ) from exc

    def quick_check(self) -> None:
        with self.connect() as db:
            row = db.execute("PRAGMA quick_check").fetchone()
            if row is None or row[0] != "ok":
                raise StoreError(f"control database quick_check failed: {row[0] if row else 'empty'}")

    def receive(self, *, message_id: str, sender_id: str, scope: dict[str, Any],
                payload: dict[str, Any], event_type: str = "message",
                event_id: str | None = None) -> tuple[str, bool]:
        with self.immediate() as db:
            return self._receive(db, message_id=message_id, sender_id=sender_id, scope=scope,
                                 payload=payload, event_type=event_type, event_id=event_id)

    @staticmethod
    def _receive(db: sqlite3.Connection, *, message_id: str, sender_id: str,
                 scope: dict[str, Any], payload: dict[str, Any],
                 event_type: str = "message", event_id: str | None = None) -> tuple[str, bool]:
        """Exactly-once inbox admission keyed on app+tenant+event_type+event_id.

        Runs inside the caller's transaction so that admission and the effect it
        guards commit or roll back together.
        """
        payload_hash = sha256(payload)
        app_id = str(scope.get("app") or "")
        tenant_key = str(scope.get("tenant") or "")
        event_id = event_id or message_id
        if event_type == LEGACY_EVENT_TYPE:
            raise StoreError("event_type 'legacy' is reserved for migrated rows")
        # The key must span every dedupe dimension, or two genuinely different events
        # collide on the primary key and the second is silently dropped by INSERT OR
        # IGNORE -- an admitted event that was never stored.
        dedupe_key = sha256({"message_id": message_id, "sender_id": sender_id, "scope": scope,
                             "payload_hash": payload_hash, "event_type": event_type,
                             "event_id": event_id})
        prior = db.execute(
            "SELECT dedupe_key,payload_hash FROM inbox "
            "WHERE app_id=? AND tenant_key=? AND event_type=? AND event_id=?",
            (app_id, tenant_key, event_type, event_id),
        ).fetchone()
        if prior is not None:
            if prior["dedupe_key"] != dedupe_key or prior["payload_hash"] != payload_hash:
                raise StoreError("message_id replayed with different scope or payload")
            return dedupe_key, False
        # A row written before the v2 dimensions existed still has to be recognised as
        # the same event, or the migration itself would cause a replay.  Its scope was
        # never stored and its key predates this formula, so payload_hash is the only
        # sound comparison, and its own key is what earlier callers were handed.
        legacy = db.execute(
            "SELECT dedupe_key,payload_hash FROM inbox WHERE event_type=? AND event_id=?",
            (LEGACY_EVENT_TYPE, f"{sender_id}:{message_id}"),
        ).fetchone()
        if legacy is not None:
            if legacy["payload_hash"] != payload_hash:
                raise StoreError("message_id replayed with different scope or payload")
            return legacy["dedupe_key"], False
        cur = db.execute(
            "INSERT OR IGNORE INTO inbox(dedupe_key,message_id,sender_id,payload_hash,"
            "payload_json,received_at,app_id,tenant_key,event_type,event_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (dedupe_key, message_id, sender_id, payload_hash,
             canonical_json(payload).decode(), utc_now(),
             app_id, tenant_key, event_type, event_id),
        )
        return dedupe_key, cur.rowcount == 1

    def prepare_action(self, *, effect_id: str, command_id: str, intent: str,
                       payload: dict[str, Any], actor: dict[str, Any] | None = None) -> bool:
        """Journal immutable command authority as well as its typed payload.

        ``actor`` is optional only for pre-v7 fixtures/legacy rows.  Production bridge
        callers always supply all four authenticated Actor fields.  A replay may fill
        a legacy empty actor slot, but can never replace an already attributed actor.
        """
        now = utc_now()
        actor_id = ""
        actor_json = None
        if actor is not None:
            if (not isinstance(actor, dict)
                    or set(actor) != {"open_id", "tenant_key", "chat_id", "chat_type"}
                    or not all(isinstance(value, str) and value for value in actor.values())):
                raise StoreError("action actor identity invalid")
            actor_id = actor["open_id"]
            actor_json = canonical_json(actor).decode()
        payload_json = canonical_json(payload).decode()
        payload_hash = sha256(payload)
        with self.immediate() as db:
            prior = db.execute("SELECT * FROM actions WHERE effect_id=?", (effect_id,)).fetchone()
            if prior is not None:
                if (prior["command_id"] != command_id or prior["intent"] != intent
                        or prior["payload_hash"] != payload_hash
                        or prior["payload_json"] not in {None, payload_json}):
                    raise StoreError("effect_id replayed with different command")
                if prior["payload_json"] is None:
                    # v1-v2 stored only the hash.  The authenticated bridge replay
                    # may safely expand that row with bytes matching the old hash.
                    db.execute("UPDATE actions SET payload_json=?,updated_at=? "
                               "WHERE effect_id=? AND payload_json IS NULL",
                               (payload_json, now, effect_id))
                if actor_json is not None:
                    if prior["actor_json"] not in {None, actor_json} or prior["actor_id"] not in {"", actor_id}:
                        raise StoreError("effect_id replayed by different actor")
                    if prior["actor_json"] is None:
                        db.execute("UPDATE actions SET actor_id=?,actor_json=?,updated_at=? "
                                   "WHERE effect_id=? AND actor_json IS NULL",
                                   (actor_id, actor_json, now, effect_id))
                return False
            cur = db.execute(
                "INSERT INTO actions(effect_id,command_id,intent,state,payload_hash,payload_json,"
                "created_at,updated_at,actor_id,actor_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (effect_id, command_id, intent, "queued", payload_hash, payload_json,
                 now, now, actor_id, actor_json),
            )
            return cur.rowcount == 1

    def action_actor(self, effect_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT actor_json FROM actions WHERE effect_id=?",
                             (effect_id,)).fetchone()
        if row is None or row["actor_json"] is None:
            raise StoreError("action has no authenticated actor identity")
        value = json.loads(row["actor_json"])
        if (not isinstance(value, dict)
                or set(value) != {"open_id", "tenant_key", "chat_id", "chat_type"}):
            raise StoreError("action actor identity corrupt")
        return value

    def claim_action(self, effect_id: str, worker_id: str, lease_seconds: int = 60) -> bool:
        now = datetime.now(timezone.utc)
        until = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self.immediate() as db:
            cur = db.execute(
                "UPDATE actions SET state='executing',worker_id=?,lease_until=?,updated_at=? "
                "WHERE effect_id=? AND (state='queued' OR (state='executing' AND lease_until<?))",
                (worker_id, until, now.isoformat(), effect_id, now.isoformat()),
            )
            return cur.rowcount == 1

    def finish_action(self, effect_id: str, *, worker_id: str, state: str,
                      result: dict[str, Any]) -> None:
        if state not in {"succeeded", "failed", "needs_clarification"}:
            raise StoreError(f"terminal action state required, got {state}")
        with self.immediate() as db:
            cur = db.execute(
                "UPDATE actions SET state=?,result_json=?,lease_until=NULL,updated_at=? "
                "WHERE effect_id=? AND state='executing' AND worker_id=?",
                (state, canonical_json(result).decode(), utc_now(), effect_id, worker_id),
            )
            if cur.rowcount != 1:
                raise StoreError("action is not held by an executor")

    def enqueue_outbox(self, effect_id: str, destination: str, payload: dict[str, Any]) -> bool:
        now = utc_now()
        with self.immediate() as db:
            cur = db.execute("INSERT OR IGNORE INTO outbox(effect_id,destination,payload_json,next_attempt_at,created_at) VALUES(?,?,?,?,?)",
                             (effect_id, destination, canonical_json(payload).decode(), now, now))
            return cur.rowcount == 1

    def save_proposal(self, proposal_id: str, raw_text: str, actor_id: str,
                      *, parent_round_id: str | None = None) -> bool:
        now = utc_now()
        with self.immediate() as db:
            cur = db.execute(
                "INSERT OR IGNORE INTO proposals(proposal_id,state,raw_hash,raw_text,actor_id,parent_round_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (proposal_id, "imported", sha256(raw_text.encode()), raw_text, actor_id,
                 parent_round_id, now, now),
            )
            return cur.rowcount == 1

    def create_upload(self, session_id: str, actor_id: str, *, ttl_seconds: int = 1800) -> None:
        now = datetime.now(timezone.utc)
        with self.immediate() as db:
            db.execute("INSERT INTO upload_sessions(session_id,actor_id,state,created_at,expires_at) VALUES(?,?,?,?,?)",
                       (session_id, actor_id, "open", now.isoformat(),
                        (now + timedelta(seconds=ttl_seconds)).isoformat()))

    def open_upload(self, actor_id: str) -> dict[str, Any] | None:
        """Return the actor's one live upload session, expiring stale state first."""
        now = utc_now()
        with self.immediate() as db:
            db.execute("UPDATE upload_sessions SET state='expired' "
                       "WHERE actor_id=? AND state='open' AND expires_at<=?", (actor_id, now))
            row = db.execute(
                "SELECT * FROM upload_sessions WHERE actor_id=? AND state='open'",
                (actor_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def upload_session(self, session_id: str, actor_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM upload_sessions WHERE session_id=? AND actor_id=?",
                             (session_id, actor_id)).fetchone()
            return dict(row) if row is not None else None

    def upload_message_saved(self, session_id: str, message_id: str) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT 1 FROM upload_parts WHERE session_id=? AND message_id=?",
                             (session_id, message_id)).fetchone()
            return row is not None

    def append_upload_part(self, session_id: str, actor_id: str, message_id: str,
                           seq: int | None, content: str, *, max_parts: int = 64,
                           max_total_bytes: int = 65536) -> tuple[int, bool]:
        with self.immediate() as db:
            return self._append_upload_part(db, session_id, actor_id, message_id, seq, content,
                                            max_parts=max_parts, max_total_bytes=max_total_bytes)

    @staticmethod
    def _append_upload_part(db: sqlite3.Connection, session_id: str, actor_id: str,
                            message_id: str, seq: int | None, content: str, *,
                            max_parts: int = 64, max_total_bytes: int = 65536) -> tuple[int, bool]:
        """Append one part, assigning its sequence number inside this transaction.

        ``seq`` is optional.  When ``None`` the store assigns the next sequence, so
        read-check-write of ``part_count`` is atomic and concurrent senders can never
        race onto the same slot.  When supplied it is an *assertion* that the caller's
        expectation still matches the durable state, which keeps the contiguity check
        meaningful for callers that track ordering themselves.

        Returns ``(seq, inserted)``.
        """
        raw_size = len(content.encode("utf-8"))
        now = utc_now()
        session = db.execute("SELECT * FROM upload_sessions WHERE session_id=?", (session_id,)).fetchone()
        if session is None or session["actor_id"] != actor_id or session["state"] != "open":
            raise StoreError("upload session unavailable")
        if session["expires_at"] <= now:
            db.execute("UPDATE upload_sessions SET state='expired' WHERE session_id=?", (session_id,))
            raise StoreError("upload session expired")
        prior = db.execute("SELECT seq,content_hash FROM upload_parts WHERE session_id=? AND message_id=?",
                           (session_id, message_id)).fetchone()
        if prior is not None:
            if (seq is None or int(prior["seq"]) == seq) and prior["content_hash"] == sha256(content.encode()):
                return int(prior["seq"]), False
            raise StoreError("upload message replayed with different sequence or content")
        next_seq = int(session["part_count"]) + 1
        if seq is not None and seq != next_seq:
            raise StoreError("upload part must be contiguous and ordered")
        seq = next_seq
        if seq > max_parts or int(session["total_bytes"]) + raw_size > max_total_bytes:
            db.execute("UPDATE upload_sessions SET state='rejected' WHERE session_id=?", (session_id,))
            raise StoreError("upload limits exceeded")
        cur = db.execute("INSERT OR IGNORE INTO upload_parts VALUES(?,?,?,?,?,?)",
                         (session_id, seq, message_id, sha256(content.encode()), content, now))
        if cur.rowcount == 1:
            db.execute("UPDATE upload_sessions SET total_bytes=total_bytes+?,part_count=part_count+1 WHERE session_id=?",
                       (raw_size, session_id))
        return seq, cur.rowcount == 1

    def receive_upload_part(self, *, message_id: str, sender_id: str, scope: dict[str, Any],
                            payload: dict[str, Any], session_id: str, content: str,
                            event_type: str = "message", event_id: str | None = None,
                            max_parts: int = 64, max_total_bytes: int = 65536
                            ) -> tuple[str, bool, int, bool]:
        """Admit a message to the inbox and store it as an upload part atomically.

        Inbox admission and the part write share one transaction, so a rejected part
        leaves no inbox row behind.  Without that, a redelivery of the rejected message
        would be seen as already-admitted, skip the append, and get re-queued at the
        tail of the proposal -- silently reordering the human's text.

        Returns ``(dedupe_key, inbox_inserted, seq, part_inserted)``.
        """
        with self.immediate() as db:
            dedupe_key, inserted = self._receive(db, message_id=message_id, sender_id=sender_id,
                                                 scope=scope, payload=payload,
                                                 event_type=event_type, event_id=event_id)
            seq, part_inserted = self._append_upload_part(
                db, session_id, sender_id, message_id, None, content,
                max_parts=max_parts, max_total_bytes=max_total_bytes)
            return dedupe_key, inserted, seq, part_inserted

    def complete_upload(self, session_id: str, actor_id: str, *,
                        proposal_id_for: Any) -> tuple[str, str]:
        """Seal the session and persist the proposal in one transaction.

        Splitting these across two commits used to open a window where a crash left
        the session ``complete`` with no proposal row.  The human's text was gone, and
        because the session was no longer open the replay fell through to the command
        router and answered "already handled".  One transaction removes the window.

        Returns ``(proposal_id, raw_text)``.
        """
        with self.immediate() as db:
            session = db.execute("SELECT * FROM upload_sessions WHERE session_id=?", (session_id,)).fetchone()
            if session is None or session["actor_id"] != actor_id or session["state"] != "open":
                raise StoreError("upload session unavailable")
            parts = db.execute("SELECT content FROM upload_parts WHERE session_id=? ORDER BY seq", (session_id,)).fetchall()
            if not parts:
                raise StoreError("empty upload")
            raw = "\n".join(row["content"] for row in parts)
            now = utc_now()
            db.execute("UPDATE upload_sessions SET state='complete',completed_at=? WHERE session_id=?",
                       (now, session_id))
            proposal_id = proposal_id_for(raw)
            db.execute(
                "INSERT OR IGNORE INTO proposals(proposal_id,state,raw_hash,raw_text,actor_id,parent_round_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (proposal_id, "imported", sha256(raw.encode()), raw, actor_id, None, now, now),
            )
            return proposal_id, raw

    def consume_approval(self, token_id: str, batch_id: str, envelope_hash: str,
                         decision: str) -> bool:
        if decision not in {"approve", "reject"}:
            raise StoreError("invalid approval decision")
        with self.immediate() as db:
            cur = db.execute("INSERT OR IGNORE INTO approval_claims VALUES(?,?,?,?,?)",
                             (token_id, batch_id, envelope_hash, decision, utc_now()))
            return cur.rowcount == 1

    def stable_approval(self, request_id: str, envelope_hash: str, decision: str,
                        signer: Any) -> dict[str, Any]:
        """Serialize human clicks so one request produces one stable signed fact."""
        with self.immediate() as db:
            row = db.execute("SELECT * FROM approval_decisions WHERE request_id=?",
                             (request_id,)).fetchone()
            if row is not None:
                if (row["envelope_hash"], row["decision"]) != (envelope_hash, decision):
                    raise StoreError("approval decision already fixed to different content")
                return json.loads(row["token_json"])
            token = signer()
            db.execute("INSERT INTO approval_decisions VALUES(?,?,?,?,?)",
                       (request_id, envelope_hash, decision,
                        canonical_json(token).decode(), utc_now()))
            return token

    def save_approval_request(self, *, request_id: str, request_version: int,
                              envelope_hash: str, bundle: dict[str, Any],
                              reference: dict[str, Any]) -> bool:
        """Persist one immutable broker-sealed approval request reference.

        This table exists independently in the Operator and Human databases.  A
        replay is accepted only when every byte-bound field is identical; a later
        bridge object cannot silently replace what the owner was shown.
        """
        require_id(request_id, "request_id")
        require_sha(envelope_hash, "envelope_hash")
        if (type(request_version) is not int or request_version < 1
                or not isinstance(bundle, dict) or not isinstance(reference, dict)):
            raise StoreError("invalid approval request")
        bundle_json = canonical_json(bundle).decode()
        reference_json = canonical_json(reference).decode()
        request_hash = sha256({"request_id": request_id,
                               "request_version": request_version,
                               "envelope_hash": envelope_hash,
                               "bundle": bundle, "reference": reference})
        now = utc_now()
        with self.immediate() as db:
            row = db.execute(
                "SELECT * FROM approval_requests WHERE request_id=? AND request_version=?",
                (request_id, request_version),
            ).fetchone()
            if row is not None:
                if (row["envelope_hash"] != envelope_hash
                        or row["bundle_json"] != bundle_json
                        or row["reference_json"] != reference_json
                        or row["request_hash"] != request_hash):
                    raise StoreError("approval request replayed with different content")
                return False
            db.execute(
                "INSERT INTO approval_requests VALUES(?,?,?,?,?,?,?,?,?)",
                (request_id, request_version, envelope_hash, "pending", bundle_json,
                 reference_json, request_hash, now, now),
            )
            return True

    def approval_request(self, request_id: str, request_version: int | None = None
                         ) -> dict[str, Any] | None:
        with self.connect() as db:
            if request_version is None:
                rows = db.execute(
                    "SELECT * FROM approval_requests WHERE request_id=? "
                    "ORDER BY request_version DESC LIMIT 2", (request_id,),
                ).fetchall()
                if not rows:
                    return None
                if len(rows) != 1:
                    raise StoreError("approval request version is ambiguous")
                row = rows[0]
            else:
                row = db.execute(
                    "SELECT * FROM approval_requests WHERE request_id=? AND request_version=?",
                    (request_id, request_version),
                ).fetchone()
                if row is None:
                    return None
            out = dict(row)
            out["bundle"] = json.loads(out.pop("bundle_json"))
            out["reference"] = json.loads(out.pop("reference_json"))
            return out

    def mark_approval_request_decided(self, request_id: str, request_version: int,
                                      envelope_hash: str, decision: str) -> None:
        if decision not in {"approve", "reject"}:
            raise StoreError("invalid approval decision")
        with self.immediate() as db:
            row = db.execute(
                "SELECT state,envelope_hash FROM approval_requests "
                "WHERE request_id=? AND request_version=?",
                (request_id, request_version),
            ).fetchone()
            if row is None or row["envelope_hash"] != envelope_hash:
                raise StoreError("approval request unavailable")
            expected = "approved" if decision == "approve" else "rejected"
            if row["state"] not in {"pending", expected}:
                raise StoreError("approval request already fixed to another decision")
            db.execute(
                "UPDATE approval_requests SET state=?,updated_at=? "
                "WHERE request_id=? AND request_version=?",
                (expected, utc_now(), request_id, request_version),
            )

    def import_approval_decision(self, *, request_id: str, request_version: int,
                                 envelope_hash: str, decision: str,
                                 document: dict[str, Any],
                                 token_claim: dict[str, str] | None = None) -> bool:
        """Record a verified Human-domain fact without interpreting its outcome."""
        if decision not in {"approve", "reject"} or not isinstance(document, dict):
            raise StoreError("invalid imported approval decision")
        decision_json = canonical_json(document).decode()
        decision_hash = sha256(document)
        now = utc_now()
        with self.immediate() as db:
            request = db.execute(
                "SELECT envelope_hash FROM approval_requests "
                "WHERE request_id=? AND request_version=?",
                (request_id, request_version),
            ).fetchone()
            if request is None or request["envelope_hash"] != envelope_hash:
                raise StoreError("imported decision has no matching approval request")
            prior = db.execute(
                "SELECT * FROM approval_imports WHERE request_id=? AND request_version=?",
                (request_id, request_version),
            ).fetchone()
            if prior is not None:
                if (prior["envelope_hash"], prior["decision"], prior["decision_hash"],
                        prior["decision_json"]) != (
                            envelope_hash, decision, decision_hash, decision_json):
                    raise StoreError("approval decision already fixed to different content")
                return False
            if decision == "approve":
                if (not isinstance(token_claim, dict)
                        or set(token_claim) != {"token_id", "batch_id"}):
                    raise StoreError("approved import lacks token claim")
                claim = db.execute(
                    "INSERT OR IGNORE INTO approval_claims VALUES(?,?,?,?,?)",
                    (token_claim["token_id"], token_claim["batch_id"], envelope_hash,
                     "approve", now),
                )
                if claim.rowcount != 1:
                    raise StoreError("approval token already consumed")
            elif token_claim is not None:
                raise StoreError("rejected import must not claim a token")
            db.execute(
                "INSERT INTO approval_imports VALUES(?,?,?,?,?,?,?)",
                (request_id, request_version, envelope_hash, decision,
                 decision_hash, decision_json, now),
            )
            db.execute(
                "UPDATE approval_requests SET state=?,updated_at=? "
                "WHERE request_id=? AND request_version=?",
                ("approved" if decision == "approve" else "rejected", now,
                 request_id, request_version),
            )
            return True

    def approval_import(self, request_id: str, request_version: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM approval_imports WHERE request_id=? AND request_version=?",
                (request_id, request_version),
            ).fetchone()
            return dict(row) if row is not None else None

    def stable_dispatch_claim(self, *, request: dict[str, Any], expires_at: str,
                              signer: Any) -> dict[str, Any]:
        """Human-domain first-claim journal.

        The transaction chooses the first-claim timestamp and fixes the target before
        returning a signed document.  Replays of the exact batch/envelope/release
        target return the original document; any attempt to reuse the token or target
        for different authority fails closed.  Expiry is evaluated only while the
        token is still unseen.
        """
        required = {"claim_id", "token_id", "request_id", "request_version",
                    "batch_id", "envelope_hash", "release_id",
                    "approval_event_id", "effect_id"}
        if not isinstance(request, dict) or set(request) != required:
            raise StoreError("dispatch claim request fields mismatch")
        for field in ("claim_id", "token_id", "request_id", "batch_id",
                      "release_id", "approval_event_id", "effect_id"):
            require_id(request[field], field)
        require_sha(request["envelope_hash"], "envelope_hash")
        if type(request["request_version"]) is not int or request["request_version"] < 1:
            raise StoreError("invalid dispatch claim request version")
        try:
            expiry = datetime.fromisoformat(expires_at)
        except (TypeError, ValueError) as exc:
            raise StoreError("invalid dispatch claim expiry") from exc
        if expiry.tzinfo is None:
            raise StoreError("dispatch claim expiry must be timezone-aware")
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat(timespec="microseconds")
        target = (request["batch_id"], request["envelope_hash"], request["release_id"])
        with self.immediate() as db:
            rows = db.execute(
                "SELECT * FROM dispatch_claims WHERE token_id=? OR "
                "(batch_id=? AND envelope_hash=? AND release_id=?)",
                (request["token_id"], *target),
            ).fetchall()
            if rows:
                canonical = rows[0]
                if any(dict(row) != dict(canonical) for row in rows[1:]):
                    raise StoreError("dispatch claim journal contains conflicting authority")
                bound = tuple(canonical[field] for field in (
                    "claim_id", "token_id", "request_id", "request_version", "batch_id",
                    "envelope_hash", "release_id", "approval_event_id", "effect_id"))
                expected = tuple(request[field] for field in (
                    "claim_id", "token_id", "request_id", "request_version", "batch_id",
                    "envelope_hash", "release_id", "approval_event_id", "effect_id"))
                if bound != expected:
                    raise StoreError("approval token/target already fixed to another claim")
                return json.loads(canonical["receipt_json"])
            state = "denied" if now_dt >= expiry else "claimed"
            core = {"schema_version": 1, "kind": "approval_claim_result", **request,
                    "state": state,
                    "first_claim_at": None if state == "denied" else now,
                    "reason_code": "APPROVAL_EXPIRED" if state == "denied" else None}
            document = signer(core)
            if (not isinstance(document, dict) or set(document) != {"core", "sealed"}
                    or document.get("core") != core or not isinstance(document.get("sealed"), dict)):
                raise StoreError("dispatch claim signer returned invalid document")
            receipt_hash = sha256(document)
            db.execute(
                "INSERT INTO dispatch_claims VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (request["claim_id"], request["token_id"], request["request_id"],
                 request["request_version"], request["batch_id"], request["envelope_hash"],
                 request["release_id"], request["approval_event_id"], request["effect_id"],
                 state, core["first_claim_at"], receipt_hash,
                 canonical_json(document).decode(), None, None),
            )
            return document

    def settle_dispatch_claim(self, claim_id: str, *, receipt_hash: str,
                              effect_id: str, dispatch_event_id: str) -> bool:
        """Human-domain transition claimed→settled; rejected claims can never settle."""
        require_id(claim_id, "claim_id")
        require_sha(receipt_hash, "receipt_hash")
        require_id(effect_id, "effect_id")
        require_id(dispatch_event_id, "dispatch_event_id")
        now = utc_now()
        with self.immediate() as db:
            row = db.execute("SELECT * FROM dispatch_claims WHERE claim_id=?",
                             (claim_id,)).fetchone()
            if row is None:
                raise StoreError("dispatch claim unavailable")
            if row["receipt_hash"] != receipt_hash or row["effect_id"] != effect_id:
                raise StoreError("dispatch settlement is not bound to claim receipt")
            if row["state"] == "settled":
                if row["settled_event_id"] != dispatch_event_id:
                    raise StoreError("dispatch claim already settled by another event")
                return False
            if row["state"] != "claimed":
                raise StoreError("only a claimed dispatch authority may settle")
            db.execute(
                "UPDATE dispatch_claims SET state='settled',settled_event_id=?,settled_at=? "
                "WHERE claim_id=? AND state='claimed'",
                (dispatch_event_id, now, claim_id),
            )
            return True

    def dispatch_claim(self, claim_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM dispatch_claims WHERE claim_id=?",
                             (claim_id,)).fetchone()
            return dict(row) if row is not None else None

    def import_dispatch_claim_result(self, document: dict[str, Any]) -> bool:
        """Operator-domain journal for a mechanically verified Human claim result."""
        core = document.get("core") if isinstance(document, dict) else None
        if not isinstance(core, dict) or core.get("state") not in {"claimed", "denied"}:
            raise StoreError("invalid dispatch claim result")
        fields = ("claim_id", "request_id", "request_version", "batch_id",
                  "envelope_hash", "release_id", "approval_event_id", "effect_id")
        if any(field not in core for field in fields):
            raise StoreError("dispatch claim result missing binding")
        document_json = canonical_json(document).decode()
        document_hash = sha256(document)
        now = utc_now()
        with self.immediate() as db:
            prior = db.execute("SELECT * FROM dispatch_claim_imports WHERE claim_id=?",
                               (core["claim_id"],)).fetchone()
            if prior is not None:
                if (prior["document_hash"] != document_hash
                        or prior["document_json"] != document_json):
                    raise StoreError("dispatch claim result replay conflict")
                return False
            db.execute(
                "INSERT INTO dispatch_claim_imports VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (core["claim_id"], core["request_id"], core["request_version"],
                 core["batch_id"], core["envelope_hash"], core["release_id"],
                 core["approval_event_id"], core["effect_id"], core["state"],
                 document_hash, document_json, now, None),
            )
            return True

    def mark_dispatch_claim_settled(self, claim_id: str, dispatch_event_id: str) -> bool:
        require_id(claim_id, "claim_id")
        require_id(dispatch_event_id, "dispatch_event_id")
        with self.immediate() as db:
            row = db.execute("SELECT * FROM dispatch_claim_imports WHERE claim_id=?",
                             (claim_id,)).fetchone()
            if row is None or row["state"] != "claimed":
                raise StoreError("claimed Human receipt unavailable")
            if row["settled_event_id"] is not None:
                if row["settled_event_id"] != dispatch_event_id:
                    raise StoreError("dispatch claim settlement replay conflict")
                return False
            db.execute("UPDATE dispatch_claim_imports SET settled_event_id=? WHERE claim_id=?",
                       (dispatch_event_id, claim_id))
            return True

    def prepare_dispatch_request(self, request: dict[str, Any]) -> bool:
        """Operator-domain immutable handoff to the fixed dispatch supervisor."""
        required = {"schema_version", "kind", "effect_id", "batch_id", "envelope_hash",
                    "release_id", "claim_id", "token_id", "claim_receipt_hash", "dispatch_event_id",
                    "envelope", "run_configs"}
        if not isinstance(request, dict) or set(request) != required:
            raise StoreError("dispatch request fields mismatch")
        if request["schema_version"] != 1 or request["kind"] != "dispatch_request":
            raise StoreError("dispatch request protocol mismatch")
        for field in ("effect_id", "batch_id", "release_id", "claim_id", "token_id",
                      "dispatch_event_id"):
            require_id(request[field], field)
        for field in ("envelope_hash", "claim_receipt_hash"):
            require_sha(request[field], field)
        if (not isinstance(request["envelope"], dict)
                or sha256(request["envelope"]) != request["envelope_hash"]
                or not isinstance(request["run_configs"], list)
                or request["run_configs"] != request["envelope"].get("run_configs")):
            raise StoreError("dispatch request envelope/run_configs binding invalid")
        raw = canonical_json(request).decode()
        digest = sha256(request)
        now = utc_now()
        with self.immediate() as db:
            prior = db.execute("SELECT * FROM dispatch_requests WHERE effect_id=? OR batch_id=?",
                               (request["effect_id"], request["batch_id"])).fetchall()
            if prior:
                if any(row["request_hash"] != digest or row["request_json"] != raw
                       for row in prior):
                    raise StoreError("dispatch request replay conflict")
                return False
            db.execute(
                "INSERT INTO dispatch_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (request["effect_id"], request["batch_id"], request["envelope_hash"],
                 request["release_id"], request["claim_id"], request["claim_receipt_hash"],
                 request["dispatch_event_id"], digest, raw, "prepared", None, now, now),
            )
            return True

    def set_dispatch_request_state(self, effect_id: str, *, state: str,
                                   reason_code: str | None = None) -> bool:
        if state not in {"prepared", "blocked", "enqueued", "running", "completed"}:
            raise StoreError("invalid dispatch request state")
        require_id(effect_id, "effect_id")
        if reason_code is not None:
            require_id(reason_code, "reason_code")
        with self.immediate() as db:
            row = db.execute("SELECT state,reason_code FROM dispatch_requests WHERE effect_id=?",
                             (effect_id,)).fetchone()
            if row is None:
                raise StoreError("dispatch request unavailable")
            allowed = {
                "prepared": {"prepared", "blocked", "enqueued"},
                "blocked": {"blocked", "enqueued"},
                "enqueued": {"enqueued", "running", "blocked"},
                "running": {"running", "completed", "blocked"},
                "completed": {"completed"},
            }
            if state not in allowed.get(row["state"], set()):
                raise StoreError("dispatch request state cannot regress")
            if (row["state"], row["reason_code"]) == (state, reason_code):
                return False
            db.execute("UPDATE dispatch_requests SET state=?,reason_code=?,updated_at=? "
                       "WHERE effect_id=?", (state, reason_code, utc_now(), effect_id))
            return True

    def save_round_report(self, *, round_id: str, batch_id: str, goal_id: str,
                          status: str, report_hash: str, audit_reference: dict[str, Any],
                          report: dict[str, Any]) -> bool:
        """Persist one immutable machine-produced report; conflicting replay fails."""
        for field, value in (("round_id", round_id), ("batch_id", batch_id),
                             ("goal_id", goal_id)):
            require_id(value, field)
        require_sha(report_hash, "report_hash")
        if status not in {"reported", "quarantined"} or report.get("report_hash") != report_hash:
            raise StoreError("round report identity invalid")
        reference_raw = canonical_json(audit_reference).decode()
        report_raw = canonical_json(report).decode()
        with self.immediate() as db:
            prior = db.execute(
                "SELECT * FROM round_reports WHERE round_id=? OR batch_id=?",
                (round_id, batch_id)).fetchall()
            if prior:
                if any((row["round_id"], row["batch_id"], row["goal_id"], row["status"],
                        row["report_hash"], row["audit_reference_json"], row["report_json"])
                       != (round_id, batch_id, goal_id, status, report_hash,
                           reference_raw, report_raw) for row in prior):
                    raise StoreError("round report replay conflict")
                return False
            db.execute("INSERT INTO round_reports VALUES(?,?,?,?,?,?,?,?)",
                       (round_id, batch_id, goal_id, status, report_hash,
                        reference_raw, report_raw, utc_now()))
            return True

    def save_goal_draft(self, *, draft_id: str, round_id: str, suggestion_id: str,
                        draft: dict[str, Any], origin: str = "machine") -> bool:
        """Store inert text outside proposals; this API has no confirm/compile transition."""
        for field, value in (("draft_id", draft_id), ("round_id", round_id),
                             ("suggestion_id", suggestion_id)):
            require_id(value, field)
        if (origin != "machine" or draft.get("draft_only") is not True
                or draft.get("requires_human_claude_review") is not True
                or draft.get("auto_execute") is not False):
            raise StoreError("goal draft is not inert machine output")
        raw = canonical_json(draft).decode()
        with self.immediate() as db:
            prior = db.execute(
                "SELECT * FROM goal_drafts WHERE draft_id=? OR (round_id=? AND suggestion_id=?)",
                (draft_id, round_id, suggestion_id)).fetchall()
            if prior:
                if any((row["draft_id"], row["round_id"], row["suggestion_id"],
                        row["state"], row["origin"], row["draft_json"])
                       != (draft_id, round_id, suggestion_id, "awaiting_human_claude",
                           origin, raw) for row in prior):
                    raise StoreError("goal draft replay conflict")
                return False
            db.execute("INSERT INTO goal_drafts VALUES(?,?,?,?,?,?,?)",
                       (draft_id, round_id, suggestion_id, "awaiting_human_claude",
                        origin, raw, utc_now()))
            return True

    def record_human_reflection(self, *, round_id: str, actor_id: str,
                                reflection_text: str) -> str:
        """Explicit human-only record; never synthesised by the round reconciler."""
        require_id(round_id, "round_id"); require_id(actor_id, "actor_id")
        if (not isinstance(reflection_text, str) or not reflection_text.strip()
                or len(reflection_text.encode("utf-8")) > 64 * 1024):
            raise StoreError("human reflection text invalid")
        reflection_id = "REFL-" + sha256({"round_id": round_id, "actor_id": actor_id,
                                            "text": reflection_text})[:24]
        with self.immediate() as db:
            if db.execute("SELECT 1 FROM round_reports WHERE round_id=?", (round_id,)).fetchone() is None:
                raise StoreError("round report unavailable")
            db.execute("INSERT OR IGNORE INTO round_reflections VALUES(?,?,?,?,?)",
                       (reflection_id, round_id, actor_id, reflection_text, utc_now()))
        return reflection_id

    def set_proposal_state(self, proposal_id: str, expected: str, new: str,
                           normalized: dict[str, Any] | None = None) -> bool:
        with self.immediate() as db:
            cur = db.execute(
                "UPDATE proposals SET state=?,normalized_json=COALESCE(?,normalized_json),updated_at=? "
                "WHERE proposal_id=? AND state=?",
                (new, canonical_json(normalized).decode() if normalized is not None else None,
                 utc_now(), proposal_id, expected),
            )
            return cur.rowcount == 1

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            return dict(row) if row is not None else None

    def append_research_event(self, event_type: str, subject_id: str,
                              payload: dict[str, Any], *, event_id: str | None = None) -> str:
        event_id = event_id or sha256({"type": event_type, "subject": subject_id, "payload": payload})
        with self.immediate() as db:
            db.execute("INSERT OR IGNORE INTO research_events(event_id,event_type,subject_id,payload_json,created_at) VALUES(?,?,?,?,?)",
                       (event_id, event_type, subject_id, canonical_json(payload).decode(), utc_now()))
        return event_id

    def research_event(self, event_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM research_events WHERE event_id=?", (event_id,)).fetchone()
            return dict(row) if row is not None else None

    def prepare_probe_run(self, *, effect_id: str, work_id: str, proposal_id: str,
                          actor_id: str, goal_id: str, goal_hash: str,
                          request: dict[str, Any]) -> bool:
        for value, name in ((effect_id, "effect_id"), (work_id, "work_id"),
                            (proposal_id, "proposal_id"), (actor_id, "actor_id"),
                            (goal_id, "goal_id")):
            require_id(value, name)
        require_sha(goal_hash, "goal_hash")
        raw = canonical_json(request).decode(); digest = sha256(request); now = utc_now()
        expected = (effect_id, work_id, proposal_id, actor_id, goal_id, goal_hash,
                    digest, raw)
        with self.immediate() as db:
            rows = db.execute("SELECT * FROM probe_runs WHERE effect_id=? OR work_id=?",
                              (effect_id, work_id)).fetchall()
            if rows:
                if any(tuple(row[key] for key in (
                        "effect_id", "work_id", "proposal_id", "actor_id", "goal_id",
                        "goal_hash", "request_hash", "request_json")) != expected for row in rows):
                    raise StoreError("probe run replay conflict")
                return False
            db.execute("INSERT INTO probe_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (*expected, "queued", None, None, now, now))
            return True

    def settle_probe_run(self, *, work_id: str, result: dict[str, Any],
                         result_hash: str) -> bool:
        require_sha(result_hash, "result_hash")
        raw = canonical_json(result).decode()
        with self.immediate() as db:
            row = db.execute("SELECT * FROM probe_runs WHERE work_id=?", (work_id,)).fetchone()
            if row is None:
                raise StoreError("probe work is unknown")
            if row["state"] == "completed":
                if row["result_hash"] != result_hash or row["result_json"] != raw:
                    raise StoreError("probe result replay conflict")
                return False
            if row["state"] != "queued":
                raise StoreError("probe run state invalid")
            db.execute("UPDATE probe_runs SET state='completed',result_hash=?,result_json=?,"
                       "updated_at=? WHERE work_id=? AND state='queued'",
                       (result_hash, raw, utc_now(), work_id))
            return True

    def save_probe_promotion(self, *, effect_id: str, row_hash: str, actor_id: str,
                             draft: dict[str, Any]) -> bool:
        require_sha(row_hash, "row_hash"); require_id(actor_id, "actor_id")
        promotion_id = draft.get("promotion_id")
        require_id(promotion_id, "promotion_id")
        if (draft.get("draft_only") is not True or draft.get("auto_execute") is not False
                or draft.get("requires_human_claude_review") is not True):
            raise StoreError("probe promotion is not inert")
        raw = canonical_json(draft).decode(); digest = sha256(draft)
        expected = (promotion_id, effect_id, row_hash, actor_id, digest, raw)
        with self.immediate() as db:
            rows = db.execute("SELECT * FROM probe_promotions WHERE promotion_id=? "
                              "OR effect_id=? OR row_hash=?",
                              (promotion_id, effect_id, row_hash)).fetchall()
            if rows:
                if any(tuple(row[key] for key in (
                        "promotion_id", "effect_id", "row_hash", "actor_id",
                        "draft_hash", "draft_json")) != expected for row in rows):
                    raise StoreError("probe promotion replay conflict")
                return False
            db.execute("INSERT INTO probe_promotions VALUES(?,?,?,?,?,?,?)",
                       (*expected, utc_now()))
            return True

    def get_or_create_incident(self, incident_id: str, fingerprint: str, *, severity: str,
                               evidence: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        with self.immediate() as db:
            existing = db.execute("SELECT * FROM incidents WHERE fingerprint=? AND state NOT IN ('resolved','quarantined')",
                                  (fingerprint,)).fetchone()
            if existing is not None:
                return dict(existing), False
            if db.execute("SELECT 1 FROM incidents WHERE incident_id=?", (incident_id,)).fetchone():
                incident_id = incident_id + "-" + sha256(now.encode())[:8]
            db.execute("INSERT INTO incidents VALUES(?,?,?,?,?,?,?,?)",
                       (incident_id, fingerprint, "detected", severity,
                        canonical_json(evidence).decode(), 0, now, now))
            return dict(db.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()), True

    def update_incident(self, incident_id: str, expected: str, new: str,
                        *, increment_action: bool = False) -> bool:
        with self.immediate() as db:
            cur = db.execute("UPDATE incidents SET state=?,action_count=action_count+?,updated_at=? WHERE incident_id=? AND state=?",
                             (new, 1 if increment_action else 0, utc_now(), incident_id, expected))
            return cur.rowcount == 1

    def create_mission(self, mission_id: str, *, risk: str, payload: dict[str, Any],
                       base_release: str, dependencies: tuple[str, ...] = (),
                       max_attempts: int = 3) -> bool:
        """Create one immutable mission intent, accepting only exact replays.

        Health reconciliation can crash after committing the mission and before
        moving its incident to ``mission_queued``.  Retrying that crash window must
        return the already committed intent, while a reused deterministic id with
        different authority must fail closed.
        """
        now = utc_now()
        payload_json = canonical_json(payload).decode()
        with self.immediate() as db:
            prior = db.execute("SELECT * FROM missions WHERE mission_id=?",
                               (mission_id,)).fetchone()
            if prior is not None:
                prior_deps = tuple(row["depends_on"] for row in db.execute(
                    "SELECT depends_on FROM mission_deps WHERE mission_id=? "
                    "ORDER BY depends_on", (mission_id,)).fetchall())
                if (prior["risk"] != risk or prior["payload_json"] != payload_json
                        or prior["base_release"] != base_release
                        or int(prior["max_attempts"]) != max_attempts
                        or prior_deps != tuple(sorted(dependencies))):
                    raise StoreError("mission_id replayed with different intent")
                return False
            db.execute("INSERT INTO missions(mission_id,state,risk,payload_json,base_release,max_attempts,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                       (mission_id, MissionState.QUEUED.value, risk,
                        payload_json, base_release, max_attempts, now, now))
            for dep in dependencies:
                if dep == mission_id:
                    raise StoreError("mission cannot depend on itself")
                db.execute("INSERT INTO mission_deps VALUES(?,?)", (mission_id, dep))
            if self._has_cycle(db):
                raise StoreError("mission dependency cycle")
            return True

    def upsert_service_status(self, *, label: str, release_id: str, status: str,
                              semantic_ok: bool, detail: dict[str, Any],
                              checked_at: str) -> bool:
        """Store the newest independently observed service fact.

        Exact replays are no-ops, older observations cannot roll the cockpit back,
        and two different observations at the same logical instant are treated as a
        producer conflict instead of last-writer-wins.  Trust evaluation belongs to
        ``health_runtime``; this method is the durable compare-and-swap boundary.
        """
        require_id(label, "service_label")
        require_id(release_id, "release_id")
        allowed = {"healthy", "idle", "blocked", "stale", "recovering",
                   "mission_queued", "needs_human", "quarantined"}
        if status not in allowed:
            raise StoreError("invalid service status")
        if type(semantic_ok) is not bool or not isinstance(detail, dict):
            raise StoreError("invalid service semantic observation")
        try:
            observed = datetime.fromisoformat(checked_at)
        except (TypeError, ValueError) as exc:
            raise StoreError("invalid service checked_at") from exc
        if observed.tzinfo is None:
            raise StoreError("service checked_at must be timezone-aware")
        checked_at = observed.astimezone(timezone.utc).isoformat(timespec="microseconds")
        detail_json = canonical_json(detail).decode()
        with self.immediate() as db:
            prior = db.execute("SELECT * FROM services WHERE label=?", (label,)).fetchone()
            if prior is not None:
                prior_at = datetime.fromisoformat(prior["checked_at"]).astimezone(timezone.utc)
                if observed.astimezone(timezone.utc) < prior_at:
                    return False
                same = (prior["release_id"] == release_id and prior["status"] == status
                        and bool(prior["semantic_ok"]) is semantic_ok
                        and prior["detail_json"] == detail_json)
                if observed.astimezone(timezone.utc) == prior_at:
                    if same:
                        return False
                    raise StoreError("service observation conflicts at checked_at")
                db.execute(
                    "UPDATE services SET release_id=?,status=?,semantic_ok=?,"
                    "detail_json=?,checked_at=? WHERE label=?",
                    (release_id, status, int(semantic_ok), detail_json, checked_at, label),
                )
                return True
            db.execute("INSERT INTO services VALUES(?,?,?,?,?,?)",
                       (label, release_id, status, int(semantic_ok), detail_json,
                        checked_at))
            return True

    @staticmethod
    def _has_cycle(db: sqlite3.Connection) -> bool:
        rows = db.execute("SELECT mission_id,depends_on FROM mission_deps").fetchall()
        graph: dict[str, list[str]] = {}
        for row in rows:
            graph.setdefault(row["mission_id"], []).append(row["depends_on"])
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in done:
                return False
            visiting.add(node)
            if any(visit(dep) for dep in graph.get(node, [])):
                return True
            visiting.remove(node)
            done.add(node)
            return False
        return any(visit(node) for node in graph)

    def claim_mission(self, worker_id: str, *, lease_seconds: int = 300) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        until = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self.immediate() as db:
            row = db.execute(
                "SELECT m.* FROM missions m WHERE m.state='queued' AND m.attempt<m.max_attempts "
                "AND NOT EXISTS (SELECT 1 FROM mission_deps d JOIN missions p ON p.mission_id=d.depends_on "
                "WHERE d.mission_id=m.mission_id AND p.state!='released') ORDER BY m.created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            token = int(row["fencing_token"]) + 1
            db.execute("UPDATE missions SET state='claimed',worker_id=?,attempt=attempt+1,fencing_token=?,lease_until=?,heartbeat_at=?,updated_at=? WHERE mission_id=? AND state='queued'",
                       (worker_id, token, until, now.isoformat(), now.isoformat(), row["mission_id"]))
            out = dict(row)
            out.update(state="claimed", worker_id=worker_id, fencing_token=token,
                       attempt=int(row["attempt"]) + 1, lease_until=until)
            out["payload"] = json.loads(out.pop("payload_json"))
            return out

    def ready_missions(self) -> list[dict[str, Any]]:
        """Return dependency-ready missions without acquiring a second lease.

        Execution leases live in the root Work broker.  The control database is
        only the durable intent/index, so Operator performs enqueue-first and a
        compare-and-swap below.  Repeating the same enqueue after a crash is
        byte-idempotent.
        """
        with self.connect() as db:
            rows = db.execute(
                "SELECT m.* FROM missions m WHERE m.state='queued' "
                "AND m.attempt<m.max_attempts "
                "AND NOT EXISTS (SELECT 1 FROM mission_deps d "
                "JOIN missions p ON p.mission_id=d.depends_on "
                "WHERE d.mission_id=m.mission_id AND p.state!='released') "
                "ORDER BY m.created_at, m.mission_id"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            value["payload"] = json.loads(value.pop("payload_json"))
            result.append(value)
        return result

    def mark_mission_enqueued(self, mission_id: str, *, expected_attempt: int,
                              fencing_token: int) -> bool:
        if expected_attempt < 1 or fencing_token < 1:
            raise StoreError("mission enqueue identity invalid")
        with self.immediate() as db:
            cur = db.execute(
                "UPDATE missions SET state='running',worker_id='abcr-operator',"
                "attempt=?,fencing_token=?,lease_until=NULL,heartbeat_at=?,updated_at=? "
                "WHERE mission_id=? AND state='queued' AND attempt=? "
                "AND fencing_token=? AND attempt<max_attempts",
                (expected_attempt, fencing_token, utc_now(), utc_now(), mission_id,
                 expected_attempt - 1, fencing_token - 1),
            )
            return cur.rowcount == 1

    def settle_mission_pipeline(self, mission_id: str, outcome: str) -> bool:
        """CAS one broker-pipeline terminal fact into the mission read model."""
        if outcome not in {"released", "failed", "needs_human", "quarantined"}:
            raise StoreError("mission terminal outcome invalid")
        with self.immediate() as db:
            cur = db.execute(
                "UPDATE missions SET state=?,worker_id=NULL,lease_until=NULL,updated_at=? "
                "WHERE mission_id=? AND state IN ('running','verifying')",
                (outcome, utc_now(), mission_id),
            )
            return cur.rowcount == 1

    def heartbeat_mission(self, mission_id: str, worker_id: str, fencing_token: int,
                          *, lease_seconds: int = 300) -> bool:
        now = datetime.now(timezone.utc)
        until = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self.immediate() as db:
            cur = db.execute("UPDATE missions SET heartbeat_at=?,lease_until=?,updated_at=? WHERE mission_id=? AND worker_id=? AND fencing_token=? AND state IN ('claimed','running','verifying')",
                             (now.isoformat(), until, now.isoformat(), mission_id, worker_id, fencing_token))
            return cur.rowcount == 1

    def transition_mission(self, mission_id: str, fencing_token: int,
                           expected: str, new: str) -> bool:
        allowed = {
            "claimed": {"running", "failed", "quarantined", "needs_human"},
            "running": {"verifying", "failed", "quarantined", "needs_human"},
            "verifying": {"released", "failed", "quarantined", "needs_human"},
        }
        if new not in allowed.get(expected, set()):
            raise StoreError(f"invalid mission transition {expected}->{new}")
        with self.immediate() as db:
            cur = db.execute("UPDATE missions SET state=?,updated_at=? WHERE mission_id=? AND fencing_token=? AND state=?",
                             (new, utc_now(), mission_id, fencing_token, expected))
            return cur.rowcount == 1

    def recover_expired_missions(self) -> tuple[int, int]:
        """Return (requeued, quarantined) without letting poison block ready work."""
        now = utc_now()
        with self.immediate() as db:
            quarantined = db.execute(
                "UPDATE missions SET state='quarantined',worker_id=NULL,lease_until=NULL,updated_at=? "
                "WHERE state IN ('claimed','running','verifying') AND lease_until<? AND attempt>=max_attempts",
                (now, now),
            ).rowcount
            requeued = db.execute(
                "UPDATE missions SET state='queued',worker_id=NULL,lease_until=NULL,updated_at=? "
                "WHERE state IN ('claimed','running','verifying') AND lease_until<? AND attempt<max_attempts",
                (now, now),
            ).rowcount
            return requeued, quarantined

    def rows(self, table: str) -> list[dict[str, Any]]:
        if table not in {"inbox", "actions", "outbox", "proposals", "upload_sessions",
                         "research_events", "incidents", "missions", "services", "releases",
                         "approval_claims", "approval_decisions", "approval_requests",
                         "approval_imports", "dispatch_claims",
                         "dispatch_claim_imports", "dispatch_requests",
                         "round_reports", "round_reflections", "goal_drafts",
                         "probe_runs", "probe_promotions"}:
            raise StoreError("table is not readable")
        with self.connect() as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table}").fetchall()]
