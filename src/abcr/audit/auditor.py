"""abcr.audit.auditor —— 审计编排 + item1(manifest) + item2(重评分比对)（A1-6）。

架构位置：包A·验船师侧。输入 batch_id，输出 AuditReport（A1-7）。阶段1 只做 item 1/2/4
（item4 委托 health.py）。fail-safe：任何检查抛异常 = 该项 FAIL 附 traceback 摘要，
绝不让审计器自己崩掉（坑5，验船师恒在场）。处置落账默认 dry-run，--apply 才真写账本（坑13）。
"""
from __future__ import annotations

import hashlib
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from abcr.audit import health as health_mod
from abcr.audit.budget_recon import budget_recon_item, check_fuse
from abcr.audit.contamination import contamination_item
from abcr.audit.rescore import rescore_run
from abcr.audit.report import AuditItem, AuditReport
from abcr.audit.version_check import version_consistency_item
from abcr.common import evidence_floor, external_seal
from abcr.common.ledger_ref import LedgerTampered, RunLedger
from abcr.ledger import schema
from abcr.ledger.statemachine import derive_run_state

# 已处置（终态）事件：--apply 读侧去重据此跳过，保证幂等、绝不重写 append-only 链
_TERMINAL_RUN_EVENTS = frozenset(
    {"run_accepted", "run_quarantined", "run_rejected", "run_cancelled"})

LEDGER_CHAINS = ("runs_index", "batches", "costs", "instances", "protocol")
# §3.8 AMENDMENT-31：manifest 22 必含键
MANIFEST_KEYS = (
    "run_id", "config", "config_hash", "git_commit", "git_clean", "code_tree_hash",
    "model_id", "model_revision", "chat_template_hash", "split_hash", "engine",
    "engine_version", "torch_version", "python_version", "env_lock_ref", "seeds",
    "started_at", "finished_at", "status", "non_citable", "protocol_ref", "batch_id",
)
# run 状态偏序（≥COMPLETED 判据用）
_STATE_RANK = {
    "PLANNED": 0, "QUEUED": 1, "RUNNING": 2, "PAUSED": 2, "FAILED": 2,
    "COMPLETED": 3, "SCORED": 4, "AUDITED": 5,
    "ACCEPTED": 6, "REJECTED": 6, "QUARANTINED": 6, "CANCELLED": 6,
}
FIXTURE_ENVELOPE = "fixtures/envelope_fixture.json"
KNOWN_WRONG = ("g03", "g07")


