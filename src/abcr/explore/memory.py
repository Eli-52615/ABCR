"""Append-only research memory for human goals, reflections and round lineage."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from abcr.control.contracts import canonical_json, sha256, utc_now


class ResearchMemory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event_type: str, subject_id: str, payload: dict[str, Any],
               *, actor_id: str) -> dict[str, Any]:
        previous = "0" * 64
        if self.path.exists() and self.path.stat().st_size:
            last = self.path.read_text(encoding="utf-8").splitlines()[-1]
            previous = json.loads(last)["entry_hash"]
        core = {"event_type": event_type, "subject_id": subject_id, "actor_id": actor_id,
                "payload": payload, "created_at": utc_now(), "prev_hash": previous}
        row = dict(core, entry_hash=sha256(core))
        with self.path.open("ab") as fh:
            fh.write(canonical_json(row) + b"\n"); fh.flush(); os.fsync(fh.fileno())
        return row

    def verify(self) -> list[dict[str, Any]]:
        previous = "0" * 64
        rows = []
        if not self.path.exists():
            return rows
        for line in self.path.read_bytes().splitlines():
            row = json.loads(line)
            entry = row.pop("entry_hash")
            if row.get("prev_hash") != previous or sha256(row) != entry:
                raise ValueError("research memory hash chain invalid")
            row["entry_hash"] = entry; rows.append(row); previous = entry
        return rows
