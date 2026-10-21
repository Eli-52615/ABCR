from __future__ import annotations

import base64
import os
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from abcr.control.approval_agent import decide, import_decision
from abcr.control.contracts import ContractError, sha256
from abcr.control.ed25519 import (GOAL_ANCHOR_EVENT, ApprovalRequestBundle, generate_keypair,
                                  identity_context_hash, sign_token_v2,
                                  verify_anchor_prefix_proof, verify_token_v2)
from abcr.control.identity import IdentityPolicy
from abcr.control.store import ControlStore
from abcr.explore.memory import ResearchMemory

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None or shutil.which("git") is None,
                                reason="openssl/git unavailable")

GOAL_BYTES = b"goal: study persona drift\n"
GOAL_PATH = "goals/g1.yaml"
RECEIPT_ID = "receipt-1"
OWNER = IdentityPolicy(owner_open_id="ou_owner", owner_chat_id="oc_chat",
                       tenant_key="tk_1", app_id="cli_app")
NONCE = "nonce-abcdef"


def keys(tmp_path):
    private = tmp_path / "human.pem"; public = tmp_path / "public.pem"
    generate_keypair(private, public); return private, public


def context(envelope_hash="a" * 64):
    return {"aud": "abcr-operator", "deployment_id": "d1", "protocol_ref": "p1",
            "request_id": "r1", "request_version": 3, "source_event_id": "evt-1",
            "tenant_key_hash": "1" * 64, "chat_id_hash": "2" * 64,
            "app_id_hash": "3" * 64, "decision_nonce_hash": "4" * 64,
            "goal_anchor_entry_hash": "5" * 64, "goal_anchor_receipt_id": "receipt-1",
            "batch_id": "b1", "envelope_sha256": envelope_hash,
            "approver_id_hash": "6" * 64}


# --------------------------------------------------------------------------
# 真实世界搭建：真 git 仓库 + 真 anchor 哈希链（用 ResearchMemory 产出，公式即生产公式）
# --------------------------------------------------------------------------

def _git(repo: Path, *argv: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, check=True)
    return proc.stdout.decode().strip()


def research_repo(tmp_path: Path, goal_bytes: bytes = GOAL_BYTES) -> tuple[Path, str]:
    repo = tmp_path / "research"; (repo / "goals").mkdir(parents=True)
    _git(repo.parent, "init", "-q", str(repo))
    (repo / GOAL_PATH).write_bytes(goal_bytes)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-qm", "freeze goal")
    return repo, _git(repo, "rev-parse", "HEAD")


def anchor_ledger(tmp_path: Path, commit: str, *, goal_hash: str | None = None,
                  goal_path: str = GOAL_PATH, receipt_id: str = RECEIPT_ID,
                  filler: int = 2) -> tuple[Path, str]:
    """真链：filler 条前置事件 + 1 条 goal_anchor_frozen；返回 (路径, anchor entry_hash)。"""
    path = tmp_path / "memory.jsonl"
    memory = ResearchMemory(path)
    for i in range(filler):
        memory.append("proposal_imported", f"p{i}", {"seq": i}, actor_id="ou_owner")
    row = memory.append(GOAL_ANCHOR_EVENT, "g1", {
        "goal_sha256": goal_hash or sha256(GOAL_BYTES), "goal_path": goal_path,
        "research_commit": commit, "receipt_id": receipt_id,
        "deployment_id": "d1", "protocol_ref": "p1"}, actor_id="ou_owner")
    return path, row["entry_hash"]


def proof_for(path: Path) -> tuple[str, ...]:
    rows = ResearchMemory(path).verify()
    return tuple(row["entry_hash"] for row in rows)


def envelope_for(commit: str, *, goal_hash: str | None = None, deployment_id: str = "d1",
                 protocol_ref: str = "p1", receipt_id: str = RECEIPT_ID,
                 **extra) -> tuple[dict, str]:
    """真实 compile_goal 形状的 envelope：含 goal 身份字段 + 自证 batch_id。

    batch_id = "EXP-" + sha256(core)[:20]（core = envelope 除 batch_id 外的全部字段），
    与 abcr.explore.compiler.compile_goal 的派生公式逐字一致。
    """
    core = {"goal_id": "g1", "goal_hash": goal_hash or sha256(GOAL_BYTES),
            "goal_receipt_id": receipt_id, "research_commit": commit,
            "deployment_id": deployment_id, "protocol_ref": protocol_ref, **extra}
    batch_id = "EXP-" + sha256(core)[:20]
    return dict(core, batch_id=batch_id), batch_id


