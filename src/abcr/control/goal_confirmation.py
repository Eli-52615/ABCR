"""Crash-recoverable human goal confirmation saga owned by the Operator domain.

The UI transports only a typed confirmation.  This module performs the fixed
mechanical consequences: immutable Git commit, domain-separated artifact receipt,
append-only ResearchMemory anchor, root external-seal refresh and a fenced item-pool
request.  No scientific choice is invented here.
"""
from __future__ import annotations

import json
import base64
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from abcr.control.contracts import (ContractError, canonical_json, require_sha, sha256,
                                    strict_object, utc_now)
from abcr.control.queue_runtime import WorkBrokerClient
from abcr.control.store import ControlStore
from abcr.explore.compiler import (ArtifactFrozenReceipt, freeze_goal,
                                   compile_goal, goal_anchor_payload, prepare_goal_anchor,
                                   sign_frozen_receipt)
from abcr.control.ed25519 import ApprovalRequestBundle
from abcr.explore.goal import Goal
from abcr.explore.item_pool import DevBundleRef
from abcr.explore.memory import ResearchMemory
from abcr.explore.personas import PersonaRegistry

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_GIT_CANDIDATES = ("/opt/homebrew/bin/git", "/usr/local/bin/git", "/usr/bin/git")


def _git_binary() -> str:
    for candidate in _GIT_CANDIDATES:
        path = Path(candidate)
        if path.is_file() and not path.is_symlink() and os.access(path, os.X_OK):
            return candidate
    raise ContractError("git_missing", "目标书定稿需要受信 Git 可执行文件")


