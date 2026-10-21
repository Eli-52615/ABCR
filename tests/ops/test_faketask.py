"""tests/ops/test_faketask —— 确定性假任务执行器四旋钮 + 确定性（契约 §2.12）。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from abcr.ops import faketask

REPO = Path(__file__).resolve().parents[2]
ITEMS = [f"g{i:02d}" for i in range(1, 11)]


def _subenv() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src")
    return env


def test_determinism_pass_and_fail():
    assert faketask.generate("g02") == "391"
    # g03 是 fail_sample（带空格），不等于严格 pass 串
    assert faketask.generate("g03") != "hello,hello,hello,hello,hello"
    # 重复调用确定
    assert faketask.generate("g05") == faketask.generate("g05")


def test_normal_run_emits_all(monkeypatch):
    monkeypatch.chdir(REPO)
    emitted: list[str] = []
    done: list[str] = []
    faketask.run_items(ITEMS, lambda i, o: emitted.append(i), lambda i: done.append(i))
    assert emitted == ITEMS
    assert done == ITEMS


def test_skip_ledger_writes(monkeypatch):
    """SKIP_LEDGER_WRITES=1：不 emit step，但仍 mark_done（伪报完成演练）。"""
    monkeypatch.chdir(REPO)
    monkeypatch.setenv("ABCR_FAKETASK_SKIP_LEDGER_WRITES", "1")
    emitted: list[str] = []
    done: list[str] = []
    faketask.run_items(ITEMS, lambda i, o: emitted.append(i), lambda i: done.append(i))
    assert emitted == []
    assert done == ITEMS


_DRIVER = """
import sys
from pathlib import Path
from abcr.ops import faketask
out = Path(sys.argv[1])
def emit(i, o): out.open("a").write(i + "\\n")
def done(i): pass
faketask.run_items([f"g{n:02d}" for n in range(1, 11)], emit, done)
"""


def test_crash_at_item(tmp_path):
    """CRASH_AT_ITEM=g05：进程即死 exit 1，只 emit g01-g04。"""
    log = tmp_path / "emitted.txt"
    env = _subenv()
    env["ABCR_FAKETASK_CRASH_AT_ITEM"] = "g05"
    r = subprocess.run([sys.executable, "-c", _DRIVER, str(log)],
                       cwd=REPO, env=env, capture_output=True, text=True)
    assert r.returncode == 1, r.stderr
    got = log.read_text().split() if log.exists() else []
    assert got == ["g01", "g02", "g03", "g04"], got


def test_exit_without_done(tmp_path):
    """EXIT_WITHOUT_DONE=1：写首个 step 后 exit 0（幽灵状态演练）。"""
    log = tmp_path / "emitted.txt"
    env = _subenv()
    env["ABCR_FAKETASK_EXIT_WITHOUT_DONE"] = "1"
    r = subprocess.run([sys.executable, "-c", _DRIVER, str(log)],
                       cwd=REPO, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = log.read_text().split() if log.exists() else []
    assert got == ["g01"], got


def test_hang_at_item(tmp_path):
    """HANG_AT_ITEM=g03：永久挂起 → 子进程超时（停摆演练）。"""
    log = tmp_path / "emitted.txt"
    env = _subenv()
    env["ABCR_FAKETASK_HANG_AT_ITEM"] = "g03"
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run([sys.executable, "-c", _DRIVER, str(log)],
                       cwd=REPO, env=env, capture_output=True, text=True, timeout=2)
