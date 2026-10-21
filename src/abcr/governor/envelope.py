"""abcr.governor.envelope —— 批次信封：格式校验、规范化、envelope_sha256（契约 §3.5/§3.7 实现）。

架构位置：包C·Governor 起草侧。abcrctl approve 用 envelope_sha256 绑定令牌；
B 的 dispatch 用同一函数核对（经本模块，勿自行序列化）。
关键不变量：approval 字段不进哈希 → 签发/换签不破坏令牌与信封的哈希绑定。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ENVELOPE_VERSION = "1.0"
BATCH_ID_RE = re.compile(r"^B-\d{8}T\d{6}Z-\d{4}$")

REQUIRED_TOP = ("envelope_version", "batch_id", "protocol_ref", "scope",
                "budget", "deadline_utc", "run_configs", "drafted_by")
REQUIRED_SCOPE = ("benchmark_families", "conditions", "splits",
                  "item_limit_per_run", "seeds", "trait_whitelist")
REQUIRED_BUDGET = ("gpu_hours_max", "cost_cap_cny")

# 契约 §3.4 condition 枚举（scope.conditions 的合法全集）
CONDITION_ENUM = frozenset({
    "vanilla", "persona_text", "neutral_token", "length_instruct", "inject",
    "ablate", "inject_random", "ablate_random", "synthetic_test", "fake"})
SPLIT_ENUM = frozenset({"dev", "calibration", "holdout", "none"})
# "none" 系 AMENDMENT-41:仅 golden10/fake 类无 split 基准合法;
# planner P1 对真实批仍限 dev/calibration,防护不减。


def canonical_json(obj: Any) -> str:
    """契约 §3.7 规范化口径（紧凑 separators——与令牌载荷的默认口径不同，勿混）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def envelope_sha256(env: dict) -> str:
    """对信封去 approval 字段后的规范化 JSON 取 sha256。"""
    core = {k: v for k, v in env.items() if k != "approval"}
    return hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()


def validate_envelope(env: dict) -> tuple[bool, list[str]]:
    """结构校验。返回 (ok, problems)。不抛异常；problems 逐条可读。"""
    problems: list[str] = []
    if not isinstance(env, dict):
        return False, ["信封不是 JSON 对象"]
    for k in REQUIRED_TOP:
        if k not in env:
            problems.append(f"缺顶层字段: {k}")
    if problems:
        return False, problems
    if env["envelope_version"] != ENVELOPE_VERSION:
        problems.append(f"envelope_version: '{env['envelope_version']}' != '{ENVELOPE_VERSION}'")
    if not BATCH_ID_RE.match(str(env["batch_id"])):
        problems.append("batch_id: 不符 B-<UTC:%Y%m%dT%H%M%SZ>-<4位序号>")
    scope = env["scope"]
    if not isinstance(scope, dict):
        problems.append("scope: 非对象")
    else:
        for k in REQUIRED_SCOPE:
            if k not in scope:
                problems.append(f"缺 scope.{k}")
        conds = scope.get("conditions", [])
        if not isinstance(conds, list) or not conds:
            problems.append("scope.conditions: 须为非空列表")
        else:
            for c in conds:
                if c not in CONDITION_ENUM:
                    problems.append(f"scope.conditions: '{c}' 不在枚举")
        splits = scope.get("splits", [])
        if not isinstance(splits, list) or not splits:
            problems.append("scope.splits: 须为非空列表")
        else:
            for s in splits:
                if s not in SPLIT_ENUM:
                    problems.append(f"scope.splits: '{s}' 不在枚举")
        lim = scope.get("item_limit_per_run")
        if not (isinstance(lim, int) and not isinstance(lim, bool) and lim > 0):
            problems.append("scope.item_limit_per_run: 须为正整数")
        seeds = scope.get("seeds", [])
        if (not isinstance(seeds, list) or not seeds
                or any(isinstance(x, bool) or not isinstance(x, int) for x in seeds)):
            problems.append("scope.seeds: 须为非空 int 列表")
        elif len(set(seeds)) != len(seeds):
            problems.append(f"scope.seeds: 含重复 seed {seeds}（须唯一，F-GOV-07）")
        if not isinstance(scope.get("trait_whitelist"), list):
            problems.append("scope.trait_whitelist: 须为列表（可空）")
        if not isinstance(scope.get("benchmark_families"), list) or not scope.get("benchmark_families"):
            problems.append("scope.benchmark_families: 须为非空列表")
    budget = env["budget"]
    if not isinstance(budget, dict):
        problems.append("budget: 非对象")
    else:
        for k in REQUIRED_BUDGET:
            v = budget.get(k)
            if k not in budget:
                problems.append(f"缺 budget.{k}")
            elif (isinstance(v, bool) or not isinstance(v, (int, float))
                  or not math.isfinite(v) or v < 0):
                # NaN/Inf 亦拒（isfinite）：NaN<0 恒 False 会被旧检查放行（P1-50/51/F-DRB-02）
                problems.append(f"budget.{k}: 须为有限非负数值（拒 NaN/Inf/负）")
    # protocol_ref 结构：非空字符串（内容/时效由 dispatch 运行期核对，见 dispatch.py）
    pref = env.get("protocol_ref")
    if not isinstance(pref, str) or not pref.strip():
        problems.append("protocol_ref: 须为非空字符串")
    # deadline_utc 结构：可解析 ISO8601（时效/过期由 dispatch 运行期核对）
    dl = env.get("deadline_utc")
    if not isinstance(dl, str):
        problems.append("deadline_utc: 须为 ISO8601 字符串")
    else:
        try:
            datetime.fromisoformat(dl)
        except (ValueError, TypeError):
            problems.append(f"deadline_utc: 非法 ISO8601 '{dl}'")
    if not isinstance(env["run_configs"], list) or not env["run_configs"]:
        problems.append("run_configs: 须为非空列表")
    return (len(problems) == 0), problems


def load_envelope(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_envelope(path: Path, env: dict) -> None:
    """落盘形态自由（indent=2 供人读）；哈希只对 canonical_json 字符串算，与落盘形态无关。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(env, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
