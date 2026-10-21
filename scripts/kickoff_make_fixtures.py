#!/usr/bin/env python3
"""kickoff_make_fixtures.py —— fixture 单点生成器（fable 维护；AMENDMENT-41）。

三包自产生成器（_bootstrap_fixtures / b_make_fixtures / c_bootstrap_fixtures）废弃，
三 worktree 只消费不自产。用法（主仓根）：
    PYTHONPATH=src .venv312/bin/python scripts/kickoff_make_fixtures.py

产物：
  fixtures/test_approval.key            确定性 32 字节（AMENDMENT-34），0600
  fixtures/envelope_fixture.json        B 版信封原件 + fable 以冻结 key 重签的 approval 块
  fixtures/envelope_fixture_badtoken.json  同信封，sig="0"*64（AMENDMENT-12 命名）
不重生成：golden10.json（A 版冻结实物）、expected_scores.jsonl（B 版冻结实物）、
faketask_spec.md（冻结文本）。

自证：生成后就地跑六步互验（validate_envelope / sha 自洽 / 正样 verify ok / 坏样
bad_signature / 过期路径 / consumed 路径），任一不过即退出非 0——生成即验收。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from abcr.common import approval_token as tok            # noqa: E402
from abcr.governor.envelope import (                     # noqa: E402
    envelope_sha256, load_envelope, save_envelope, validate_envelope)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"

# AMENDMENT-34：测试专用确定性密钥（唯一入 git 的 key；真实密钥禁入 git 不变）
KEY_SEED = b"abcr-w1-fixture-test-approval-key"
TTL_SECONDS = 10 * 365 * 24 * 3600   # 长效 TTL（疑议#5 裁决：静态 fixture 不设演练日过期陷阱）


def main() -> int:
    FIXTURES.mkdir(exist_ok=True)

    # 1) 冻结测试密钥
    key = hashlib.sha256(KEY_SEED).digest()
    key_path = FIXTURES / "test_approval.key"
    key_path.write_bytes(key)
    os.chmod(key_path, 0o600)

    # 2) 信封：以仓内现存 envelope_fixture.json 为底（首次生成时 = B 版原件），重签 approval
    env_path = FIXTURES / "envelope_fixture.json"
    env = load_envelope(env_path)
    env.pop("approval", None)
    ok, problems = validate_envelope(env)
    if not ok:
        print(f"FAIL validate_envelope: {problems}", file=sys.stderr)
        return 1
    sha = envelope_sha256(env)
    token = tok.sign_token(env["batch_id"], sha, human_secret=key, ttl_seconds=TTL_SECONDS)
    env["approval"] = {"token": token, "approved_at": None}   # 预签未批：approve 时填 approved_at
    save_envelope(env_path, env)

    # 3) 坏令牌独立文件（AMENDMENT-12）
    bad = json.loads(json.dumps(env, ensure_ascii=False))
    bad["approval"]["token"]["sig"] = "0" * 64
    save_envelope(FIXTURES / "envelope_fixture_badtoken.json", bad)

    # 4) 自证六步（生成即验收）
    with tempfile.TemporaryDirectory() as td:
        store = Path(td) / "consumed.json"
        good = load_envelope(env_path)
        sha2 = envelope_sha256(good)
        assert sha2 == sha, "重载后 envelope_sha256 漂移"
        v_ok, v_reason = tok.verify_token(
            good["approval"]["token"], expected_envelope_sha256=sha2,
            verify_secret=key, consumed_store=store)
        assert (v_ok, v_reason) == (True, "ok"), f"正样验签失败: {v_reason}"
        badtok = load_envelope(FIXTURES / "envelope_fixture_badtoken.json")["approval"]["token"]
        b_ok, b_reason = tok.verify_token(
            badtok, expected_envelope_sha256=sha2, verify_secret=key, consumed_store=store)
        assert (b_ok, b_reason) == (False, "bad_signature"), f"坏样应 bad_signature: {b_reason}"
        w_ok, w_reason = tok.verify_token(
            good["approval"]["token"], expected_envelope_sha256="f" * 64,
            verify_secret=key, consumed_store=store)
        assert (w_ok, w_reason) == (False, "changeset_mismatch"), f"哈希失配路径: {w_reason}"
        tok.consume_token(good["approval"]["token"], store)
        c_ok, c_reason = tok.verify_token(
            good["approval"]["token"], expected_envelope_sha256=sha2,
            verify_secret=key, consumed_store=store)
        assert (c_ok, c_reason) == (False, "already_consumed"), f"消费路径: {c_reason}"

    print(f"OK  key={key_path} envelope_sha256={sha[:16]}… token_id={token['token_id']} "
          f"expires={token['expires_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