def world(tmp_path: Path, goal_bytes: bytes = GOAL_BYTES):
    repo, commit = research_repo(tmp_path, goal_bytes)
    ledger, entry_hash = anchor_ledger(tmp_path, commit, goal_hash=sha256(goal_bytes))
    envelope, batch_id = envelope_for(commit, goal_hash=sha256(goal_bytes))
    envelope_hash = sha256(envelope)
    bundle = ApprovalRequestBundle(
        batch_id, base64.b64encode(goal_bytes).decode(), sha256(goal_bytes), commit,
        {"receipt_id": RECEIPT_ID, "goal_hash": sha256(goal_bytes), "research_commit": commit},
        envelope, envelope_hash, proof_for(ledger))
    return repo, ledger, entry_hash, commit, envelope_hash, bundle


def bound_context(entry_hash: str, envelope_hash: str, batch_id: str) -> dict:
    """request_id 与 batch_id 同为被锚 goal 的自证 batch_id（request_id 已不再自由）。"""
    return {"aud": "abcr-operator", "deployment_id": "d1", "protocol_ref": "p1",
            "request_id": batch_id, "request_version": 3, "source_event_id": "evt-1",
            "tenant_key_hash": identity_context_hash("tenant_key_hash", OWNER.tenant_key),
            "chat_id_hash": identity_context_hash("chat_id_hash", OWNER.owner_chat_id),
            "app_id_hash": identity_context_hash("app_id_hash", OWNER.app_id),
            "decision_nonce_hash": identity_context_hash("decision_nonce_hash", NONCE),
            "goal_anchor_entry_hash": entry_hash, "goal_anchor_receipt_id": RECEIPT_ID,
            "batch_id": batch_id, "envelope_sha256": envelope_hash,
            "approver_id_hash": identity_context_hash("approver_id_hash", OWNER.owner_open_id)}


def decide_kwargs(tmp_path, repo, ledger, name="control.db"):
    private, public = keys(tmp_path)
    seal_private = tmp_path / f"{name}.anchor-sealer.key"
    seal_public = tmp_path / f"{name}.anchor-sealer.pub"
    seal_path = tmp_path / f"{name}.research-memory.seal.json"
    generate_keypair(seal_private, seal_public)
    ResearchMemory(ledger).write_external_seal(
        seal_path, private_key=seal_private, public_key=seal_public)
    return dict(private_key=private, public_key=public, store=ControlStore(tmp_path / name),
                identity=OWNER, decision_nonce=NONCE, research_repo=repo, anchor_ledger=ledger,
                anchor_seal_path=seal_path, anchor_sealer_public_key=seal_public,
                anchor_seal_owner_uid=os.getuid(), anchor_ledger_owner_uid=os.getuid(),
                allow_direct_fixture=True)


def fixture_validate(bundle: ApprovalRequestBundle, repo: Path, ledger: Path):
    """Low-level fixtures can exercise chain checks without provisioning the root seal."""
    return bundle.validate(research_repo=repo, anchor_ledger=ledger,
                           allow_unsealed_fixture=True)


# --------------------------------------------------------------------------
# 既有强项（原样保留）
# --------------------------------------------------------------------------

def test_v2_public_verify_environment_binding_and_one_shot(tmp_path):
    private, public = keys(tmp_path); env_hash = "a" * 64
    ctx = context(env_hash)
    token = sign_token_v2(private_key=private, public_key=public, context=ctx, ttl_seconds=60)
    assert verify_token_v2(token, public_key=public, expected_context=ctx) == (True, "ok")
    assert verify_token_v2(token, public_key=public,
                           expected_context=dict(ctx, app_id_hash="f" * 64))[1] == "request_snapshot_mismatch"
    store = ControlStore(tmp_path / "control.db")
    kwargs = dict(public_key=public, expected_context=ctx)
    assert import_decision(token, store, **kwargs) == (True, "ok")
    assert import_decision(token, store, **kwargs) == (False, "already_consumed")


def test_v2_mutation_and_expiry_reject(tmp_path):
    private, public = keys(tmp_path); now = datetime.now(timezone.utc)
    ctx = context()
    token = sign_token_v2(private_key=private, public_key=public, context=ctx,
                          ttl_seconds=1, now=now)
    changed = dict(token, batch_id="b2")
    assert verify_token_v2(changed, public_key=public,
                           expected_context=dict(ctx, batch_id="b2"))[1] == "bad_signature"
    assert verify_token_v2(token, public_key=public, expected_context=ctx,
                           now=now + timedelta(seconds=2))[1] == "expired"
    assert token["signature_b64"].endswith("==") and "-" not in token["signature_b64"]


