"""tests/rig/test_flip_demo —— 翻转 demo 生成器结构校验（B2-11；手造小 CSV）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/b_flip_demo.py"


def _mk_csv(path: Path, scores: list[int], answers: list[str]):
    df = pd.DataFrame([{"question": f"题{q}", "prompt": "p", "answer": answers[q],
                        "question_id": f"q{q}", "optimistic": scores[q], "coherence": 80}
                       for q in range(len(scores))])
    df.to_csv(path, index=False)


def test_flip_demo_structure(tmp_path: Path):
    _mk_csv(tmp_path / "base.csv", [50, 50, 50], ["中0", "中1", "中2"])
    _mk_csv(tmp_path / "pos.csv", [85, 60, 88], ["乐0", "乐1", "乐2"])
    _mk_csv(tmp_path / "neg.csv", [15, 40, 12], ["悲0", "悲1", "悲2"])
    out = tmp_path / "demo.md"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--trait", "optimistic",
         "--baseline", str(tmp_path / "base.csv"), "--pos", str(tmp_path / "pos.csv"),
         "--neg", str(tmp_path / "neg.csv"), "--topk", "2", "--out", str(out)],
        capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    assert "exploratory / rig-validation" in text
    # gap 排序：q2(76) 先于 q0(70)；q1(20) 不入 top2
    assert text.index("## q2") < text.index("## q0")
    assert "## q1" not in text
    assert "正向注入" in text and "负向注入" in text
