"""Notification retry/cooldown journal; notifications never repeat experiment effects."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from abcr.control.contracts import sha256
from abcr.control.store import ControlStore


def schedule_notification(store: ControlStore, *, topic: str, subject_id: str,
                          payload: dict[str, Any], destination: str,
                          cooldown_bucket: str) -> str:
    effect_id = sha256({"kind": "notification", "topic": topic, "subject": subject_id,
                        "bucket": cooldown_bucket, "payload": payload})
    store.enqueue_outbox(effect_id, destination, payload)
    return effect_id
