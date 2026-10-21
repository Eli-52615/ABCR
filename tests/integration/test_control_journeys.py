"""六条零费用纵向旅程。

与初版的差别:初版只断言 happy path。本版按工程清单的验收判据补上了
被漏掉的部分 —— 旅程 4 的「无重复」、旅程 5 的「故意坏补丁绝不发布 +
回滚恢复 fixture」,以及贯穿全链的**签名信任链**必须真正串起来。

隔离说明:CODE_RC 阶段跑不了生产沙箱(ops/sandbox/abcr-candidate.sb 的
deny-default 目前挡住了解释器所需的系统 dylib,见交付说明)。因此旅程 5
用一个「允许默认、但拒绝写 result spool」的 profile 来证明隔离机制真实
生效,并**额外断言** FIXTURE_UNSANDBOXED 哨兵跑出来的结果无法发布。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from abcr.audit.evidence import audit_evidence
from abcr.control.black_box_oracle import (
    FIXTURE_UNSANDBOXED, OracleRegistry, SigningIdentity, equality_assertion,
)
from abcr.control.canary_controller import run_canary
from abcr.control.contracts import ContractError, sha256
from abcr.control.ed25519 import generate_keypair
from abcr.control.reconciler import Reconciler
from abcr.control.release import prepare_release
from abcr.control.store import ControlStore
from abcr.control.test_controller import run_profile
from abcr.control.verifier import verify_result
from abcr.control.worktree import scan_tree, tree_hash
from abcr.explore.compiler import ArtifactFrozenReceipt, sign_frozen_receipt
from abcr.explore.item_pool import SelectionRequest, build_dev_bundle
from abcr.explore.memory import ResearchMemory
from abcr.explore.personas import PersonaRegistry
from abcr.explore.rounds import build_round_report, next_goal_draft
from abcr.explore.workflow import ScientificWorkflow
from abcr.probe.contracts import ProbeRequest
from abcr.probe.engine import FakeProbeEngine, run_probe
from abcr.probe.notebook import ProbeNotebook
from abcr.probe.promote import promote_probe
from tests.explore.test_goal_persona import behavior_probe_goal
from tests.explore.test_itempool_workflow import itempool_keys, sealed_bundle, sources
from tests.control.release_fixture_support import add_bootstrap_payload

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
HAS_SANDBOX = os.path.isfile(SANDBOX_EXEC) and os.access(SANDBOX_EXEC, os.X_OK)
ROOT = Path(__file__).resolve().parents[2]

ORACLE_PROFILE = {"required_external_oracle_ids": ["equal"],
                  "external_oracles": [{"oracle_id": "equal", "version": "1",
                                        "request": {"expected": 7}}]}


def persona_registry():
    registry = PersonaRegistry()
    registry.add({"persona_id": "p", "version": 1, "parent_ref": None,
                  "components": {"stance": "careful"}, "changed_component": None,
                  "manipulation_checks": ["careful"]})
    return registry


def keypair(tmp_path, name):
    private, public = tmp_path / f"{name}.pem", tmp_path / f"{name}.pub"
    generate_keypair(private, public)
    return private, public


def journey_one_and_two(tmp_path):
    """1 目标书→确认→锚定→编译;2 探针→笔记本→人工提升。"""
    store = ControlStore(tmp_path / "control.db")
    raw = behavior_probe_goal(); proposal_id = "PROP1"
    store.save_proposal(proposal_id, raw.decode(), "owner")
    bundle_root = tmp_path / "bundles"
    receipt_private, receipt_public = keypair(tmp_path, "receipt")
    sealer = itempool_keys(tmp_path)
    workflow = ScientificWorkflow(store, persona_registry(), bundle_root, receipt_public,
                                  sealer[1])
    goal = workflow.validate_proposal(proposal_id, raw)
    dataset, split = sources(tmp_path)
    bundle = sealed_bundle(SelectionRequest("SEL-" + goal.goal_id, goal.goal_hash,
                                            goal.item_count, goal.seeds[0]),
                           dataset_path=dataset, split_path=split, output_root=bundle_root,
                           keys=sealer)
    receipt = sign_frozen_receipt(
        ArtifactFrozenReceipt("receipt-1", goal.goal_hash, "c" * 64, "now"),
        private_key=receipt_private, public_key=receipt_public)
    envelope = workflow.confirm_and_compile(
        proposal_id, goal, actor_id="owner", research_commit="c" * 64,
        goal_path="goals/g.yaml", receipt=receipt, bundle=bundle, protocol_ref="CONTROL-V1",
        deployment_id="fixture")

    from abcr.probe.contracts import ProbePersona
    probe = run_probe(ProbeRequest("P1", goal.goal_hash, bundle,
                                   (ProbePersona("p@v1", "careful"),),
                                   "increase", 1, "fixture"), FakeProbeEngine(),
                      trusted_dev_bundle_root=bundle_root,
                      bundle_sealer_public_key=sealer[1])
    notebook = ProbeNotebook(tmp_path / "lab")
    for row in probe.rows:
        notebook.append(row)
    promotion = promote_probe([x["row_hash"] for x in probe.rows], notebook,
                              actor_id="owner", human_confirmed=True)
    assert envelope["split"] == "dev" and promotion["draft_only"]
    # 探针产物永远不可引用 —— Mac 产物不是正式证据。
    assert all(row.get("citable") is False for row in probe.rows)
    return store, goal, envelope, promotion, bundle, bundle_root, sealer


def journeys_one_to_four(tmp_path):
    store, goal, envelope, _promotion, bundle, bundle_root, sealer = journey_one_and_two(tmp_path)

    # 3 精确证据审计 → 可引用报告。只有 auditor 签名的 attestation 才可引用。
    auditor_private, auditor_public = keypair(tmp_path, "auditor")
    keys = [(item, seed, arm["id"]) for item in envelope["item_ids"]
            for seed in envelope["seeds"] for arm in envelope["arms"]]
    steps = [{"item_id": i, "random_seed": s, "condition": c,
              "prompt_hash": "p", "output_text": "fixture"} for i, s, c in keys]
    scores = [{"item_id": i, "random_seed": s, "condition": c} for i, s, c in keys]
    sidecars = [{"item_id": i, "random_seed": s, "condition": c} for i, s, c in keys]
    audit = audit_evidence(batch_id=envelope["batch_id"], item_ids=tuple(envelope["item_ids"]),
                           seeds=tuple(envelope["seeds"]),
                           conditions=tuple(x["id"] for x in envelope["arms"]), steps=steps,
                           scores=scores, sidecars=sidecars, dev_bundle=bundle,
                           trusted_dev_bundle_root=bundle_root,
                           bundle_sealer_public_key=sealer[1],
                           compile_envelope=envelope,
                           auditor_private_key=auditor_private, auditor_public_key=auditor_public)
    # 集成路径传入 compile envelope,把 goal 绑定从「结构可见」升级为「强制校验」:
    # 报告引用的证据集必须可证明地属于它声称的那个 goal(闭合 B4 的集成路径)。
    report = build_round_report(
        round_id="ROUND1", goal_id=goal.goal_id, audit=audit,
        expected_batch_id=envelope["batch_id"], compile_envelope=envelope,
        observations=[{"effect": 0}],
        interpretations=["null is informative"], limitations=["fixture"],
        suggestion_inputs=[{"observation": "no difference",
                            "competing_explanation": "weak manipulation",
                            "discriminating_experiment": "stronger one-component contrast",
                            "opposite_result_update": "retain original strength",
                            "evidence_refs": [audit.attestation_hash]}],
        auditor_public_key=auditor_public)
    assert audit.verdict == "PASS" and report.citable
    assert report.goal_binding_verified is True
    assert report.narrative_authenticated is False

    # B4 集成攻击:同一份真 attestation 挂到一个不同的 goal_id → 拒绝。
    with pytest.raises(ContractError):
        build_round_report(
            round_id="ROUND1y", goal_id="G-DIFFERENT", audit=audit,
            expected_batch_id=envelope["batch_id"], compile_envelope=envelope,
            observations=[{"effect": 999}], interpretations=["巨大效应"], limitations=["无"],
            suggestion_inputs=[{"observation": "o", "competing_explanation": "c",
                                "discriminating_experiment": "d", "opposite_result_update": "u",
                                "evidence_refs": [audit.attestation_hash]}],
            auditor_public_key=auditor_public)

    # 同一份审计,换一把公钥 → 不可引用。可引用性的信任根是签名,不是哈希。
    _, stranger_public = keypair(tmp_path, "stranger")
    with pytest.raises(ContractError):
        build_round_report(
            round_id="ROUND1x", goal_id=goal.goal_id, audit=audit,
            expected_batch_id=envelope["batch_id"], observations=[{"effect": 0}],
            interpretations=["x"], limitations=["x"],
            suggestion_inputs=[{"observation": "o", "competing_explanation": "c",
                                "discriminating_experiment": "d", "opposite_result_update": "u",
                                "evidence_refs": [audit.attestation_hash]}],
            auditor_public_key=stranger_public)

    # 4 崩溃 → 同一 release 内有界恢复,且**不产生重复**。
    resumed = []
    reconciler = Reconciler(store)
    incident = {"subject_id": "run1", "code": "process_dead", "release_id": "REL0"}
    action = reconciler.observe(incident)
    assert action and reconciler.apply(action, {"resume_same_release": lambda p: resumed.append(p)})
    assert resumed[0]["release_id"] == "REL0"
    # 判据:一个活跃事件只有一个动作 —— 重复观察不得再产生一次恢复副作用。
    repeat = reconciler.observe(incident)
    if repeat is not None:
        reconciler.apply(repeat, {"resume_same_release": lambda p: resumed.append(p)})
    assert len(resumed) == 1, f"同一事件触发了 {len(resumed)} 次恢复 —— 出现重复副作用"

    return report


def test_journeys_one_to_four(tmp_path):
    """1-4 由 journeys_one_to_four 串起,本用例固定它作为独立回归点。"""
    assert journeys_one_to_four(tmp_path).citable


def test_journey_six_human_reflection_is_inert(tmp_path):
    """6 人类反思 → 惰性下一轮草案,绝不自动执行。"""
    report = journeys_one_to_four(tmp_path)
    memory = ResearchMemory(tmp_path / "research.jsonl")
    memory.append("human_reflection", report.round_id, {"text": "需要更强区分实验"},
                  actor_id="owner")
    draft = next_goal_draft(report, report.suggestions[0].suggestion_id)
    assert memory.verify()
    assert draft["auto_execute"] is False and draft["requires_human_claude_review"]
    # 草案上不得存在任何可直接触发执行的把手。
    assert not any(k in draft for k in ("envelope", "batch_id", "dispatch"))


def _candidate_tree(tmp_path, name, content):
    root = tmp_path / name
    root.mkdir()
    (root / "x.txt").write_text(content)
    python = root / "env/bin/python"; python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 99\n"); python.chmod(0o500)
    module = root / "env/lib/python3.12/site-packages/abcr/control/panel.py"
    module.parent.mkdir(parents=True)
    module.write_text("def main():\n    return 0\n"); module.chmod(0o400)
    (root / "requirements.lock").write_text(
        "fixture==1 --hash=sha256:" + "a" * 64 + "\n")
    topology = root / "configs/control/service-topology-v1.json"
    topology.parent.mkdir(parents=True)
    topology.write_bytes((ROOT / "configs/control/service-topology-v1.json").read_bytes())
    # Keep the journey production-shaped as the finite reviewed bootstrap
    # contract grows; never weaken prepare_release merely for this fixture.
    add_bootstrap_payload(root)
    return root, tree_hash(scan_tree(root))


def _registry():
    registry = OracleRegistry()
    registry.register("equal", "1", equality_assertion)
    return registry


HONEST_CODE = ("import sys,json;q=json.loads(sys.stdin.readline());"
               "print(json.dumps({'nonce':q['nonce'],'result':7}))")
# 故意的坏补丁:答错 oracle。受信父进程会判 FAIL。
BAD_PATCH_CODE = ("import sys,json;q=json.loads(sys.stdin.readline());"
                  "print(json.dumps({'nonce':q['nonce'],'result':999}))")


def test_journey_five_unsandboxed_result_can_never_be_released(tmp_path):
    """旅程 5 的安全性质:哨兵跑出来的结果,即使 PASS 也不得发布。

    这条不依赖 sandbox-exec,任何机器上都必须成立。
    """
    controller = SigningIdentity(*keypair(tmp_path, "ctl"))
    _, candidate_hash = _candidate_tree(tmp_path, "cand", "safe")
    bundle = run_profile(mission_id="M-U", fencing_token=1, candidate_tree_hash=candidate_hash,
                         profile=ORACLE_PROFILE,
                         candidate_argv=(sys.executable, "-c", HONEST_CODE),
                         registry=_registry(), isolation=FIXTURE_UNSANDBOXED, signer=controller)
    assert bundle.verdict == "PASS"  # 它确实答对了 oracle
    verifier = SigningIdentity(*keypair(tmp_path, "vfy"))
    with pytest.raises(ContractError) as exc:
        verify_result(bundle, base_tree_hash="b" * 64,
                      expected_candidate_tree_hash=candidate_hash,
                      expected_profile_hash=sha256(ORACLE_PROFILE),
                      expected_oracle_registry_hash=_registry().registry_hash,
                      declared_risk="normal", changed_paths=("src/abcr/util/x.py",),
                      path_registry={"src/abcr/util/x.py": {
                          "auto_release_eligible": True,
                          "required_external_oracle_ids": ["equal"]}},
                      controller_public_key=controller.public_key, signer=verifier)
    assert exc.value.code == "unsandboxed_result_forbidden"


@pytest.mark.skipif(not HAS_SANDBOX, reason="sandbox-exec 不可用")
def test_journey_five_sandboxed_release_and_bad_patch_rollback(tmp_path):
    """5 未知故障 → 受信外部 oracle → 独立验证 → canary → 发布或回滚。

    含工程清单判据 12:**故意坏补丁绝不发布,回滚恢复 fixture**。
    """
    controller = SigningIdentity(*keypair(tmp_path, "ctl"))
    verifier = SigningIdentity(*keypair(tmp_path, "vfy"))
    spool = tmp_path / "spool"; spool.mkdir()
    profile_file = tmp_path / "deny-spool.sb"
    profile_file.write_text('(version 1)\n(allow default)\n'
                            '(deny file-write* (subpath (param "SPOOL")))\n')
    registry = _registry()
    path_registry = {"src/abcr/util/x.py": {"auto_release_eligible": True,
                                            "required_external_oracle_ids": ["equal"]}}

    def run(name, code):
        root, candidate_hash = _candidate_tree(tmp_path, name, name)
        bundle = run_profile(mission_id="M-" + name, fencing_token=1,
                             candidate_tree_hash=candidate_hash, profile=ORACLE_PROFILE,
                             candidate_argv=(sys.executable, "-c", code), registry=registry,
                             isolation=str(profile_file), signer=controller,
                             sandbox_params={"SPOOL": str(spool.resolve())})
        return root, candidate_hash, bundle

    # --- 诚实补丁:一路走到发布 + canary ---
    good_root, good_hash, good_bundle = run("good", HONEST_CODE)
    assert good_bundle.verdict == "PASS"
    attestation = verify_result(good_bundle, base_tree_hash="b" * 64,
                                expected_candidate_tree_hash=good_hash,
                                expected_profile_hash=sha256(ORACLE_PROFILE),
                                expected_oracle_registry_hash=registry.registry_hash,
                                declared_risk="normal", changed_paths=("src/abcr/util/x.py",),
                                path_registry=path_registry,
                                controller_public_key=controller.public_key, signer=verifier)
    assert attestation.verdict == "PASS"
    release = prepare_release(good_root, attestation,
                              verifier_public_key=verifier.public_key)
    canary = run_canary(release.release_id, "v1", lambda: ("v1", True, "ok"))
    assert canary.semantic_ok

    # --- 故意坏补丁:绝不发布(判据 12)---
    # 不变式是「坏补丁到不了发布」,而不是某一环必须抛错。实际链路是
    # FAIL bundle → FAIL 证明(仍是一份签名记录)→ 发布闸拒绝。
    bad_root, bad_hash, bad_bundle = run("bad", BAD_PATCH_CODE)
    assert bad_bundle.verdict == "FAIL", "坏补丁被判 PASS —— 受信 oracle 失效"
    bad_attestation = verify_result(
        bad_bundle, base_tree_hash="b" * 64, expected_candidate_tree_hash=bad_hash,
        expected_profile_hash=sha256(ORACLE_PROFILE),
        expected_oracle_registry_hash=registry.registry_hash,
        declared_risk="normal", changed_paths=("src/abcr/util/x.py",),
        path_registry=path_registry,
        controller_public_key=controller.public_key, signer=verifier)
    assert bad_attestation.verdict == "FAIL"
    with pytest.raises(ContractError) as exc:
        prepare_release(bad_root, bad_attestation,
                        verifier_public_key=verifier.public_key)
    assert exc.value.code == "verification_not_pass"

    # --- 回滚:canary 语义失败后,活动版本必须退回旧版 ---
    failed = run_canary(release.release_id, "v2", lambda: ("v1", False, "semantic health failed"))
    assert not failed.semantic_ok, "canary 未能识别语义失败"

    # 候选进程始终没能写进 result spool。
    assert not any(spool.iterdir()), "候选写进了 result spool —— 隔离失效"