def test_concurrent_clicks_return_one_stable_signed_decision(tmp_path):
    repo, ledger, entry_hash, _, envelope_hash, bundle = world(tmp_path)
    kwargs = decide_kwargs(tmp_path, repo, ledger, "human.db")
    ctx = bound_context(entry_hash, envelope_hash, bundle.envelope["batch_id"])
    tokens = []
    threads = [threading.Thread(target=lambda: tokens.append(decide(bundle, context=ctx, **kwargs)))
               for _ in range(10)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert len(tokens) == 10
    assert len({token["token_id"] for token in tokens}) == 1
    assert len(kwargs["store"].rows("approval_decisions")) == 1


# --------------------------------------------------------------------------
# P0-5：「证明」必须是真验证 —— 原样执行已验证攻击，断言现在失败
# --------------------------------------------------------------------------

def test_happy_path_bundle_validates_against_real_repo_and_chain(tmp_path):
    repo, ledger, entry_hash, commit, _, bundle = world(tmp_path)
    verified = fixture_validate(bundle, repo, ledger)
    assert verified.goal_anchor_entry_hash == entry_hash
    assert verified.research_commit == commit
    assert verified.goal_anchor_receipt_id == RECEIPT_ID


def test_forged_commit_and_bogus_anchor_proof_are_rejected(tmp_path):
    """已验证攻击原文：research_commit="c"*40 + anchor_prefix_proof=("bogus-anchor",)。"""
    repo, ledger, _, _, _, _ = world(tmp_path)
    envelope = {"batch_id": "b1", "deployment_id": "d1", "protocol_ref": "p1"}
    forged = ApprovalRequestBundle(
        "r1", base64.b64encode(GOAL_BYTES).decode(), sha256(GOAL_BYTES), "c" * 40,
        {"receipt_id": RECEIPT_ID, "goal_hash": sha256(GOAL_BYTES), "research_commit": "c" * 40},
        envelope, sha256(envelope), ("bogus-anchor",))
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(forged, repo, ledger)
    assert excinfo.value.code == "anchor_proof_malformed"


def test_forged_commit_with_wellformed_but_fake_anchor_is_rejected(tmp_path):
    """proof 形状合法（64 位十六进制）但不在真实链上 —— 仍必须拒。"""
    repo, ledger, _, _, _, _ = world(tmp_path)
    envelope = {"batch_id": "b1", "deployment_id": "d1", "protocol_ref": "p1"}
    forged = ApprovalRequestBundle(
        "r1", base64.b64encode(GOAL_BYTES).decode(), sha256(GOAL_BYTES), "c" * 40,
        {"receipt_id": RECEIPT_ID, "goal_hash": sha256(GOAL_BYTES), "research_commit": "c" * 40},
        envelope, sha256(envelope), ("f" * 64,))
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(forged, repo, ledger)
    assert excinfo.value.code == "anchor_proof_mismatch"


def test_forged_bundle_never_reaches_signature(tmp_path):
    """攻击原文走完整 decide()：必须在出卡片/签名之前被拒，且账本零落库。"""
    repo, ledger, entry_hash, _, envelope_hash, bundle = world(tmp_path)
    envelope = {"batch_id": "b1", "deployment_id": "d1", "protocol_ref": "p1"}
    forged = ApprovalRequestBundle(
        "r1", base64.b64encode(GOAL_BYTES).decode(), sha256(GOAL_BYTES), "c" * 40,
        {"receipt_id": RECEIPT_ID, "goal_hash": sha256(GOAL_BYTES), "research_commit": "c" * 40},
        envelope, sha256(envelope), ("bogus-anchor",))
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    with pytest.raises(ContractError):
        decide(forged, context=bound_context(entry_hash, envelope_hash, bundle.envelope["batch_id"]), **kwargs)
    assert kwargs["store"].rows("approval_decisions") == []


@pytest.mark.parametrize("link", [0, 1, 2])
def test_tampering_any_link_of_the_anchor_proof_is_rejected(tmp_path, link):
    repo, ledger, _, _, _, bundle = world(tmp_path)
    proof = list(bundle.anchor_prefix_proof)
    assert len(proof) == 3
    proof[link] = "0" * 63 + "1"
    tampered = ApprovalRequestBundle(*[*_fields(bundle)[:-1], tuple(proof)])
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(tampered, repo, ledger)
    assert excinfo.value.code == "anchor_proof_mismatch"


def test_tampering_a_row_of_the_anchor_ledger_is_rejected(tmp_path):
    """改链上一行的内容（proof 不动）—— 重算 entry_hash 失配，必须拒。"""
    repo, ledger, _, _, _, bundle = world(tmp_path)
    rows = ledger.read_text(encoding="utf-8").splitlines()
    rows[0] = rows[0].replace('"p0"', '"p0-tampered"')
    ledger.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, repo, ledger)
    assert excinfo.value.code == "anchor_chain_break"


