"""StepWriter 外部锚接线测试（步骤链 × external_seal）。

覆盖：finalize 收口即 seal；verify_external_seal 只认规范锚；
攻击：尾截断（内部链仍自洽）、整链从 genesis 重算、影子锚文件、缺锚 fail-closed。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from abcr.common.external_seal import ANCHOR_STORE_ENV
from abcr.logging.schema import SCHEMA_VERSION
from abcr.logging.writer import StepWriter


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "anchors" / "seals.jsonl"
    monkeypatch.setenv(ANCHOR_STORE_ENV, str(p))
    return p


def _make_step(item_id: str, seed: int, condition: str = "vanilla",
               step_id: int = 0) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": "test-run",
        "trajectory_id": f"test-run:{item_id}:{seed}",
        "step_id": step_id,
        "parent_run": None,
        "git_commit": "abc123",
        "config_hash": "cfg_hash_000",
        "protocol_ref": "test",
        "env_lock_ref": "env.lock",
        "model_id": "tinyqwen",
        "model_revision": "local-fixture-seed0",
        "dtype": "float32",
        "quantization": None,
        "device": "cpu",
        "device_backend": "cpu",
        "engine": "transformers",
        "engine_version": "4.52.3",
        "torch_version": "2.6.0",
        "cuda_version": None,
        "chat_template_hash": "deadbeef",
        "benchmark": "fixture",
        "split_hash": "split_hash_000",
        "item_id": item_id,
        "condition": condition,
        "trait": None,
        "trait_pole": None,
        "method": "none",
        "layer": None,
        "coefficient": None,
        "intervention_strength": None,
        "env_seed": None,
        "action": None,
        "obs_hash": None,
        "remaining_budget": None,
        "stop_reason": "eos",
        "state_snapshot_ref": None,
        "random_seed": seed,
        "prompt_hash": "prompt_hash_000",
        "output_text": f"output for {item_id} seed {seed}",
        "parsed_answer": None,
        "is_correct": None,
        "latency_ms": 100.0,
        "input_tokens": 10,
        "output_tokens": 20,
        "trait_score": None,
        "fluency_score": None,
        "safety_flags": [],
        "activation_summary": None,
        "citable": False,
        "prev_hash": "",
        "entry_hash": "",
    }


def _run_with_steps(root: Path, name: str, n: int, seed: int = 42) -> Path:
    """seed 参数让"洗过的链"内容确实不同（同 seed 会生成逐字节相同的链）。"""
    run_dir = root / name
    run_dir.mkdir(parents=True)
    w = StepWriter(run_dir)
    for i in range(n):
        w.append(_make_step(f"item_{i:03d}", seed))
    return run_dir


def test_finalize_seals_and_verify_ok(store: Path, tmp_path: Path) -> None:
    run_dir = _run_with_steps(tmp_path, "run-ok", 5)
    rec = StepWriter(run_dir).finalize()
    assert rec["kind"] == "step_chain"
    assert rec["subject_id"] == "run-ok"       # 默认 subject = run_dir 目录名
    assert rec["length"] == 5
    assert store.exists()
    ok, reason = StepWriter.verify_external_seal(run_dir)
    assert ok is True and reason == "ok"
    # 直接传 steps.jsonl 路径同样可验
    ok, _ = StepWriter.verify_external_seal(run_dir / "steps.jsonl")
    assert ok is True


def test_close_is_finalize_alias(store: Path, tmp_path: Path) -> None:
    run_dir = _run_with_steps(tmp_path, "run-close", 2)
    rec = StepWriter(run_dir).close()
    assert rec["kind"] == "step_chain" and rec["length"] == 2
    assert StepWriter.verify_external_seal(run_dir)[0] is True


def test_no_seal_fail_closed(store: Path, tmp_path: Path) -> None:
    """未 finalize（缺锚）→ False('no external seal')，绝不判过。"""
    run_dir = _run_with_steps(tmp_path, "run-noseal", 3)
    assert StepWriter.verify_chain(run_dir / "steps.jsonl") is True  # 内部自洽
    ok, reason = StepWriter.verify_external_seal(run_dir)
    assert ok is False and "no external seal" in reason


def test_attack_tail_truncation_detected(store: Path, tmp_path: Path) -> None:
    """尾截断：内部 verify_chain 仍 True（前缀合法链），外部锚 length 失配 → False。"""
    run_dir = _run_with_steps(tmp_path, "run-trunc", 5)
    StepWriter(run_dir).finalize()

    steps = run_dir / "steps.jsonl"
    lines = steps.read_text().splitlines()
    steps.write_text("\n".join(lines[:-1]) + "\n")   # 截掉最后一条

    assert StepWriter.verify_chain(steps) is True    # 旧弱语义：内部照样绿
    ok, reason = StepWriter.verify_external_seal(run_dir)
    assert ok is False
    assert "length mismatch" in reason


def test_attack_full_rechain_from_genesis_detected(
        store: Path, tmp_path: Path) -> None:
    """整链从 genesis 重算洗链（自洽、可含不同条目数）→ 外部锚失配 → False。"""
    victim = _run_with_steps(tmp_path, "run-victim", 5)
    StepWriter(victim).finalize()

    forged = _run_with_steps(tmp_path, "run-forge", 3, seed=99)  # 攻击者全新自洽链
    shutil.copyfile(forged / "steps.jsonl", victim / "steps.jsonl")

    assert StepWriter.verify_chain(victim / "steps.jsonl") is True  # 内部照样绿
    ok, reason = StepWriter.verify_external_seal(victim)
    assert ok is False
    assert "length mismatch" in reason

    # 变体：同条目数、内容洗过 → digest 失配
    forged2 = _run_with_steps(tmp_path, "run-forge2", 5, seed=99)
    shutil.copyfile(forged2 / "steps.jsonl", victim / "steps.jsonl")
    ok, reason = StepWriter.verify_external_seal(victim)
    assert ok is False and "digest mismatch" in reason


def test_attack_shadow_anchor_in_run_dir_ignored(
        store: Path, tmp_path: Path) -> None:
    """run_dir 内放自洽影子 seals.jsonl → verify 只读规范锚，零影响。"""
    run_dir = _run_with_steps(tmp_path, "run-shadow", 4)
    StepWriter(run_dir).finalize()
    # 洗链（不同 seed → 内容确实不同）
    forged = _run_with_steps(tmp_path, "run-shadow-forge", 4, seed=99)
    shutil.copyfile(forged / "steps.jsonl", run_dir / "steps.jsonl")
    # 攻击者为洗过的链伪造"配套锚"，放在 run_dir 内与 anchors 子目录
    from abcr.common.external_seal import chain_digest_and_length
    import json as _json
    d_f, n_f = chain_digest_and_length(StepWriter._load_entries(run_dir / "steps.jsonl"))
    shadow = _json.dumps({"ts": "2026-07-19T00:00:00+00:00", "kind": "step_chain",
                          "subject_id": "run-shadow", "digest": d_f,
                          "length": n_f, "extra": {}}) + "\n"
    (run_dir / "seals.jsonl").write_text(shadow)
    (run_dir / "anchors").mkdir()
    (run_dir / "anchors" / "seals.jsonl").write_text(shadow)

    ok, reason = StepWriter.verify_external_seal(run_dir)
    assert ok is False and "digest mismatch" in reason


def test_missing_steps_file_fail_closed(store: Path, tmp_path: Path) -> None:
    run_dir = tmp_path / "run-empty"
    run_dir.mkdir()
    ok, reason = StepWriter.verify_external_seal(run_dir)
    assert ok is False and "missing" in reason


def test_existing_chain_semantics_unchanged(store: Path, tmp_path: Path) -> None:
    """回归面：append/verify_chain/load_done 行为不因外部锚接线改变。"""
    run_dir = _run_with_steps(tmp_path, "run-reg", 5)
    w = StepWriter(run_dir)
    assert len(w.load_done()) == 5
    assert StepWriter.verify_chain(run_dir / "steps.jsonl") is True
    digest, length = w.head_and_length()
    assert length == 5 and len(digest) == 64
