"""tests/audit/test_e_rootcause_closure.py —— 组E 四根因闭合回归。

覆盖：①外部信任根（item1 step_chain 封印，citable 缺锚 FAIL / non_citable 注记）、
②空/缺失被当成功（overall 全 SKIP → FAIL；git_clean 缺字段 → FAIL）、
③验船师问运动员（contamination dev-only 改由 ABCR_PHASE 驱动，批自述 none 不豁免）、
④判据只在文档没接线（budget 超 cap → item6 FAIL；--apply 幂等）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from abcr.audit import auditor, budget_recon as br, contamination as con, version_check as vc
from abcr.audit.report import AuditItem, AuditReport
from abcr.audit.rescore import rescore_run
from abcr.common import external_seal
from abcr.common.ledger_ref import RunLedger

BATCH_ID = "B-20260714T090000Z-0001"


def _report(*verdicts: str) -> AuditReport:
    r = AuditReport(batch_id="B", generated_at="t", thresholds={})
    for i, v in enumerate(verdicts, start=1):
        r.items.append(AuditItem.make(i, v, ["ev"]))
    return r


# ---- 根因②：overall 实质项地板 ----

def test_overall_all_skip_is_fail() -> None:
    assert _report("SKIP", "SKIP", "SKIP").overall == "FAIL"


def test_overall_empty_is_fail() -> None:
    assert _report().overall == "FAIL"


def test_overall_one_pass_rest_skip_is_pass() -> None:
    assert _report("SKIP", "PASS", "SKIP").overall == "PASS"


# ---- 根因②：git_clean 缺字段即 FAIL ----

def test_git_clean_missing_field_fails(tmp_path: Path) -> None:
    rd = tmp_path / "data" / "runs" / "r1"
    rd.mkdir(parents=True)
    # 无 git_clean 键
    (rd / "manifest.json").write_text(json.dumps(
        {"non_citable": True, "code_tree_hash": "x", "env_lock_ref": "e"}), encoding="utf-8")
    item = vc.version_consistency_item(tmp_path, BATCH_ID, ["r1"])
    assert item.verdict == "FAIL"
    assert any("缺 git_clean" in e for e in item.evidence), item.evidence


# ---- 根因③：dev-only 由 ABCR_PHASE 驱动，自述 none 不豁免 ----

def _seed_nondev_run(repo: Path) -> str:
    # 找一个 golden10 公式下归属 != dev 的 item_id
    iid = next(i for i in (f"g{n:02d}" for n in range(1, 99))
               if con.split_bucket("golden10", i) != "dev")
    rd = repo / "data" / "runs" / "run-1"
    rd.mkdir(parents=True)
    (rd / "steps.jsonl").write_text(
        json.dumps({"item_id": iid, "split_hash": "a" * 64, "benchmark": "golden10"}) + "\n",
        encoding="utf-8")
    # 批自述 splits=["none"]（试图豁免）
    (repo / "fixtures").mkdir(exist_ok=True)
    (repo / "fixtures" / "envelope_fixture.json").write_text(json.dumps(
        {"batch_id": BATCH_ID, "scope": {"splits": ["none"]}}), encoding="utf-8")
    return iid


def test_confirmation_phase_enforces_dev_despite_none_declaration(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_nondev_run(tmp_path)
    monkeypatch.setenv("ABCR_PHASE", "confirmation")
    verdict, ev = con.check_split_hash(tmp_path, BATCH_ID, ["run-1"])
    assert verdict == "FAIL", ev
    assert any("非 dev" in e for e in ev), ev


def test_exploration_phase_none_not_enforced(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_nondev_run(tmp_path)
    monkeypatch.delenv("ABCR_PHASE", raising=False)
    verdict, ev = con.check_split_hash(tmp_path, BATCH_ID, ["run-1"])
    assert verdict == "PASS", ev


# ---- 根因（evasion）：全字段扫描堵住"藏进别的键" ----

def test_leak_hidden_under_nonmessages_key_is_caught(tmp_path: Path) -> None:
    logs = tmp_path / "data" / "runs" / "run-1" / "logs"
    logs.mkdir(parents=True)
    # inject 藏在 "notes" 键而非 messages
    (logs / "judge_calls.jsonl").write_text(json.dumps({
        "messages": [{"role": "user", "content": "clean question"}],
        "notes": "arm=inject coefficient=8",
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    verdict, ev = con.check_judge_structure(tmp_path, ["run-1"])
    assert verdict == "FAIL", ev
    assert any("inject" in e for e in ev), ev


def test_pos_neg_boundary_no_false_positive(tmp_path: Path) -> None:
    logs = tmp_path / "data" / "runs" / "run-1" / "logs"
    logs.mkdir(parents=True)
    # "compose" 含子串 "pos"，"assignment" 含 "neg"? 用明确的裸子串诱饵
    (logs / "judge_calls.jsonl").write_text(json.dumps({
        "messages": [{"role": "user", "content": "Please compose a response; a negligible detail."}],
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    verdict, ev = con.check_judge_structure(tmp_path, ["run-1"])
    assert verdict == "PASS", ev


# ---- 根因④：budget 超 cap → item6 FAIL ----

def test_budget_over_cap_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ABCR_BUDGET_CAP_CNY", "100")
    costs = RunLedger(tmp_path / "ledger", "costs")
    costs.append("run_cost_estimated", subject_id="r1", batch_id=BATCH_ID,
                 amount_cny=100.0, basis="t")
    costs.append("run_cost_actual", subject_id="r1", batch_id=BATCH_ID,
                 amount_cny=105.0, basis="t")  # 超 cap 100
    item = br.budget_recon_item(tmp_path, BATCH_ID, ["r1"])
    assert item.verdict == "FAIL"
    assert any("超线" in e for e in item.evidence), item.evidence


# ---- 根因④/幂等：--apply 二次调用不重复落账 ----

def test_apply_is_idempotent(fixture_repo: Path) -> None:
    for rid in auditor.runs_of_batch(fixture_repo, BATCH_ID):
        rescore_run(fixture_repo / "data" / "runs" / rid)

    def _count() -> tuple[int, int]:
        idx = list(RunLedger(fixture_repo / "ledger", "runs_index").events())
        acc = sum(1 for e in idx if e.get("event") == "run_accepted")
        bat = sum(1 for e in RunLedger(fixture_repo / "ledger", "batches").events()
                  if e.get("event") == "batch_audited")
        return acc, bat

    auditor.audit_batch(fixture_repo, BATCH_ID, items=(1, 2, 4), apply=True)
    acc1, bat1 = _count()
    auditor.audit_batch(fixture_repo, BATCH_ID, items=(1, 2, 4), apply=True)
    acc2, bat2 = _count()
    assert (acc1, bat1) == (acc2, bat2), f"二次 apply 重复落账: {(acc1, bat1)} -> {(acc2, bat2)}"


# ---- 根因①：item1 citable 缺锚 FAIL / non_citable 注记 ----

def test_item1_citable_missing_seal_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 隔离锚存储到空目录，保证无锚
    monkeypatch.setenv(external_seal.ANCHOR_STORE_ENV, str(tmp_path / "anchors" / "seals.jsonl"))
    rd = tmp_path / "data" / "runs" / "r1"
    rd.mkdir(parents=True)
    steps = [{"item_id": "g01"}]
    (rd / "steps.jsonl").write_text(
        "\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8")
    # citable manifest（non_citable=False）无 step_chain 封印
    (rd / "manifest.json").write_text(json.dumps({"non_citable": False}), encoding="utf-8")
    seal_digest, seal_length = external_seal.chain_digest_and_length(steps)
    ok = external_seal.latest_seal(external_seal.KIND_STEP_CHAIN, "r1")
    assert ok is None  # 隔离后确无锚
    v_ok, why = external_seal.verify(external_seal.KIND_STEP_CHAIN, "r1", seal_digest, seal_length)
    assert not v_ok and "no external seal" in why


def test_item1_seal_roundtrip_verifies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(external_seal.ANCHOR_STORE_ENV, str(tmp_path / "anchors" / "seals.jsonl"))
    steps = [{"item_id": "g01", "x": 1}, {"item_id": "g02", "x": 2}]
    digest, length = external_seal.chain_digest_and_length(steps)
    external_seal.seal(external_seal.KIND_STEP_CHAIN, "r1", digest, length)
    ok, why = external_seal.verify(external_seal.KIND_STEP_CHAIN, "r1", digest, length)
    assert ok, why
    # 篡改一条 → length 同但 digest 变 → 失配
    bad_digest, bad_len = external_seal.chain_digest_and_length(
        [{"item_id": "g01", "x": 999}, {"item_id": "g02", "x": 2}])
    ok2, why2 = external_seal.verify(external_seal.KIND_STEP_CHAIN, "r1", bad_digest, bad_len)
    assert not ok2 and "digest mismatch" in why2
