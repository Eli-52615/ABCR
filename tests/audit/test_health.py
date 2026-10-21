"""tests/audit/test_health.py —— A1-6 item4 健康面板。"""
from __future__ import annotations

import json
from pathlib import Path

from abcr.audit import health


def _run_with_flags(tmp_path: Path, flags_per_step: list[list[str]]) -> list[Path]:
    run_dir = tmp_path / "data" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    lines = []
    for i, flags in enumerate(flags_per_step):
        lines.append(json.dumps({"run_id": "r1", "item_id": f"g{i:02d}",
                                 "safety_flags": flags}, ensure_ascii=False))
    (run_dir / "steps.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [run_dir]


def test_clean_batch_all_rates_zero(fixture_repo: Path) -> None:
    from abcr.audit import auditor
    run_dirs = [fixture_repo / "data" / "runs" / r
                for r in auditor.runs_of_batch(fixture_repo, "B-20260714T090000Z-0001")]
    item, breached = health.health_panel(run_dirs)
    assert item.verdict == "PASS" and not breached
    assert all("0.0000" in e or "总 step" in e for e in item.evidence)


def test_breach_triggers_quarantine_intent(tmp_path: Path) -> None:
    # 10 步中 3 步 parse_fail → 0.30 > 阈 0.20 → 超阈
    flags = [["parse_fail"]] * 3 + [[]] * 7
    run_dirs = _run_with_flags(tmp_path, flags)
    item, breached = health.health_panel(run_dirs)
    assert breached and item.verdict == "FAIL"
    assert "QUARANTINED" in (item.disposition or "")
    assert any("parse_fail" in e and "超阈" in e for e in item.evidence)


def test_env_threshold_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ABCR_HEALTH_PARSE_FAIL_MAX", "0.40")
    flags = [["parse_fail"]] * 3 + [[]] * 7   # 0.30，此时阈 0.40 不超
    run_dirs = _run_with_flags(tmp_path, flags)
    item, breached = health.health_panel(run_dirs)
    assert not breached and item.verdict == "PASS"


def test_rates_computation() -> None:
    thr = health.thresholds()
    assert thr["empty"] == 0.05 and thr["truncated"] == 0.30
