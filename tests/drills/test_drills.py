"""tests/drills/test_drills.py —— A2-6 四演练脚本端到端 + harness 断言库。

演练在隔离 root（state/audit/drills/，gitignored）上跑，真链零写入（各脚本自带 ⑤ 断言）。
演练1/2/3 经 importlib 调 run_drill(REPO)；演练4 经 subprocess 跑 .sh（sandbox 不可用时 SKIP）。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from abcr.sandboxing.drills import harness as H
from abcr.sandboxing.profiles import available

REPO = Path(__file__).resolve().parents[2]


def _load(script: str):
    path = REPO / "scripts" / script
    spec = importlib.util.spec_from_file_location(f"_{script}", path)
    mod = importlib.util.module_from_spec(spec)
    if str(REPO / "src") not in sys.path:
        sys.path.insert(0, str(REPO / "src"))
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _real_ledger_before():
    return H.real_ledger_digest(REPO)


def test_drill_1_kill_pass() -> None:
    before = _real_ledger_before()
    rc = _load("a_drill_1_kill.py").run_drill(REPO)
    assert rc == 0
    assert H.real_ledger_digest(REPO) == before  # 真链零写入


def test_drill_2_fake_completion_pass() -> None:
    before = _real_ledger_before()
    rc = _load("a_drill_2_fake_completion.py").run_drill(REPO)
    assert rc == 0
    assert H.real_ledger_digest(REPO) == before


def test_drill_3_idle_instance_pass() -> None:
    before = _real_ledger_before()
    rc = _load("a_drill_3_idle_instance.py").run_drill(REPO)
    assert rc == 0
    assert H.real_ledger_digest(REPO) == before


@pytest.mark.skipif(not available(), reason="sandbox-exec 不可用")
def test_drill_4_frozen_write_pass() -> None:
    before = _real_ledger_before()
    r = subprocess.run(
        ["bash", str(REPO / "scripts" / "a_drill_4_frozen_write.sh")],
        capture_output=True, text=True,
        env={**_env(), "ABCR_PYTHON": sys.executable, "ABCR_REPO_ROOT": str(REPO)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DRILL 4 VERDICT: PASS" in r.stdout
    assert H.real_ledger_digest(REPO) == before


def _env() -> dict:
    import os
    e = dict(os.environ)
    e["PYTHONPATH"] = str(REPO / "src") + (":" + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    return e


# ---------- harness 断言库单测 ----------

def test_no_duplicate_steps_detects_dup(tmp_path: Path) -> None:
    rd = tmp_path / "run"
    rd.mkdir()
    import json
    line = json.dumps({"item_id": "g01", "random_seed": 1, "step_id": 0})
    (rd / "steps.jsonl").write_text(line + "\n" + line + "\n", encoding="utf-8")
    ok, ev = H.no_duplicate_steps(rd)
    assert not ok and any("重复" in e for e in ev)


def test_no_duplicate_steps_empty_is_fail(tmp_path: Path) -> None:
    """根因②：缺文件/空文件不得静默通过（清空 steps 绕过无重复检查）。"""
    rd = tmp_path / "run"
    rd.mkdir()
    ok, ev = H.no_duplicate_steps(rd)                      # 无 steps.jsonl
    assert not ok and any("实质 step" in e for e in ev)
    (rd / "steps.jsonl").write_text("", encoding="utf-8")  # 空文件
    ok2, ev2 = H.no_duplicate_steps(rd)
    assert not ok2 and any("evidence_floor" in e for e in ev2)


def test_verify_all_chains_all_missing_is_fail(tmp_path: Path) -> None:
    """根因②：全部链缺失/全空的空账本不得冒充五链完整。"""
    (tmp_path / "ledger").mkdir(parents=True)              # 无任何链文件
    ok, ev = H.verify_all_chains(tmp_path)
    assert not ok and any("evidence_floor" in e for e in ev)
    # touch 空链文件同样不算实质验证
    (tmp_path / "ledger" / "runs_index.jsonl").write_text("", encoding="utf-8")
    ok2, ev2 = H.verify_all_chains(tmp_path)
    assert not ok2 and any("无一条实质链可验" in e for e in ev2)


def test_verify_all_chains_clean(tmp_path: Path) -> None:
    from abcr.common.ledger_ref import RunLedger
    RunLedger(tmp_path / "ledger", "runs_index").append("run_registered", subject_id="r", batch_id="b")
    ok, ev = H.verify_all_chains(tmp_path)
    assert ok


def test_verify_all_chains_detects_tamper(tmp_path: Path) -> None:
    from abcr.common.ledger_ref import RunLedger
    ri = RunLedger(tmp_path / "ledger", "runs_index")
    ri.append("run_registered", subject_id="r", batch_id="b")
    ri.append("run_queued", subject_id="r")
    p = tmp_path / "ledger" / "runs_index.jsonl"
    lines = p.read_text().splitlines()
    lines[0] = lines[0].replace('"run_registered"', '"run_started"')  # 篡改首条
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, ev = H.verify_all_chains(tmp_path)
    assert not ok and any("断链" in e for e in ev)


def test_new_iso_root_under_drills(tmp_path: Path) -> None:
    iso = H.new_iso_root(tmp_path, "dX")
    assert iso.parent == tmp_path / "state" / "audit" / "drills"
    assert (iso / "ledger").is_dir()
