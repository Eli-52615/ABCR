"""tests/audit/test_version_check.py —— A2-2 审计项5 版本一致三查。"""
from __future__ import annotations

import json
from pathlib import Path

from abcr.audit import version_check as vc
from abcr.audit.treehash import code_tree_hash

BATCH_ID = "B-20260714T090000Z-0001"


def _mk_run(repo: Path, rid: str, manifest: dict, env_lock: str | None = None,
            step_ref: str | None = "env/lock.txt") -> None:
    rd = repo / "data" / "runs" / rid
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    if step_ref is not None:
        (rd / "steps.jsonl").write_text(
            json.dumps({"item_id": "g01", "env_lock_ref": step_ref}) + "\n", encoding="utf-8")
    if env_lock is not None:
        lock_p = repo / manifest["env_lock_ref"]
        lock_p.parent.mkdir(parents=True, exist_ok=True)
        lock_p.write_text(env_lock, encoding="utf-8")


def _base_manifest(repo: Path, **over) -> dict:
    m = {
        "run_id": "r", "code_tree_hash": code_tree_hash(repo),
        "git_clean": True, "non_citable": False,
        "env_lock_ref": "env/lock.txt",
    }
    m.update(over)
    return m


def test_all_pass(tmp_path: Path) -> None:
    m = _base_manifest(tmp_path)
    _mk_run(tmp_path, "r1", m, env_lock="python 3.12.13\nnumpy==1.0\n")
    item = vc.version_consistency_item(tmp_path, BATCH_ID, ["r1"])
    assert item.id == 5 and item.verdict == "PASS", item.evidence


def test_dirty_tree_citable_fails(tmp_path: Path) -> None:
    m = _base_manifest(tmp_path, git_clean=False, non_citable=False)
    _mk_run(tmp_path, "r1", m, env_lock="python 3.12\n")
    item = vc.version_consistency_item(tmp_path, BATCH_ID, ["r1"])
    assert item.verdict == "FAIL"
    assert any("脏树宣称可引用" in e for e in item.evidence)


def test_dirty_tree_noncitable_ok(tmp_path: Path) -> None:
    m = _base_manifest(tmp_path, git_clean=False, non_citable=True)
    _mk_run(tmp_path, "r1", m, env_lock="python 3.12\n")
    item = vc.version_consistency_item(tmp_path, BATCH_ID, ["r1"])
    assert item.verdict == "PASS", item.evidence


def test_code_drift_not_fail_by_default(tmp_path: Path) -> None:
    m = _base_manifest(tmp_path, code_tree_hash="0" * 64)
    _mk_run(tmp_path, "r1", m, env_lock="python 3.12\n")
    item = vc.version_consistency_item(tmp_path, BATCH_ID, ["r1"], strict=False)
    assert item.verdict == "PASS"
    assert any("code_drift=true" in e for e in item.evidence)


def test_code_drift_strict_fails(tmp_path: Path) -> None:
    m = _base_manifest(tmp_path, code_tree_hash="0" * 64)
    _mk_run(tmp_path, "r1", m, env_lock="python 3.12\n")
    item = vc.version_consistency_item(tmp_path, BATCH_ID, ["r1"], strict=True)
    assert item.verdict == "FAIL"
    assert any("strict" in e.lower() for e in item.evidence)


def test_env_lock_missing_citable_fails(tmp_path: Path) -> None:
    m = _base_manifest(tmp_path, non_citable=False)
    _mk_run(tmp_path, "r1", m, env_lock=None)  # 未落 lockfile
    item = vc.version_consistency_item(tmp_path, BATCH_ID, ["r1"])
    assert item.verdict == "FAIL"
    assert any("env_lock" in e and "citable" in e for e in item.evidence)


def test_env_lock_missing_noncitable_ok(tmp_path: Path) -> None:
    m = _base_manifest(tmp_path, non_citable=True)
    _mk_run(tmp_path, "r1", m, env_lock=None)
    item = vc.version_consistency_item(tmp_path, BATCH_ID, ["r1"])
    assert item.verdict == "PASS", item.evidence


def test_env_lock_no_python_line_citable_fails(tmp_path: Path) -> None:
    m = _base_manifest(tmp_path, non_citable=False)
    _mk_run(tmp_path, "r1", m, env_lock="numpy==1.0\npandas==2.0\n")
    item = vc.version_consistency_item(tmp_path, BATCH_ID, ["r1"])
    assert item.verdict == "FAIL"
    assert any("python 版本行" in e for e in item.evidence)


def test_env_lock_step_mismatch_fails(tmp_path: Path) -> None:
    m = _base_manifest(tmp_path)
    _mk_run(tmp_path, "r1", m, env_lock="python 3.12\n", step_ref="env/OTHER.txt")
    item = vc.version_consistency_item(tmp_path, BATCH_ID, ["r1"])
    assert item.verdict == "FAIL"
    assert any("不一致" in e for e in item.evidence)


def test_missing_manifest_fails(tmp_path: Path) -> None:
    (tmp_path / "data" / "runs" / "r1").mkdir(parents=True)
    item = vc.version_consistency_item(tmp_path, BATCH_ID, ["r1"])
    assert item.verdict == "FAIL"


def test_no_runs_skip(tmp_path: Path) -> None:
    item = vc.version_consistency_item(tmp_path, BATCH_ID, [])
    assert item.verdict == "SKIP"
