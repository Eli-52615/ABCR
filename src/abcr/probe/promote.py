"""Promotion creates an inert human-review draft and an auditable exclusion set."""
from __future__ import annotations

from typing import Any

from abcr.control.contracts import ContractError, sha256, utc_now
from abcr.probe.notebook import ProbeNotebook


def promote_probe(row_hashes: list[str], notebook: ProbeNotebook, *, actor_id: str,
                  human_confirmed: bool) -> dict[str, Any]:
    if not human_confirmed:
        raise ContractError("promotion_not_confirmed", "毕业必须由人明确确认")
    if not row_hashes or len(row_hashes) != len(set(row_hashes)):
        raise ContractError("bad_promotion_rows", "毕业行必须非空且去重")
    rows = [notebook.read(row_hash) for row_hash in row_hashes]
    goal_hashes = {row["goal_hash"] for row in rows}
    if len(goal_hashes) != 1:
        raise ContractError("promotion_goal_mismatch", "一次毕业只能来自同一目标")
    excluded_items = sorted({row["item_id"] for row in rows})
    core = {"draft_only": True, "auto_execute": False, "requires_human_claude_review": True,
            "source_goal_hash": next(iter(goal_hashes)), "source_probe_rows": sorted(row_hashes),
            "excluded_item_ids": excluded_items, "confirmed_by": actor_id,
            "created_at": utc_now()}
    return dict(core, promotion_id="PROM-" + sha256(core)[:20])
