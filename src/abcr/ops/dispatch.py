"""abcr.ops.dispatch — 信封消费与逐 run 驱动（契约 §2.6/§4.4；Operator(B) 的心脏）。

架构位置：控制面的执行入口。消费 C 起草、人签发的批次信封，令牌 fail-closed 校验后
展开为 run 入队、逐 run 驱动执行器、全程落账本事件、评分、批次收口。幂等：同一
--envelope 重跑只补未完成部分（run_id 确定性 + 事件幂等 + 队列/断点幂等）。

八步流程（契约 §5-B1-5）：
  0 已结批次短路(AMENDMENT-23) → 1 令牌校验(fail-closed,双留痕) → 2 scope 强制
  → 3 展开入队+开局事件 → 4 启动对账三步(孤儿/续跑) → 5 逐 run 驱动 → 6 评分 → 7 批次收口
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from abcr.audit import treehash
from abcr.common import approval_token as tok
from abcr.common import external_seal
from abcr.common.constants import PROTOCOL_REF, STATE_DIR_DEFAULT
from abcr.common.ledger_ref import GENESIS_HASH, RunLedger, append_record
from abcr.governor.envelope import envelope_sha256
from abcr.ops import faketask, queue, runstate
from abcr.ops.heartbeat import Heartbeat
from abcr.rig import scorer

LEDGER_DIR_DEFAULT = Path("ledger")
RUNS_ROOT_DEFAULT = Path("data/runs")
GOLDEN_PATH = Path("data/golden/golden10.json")   # 输入(只读真仓)——不隔离
W1_TOTAL_BUDGET_CNY = 150.0   # 全局硬顶（呈现纪律 ¥150 常量）；信封 cost_cap 不得越顶


def _ledger_dir() -> Path:
    """账本根调用时读 env（AMENDMENT-38）。隔离演练/云日摄入经 ABCR_LEDGER_DIR 指向沙箱;
    无 env 时=ledger/,与旧常量字节等价 → R1 回归零影响。"""
    return Path(os.environ.get("ABCR_LEDGER_DIR", str(LEDGER_DIR_DEFAULT)))


def _runs_root() -> Path:
    """run 产物根调用时读 env（AMENDMENT-38）。经 ABCR_RUNS_ROOT 指向沙箱;无 env 时=data/runs/。"""
    return Path(os.environ.get("ABCR_RUNS_ROOT", str(RUNS_ROOT_DEFAULT)))


# 单一定义纪律（§3.7）：code_tree_hash 的根集/后缀集/公式**只在 abcr.audit.treehash**。
# 原此处有一份平行私有副本（_CODE_TREE_EXTS/_CODE_TREE_ROOTS，旧集：无 .sh/.toml/.jsonl/.pyi/.cfg，
# 无 data/items），与验船师侧的权威集合分叉 → 同一棵树 生产端算出的 manifest.code_tree_hash
# 与审计重算恒不相等，任何含 .sh/.toml 的真实仓都被判 code_drift，真漂移淹没在噪声里。
# 平行定义已消灭：本模块只 import 权威实现，不再持有任何本地副本。
_CODE_TREE_EXTS = treehash.CODE_TREE_EXTS      # 兼容别名（外部若引用）——权威值，不是副本
_CODE_TREE_ROOTS = treehash.CODE_TREE_ROOTS


# ────────────────────────── 哈希/id 工具（契约 §3.5/§3.6）──────────────────────────
def _canonical(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(_canonical(cfg).encode("utf-8")).hexdigest()


def _batch_ts_segment(batch_id: str) -> str:
    """B-<UTC>-<4序号> → <UTC>（AMENDMENT-22：run_id 时间戳段取信封 batch_id 内嵌时间戳）。"""
    parts = batch_id.split("-")
    return parts[1] if len(parts) >= 3 else batch_id


def make_run_id(batch_id: str, chash: str) -> str:
    return f"{_batch_ts_segment(batch_id)}-{chash[:12]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=5).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _git_clean() -> bool:
    try:
        out = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        return out == ""
    except Exception:
        return False


def _code_tree_hash() -> str:
    """契约 §3.5/§3.7：委托给权威实现 abcr.audit.treehash.code_tree_hash（单一定义）。

    生产端（manifest 写入）与验船师端（审计项5 重算）**必须**是同一个函数，否则
    "定义分叉"本身就是漏洞：漏掉的后缀/根下的文件可被替换而树哈希不变。
    cwd 即仓根（dispatch 一贯以相对路径消费 data/ledger），故传 Path.cwd()——
    treehash 内部 relative_to(repo_root) 产出的相对路径与原实现字节等价。
    """
    return treehash.code_tree_hash(Path.cwd())


def _golden_ids(item_limit: int) -> list[str]:
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    ids = sorted(r["id"] for r in data["items"])
    return ids[:item_limit] if item_limit else ids


def _golden_prompts() -> dict[str, str]:
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return {r["id"]: r["prompt"] for r in data["items"]}


# ────────────────────────── 账本幂等/拒绝留痕 ──────────────────────────
def _append_once(led: RunLedger, event: str, subject_id: str, **payload: object):
    if led.has_event(event, subject_id):
        return None
    return led.append(event, subject_id=subject_id, **payload)


def _write_alert(state_dir: Path, kind: str, subject_id: str, reason: str,
                 severity: str = "A") -> Path:
    """告警文件接口（AMENDMENT-18）：state/alerts/<ts>-<kind>.json。"""
    alerts = state_dir / "alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    p = alerts / f"{ts}-{kind}.json"
    p.write_text(json.dumps(
        {"ts": ts, "kind": kind, "severity": severity,
         "subject_id": subject_id, "reason": reason},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _reject(batches_led: RunLedger, state_dir: Path, batch_id: str,
            reason: str, alert_kind: str) -> None:
    """拒绝双留痕（AMENDMENT-13）：batches 链 batch_dispatch_rejected + 告警文件。不落 runs_index。"""
    batches_led.append("batch_dispatch_rejected", subject_id=batch_id, reason_code=reason)
    _write_alert(state_dir, alert_kind, batch_id, reason, severity="A")


# ────────────────────────── scope 强制（契约 §5-B1-5 步骤2）──────────────────────────
def _scope_violation(cfg: dict, scope: dict) -> str | None:
    bench = cfg.get("benchmark", {})
    if bench.get("family") not in scope.get("benchmark_families", []):
        return "BENCHMARK_OUT_OF_SCOPE"
    if cfg.get("condition") not in scope.get("conditions", []):
        return "CONDITION_OUT_OF_SCOPE"
    if bench.get("split", "none") not in scope.get("splits", []):
        return "SPLIT_OUT_OF_SCOPE"
    if int(bench.get("item_limit", 0)) > int(scope.get("item_limit_per_run", 0)):
        return "ITEM_LIMIT_EXCEEDED"
    seeds = set(cfg.get("decoding", {}).get("seeds", []))
    if not seeds.issubset(set(scope.get("seeds", []))):
        return "SEED_OUT_OF_SCOPE"
    trait = (cfg.get("intervention") or {}).get("trait")
    wl = scope.get("trait_whitelist", [])
    if trait and wl and trait not in wl:
        return "TRAIT_OUT_OF_SCOPE"
    return None


def _budget_violation(envelope: dict) -> str | None:
    """批级预算强制（对抗根因②/④：信封 budget 键只在文档、scope 检从不读）。

    fail-closed：缺 budget / cost_cap / gpu_hours 键，或值非数值/为负，一律拒批——
    "无申报预算"绝不等于"零成本可放行"。cost_cap 越过全局 ¥150 硬顶亦拒。
    这里把人签发信封里申报的预算真正接进 dispatch 闸门，令等价攻击（改大 cost_cap /
    删掉 budget 键）不再绕过。
    """
    budget = envelope.get("budget")
    if not isinstance(budget, dict):
        return "BUDGET_MISSING"
    cap = budget.get("cost_cap_cny")
    gph = budget.get("gpu_hours_max")
    if not _is_num(cap) or float(cap) < 0.0:
        return "BUDGET_COST_CAP_INVALID"
    if not _is_num(gph) or float(gph) < 0.0:
        return "BUDGET_GPU_HOURS_INVALID"
    if float(cap) > W1_TOTAL_BUDGET_CNY:
        return "BUDGET_EXCEEDS_W1_CAP"
    return None


def _is_num(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _load_run_configs(envelope: dict) -> list[dict]:
    out: list[dict] = []
    for entry in envelope.get("run_configs", []):
        if isinstance(entry, dict):
            out.append(entry)
        else:
            out.append(json.loads(Path(entry).read_text(encoding="utf-8")))
    return out


# ────────────────────────── step 记录组装（48 字段，契约 §3.3/§5-B1-5）──────────────────────────
def _build_step(run_id: str, item_id: str, output_text: str, cfg: dict,
                seed: int, chash: str, prompts: dict[str, str], git_commit: str) -> dict:
    prompt = prompts.get(item_id, "")
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "trajectory_id": f"{run_id}-{item_id}-{seed}",
        "step_id": 0,
        "parent_run": None,
        "git_commit": git_commit,
        "model_id": "fake/deterministic-v1",
        "model_revision": "fixture",
        "dtype": "none",
        "quantization": None,
        "device": "none",
        "engine": "fake",
        "engine_version": "1.0",
        "torch_version": None,
        "cuda_version": None,
        "benchmark": cfg.get("benchmark", {}).get("family", "golden10"),
        "split_hash": "fixture",
        "item_id": item_id,
        "condition": cfg.get("condition", "fake"),
        "trait": None,
        "trait_pole": None,
        "method": None,
        "layer": None,
        "coefficient": None,
        "intervention_strength": None,
        "random_seed": seed,
        "env_seed": None,
        "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "chat_template_hash": "fixture",
        "config_hash": chash,
        "action": "generate",
        "obs_hash": None,
        "remaining_budget": None,
        "output_text": output_text,
        "parsed_answer": output_text,
        "is_correct": None,          # 权威值在 scores
        "latency_ms": 200,
        "input_tokens": 0,
        "output_tokens": 0,
        "stop_reason": "fake",
        "trajectory_stop_reason": "task_done",
        "trait_score": None,
        "fluency_score": None,
        "safety_flags": [],
        "activation_summary": None,
        "state_snapshot_ref": None,
        "protocol_ref": PROTOCOL_REF,
        "env_lock_ref": "requirements-mac.txt",
    }


def _write_manifest(run_dir: Path, run_id: str, cfg: dict, chash: str, batch_id: str,
                    seed: int, git_commit: str, status: str,
                    finished_at: str | None) -> None:
    """22 键 manifest（AMENDMENT-31）。"""
    manifest = {
        "run_id": run_id,
        "config": cfg,
        "config_hash": chash,
        "git_commit": git_commit,
        "git_clean": _git_clean(),
        "code_tree_hash": _code_tree_hash(),
        "model_id": "fake/deterministic-v1",
        "model_revision": "fixture",
        "chat_template_hash": "fixture",
        "split_hash": "fixture",
        "engine": "fake",
        "engine_version": "1.0",
        "torch_version": None,
        "python_version": platform.python_version(),
        "env_lock_ref": "requirements-mac.txt",
        "seeds": [seed],
        "started_at": _now() if finished_at is None else None,
        "finished_at": finished_at,
        "status": status,
        "non_citable": True,          # fake / Mac → 一律 non-citable（契约 §4.1）
        "protocol_ref": PROTOCOL_REF,
        "batch_id": batch_id,
    }
    # 续跑时保留 started_at（若已存在 manifest）
    p = run_dir / "manifest.json"
    if p.exists():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
            if old.get("started_at"):
                manifest["started_at"] = old["started_at"]
        except (OSError, ValueError):
            pass
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _existing_step_keys(steps_path: Path) -> set[tuple[str, int]]:
    """已有 steps 的 (item_id, random_seed) 集合（AMENDMENT-25 续跑去重以 steps 为准）。"""
    keys: set[tuple[str, int]] = set()
    if steps_path.exists():
        for line in steps_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                keys.add((r["item_id"], r["random_seed"]))
    return keys


def _queue_state(run_id: str) -> str | None:
    for st in queue.STATES:
        if (queue._queue_root() / st / f"{run_id}.json").exists():
            return st
    return None


# ────────────────────────── 逐 run 驱动（契约 §5-B1-5 步骤5）──────────────────────────
def _process_run(run_id: str, cfg: dict, item_ids: list[str], seed: int, chash: str,
                 batch_id: str, runs_led: RunLedger, state_dir: Path,
                 prompts: dict[str, str], git_commit: str) -> str:
    qstate = _queue_state(run_id)
    if qstate == "done":
        return "skip-done"

    rec = runstate.load(run_id)
    resume = rec is not None and rec.get("status") == runstate.STATUS_SUSPENDED

    if resume:
        can, why = runstate.can_resume(run_id)
        # 配额类失败不盲目续跑（K12）
        if any(tag in (rec.get("reason", "").lower()) for tag in ("quota", "402", "insufficient", "额度")):
            _write_alert(state_dir, "resume-blocked-quota", run_id, rec.get("reason", ""), severity="A")
            return "skip-quota"
        if not can:
            _write_alert(state_dir, "resume-blocked", run_id, why, severity="B")
            return "skip-noresume"

    # 移入 running
    if qstate == "running":
        pass                                   # 孤儿：已在 running/（crash 遗留）
    elif qstate == "failed":
        queue.requeue(run_id)
        if queue.claim(run_id) is None:
            return "lost"
    elif qstate == "pending":
        if queue.claim(run_id) is None:
            return "lost"
    else:
        return "not-queued"

    # 事件序：run_started（首次）；续跑则 run_failed(once)→run_resumed
    _append_once(runs_led, "run_started", run_id, batch_id=batch_id)
    if resume:
        _append_once(runs_led, "run_failed", run_id, batch_id=batch_id,
                     reason=rec.get("reason", "orphan"))
        runs_led.append("run_resumed", subject_id=run_id, batch_id=batch_id)

    # run 目录 + manifest + runstate 登记（幂等续跑）
    # 执行器按 config.model.engine 分发（AMENDMENT-31 设计）：fake→faketask（现状,R1 保绿）；
    # 非 fake→rig.runner 真模型（R2 真批）。dispatch 恒握账本/队列/心跳/评分；真 manifest+step 由 runner 产。
    engine = (cfg.get("model") or {}).get("engine") or "fake"
    run_dir = _runs_root() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if engine == "fake":
        _write_manifest(run_dir, run_id, cfg, chash, batch_id, seed, git_commit,
                        status="running", finished_at=None)
    steps_path = run_dir / "steps.jsonl"
    existing = _existing_step_keys(steps_path)
    runstate.register_run(run_id, item_ids)
    cur = runstate.load(run_id) or {}
    done_count = sum(1 for v in (cur.get("items") or {}).values() if v == "done")
    hb = Heartbeat(runs_led.append, run_id, start_items=done_count)

    def emit_step(item_id: str, output_text: str) -> None:
        if (item_id, seed) in existing:        # 续跑去重（AMENDMENT-25）
            return
        rec_step = _build_step(run_id, item_id, output_text, cfg, seed, chash,
                               prompts, git_commit)
        append_record(steps_path, rec_step)
        existing.add((item_id, seed))

    def append_step(item_id: str, step: dict) -> None:
        """真 engine：runner 已 build_step（真模型字段），dispatch 只去重挂链（AMENDMENT-25）。"""
        if (item_id, seed) in existing:
            return
        append_record(steps_path, step)
        existing.add((item_id, seed))

    def mark_done(item_id: str) -> None:
        runstate.mark_item_done(run_id, item_id)
        hb.tick()

    pend = runstate.pending_items(run_id)
    try:
        if engine == "fake":
            faketask.run_items(pend, emit_step, mark_done)
        else:
            from abcr.rig import runner        # 惰性 import：runner 顶层 import dispatch，避免循环
            runner.run_items(pend, cfg, seed, run_id, chash, git_commit, prompts,
                             append_step, mark_done, run_dir, batch_id=batch_id)
    except Exception as e:                     # 非 crash 类被捕获异常：单 run 失败不炸整批
        runstate.mark_suspended(run_id, f"driver 异常: {e}")
        _append_once(runs_led, "run_failed", run_id, batch_id=batch_id, reason=str(e))
        queue.settle(run_id, ok=False)
        return "failed"

    hb.flush()
    _append_once(runs_led, "run_completed", run_id, batch_id=batch_id)
    if engine == "fake":
        _write_manifest(run_dir, run_id, cfg, chash, batch_id, seed, git_commit,
                        status="completed", finished_at=_now())
    # 真 engine 的 running/completed manifest 已由 runner.run_items 用真模型字段写
    if _queue_state(run_id) == "running":
        queue.settle(run_id, ok=True)

    # 评分 pass（幂等：已 scored 不重算）
    if not runs_led.has_event("run_scored", run_id):
        scorer.score_run(run_dir)
        runs_led.append("run_scored", subject_id=run_id, batch_id=batch_id)
    return "completed"


# ────────────────────────── 主流程 ──────────────────────────
def dispatch(envelope_path: str, key_path: str) -> int:
    envelope = json.loads(Path(envelope_path).read_text(encoding="utf-8"))
    batch_id = envelope["batch_id"]
    state_dir = Path(os.environ.get("ABCR_STATE_DIR", STATE_DIR_DEFAULT))  # env 调用时读（AMENDMENT-38）
    ledger_dir = _ledger_dir()
    runs_led = RunLedger(ledger_dir, "runs_index")
    batches_led = RunLedger(ledger_dir, "batches")
    costs_led = RunLedger(ledger_dir, "costs")

    # step0：已结批次短路（AMENDMENT-23）——一切校验之前，不触碰令牌
    if batches_led.has_event("batch_settled", batch_id):
        print(f"already-settled batch_id={batch_id}")
        return 0

    key = Path(key_path).read_bytes()

    # step1：令牌校验（fail-closed，双留痕；AMENDMENT-37 冻结口径）：
    # envelope_sha256 单点在 abcr.governor.envelope（去 approval 的信封体）；
    # 令牌缺位时传空 dict → verify_token 按 C 码表返回 missing_field:*。
    token = (envelope.get("approval") or {}).get("token") or {}
    consumed_store = state_dir / "approvals" / "consumed.json"
    ok, reason = tok.verify_token(
        token, expected_envelope_sha256=envelope_sha256(envelope),
        verify_secret=key, consumed_store=consumed_store)
    if not ok:
        _reject(batches_led, state_dir, batch_id, reason, alert_kind="envelope-rejected")
        print(f"[dispatch] token verify FAILED: {reason}", file=sys.stderr, flush=True)
        return 2

    # step2：scope 强制（含批级预算闸——接进人签发信封申报的 budget）
    bv = _budget_violation(envelope)
    if bv:
        _reject(batches_led, state_dir, batch_id, bv, alert_kind="scope-rejected")
        print(f"[dispatch] budget FAILED: {bv}", file=sys.stderr, flush=True)
        return 2
    scope = envelope["scope"]
    configs = _load_run_configs(envelope)
    hashes = [config_hash(c) for c in configs]
    if len(set(hashes)) != len(hashes):
        _reject(batches_led, state_dir, batch_id, "DUPLICATE_CONFIG_HASH",
                alert_kind="scope-rejected")
        print("[dispatch] scope FAILED: DUPLICATE_CONFIG_HASH", file=sys.stderr, flush=True)
        return 2
    for cfg in configs:
        v = _scope_violation(cfg, scope)
        if v:
            _reject(batches_led, state_dir, batch_id, v, alert_kind="scope-rejected")
            print(f"[dispatch] scope FAILED: {v}", file=sys.stderr, flush=True)
            return 2

    # step3：展开入队 + 开局事件（全幂等）
    _append_once(batches_led, "batch_dispatch_started", batch_id)
    prompts = _golden_prompts()
    git_commit = _git_head()
    run_specs: list[tuple] = []
    for cfg, chash in zip(configs, hashes):
        run_id = make_run_id(batch_id, chash)
        seed = int(cfg.get("decoding", {}).get("seeds", [0])[0])
        item_ids = _golden_ids(int(cfg.get("benchmark", {}).get("item_limit", 0)))
        queue.enqueue(run_id, {"config": cfg, "batch_id": batch_id, "run_id": run_id,
                               "seed": seed, "config_hash": chash})
        _append_once(runs_led, "run_registered", run_id, batch_id=batch_id, config_hash=chash)
        _append_once(runs_led, "run_queued", run_id, batch_id=batch_id)
        _append_once(costs_led, "run_cost_estimated", run_id,
                     amount_cny=0.0, basis="fake", batch_id=batch_id)
        run_specs.append((run_id, cfg, item_ids, seed, chash))

    # step4：启动对账（孤儿 running → suspended；失败/挂起可续则续）
    runstate.scan_orphans()

    # step5+6：逐 run 驱动 + 评分
    results: dict[str, str] = {}
    for run_id, cfg, item_ids, seed, chash in run_specs:
        results[run_id] = _process_run(run_id, cfg, item_ids, seed, chash, batch_id,
                                        runs_led, state_dir, prompts, git_commit)

    # step7：批次收口
    done = set(queue.list_state("done"))
    all_done = all(rid in done for rid, *_ in run_specs)
    print("[dispatch] run 结果:")
    for rid, *_ in run_specs:
        print(f"  {rid}: {results[rid]} (queue={_queue_state(rid)})")
    if all_done:
        _append_once(batches_led, "batch_settled", batch_id)
        tok.consume_token(token, consumed_store)   # AMENDMENT-37：业务收口成功后才烧令牌
        # 批次收口 = 账本外部封印点（根因①接线）。此刻起 batches/costs/runs_index 三链
        # 的内容与条目数被承诺进仓级规范锚存储；日后任何人物理截断链尾（例如把
        # costs.jsonl 尾部超支行删掉再重算），审计侧 verify_external_seal 的 length
        # 承诺立刻失配。封印失败绝不阻断收口（告警侧异常不得拖垮业务路径）。
        # V09 防洗白：走 external_seal.guarded_reseal（seal-once + 前缀校验），**不**用
        # 无条件覆盖的 led.seal_chain()——若既有锚承诺的前缀已被截断/改写，重封被拒并
        # 落一条 anchor_mismatch 告警，绝不拿被篡改后的内容盖掉旧锚把篡改洗成合规。
        for led in (batches_led, costs_led, runs_led):
            try:
                evs = led.events()
                tail = evs[-1]["entry_hash"] if evs else GENESIS_HASH
                rec = external_seal.guarded_reseal(
                    external_seal.KIND_LEDGER_CHAIN, led.run_id, evs,
                    extra={"chain_path": str(led.path), "chain_tail": tail,
                           "sealed_by": "dispatch"},
                    scope_extra_keys=("chain_path",))
                print(f"[dispatch] 链 {led.run_id} 已 seal（length={rec['length']}）")
            except external_seal.ResealRefused as e:
                _write_alert(state_dir, "anchor_mismatch", led.run_id, str(e), severity="A")
                print(f"[dispatch] 链 {led.run_id} 重封拒绝（防洗白，已落 anchor_mismatch 告警）: {e}",
                      file=sys.stderr, flush=True)
            except Exception as e:                 # noqa: BLE001
                print(f"[dispatch] 链 {led.run_id} seal 失败: {type(e).__name__}: {e}",
                      file=sys.stderr, flush=True)
        print(f"[dispatch] batch_settled {batch_id}；6 run 全部 completed + scored；退出码 0")
        return 0
    print(f"[dispatch] 批次未收口（部分 run 未 done）：{sorted(set(run for run,*_ in run_specs) - done)}",
          file=sys.stderr, flush=True)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="ABCR dispatch —— 信封消费与逐 run 驱动")
    ap.add_argument("--envelope", required=True, help="批次信封 JSON 路径")
    ap.add_argument("--key", default="state/approval.key", help="审批 HMAC 密钥文件")
    a = ap.parse_args()
    return dispatch(a.envelope, a.key)


if __name__ == "__main__":
    raise SystemExit(main())
