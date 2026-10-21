"""abcr.governor.planner —— 固定规则计划器 v0（零 LLM，契约外规则由工程包C 冻结）。

架构位置：包C·Governor。plan-spec → 信封草案 + 预算预估 + 符合性预检。
本模块永不签发令牌、永不写账本；产物只落 configs/envelopes/ 与 plans/precheck/。
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from abcr.governor.envelope import (BATCH_ID_RE, CONDITION_ENUM, ENVELOPE_VERSION,
                                    canonical_json, save_envelope, validate_envelope)
from abcr.report import ledgerio

MAX_BATCH_COST_CNY = 60.0
MAX_BATCH_GPU_HOURS = 6.0
W1_TOTAL_BUDGET_CNY = 150.0
SEC_PER_ITEM = {"fake": 0.2, "mac_3b": 3.0, "cloud_7b": 6.0}   # 未实测估计值
CNY_PER_GPU_HOUR = 2.5                                          # 未实测估计值
TRAIT_WHITELIST = frozenset({"conscientiousness", "openness", "neuroticism",
                             "optimistic", "sycophantic"})

# AMENDMENT-33：spec.run_configs = 内联完整 RunConfig 对象（非路径列表）。
# 必需键（嵌套格式见 fixtures/envelope_fixture.json run_configs[0]）；
# batch_id 由 planner 起草时注入（spec 阶段可缺省，若带则被覆盖）。
RUN_CONFIG_REQUIRED = ("config_version", "protocol_ref", "model", "benchmark",
                       "condition", "intervention", "decoding")


def _finite_pos(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def config_hash(cfg: dict) -> str:
    """AMENDMENT-33：config_hash = sha256(canonical_compact(config))（紧凑 separators 口径，K1；
    单点复用 envelope.canonical_json）。"""
    return hashlib.sha256(canonical_json(cfg).encode("utf-8")).hexdigest()


@dataclass
class PlanResult:
    ok: bool
    batch_id: str
    checks: list[dict] = field(default_factory=list)   # [{"rule","passed","evidence"}]
    estimate: dict = field(default_factory=dict)        # {"est_total_items","est_gpu_hours","est_cost_cny"}
    envelope_path: str | None = None                    # FAIL 时 None
    precheck_path: str = ""

    def render_text(self) -> str:
        lines = [f"# 计划草案预检 — {self.batch_id}",
                 f"结论: {'PASS（草案已落）' if self.ok else 'FAIL（未落草案）'}"]
        lines.append("")
        lines.append("| 规则 | 判定 | 证据 |")
        lines.append("|---|---|---|")
        for c in self.checks:
            lines.append(f"| {c['rule']} | {'PASS' if c['passed'] else 'FAIL'} | {c['evidence']} |")
        e = self.estimate
        lines.append("")
        lines.append(f"预估: items={e.get('est_total_items')} "
                     f"gpu_hours={e.get('est_gpu_hours'):.4f} "
                     f"cost_cny={e.get('est_cost_cny'):.2f}")
        if self.envelope_path:
            lines.append(f"信封草案: {self.envelope_path}")
        lines.append(f"预检报告: {self.precheck_path}")
        return "\n".join(lines)


def next_batch_id(envdir: Path) -> str:
    """B-<UTC:%Y%m%dT%H%M%SZ>-<4位序号>；序号 = 当日已有信封数+1（单人操作，不设并发防护）。"""
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    envdir = Path(envdir)
    existing = [p for p in envdir.glob(f"B-{day}T*.json")
                if not p.name.endswith(".reject.json")] if envdir.exists() else []
    return f"B-{ts}-{len(existing) + 1:04d}"


def authoritative_spent(costs_path: Path) -> tuple[float, str]:
    """F-COST-03：预算闸接入**真实 spent**。优先读权威项目成本账本（cost_ledger 创世存在时），
    取悲观口径 settled + 未结算负债（在飞负债计入占用，fail-closed）；创世不存在或账本
    损坏 → 回退到 costs.jsonl 的 run_cost_actual 汇总（spent_cny）。恒 0 空转由此消除：
    只要有 RESERVED/SETTLED 事件或 run_cost_actual 写入，spent 即真实反映。"""
    from abcr.common import cost_ledger as _cl
    ledger_dir = Path(costs_path).parent
    if (ledger_dir / _cl.GENESIS_FILE).exists():
        try:
            led = _cl.CostLedger(ledger_dir)
            settled, liability = led.spent()
            worst = settled + liability
            return worst, (f"权威成本账本：已结算 {settled:.2f} + 在飞负债 {liability:.2f}"
                           f"（悲观口径 {worst:.2f}）")
        except _cl.CostLedgerError as e:
            # 账本存在但损坏 → fail-closed：按 W1 全额占用，逼预算门保守拒绝。
            return W1_TOTAL_BUDGET_CNY, f"权威成本账本损坏（{e}）→ 按全额占用 fail-closed"
    return spent_cny(costs_path)


def spent_cny(costs_path: Path) -> tuple[float, str]:
    """汇总 run_cost_actual 的 payload amount_cny（AMENDMENT-9 键名；主链+云链段
    合并读，见 ledgerio.read_chain_merged）；缺文件→(0.0, 注记)。"""
    costs_path = Path(costs_path)
    if not costs_path.exists() and not list(Path(costs_path.parent).glob("cloud-day*")):
        return 0.0, "账本无实耗记录（costs.jsonl 不存在，按 0 计）"
    events = ledgerio.read_chain_merged(costs_path.parent, costs_path.stem)
    total = 0.0
    n = 0
    for ev in events:
        if ev.get("event") == "run_cost_actual":
            amt = ev.get("amount_cny")
            if isinstance(amt, (int, float)) and not isinstance(amt, bool):
                total += float(amt)
                n += 1
    if n == 0:
        return 0.0, "账本无 run_cost_actual 记录（按 0 计）"
    return total, f"实耗汇总自 {n} 条 run_cost_actual"


def _estimate(spec: dict) -> dict:
    n_configs = len(spec.get("run_configs", []))
    item_limit = spec.get("item_limit_per_run", 0)
    engine = spec.get("engine_class", "fake")
    sec = SEC_PER_ITEM.get(engine, SEC_PER_ITEM["fake"])
    total_items = n_configs * (item_limit if isinstance(item_limit, int)
                               and not isinstance(item_limit, bool) else 0)
    gpu_hours = total_items * sec / 3600.0
    cost = gpu_hours * CNY_PER_GPU_HOUR if engine == "cloud_7b" else 0.0   # fake/mac 按 0 元
    return {"est_total_items": total_items, "est_gpu_hours": gpu_hours, "est_cost_cny": cost}


def _prechecks(spec: dict, est: dict, spent: float, spent_note: str) -> list[dict]:
    def chk(rule: str, passed: bool, evidence: str) -> dict:
        return {"rule": rule, "passed": bool(passed), "evidence": evidence}

    splits = spec.get("splits", [])
    conds = spec.get("conditions", [])
    budget = spec.get("budget", {})
    cost_cap = budget.get("cost_cap_cny", 0)
    gpu_max = budget.get("gpu_hours_max", 0)
    traits = spec.get("trait_whitelist", [])
    item_limit = spec.get("item_limit_per_run", 0)
    seeds = spec.get("seeds", [])
    run_configs = spec.get("run_configs", [])

    checks = []
    # P1 split 只 dev
    checks.append(chk("P1 split只dev", set(splits) == {"dev"},
                      f"splits={splits}"))
    # P2 条件白名单
    p2 = bool(conds) and set(conds) <= CONDITION_ENUM
    bad_c = [c for c in conds if c not in CONDITION_ENUM]
    checks.append(chk("P2 条件白名单", p2,
                      f"conditions={conds}" + (f"；越界={bad_c}" if bad_c else "")))
    # P3 批预算合规
    p3 = (isinstance(cost_cap, (int, float)) and not isinstance(cost_cap, bool)
          and cost_cap <= MAX_BATCH_COST_CNY
          and isinstance(gpu_max, (int, float)) and not isinstance(gpu_max, bool)
          and gpu_max <= MAX_BATCH_GPU_HOURS)
    checks.append(chk("P3 批预算合规",
                      p3, f"cost_cap={cost_cap}≤{MAX_BATCH_COST_CNY}, gpu_max={gpu_max}≤{MAX_BATCH_GPU_HOURS}"))
    # P4 W1 总预算内
    remaining = W1_TOTAL_BUDGET_CNY - spent
    p4 = isinstance(cost_cap, (int, float)) and not isinstance(cost_cap, bool) and cost_cap <= remaining
    checks.append(chk("P4 W1总预算内", p4,
                      f"cost_cap={cost_cap}≤(150−{spent:.2f}={remaining:.2f})；{spent_note}"))
    # P5 trait 白名单
    bad_t = [t for t in traits if t not in TRAIT_WHITELIST]
    checks.append(chk("P5 trait白名单", not bad_t,
                      f"trait_whitelist={traits}" + (f"；越界={bad_t}" if bad_t else "")))
    # P6 规模上限
    p6 = (isinstance(item_limit, int) and not isinstance(item_limit, bool)
          and item_limit <= 250 and isinstance(seeds, list) and 1 <= len(seeds) <= 5)
    checks.append(chk("P6 规模上限", p6,
                      f"item_limit={item_limit}≤250, len(seeds)={len(seeds) if isinstance(seeds, list) else 'NA'}∈[1,5]"))
    # P7 run_configs 结构完备（AMENDMENT-33：内联完整 RunConfig 对象，非路径列表；
    # 必需键齐全 + config_hash 唯一性可算——batch_id 起草时统一注入，不参与唯一性）
    p7_problems: list[str] = []
    hashes: list[str] = []
    for i, rc in enumerate(run_configs):
        if not isinstance(rc, dict):
            p7_problems.append(f"[{i}] 非内联 RunConfig 对象（路径列表形态已废，AMENDMENT-33）")
            continue
        miss = [k for k in RUN_CONFIG_REQUIRED if k not in rc]
        if miss:
            p7_problems.append(f"[{i}] 缺必需键 {miss}")
            continue
        for k in ("model", "benchmark", "decoding"):
            if not isinstance(rc.get(k), dict):
                p7_problems.append(f"[{i}] {k} 须为对象")
        try:
            hashes.append(config_hash({k: v for k, v in rc.items() if k != "batch_id"}))
        except (TypeError, ValueError) as e:
            p7_problems.append(f"[{i}] config_hash 不可算: {e!r}")
    if not p7_problems and len(set(hashes)) != len(hashes):
        p7_problems.append("config_hash 不唯一（存在重复 RunConfig，AMENDMENT-22）")
    p7 = bool(run_configs) and not p7_problems
    checks.append(chk("P7 run_configs结构完备", p7,
                      f"n={len(run_configs)}"
                      + (f"；问题={p7_problems}" if p7_problems else "；必需键齐全且 config_hash 唯一")))
    # P8 预估不超信封
    p8 = (est["est_gpu_hours"] <= gpu_max if isinstance(gpu_max, (int, float)) else False) \
        and (est["est_cost_cny"] <= cost_cap if isinstance(cost_cap, (int, float)) else False)
    checks.append(chk("P8 预估不超信封", p8,
                      f"est_gpu={est['est_gpu_hours']:.4f}≤{gpu_max}, est_cost={est['est_cost_cny']:.2f}≤{cost_cap}"))
    return checks


def _spec_to_envelope(spec: dict, batch_id: str) -> dict:
    """spec 直映射为信封草案（无 approval）。engine_class/goal/deadline_hours/planspec_version 不进信封。"""
    deadline = datetime.now(timezone.utc) + timedelta(hours=float(spec.get("deadline_hours", 24)))
    return {
        "envelope_version": ENVELOPE_VERSION,
        "batch_id": batch_id,
        "protocol_ref": spec.get("protocol_ref", "W1-V0.9"),
        "scope": {
            "benchmark_families": spec.get("benchmark_families", []),
            "conditions": spec.get("conditions", []),
            "splits": spec.get("splits", []),
            "item_limit_per_run": spec.get("item_limit_per_run"),
            "seeds": spec.get("seeds", []),
            "trait_whitelist": spec.get("trait_whitelist", []),
        },
        "budget": {
            "gpu_hours_max": spec.get("budget", {}).get("gpu_hours_max"),
            "cost_cap_cny": spec.get("budget", {}).get("cost_cap_cny"),
        },
        "deadline_utc": deadline.isoformat(timespec="seconds"),
        # AMENDMENT-33：内联完整 RunConfig 深拷贝入信封（envelope_sha256 覆盖全部实验参数），
        # 逐个注入本批 batch_id（spec 阶段若带 batch_id 以起草值为准）。
        "run_configs": [{**copy.deepcopy(rc), "batch_id": batch_id}
                        for rc in spec.get("run_configs", [])],
        "drafted_by": "governor-rules-v1",
    }


def _write_precheck(precheck_dir: Path, batch_id: str, result: PlanResult,
                    spec_path: Path, spent: float, spent_note: str) -> tuple[str, str]:
    precheck_dir = Path(precheck_dir)
    precheck_dir.mkdir(parents=True, exist_ok=True)
    jpath = precheck_dir / f"{batch_id}.precheck.json"
    mpath = precheck_dir / f"{batch_id}.precheck.md"
    jpath.write_text(json.dumps({
        "batch_id": batch_id, "ok": result.ok, "checks": result.checks,
        "estimate": result.estimate,
        "spent_cny": spent, "remaining_cny": W1_TOTAL_BUDGET_CNY - spent,
        "spent_note": spent_note, "spec_path": str(spec_path),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = [f"# 预检报告 {batch_id}",
          f"- spec: {spec_path}",
          f"- 已实耗: {spent:.2f} 元；W1 余额: {W1_TOTAL_BUDGET_CNY - spent:.2f} 元（{spent_note}）",
          f"- 预估: items={result.estimate['est_total_items']} "
          f"gpu_hours={result.estimate['est_gpu_hours']:.4f} cost={result.estimate['est_cost_cny']:.2f} 元",
          "", "| 规则 | 判定 | 证据 |", "|---|---|---|"]
    for c in result.checks:
        md.append(f"| {c['rule']} | {'PASS' if c['passed'] else 'FAIL'} | {c['evidence']} |")
    mpath.write_text("\n".join(md) + "\n", encoding="utf-8")
    return str(jpath), str(mpath)


def plan(spec_path: Path, envdir: Path = Path("configs/envelopes"),
         precheck_dir: Path = Path("plans/precheck"),
         costs_path: Path = Path("ledger/costs.jsonl")) -> PlanResult:
    """主入口：读 spec → 八项预检 → 预估 → （全 PASS 才）落信封草案；预检报告恒落。"""
    spec_path = Path(spec_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    envdir = Path(envdir)
    batch_id = next_batch_id(envdir)

    est = _estimate(spec)
    spent, spent_note = authoritative_spent(costs_path)   # F-COST-03：接入权威真实 spent
    checks = _prechecks(spec, est, spent, spent_note)

    # protocol_ref / deadline 合规（F-GOV-06）：条件式追加（仅违规才加一条 FAIL，happy path 不改 8 项计数）。
    pref = spec.get("protocol_ref", "W1-V0.9")
    dh = spec.get("deadline_hours", 24)
    pd_problems: list[str] = []
    if not isinstance(pref, str) or not pref.strip():
        pd_problems.append(f"protocol_ref 空/非字符串: {pref!r}")
    if isinstance(dh, bool) or not isinstance(dh, (int, float)) or not _finite_pos(dh):
        pd_problems.append(f"deadline_hours 须为有限正数: {dh!r}")
    if pd_problems:
        checks.append({"rule": "P10 protocol/deadline合规", "passed": False,
                       "evidence": "；".join(pd_problems)})

    ok = all(c["passed"] for c in checks)

    result = PlanResult(ok=ok, batch_id=batch_id, checks=checks, estimate=est)
    # 全 PASS 才落信封草案；预检报告恒落
    if ok:
        env = _spec_to_envelope(spec, batch_id)
        v_ok, v_problems = validate_envelope(env)
        if not v_ok:   # 双保险：草案自身须过 envelope 结构校验
            ok = False
            checks.append({"rule": "P9 草案结构自校验", "passed": False,
                           "evidence": f"validate_envelope FAIL: {v_problems}"})
            result.ok = False
        else:
            envdir.mkdir(parents=True, exist_ok=True)
            epath = envdir / f"{batch_id}.json"
            save_envelope(epath, env)
            result.envelope_path = str(epath)
    jpath, mpath = _write_precheck(precheck_dir, batch_id, result, spec_path, spent, spent_note)
    result.precheck_path = mpath
    assert BATCH_ID_RE.match(batch_id), "内部错误：batch_id 格式不合法"
    return result