def _canonical(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def runs_of_batch(repo_root: Path, batch_id: str) -> list[str]:
    """经 runs_index 的 run_registered(batch_id) 折叠该批 run_id（保持首见顺序）。"""
    ledger = RunLedger(repo_root / "ledger", "runs_index")
    out, seen = [], set()
    for ev in ledger.events():
        if ev.get("event") == "run_registered" and ev.get("batch_id") == batch_id:
            rid = ev.get("subject_id")
            if rid and rid not in seen:
                seen.add(rid)
                out.append(rid)
    return out


def _runs_index_events_for(repo_root: Path, rid: str) -> list[dict]:
    ledger = RunLedger(repo_root / "ledger", "runs_index")
    return [e for e in ledger.events() if e.get("subject_id") == rid]


def _verify_all_chains(repo_root: Path) -> list[str]:
    """五链主段 + 云链段（AMENDMENT-2）逐段独立 verify_chain。返回证据行。"""
    evidence = []
    for chain in LEDGER_CHAINS:
        main = repo_root / "ledger" / f"{chain}.jsonl"
        segments = [main] + sorted((repo_root / "ledger").glob(f"cloud-day*/{chain}.jsonl"))
        existing = [p for p in segments if p.exists()]
        if not existing:
            evidence.append(f"链 {chain}: 空链 SKIP")
            continue
        for seg in existing:
            RunLedger(seg.parent, seg.stem).verify_chain()  # 抛 LedgerTampered 则上层捕获
        evidence.append(f"链 {chain}: {len(existing)} 段 verify_chain 通过")
    return evidence


def _expected_item_count(repo_root: Path) -> int:
    golden = json.loads((repo_root / "data" / "golden" / "golden10.json")
                        .read_text(encoding="utf-8"))["items"]
    return len(golden)


def _require_runs(batch_id: str, run_ids: list[str], what: str) -> None:
    """审计项入口的证据地板（根因②）：批内零 run = 无证据可审，绝不是"没问题"。

    实测击穿：对一个从不存在的 batch_id 调 audit_batch，runs_of_batch 返回 []，
    item1/item2/item4 各自"零循环、零 fail"→ 三项全 **真 PASS** → overall=PASS，
    --apply 还会给幽灵批写下 batch_audited(verdict=pass)。fail-closed 在每个
    item 入口掐断：抛 EvidenceError，由 _safe 转成该项 FAIL 并留证据行。
    """
    evidence_floor.require_substantive(len(run_ids), f"{what}（批 {batch_id} 的 run 集）")


def _item1_manifest(repo_root: Path, batch_id: str, run_ids: list[str]) -> AuditItem:
    """item1 · manifest 完整性 + steps/scores schema + 五链 + 生命周期 + config_hash。"""
    _require_runs(batch_id, run_ids, "item1 manifest 完整性")
    evidence: list[str] = []
    fails: list[str] = []
    expected_n = _expected_item_count(repo_root)

    # 五链 verify（批级一次）
    try:
        evidence += _verify_all_chains(repo_root)
    except LedgerTampered as e:
        fails.append(f"账本链断链: {e}")

    total_steps = 0
    for rid in run_ids:
        run_dir = repo_root / "data" / "runs" / rid
        # manifest 22 键
        mpath = run_dir / "manifest.json"
        if not mpath.exists():
            fails.append(f"{rid}: manifest.json 缺失")
            continue
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        missing = [k for k in MANIFEST_KEYS if k not in manifest]
        if missing:
            fails.append(f"{rid}: manifest 缺键 {missing}")
        # config_hash 重算
        cfg = manifest.get("config")
        if isinstance(cfg, dict):
            recomputed = hashlib.sha256(_canonical(cfg).encode()).hexdigest()
            if recomputed != manifest.get("config_hash"):
                fails.append(f"{rid}: config_hash 重算不符 "
                             f"(算 {recomputed[:12]} vs manifest {str(manifest.get('config_hash'))[:12]})")
            elif not rid.endswith(recomputed[:12]):
                fails.append(f"{rid}: run_id 后缀 ≠ config_hash[:12] ({recomputed[:12]})")
        else:
            fails.append(f"{rid}: manifest.config 非 dict")
        # steps 行数 + schema
        steps = _load_jsonl(run_dir / "steps.jsonl")
        total_steps += len(steps)
        if len(steps) != expected_n:
            fails.append(f"{rid}: steps 行数 {len(steps)} ≠ 期望 {expected_n}")
        # 外部信任根：steps 链外部封印校验（根因①：仅链内自洽不足信）。
        # 生产端 StepWriter.finalize 收口时 seal(kind='step_chain', subject_id=run_dir 名)；
        # 此处用同一 chain_digest_and_length 重算并只与规范锚比对——length 防截断、
        # 摘要承诺每条 step 全部内容。citable run 缺锚 = FAIL（可引用证据必须有外部锚）；
        # non_citable（Mac/fixture）产物缺锚降为注记（呈现纪律）。锚存在但失配 = 一律 FAIL。
        seal_digest, seal_length = external_seal.chain_digest_and_length(steps)
        sealed = external_seal.latest_seal(external_seal.KIND_STEP_CHAIN, rid)
        if sealed is None:
            if manifest.get("non_citable") is True:
                evidence.append(f"{rid}: 无 step_chain 外部封印（non_citable 产物，注记）")
            else:
                fails.append(f"{rid}: citable run 缺 step_chain 外部封印"
                             f"（根因①无外部信任根 → FAIL）")
        else:
            seal_ok, seal_why = external_seal.verify(
                external_seal.KIND_STEP_CHAIN, rid, seal_digest, seal_length)
            if not seal_ok:
                fails.append(f"{rid}: step_chain 外部封印失配 {seal_why}")
            else:
                evidence.append(f"{rid}: step_chain 外部封印校验通过（length={seal_length}）")
        for i, st in enumerate(steps):
            res = schema.validate_step(st)
            if not res.ok:
                fails.append(f"{rid}#step{i}: {res.summary()}")
                break
            # 激活抽样：activation_summary 非 null 才需 .npz（fixture 全 null，SKIP）
        # scores schema
        for i, sc in enumerate(_load_jsonl(run_dir / "scores.jsonl")):
            res = schema.validate_score(sc)
            if not res.ok:
                fails.append(f"{rid}#score{i}: {res.summary()}")
                break
        # 生命周期：derive_run_state 无违规 & ≥COMPLETED
        evs = _runs_index_events_for(repo_root, rid)
        state, violations = derive_run_state(evs)
        if violations:
            fails.append(f"{rid}: 生命周期违规 {violations}")
        if state is None or _STATE_RANK.get(state, -1) < _STATE_RANK["COMPLETED"]:
            fails.append(f"{rid}: 终点 {state} < COMPLETED")
        else:
            evidence.append(f"{rid}: manifest {len(MANIFEST_KEYS)}/{len(MANIFEST_KEYS)} 键齐；"
                            f"steps {len(steps)} 行过 schema；生命周期终点 {state}")
    evidence.append(f"批粒度总 steps={total_steps}（期望 {expected_n}×{len(run_ids)} run"
                    f"={expected_n * len(run_ids)}）")
    evidence.append("激活抽样：fixture 全 activation_summary=null，SKIP")
    verdict = "FAIL" if fails else "PASS"
    return AuditItem.make(1, verdict, (fails + evidence) if fails else evidence)


def _is_fixture_batch(repo_root: Path, batch_id: str) -> bool:
    env_p = repo_root / FIXTURE_ENVELOPE
    if not env_p.exists():
        return False
    try:
        return json.loads(env_p.read_text(encoding="utf-8")).get("batch_id") == batch_id
    except (OSError, ValueError):
        return False


def _collect_is_correct(run_dir: Path, scorer_id: str) -> dict[tuple, int]:
    """(item_id, random_seed, condition) → is_correct 值。"""
    out = {}
    for r in _load_jsonl(run_dir / "scores.jsonl"):
        if r.get("scorer_id") == scorer_id and r.get("metric_name") == "is_correct":
            out[(r.get("item_id"), r.get("random_seed"), r.get("condition"))] = r.get("metric_value")
    return out


def _item2_rescore(repo_root: Path, batch_id: str, run_ids: list[str]) -> AuditItem:
    """item2 · 重评分比对：deterministic_v1 vs rescore_v1（+ fixture 批的 expected 三方）。"""
    _require_runs(batch_id, run_ids, "item2 重评分比对")
    fails: list[str] = []
    evidence: list[str] = []
    is_fixture = _is_fixture_batch(repo_root, batch_id)
    expected: dict[tuple, int] = {}
    if is_fixture:
        for r in _load_jsonl(repo_root / "fixtures" / "expected_scores.jsonl"):
            if r.get("metric_name") == "is_correct":
                expected[(r.get("item_id"), r.get("random_seed"), r.get("condition"))] = r.get("metric_value")

    n_cmp = 0
    g_known_consistent = True
    for rid in run_ids:
        run_dir = repo_root / "data" / "runs" / rid
        det = _collect_is_correct(run_dir, "deterministic_v1")
        res = _collect_is_correct(run_dir, "rescore_v1")
        for key, dv in det.items():
            rv = res.get(key)
            if rv is None:
                fails.append(f"{rid} {key}: rescore_v1 缺 is_correct 行")
                continue
            n_cmp += 1
            if dv != rv:
                st = _step_text_for(run_dir, key[0])
                fails.append(f"{rid} {key}: det={dv} rescore={rv} | output_text[:80]={st!r}")
            if is_fixture:
                ev = expected.get(key)
                if ev is not None and not (dv == rv == ev):
                    fails.append(f"{rid} {key}: 三方不一致 det={dv} rescore={rv} expected={ev}")
                # g03/g07 已知错误分布核对
                if key[0] in KNOWN_WRONG and not (dv == rv == 0):
                    g_known_consistent = False
    # 零可比对格 = 无证据（scores 全删也会走到这里）→ 不得判 PASS。
    # 已有具体 fails 时不抛（保留更有诊断价值的证据行，verdict 同样是 FAIL）。
    if not fails:
        evidence_floor.require_substantive(
            n_cmp, f"item2 可比对的 is_correct 格数（批 {batch_id}）")
    evidence.append(f"{len(run_ids)} run × is_correct 比对 {n_cmp} 格 "
                    f"（deterministic_v1 = rescore_v1{' = expected' if is_fixture else ''}）")
    if is_fixture:
        if g_known_consistent:
            evidence.append("g03/g07 判 0 双方一致 —— fixture 设计的已知错误分布，非异常")
        else:
            fails.append("g03/g07 已知错误分布未被一致复算（期望三方均为 0）")
    verdict = "FAIL" if fails else "PASS"
    return AuditItem.make(2, verdict, (fails + evidence) if fails else evidence)


def _step_text_for(run_dir: Path, item_id: str) -> str:
    for st in _load_jsonl(run_dir / "steps.jsonl"):
        if st.get("item_id") == item_id:
            return (st.get("output_text") or "")[:80]
    return ""


def _safe(item_id: int, fn: Callable[[], AuditItem]) -> AuditItem:
    """fail-safe 包裹：异常转该项 FAIL 附 traceback 摘要（坑5）。"""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 —— 验船师恒在场，任何异常都不许崩掉审计器
        tb = traceback.format_exc().strip().splitlines()
        summary = f"{type(e).__name__}: {e} | " + (tb[-1] if tb else "")
        return AuditItem.make(item_id, "FAIL", [f"审计项抛异常（已 fail-safe 捕获）: {summary}"])


def _batch_all_non_citable(repo_root: Path, run_ids: list[str]) -> bool:
    """批内**每个** run 的 manifest 都明确 non_citable=true 才算非可引用批。
    manifest 缺失/坏/未声明 → 按 citable 处理（fail-closed，不给"读不到就宽松"）。"""
    if not run_ids:
        return False
    for rid in run_ids:
        p = repo_root / "data" / "runs" / rid / "manifest.json"
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("non_citable") is not True:
                return False
        except (OSError, ValueError):
            return False
    return True


def _ledger_anchor_status(led: RunLedger) -> tuple[str, str]:
    """本链的规范锚状态：('ok'|'missing'|'mismatch', 说明)。

    锚记录按 (kind='ledger_chain', subject_id=链名) 定位；由于 subject_id 只有链名，
    同一锚存储可能同时被多个 repo_root（演练沙箱/临时仓）写过——故收口方封印时
    （dispatch/cloud 走 guarded_reseal）在 extra.chain_path 写入本链路径做归属判定：
    不是本链路径的锚记录一律视为"本链无锚"（fail-closed 方向：宁可判缺锚，
    绝不拿别人的锚当自己的通过证据）。本函数只 **读** 锚（latest_seal/verify），
    绝不写——验船师无写锚权（V09 P4）。
    """
    rec = external_seal.latest_seal(external_seal.KIND_LEDGER_CHAIN, led.run_id)
    if rec is None:
        return "missing", "规范锚存储中无本链记录"
    if (rec.get("extra") or {}).get("chain_path") != str(led.path):
        return "missing", (f"规范锚存储最新记录属于别的链路径 "
                           f"{(rec.get('extra') or {}).get('chain_path')!r}，非本链")
    ok, why = led.verify_external_seal()
    return ("ok" if ok else "mismatch"), why


def _verify_ledger_anchors(repo_root: Path, lenient: bool) -> tuple[list[str], list[str]]:
    """对 ledger 五链逐条做**外部锚**校验（根因①：链内自洽 ≠ 链外可信）。

    verify_chain 只保证"从 GENESIS 重放自洽"——把 costs.jsonl 尾部几行物理截断
    （抹掉超支记账）后，剩下的仍是一条合法链，内部校验全绿。external_seal 的
    length 承诺是抓这种尾部截断的独立防线；但上一轮它只存在于库与单测里，
    生产审计路径一次都没调过。此处接线：

    - 锚存在 → 必须重算相符（digest 防整链重算，length 防截断）；失配一律 FAIL。
    - 锚缺失 → citable 批 FAIL（可引用证据必须有外部信任根）；
      整批 non_citable（Mac/fixture 产物）降为注记，与 item1 step_chain 同口径。
    """
    fails: list[str] = []
    evidence: list[str] = []
    for chain in LEDGER_CHAINS:
        led = RunLedger(repo_root / "ledger", chain)
        if not led.path.exists():
            evidence.append(f"链 {chain}: 文件不存在，无外部锚可校验（SKIP）")
            continue
        status, why = _ledger_anchor_status(led)
        if status == "ok":
            evidence.append(f"链 {chain}: 外部锚校验通过（{why}）")
        elif status == "mismatch":
            fails.append(f"链 {chain}: 外部锚失配 → {why}"
                         f"（尾部截断/整链重算 → FAIL）")
        elif lenient:
            evidence.append(f"链 {chain}: 缺外部锚（{why}；整批 non_citable，注记）")
        else:
            fails.append(f"链 {chain}: 缺外部锚（{why}）——"
                         f"citable 批的账本链必须有外部信任根 → FAIL")
    return fails, evidence


def _item0_batch_floor(repo_root: Path, batch_id: str, run_ids: list[str]) -> AuditItem:
    """批级证据地板（恒执行，不受 --items 影响）：这批到底有没有东西可审、账本能不能信。

    两查：
      (a) run 集实质性 —— 空 run 集 / 幽灵 batch_id 一律 FAIL（根因②）；
      (b) ledger 五链外部锚 —— 缺锚/失配按 citable 与否判 FAIL 或注记（根因①）。
    本项 substantive=False：它的 PASS 不满足 report.overall 的"≥1 实质 PASS"地板。
    """
    fails: list[str] = []
    evidence: list[str] = []
    try:
        _require_runs(batch_id, run_ids, "批级证据地板")
        evidence.append(f"批 {batch_id}: run 集实质性 OK（{len(run_ids)} run）")
    except evidence_floor.EvidenceError as e:
        fails.append(f"批 {batch_id}: {e} —— 空 run 集/幽灵批次（该 batch_id 在 "
                     f"runs_index 上没有任何 run_registered），无证据可审 → fail-closed")
    lenient = _batch_all_non_citable(repo_root, run_ids)
    f2, e2 = _verify_ledger_anchors(repo_root, lenient)
    fails += f2
    evidence += e2
    return AuditItem.make(0, "FAIL" if fails else "PASS",
                          (fails + evidence) if fails else evidence)


def _ledger_tails(repo_root: Path) -> dict[str, str]:
    out = {}
    for chain in LEDGER_CHAINS:
        p = repo_root / "ledger" / f"{chain}.jsonl"
        if p.exists():
            out[chain] = RunLedger(repo_root / "ledger", chain).snapshot_digest()
    return out


def _run_last_events(repo_root: Path) -> dict[str, str]:
    """runs_index 每个 subject_id 的最后一个事件名（读侧幂等去重用）。"""
    last: dict[str, str] = {}
    for ev in RunLedger(repo_root / "ledger", "runs_index").events():
        sid = ev.get("subject_id")
        if sid:
            last[sid] = ev.get("event")
    return last


def _batch_already_audited(repo_root: Path, batch_id: str) -> bool:
    last = None
    for ev in RunLedger(repo_root / "ledger", "batches").events():
        if ev.get("subject_id") == batch_id:
            last = ev.get("event")
    return last == "batch_audited"


def _apply_dispositions(repo_root: Path, batch_id: str, run_ids: list[str],
                        overall: str, quarantine: bool) -> str:
    """按 AMENDMENT-16 落账。只追加事件、绝不删数据（坑13）。返回处置摘要。
    quarantine=True（health 超阈 或 item1 manifest/steps 完整性 FAIL——"无 step 的完成"须拦在
    ACCEPTED 之外，A2-6 演练2）→ 批内 run 先 run_audited(verdict:quarantined) 再 run_quarantined，
    批次 batch_audited(verdict:quarantined)。

    幂等（读侧去重）：重复 --apply 不得重复落账。落账前先读 runs_index 各 run 末事件——
    已处于终态（run_accepted/run_quarantined/run_rejected/run_cancelled）的 run 跳过；
    批次已 batch_audited 则不再补记。绝不重写 append-only 链，只在"尚未处置"时追加。"""
    # 幽灵批闸（根因②）：批内零 run 时绝不落任何处置事件。原实现对一个从不存在的
    # batch_id 也会 append batch_audited(verdict=pass)——凭空给一个没有任何 run 的
    # 批次盖章"审计通过"，等于往 append-only 账本里灌入不可撤销的伪证。
    if not run_ids:
        return ("空 run 集/幽灵批：拒绝落任何处置事件（fail-closed，不给不存在的批盖章）")
    runs_idx = RunLedger(repo_root / "ledger", "runs_index")
    batches = RunLedger(repo_root / "ledger", "batches")
    last_ev = _run_last_events(repo_root)
    batch_done = _batch_already_audited(repo_root, batch_id)
    todo = [r for r in run_ids if last_ev.get(r) not in _TERMINAL_RUN_EVENTS]
    skipped = len(run_ids) - len(todo)

    if quarantine:
        for rid in todo:
            runs_idx.append("run_audited", subject_id=rid, verdict="quarantined")
            runs_idx.append("run_quarantined", subject_id=rid)
        if not batch_done:
            batches.append("batch_audited", subject_id=batch_id, verdict="quarantined")
        return (f"quarantined {len(todo)} runs（跳过已处置 {skipped}）, "
                f"dry_run=false" + ("（批已 audited，未重复）" if batch_done else ""))
    if overall == "PASS":
        for rid in todo:
            runs_idx.append("run_audited", subject_id=rid, verdict="pass")
            runs_idx.append("run_accepted", subject_id=rid)
        if not batch_done:
            batches.append("batch_audited", subject_id=batch_id, verdict="pass")
        return (f"accepted {len(todo)} runs（跳过已处置 {skipped}）, "
                f"dry_run=false" + ("（批已 audited，未重复）" if batch_done else ""))
    return "overall=FAIL 且无 health 超阈：不落 accept/quarantine（人裁决）"


def audit_batch(repo_root: Path, batch_id: str,
                items: tuple[int, ...] = (1, 2, 4),
                apply: bool = False, strict: bool = False) -> AuditReport:
    """按 items 执行审计项，返回 AuditReport（A1-7）。fail-safe 恒在场。
    strict=True 时项5 的 code_tree_hash 漂移由呈现升级为 FAIL（复现包出包前，A2-2）。"""
    repo_root = Path(repo_root)
    run_ids = runs_of_batch(repo_root, batch_id)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = AuditReport(batch_id=batch_id, generated_at=generated_at,
                         thresholds=health_mod.thresholds())

    health_breached = False
    for item_id in items:
        if item_id == 1:
            report.items.append(_safe(1, lambda: _item1_manifest(repo_root, batch_id, run_ids)))
        elif item_id == 2:
            report.items.append(_safe(2, lambda: _item2_rescore(repo_root, batch_id, run_ids)))
        elif item_id == 3:
            report.items.append(_safe(3, lambda: contamination_item(repo_root, batch_id, run_ids)))
        elif item_id == 4:
            run_dirs = [repo_root / "data" / "runs" / r for r in run_ids]
            hitem = _safe(4, lambda: health_mod.health_panel(run_dirs)[0])
            report.items.append(hitem)
            # 单独取 breached 标志（health_panel 返回二元组；_safe 只取 item，此处重算标志）
            if hitem.verdict == "FAIL":
                health_breached = True
        elif item_id == 5:
            report.items.append(_safe(5, lambda: version_consistency_item(
                repo_root, batch_id, run_ids, strict=strict)))
        elif item_id == 6:
            report.items.append(_safe(6, lambda: budget_recon_item(repo_root, batch_id, run_ids)))
        else:
            report.items.append(AuditItem.make(item_id, "SKIP",
                                                [f"item{item_id} 属阶段2，R1-core 不执行"]))

    # 批级证据地板（id=0，恒执行、不受 --items 影响，substantive=False）：
    # 空 run 集/幽灵批 → FAIL；ledger 链外部锚缺失或失配 → FAIL（V07 + V09 接线点）。
    report.items.append(_safe(0, lambda: _item0_batch_floor(repo_root, batch_id, run_ids)))

    report.evidence_pointers = {
        "ledger_tail": _ledger_tails(repo_root),
        "runs": [f"data/runs/{r}" for r in run_ids],
    }

    # 完整性 FAIL（item1 manifest/steps）与 health 超阈同样触发 QUARANTINE（AMENDMENT-16 / A2-6 演练2）
    integrity_breached = any(it.id == 1 and it.verdict == "FAIL" for it in report.items)
    quarantine = health_breached or integrity_breached

    if apply:
        disp = _apply_dispositions(repo_root, batch_id, run_ids,
                                   report.overall, quarantine)
        # 预算熔断生产调用点（根因④：check_fuse 原仅演练/测试触发，判据未接线）。
        # --apply 是审计真写路径、A 是 budget_alert 唯一写者：在此评估 85% 熔断线，
        # 超线则入账 budget_alert + 告警文件（24h 冷却去重）。未超线 return None 不写。
        # 告警是"让超线不可能无声"，不阻断落账——熔断失败也不许拖垮审计处置。
        costs_ledger = RunLedger(repo_root / "ledger", "costs")
        try:
            fuse = check_fuse(repo_root, costs_ledger.append, alert_actor="a_audit")
        except Exception as e:  # noqa: BLE001 —— 告警侧异常不得阻断审计落账
            fuse = None
            for it in report.items:
                if it.id == 6:
                    it.evidence.append(f"熔断检查异常（已隔离，不阻断落账）: {type(e).__name__}: {e}")
        if fuse is not None:
            for it in report.items:
                if it.id == 6:
                    it.evidence.append(
                        f"熔断触发（check_fuse）: 累计 ¥{fuse['total_cny']} / cap "
                        f"¥{fuse['cap_cny']} = {fuse['ratio']:.1%} → budget_alert 已入账")
        if quarantine:
            for it in report.items:
                if (it.id == 4 and health_breached) or (it.id == 1 and integrity_breached):
                    it.disposition = (it.disposition or "") + f" | 落账: {disp}"
        elif report.overall == "PASS":
            # 在 item1 记批级处置摘要（便于人读）
            for it in report.items:
                if it.id == 1:
                    it.disposition = f"落账: {disp}"
        # V09 三分原则 P4（运动员/裁判/验船师三分）：auditor 是 **验船师**，
        # 绝不能有写锚（seal）的权力——否则它能把自己刚在 item0/_verify_ledger_anchors
        # 里检出的篡改重新封印成合规。故此处 **不做任何 seal**：验船师只 verify。
        # 收口封印是生产收口方（dispatch batch_settled / cloud.stop）的职责，
        # 且已改走 external_seal.guarded_reseal（seal-once + 前缀校验，防洗白）。
    return report
