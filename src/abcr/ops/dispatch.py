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
import copy
import fcntl
import hashlib
import json
import os
import platform
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from abcr.audit import treehash
from abcr.common import approval_token as tok
from abcr.common import external_seal
from abcr.common.constants import PROTOCOL_REF, STATE_DIR_DEFAULT
from abcr.common.ledger_ref import GENESIS_HASH, RunLedger, append_record
from abcr.control.contracts import ContractError, sha256
from abcr.explore.item_pool import DevBundleRef, iter_bundle_items
from abcr.governor.envelope import envelope_sha256
from abcr.ops import faketask, queue, runstate
from abcr.ops.heartbeat import Heartbeat
from abcr.rig import scorer

LEDGER_DIR_DEFAULT = Path("ledger")
RUNS_ROOT_DEFAULT = Path("data/runs")
GOLDEN_PATH = Path("data/golden/golden10.json")   # 输入(只读真仓)——不隔离
W1_TOTAL_BUDGET_CNY = 150.0   # 全局硬顶（呈现纪律 ¥150 常量）；信封 cost_cap 不得越顶
PRODUCTION_RUN_CONTROL_ROOT = Path(
    "/Users/superagent/Library/Application Support/ABCR-Evidence/dispatch-state/run-controls")


class _PauseAtBoundary(RuntimeError):
    pass


class _AbortAtBoundary(RuntimeError):
    pass


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


def _explicit_string_list(value: object, field: str) -> list[str]:
    if (not isinstance(value, list) or not value
            or not all(isinstance(item, str) and item for item in value)
            or len(value) != len(set(value))):
        raise ContractError("dispatch_items_invalid", f"{field} 必须是不重复的非空字符串数组")
    return list(value)


def _dev_bundle_ref_from_config(cfg: dict, trusted_root: Path) -> DevBundleRef:
    raw = cfg.get("dev_bundle_ref")
    if not isinstance(raw, dict):
        raise ContractError("dev_bundle_ref_missing", "证据 dispatch 必须携带 DevBundleRef")
    if any(key in raw for key in ("root", "path", "dataset_path", "split_path")):
        raise ContractError("dev_bundle_ref_path_injection", "DevBundleRef 不接受调用方路径")
    required = {"bundle_id", "manifest_hash", "item_ids", "source_hash"}
    if set(raw) != required:
        raise ContractError("dev_bundle_ref_invalid", "DevBundleRef 字段集合不精确",
                            {"required": sorted(required), "actual": sorted(raw)})
    item_ids = tuple(_explicit_string_list(raw["item_ids"], "dev_bundle_ref.item_ids"))
    for key in ("bundle_id", "manifest_hash", "source_hash"):
        value = raw[key]
        if (not isinstance(value, str) or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)):
            raise ContractError("dev_bundle_ref_invalid", f"{key} 必须是小写 SHA-256")
    return DevBundleRef(raw["bundle_id"], trusted_root / raw["bundle_id"],
                        raw["manifest_hash"], item_ids, raw["source_hash"])


def _legacy_golden_items(cfg: dict) -> tuple[list[str], dict[str, str]]:
    """Only the frozen R1 fixture path may read golden10 directly.

    Evidence configurations are identified by ``dev_bundle_ref`` and can never
    fall through to this compatibility path.  In particular a non-golden family
    without a sealed bundle fails instead of borrowing golden prompts.
    """
    benchmark = cfg.get("benchmark") or {}
    if benchmark.get("family", "golden10") != "golden10":
        raise ContractError("dev_bundle_ref_missing",
                            "非 golden family 禁止从仓内 benchmark 取题；必须使用封印 DevBundle")
    if benchmark.get("split", "none") != "none":
        raise ContractError("dispatch_split_violation", "legacy golden fixture 的 split 必须为 none")
    item_ids = _golden_ids(int(benchmark.get("item_limit", 0)))
    prompts = _golden_prompts()
    return item_ids, {item_id: prompts[item_id] for item_id in item_ids}