def test_proof_may_not_claim_more_links_than_the_chain_has(tmp_path):
    repo, ledger, _, _, _, bundle = world(tmp_path)
    longer = (*bundle.anchor_prefix_proof, "e" * 64)
    tampered = ApprovalRequestBundle(*[*_fields(bundle)[:-1], longer])
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(tampered, repo, ledger)
    assert excinfo.value.code == "anchor_proof_too_long"


def test_proof_must_terminate_on_a_goal_anchor_row(tmp_path):
    """截短到 filler 行 —— 前缀本身自洽,但末端不是 goal anchor,必须拒。"""
    repo, ledger, _, _, _, bundle = world(tmp_path)
    short = bundle.anchor_prefix_proof[:1]
    tampered = ApprovalRequestBundle(*[*_fields(bundle)[:-1], short])
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(tampered, repo, ledger)
    assert excinfo.value.code == "anchor_proof_not_goal_anchor"


def test_anchor_ledger_unreachable_is_a_hard_error(tmp_path):
    repo, ledger, _, _, _, bundle = world(tmp_path)
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, repo, tmp_path / "nope.jsonl")
    assert excinfo.value.code == "anchor_ledger_unreachable"


def test_anchor_chain_formula_matches_research_memory(tmp_path):
    """防定义漂移：本模块重算的公式必须与 ResearchMemory 真实产出的链一致。"""
    _, commit = research_repo(tmp_path)
    ledger, entry_hash = anchor_ledger(tmp_path, commit, filler=4)
    row = verify_anchor_prefix_proof(ledger, proof_for(ledger))
    assert row["entry_hash"] == entry_hash
    assert row["payload"]["research_commit"] == commit


# --------------------------------------------------------------------------
# P0-5：research_commit 必须真解析
# --------------------------------------------------------------------------

def test_research_repo_unreachable_is_a_hard_error_not_a_skip(tmp_path):
    _, ledger, _, _, _, bundle = world(tmp_path)
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, tmp_path / "no-such-repo", ledger)
    assert excinfo.value.code == "research_repo_unreachable"
    plain = tmp_path / "plain"; plain.mkdir()
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, plain, ledger)
    assert excinfo.value.code == "research_repo_unreachable"


def test_commit_absent_from_repo_is_rejected(tmp_path):
    """anchor 链和 bundle 都一致地声称一个不存在的 commit —— git 说了算,必须拒。"""
    repo, _ = research_repo(tmp_path)
    ghost = "c" * 40
    ledger, _ = anchor_ledger(tmp_path, ghost)
    envelope = {"batch_id": "b1", "deployment_id": "d1", "protocol_ref": "p1"}
    bundle = ApprovalRequestBundle(
        "r1", base64.b64encode(GOAL_BYTES).decode(), sha256(GOAL_BYTES), ghost,
        {"receipt_id": RECEIPT_ID, "goal_hash": sha256(GOAL_BYTES), "research_commit": ghost},
        envelope, sha256(envelope), proof_for(ledger))
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, repo, ledger)
    assert excinfo.value.code == "research_commit_unknown"


def test_goal_file_absent_at_that_commit_is_rejected(tmp_path):
    repo, commit = research_repo(tmp_path)
    ledger, _ = anchor_ledger(tmp_path, commit, goal_path="goals/other.yaml")
    envelope = {"batch_id": "b1", "deployment_id": "d1", "protocol_ref": "p1"}
    bundle = ApprovalRequestBundle(
        "r1", base64.b64encode(GOAL_BYTES).decode(), sha256(GOAL_BYTES), commit,
        {"receipt_id": RECEIPT_ID, "goal_hash": sha256(GOAL_BYTES), "research_commit": commit},
        envelope, sha256(envelope), proof_for(ledger))
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, repo, ledger)
    assert excinfo.value.code == "goal_blob_missing"


