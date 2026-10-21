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

from abcr.control.contracts import MissionState, canonical_json, sha256, utc_now

SCHEMA_VERSION = 2

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
  state TEXT NOT NULL, payload_hash TEXT NOT NULL, result_json TEXT,
  worker_id TEXT, lease_until TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
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
                       payload: dict[str, Any]) -> bool:
        now = utc_now()
        with self.immediate() as db:
            cur = db.execute(
                "INSERT OR IGNORE INTO actions(effect_id,command_id,intent,state,payload_hash,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (effect_id, command_id, intent, "queued", sha256(payload), now, now),
            )
            return cur.rowcount == 1

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
                       max_attempts: int = 3) -> None:
        now = utc_now()
        with self.immediate() as db:
            db.execute("INSERT INTO missions(mission_id,state,risk,payload_json,base_release,max_attempts,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                       (mission_id, MissionState.QUEUED.value, risk,
                        canonical_json(payload).decode(), base_release, max_attempts, now, now))
            for dep in dependencies:
                if dep == mission_id:
                    raise StoreError("mission cannot depend on itself")
                db.execute("INSERT INTO mission_deps VALUES(?,?)", (mission_id, dep))
            if self._has_cycle(db):
                raise StoreError("mission dependency cycle")

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
                         "approval_claims", "approval_decisions"}:
            raise StoreError("table is not readable")
        with self.connect() as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table}").fetchall()]
