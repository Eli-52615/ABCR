"""abcr.report.views —— DuckDB 只读查询面（包C 自建；对 ledger/ 与 data/runs/ 只 SELECT）。

架构位置：包C·呈现侧三层钻取的查询函数。状态折叠不走 SQL（账本事件序依赖文件序，
用 ledgerio.fold_subjects）；DuckDB 只做 scores/steps 聚合。
空数据护栏（K7）：read_json_auto 对无匹配 glob 抛 IO Error——查询前先 Python glob
判空、空则不下 SQL、直接返回零值结构。
run_id/item_id 进 SQL 一律参数化（K8），不 f-string 拼接。
"""
from __future__ import annotations

import glob
import json
from collections import Counter
from pathlib import Path

import duckdb

from abcr.report import ledgerio


def _read_json(path: str) -> str:
    # DuckDB ≥0.9 语法；1.5.4 实测 OK。若版本报参数不识别，改 read_ndjson_auto（§10 K7）。
    return f"read_json_auto('{path}', format='newline_delimited', union_by_name=true)"


def _scores_pattern(runs_dir: Path) -> str:
    return str(Path(runs_dir) / "*" / "scores.jsonl")


# 账本非可引状态：这些 run 的 scores 不得计入对外聚合（fail-closed：宁漏计不污染）。
# QUARANTINED/FAILED/CANCELLED/REJECTED 及未在账本登记（无现态）的孤儿 scores 一律排除。
_NON_CITABLE_STATES = frozenset({"QUARANTINED", "FAILED", "CANCELLED", "REJECTED",
                                 "DISPATCH_REJECTED"})


def _agg_scores(pattern: str, run_ids: list[str] | None = None) -> list[dict]:
    """condition×metric_name×scorer_id 的均值与 n。空数据 → []（护栏）。

    reducer 硬化（F-GOV-03/04）：
      1) 去重——按 (run_id,item_id,condition,metric_name,scorer_id,random_seed,值) DISTINCT，
         消除断点续跑/重评的重复追加双计（旧实现 n 与均值被重复行拉偏）。
      2) null 口径一致——n=count(非 null 值)、mean=avg(非 null 值)，二者同分母；
         整组全 null（无实测值）→ HAVING 丢弃（不谎报 n，且避免 mean=None 下游崩溃）。
    调用方传 run_ids 以按账本现态过滤（排除 QUARANTINED/FAILED 等，见 overview/batch_detail）。"""
    if not glob.glob(pattern):
        return []
    con = duckdb.connect()
    where = ""
    params: list = []
    if run_ids is not None:
        if not run_ids:
            return []
        placeholders = ",".join("?" * len(run_ids))
        where = f"WHERE run_id IN ({placeholders}) "
        params = run_ids
    sql = (
        f"WITH raw AS (SELECT run_id, item_id, condition, metric_name, scorer_id, "
        f"random_seed, CAST(metric_value AS DOUBLE) AS mv FROM {_read_json(pattern)} {where}), "
        f"dedup AS (SELECT DISTINCT run_id, item_id, condition, metric_name, scorer_id, "
        f"random_seed, mv FROM raw) "
        f"SELECT condition, metric_name, scorer_id, avg(mv) AS mean_value, count(mv) AS n "
        f"FROM dedup GROUP BY condition, metric_name, scorer_id HAVING count(mv) > 0 "
        f"ORDER BY condition, metric_name, scorer_id")
    rows = con.execute(sql, params).fetchall()
    return [{"condition": c, "metric_name": m, "scorer_id": s,
             "mean_value": mean, "n": n} for c, m, s, mean, n in rows]


def _citable_run_ids(ledger_dir: Path) -> list[str]:
    """账本现态非 QUARANTINED/FAILED/… 的 run（含无 scores 者）——聚合白名单。
    孤儿 scores（无账本登记）不在其中，故被排除（fail-closed provenance）。"""
    runs = ledgerio.fold_subjects(
        ledgerio.read_chain_merged(ledger_dir, "runs_index"), ledgerio.RUN_EVENT_STATE)
    return [rid for rid, rec in runs.items() if rec.get("state") not in _NON_CITABLE_STATES]


def overview(ledger_dir: Path, runs_dir: Path) -> dict:
    """L1：批次现态计数、run 现态计数、per-condition 确定性指标均值（分 scorer_id）。"""
    runs = ledgerio.fold_subjects(
        ledgerio.read_chain_merged(ledger_dir, "runs_index"), ledgerio.RUN_EVENT_STATE)
    batches = ledgerio.fold_subjects(
        ledgerio.read_chain_merged(ledger_dir, "batches"), ledgerio.BATCH_EVENT_STATE)
    # F-GOV(quarantine): 按账本现态过滤——QUARANTINED/FAILED 及未登记孤儿 scores 不计入
    citable = [rid for rid, rec in runs.items() if rec.get("state") not in _NON_CITABLE_STATES]
    return {
        "run_state_counts": dict(Counter(r["state"] for r in runs.values() if r["state"])),
        "batch_state_counts": dict(Counter(b["state"] for b in batches.values() if b["state"])),
        "per_condition": _agg_scores(_scores_pattern(runs_dir), citable),
    }