def test_goal_bytes_changed_after_the_commit_is_rejected_before_signing(tmp_path):
    """goal 字节被改（连同自洽的 goal_sha256 / receipt / 链）—— commit 内字节是真,必须拒。"""
    repo, commit = research_repo(tmp_path)
    evil = b"goal: exfiltrate everything\n"
    ledger, entry_hash = anchor_ledger(tmp_path, commit, goal_hash=sha256(evil))
    envelope = {"batch_id": "b1", "deployment_id": "d1", "protocol_ref": "p1"}
    envelope_hash = sha256(envelope)
    bundle = ApprovalRequestBundle(
        "r1", base64.b64encode(evil).decode(), sha256(evil), commit,
        {"receipt_id": RECEIPT_ID, "goal_hash": sha256(evil), "research_commit": commit},
        envelope, envelope_hash, proof_for(ledger))
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, repo, ledger)
    assert excinfo.value.code == "goal_blob_mismatch"
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    with pytest.raises(ContractError):
        decide(bundle, context=bound_context(entry_hash, envelope_hash, bundle.envelope["batch_id"]), **kwargs)
    assert kwargs["store"].rows("approval_decisions") == []


def test_truncated_bundle_is_rejected_before_signing(tmp_path):
    """envelope 被截断（去掉 protocol_ref）—— envelope_sha256 失配,签名前拒。"""
    repo, ledger, entry_hash, commit, envelope_hash, _ = world(tmp_path)
    truncated_envelope = {"batch_id": "b1", "deployment_id": "d1"}
    bundle = ApprovalRequestBundle(
        "r1", base64.b64encode(GOAL_BYTES).decode(), sha256(GOAL_BYTES), commit,
        {"receipt_id": RECEIPT_ID, "goal_hash": sha256(GOAL_BYTES), "research_commit": commit},
        truncated_envelope, envelope_hash, proof_for(ledger))
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, repo, ledger)
    assert excinfo.value.code == "envelope_bytes_mismatch"
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    with pytest.raises(ContractError):
        decide(bundle, context=bound_context(entry_hash, envelope_hash, bundle.envelope["batch_id"]), **kwargs)
    assert kwargs["store"].rows("approval_decisions") == []


# --------------------------------------------------------------------------
# P0-5b：15 个 context 字段必须全部绑定
# --------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["goal_anchor_entry_hash", "goal_anchor_receipt_id",
                                   "approver_id_hash", "tenant_key_hash", "chat_id_hash",
                                   "app_id_hash", "decision_nonce_hash"])
def test_each_identity_field_must_be_bound(tmp_path, field):
    """7 个身份字段逐个换成任意合法值 —— 每一个都必须被拒,且签名前拒。"""
    repo, ledger, entry_hash, _, envelope_hash, bundle = world(tmp_path)
    forged = dict(bound_context(entry_hash, envelope_hash, bundle.envelope["batch_id"]), **{field: "d" * 64})
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    with pytest.raises(ContractError) as excinfo:
        decide(bundle, context=forged, **kwargs)
    assert excinfo.value.code == "approval_context_unbound"
    assert excinfo.value.details["fields"] == [field]
    assert kwargs["store"].rows("approval_decisions") == []


@pytest.mark.parametrize("field,value", [("request_id", "r2"), ("batch_id", "b2"),
                                         ("envelope_sha256", "a" * 64), ("aud", "someone-else"),
                                         ("deployment_id", "d2"), ("protocol_ref", "p2")])
def test_remaining_bound_fields_are_checked_too(tmp_path, field, value):
    repo, ledger, entry_hash, _, envelope_hash, bundle = world(tmp_path)
    forged = dict(bound_context(entry_hash, envelope_hash, bundle.envelope["batch_id"]), **{field: value})
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    with pytest.raises(ContractError) as excinfo:
        decide(bundle, context=forged, **kwargs)
    assert excinfo.value.code == "approval_context_unbound"


def test_identity_hashes_are_domain_separated(tmp_path):
    """把 tenant_key 的哈希塞进 chat_id_hash 位 —— 域分隔使其无法冒充。"""
    repo, ledger, entry_hash, _, envelope_hash, bundle = world(tmp_path)
    same_value_wrong_field = identity_context_hash("tenant_key_hash", OWNER.owner_chat_id)
    forged = dict(bound_context(entry_hash, envelope_hash, bundle.envelope["batch_id"]), chat_id_hash=same_value_wrong_field)
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    with pytest.raises(ContractError):
        decide(bundle, context=forged, **kwargs)


