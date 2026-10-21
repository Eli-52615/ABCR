"""abcr.report.ledgerio —— 账本只读装载与状态折叠（包C 自建只读查询层）。

架构位置：包C·呈现侧的数据入口。只 open 读文件，永不写 ledger/。
状态映射与契约 §3.3 全表一致（本地只读副本，另含 AMENDMENT-13 两拒绝事件的
呈现标记映射；R1 合并后可自愿切 A 的 statemachine，标记映射保留本侧）。
装载一律走 read_chain_merged（主链 + ledger/cloud-day*/ 云链段——AMENDMENT-2）。
"""
from __future__ import annotations

import json
from pathlib import Path

RUN_EVENT_STATE: dict[str, str] = {
    "run_registered": "PLANNED", "run_queued": "QUEUED", "run_started": "RUNNING",
    "run_paused": "PAUSED", "run_resumed": "RUNNING", "run_failed": "FAILED",
    "run_completed": "COMPLETED", "run_scored": "SCORED", "run_audited": "AUDITED",
    "run_accepted": "ACCEPTED", "run_quarantined": "QUARANTINED",
    "run_cancelled": "CANCELLED",
}
BATCH_EVENT_STATE: dict[str, str] = {
    "batch_drafted": "DRAFT", "batch_approved": "APPROVED",
    "batch_dispatch_started": "DISPATCHING", "batch_settled": "SETTLED",
    "batch_audited": "AUDITED", "batch_reported": "REPORTED",
    # AMENDMENT-13 两拒绝事件：批次冻结状态机主线无拒绝态，以下为呈现折叠专用标记态
    # （你只读折叠、不做迁移校验；迁移守卫语义以 A 的 statemachine 为准）。
    "batch_rejected": "REJECTED", "batch_dispatch_rejected": "DISPATCH_REJECTED",
}
INSTANCE_EVENT_STATE: dict[str, str] = {
    "instance_registered": "REGISTERED", "instance_started": "RUNNING",
    "instance_stopped": "STOPPED",
    # instance_idle_alert 是标记事件、非状态迁移（云实例空转=A级显示项，triage A桶）；
    # 折叠时不改 state，只在 events 里留痕供 sync/triage 检出。
}


def read_chain(path: Path) -> list[dict]:
    """读一条账本链的全部记录（文件序即链序）。缺文件返回 []。"""
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def read_chain_merged(ledger_dir: Path, chain: str) -> list[dict]:
    """主链 + 云链段合并只读视图（AMENDMENT-2）：先 ledger/<chain>.jsonl，再按目录名序
    依次装载 ledger/cloud-day*/<chain>.jsonl。各段自成一链——只合并记录、不拼哈希、
    不跨段校验。triage/sync/views/planner 的一切账本装载一律走本函数。"""
    events = read_chain(Path(ledger_dir) / f"{chain}.jsonl")
    for seg in sorted(Path(ledger_dir).glob("cloud-day*")):
        if seg.is_dir():
            events += read_chain(seg / f"{chain}.jsonl")
    return events


def fold_subjects(events: list[dict], state_map: dict[str, str]) -> dict[str, dict]:
    """按 payload.subject_id 折叠出每主体现状。
    返回 {subject_id: {"state","last_ts","last_progress_ts","events"}}。"""
    out: dict[str, dict] = {}
    for ev in events:
        sid = ev.get("subject_id")
        if sid is None:
            continue
        rec = out.setdefault(sid, {"state": None, "last_ts": None,
                                   "last_progress_ts": None, "events": []})
        rec["events"].append(ev)
        rec["last_ts"] = ev.get("ts")
        name = ev.get("event", "")
        if name == "step_progress":
            rec["last_progress_ts"] = ev.get("ts")
            continue
        st = state_map.get(name)
        if st is not None:
            rec["state"] = st
    return out