def _git(repo: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    proc = subprocess.run(
        [_git_binary(), "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
         "-C", str(repo), *arguments], input=input_bytes, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, shell=False, timeout=30,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_GLOBAL": "/dev/null"},
    )
    if proc.returncode != 0:
        raise ContractError("research_git_failed", "目标书 Git 定稿失败",
                            {"operation": arguments[0] if arguments else "unknown"})
    return proc.stdout


def _require_owned_directory(path: Path, *, owner_uid: int, create: bool = False) -> None:
    if create and not path.exists():
        path.mkdir(mode=0o750, parents=False)
    info = path.lstat()
    if (path.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid
            or stat.S_IMODE(info.st_mode) & 0o022):
        raise ContractError("research_repo_unsafe", "Research repo owner/mode 不安全")


def _write_once(path: Path, raw: bytes, *, group_gid: int) -> None:
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if (path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid() or info.st_gid != group_gid
                or stat.S_IMODE(info.st_mode) != 0o640 or path.read_bytes() != raw):
            raise ContractError("goal_artifact_conflict", "同名目标工件已存在且内容/权限不一致")
        return
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(name)
    try:
        os.write(fd, raw)
        os.fchown(fd, -1, group_gid)
        os.fchmod(fd, 0o640)
        os.fsync(fd)
        os.close(fd); fd = -1
        os.replace(tmp, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        if fd >= 0: os.close(fd)
        tmp.unlink(missing_ok=True)


def commit_goal(repo: Path, goal: Goal, raw: bytes, *, group_gid: int) -> tuple[str, str]:
    """Write exactly two immutable goal files and return their Git commit/path."""
    if _SAFE_SEGMENT.fullmatch(goal.goal_id) is None:
        raise ContractError("goal_path_unsafe", "goal_id 不能安全映射到仓内路径")
    repo = Path(repo)
    _require_owned_directory(repo.parent, owner_uid=os.geteuid())
    if not repo.exists():
        _require_owned_directory(repo, owner_uid=os.geteuid(), create=True)
        _git(repo, "init", "--quiet")
    _require_owned_directory(repo, owner_uid=os.geteuid())
    git_dir = repo / ".git"
    _require_owned_directory(git_dir, owner_uid=os.geteuid())

    relative = f"goals/{goal.goal_id}/goal.yaml"
    normalized_relative = f"goals/{goal.goal_id}/normalized.json"
    goal_dir = repo / "goals" / goal.goal_id
    goals_dir = repo / "goals"
    if not goal_dir.exists():
        goals_dir.mkdir(mode=0o750, exist_ok=True)
        goal_dir.mkdir(mode=0o750)
        os.chown(goals_dir, -1, group_gid)
        os.chown(goal_dir, -1, group_gid)
    _require_owned_directory(goals_dir, owner_uid=os.geteuid())
    _require_owned_directory(goal_dir, owner_uid=os.geteuid())
    _write_once(repo / relative, raw, group_gid=group_gid)
    _write_once(repo / normalized_relative, canonical_json(goal.as_dict()) + b"\n",
                group_gid=group_gid)

    try:
        head = _git(repo, "rev-parse", "--verify", "HEAD").decode().strip()
        existing = _git(repo, "show", f"{head}:{relative}")
        normalized = _git(repo, "show", f"{head}:{normalized_relative}")
        if existing == raw and normalized == canonical_json(goal.as_dict()) + b"\n":
            return head, relative
    except ContractError:
        pass

    _git(repo, "add", "--", relative, normalized_relative)
    _git(repo, "-c", "user.name=ABCR Operator", "-c", "user.email=abcr-operator@localhost",
         "commit", "--quiet", "--no-gpg-sign", "--only", "-m",
         f"freeze goal {goal.goal_id}", "--", relative, normalized_relative)
    commit = _git(repo, "rev-parse", "--verify", "HEAD").decode().strip()
    if (len(commit) not in {40, 64}
            or any(ch not in "0123456789abcdef" for ch in commit)
            or _git(repo, "show", f"{commit}:{relative}") != raw
            or _git(repo, "show", f"{commit}:{normalized_relative}")
            != canonical_json(goal.as_dict()) + b"\n"):
        raise ContractError("research_commit_unverified", "目标书 commit 无法逐字复验")
    return commit, relative


def _receipt_from_dict(value: Any) -> ArtifactFrozenReceipt:
    obj = strict_object(value, required={"receipt_id", "goal_hash", "research_commit",
                                        "recorded_at", "sealed"})
    if not isinstance(obj["sealed"], dict):
        raise ContractError("freeze_receipt_unsigned", "artifact receipt 缺少签名")
    return ArtifactFrozenReceipt(**obj)


def _prepared_receipt(store: ControlStore, *, effect_id: str, goal: Goal,
                      research_commit: str, private_key: Path,
                      public_key: Path) -> ArtifactFrozenReceipt:
    event_id = sha256({"effect_id": effect_id, "stage": "artifact-frozen-prepared"})
    existing = store.research_event(event_id)
    if existing is not None:
        payload = json.loads(existing["payload_json"])
        if (existing["event_type"] != "artifact_frozen_prepared"
                or existing["subject_id"] != goal.goal_id
                or payload.get("effect_id") != effect_id):
            raise ContractError("freeze_receipt_conflict", "prepared receipt effect 冲突")
        return _receipt_from_dict(payload.get("receipt"))
    receipt = ArtifactFrozenReceipt(
        "AFR-" + sha256({"effect_id": effect_id, "goal_hash": goal.goal_hash,
                         "research_commit": research_commit})[:32],
        goal.goal_hash, research_commit, utc_now())
    signed = sign_frozen_receipt(receipt, private_key=private_key, public_key=public_key)
    store.append_research_event(
        "artifact_frozen_prepared", goal.goal_id,
        {"effect_id": effect_id, "receipt": asdict(signed)}, event_id=event_id)
    return signed


def _append_anchor(memory: ResearchMemory, *, goal: Goal, anchor: Any,
                   group_gid: int) -> dict[str, Any]:
    payload = goal_anchor_payload(anchor)
    matches = [row for row in memory.verify()
               if row["event_type"] == "goal_anchor_frozen"
               and row["subject_id"] == goal.goal_id]
    if matches:
        if len(matches) != 1 or matches[0]["payload"] != payload:
            raise ContractError("goal_anchor_conflict", "该 goal 已存在不同冻结锚")
        return matches[0]
    row = memory.append("goal_anchor_frozen", goal.goal_id, payload,
                        actor_id=anchor.candidate.confirmed_by)
    os.chown(memory.path, -1, group_gid)
    os.chmod(memory.path, 0o640)
    return row


def confirm_goal(*, store: ControlStore, broker: WorkBrokerClient, effect_id: str,
                 proposal: dict[str, Any], goal: Goal, deployment_id: str,
                 protocol_ref: str, research_repo: Path, research_memory_path: Path,
                 research_group_gid: int, artifact_receipt_private_key: Path,
                 artifact_receipt_public_key: Path) -> dict[str, Any]:
    """Advance confirmation through all durable gates; every replay is identical."""
    raw = proposal["raw_text"].encode("utf-8")
    if sha256(raw) != proposal["raw_hash"]:
        raise ContractError("proposal_bytes_drift", "提案原始字节与入库 hash 不一致")
    commit, relative = commit_goal(research_repo, goal, raw, group_gid=research_group_gid)
    candidate = prepare_goal_anchor(
        goal, research_commit=commit, relative_path=relative,
        confirmed_by=proposal["actor_id"], deployment_id=deployment_id,
        protocol_ref=protocol_ref)
    receipt = _prepared_receipt(
        store, effect_id=effect_id, goal=goal, research_commit=commit,
        private_key=artifact_receipt_private_key,
        public_key=artifact_receipt_public_key)
    anchor = freeze_goal(candidate, receipt, receipt_public_key=artifact_receipt_public_key)
    memory = ResearchMemory(research_memory_path, owner_uid=os.geteuid())
    row = _append_anchor(memory, goal=goal, anchor=anchor, group_gid=research_group_gid)
    seal_core = memory.seal_core()
    seal = broker.request("seal_research_memory", {
        "nonce": "RM-" + effect_id[:32], "expected_length": seal_core["length"],
        "expected_head_entry_hash": seal_core["head_entry_hash"],
        "expected_ledger_sha256": seal_core["ledger_sha256"],
    })
    if (not isinstance(seal, dict) or seal.get("length") != seal_core["length"]
            or seal.get("head_entry_hash") != row["entry_hash"]
            or seal.get("ledger_sha256") != seal_core["ledger_sha256"]
            or not isinstance(seal.get("receipt_id"), str)):
        raise ContractError("research_seal_mismatch", "外部 ResearchMemory seal 回执不匹配")

    if proposal["state"] == "validated":
        if not store.set_proposal_state(proposal["proposal_id"], "validated", "human_confirmed"):
            raise ContractError("proposal_state_race", "提案确认状态发生并发变化")
    elif proposal["state"] != "human_confirmed":
        raise ContractError("proposal_state_invalid", "提案不在可确认状态")

    work_id = "itempool-" + sha256({"effect_id": effect_id, "goal": goal.goal_hash})[:32]
    broker.request("work_enqueue", {
        "stage": "itempool", "work_id": work_id, "attempt": 1, "fencing_token": 1,
        "producer": "abcr-operator",
        "payload": {"request_id": "SEL-" + effect_id[:24], "goal_hash": goal.goal_hash,
                    "count": goal.item_count, "seed": goal.seeds[0],
                    "excluded_item_ids": [], "request_created_at": receipt.recorded_at},
    })
    return {"code": "goal_confirmed_and_itempool_queued", "goal_id": goal.goal_id,
            "research_commit": commit, "goal_anchor_entry_hash": row["entry_hash"],
            "research_seal_receipt_id": seal["receipt_id"], "itempool_work_id": work_id}


def _bundle_wire(bundle: ApprovalRequestBundle) -> dict[str, Any]:
    value = asdict(bundle)
    value["anchor_prefix_proof"] = list(bundle.anchor_prefix_proof)
    return value


def reconcile_itempool_results(*, store: ControlStore, broker: WorkBrokerClient,
                               research_memory_path: Path, research_repo: Path,
                               persona_root: Path, trusted_dev_bundle_root: Path,
                               bundle_sealer_public_key: Path, deployment_id: str,
                               protocol_ref: str,
                               artifact_receipt_public_key: Path,
                               execution_profile: dict[str, Any] | None = None) -> int:
    """Compile sealed item-pool results and enqueue independent approval validation."""
    completed = set(broker.completed("itempool"))
    if not completed:
        return 0
    count = 0
    memory = ResearchMemory(research_memory_path, owner_uid=os.geteuid())
    rows = memory.verify()
    prepared = [row for row in store.rows("research_events")
                if row["event_type"] == "artifact_frozen_prepared"]
    for event in prepared:
        payload = json.loads(event["payload_json"])
        effect_id = payload.get("effect_id")
        if not isinstance(effect_id, str):
            continue
        receipt = _receipt_from_dict(payload.get("receipt"))
        work_id = "itempool-" + sha256({"effect_id": effect_id,
                                         "goal": receipt.goal_hash})[:32]
        if work_id not in completed:
            continue
        compiled_event_id = sha256({"work_id": work_id, "stage": "compiled"})
        prior = store.research_event(compiled_event_id)
        result_envelope = broker.read_result("itempool", work_id)
        result_hash = result_envelope["result_hash"]
        if prior is not None:
            broker.acknowledge("itempool", work_id, result_hash=result_hash)
            continue
        outer = strict_object(result_envelope["result"], required={"ok"},
                              optional={"result", "error_code"})
        if outer["ok"] is not True or not isinstance(outer.get("result"), dict):
            raise ContractError("itempool_result_failed",
                                str(outer.get("error_code", "itempool_failed")))
        result = strict_object(
            outer["result"],
            required={"bundle_id", "manifest_hash", "item_ids", "source_hash",
                      "split", "selected_bytes_hash", "seal_receipt_id",
                      "sealed_tree_hash"})
        if result["split"] != "dev":
            raise ContractError("itempool_result_split_invalid",
                                "itempool result 必须由签名 DevBundle 绑定 split=dev")
        for field in ("bundle_id", "manifest_hash", "source_hash",
                      "selected_bytes_hash", "seal_receipt_id", "sealed_tree_hash"):
            require_sha(result[field], f"itempool_result.{field}")
        proposal_rows = [p for p in store.rows("proposals")
                         if p["raw_hash"] and p["state"] == "human_confirmed"]
        matching: list[tuple[dict[str, Any], Goal]] = []
        for proposal in proposal_rows:
            from abcr.explore.goal import validate_goal
            report = validate_goal(proposal["raw_text"].encode("utf-8"))
            if report.ok and report.goal is not None and report.goal.goal_hash == receipt.goal_hash:
                matching.append((proposal, report.goal))
        if len(matching) != 1:
            raise ContractError("confirmed_goal_ambiguous", "itempool result 无法唯一关联已确认目标")
        proposal, goal = matching[0]
        anchor_rows = [row for row in rows if row["event_type"] == "goal_anchor_frozen"
                       and row["subject_id"] == goal.goal_id
                       and row["payload"].get("receipt_id") == receipt.receipt_id]
        if len(anchor_rows) != 1:
            raise ContractError("goal_anchor_missing", "已确认目标的 ResearchMemory anchor 缺失")
        candidate = prepare_goal_anchor(
            goal, research_commit=receipt.research_commit,
            relative_path=anchor_rows[0]["payload"]["goal_path"],
            confirmed_by=proposal["actor_id"], deployment_id=deployment_id,
            protocol_ref=protocol_ref)
        anchor = freeze_goal(candidate, receipt,
                             receipt_public_key=artifact_receipt_public_key)
        if (not isinstance(result["item_ids"], list)
                or not all(isinstance(item, str) and item for item in result["item_ids"])):
            raise ContractError("itempool_result_invalid", "item IDs 非法")
        dev_bundle = DevBundleRef(
            result["bundle_id"], Path(trusted_dev_bundle_root) / result["bundle_id"],
            result["manifest_hash"], tuple(result["item_ids"]), result["source_hash"])
        personas = PersonaRegistry()
        personas.load_dir(persona_root)
        compiled = compile_goal(
            goal, anchor, dev_bundle, personas, protocol_ref=protocol_ref,
            trusted_dev_bundle_root=trusted_dev_bundle_root,
            bundle_sealer_public_key=bundle_sealer_public_key,
            deployment_id=deployment_id, created_at=receipt.recorded_at,
            execution_profile=execution_profile,
            selection_receipt={field: result[field] for field in (
                "bundle_id", "manifest_hash", "item_ids", "source_hash", "split",
                "selected_bytes_hash", "seal_receipt_id", "sealed_tree_hash")})
        prefix: list[str] = []
        for row in rows:
            prefix.append(row["entry_hash"])
            if row["entry_hash"] == anchor_rows[0]["entry_hash"]:
                break
        if not prefix or prefix[-1] != anchor_rows[0]["entry_hash"]:
            raise ContractError("goal_anchor_prefix_missing", "目标冻结锚不在可信 ledger prefix")
        approval = ApprovalRequestBundle(
            compiled.batch_id, base64.b64encode(proposal["raw_text"].encode("utf-8")).decode(),
            goal.goal_hash, receipt.research_commit, asdict(receipt), compiled.envelope,
            compiled.envelope_hash, tuple(prefix))
        audit_work_id = "approval-" + compiled.batch_id.removeprefix("EXP-")
        broker.request("work_enqueue", {
            "stage": "audit", "work_id": audit_work_id, "attempt": 1,
            "fencing_token": 1, "producer": "abcr-operator",
            "payload": {"kind": "approval_validation", "bundle": _bundle_wire(approval)},
        })
        store.append_research_event(
            "compile_envelope_ready", goal.goal_id,
            {"proposal_id": proposal["proposal_id"], "batch_id": compiled.batch_id,
             "envelope": compiled.envelope, "envelope_sha256": compiled.envelope_hash,
             "approval_bundle": _bundle_wire(approval),
             "approval_work_id": audit_work_id, "itempool_work_id": work_id},
            event_id=compiled_event_id)
        if not store.set_proposal_state(proposal["proposal_id"], "human_confirmed", "compiled"):
            raise ContractError("proposal_state_race", "编译完成时 proposal 状态漂移")
        broker.acknowledge("itempool", work_id, result_hash=result_hash)
        count += 1
    return count


def reconcile_approval_results(*, store: ControlStore, broker: WorkBrokerClient,
                               bridge: Any) -> int:
    """Publish broker-sealed validator references to Human and ack only afterwards.

    The validator document intentionally never crosses the bridge.  Human re-opens
    the root-owned object from the three opaque broker bindings and verifies it.
    """
    completed = set(broker.completed("audit"))
    if not completed:
        return 0
    count = 0
    for event in store.rows("research_events"):
        if event["event_type"] != "compile_envelope_ready":
            continue
        payload = json.loads(event["payload_json"])
        work_id = payload.get("approval_work_id")
        bundle = payload.get("approval_bundle")
        if not isinstance(work_id, str) or work_id not in completed or not isinstance(bundle, dict):
            continue
        result_envelope = broker.read_result("audit", work_id)
        result_hash = result_envelope["result_hash"]
        exported_id = sha256({"work_id": work_id, "stage": "approval-request-exported"})
        prior = store.research_event(exported_id)
        if prior is not None:
            broker.acknowledge("audit", work_id, result_hash=result_hash)
            continue
        outer = strict_object(result_envelope["result"], required={"ok"},
                              optional={"result", "error_code"})
        if outer["ok"] is not True or not isinstance(outer.get("result"), dict):
            raise ContractError("approval_validation_failed",
                                str(outer.get("error_code", "approval_validation_failed")))
        result = strict_object(
            outer["result"],
            required={"document", "broker_receipt_id", "broker_object_id",
                      "sealed_tree_hash"})
        # The document is deliberately ignored here; the root broker already
        # validated it and Human independently re-opens the sealed bytes.
        if not isinstance(result["document"], dict):
            raise ContractError("approval_validation_result_invalid",
                                "auditor validator result 类型不合法")
        reference = {field: result[field] for field in (
            "broker_receipt_id", "broker_object_id", "sealed_tree_hash")}
        for field, value in reference.items():
            if not isinstance(value, str) or len(value) != 64 or any(
                    ch not in "0123456789abcdef" for ch in value):
                raise ContractError("approval_validation_result_invalid",
                                    f"{field} 不合法")
        bridge.export_approval_request(store, bundle=bundle, reference=reference,
                                       request_version=1)
        store.append_research_event(
            "approval_request_exported", payload["batch_id"],
            {"approval_work_id": work_id, "request_id": bundle.get("request_id"),
             "request_version": 1, **reference}, event_id=exported_id)
        broker.acknowledge("audit", work_id, result_hash=result_hash)
        count += 1
    return count