def load_dispatch_items(cfg: dict, *, trusted_root: Path | None = None,
                        sealer_public_key: Path | None = None) -> list[dict]:
    """Load the exact item bytes selected by a sealed dev bundle.

    The trusted root and public key are deployment configuration, never fields
    in an approved RunConfig.  This function deliberately has no benchmark or
    split-root parameter: dispatch cannot see the full corpus.
    """
    if "dev_bundle_ref" not in cfg:
        ids, prompts = _legacy_golden_items(cfg)
        return [{"item_id": item_id, "prompt": prompts[item_id]} for item_id in ids]
    root = Path(trusted_root or os.environ.get("ABCR_DEV_BUNDLE_ROOT", ""))
    public_key = Path(sealer_public_key or os.environ.get("ABCR_DEV_BUNDLE_SEALER_PUBLIC_KEY", ""))
    if not str(root) or str(root) == "." or not str(public_key) or str(public_key) == ".":
        raise ContractError("dev_bundle_trust_missing", "dispatch 缺可信 DevBundle root 或封印公钥")
    ref = _dev_bundle_ref_from_config(cfg, root)
    explicit_ids = tuple(_explicit_string_list(cfg.get("item_ids"), "item_ids"))
    if explicit_ids != ref.item_ids:
        raise ContractError("dispatch_item_set_mismatch", "RunConfig item_ids 与 DevBundleRef 不精确相等")
    benchmark = cfg.get("benchmark") or {}
    if benchmark.get("split") != "dev":
        raise ContractError("dispatch_split_violation", "证据 dispatch 只接受 split=dev")
    limit = benchmark.get("item_limit")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)
                              or limit != len(explicit_ids)):
        raise ContractError("dispatch_item_limit_mismatch", "item_limit 必须精确等于显式 item_ids 数量")
    receipt = cfg.get("selection_receipt")
    if not isinstance(receipt, dict):
        raise ContractError("selection_receipt_missing", "证据 dispatch 必须携带 selection receipt")
    receipt_expected = {
        "bundle_id": ref.bundle_id, "manifest_hash": ref.manifest_hash,
        "source_hash": ref.source_hash, "split": "dev", "item_ids": list(ref.item_ids),
    }
    if any(receipt.get(key) != value for key, value in receipt_expected.items()):
        raise ContractError("selection_receipt_mismatch", "selection receipt 与 DevBundleRef 不一致")
    items = list(iter_bundle_items(ref, root, sealer_public_key=public_key))
    observed_ids = tuple(item.get("item_id") for item in items)
    if observed_ids != explicit_ids:
        raise ContractError("dispatch_item_set_mismatch", "selected item bytes 与显式 item_ids 不一致")
    family = benchmark.get("family")
    for item in items:
        if not isinstance(item.get("prompt"), str) or not item["prompt"]:
            raise ContractError("dispatch_prompt_missing", "DevBundle item 缺非空 prompt")
        if item.get("family") not in (None, family):
            raise ContractError("dispatch_family_mismatch", "DevBundle item family 与 RunConfig 不一致")
    return items


def _validate_compile_binding(cfg: dict, envelope: dict, items: list[dict]) -> None:
    """Require every evidence RunConfig to repeat the approved compile/research facts."""
    if "dev_bundle_ref" not in cfg:
        return
    evidence = cfg.get("evidence_inputs")
    if not isinstance(evidence, dict):
        raise ContractError("evidence_inputs_missing", "证据 RunConfig 缺 evidence_inputs")
    ref = cfg["dev_bundle_ref"]
    receipt = cfg["selection_receipt"]
    required = {
        "goal_hash": envelope.get("goal_hash"),
        "goal_receipt_id": envelope.get("goal_receipt_id"),
        "research_commit": envelope.get("research_commit"),
        "deployment_id": envelope.get("deployment_id"),
        "protocol_ref": envelope.get("protocol_ref"),
        "dev_bundle_id": ref["bundle_id"],
        "dev_bundle_manifest_hash": ref["manifest_hash"],
        "source_hash": ref["source_hash"],
        "item_set_hash": sha256(list(ref["item_ids"])),
        "selected_bytes_hash": receipt.get("selected_bytes_hash"),
    }
    if any(not isinstance(required[key], str) or not required[key] for key in required):
        raise ContractError("compile_binding_missing", "compile envelope/selection receipt 缺研究或证据绑定")
    for key, value in required.items():
        if evidence.get(key) != value:
            raise ContractError("compile_binding_mismatch", f"RunConfig evidence_inputs.{key} 与编译信封不一致")
    raw_bytes = b"".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        for item in items)
    if sha256(raw_bytes) != evidence["selected_bytes_hash"]:
        raise ContractError("selected_bytes_hash_mismatch", "dispatch 重算 selected item bytes 失败")
    release = cfg.get("release_pin")
    if not isinstance(release, dict):
        raise ContractError("release_pin_missing", "证据 RunConfig 缺不可变 release pin")
    for field in ("release_id", "release_tree_hash", "release_lock_hash"):
        if release.get(field) != evidence.get(field):
            raise ContractError("release_pin_mismatch", f"release_pin.{field} 与 evidence_inputs 不一致")
    launched_release = os.environ.get("ABCR_RELEASE_ID")
    if os.environ.get("ABCR_SERVICE_LABEL") and launched_release != release["release_id"]:
        raise ContractError("active_release_mismatch", "实际 active release 与批准 RunConfig 不一致")


