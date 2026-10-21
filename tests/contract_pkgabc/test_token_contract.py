"""tests/contract_pkgabc/test_token_contract.py —— 契约：令牌正样过、坏令牌逐失败路径原因码。

权威语义 = fable 广播 20260715 AMENDMENT-37（C 式 API：sign_token/verify_token/consume_token；
字段 task_id/changeset_sha256/sig；scope 冻结 "batch_approve"；原因码
missing_field:*/bad_scope/bad_signature/changeset_mismatch/bad_expires_at/expired/already_consumed；
校验顺序 结构→scope→恒时签名→envelope 哈希→过期→已消费）+ AMENDMENT-34（冻结测试 key）
+ AMENDMENT-41（正样 = fixtures/envelope_fixture.json 预签令牌；badtoken = 整信封 sig="0"*64）。

本文件由 A 版 test_token_contract.py 与 B 版 test_token.py 合并改写：
A 版 tok.verify(token, env, key)/REASON_* 常量/"signature" 字段/bad_token.json →
C 式 verify_token(...)/字符串原因码/"sig" 字段/envelope_fixture_badtoken.json；
B 版 make_token/verify(env, key, dir)/consume(token_id, dir)/token.scope==envelope.scope 的
dict 绑定校验（AMENDMENT-37 废）→ scope 冻结字符串 "batch_approve" 校验 + changeset 绑定。
一次性消费账本一律走 tmp_path（不碰仓内 state/）。
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from abcr.common import approval_token as tok
from abcr.governor import envelope as gv

REPO = Path(__file__).resolve().parents[2]

_PAYLOAD_FIELDS = ("token_id", "scope", "task_id", "changeset_sha256",
                   "expires_at", "persona_change")


def _load() -> tuple[dict, bytes, dict]:
    env = json.loads((REPO / "fixtures" / "envelope_fixture.json").read_text(encoding="utf-8"))
    key = (REPO / "fixtures" / "test_approval.key").read_bytes()
    return env, key, env["approval"]["token"]


def _resign(token: dict, key: bytes) -> dict:
    """按冻结序列化口径重签（json.dumps sort_keys、默认 separators——契约注明勿改）。"""
    core = {k: token[k] for k in _PAYLOAD_FIELDS}
    payload = json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")
    token["sig"] = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return token


def _verify(token: dict, env: dict, key: bytes, store: Path) -> tuple[bool, str]:
    return tok.verify_token(token, expected_envelope_sha256=gv.envelope_sha256(env),
                            verify_secret=key, consumed_store=store)


# ---------------------------------------------------------------- 正样
def test_frozen_key_derivation() -> None:
    """AMENDMENT-34：test_approval.key = sha256(b"abcr-w1-fixture-test-approval-key") 32 字节。"""
    key = (REPO / "fixtures" / "test_approval.key").read_bytes()
    assert key == hashlib.sha256(b"abcr-w1-fixture-test-approval-key").digest()
    assert len(key) == 32


def test_valid_token_verifies(tmp_path: Path) -> None:
    env, key, token = _load()
    ok, reason = _verify(token, env, key, tmp_path / "consumed.json")
    assert ok is True and reason == "ok"


def test_fixture_signature_matches_canonical_payload() -> None:
    """fixture 跨模块互验：按冻结口径重签 fixture 令牌核心 == fixture 预签 sig。"""
    env, key, token = _load()
    assert _resign(copy.deepcopy(token), key)["sig"] == token["sig"]
    assert token["scope"] == tok.EXPECTED_SCOPE == "batch_approve"
    assert token["task_id"] == env["batch_id"]
    assert token["changeset_sha256"] == gv.envelope_sha256(env)


def test_sign_token_roundtrip(tmp_path: Path) -> None:
    """人侧签发 → 系统侧校验闭环（冻结字段名 task_id/changeset_sha256/sig）。"""
    env, key, _ = _load()
    sha = gv.envelope_sha256(env)
    t = tok.sign_token(env["batch_id"], sha, human_secret=key)
    assert t["scope"] == "batch_approve"
    assert t["task_id"] == env["batch_id"] and t["changeset_sha256"] == sha and "sig" in t
    ok, reason = _verify(t, env, key, tmp_path / "consumed.json")
    assert ok and reason == "ok"


# ---------------------------------------------------------------- 失败路径 1：结构缺字段
@pytest.mark.parametrize("field", ["token_id", "sig", "scope", "task_id",
                                   "changeset_sha256", "expires_at", "persona_change"])
def test_missing_field(tmp_path: Path, field: str) -> None:
    env, key, token = _load()
    bad = copy.deepcopy(token)
    del bad[field]
    ok, reason = _verify(bad, env, key, tmp_path / "consumed.json")
    assert not ok and reason == f"missing_field:{field}"


# ---------------------------------------------------------------- 失败路径 2：bad_scope
def test_bad_scope(tmp_path: Path) -> None:
    """scope != "batch_approve" → bad_scope（先于签名校验；B 版 dict scope 绑定断言已废 AMENDMENT-37）。"""
    env, key, token = _load()
    bad = copy.deepcopy(token)
    bad["scope"] = "envelope_approve"
    ok, reason = _verify(bad, env, key, tmp_path / "consumed.json")
    assert not ok and reason == "bad_scope"


# ---------------------------------------------------------------- 失败路径 3：bad_signature
def test_bad_signature_badtoken_fixture(tmp_path: Path) -> None:
    """AMENDMENT-41 badtoken fixture：整信封、sig="0"*64 → bad_signature。"""
    badenv = json.loads(
        (REPO / "fixtures" / "envelope_fixture_badtoken.json").read_text(encoding="utf-8"))
    _, key, _ = _load()
    badtok = badenv["approval"]["token"]
    assert badtok["sig"] == "0" * 64
    ok, reason = _verify(badtok, badenv, key, tmp_path / "consumed.json")
    assert not ok and reason == "bad_signature"


def test_bad_signature_wrong_key(tmp_path: Path) -> None:
    """异密钥校验 → bad_signature（恒时比较）。"""
    env, _, token = _load()
    ok, reason = _verify(token, env, b"\xff" * 32, tmp_path / "consumed.json")
    assert not ok and reason == "bad_signature"


def test_bad_signature_tampered_payload(tmp_path: Path) -> None:
    """改载荷不重签 → bad_signature。"""
    env, key, token = _load()
    bad = copy.deepcopy(token)
    bad["task_id"] = "B-20260101T000000Z-9999"
    ok, reason = _verify(bad, env, key, tmp_path / "consumed.json")
    assert not ok and reason == "bad_signature"


# ---------------------------------------------------------------- 失败路径 4：changeset_mismatch
def test_changeset_mismatch_envelope_tampered(tmp_path: Path) -> None:
    """批准后改信封（非 approval 字段）→ envelope_sha256 变、签名仍验 → changeset_mismatch。"""
    env, key, token = _load()
    tampered = copy.deepcopy(env)
    tampered["drafted_by"] = "tampered"
    ok, reason = _verify(token, tampered, key, tmp_path / "consumed.json")
    assert not ok and reason == "changeset_mismatch"


def test_changeset_mismatch_resigned_foreign_hash(tmp_path: Path) -> None:
    """签名对 core 有效但 changeset 指向他处 → changeset_mismatch。"""
    env, key, token = _load()
    bad = copy.deepcopy(token)
    bad["changeset_sha256"] = "f" * 64
    _resign(bad, key)
    ok, reason = _verify(bad, env, key, tmp_path / "consumed.json")
    assert not ok and reason == "changeset_mismatch"


# ---------------------------------------------------------------- 失败路径 5：bad_expires_at
def test_bad_expires_at(tmp_path: Path) -> None:
    env, key, token = _load()
    bad = copy.deepcopy(token)
    bad["expires_at"] = "not-a-timestamp"
    _resign(bad, key)   # 重签保证走到过期解析步
    ok, reason = _verify(bad, env, key, tmp_path / "consumed.json")
    assert not ok and reason == "bad_expires_at"


# ---------------------------------------------------------------- 失败路径 6：expired
def test_expired(tmp_path: Path) -> None:
    env, key, token = _load()
    bad = copy.deepcopy(token)
    bad["expires_at"] = "2000-01-01T00:00:00+00:00"
    _resign(bad, key)
    ok, reason = _verify(bad, env, key, tmp_path / "consumed.json")
    assert not ok and reason == "expired"


def test_expired_via_sign_token_now(tmp_path: Path) -> None:
    """sign_token 的 now/ttl 注入路径：签发即过期。"""
    env, key, _ = _load()
    past = datetime(2000, 1, 1, tzinfo=timezone.utc)
    t = tok.sign_token(env["batch_id"], gv.envelope_sha256(env),
                       human_secret=key, ttl_seconds=1, now=past)
    ok, reason = _verify(t, env, key, tmp_path / "consumed.json")
    assert not ok and reason == "expired"


# ---------------------------------------------------------------- 失败路径 7：already_consumed
def test_already_consumed(tmp_path: Path) -> None:
    env, key, token = _load()
    store = tmp_path / "consumed.json"
    # keyed 部署端到端一致（F-TOKEN-02-R3-01）：consume 与 verify 用同一密钥。
    tok.consume_token(token, store, verify_secret=key)
    assert token["token_id"] in json.loads(store.read_text(encoding="utf-8"))
    ok, reason = _verify(token, env, key, store)
    assert not ok and reason == "already_consumed"


def test_corrupted_consumed_store_fails_closed(tmp_path: Path) -> None:
    """K5 修订（F-TOKEN-02）：consumed.json 损坏必须 fail-closed，拒绝一切消费，
    绝不"按空集放行"使已消费的旧令牌复活。"""
    env, key, token = _load()
    store = tmp_path / "consumed.json"
    store.write_text("{not json!!", encoding="utf-8")
    ok, reason = _verify(token, env, key, store)
    assert not ok and reason.startswith("consumed_store_unreadable")
