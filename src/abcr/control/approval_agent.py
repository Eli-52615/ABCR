"""Human-domain approval adapter; the operator sees only signed decisions."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from abcr.control.contracts import ContractError, require_id
from abcr.control.ed25519 import (CONTEXT_FIELDS, ApprovalRequestBundle, identity_context_hash,
                                  sign_token_v2, verify_token_v2)
from abcr.control.identity import IdentityPolicy
from abcr.control.store import ControlStore

# 15 个 CONTEXT_FIELDS 的绑定来源（decide 必须逐个核到，不留「调用方随便填」的字段）：
#   · bundle 重算事实：request_id / batch_id / envelope_sha256 /
#                      goal_anchor_entry_hash / goal_anchor_receipt_id
#   · IdentityPolicy ：approver_id_hash / tenant_key_hash / chat_id_hash / app_id_hash
#   · 调用方秘密     ：decision_nonce_hash（由 decision_nonce 现算，不接受直接填哈希）
#   · envelope       ：deployment_id / protocol_ref
#   · 协议常量/形状  ：aud / request_version / source_event_id
_IDENTITY_SOURCES = {
    "approver_id_hash": "owner_open_id", "tenant_key_hash": "tenant_key",
    "chat_id_hash": "owner_chat_id", "app_id_hash": "app_id",
}


def _expected_context(bundle: ApprovalRequestBundle, *, research_repo: Path, anchor_ledger: Path,
                      identity: IdentityPolicy, decision_nonce: str,
                      context: dict[str, Any]) -> None:
    """把 context 逐字段钉死在重算事实上。任一字段对不上即抛——**在出卡片和签名之前**。"""
    if set(context) != set(CONTEXT_FIELDS):
        raise ContractError("approval_context_fields", "approval context 字段不精确")
    verified = bundle.validate(research_repo=research_repo, anchor_ledger=anchor_ledger)

    expected = {
        "request_id": verified.request_id,
        "batch_id": verified.batch_id,
        "envelope_sha256": verified.envelope_sha256,
        "goal_anchor_entry_hash": verified.goal_anchor_entry_hash,
        "goal_anchor_receipt_id": verified.goal_anchor_receipt_id,
        "decision_nonce_hash": identity_context_hash("decision_nonce_hash", decision_nonce),
        "aud": "abcr-operator",
        # deployment_id / protocol_ref 只认 validate() 重算出的、已绑定到被锚 goal 的
        # envelope 事实——不再旁路直接读 bundle.envelope（F1：那会让未绑定的 envelope
        # 字段直接进 token）。
        "deployment_id": verified.deployment_id,
        "protocol_ref": verified.protocol_ref,
    }
    for field, attribute in _IDENTITY_SOURCES.items():
        expected[field] = identity_context_hash(field, getattr(identity, attribute))

    mismatched = sorted(field for field, want in expected.items() if context[field] != want)
    if mismatched:
        raise ContractError("approval_context_unbound",
                            "approval context 未绑定到 bundle / IdentityPolicy",
                            {"fields": mismatched})
    # 剩余 2 个字段无外部事实源可钉，做严格形状校验（request_version 的整数性由
    # sign_token_v2 再验一次；此处提前拒，保证「拒绝发生在签名之前」）。
    require_id(context["source_event_id"], "source_event_id")
    if not isinstance(context["request_version"], int) or isinstance(context["request_version"], bool):
        raise ContractError("request_version_invalid", "request_version 必须是整数")


def decide(bundle: ApprovalRequestBundle, *, private_key: Path,
           public_key: Path, context: dict[str, Any],
           store: ControlStore, identity: IdentityPolicy, decision_nonce: str,
           research_repo: Path, anchor_ledger: Path,
           ttl_seconds: int = 3600) -> dict[str, Any]:
    _expected_context(bundle, research_repo=research_repo, anchor_ledger=anchor_ledger,
                      identity=identity, decision_nonce=decision_nonce, context=context)
    return store.stable_approval(
        bundle.request_id, bundle.envelope_sha256, "approve",
        lambda: sign_token_v2(private_key=private_key, public_key=public_key,
                              context=context,
                              ttl_seconds=ttl_seconds),
    )


def import_decision(token: dict[str, Any], store: ControlStore, *, public_key: Path,
                    expected_context: dict[str, Any],
                    now: datetime | None = None) -> tuple[bool, str]:
    ok, reason = verify_token_v2(token, public_key=public_key,
                                 expected_context=expected_context, now=now)
    if not ok: return False, reason
    if not store.consume_approval(token["token_id"], token["batch_id"],
                                  token["envelope_sha256"], "approve"):
        return False, "already_consumed"
    return True, "ok"