def _seeds(cfg: dict) -> list[int]:
    values = (cfg.get("decoding") or {}).get("seeds")
    if (not isinstance(values, list) or not values
            or not all(isinstance(seed, int) and not isinstance(seed, bool) for seed in values)
            or len(values) != len(set(values))):
        raise ContractError("dispatch_seeds_invalid", "decoding.seeds 必须是不重复的非空整数数组")
    return values


def expand_all_seed_configs(configs: list[dict]) -> list[dict]:
    """Deterministically derive one immutable run config per configured seed."""
    expanded: list[dict] = []
    for original in configs:
        for seed in _seeds(original):
            cfg = copy.deepcopy(original)
            cfg.setdefault("decoding", {})["seeds"] = [seed]
            expanded.append(cfg)
    return expanded


def _fake_render_prompts(cfg: dict, prompts: dict[str, str]) -> dict[str, str]:
    """Frozen fake serializer used only for non-citable P4 wiring tests."""
    condition = cfg.get("condition")
    if "dev_bundle_ref" not in cfg or condition not in {"persona_text", "length_instruct"}:
        return prompts
    system = cfg.get("prompt_text")
    if not isinstance(system, str) or not system:
        raise ContractError("inline_prompt_missing", f"{condition} 缺 inline prompt_text")
    if cfg.get("prompt_sha256") != hashlib.sha256(system.encode("utf-8")).hexdigest():
        raise ContractError("inline_prompt_hash_mismatch", "inline prompt_text 与 prompt_sha256 不一致")
    return {item_id: f"{system}\n\n{prompt}" for item_id, prompt in prompts.items()}


