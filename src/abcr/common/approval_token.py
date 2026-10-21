"""abcr.common.approval_token —— 批次审批令牌（HMAC-SHA256，纯 stdlib）。

架构位置：包C·Governor 侧维护的公共契约库。签发权在人（scripts/abcrctl），
系统侧（B 的 dispatch）只 verify + consume。改写自 AILH V2 canonical 实现，
字段映射：task_id 承载 batch_id、changeset_sha256 承载 envelope_sha256。

序列化口径（签名互认的要害，勿动）：
  载荷 = json.dumps(core, ensure_ascii=False, sort_keys=True)   # 默认 separators
  注意：envelope_sha256 的规范化是另一口径 separators=(",", ":")，见 governor/envelope.py。
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

from abcr.common import consumed_ledger as _cl
# fail-closed 异常单一定义在 consumed_ledger，此处 re-export 保持 tok.ConsumedStoreError 身份稳定
# （既有测试 import tok.ConsumedStoreError）。ConsumedLedgerTampered 是其子类（删除/断链向量）。
from abcr.common.consumed_ledger import ConsumedStoreError, ConsumedLedgerTampered  # noqa: F401

EXPECTED_SCOPE = "batch_approve"   # 冻结值（AMENDMENT-11）；fixture 不符 = fixture 缺陷，报 BLOCKER 重签，勿改本常量（§4.4 核对项2）


class MissingKeyError(Exception):
    """校验密钥缺失。系统侧（dispatch）不得自铸密钥（F-TOKEN-04/P1-32 修复）。"""

_PAYLOAD_FIELDS = ("token_id", "scope", "task_id", "changeset_sha256",
                   "expires_at", "persona_change")


def default_key_path() -> Path:
    """人侧签发密钥缺省位置：<ABCR_STATE_DIR>/approval.key（契约 §3.5）。"""
    return Path(os.environ.get("ABCR_STATE_DIR", "state")) / "approval.key"


def default_consumed_store() -> Path:
    """一次性消费账本缺省位置：<ABCR_STATE_DIR>/approvals/consumed.json。"""
    return Path(os.environ.get("ABCR_STATE_DIR", "state")) / "approvals" / "consumed.json"


def load_or_create_key(path: Optional[Path] = None) -> bytes:
    """读密钥；不存在则生成 32 字节随机并 chmod 0600。

    ⚠️ 仅供**人侧签发 CLI**（scripts/abcrctl）首用生成密钥。系统/校验侧（B 的 dispatch）
    **禁止**调用本函数——自铸密钥即令签/验同权、令牌信任根失守（F-TOKEN-04/P1-32）。
    系统侧一律用 load_verify_key()（缺失即 fail-closed，不自铸）。"""
    p = path or default_key_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(secrets.token_bytes(32))
        os.chmod(p, 0o600)
    return p.read_bytes()


def load_verify_key(path: Path) -> bytes:
    """系统/校验侧读密钥：**只读、不自铸**（F-TOKEN-04/P1-32）。
    密钥文件不存在/为空 → MissingKeyError（fail-closed，绝不生成一把系统自己能签的密钥）。"""
    p = Path(path)
    if not p.exists():
        raise MissingKeyError(f"校验密钥不存在: {p}（系统侧不得自铸；须由人侧 abcrctl 预置）")
    key = p.read_bytes()
    if not key:
        raise MissingKeyError(f"校验密钥为空: {p}")
    return key


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _payload_bytes(token: dict) -> bytes:
    """签名覆盖的规范化载荷（不含 sig 本身）。默认 separators——勿改。"""
    core = {k: token[k] for k in _PAYLOAD_FIELDS}
    return json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")


# --- 人侧：签发（系统域代码不得 import 本函数）---
def sign_token(batch_id: str, envelope_sha256: str, *, human_secret: bytes,
               ttl_seconds: int = 24 * 3600,
               now: Optional[datetime] = None) -> dict:
    n = now or _now()
    token = {
        "token_id": secrets.token_hex(8),
        "scope": EXPECTED_SCOPE,
        "task_id": batch_id,                     # 字段名承 V2 canonical；值 = batch_id
        "changeset_sha256": envelope_sha256,     # 值 = envelope_sha256
        "expires_at": (n + timedelta(seconds=ttl_seconds)).isoformat(),
        "persona_change": False,
    }
    token["sig"] = hmac.new(human_secret, _payload_bytes(token), hashlib.sha256).hexdigest()
    return token


# --- 系统侧：校验 + 消费 ---
def _stateless_reason(token: dict, expected_envelope_sha256: str, verify_secret: bytes,
                      n: datetime) -> Optional[str]:
    """无状态校验（不含已消费判定）：结构→scope→恒时签名→envelope 哈希→过期。
    通过返回 None，否则返回原因码。"""
    for k in ("token_id", "sig", "scope", "task_id", "changeset_sha256",
              "expires_at", "persona_change"):
        if k not in token:
            return f"missing_field:{k}"
    if token["scope"] != EXPECTED_SCOPE:
        return "bad_scope"
    expect_sig = hmac.new(verify_secret, _payload_bytes(token), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect_sig, str(token.get("sig", ""))):
        return "bad_signature"
    if token["changeset_sha256"] != expected_envelope_sha256:
        return "changeset_mismatch"
    try:
        exp = datetime.fromisoformat(token["expires_at"])
    except (ValueError, TypeError):
        return "bad_expires_at"
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)   # naive 按 UTC 补 tzinfo
    if n >= exp:
        return "expired"
    return None


def verify_token(token: dict, *, expected_envelope_sha256: str, verify_secret: bytes,
                 consumed_store: Optional[Path] = None,
                 now: Optional[datetime] = None) -> Tuple[bool, str]:
    """只读校验（不消费）：结构→scope→恒时签名→envelope 哈希→过期→已消费。
    任一不过返回 (False, 原因码)，调用方 fail-closed 拒绝。不抛异常。

    consumed 账本损坏/截断/格式非法 → (False, 'consumed_store_unreadable:*')
    （F-TOKEN-02/34：**不再**当空集放行——旧 fail-open 语义已废）。"""
    store = consumed_store or default_consumed_store()
    reason = _stateless_reason(token, expected_envelope_sha256, verify_secret, now or _now())
    if reason is not None:
        return False, reason
    try:
        consumed = _load_consumed(store, verify_secret=verify_secret)
    except ConsumedStoreError as e:
        # ConsumedLedgerTampered（删链/断链/伪 genesis/删除向量）亦是 ConsumedStoreError 子类，
        # 统一前缀 consumed_store_unreadable，类名区分损坏 vs 篡改（F-TOKEN-02）。
        return False, f"consumed_store_unreadable:{type(e).__name__}"
    if token["token_id"] in consumed:
        return False, "already_consumed"
    return True, "ok"


def verify_and_consume(token: dict, *, expected_envelope_sha256: str, verify_secret: bytes,
                       consumed_store: Optional[Path] = None,
                       now: Optional[datetime] = None) -> Tuple[bool, str]:
    """原子领取（claim）：在**同一文件锁临界区**内完成「全部校验（含已消费判定）+ 标记消费 + fsync」。
    并发多进程对同一令牌调用：**恰好一个**返回 (True,'ok')，其余 (False,'already_consumed')
    ——修复 verify/consume 分离导致的双花/批次双执行（F-TOKEN-01/33）。
    损坏账本 → (False,'consumed_store_unreadable:*') fail-closed（不复活旧令牌，F-TOKEN-02）。"""
    store = consumed_store or default_consumed_store()
    n = now or _now()
    reason = _stateless_reason(token, expected_envelope_sha256, verify_secret, n)
    if reason is not None:
        return False, reason
    store.parent.mkdir(parents=True, exist_ok=True)
    lock_path = store.with_name(store.name + ".lock")
    with lock_path.open("a", encoding="utf-8") as lk:
        fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
        try:
            try:
                consumed = _load_consumed(store, verify_secret=verify_secret)  # 锁内重读，fail-closed
            except ConsumedStoreError as e:
                return False, f"consumed_store_unreadable:{type(e).__name__}"
            if token["token_id"] in consumed:
                return False, "already_consumed"
            # per-batch genesis 锚（design point 2）：消费时独立重算 H(env_sha||batch_id) 并写入哈希链。
            bg = _cl.genesis(expected_envelope_sha256, token["task_id"])
            try:
                _cl.append(store, token_id=token["token_id"], batch_id=token["task_id"],
                           batch_genesis=bg, verify_secret=verify_secret)
            except ConsumedStoreError as e:
                return False, f"consumed_store_unreadable:{type(e).__name__}"
            return True, "ok"
        finally:
            fcntl.flock(lk.fileno(), fcntl.LOCK_UN)


def consume_token(token: dict, consumed_store: Optional[Path] = None, *,
                  verify_secret: Optional[bytes] = None) -> None:
    """标记令牌已用（一次一用）。文件锁互斥 + 原子写 + fsync（F-TOKEN-03/35：非原子 RMW 修复）。
    损坏账本 → ConsumedStoreError（fail-closed，绝不静默丢弃既有消费记录使旧令牌复活）。

    注：dispatch 主链路已改用 verify_and_consume 原子领取；本函数保留兼容/幂等语义。
    F-TOKEN-02-R3-01：keyed 部署应端到端 keyed——传入 verify_secret 时写 keyed 锚（带 mac），
    与 verify_and_consume 一致，使『密钥在场却 mac 缺失』能被判为降级篡改而非合法 keyless。
    不传 verify_secret 则维持旧 keyless 兼容语义（删除检出仍靠锚在/链缺）。"""
    store = consumed_store or default_consumed_store()
    store.parent.mkdir(parents=True, exist_ok=True)
    lock_path = store.with_name(store.name + ".lock")
    with lock_path.open("a", encoding="utf-8") as lk:
        fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
        try:
            # 损坏/篡改 → append 内部 load_consumed 抛 ConsumedStoreError（fail-closed，绝不静默丢记录）。
            bg = _cl.genesis(token["changeset_sha256"], token["task_id"])
            _cl.append(store, token_id=token["token_id"], batch_id=token["task_id"],
                       batch_genesis=bg, verify_secret=verify_secret)
        finally:
            fcntl.flock(lk.fileno(), fcntl.LOCK_UN)


def _load_consumed(consumed_store: Path, *, verify_secret: Optional[bytes] = None) -> set:
    """读 consumed 账本（委托 consumed_ledger.load_consumed）。**fail-closed**（F-TOKEN-02/34）：
      - 链+锚+投影均不存在 → 空集（合法：尚无任何消费，全新系统首用）；
      - 投影为空/截断/非 JSON/非 list[str] → ConsumedStoreError（损坏拒绝）；
      - 链断裂/伪 genesis/『锚在而链缺（删除向量）』 → ConsumedLedgerTampered（篡改拒绝）。
    删除向量修复：删 consumed store 文件/approvals 目录 → 外部锚（approvals 之外）仍在 → 判篡改；
    全域抹除 / 密钥失陷仍无法区分冷启动 → residual（需仓外 git/audit 锚）。"""
    return _cl.load_consumed(Path(consumed_store), verify_secret=verify_secret)