def test_decision_nonce_hash_cannot_be_supplied_directly(tmp_path):
    """调用方只能给 nonce 原文;给错 nonce 即签不出。"""
    repo, ledger, entry_hash, _, envelope_hash, bundle = world(tmp_path)
    ctx = bound_context(entry_hash, envelope_hash, bundle.envelope["batch_id"])
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    kwargs["decision_nonce"] = "some-other-nonce"
    with pytest.raises(ContractError) as excinfo:
        decide(bundle, context=ctx, **kwargs)
    assert excinfo.value.details["fields"] == ["decision_nonce_hash"]


def test_context_field_set_must_be_exact(tmp_path):
    repo, ledger, entry_hash, _, envelope_hash, bundle = world(tmp_path)
    ctx = bound_context(entry_hash, envelope_hash, bundle.envelope["batch_id"]); ctx.pop("source_event_id")
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    with pytest.raises(ContractError) as excinfo:
        decide(bundle, context=ctx, **kwargs)
    assert excinfo.value.code == "approval_context_fields"


# --------------------------------------------------------------------------
# P2：goal_bytes_b64 必须 canonical 回环
# --------------------------------------------------------------------------

@pytest.mark.parametrize("encoded", ["Zm9vYh==", "Zm9vYj=="])
def test_non_canonical_goal_base64_rejected(tmp_path, encoded):
    """Zm9vYg== 与 Zm9vYh== 解码结果相同;非 canonical 的那个必须拒,canonical 的必须过。"""
    repo, commit = research_repo(tmp_path, b"foob")
    ledger, _ = anchor_ledger(tmp_path, commit, goal_hash=sha256(b"foob"))
    envelope, batch_id = envelope_for(commit, goal_hash=sha256(b"foob"))
    assert base64.b64decode(encoded, validate=True) == b"foob"   # 同一解码结果
    bundle = ApprovalRequestBundle(
        batch_id, encoded, sha256(b"foob"), commit,
        {"receipt_id": RECEIPT_ID, "goal_hash": sha256(b"foob"), "research_commit": commit},
        envelope, sha256(envelope), proof_for(ledger))
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, repo, ledger)
    assert excinfo.value.code == "goal_bytes_encoding"
    canonical = ApprovalRequestBundle(
        batch_id, "Zm9vYg==", sha256(b"foob"), commit,
        {"receipt_id": RECEIPT_ID, "goal_hash": sha256(b"foob"), "research_commit": commit},
        envelope, sha256(envelope), proof_for(ledger))
    assert fixture_validate(canonical, repo, ledger).research_commit == commit


# --------------------------------------------------------------------------
# F1：被批之物(batch/deployment/request)必须可证明地属于被锚定的 goal
# --------------------------------------------------------------------------

def _real_chain(tmp_path):
    """真 git 仓库 + 真 anchor 链(锚定当前 GOAL_BYTES);返回构 bundle 所需材料。"""
    repo, commit = research_repo(tmp_path)
    ledger, entry_hash = anchor_ledger(tmp_path, commit, goal_hash=sha256(GOAL_BYTES))
    return repo, commit, ledger, entry_hash


def _goal_bundle(commit, ledger, envelope, request_id):
    return ApprovalRequestBundle(
        request_id, base64.b64encode(GOAL_BYTES).decode(), sha256(GOAL_BYTES), commit,
        {"receipt_id": RECEIPT_ID, "goal_hash": sha256(GOAL_BYTES), "research_commit": commit},
        envelope, sha256(envelope), proof_for(ledger))


def test_a4_attacker_authored_envelope_is_rejected_before_signing(tmp_path):
    """A4 原样复现:真链、真当前 goal + 攻击者自撰 envelope
    (batch_id="b-attacker-chosen", deployment_id="prod-cluster", 外加任意 payload)。
    之前 decide() 会签发;现在 validate 与 decide 都必须拒,账本零落库。"""
    repo, commit, ledger, entry_hash = _real_chain(tmp_path)
    envelope = {"batch_id": "b-attacker-chosen", "deployment_id": "prod-cluster",
                "protocol_ref": "p1", "attacker_payload": "ship whatever I want"}
    bundle = _goal_bundle(commit, ledger, envelope, "b-attacker-chosen")
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, repo, ledger)
    assert excinfo.value.code == "envelope_goal_mismatch"
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    ctx = bound_context(entry_hash, sha256(envelope), "b-attacker-chosen")
    with pytest.raises(ContractError):
        decide(bundle, context=ctx, **kwargs)
    assert kwargs["store"].rows("approval_decisions") == []


