"""tests/audit/conftest.py —— auditor 测试共享夹具：临时 repo_root + 模拟 fixture 批次。"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BATCH_ID = "B-20260714T090000Z-0001"


def _load_simulator():
    """从 scripts/a_sim_b_fixture.py 载入批次模拟器（避免污染 sys.path 长期状态）。"""
    path = REPO / "scripts" / "a_sim_b_fixture.py"
    spec = importlib.util.spec_from_file_location("_a_sim_b_fixture", path)
    mod = importlib.util.module_from_spec(spec)
    if str(REPO / "src") not in sys.path:
        sys.path.insert(0, str(REPO / "src"))
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """临时 repo_root：拷入 golden10 + fixtures，构建模拟 fixture 批次。"""
    (tmp_path / "data" / "golden").mkdir(parents=True)
    shutil.copy(REPO / "data" / "golden" / "golden10.json",
                tmp_path / "data" / "golden" / "golden10.json")
    (tmp_path / "fixtures").mkdir()
    for f in ("envelope_fixture.json", "expected_scores.jsonl"):
        shutil.copy(REPO / "fixtures" / f, tmp_path / "fixtures" / f)
    sim = _load_simulator()
    sim.build_batch(tmp_path)
    return tmp_path