def _append_prompt_sidecar_once(run_dir: Path, row: dict) -> None:
    """Crash-idempotent raw prompt evidence; conflicting replay fails closed."""
    if os.environ.get("ABCR_SERVICE_LABEL"):
        if (not isinstance(row.get("arm_id"), str) or not row["arm_id"]
                or not isinstance(row.get("config_hash"), str)
                or len(row["config_hash"]) != 64):
            raise ContractError("prompt_sidecar_arm_binding_missing",
                                "生产 prompt sidecar 缺 arm_id/config_hash")
    evidence_root = os.environ.get("ABCR_EVIDENCE_ROOT")
    base = (Path(evidence_root) / "runs" / row["run_id"]
            if evidence_root else Path(run_dir))
    path = base / "logs" / "rendered_prompts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    key = (row["run_id"], row["item_id"], row["random_seed"])
    with lock.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    existing = json.loads(line)
                    if (existing.get("run_id"), existing.get("item_id"),
                            existing.get("random_seed")) == key:
                        if existing != row:
                            raise ContractError("prompt_sidecar_conflict", "同一 prompt sidecar key 内容冲突")
                        return
            with path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                out.flush(); os.fsync(out.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
        "split_hash": (cfg.get("evidence_inputs") or {}).get("source_hash", "fixture"),
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
    release = cfg.get("release_pin") or {}
    manifest = {
        "run_id": run_id,
        "config": cfg,
        "config_hash": chash,
        "git_commit": git_commit,
        "git_clean": _git_clean(),
        "code_tree_hash": _code_tree_hash(),
        "model_id": "fake/deterministic-v1",
        "model_revision": "fixture",
        "chat_template_hash": (cfg.get("evidence_inputs") or {}).get(
            "chat_template_sha256", "fixture"),
        "split_hash": (cfg.get("evidence_inputs") or {}).get("source_hash", "fixture"),
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
        "release_id": release.get("release_id"),
        "release_tree_hash": release.get("release_tree_hash"),
        "release_lock_hash": release.get("release_lock_hash"),
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
                 prompts: dict[str, str], selected_items: dict[str, dict],
                 git_commit: str) -> str:
    qstate = _queue_state(run_id)
    if qstate == "done":
        return "skip-done"

    rec = runstate.load(run_id)
    if rec is not None and rec.get("status") == runstate.STATUS_ABORTED:
        return "skip-aborted"
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
        prompt = _fake_render_prompts(cfg, {item_id: prompts[item_id]})[item_id]
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        _append_prompt_sidecar_once(run_dir, {
            "run_id": run_id, "item_id": item_id, "seed": seed, "random_seed": seed,
            "config_hash": chash, "arm_id": cfg.get("arm_id"),
            "condition": cfg.get("condition", "fake"), "prompt_text": prompt,
            "prompt_hash": prompt_hash,
            "system_prompt_hash": hashlib.sha256(
                str(cfg.get("prompt_text", "")).encode("utf-8")).hexdigest(),
            "template_hash": "fixture",
        })
        rec_step = _build_step(run_id, item_id, output_text, cfg, seed, chash,
                               {item_id: prompt}, git_commit)
        if rec_step["prompt_hash"] != prompt_hash:
            raise ContractError("prompt_sidecar_hash_mismatch", "step 与 prompt sidecar hash 不一致")
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
        root_text = (str(PRODUCTION_RUN_CONTROL_ROOT) if os.environ.get("ABCR_SERVICE_LABEL")
                     else os.environ.get("ABCR_RUN_CONTROL_ROOT"))
        if root_text:
            from abcr.control.signals import RunControl
            desired = RunControl(Path(root_text)).read(run_id)
            if desired is not None:
                release_id = str((cfg.get("release_pin") or {}).get("release_id", "fixture"))
                if desired.release_id != release_id:
                    raise ContractError("release_pin_mismatch",
                                        "运行控制记录不能跨 release 操作 run")
                if desired.desired == "paused":
                    raise _PauseAtBoundary(desired.reason or "item-boundary pause")
                if desired.desired == "aborted":
                    raise _AbortAtBoundary(desired.reason or "item-boundary abort")

    pend = runstate.pending_items(run_id)
    try:
        if engine == "fake":
            output_for_item = None
            if "dev_bundle_ref" in cfg:
                output_for_item = lambda item_id: (
                    "[devbundle-fake] " + hashlib.sha256(
                        prompts[item_id].encode("utf-8")).hexdigest()[:16])
            faketask.run_items(pend, emit_step, mark_done, output_for_item=output_for_item)
        else:
            from abcr.rig import runner        # 惰性 import：runner 顶层 import dispatch，避免循环
            runner.run_items(pend, cfg, seed, run_id, chash, git_commit, prompts,
                             append_step, mark_done, run_dir, batch_id=batch_id)
    except _PauseAtBoundary as exc:
        runstate.mark_suspended(run_id, str(exc))
        _append_once(runs_led, "run_suspended", run_id, batch_id=batch_id,
                     reason=str(exc), boundary="item")
        queue.settle(run_id, ok=False)
        return "paused"
    except _AbortAtBoundary as exc:
        runstate.mark_aborted(run_id, str(exc))
        _append_once(runs_led, "run_aborted", run_id, batch_id=batch_id,
                     reason=str(exc), boundary="item")
        queue.settle(run_id, ok=False)
        return "aborted"
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
        scorer.score_run(run_dir, selected_items=(selected_items if "dev_bundle_ref" in cfg else None))
        runs_led.append("run_scored", subject_id=run_id, batch_id=batch_id)
    return "completed"


@dataclass(frozen=True)
class ClaimedDispatchRoots:
    """Operator-owned fixed roots for the post-v2-claim preparation step."""

    queue_root: Path
    state_root: Path
    ledger_root: Path
    dev_bundle_root: Path
    bundle_sealer_public_key: Path


def _prepare_root(path: Path, label: str, *, writable: bool) -> Path:
    value = Path(path)
    if not value.is_absolute() or value.is_symlink() or not value.is_dir():
        raise ContractError("dispatch_root_unsafe", f"{label} 必须是固定真实绝对目录")
    info = value.lstat()
    if writable and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
        raise ContractError("dispatch_root_unsafe", f"{label} owner/mode 不安全")
    if not os.access(value, os.R_OK | os.X_OK | (os.W_OK if writable else 0)):
        raise ContractError("dispatch_root_unavailable", f"{label} 权限不足")
    return value


def _write_json_once(path: Path, value: dict, *, conflict_code: str) -> None:
    """Durably publish exact bytes once; a non-identical replay is corruption."""
    canonical_json_bytes = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    expected = canonical_json_bytes
    if path.exists():
        if path.is_symlink() or path.read_bytes() != expected:
            raise ContractError(conflict_code, f"幂等目标内容冲突: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("xb") as handle:
            handle.write(canonical_json_bytes); handle.flush(); os.fsync(handle.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != expected:
                raise ContractError(conflict_code, f"并发幂等目标内容冲突: {path.name}")
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        tmp.unlink(missing_ok=True)


def _prepare_runstate_once(path: Path, value: dict) -> None:
    """Publish queued state once while accepting later legitimate progress."""
    if path.exists():
        if path.is_symlink():
            raise ContractError("claimed_runstate_conflict", "runstate 不能是 symlink")
        try:
            observed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError("claimed_runstate_conflict", "runstate 无法解析") from exc
        immutable_meta = value["meta"]
        if (observed.get("run_id") != value["run_id"]
                or set((observed.get("items") or {})) != set(value["items"])
                or any((observed.get("meta") or {}).get(key) != expected
                       for key, expected in immutable_meta.items())):
            raise ContractError("claimed_runstate_conflict", "runstate 不可变身份与 claim 冲突")
        return
    _write_json_once(path, value, conflict_code="claimed_runstate_conflict")


def prepare_claimed_dispatch(*, envelope: dict, approval_binding: dict,
                             dispatch_event_id: str,
                             roots: ClaimedDispatchRoots) -> dict[str, object]:
    """Prepare an approved batch after a v2 Human claim, without executing it.

    This adapter deliberately has no HMAC key parameter and invokes no model,
    cloud or scorer.  It validates the complete P4 evidence/release binding, then
    publishes deterministic existing-queue entries plus queued runstate records.
    Replaying the same claim is byte-idempotent; changing any config or binding
    under the same run id fails closed.
    """
    from abcr.governor.envelope import envelope_sha256 as approved_envelope_sha256

    if not isinstance(envelope, dict):
        raise ContractError("claimed_envelope_invalid", "claimed envelope 必须是对象")
    binding = strict_binding = {
        key: approval_binding.get(key) for key in (
            "token_id", "claim_id", "batch_id", "envelope_sha256", "release_id")}
    if set(approval_binding) != set(binding):
        raise ContractError("approval_binding_invalid", "approval binding 字段集合不精确")
    if not all(isinstance(strict_binding[key], str) and strict_binding[key]
               for key in strict_binding):
        raise ContractError("approval_binding_invalid", "approval binding 字段必须非空")
    batch_id = envelope.get("batch_id")
    digest = approved_envelope_sha256(envelope)
    if (binding["batch_id"] != batch_id or binding["envelope_sha256"] != digest
            or len(digest) != 64):
        raise ContractError("approval_binding_mismatch", "Human claim 未绑定当前完整 envelope")
    if not isinstance(dispatch_event_id, str) or not dispatch_event_id:
        raise ContractError("dispatch_event_invalid", "dispatch_event_id 必须是稳定非空字符串")

    queue_root = _prepare_root(roots.queue_root, "queue root", writable=True)
    state_root = _prepare_root(roots.state_root, "state root", writable=True)
    ledger_root = _prepare_root(roots.ledger_root, "ledger root", writable=True)
    bundle_root = _prepare_root(roots.dev_bundle_root, "dev bundle root", writable=False)
    public_key = Path(roots.bundle_sealer_public_key)
    if (not public_key.is_absolute() or public_key.is_symlink()
            or not public_key.is_file() or not os.access(public_key, os.R_OK)):
        raise ContractError("dispatch_root_unsafe", "bundle sealer public key 不安全")

    configs = envelope.get("run_configs")
    scope = envelope.get("scope")
    if (not isinstance(configs, list) or not configs
            or not all(isinstance(config, dict) for config in configs)
            or not isinstance(scope, dict)):
        raise ContractError("claimed_envelope_invalid", "claimed envelope 缺内联 RunConfigs/scope")
    prepared: list[tuple[str, dict, list[str], str]] = []
    for cfg in configs:
        violation = _scope_violation(cfg, scope)
        if violation:
            raise ContractError("claimed_scope_violation", violation)
        seeds = _seeds(cfg)
        if len(seeds) != 1:
            raise ContractError("claimed_config_not_atomic", "claimed RunConfig 必须已展开为单 seed")
        items = load_dispatch_items(cfg, trusted_root=bundle_root,
                                    sealer_public_key=public_key)
        _validate_compile_binding(cfg, envelope, items)
        release = cfg["release_pin"]
        if release["release_id"] != binding["release_id"]:
            raise ContractError("claimed_release_mismatch", "claim release 与 RunConfig pin 不一致")
        chash = config_hash(cfg)
        prepared.append((make_run_id(str(batch_id), chash), cfg,
                         [item["item_id"] for item in items], chash))
    if len({row[0] for row in prepared}) != len(prepared):
        raise ContractError("claimed_run_id_collision", "claimed RunConfigs 产生重复 run_id")

    runs = RunLedger(ledger_root, "runs_index")
    batches = RunLedger(ledger_root, "batches")
    if not batches.has_event("batch_dispatch_started", str(batch_id)):
        batches.append("batch_dispatch_started", subject_id=batch_id,
                       dispatch_event_id=dispatch_event_id,
                       token_id=binding["token_id"], claim_id=binding["claim_id"],
                       envelope_sha256=digest, release_id=binding["release_id"])
    else:
        rows = batches.events(event="batch_dispatch_started", subject_id=str(batch_id))
        if not any(row.get("dispatch_event_id") == dispatch_event_id
                   and row.get("claim_id") == binding["claim_id"]
                   and row.get("envelope_sha256") == digest for row in rows):
            raise ContractError("claimed_dispatch_conflict", "batch 已由不同 claim/事件启动")

    queued: list[str] = []
    for run_id, cfg, item_ids, chash in prepared:
        state = {"run_id": run_id, "status": "queued",
                 "items": {item_id: "pending" for item_id in item_ids},
                 "meta": {"batch_id": batch_id, "config_hash": chash,
                          "release_id": binding["release_id"],
                          "dispatch_event_id": dispatch_event_id,
                          "claim_id": binding["claim_id"]},
                 "reason": "", "resume_count": 0}
        _prepare_runstate_once(state_root / "runs" / f"{run_id}.json", state)
        payload = {"config": cfg, "batch_id": batch_id, "run_id": run_id,
                   "seed": _seeds(cfg)[0], "config_hash": chash,
                   "approval_binding": binding, "dispatch_event_id": dispatch_event_id}
        existing = [queue_root / stage / f"{run_id}.json" for stage in queue.STATES
                    if (queue_root / stage / f"{run_id}.json").exists()]
        if existing:
            if len(existing) != 1 or existing[0].is_symlink() or json.loads(
                    existing[0].read_text(encoding="utf-8")) != payload:
                raise ContractError("claimed_queue_conflict", "run queue payload 冲突")
        else:
            _write_json_once(queue_root / "pending" / f"{run_id}.json", payload,
                             conflict_code="claimed_queue_conflict")
        if not runs.has_event("run_registered", run_id):
            runs.append("run_registered", subject_id=run_id, batch_id=batch_id,
                        config_hash=chash, release_id=binding["release_id"],
                        dispatch_event_id=dispatch_event_id)
        else:
            prior = runs.events(event="run_registered", subject_id=run_id)
            if not any(row.get("batch_id") == batch_id
                       and row.get("config_hash") == chash
                       and row.get("release_id") == binding["release_id"]
                       and row.get("dispatch_event_id") == dispatch_event_id
                       for row in prior):
                raise ContractError("claimed_run_registration_conflict",
                                    "run_registered 已绑定不同 claim/config")
        queued.append(run_id)
    return {"batch_id": batch_id, "dispatch_event_id": dispatch_event_id,
            "envelope_sha256": digest, "run_ids": queued, "prepared": len(queued)}


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
    original_configs = _load_run_configs(envelope)
    for cfg in original_configs:
        v = _scope_violation(cfg, scope)
        if v:
            _reject(batches_led, state_dir, batch_id, v, alert_kind="scope-rejected")
            print(f"[dispatch] scope FAILED: {v}", file=sys.stderr, flush=True)
            return 2
    try:
        configs = expand_all_seed_configs(original_configs)
    except ContractError as exc:
        _reject(batches_led, state_dir, batch_id, exc.code, alert_kind="scope-rejected")
        print(f"[dispatch] seed expansion FAILED: {exc.code}", file=sys.stderr, flush=True)
        return 2
    hashes = [config_hash(c) for c in configs]
    if len(set(hashes)) != len(hashes):
        _reject(batches_led, state_dir, batch_id, "DUPLICATE_CONFIG_HASH",
                alert_kind="scope-rejected")
        print("[dispatch] scope FAILED: DUPLICATE_CONFIG_HASH", file=sys.stderr, flush=True)
        return 2
    # step3：展开入队 + 开局事件（全幂等）
    git_commit = _git_head()
    run_specs: list[tuple] = []
    try:
        for cfg, chash in zip(configs, hashes):
            items = load_dispatch_items(cfg)
            _validate_compile_binding(cfg, envelope, items)
            item_ids = [item["item_id"] for item in items]
            prompts = {item["item_id"]: item["prompt"] for item in items}
            selected_items = {item["item_id"]: item for item in items}
            run_id = make_run_id(batch_id, chash)
            seed = _seeds(cfg)[0]
            run_specs.append((run_id, cfg, item_ids, seed, chash, prompts, selected_items))
    except ContractError as exc:
        _reject(batches_led, state_dir, batch_id, exc.code, alert_kind="dispatch-input-rejected")
        print(f"[dispatch] item/binding FAILED: {exc.code}", file=sys.stderr, flush=True)
        return 2

    # Evidence arms sharing a bundle must see the exact same item set and seed set.
    evidence_groups: dict[tuple[str, str], dict[str, tuple[tuple[str, ...], set[int]]]] = {}
    for run_id, cfg, item_ids, seed, chash, prompts, selected_items in run_specs:
        ref = cfg.get("dev_bundle_ref")
        if not isinstance(ref, dict):
            continue
        group = (str((cfg.get("benchmark") or {}).get("family")), str(ref["bundle_id"]))
        condition = str(cfg.get("condition"))
        by_condition = evidence_groups.setdefault(group, {})
        ids, seeds = by_condition.setdefault(condition, (tuple(item_ids), set()))
        if ids != tuple(item_ids):
            _reject(batches_led, state_dir, batch_id, "EVIDENCE_DISPATCH_ITEM_MISMATCH",
                    alert_kind="dispatch-input-rejected")
            return 2
        seeds.add(seed)
    for by_condition in evidence_groups.values():
        signatures = {(ids, tuple(sorted(seeds))) for ids, seeds in by_condition.values()}
        if len(signatures) != 1:
            _reject(batches_led, state_dir, batch_id, "EVIDENCE_DISPATCH_NOT_SHARED",
                    alert_kind="dispatch-input-rejected")
            return 2

    _append_once(batches_led, "batch_dispatch_started", batch_id)
    for run_id, cfg, item_ids, seed, chash, prompts, selected_items in run_specs:
        queue.enqueue(run_id, {"config": cfg, "batch_id": batch_id, "run_id": run_id,
                               "seed": seed, "config_hash": chash,
                               "dev_bundle_ref": cfg.get("dev_bundle_ref")})
        _append_once(runs_led, "run_registered", run_id, batch_id=batch_id, config_hash=chash)
        _append_once(runs_led, "run_queued", run_id, batch_id=batch_id)
        _append_once(costs_led, "run_cost_estimated", run_id,
                     amount_cny=0.0, basis="fake", batch_id=batch_id)

    # step4：启动对账（孤儿 running → suspended；失败/挂起可续则续）
    runstate.scan_orphans()

    # step5+6：逐 run 驱动 + 评分
    results: dict[str, str] = {}
    for run_id, cfg, item_ids, seed, chash, prompts, selected_items in run_specs:
        results[run_id] = _process_run(run_id, cfg, item_ids, seed, chash, batch_id,
                                        runs_led, state_dir, prompts, selected_items, git_commit)

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
        print(f"[dispatch] batch_settled {batch_id}；{len(run_specs)} run 全部 completed + scored；退出码 0")
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