def test_a4_free_batch_id_with_correct_goal_identity_is_rejected(tmp_path):
    """更强的攻击:goal 身份字段全对,仍自撰 batch_id —— batch_id 自证失败必须拒。"""
    repo, commit, ledger, _ = _real_chain(tmp_path)
    envelope = {"goal_id": "g1", "goal_hash": sha256(GOAL_BYTES), "goal_receipt_id": RECEIPT_ID,
                "research_commit": commit, "deployment_id": "prod-cluster",
                "protocol_ref": "p1", "batch_id": "b-attacker-chosen"}
    bundle = _goal_bundle(commit, ledger, envelope, "b-attacker-chosen")
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, repo, ledger)
    assert excinfo.value.code == "envelope_batch_id_forged"


def test_envelope_goal_hash_swapped_to_another_goal_is_rejected(tmp_path):
    """envelope 的 goal_hash 换成另一个 goal(自证 batch_id 随之重算) —— 与被锚 goal 不符必须拒。"""
    repo, commit, ledger, _ = _real_chain(tmp_path)
    other = sha256(b"goal: a completely different goal\n")
    envelope, batch_id = envelope_for(commit, goal_hash=other)
    bundle = _goal_bundle(commit, ledger, envelope, batch_id)
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, repo, ledger)
    assert excinfo.value.code == "envelope_goal_mismatch"


def test_token_deployment_id_inconsistent_with_bound_envelope_is_rejected(tmp_path):
    """token 的 deployment_id 与被锚 envelope 声称的不一致 —— 签名前拒,零落库。"""
    repo, ledger, entry_hash, _, envelope_hash, bundle = world(tmp_path)
    ctx = dict(bound_context(entry_hash, envelope_hash, bundle.envelope["batch_id"]),
               deployment_id="prod-cluster")
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    with pytest.raises(ContractError) as excinfo:
        decide(bundle, context=ctx, **kwargs)
    assert excinfo.value.code == "approval_context_unbound"
    assert excinfo.value.details["fields"] == ["deployment_id"]
    assert kwargs["store"].rows("approval_decisions") == []


def test_request_id_must_be_bound_to_the_self_certifying_batch(tmp_path):
    """request_id 是自由值(!= 自证 batch_id) —— validate 与 decide 都必须拒,零落库。"""
    repo, commit, ledger, entry_hash = _real_chain(tmp_path)
    envelope, batch_id = envelope_for(commit)
    bundle = _goal_bundle(commit, ledger, envelope, "r-free-value")
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, repo, ledger)
    assert excinfo.value.code == "request_id_unbound"
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    ctx = bound_context(entry_hash, sha256(envelope), batch_id)
    with pytest.raises(ContractError):
        decide(bundle, context=ctx, **kwargs)
    assert kwargs["store"].rows("approval_decisions") == []


def test_happy_path_exposes_envelope_deployment_bound_to_anchored_goal(tmp_path):
    """正例:validate 产出的 deployment_id/protocol_ref/batch_id/request_id 都来自
    已绑定被锚 goal 的自证 envelope,且 decide 能正常签发。"""
    repo, ledger, entry_hash, _, envelope_hash, bundle = world(tmp_path)
    verified = fixture_validate(bundle, repo, ledger)
    assert (verified.deployment_id, verified.protocol_ref) == ("d1", "p1")
    assert verified.batch_id == bundle.envelope["batch_id"]
    assert verified.request_id == bundle.envelope["batch_id"]
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    token = decide(bundle, context=bound_context(entry_hash, envelope_hash,
                                                 bundle.envelope["batch_id"]), **kwargs)
    assert token["deployment_id"] == "d1" and token["scope"] == "batch_approve"
    assert token["batch_id"] == bundle.envelope["batch_id"]


def _fields(bundle: ApprovalRequestBundle) -> list:
    return [bundle.request_id, bundle.goal_bytes_b64, bundle.goal_sha256, bundle.research_commit,
            bundle.artifact_frozen_receipt, bundle.envelope, bundle.envelope_sha256,
            bundle.anchor_prefix_proof]


# --------------------------------------------------------------------------
# F1-deep / F2 / F3: anchored runtime, current authorization, external trust
# --------------------------------------------------------------------------

