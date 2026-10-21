"""tests/ledger/test_views.py —— A1-4 DuckDB 只读视图（R1-full）。"""
from __future__ import annotations

from pathlib import Path

from abcr.common.ledger_ref import RunLedger
from abcr.ledger import views


def _seed_ledger(tmp_path: Path) -> None:
    ldir = tmp_path / "ledger"
    ri = RunLedger(ldir, "runs_index")
    for rid, events in {
        "run-a": ["run_registered", "run_queued", "run_started",
                  "run_completed", "run_scored", "run_audited", "run_accepted"],
        "run-b": ["run_registered", "run_queued", "run_failed"],
    }.items():
        for e in events:
            if e == "run_registered":
                ri.append(e, subject_id=rid, batch_id="B-20260714T090000Z-0001")
            else:
                ri.append(e, subject_id=rid)
    bt = RunLedger(ldir, "batches")
    bt.append("batch_drafted", subject_id="B-20260714T090000Z-0001")
    bt.append("batch_audited", subject_id="B-20260714T090000Z-0001")


def test_run_summary_view(tmp_path: Path) -> None:
    _seed_ledger(tmp_path)
    rows = views.run_summary(tmp_path)
    by_id = {r[0]: r for r in rows}
    assert by_id["run-a"][1] == "run_accepted"
    assert by_id["run-b"][1] == "run_failed"


def test_batch_progress_view(tmp_path: Path) -> None:
    _seed_ledger(tmp_path)
    rows = views.batch_progress(tmp_path)
    assert rows and rows[0][1] == "batch_audited"


def test_anomalies_flags_failed(tmp_path: Path) -> None:
    _seed_ledger(tmp_path)
    rows = views.anomalies(tmp_path)
    subjects = {r[0] for r in rows}
    assert "run-b" in subjects        # run_failed → 异常
    assert "run-a" not in subjects    # run_accepted 终态 → 非异常


def test_empty_ledger_stable_views(tmp_path: Path) -> None:
    """空账本也要有视图（不报错）。"""
    (tmp_path / "ledger").mkdir()
    assert views.run_summary(tmp_path) == []
    assert views.anomalies(tmp_path) == []


def test_views_module_is_select_only() -> None:
    """坑11：views.py 传给 execute 的 SQL 字面量不得含写语句（只查 SQL，不查 docstring/注释）。"""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(views))

    def sql_text(arg) -> str:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        if isinstance(arg, ast.JoinedStr):  # f-string：取静态字面部分
            return "".join(v.value for v in arg.values
                           if isinstance(v, ast.Constant) and isinstance(v.value, str))
        return ""

    sqls: list[str] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute" and node.args):
            t = sql_text(node.args[0]).upper()
            if t.strip():
                sqls.append(t)
    assert len(sqls) >= 4, f"应捕获多条 execute SQL，实得 {len(sqls)}"
    for sql in sqls:
        for kw in ("INSERT ", "UPDATE ", "DELETE ", "COPY "):
            assert kw not in sql, f"SQL 含写语句: {kw} in {sql[:60]}"
        assert sql.lstrip().startswith(("CREATE VIEW", "SELECT")), sql[:60]
