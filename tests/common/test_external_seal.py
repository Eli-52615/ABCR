"""外部信任根 external_seal 单元 + 攻击测试（根因①：无外部锚）。

攻击测试覆盖（任务书要求的三条 + 补充）：
(a) 尾部截断 → length 不符 → False
(b) 整链从 genesis 重算但条目数变了 → length 不符 → False
(b') 整链重算、条目数不变但内容变 → digest 不符 → False
(c) 相邻/内部影子锚文件 → 被忽略 → 仍按真锚判定
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from abcr.common import external_seal
from abcr.common.external_seal import (
    ANCHOR_STORE_ENV, KIND_LEDGER_CHAIN, KIND_STEP_CHAIN,
    anchor_store_path, chain_digest_and_length, latest_seal, seal, verify)


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离规范锚存储到 tmp_path（ABCR_ANCHOR_STORE 调用时读）。"""
    p = tmp_path / "anchors" / "seals.jsonl"
    monkeypatch.setenv(ANCHOR_STORE_ENV, str(p))
    return p


def _entries(n: int, salt: str = "x") -> list[dict]:
    return [{"event": "e", "subject_id": f"{salt}{i}", "i": i} for i in range(n)]


# ---------- 基本语义 ----------

def test_env_override_is_canonical_path(store: Path) -> None:
    assert anchor_store_path() == store


def test_seal_then_verify_ok(store: Path) -> None:
    ents = _entries(5)
    digest, length = chain_digest_and_length(ents)
    rec = seal(KIND_LEDGER_CHAIN, "costs", digest, length, extra={"note": "t"})
    assert rec["digest"] == digest and rec["length"] == 5
    assert store.exists()
    ok, reason = verify(KIND_LEDGER_CHAIN, "costs", digest, length)
    assert ok is True and reason == "ok"


def test_missing_store_fail_closed(store: Path) -> None:
    """锚存储不存在 → (False, 'no external seal ...')，缺锚绝不判过。"""
    ok, reason = verify(KIND_STEP_CHAIN, "run-001", "d" * 64, 3)
    assert ok is False
    assert "no external seal" in reason


def test_missing_subject_fail_closed(store: Path) -> None:
    """存储存在但无该 (kind, subject_id) 记录 → False。"""
    d, n = chain_digest_and_length(_entries(2))
    seal(KIND_LEDGER_CHAIN, "batches", d, n)
    ok, reason = verify(KIND_LEDGER_CHAIN, "costs", d, n)
    assert ok is False and "no external seal" in reason
    # kind 不匹配同样缺锚
    ok, reason = verify(KIND_STEP_CHAIN, "batches", d, n)
    assert ok is False and "no external seal" in reason


def test_reseal_latest_wins(store: Path) -> None:
    """append-only 重封：同 (kind, subject_id) 取最后一条。"""
    d1, n1 = chain_digest_and_length(_entries(2))
    d2, n2 = chain_digest_and_length(_entries(4))
    seal(KIND_LEDGER_CHAIN, "costs", d1, n1)
    seal(KIND_LEDGER_CHAIN, "costs", d2, n2)
    assert latest_seal(KIND_LEDGER_CHAIN, "costs")["length"] == 4
    ok, _ = verify(KIND_LEDGER_CHAIN, "costs", d2, n2)
    assert ok is True
    ok, _ = verify(KIND_LEDGER_CHAIN, "costs", d1, n1)
    assert ok is False  # 旧值已被重封覆盖


def test_chain_digest_and_length_properties() -> None:
    ents = _entries(3)
    d1, n1 = chain_digest_and_length(ents)
    d2, n2 = chain_digest_and_length([dict(e) for e in ents])  # 拷贝等值
    assert (d1, n1) == (d2, n2) and n1 == 3
    # 键序无关（canonical sort_keys）
    reordered = [{k: e[k] for k in sorted(e, reverse=True)} for e in ents]
    assert chain_digest_and_length(reordered)[0] == d1
    # 空序列：明确可区分的值，长度 0
    d0, n0 = chain_digest_and_length([])
    assert n0 == 0 and d0 != d1


def test_seal_input_validation(store: Path) -> None:
    with pytest.raises(ValueError):
        seal("", "s", "d", 1)
    with pytest.raises(ValueError):
        seal("k", "", "d", 1)
    with pytest.raises(ValueError):
        seal("k", "s", "d", -1)


