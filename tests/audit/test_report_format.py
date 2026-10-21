"""tests/audit/test_report_format.py —— A1-7 报告格式（JSON schema + MD 同源）。"""
from __future__ import annotations

import json
from pathlib import Path

from abcr.audit.report import AuditItem, AuditReport


def _sample() -> AuditReport:
    return AuditReport(
        batch_id="B-20260714T090000Z-0001",
        generated_at="2026-07-14T12:00:00+00:00",
        thresholds={"parse_fail": 0.2, "refusal": 0.2, "truncated": 0.3,
                    "empty": 0.05, "repetition": 0.2},
        items=[
            AuditItem.make(1, "PASS", ["manifest 22/22 键齐"]),
            AuditItem.make(2, "PASS", ["三方一致", "g03/g07 已知错误分布"]),
            AuditItem.make(4, "PASS", ["parse_fail 0.0000 (阈 0.2)"]),
        ],
        evidence_pointers={"ledger_tail": {"runs_index": "abc"}, "runs": ["data/runs/x"]},
    )


def test_json_schema_fields() -> None:
    d = _sample().to_dict()
    for k in ("audit_schema_version", "batch_id", "generated_at", "auditor_version",
              "thresholds", "items", "overall", "evidence_pointers"):
        assert k in d
    assert d["overall"] == "PASS"
    for it in d["items"]:
        assert set(it) >= {"id", "name", "verdict", "evidence", "disposition"}


def test_overall_fail_if_any_item_fail() -> None:
    r = _sample()
    r.items[0].verdict = "FAIL"
    assert r.overall == "FAIL"


def test_overall_pass_with_skip_only() -> None:
    r = _sample()
    r.items[0].verdict = "SKIP"
    assert r.overall == "PASS"


def test_md_same_source_as_json() -> None:
    r = _sample()
    md = r.to_md()
    assert "# 审计报告 · B-20260714T090000Z-0001" in md
    assert "✅ PASS" in md
    # MD 逐项渲染自 JSON items
    for it in r.items:
        assert it.name in md
    assert "已知错误分布" in md      # item2 证据行进入 MD
    assert "证据指针" in md


def test_write_produces_both_files(tmp_path: Path) -> None:
    json_p, md_p = _sample().write(tmp_path)
    assert json_p.exists() and md_p.exists()
    # JSON 可解析且 overall 一致
    loaded = json.loads(json_p.read_text(encoding="utf-8"))
    assert loaded["overall"] == "PASS"
    assert loaded["batch_id"] == "B-20260714T090000Z-0001"


def test_skip_requires_reason() -> None:
    """SKIP 项 evidence 非空（SKIP 必附原因）——约定层面校验。"""
    it = AuditItem.make(3, "SKIP", ["item3 属阶段2"])
    assert it.verdict == "SKIP" and it.evidence
