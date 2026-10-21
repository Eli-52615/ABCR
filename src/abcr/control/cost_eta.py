"""Hash-bound cost/ETA estimates that become UNKNOWN when stale."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from abcr.control.contracts import sha256


@dataclass(frozen=True)
class CostEta:
    state: str
    estimated_cost_usd: float | None
    eta_seconds: int | None
    input_hash: str
    profile_hash: str
    calculated_at: str
    valid_until: str
    estimate_hash: str


def estimate(envelope: dict[str, Any], profile: dict[str, Any], *,
             now: datetime | None = None) -> CostEta:
    now = now or datetime.now(timezone.utc)
    required = {"usd_per_million_input_tokens", "usd_per_million_output_tokens",
                "seconds_per_item", "valid_until"}
    if not required.issubset(profile):
        return _unknown(envelope, profile, now)
    try: profile_until = datetime.fromisoformat(profile["valid_until"])
    except (TypeError, ValueError): return _unknown(envelope, profile, now)
    if profile_until.tzinfo is None or now >= profile_until: return _unknown(envelope, profile, now)
    items = len(envelope.get("item_ids", [])); seeds = len(envelope.get("seeds", []))
    arms = len(envelope.get("arms", [])); calls = items * seeds * arms
    in_tokens = calls * int(profile.get("input_tokens_per_call", 1024))
    out_tokens = calls * int(profile.get("output_tokens_per_call", 256))
    cost = in_tokens / 1_000_000 * float(profile["usd_per_million_input_tokens"])
    cost += out_tokens / 1_000_000 * float(profile["usd_per_million_output_tokens"])
    eta = int(calls * float(profile["seconds_per_item"]))
    core = {"state": "KNOWN", "estimated_cost_usd": round(cost, 4), "eta_seconds": eta,
            "input_hash": sha256(envelope), "profile_hash": sha256(profile),
            "calculated_at": now.isoformat(), "valid_until": profile_until.isoformat()}
    return CostEta(**core, estimate_hash=sha256(core))


def _unknown(envelope: dict[str, Any], profile: dict[str, Any], now: datetime) -> CostEta:
    core = {"state": "UNKNOWN", "estimated_cost_usd": None, "eta_seconds": None,
            "input_hash": sha256(envelope), "profile_hash": sha256(profile),
            "calculated_at": now.isoformat(), "valid_until": now.isoformat()}
    return CostEta(**core, estimate_hash=sha256(core))