def test_corrupt_store_line_does_not_grant_pass(store: Path) -> None:
    """锚文件里的坏行按不存在处理——不会变成可通过的锚。"""
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("{not json\n", encoding="utf-8")
    ok, reason = verify(KIND_LEDGER_CHAIN, "costs", "d" * 64, 1)
    assert ok is False and "no external seal" in reason


# ---------- 攻击测试 ----------

def test_attack_a_tail_truncation_length_mismatch(store: Path) -> None:
    """(a) 尾部截断：前缀链内自洽，但 length 不符 → False。"""
    full = _entries(5)
    d_full, n_full = chain_digest_and_length(full)
    seal(KIND_LEDGER_CHAIN, "costs", d_full, n_full)

    truncated = full[:-1]                      # 攻击者截掉最后一条
    d_t, n_t = chain_digest_and_length(truncated)
    ok, reason = verify(KIND_LEDGER_CHAIN, "costs", d_t, n_t)
    assert ok is False
    assert "length mismatch" in reason


def test_attack_b_full_rechain_count_changed(store: Path) -> None:
    """(b) 整链从 genesis 重算（自洽）但条目数变了 → length 不符 → False。"""
    honest = _entries(4, salt="honest")
    d_h, n_h = chain_digest_and_length(honest)
    seal(KIND_STEP_CHAIN, "run-001", d_h, n_h)

    forged = _entries(6, salt="forged")        # 攻击者全新自洽链，6 条
    d_f, n_f = chain_digest_and_length(forged)
    ok, reason = verify(KIND_STEP_CHAIN, "run-001", d_f, n_f)
    assert ok is False
    assert "length mismatch" in reason


def test_attack_b2_full_rechain_same_count_content_changed(store: Path) -> None:
    """(b') 整链重算、条目数相同但内容洗过 → digest 不符 → False。"""
    honest = _entries(4, salt="honest")
    d_h, n_h = chain_digest_and_length(honest)
    seal(KIND_STEP_CHAIN, "run-002", d_h, n_h)

    forged = _entries(4, salt="washed")
    d_f, n_f = chain_digest_and_length(forged)
    assert n_f == n_h
    ok, reason = verify(KIND_STEP_CHAIN, "run-002", d_f, n_f)
    assert ok is False
    assert "digest mismatch" in reason


def test_attack_c_shadow_anchor_files_ignored(
        store: Path, tmp_path: Path) -> None:
    """(c) 攻击者在被验证物内部/相邻目录放自洽影子锚 → 被忽略，仍按真锚判定。

    verify 只读 anchor_store_path() 这一处（无多路径搜索），
    所以影子 seals.jsonl 无论放哪、内容多自洽，都影响不了结果。
    """
    honest = _entries(3, salt="honest")
    d_h, n_h = chain_digest_and_length(honest)
    seal(KIND_STEP_CHAIN, "run-003", d_h, n_h)     # 真锚入规范存储

    forged = _entries(3, salt="forged")
    d_f, n_f = chain_digest_and_length(forged)

    # 影子锚 1：与被验证物同目录；影子锚 2：规范存储相邻目录（同名文件）
    shadow_rec = json.dumps({
        "ts": "2026-07-19T00:00:00+00:00", "kind": KIND_STEP_CHAIN,
        "subject_id": "run-003", "digest": d_f, "length": n_f, "extra": {}},
        ensure_ascii=False) + "\n"
    subject_dir = tmp_path / "runs" / "run-003"
    subject_dir.mkdir(parents=True)
    (subject_dir / "seals.jsonl").write_text(shadow_rec, encoding="utf-8")
    shadow_dir = store.parent.parent / "anchors-shadow"
    shadow_dir.mkdir(parents=True, exist_ok=True)
    (shadow_dir / "seals.jsonl").write_text(shadow_rec, encoding="utf-8")

    # 伪造链虽有两处"自洽影子锚"，verify 仍 False（真锚 digest 不符）
    ok, reason = verify(KIND_STEP_CHAIN, "run-003", d_f, n_f)
    assert ok is False and "digest mismatch" in reason
    # 诚实链仍按真锚判 True —— 影子文件对两个方向都零影响
    ok, reason = verify(KIND_STEP_CHAIN, "run-003", d_h, n_h)
    assert ok is True and reason == "ok"
