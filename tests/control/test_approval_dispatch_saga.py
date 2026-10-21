from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from abcr.control.approval_dispatch import sign_claim_result
from abcr.control.contracts import sha256
from abcr.control.ed25519 import generate_keypair
from abcr.control.store import ControlStore, StoreError


def _request() -> dict:
    return {
        "claim_id": "CLM-0123456789abcdef0123456789abcdef",
        "token_id": "0123456789abcdef0123456789abcdef",
        "request_id": "APR-1", "request_version": 1,
        "batch_id": "EXP-0123456789abcdef0123", "envelope_hash": "a" * 64,
        "release_id": "REL-1", "approval_event_id": "EVT-approved",
        "effect_id": "b" * 64,
    }


def test_human_first_claim_is_stable_and_settles_once(tmp_path):
    private = tmp_path / "human.pem"; public = tmp_path / "human.pub"
    generate_keypair(private, public)
    store = ControlStore(tmp_path / "human.sqlite3")
    signer = lambda core: sign_claim_result(core, private_key=private, public_key=public)
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    first = store.stable_dispatch_claim(request=_request(), expires_at=expiry, signer=signer)
    replay = store.stable_dispatch_claim(request=_request(), expires_at=expiry, signer=signer)
    assert replay == first
    assert first["core"]["state"] == "claimed"

    receipt_hash = sha256(first)
    assert store.settle_dispatch_claim(
        _request()["claim_id"], receipt_hash=receipt_hash,
        effect_id=_request()["effect_id"], dispatch_event_id="EVT-dispatched")
    assert not store.settle_dispatch_claim(
        _request()["claim_id"], receipt_hash=receipt_hash,
        effect_id=_request()["effect_id"], dispatch_event_id="EVT-dispatched")


def test_expired_unseen_token_is_denied_and_can_never_settle(tmp_path):
    private = tmp_path / "human.pem"; public = tmp_path / "human.pub"
    generate_keypair(private, public)
    store = ControlStore(tmp_path / "human.sqlite3")
    result = store.stable_dispatch_claim(
        request=_request(),
        expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        signer=lambda core: sign_claim_result(
            core, private_key=private, public_key=public),
    )
    assert result["core"]["state"] == "denied"
    assert result["core"]["first_claim_at"] is None
    assert result["core"]["reason_code"] == "APPROVAL_EXPIRED"
    with pytest.raises(StoreError):
        store.settle_dispatch_claim(
            _request()["claim_id"],
            receipt_hash=sha256(result),
            effect_id=_request()["effect_id"], dispatch_event_id="EVT-illegal")
