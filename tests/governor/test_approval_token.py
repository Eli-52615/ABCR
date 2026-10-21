"""C1-1 approval_token 防回归测试（§C1-1 补测用例，最少覆盖）。"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from abcr.common import approval_token as tok
from abcr.governor import envelope as envmod

SECRET = b"0" * 32
SHA = "a" * 64


def _sign(**over):
    """便捷签发（可覆盖 ttl/now）。"""
    return tok.sign_token("B-20260714T000000Z-0001", SHA, human_secret=SECRET,
                          ttl_seconds=over.get("ttl_seconds", 24 * 3600),
                          now=over.get("now"))


def _verify(token, store, **over):
    return tok.verify_token(token, expected_envelope_sha256=over.get("sha", SHA),
                            verify_secret=over.get("secret", SECRET),
                            consumed_store=store, now=over.get("now"))


# 1. 正样
def test_sign_verify_ok(tmp_path):
    store = tmp_path / "consumed.json"
    t = _sign()
    assert _verify(t, store) == (True, "ok")


# 2. 六失败路径逐一断言原因码
def test_missing_field(tmp_path):
    t = _sign()
    del t["sig"]
    assert _verify(t, tmp_path / "c.json") == (False, "missing_field:sig")


def test_bad_scope(tmp_path):
    t = _sign()
    t["scope"] = "wrong"
    assert _verify(t, tmp_path / "c.json") == (False, "bad_scope")


def test_bad_signature(tmp_path):
    t = _sign()
    t["task_id"] = "B-20260714T000000Z-9999"   # 签名后篡改载荷
    assert _verify(t, tmp_path / "c.json") == (False, "bad_signature")


def test_changeset_mismatch(tmp_path):
    t = _sign()
    assert _verify(t, tmp_path / "c.json", sha="b" * 64) == (False, "changeset_mismatch")


def test_expired(tmp_path):
    t = _sign(ttl_seconds=-1)
    assert _verify(t, tmp_path / "c.json") == (False, "expired")


def test_already_consumed(tmp_path):
    store = tmp_path / "consumed.json"
    t = _sign()
    assert _verify(t, store) == (True, "ok")
    # keyed 部署端到端一致（F-TOKEN-02-R3-01）：consume 与 verify 用同一密钥。
    tok.consume_token(t, store, verify_secret=SECRET)
    assert _verify(t, store) == (False, "already_consumed")


# 3. expires_at 非法 + naive ISO 时间
def test_bad_expires_at(tmp_path):
    t = _sign()
    t["expires_at"] = "not-a-date"
    t["sig"] = tok.hmac.new(SECRET, tok._payload_bytes(t), tok.hashlib.sha256).hexdigest()
    assert _verify(t, tmp_path / "c.json") == (False, "bad_expires_at")


def test_naive_iso_not_crash_and_utc(tmp_path):
    # naive 未来时间（无 tzinfo）应按 UTC 判定、不崩
    future_naive = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    t = _sign()
    t["expires_at"] = future_naive
    t["sig"] = tok.hmac.new(SECRET, tok._payload_bytes(t), tok.hashlib.sha256).hexdigest()
    assert _verify(t, tmp_path / "c.json") == (True, "ok")


# 4. consume 幂等 + consumed.json 损坏
def test_consume_idempotent(tmp_path):
    store = tmp_path / "consumed.json"
    t = _sign()
    tok.consume_token(t, store)
    tok.consume_token(t, store)   # 两次不炸
    assert t["token_id"] in json.loads(store.read_text(encoding="utf-8"))


def test_corrupt_consumed_fails_closed(tmp_path):
    """F-TOKEN-02：损坏 consumed 账本不得当空集放行（那会复活旧令牌）；
    必须 fail-closed 拒绝，且不崩溃。"""
    store = tmp_path / "consumed.json"
    store.write_text("not-json", encoding="utf-8")
    t = _sign()
    ok, reason = _verify(t, store)
    assert not ok and reason.startswith("consumed_store_unreadable")


# 5. load_or_create_key：首建 0600、幂等
def test_load_or_create_key(tmp_path):
    kp = tmp_path / "approval.key"
    k1 = tok.load_or_create_key(kp)
    assert kp.exists() and len(k1) == 32
    assert stat.S_IMODE(os.stat(kp).st_mode) == 0o600
    k2 = tok.load_or_create_key(kp)
    assert k1 == k2   # 重复调用同一 key


# 6. fixture 真值锚（envelope_sha256 用 C1-2 的函数算）
def test_fixture_anchor(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = envmod.load_envelope(root / "fixtures" / "envelope_fixture.json")
    key = (root / "fixtures" / "test_approval.key").read_bytes()
    token = env["approval"]["token"]
    sha = envmod.envelope_sha256(env)
    assert _verify(token, tmp_path / "c.json", sha=sha, secret=key) == (True, "ok")


def test_fixture_badtoken_anchor(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = envmod.load_envelope(root / "fixtures" / "envelope_fixture_badtoken.json")
    key = (root / "fixtures" / "test_approval.key").read_bytes()
    token = env["approval"]["token"]
    sha = envmod.envelope_sha256(env)
    ok, why = _verify(token, tmp_path / "c.json", sha=sha, secret=key)
    assert (ok, why) == (False, "bad_signature")
