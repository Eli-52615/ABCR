"""tests/audit/test_auditor_v0.py —— A1-6 auditor item1/2 + 编排 + fail-safe。"""
from __future__ import annotations

import json
from pathlib import Path

from abcr.audit import auditor
from abcr.audit.rescore import rescore_run

BATCH_ID = "B-20260714T090000Z-0001"


def _rescore_all(repo: Path) -> None:
    for rid in auditor.runs_of_batch(repo, BATCH_ID):
        rescore_run(repo / "data" / "runs" / rid)


def test_item1_pass_on_clean_batch(fixture_repo: Path) -> None:
    _rescore_all(fixture_repo)
    report = auditor.audit_batch(fixture_repo, BATCH_ID, items=(1,))
    it = report.items[0]
    assert it.id == 1 and it.verdict == "PASS", it.evidence


def test_item1_detects_missing_manifest(fixture_repo: Path) -> None:
    _rescore_all(fixture_repo)
    rid = auditor.runs_of_batch(fixture_repo, BATCH_ID)[0]
    (fixture_repo / "data" / "runs" / rid / "manifest.json").unlink()
    report = auditor.audit_batch(fixture_repo, BATCH_ID, items=(1,))
    assert report.items[0].verdict == "FAIL"
    assert any("manifest.json 缺失" in e for e in report.items[0].evidence)


def test_item1_detects_config_hash_drift(fixture_repo: Path) -> None:
    _rescore_all(fixture_repo)
    rid = auditor.runs_of_batch(fixture_repo, BATCH_ID)[0]
    mp = fixture_repo / "data" / "runs" / rid / "manifest.json"
    m = json.loads(mp.read_text())
    m["config_hash"] = "0" * 64
    mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    report = auditor.audit_batch(fixture_repo, BATCH_ID, items=(1,))
    assert report.items[0].verdict == "FAIL"
    assert any("config_hash" in e for e in report.items[0].evidence)


def test_item2_three_way_match(fixture_repo: Path) -> None:
    _rescore_all(fixture_repo)
    report = auditor.audit_batch(fixture_repo, BATCH_ID, items=(2,))
    it = report.items[0]
    assert it.verdict == "PASS", it.evidence
    assert any("已知错误分布" in e for e in it.evidence), "g03/g07 呈现句缺失"


def test_item2_detects_rescore_disagreement(fixture_repo: Path) -> None:
    """篡改一条 deterministic_v1 分 → 与 rescore 不一致 → item2 FAIL 附 output_text。"""
    _rescore_all(fixture_repo)
    rid = auditor.runs_of_batch(fixture_repo, BATCH_ID)[0]
    sp = fixture_repo / "data" / "runs" / rid / "scores.jsonl"
    rows = [json.loads(l) for l in sp.read_text().splitlines() if l.strip()]
    for r in rows:
        if r["scorer_id"] == "deterministic_v1" and r["item_id"] == "g01":
            r["metric_value"] = 0  # 本应 1
            break
    sp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    report = auditor.audit_batch(fixture_repo, BATCH_ID, items=(2,))
    assert report.items[0].verdict == "FAIL"
    assert any("output_text" in e for e in report.items[0].evidence)


def test_orchestration_all_items_pass_and_apply(fixture_repo: Path) -> None:
    _rescore_all(fixture_repo)
    report = auditor.audit_batch(fixture_repo, BATCH_ID, items=(1, 2, 4), apply=True)
    assert report.overall == "PASS"
    # 落账后 6 run 末事件 run_accepted、批次 batch_audited
    from abcr.common.ledger_ref import RunLedger
    last = {}
    for e in RunLedger(fixture_repo / "ledger", "runs_index").events():
        last[e.get("subject_id")] = e.get("event")
    assert set(last.values()) == {"run_accepted"}
    blast = [e.get("event") for e in RunLedger(fixture_repo / "ledger", "batches").events()]
    assert blast[-1] == "batch_audited"


def test_fail_safe_on_corrupt_manifest(fixture_repo: Path) -> None:
    """坏 manifest（非 JSON）不让审计器崩溃，转该项 FAIL。"""
    _rescore_all(fixture_repo)
    rid = auditor.runs_of_batch(fixture_repo, BATCH_ID)[0]
    (fixture_repo / "data" / "runs" / rid / "manifest.json").write_text("{ broken", encoding="utf-8")
    report = auditor.audit_batch(fixture_repo, BATCH_ID, items=(1,))  # 不抛异常
    assert report.items[0].verdict == "FAIL"
