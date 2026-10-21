"""abcr.ledger.views —— 账本 DuckDB 只读视图（对外数字的唯一合法出处）。

架构位置：包A·裁判侧。内存 DuckDB 直读 ledger/*.jsonl（含 ledger/cloud-day*/ 云链段
——AMENDMENT-2 合并只读装载）与 data/runs/*/scores.jsonl，不落库文件（防第二事实源）。
消费者：auditor 健康面板、C 的同步视图（只读）、人。

R1-full 项（AMENDMENT-30）：不卡 R1-core 门。全模块只 SELECT，出现任何
INSERT/UPDATE/COPY 即违契（坑11）。精确状态推导恒用 statemachine.derive_run_state
（Python 按文件行序）；SQL 视图是便捷查询面，同秒多事件 tie-break 无语义（实施要点②′）。
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from abcr.ledger.statemachine import derive_run_state, ttl_seconds


def _merged_events(repo_root: Path, chain: str) -> list[dict]:
    """主链 + 云链段（ledger/cloud-day*/<chain>.jsonl）合并只读，按事件全序（ts）排序。

    F-LEDGER-01 修复：权威 reader 旧实现只读 ledger/<chain>.jsonl，静默丢弃全部
    cloud-day 段事件（run_failed 漏报、违 fail-closed）。此处纳入云段，且按 ts 全序
    合并——而非字典序/文件序——使 cloud 侧更晚事件不被主链旧态覆盖、run_failed 不漏报。
    坏行跳过（单坏行不阻断），tie-break 用 (段序, 行序) 稳定次序。"""
    ledger_root = Path(repo_root) / "ledger"
    files = [ledger_root / f"{chain}.jsonl"]
    files += sorted(ledger_root.glob(f"cloud-day*/{chain}.jsonl"))
    evs: list[dict] = []
    seq = 0
    for f in files:
        if not f.exists():
            continue
        for ln in f.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            if isinstance(rec, dict):
                rec["__seq"] = seq
                evs.append(rec)
            seq += 1
    evs.sort(key=lambda e: (str(e.get("ts") or ""), e["__seq"]))
    for e in evs:
        e.pop("__seq", None)
    return evs


def connect(repo_root: Path) -> "duckdb.DuckDBPyConnection":
    """建内存库并注册视图。JSONL 行结构异构，必须 union_by_name（坑10）。"""
    con = duckdb.connect(":memory:")
    root = str(Path(repo_root).resolve())
    for chain in ("runs_index", "batches", "costs", "instances", "protocol"):
        # 主链 + 云链段（AMENDMENT-2：ledger/cloud-day<N>/ 各文件自成一链，合并只读装载）
        parts = [Path(root) / "ledger" / f"{chain}.jsonl"]
        parts += sorted(Path(root, "ledger").glob(f"cloud-day*/{chain}.jsonl"))
        files = [str(p) for p in parts if p.exists()]
        if files:
            file_list = ", ".join(f"'{f}'" for f in files)
            con.execute(f"""
                CREATE VIEW {chain} AS
                SELECT * FROM read_json([{file_list}],
                    format='newline_delimited', union_by_name=true,
                    maximum_object_size=16777216)""")
        else:  # 空账本也要有视图（查询面稳定）
            con.execute(f"CREATE VIEW {chain} AS SELECT NULL::VARCHAR AS ts, "
                        f"NULL::VARCHAR AS run_id, NULL::VARCHAR AS event, "
                        f"NULL::VARCHAR AS subject_id, "
                        f"NULL::VARCHAR AS entry_hash WHERE 1=0")
    scores_glob = f"{root}/data/runs/*/scores.jsonl"
    if any(Path(root, "data", "runs").glob("*/scores.jsonl")):
        con.execute(f"""
            CREATE VIEW all_scores AS
            SELECT * FROM read_json('{scores_glob}',
                format='newline_delimited', union_by_name=true)""")
    con.execute("""
        CREATE VIEW run_latest AS
        SELECT subject_id,
               arg_max(event, ts || entry_hash) AS last_event,
               max(ts) AS last_ts,
               count(*) AS n_events
        FROM runs_index
        WHERE subject_id IS NOT NULL
        GROUP BY subject_id""")
    con.execute("""
        CREATE VIEW batch_progress AS
        SELECT subject_id AS batch_id,
               arg_max(event, ts || entry_hash) AS last_event,
               max(ts) AS last_ts
        FROM batches
        WHERE subject_id IS NOT NULL
        GROUP BY subject_id""")
    # 陈旧阈值从 statemachine.ttl_seconds() 取（实施要点②：别写死 1800）
    stale = ttl_seconds()["RUNNING_HEARTBEAT"]
    # 偏差注：骨架用 strptime(last_ts,...) 假设 last_ts 是 VARCHAR，但 DuckDB read_json
    # 自动把 ISO ts 列识别为 TIMESTAMP → strptime 报 BinderError。改用 ::TIMESTAMPTZ
    # 显式转换（对 str / naive-ts / tz-aware 三种输入均稳健），语义等价。
    con.execute(f"""
        CREATE VIEW anomalies AS
        SELECT subject_id, last_event, last_ts,
               date_diff('second', last_ts::TIMESTAMPTZ, now()) AS age_s
        FROM run_latest
        WHERE last_event IN ('run_failed', 'run_paused', 'run_quarantined')
           OR (last_event IN ('run_queued', 'run_started', 'step_progress',
                              'run_completed', 'run_scored')
               AND date_diff('second', last_ts::TIMESTAMPTZ, now()) > {stale})""")
    return con


def authoritative_run_states(repo_root: Path) -> dict[str, tuple[str, str]]:
    """权威 per-run 末态与末事件（走 derive_run_state，按文件行序——实施要点②′：
    SQL arg_max 同秒 tie-break 无语义，精确状态恒用此。返回 {subject_id: (state, last_event)}。
    纳入 cloud-day 段并按事件全序（F-LEDGER-01）。"""
    by_subject: dict[str, list[dict]] = {}
    for ev in _merged_events(repo_root, "runs_index"):
        sid = ev.get("subject_id")
        if sid is not None:
            by_subject.setdefault(sid, []).append(ev)
    out: dict[str, tuple[str, str]] = {}
    for sid, evs in by_subject.items():
        state, _ = derive_run_state(evs)
        last_event = evs[-1].get("event", "") if evs else ""
        out[sid] = (state or "?", last_event)
    return out


def run_summary(repo_root: Path) -> list[tuple]:
    """run 汇总（subject_id、权威末事件、事件数、最新时间）。末事件用权威推导（文件行序），
    事件数/时间用 SQL 视图——两者结论冲突以权威推导为准（实施要点②′）。"""
    con = connect(repo_root)
    counts = {r[0]: (r[3], r[2]) for r in
              con.execute("SELECT * FROM run_latest").fetchall()}  # sid -> (n_events, last_ts)
    auth = authoritative_run_states(repo_root)
    rows = []
    for sid, (state, last_event) in auth.items():
        n, last_ts = counts.get(sid, (0, None))
        rows.append((sid, last_event, str(last_ts), n))
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows


def _last_events_by_subject(repo_root: Path, chain: str) -> dict[str, tuple[str, str]]:
    """按事件全序（ts）取每主体的 (末事件, 末ts)——权威读法（不依赖 SQL 同秒 tie-break）。
    纳入 cloud-day 段（F-LEDGER-01）：末事件 = ts 最大者，故 cloud 侧 run_failed 不漏报。"""
    out: dict[str, tuple[str, str]] = {}
    for ev in _merged_events(repo_root, chain):
        sid = ev.get("subject_id")
        if sid is not None:
            out[sid] = (ev.get("event", ""), ev.get("ts", ""))
    return out


def batch_progress(repo_root: Path) -> list[tuple]:
    """批次进度（batch_id、权威末事件、末ts）。用文件行序（实施要点②′）。"""
    last = _last_events_by_subject(repo_root, "batches")
    rows = [(bid, ev, ts) for bid, (ev, ts) in last.items()]
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows


# 陈旧型异常涉及的进行中状态；失败型异常无条件入列（fail-closed：宁误报不漏报）
_STALE_STATES = ("run_queued", "run_started", "step_progress", "run_completed", "run_scored")
_FAIL_STATES = ("run_failed", "run_paused", "run_quarantined")


def anomalies(repo_root: Path) -> list[tuple]:
    """异常清单（subject_id、末事件、末ts、age_s）。权威读法（文件行序）：失败型无条件入列，
    进行中型超 RUNNING_HEARTBEAT 阈值入列。避免 SQL tie-break 漏报 run_failed（fail-closed）。"""
    from datetime import datetime, timezone
    stale = ttl_seconds()["RUNNING_HEARTBEAT"]
    now = datetime.now(timezone.utc)
    rows: list[tuple] = []
    for sid, (ev, ts) in _last_events_by_subject(repo_root, "runs_index").items():
        try:
            age = (now - datetime.fromisoformat(ts)).total_seconds()
        except (ValueError, TypeError):
            age = 0.0
        if ev in _FAIL_STATES:
            rows.append((sid, ev, ts, int(age)))
        elif ev in _STALE_STATES and age > stale:
            rows.append((sid, ev, ts, int(age)))
    rows.sort(key=lambda r: r[3], reverse=True)
    return rows