def test_deployment_and_protocol_must_equal_frozen_anchor(tmp_path):
    repo, commit, ledger, _ = _real_chain(tmp_path)
    envelope, batch_id = envelope_for(commit, deployment_id="another-deployment",
                                      protocol_ref="p1")
    bundle = _goal_bundle(commit, ledger, envelope, batch_id)
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, repo, ledger)
    assert excinfo.value.code == "anchor_deployment_mismatch"


def test_historic_anchor_cannot_be_revived_by_short_prefix(tmp_path):
    repo, ledger, _, commit, _, bundle = world(tmp_path)
    old_proof = bundle.anchor_prefix_proof
    memory = ResearchMemory(ledger)
    memory.append(GOAL_ANCHOR_EVENT, "g1", {
        "goal_sha256": sha256(GOAL_BYTES), "goal_path": GOAL_PATH,
        "research_commit": commit, "receipt_id": "receipt-new",
        "deployment_id": "d1", "protocol_ref": "p1"}, actor_id="ou_owner")
    historic = ApprovalRequestBundle(*[*_fields(bundle)[:-1], old_proof])
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(historic, repo, ledger)
    assert excinfo.value.code == "anchor_not_latest"


def test_revoked_anchor_cannot_be_revived_by_short_prefix(tmp_path):
    repo, ledger, entry_hash, _, _, bundle = world(tmp_path)
    ResearchMemory(ledger).append("goal_anchor_revoked", "g1", {
        "target_entry_hash": entry_hash, "receipt_id": RECEIPT_ID,
    }, actor_id="ou_owner")
    with pytest.raises(ContractError) as excinfo:
        fixture_validate(bundle, repo, ledger)
    assert excinfo.value.code == "anchor_revoked"


def test_production_validation_requires_external_research_memory_seal(tmp_path):
    repo, ledger, _, _, _, bundle = world(tmp_path)
    with pytest.raises(ContractError) as excinfo:
        bundle.validate(research_repo=repo, anchor_ledger=ledger)
    assert excinfo.value.code == "research_memory_seal_required"


def test_human_domain_direct_research_mount_path_is_blocked(tmp_path):
    repo, ledger, entry_hash, _, envelope_hash, bundle = world(tmp_path)
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    kwargs.pop("allow_direct_fixture")
    with pytest.raises(ContractError) as excinfo:
        decide(bundle, context=bound_context(entry_hash, envelope_hash,
                                             bundle.envelope["batch_id"]), **kwargs)
    assert excinfo.value.code == "broker_sealed_approval_bundle_required"


def test_append_after_signed_seal_fails_closed_before_approval(tmp_path):
    repo, ledger, entry_hash, _, envelope_hash, bundle = world(tmp_path)
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    ResearchMemory(ledger).append("human_reflection", "g1", {"text": "later"},
                                  actor_id="ou_owner")
    with pytest.raises(ContractError) as excinfo:
        decide(bundle, context=bound_context(entry_hash, envelope_hash,
                                             bundle.envelope["batch_id"]), **kwargs)
    assert excinfo.value.code == "research_memory_seal_stale"
    assert kwargs["store"].rows("approval_decisions") == []


def test_full_rechain_from_public_genesis_cannot_replace_signed_memory(tmp_path):
    repo, ledger, entry_hash, commit, envelope_hash, bundle = world(tmp_path)
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    ledger.unlink()
    forged = ResearchMemory(ledger)
    forged.append(GOAL_ANCHOR_EVENT, "g1", {
        "goal_sha256": sha256(GOAL_BYTES), "goal_path": GOAL_PATH,
        "research_commit": commit, "receipt_id": RECEIPT_ID,
        "deployment_id": "d1", "protocol_ref": "p1"}, actor_id="ou_owner")
    with pytest.raises(ContractError) as excinfo:
        decide(bundle, context=bound_context(entry_hash, envelope_hash,
                                             bundle.envelope["batch_id"]), **kwargs)
    assert excinfo.value.code == "research_memory_seal_stale"


def test_writable_external_seal_is_outside_trust_boundary(tmp_path):
    repo, ledger, entry_hash, _, envelope_hash, bundle = world(tmp_path)
    kwargs = decide_kwargs(tmp_path, repo, ledger)
    kwargs["anchor_seal_path"].chmod(0o666)
    with pytest.raises(ContractError) as excinfo:
        decide(bundle, context=bound_context(entry_hash, envelope_hash,
                                             bundle.envelope["batch_id"]), **kwargs)
    assert excinfo.value.code == "research_memory_seal_permissions"
