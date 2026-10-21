"""§7.2 影子模式毕业检查器测试：对测试造的 shadow 记录 + 假审计报告，
GRADUATED / NOT_GRADUATED 两种结论各正确打印。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from abcr.common.ledger_ref import RunLedger
from abcr.governor import shadow

_MOD_PATH = Path(__file__).resolve().parents[2] / "scripts" / "c_shadow_graduation.py"
_spec = importlib.util.spec_from_file_location("c_shadow_graduation", _MOD_PATH)
grad = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grad)


@pytest.fixture(autouse=True)
def _iso_anchor(monkeypatch, tmp_path):
    """毕业检查器现要求 shadow 记录已 seal 进外部规范锚存储——隔离到 tmp 防污染真仓。"""
    monkeypatch.setenv("ABCR_ANCHOR_STORE", str(tmp_path / "anchors" / "seals.jsonl"))


def _shadow(repo: Path, bid: str, key_diff: bool, seal: bool = True):
    d = repo / "plans" / "shadow"
    d.mkdir(parents=True, exist_ok=True)
    rec = {"shadow_version": "1.0", "batch_id": bid, "key_difference": key_diff}
    (d / f"{bid}.shadow.json").write_text(json.dumps(rec), encoding="utf-8")
    if seal:   # 合法记录须有外部锚才计入毕业
        shadow.seal_record(rec)


def _audit(repo: Path, bid: str, overall: str):
    d = repo / "reports" / "audit"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{bid}.json").write_text(json.dumps({"batch_id": bid, "overall": overall}),
                                   encoding="utf-8")


def _register_runs(repo: Path, bid: str, n: int):
    led = RunLedger(repo / "ledger", "runs_index")
    for i in range(n):
        led.append("run_registered", subject_id=f"{bid}-run{i}", batch_id=bid)


def test_graduated(tmp_path):
    """两批零关键差异、审计 PASS、合计 ≥20 run → GRADUATED。"""
    _shadow(tmp_path, "B-20260716T020000Z-0001", key_diff=False)
    _shadow(tmp_path, "B-20260717T020000Z-0001", key_diff=False)
    _audit(tmp_path, "B-20260716T020000Z-0001", "PASS")
    _audit(tmp_path, "B-20260717T020000Z-0001", "PASS")
    _register_runs(tmp_path, "B-20260716T020000Z-0001", 12)
    _register_runs(tmp_path, "B-20260717T020000Z-0001", 10)
    st = grad.graduation_status(tmp_path)
    assert st["graduated"] is True
    assert st["total_runs"] == 22 and st["all_green"] is True
    assert "GRADUATED" in grad.render(st) and "NOT_GRADUATED" not in grad.render(st)


def test_not_graduated_insufficient_runs(tmp_path):
    """零关键差异但 run 不足 20 → NOT_GRADUATED。"""
    _shadow(tmp_path, "B-20260716T020000Z-0001", key_diff=False)
    _audit(tmp_path, "B-20260716T020000Z-0001", "PASS")
    _register_runs(tmp_path, "B-20260716T020000Z-0001", 5)
    st = grad.graduation_status(tmp_path)
    assert st["graduated"] is False and st["total_runs"] == 5
    assert grad.render(st).startswith("NOT_GRADUATED")


def test_not_graduated_audit_fail(tmp_path):
    """够 20 run 但某零关键差异批次审计非 PASS → 未全绿 → NOT_GRADUATED。"""
    _shadow(tmp_path, "B-20260716T020000Z-0001", key_diff=False)
    _audit(tmp_path, "B-20260716T020000Z-0001", "FAIL")
    _register_runs(tmp_path, "B-20260716T020000Z-0001", 25)
    st = grad.graduation_status(tmp_path)
    assert st["graduated"] is False and st["all_green"] is False


def test_key_difference_batch_excluded(tmp_path):
    """关键差异批次不计入毕业（即便审计 PASS、run 充足）。"""
    _shadow(tmp_path, "B-20260716T020000Z-0001", key_diff=True)
    _audit(tmp_path, "B-20260716T020000Z-0001", "PASS")
    _register_runs(tmp_path, "B-20260716T020000Z-0001", 30)
    st = grad.graduation_status(tmp_path)
    assert st["graduated"] is False and st["total_runs"] == 0
    assert st["batches"][0]["counts_toward_graduation"] is False


def test_forged_unsealed_shadow_excluded(tmp_path):
    """伪造记录（无外部锚）即便零关键差异+审计 PASS+run 充足，也不计入毕业（根因①闭合）。"""
    bid = "B-20260716T020000Z-0001"
    _shadow(tmp_path, bid, key_diff=False, seal=False)   # 手写、未 seal
    _audit(tmp_path, bid, "PASS")
    _register_runs(tmp_path, bid, 30)
    st = grad.graduation_status(tmp_path)
    assert st["graduated"] is False and st["total_runs"] == 0
    b = st["batches"][0]
    assert b["seal_ok"] is False and b["counts_toward_graduation"] is False


def test_tampered_sealed_shadow_excluded(tmp_path):
    """已 seal 但记录被篡改（key_difference 翻假）→ 摘要失配 → 不计入（防改锚后内容）。"""
    bid = "B-20260716T020000Z-0001"
    d = tmp_path / "plans" / "shadow"
    d.mkdir(parents=True, exist_ok=True)
    # 对 key_difference=True 的记录 seal，再把文件改成 False
    rec_true = {"shadow_version": "1.0", "batch_id": bid, "key_difference": True}
    shadow.seal_record(rec_true)
    (d / f"{bid}.shadow.json").write_text(json.dumps(
        {"shadow_version": "1.0", "batch_id": bid, "key_difference": False}), encoding="utf-8")
    _audit(tmp_path, bid, "PASS")
    _register_runs(tmp_path, bid, 30)
    st = grad.graduation_status(tmp_path)
    assert st["batches"][0]["seal_ok"] is False
    assert st["graduated"] is False


def test_unstarted_run_count_via_envelope(tmp_path):
    """未启动 run：无 run_registered 时以信封 run_configs 对账。"""
    bid = "B-20260716T020000Z-0001"
    _shadow(tmp_path, bid, key_diff=False)
    _audit(tmp_path, bid, "PASS")
    envd = tmp_path / "configs" / "envelopes"
    envd.mkdir(parents=True)
    (envd / f"{bid}.json").write_text(json.dumps(
        {"batch_id": bid, "run_configs": [{"i": i} for i in range(21)]}), encoding="utf-8")
    st = grad.graduation_status(tmp_path)
    assert st["total_runs"] == 21 and st["graduated"] is True