def _runs_of_batch(ledger_dir: Path, batch_id: str) -> dict[str, dict]:
    """AMENDMENT-19：对 runs_index 的 run_registered 事件按 payload.batch_id 过滤折叠。"""
    runs = ledgerio.fold_subjects(
        ledgerio.read_chain_merged(ledger_dir, "runs_index"), ledgerio.RUN_EVENT_STATE)
    out = {}
    for rid, rec in runs.items():
        reg = next((e for e in rec["events"] if e.get("event") == "run_registered"), None)
        if reg and reg.get("batch_id") == batch_id:
            out[rid] = rec
    return out


def _run_condition_seed(pattern: str, run_id: str) -> tuple[str | None, list]:
    """从 scores 取该 run 的 distinct condition 与 seed（未启动 run 无 scores → (None, [])）。"""
    if not glob.glob(pattern):
        return None, []
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT DISTINCT condition, random_seed FROM {_read_json(pattern)} WHERE run_id = ?",
        [run_id]).fetchall()
    conds = {r[0] for r in rows if r[0] is not None}
    seeds = sorted({r[1] for r in rows if r[1] is not None})
    return (next(iter(conds)) if len(conds) == 1 else (";".join(sorted(conds)) or None)), seeds


def batch_detail(batch_id: str, ledger_dir: Path, runs_dir: Path) -> dict:
    """L2：该批 run 清单（run_id/condition/seed/现态）+ 臂级聚合（condition×metric 均值与 n）。"""
    batch_runs = _runs_of_batch(ledger_dir, batch_id)
    pattern = _scores_pattern(runs_dir)
    run_list = []
    for rid, rec in sorted(batch_runs.items()):
        cond, seeds = _run_condition_seed(pattern, rid)
        run_list.append({"run_id": rid, "condition": cond, "seeds": seeds, "state": rec["state"]})
    run_ids = list(batch_runs)
    # 臂级聚合只计入可引 run（排除 QUARANTINED/FAILED 等，fail-closed）
    citable_ids = [rid for rid, rec in batch_runs.items()
                   if rec.get("state") not in _NON_CITABLE_STATES]
    return {
        "batch_id": batch_id,
        "runs": run_list,
        "run_ids": run_ids,
        "arm_aggregate": _agg_scores(pattern, citable_ids),
    }


def per_run_metrics(runs_dir: Path, run_ids: list[str] | None = None) -> list[dict]:
    """逐 run × metric × scorer 的均值与 n（sync evening 逐 run 呈现用）。空数据 → []。"""
    pattern = _scores_pattern(runs_dir)
    if not glob.glob(pattern):
        return []
    con = duckdb.connect()
    where = ""
    params: list = []
    if run_ids is not None:
        if not run_ids:
            return []
        placeholders = ",".join("?" * len(run_ids))
        where = f"WHERE run_id IN ({placeholders}) "
        params = run_ids
    # 去重 + null 口径一致（F-GOV-03/04），同 _agg_scores
    sql = (
        f"WITH raw AS (SELECT run_id, item_id, condition, metric_name, scorer_id, "
        f"random_seed, CAST(metric_value AS DOUBLE) AS mv FROM {_read_json(pattern)} {where}), "
        f"dedup AS (SELECT DISTINCT run_id, item_id, condition, metric_name, scorer_id, "
        f"random_seed, mv FROM raw) "
        f"SELECT run_id, condition, metric_name, scorer_id, avg(mv) AS mean_value, "
        f"count(mv) AS n FROM dedup GROUP BY run_id, condition, metric_name, scorer_id "
        f"HAVING count(mv) > 0 ORDER BY run_id, metric_name, scorer_id")
    return [{"run_id": r, "condition": c, "metric_name": m, "scorer_id": s,
             "mean_value": mean, "n": n} for r, c, m, s, mean, n in con.execute(sql, params).fetchall()]


def run_item(run_id: str, item_id: str, runs_dir: Path) -> dict:
    """L3：单 run 单题——steps.jsonl 中该 item 全部记录（output_text 原文）+ scores 各行。

    读单个 run 的产物，用 Python 过滤（免 SQL 注入面，K8）；output_text 不截断。
    """
    rd = Path(runs_dir) / run_id
    steps_p = rd / "steps.jsonl"
    scores_p = rd / "scores.jsonl"

    def _load(p):
        if not p.exists():
            return []
        return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]

    steps = [r for r in _load(steps_p) if r.get("item_id") == item_id]
    scores = [r for r in _load(scores_p) if r.get("item_id") == item_id]
    return {"run_id": run_id, "item_id": item_id, "steps": steps, "scores": scores}
