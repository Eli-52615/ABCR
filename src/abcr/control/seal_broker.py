"""Finite-operation sealing broker core (transport/peer-credential wrapper is external)."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import signal
import socket
import stat
import struct
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from abcr.control.contracts import ContractError, canonical_json, strict_object, sha256, utc_now
from abcr.control.work_spool import Claim, STAGES, WORK_ID, WorkSpool
from abcr.control.research_memory_seal import (OPERATION as RESEARCH_MEMORY_SEAL_OPERATION,
                                               ResearchMemorySealConfig,
                                               refresh_research_memory_seal)
from abcr.control.worktree import scan_tree, tree_hash
from abcr.control.validated_approval_bundle import broker_verify_candidate
from abcr.control.release_policy import enforce_release_content_policy

SEAL_OPS = frozenset({"seal_dev_bundle", "seal_test_result", "seal_verification",
                      "seal_canary", "seal_release", "seal_approval_bundle",
                      "seal_audit_result", "seal_attestation"})
WORK_OPS = frozenset({"work_enqueue", "work_list", "work_claim", "work_heartbeat",
                      "work_result", "work_result_list", "work_result_read", "work_ack"})
OPS = SEAL_OPS | WORK_OPS | frozenset({"activate_release", "restart_generation",
                                       RESEARCH_MEMORY_SEAL_OPERATION})


def _strict_json(raw: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out: raise ValueError("duplicate key")
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def _darwin_processes(expected_uid: int, expected_executable: Path) -> list[int]:
    """Return PIDs whose kernel-reported euid and executable both match exactly."""
    if sys.platform != "darwin":
        return []
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    list_all = library.proc_listallpids
    list_all.argtypes = [ctypes.c_void_p, ctypes.c_int]
    list_all.restype = ctypes.c_int
    pid_info = library.proc_pidinfo
    pid_info.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                         ctypes.c_void_p, ctypes.c_int]
    pid_info.restype = ctypes.c_int
    pid_path = library.proc_pidpath
    pid_path.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    pid_path.restype = ctypes.c_int
    capacity = max(64, list_all(None, 0) + 64)
    pids = (ctypes.c_int * capacity)()
    count = list_all(pids, ctypes.sizeof(pids))
    if count < 0 or count > capacity:
        raise ContractError("process_registry_unavailable", "无法枚举 service PID")
    found: list[int] = []
    for pid in pids[:count]:
        if pid <= 1:
            continue
        # proc_bsdinfo starts with flags,status,xstatus,pid,ppid,uid; uid is
        # therefore the sixth native uint32 at byte offset 20.
        bsd = ctypes.create_string_buffer(256)
        if pid_info(pid, 3, 0, bsd, ctypes.sizeof(bsd)) < 24:
            continue
        observed_uid = struct.unpack_from("=I", bsd.raw, 20)[0]
        if observed_uid != expected_uid:
            continue
        path_buffer = ctypes.create_string_buffer(4096)
        if pid_path(pid, path_buffer, ctypes.sizeof(path_buffer)) <= 0:
            continue
        try:
            observed = Path(os.fsdecode(path_buffer.value)).resolve()
        except (OSError, ValueError):
            continue
        if observed == expected_executable:
            found.append(int(pid))
    return found


class SealBroker:
    def __init__(self, operation_roots: dict[str, Path], receipt_root: Path, *,
                 source_roots: dict[str, Path], active_path: Path | None = None,
                 operation_policies: dict[str, dict[str, int]] | None = None,
                 authority_uid: int | None = None,
                 receipt_owner_uid: int | None = None,
                 receipt_group_gid: int | None = None):
        unknown = set(operation_roots) - OPS
        if unknown: raise ValueError(f"unknown broker operations: {unknown}")
        self.operation_roots = {k: Path(v).resolve() for k, v in operation_roots.items()}
        self.source_roots = {k: Path(v).resolve() for k, v in source_roots.items()}
        seal_ops = set(operation_roots) & SEAL_OPS
        if not seal_ops.issubset(self.source_roots):
            raise ValueError("every seal operation requires a fixed staging source root")
        self.receipt_root = Path(receipt_root); self.receipt_root.mkdir(parents=True, exist_ok=True)
        self.active_path = Path(active_path).resolve() if active_path is not None else None
        self.authority_uid = os.geteuid() if authority_uid is None else authority_uid
        self.receipt_owner_uid = (os.geteuid() if receipt_owner_uid is None
                                  else receipt_owner_uid)
        self.receipt_group_gid = (os.getegid() if receipt_group_gid is None
                                  else receipt_group_gid)
        self.operation_policies = operation_policies or {}
        if set(self.operation_policies) - seal_ops:
            raise ValueError("operation policy names must be configured seal operations")
        for operation, policy in self.operation_policies.items():
            if (set(policy) not in ({"owner_uid", "group_gid", "directory_mode", "file_mode"},
                                    {"owner_uid", "group_gid", "directory_mode", "file_mode",
                                     "executable_file_mode"})
                    or any(type(value) is not int or value < 0 for value in policy.values())
                    or policy["directory_mode"] & 0o022
                    or policy["file_mode"] & 0o022
                    or policy.get("executable_file_mode", policy["file_mode"]) & 0o022):
                raise ValueError(f"unsafe operation policy: {operation}")

    def _load_receipt(self, path: Path) -> dict[str, Any]:
        info = path.lstat()
        if (path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != self.receipt_owner_uid
                or info.st_gid != self.receipt_group_gid
                or stat.S_IMODE(info.st_mode) != 0o440 or info.st_size > 65536):
            raise ContractError("broker_receipt_permissions",
                                "broker receipt owner/group/mode/link 不安全")
        try:
            value = _strict_json(path.read_bytes())
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ContractError("broker_receipt_unreadable", "broker receipt 无法解析") from exc
        if not isinstance(value, dict):
            raise ContractError("broker_receipt_unreadable", "broker receipt 不是 object")
        return value

    def _apply_policy(self, operation: str, root: Path) -> None:
        policy = self.operation_policies.get(operation)
        if policy is None:
            return
        for entry in scan_tree(root):
            path = root / entry.path
            os.chown(path, policy["owner_uid"], policy["group_gid"])
            mode = (policy.get("executable_file_mode", policy["file_mode"])
                    if entry.mode & 0o111 else policy["file_mode"])
            os.chmod(path, mode)
        for directory, names, _files in os.walk(root, topdown=False, followlinks=False):
            for name in names:
                path = Path(directory) / name
                info = path.lstat()
                if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
                    raise ContractError("sealed_tree_policy_unsafe", "sealed tree 目录类型异常")
                os.chown(path, policy["owner_uid"], policy["group_gid"])
                os.chmod(path, policy["directory_mode"])
        os.chown(root, policy["owner_uid"], policy["group_gid"])
        os.chmod(root, policy["directory_mode"])

    def _verify_policy(self, operation: str, root: Path) -> None:
        policy = self.operation_policies.get(operation)
        if policy is None:
            return
        paths = [root, *(root / entry.path for entry in scan_tree(root))]
        paths.extend(Path(directory) / name
                     for directory, names, _files in os.walk(root, followlinks=False)
                     for name in names)
        for path in paths:
            info = path.lstat()
            expected_mode = (policy["directory_mode"] if stat.S_ISDIR(info.st_mode)
                             else (policy.get("executable_file_mode", policy["file_mode"])
                                   if stat.S_IMODE(info.st_mode) & 0o111
                                   else policy["file_mode"]))
            if (info.st_uid != policy["owner_uid"] or info.st_gid != policy["group_gid"]
                    or stat.S_IMODE(info.st_mode) != expected_mode):
                raise ContractError("sealed_tree_policy_drift", "sealed tree owner/group/mode 漂移")

    def seal_tree(self, operation: str, source: Path, *, nonce: str,
                  expected_tree_hash: str, object_id: str | None = None) -> dict[str, Any]:
        if operation not in self.operation_roots or operation not in SEAL_OPS:
            raise ContractError("broker_operation_forbidden", "broker operation 不允许 seal tree")
        raw_source = Path(source)
        if raw_source.is_symlink():
            raise ContractError("broker_source_forbidden", "source 不能是 symlink")
        source = raw_source.resolve(); observed = tree_hash(scan_tree(source))
        if source.parent != self.source_roots[operation]:
            raise ContractError("broker_source_forbidden", "source 不在该 operation 的固定 staging 根")
        if observed != expected_tree_hash: raise ContractError("seal_tree_mismatch", "staging tree hash 不一致")
        if operation == "seal_release":
            # Root broker independently enforces the scientific-data boundary;
            # a compromised activator cannot bypass release.prepare checks.
            enforce_release_content_policy(source)
        object_id = object_id or observed
        if "/" in object_id or ".." in object_id or not object_id:
            raise ContractError("broker_object_id", "sealed object id 不合法")
        if operation == "seal_release" and not object_id.startswith("REL-"):
            raise ContractError("broker_release_id", "seal_release 必须使用 REL- object id")
        receipt_id = sha256({"operation": operation, "nonce": nonce, "tree_hash": observed,
                             "object_id": object_id})
        receipt_path = self.receipt_root / f"{receipt_id}.json"
        if receipt_path.exists():
            receipt = self._load_receipt(receipt_path)
            if (receipt.get("operation"), receipt.get("nonce"), receipt.get("tree_hash"),
                    receipt.get("object_id")) != (operation, nonce, observed, object_id):
                raise ContractError("broker_receipt_conflict", "receipt replay 内容冲突")
            sealed = Path(receipt.get("sealed_path", ""))
            if (sealed.resolve() != (self.operation_roots[operation] / object_id).resolve()
                    or not sealed.is_dir()
                    or tree_hash(scan_tree(sealed)) != receipt.get("sealed_tree_hash")):
                raise ContractError("broker_receipt_target_invalid", "receipt 对应 sealed target 缺失或损坏")
            # A one-time genesis receipt can pre-exist so the selector can
            # resolve the first broker LKG.  Replay must therefore revalidate
            # the full owner/group/mode policy, not only content identity,
            # before the genesis ceremony may qualify that receipt.
            self._verify_policy(operation, sealed)
            return receipt
        target_root = self.operation_roots[operation]; target_root.mkdir(parents=True, exist_ok=True)
        final = target_root / object_id
        if not final.exists():
            tmp = target_root / f".{object_id}.{uuid.uuid4().hex}.tmp"
            shutil.copytree(source, tmp, symlinks=True)
            # Re-scan after copy closes symlink/hardlink/special and TOCTOU windows.
            if tree_hash(scan_tree(tmp)) != observed:
                shutil.rmtree(tmp); raise ContractError("seal_copy_drift", "copy 后 tree hash 漂移")
            if operation == "seal_release":
                enforce_release_content_policy(tmp)
            if operation in self.operation_policies:
                self._apply_policy(operation, tmp)
            else:
                for entry in scan_tree(tmp):
                    os.chmod(tmp / entry.path, 0o550 if entry.mode & 0o111 else 0o440)
            os.rename(tmp, final); os.chmod(final, 0o550)
            if operation in self.operation_policies:
                self._apply_policy(operation, final)
        else:
            source_content = [(x.path, x.size, x.sha256) for x in scan_tree(source)]
            target_content = [(x.path, x.size, x.sha256) for x in scan_tree(final)]
            if source_content != target_content:
                raise ContractError("broker_existing_target_mismatch", "已存在 sealed target 内容冲突")
        if operation == "seal_release":
            enforce_release_content_policy(final)
        sealed_tree_hash = tree_hash(scan_tree(final))
        self._verify_policy(operation, final)
        receipt = {"receipt_id": receipt_id, "operation": operation, "nonce": nonce,
                   "object_id": object_id,
                   "tree_hash": observed, "sealed_tree_hash": sealed_tree_hash,
                   "sealed_path": str(final), "created_at": utc_now()}
        tmp_receipt = receipt_path.with_name(f".{receipt_path.name}.{uuid.uuid4().hex}.tmp")
        tmp_receipt.write_bytes(canonical_json(receipt) + b"\n")
        os.chown(tmp_receipt, self.receipt_owner_uid, self.receipt_group_gid)
        os.chmod(tmp_receipt, 0o440)
        os.replace(tmp_receipt, receipt_path)
        return receipt

    def _resolve_receipt(self, release_receipt: dict[str, Any] | str,
                         new_release: str) -> dict[str, Any]:
        """从 receipt_root 解析收据 —— 调用方传入的内容一律不被信任。

        调用方只用来指出 *哪一份* 收据(receipt_id);收据的全部字段以磁盘上
        broker 自己写下的那份为准,并且必须确认封存树真实存在且未被改动。
        """
        if isinstance(release_receipt, str):
            receipt_id = release_receipt
        elif isinstance(release_receipt, dict):
            receipt_id = release_receipt.get("receipt_id")
        else:
            raise ContractError("release_receipt_invalid", "release receipt 必须是 receipt_id 或 receipt dict")
        if (not isinstance(receipt_id, str) or not receipt_id
                or "/" in receipt_id or "." in receipt_id):
            raise ContractError("release_receipt_id_invalid", "release receipt id 不合法")
        receipt_path = self.receipt_root / f"{receipt_id}.json"
        if not receipt_path.is_file() or receipt_path.is_symlink():
            raise ContractError("release_receipt_unknown", "receipt_root 中不存在该封存收据")
        receipt = self._load_receipt(receipt_path)
        if not isinstance(receipt, dict) or receipt.get("receipt_id") != receipt_id:
            raise ContractError("release_receipt_corrupt", "封存收据自身不自洽")
        # 收据 id 必须是其内容的函数 —— 挡住往 receipt_root 里塞任意文件。
        recomputed = sha256({"operation": receipt.get("operation"), "nonce": receipt.get("nonce"),
                             "tree_hash": receipt.get("tree_hash"),
                             "object_id": receipt.get("object_id")})
        if recomputed != receipt_id:
            raise ContractError("release_receipt_corrupt", "封存收据 id 与内容不匹配")
        if receipt.get("operation") != "seal_release":
            raise ContractError("release_unsealed", "只允许激活 broker sealed release")
        if receipt.get("object_id") != new_release:
            raise ContractError("release_receipt_mismatch", "release receipt 与新 release 不匹配")
        if "seal_release" not in self.operation_roots:
            raise ContractError("release_unsealed", "broker 未登记 seal_release operation")
        # 封存树必须在磁盘上真实存在,且内容与收据一致。
        expected_dir = (self.operation_roots["seal_release"] / new_release)
        sealed = Path(receipt.get("sealed_path", ""))
        if not sealed.is_absolute() or sealed.is_symlink() or not sealed.is_dir():
            raise ContractError("sealed_tree_missing", "封存树在磁盘上不存在")
        if sealed.resolve() != expected_dir.resolve():
            raise ContractError("sealed_tree_missing", "封存树不在该 broker 的 release 根下")
        if tree_hash(scan_tree(sealed)) != receipt.get("sealed_tree_hash"):
            raise ContractError("sealed_tree_drift", "封存树内容与收据不一致")
        # Old/on-disk receipts are not grandfathered around a newly tightened
        # scientific-data boundary.  Re-open and scan before every activation.
        enforce_release_content_policy(sealed)
        # 若调用方同时递交了 dict,它必须与磁盘上那份完全一致,否则视为伪造。
        if isinstance(release_receipt, dict) and release_receipt != receipt:
            raise ContractError("release_receipt_conflict", "递交的 receipt 与 receipt_root 中的不一致")
        return receipt

    def activate(self, active_path: Path, *, expected_old: str | None, new_release: str,
                 release_receipt: dict[str, Any] | str, verification_hash: str,
                 canary_hash: str) -> dict[str, Any]:
        active_path = Path(active_path)
        if self.active_path is None or active_path.resolve() != self.active_path:
            raise ContractError("active_path_forbidden", "active pointer 路径不在 broker registry")
        if active_path.exists():
            info = active_path.lstat()
            if (active_path.is_symlink() or not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1 or info.st_uid != self.authority_uid
                    or stat.S_IMODE(info.st_mode) != 0o444):
                raise ContractError("active_file_unsafe", "active pointer 必须是单链接 regular file")
        current = json.loads(active_path.read_text()) if active_path.exists() else None
        if (isinstance(current, dict) and current.get("release_id") == new_release
                and current.get("previous_release") == expected_old):
            receipt = self._resolve_receipt(release_receipt, new_release)
            if (current.get("release_receipt_id") == receipt["receipt_id"]
                    and current.get("verification_hash") == verification_hash
                    and current.get("canary_hash") == canary_hash):
                return current
            raise ContractError("active_replay_conflict", "已激活 release 的证明绑定冲突")
        if (current or {}).get("release_id") != expected_old:
            raise ContractError("active_cas_failed", "active release 已变化")
        receipt = self._resolve_receipt(release_receipt, new_release)
        record = {"release_id": new_release, "previous_release": expected_old,
                  "release_receipt_id": receipt["receipt_id"],
                  "verification_hash": verification_hash, "canary_hash": canary_hash,
                  "activated_at": utc_now()}
        active_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = active_path.with_name(f".{active_path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(canonical_json(record) + b"\n"); os.replace(tmp, active_path); os.chmod(active_path, 0o444)
        return record

    def restart_generation(self, generation: str, *, expected_release_id: str,
                           generations: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        """TERM fixed unique-UID services; launchd KeepAlive starts the new generation."""
        services = generations.get(generation)
        if (not isinstance(generation, str) or not isinstance(services, list) or not services):
            raise ContractError("restart_generation_unknown", "restart generation 未冻结")
        if self.active_path is None:
            raise ContractError("active_path_forbidden", "broker 未登记 active pointer")
        info = self.active_path.lstat()
        if (self.active_path.is_symlink() or not stat.S_ISREG(info.st_mode)
                or info.st_uid != self.authority_uid
                or stat.S_IMODE(info.st_mode) != 0o444):
            raise ContractError("active_file_unsafe", "active pointer owner/mode 不安全")
        active = _strict_json(self.active_path.read_bytes())
        if (not isinstance(active, dict)
                or active.get("release_id") != expected_release_id):
            raise ContractError("restart_release_drift", "restart 前 active release 已变化")
        if sys.platform != "darwin":
            raise ContractError("process_registry_unavailable", "generation restart 仅支持 macOS")
        expected_executable = (self.operation_roots["seal_release"]
                               / expected_release_id / "env/bin/python").resolve()
        if not expected_executable.is_file() or expected_executable.is_symlink():
            raise ContractError("restart_release_runtime_missing", "目标 release runtime 不可用")
        restarted: list[str] = []
        already_current: list[str] = []
        previous_release = active.get("previous_release")
        previous_executable = ((self.operation_roots["seal_release"]
                                / previous_release / "env/bin/python").resolve()
                               if isinstance(previous_release, str) else None)
        for service in services:
            exact = strict_object(service, required={"label", "uid"})
            label, service_uid = exact["label"], exact["uid"]
            if (not isinstance(label, str) or not label.startswith("com.abcr.")
                    or label == "com.abcr.seal-broker" or "/" in label
                    or type(service_uid) is not int or service_uid <= 0):
                raise ContractError("restart_generation_config_invalid",
                                    "restart service binding 不合法")
            current_matches = _darwin_processes(service_uid, expected_executable)
            if len(current_matches) == 1:
                already_current.append(label)
                continue
            if current_matches:
                raise ContractError("restart_process_ambiguous", "新 generation PID 不唯一",
                                    {"generation": generation,
                                     "match_count": len(current_matches)})
            if previous_executable is None:
                raise ContractError("restart_previous_release_missing",
                                    "active record 缺少 previous release")
            if not previous_executable.is_file() or previous_executable.is_symlink():
                raise ContractError("restart_previous_release_missing",
                                    "previous release runtime 不可用")
            matches = _darwin_processes(service_uid, previous_executable)
            if len(matches) != 1:
                raise ContractError("restart_process_ambiguous", "service PID 无法唯一验证",
                                    {"generation": generation, "match_count": len(matches)})
            pid = matches[0]
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                # Recheck UID+executable before KILL so PID reuse cannot target a
                # different process.
                if pid not in _darwin_processes(service_uid, previous_executable):
                    raise ContractError("restart_pid_reused", "service PID 在等待时发生复用")
                os.kill(pid, signal.SIGKILL)
            restarted.append(label)
        return {"generation": generation, "release_id": expected_release_id,
                "restarted_labels": restarted, "already_current_labels": already_current,
                "completed_at": utc_now()}


def main(argv: list[str] | None = None) -> int:
    """Serve the finite broker API over a peer-credential-authenticated Unix socket."""
    from abcr.control.queue_runtime import EX_CONFIG, ServiceRuntimeBlocked, load_queue_config

    parser = argparse.ArgumentParser(prog="seal-broker")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--doctor", action="store_true")
    modes.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)

    def load():
        config = load_queue_config("seal-broker")
        settings = strict_object(config["settings"], required={
            "operation_roots", "source_roots", "receipt_root", "active_path",
            "socket_path", "socket_gid", "allowed_peer_uids", "work_root",
            "work_stage_acl", "research_memory_seal", "operation_policies",
            "source_policies", "approval_validator_public_key",
            "restart_generations", "receipt_owner_uid", "receipt_group_gid",
            "work_lease_seconds", "work_max_attempts"})
        if not isinstance(settings["operation_roots"], dict) or not isinstance(settings["source_roots"], dict):
            raise ContractError("broker_roots_invalid", "broker roots 不合法")
        operation_roots = {name: Path(value) for name, value in settings["operation_roots"].items()}
        source_roots = {name: Path(value) for name, value in settings["source_roots"].items()}
        if set(operation_roots) - OPS or set(source_roots) - OPS:
            raise ContractError("broker_operation_unknown", "broker operation 未冻结")
        policies = settings["operation_policies"]
        if not isinstance(policies, dict) or set(policies) != (set(operation_roots) & SEAL_OPS):
            raise ContractError("broker_operation_policy_invalid", "每个 seal op 必须有精确 owner/mode policy")
        for name, value in policies.items():
            exact = strict_object(value, required={"owner_uid", "group_gid",
                                                   "directory_mode", "file_mode"},
                                  optional={"executable_file_mode"})
            if (any(type(exact[key]) is not int or exact[key] < 0 for key in exact)
                    or exact["directory_mode"] & 0o022 or exact["file_mode"] & 0o022
                    or exact.get("executable_file_mode", exact["file_mode"]) & 0o022):
                raise ContractError("broker_operation_policy_invalid", f"{name} policy 不安全")
        source_policies = settings["source_policies"]
        if (not isinstance(source_policies, dict)
                or set(source_policies) != (set(source_roots) & SEAL_OPS)):
            raise ContractError("broker_source_policy_invalid", "每个 source root 必须有固定 producer policy")
        for name, value in source_policies.items():
            exact = strict_object(value, required={"owner_uid", "group_gid", "directory_mode"})
            if (any(type(exact[key]) is not int or exact[key] < 0 for key in exact)
                    or exact["directory_mode"] & 0o022):
                raise ContractError("broker_source_policy_invalid", f"{name} source policy 不安全")
        allowed = settings["allowed_peer_uids"]
        if (not isinstance(allowed, dict) or set(allowed) - OPS
                or any(not isinstance(items, list)
                       or any(type(uid) is not int or uid < 0 for uid in items)
                       for items in allowed.values())):
            raise ContractError("broker_peer_policy_invalid", "peer uid policy 不合法")
        acl = settings["work_stage_acl"]
        if not isinstance(acl, dict) or set(acl) != set(STAGES):
            raise ContractError("work_stage_acl_invalid", "九阶段 ACL 必须完整冻结")
        for stage, rule in acl.items():
            exact = strict_object(rule, required={"producers", "consumers"})
            if (not isinstance(exact["producers"], dict)
                    or not isinstance(exact["consumers"], dict)
                    or any(not key.isdigit() or not isinstance(value, str) or not value
                           for mapping in (exact["producers"], exact["consumers"])
                           for key, value in mapping.items())):
                raise ContractError("work_stage_acl_invalid", f"{stage} ACL 不合法")
        if type(settings["socket_gid"]) is not int or settings["socket_gid"] < 0:
            raise ContractError("broker_socket_group_invalid", "socket gid 不合法")
        if (settings["receipt_owner_uid"] != os.geteuid()
                or type(settings["receipt_group_gid"]) is not int
                or settings["receipt_group_gid"] < 0):
            raise ContractError("broker_receipt_policy_invalid",
                                "broker receipt owner/group policy 不合法")
        if (type(settings["work_lease_seconds"]) is not int
                or not 10 <= settings["work_lease_seconds"] <= 3600
                or type(settings["work_max_attempts"]) is not int
                or not 1 <= settings["work_max_attempts"] <= 20):
            raise ContractError("work_recovery_policy_invalid",
                                "work recovery policy 不合法")
        generations = settings["restart_generations"]
        if (not isinstance(generations, dict) or not generations
                or any(not isinstance(name, str) or not name
                       or not isinstance(services, list) or not services
                       or any(not isinstance(service, dict)
                              or set(service) != {"label", "uid"}
                              or not isinstance(service.get("label"), str)
                              or not service["label"].startswith("com.abcr.")
                              or "/" in service["label"]
                              or service["label"] == "com.abcr.seal-broker"
                              or type(service.get("uid")) is not int
                              or service["uid"] <= 0 for service in services)
                       or len({service["label"] for service in services}) != len(services)
                       or len({service["uid"] for service in services}) != len(services)
                       for name, services in generations.items())):
            raise ContractError("restart_generation_config_invalid",
                                "restart generations config 不合法")
        if config["broker_socket"] != settings["socket_path"]:
            raise ContractError("broker_socket_binding_mismatch", "client/server socket binding 不一致")
        paths = [*operation_roots.values(), Path(settings["receipt_root"]), Path(settings["work_root"]),
                 Path(settings["active_path"]).parent,
                 Path(settings["socket_path"]).parent]
        for path in paths:
            info = path.lstat()
            if path.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
                raise ContractError("broker_root_unsafe", "broker root owner/mode 不安全")
        for operation, path in source_roots.items():
            info = path.lstat()
            policy = source_policies[operation]
            if (path.is_symlink() or not stat.S_ISDIR(info.st_mode)
                    or info.st_uid != policy["owner_uid"] or info.st_gid != policy["group_gid"]
                    or stat.S_IMODE(info.st_mode) != policy["directory_mode"]):
                raise ContractError("broker_source_root_unsafe", f"{operation} source root policy 不匹配")
        validator_key = Path(settings["approval_validator_public_key"])
        validator_info = validator_key.lstat()
        if (not validator_key.is_absolute() or validator_key.is_symlink()
                or not stat.S_ISREG(validator_info.st_mode) or validator_info.st_nlink != 1
                or validator_info.st_uid != 0 or validator_info.st_mode & 0o022):
            raise ContractError("validator_public_key_invalid", "broker validator trust anchor 不安全")
        seal_config = strict_object(settings["research_memory_seal"], required={
            "ledger_path", "seal_path", "private_key", "public_key",
            "ledger_owner_uid", "trust_owner_uid"})
        if any(not isinstance(seal_config[name], str) or not Path(seal_config[name]).is_absolute()
               for name in ("ledger_path", "seal_path", "private_key", "public_key")):
            raise ContractError("research_memory_seal_config", "ResearchMemory 固定路径不合法")
        return settings, operation_roots, source_roots

    def peer_uid(connection: socket.socket) -> int:
        getpeereid = getattr(connection, "getpeereid", None)
        if callable(getpeereid):
            return int(getpeereid()[0])
        if hasattr(socket, "SO_PEERCRED"):
            raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            _pid, uid, _gid = struct.unpack("3i", raw)
            return int(uid)
        raise ContractError("peer_credentials_unavailable", "系统不支持 peer credentials")

    def launchd_listener() -> socket.socket:
        """Adopt launchd's Listener fd; production must never unlink/rebind it."""
        if sys.platform != "darwin":
            raise ContractError("launchd_socket_unavailable", "launchd socket activation 仅支持 macOS")
        library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        function = library.launch_activate_socket
        function.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
                             ctypes.POINTER(ctypes.c_size_t)]
        function.restype = ctypes.c_int
        release = library.free
        release.argtypes = [ctypes.c_void_p]; release.restype = None
        fds = ctypes.POINTER(ctypes.c_int)()
        count = ctypes.c_size_t()
        status = function(b"Listener", ctypes.byref(fds), ctypes.byref(count))
        if status != 0 or count.value != 1:
            if bool(fds): release(ctypes.cast(fds, ctypes.c_void_p))
            raise ContractError("launchd_socket_activation_failed", "Listener fd 不可用")
        fd = int(fds[0]); release(ctypes.cast(fds, ctypes.c_void_p))
        return socket.socket(fileno=fd)

    def dispatch(request: Any, uid: int, settings: dict, broker: SealBroker) -> dict[str, Any]:
        obj = strict_object(request, required={"schema_version", "operation", "arguments"},
                            optional={"active_path"})
        operation = obj["operation"]
        if obj["schema_version"] != 1 or operation not in OPS or not isinstance(obj["arguments"], dict):
            raise ContractError("broker_request_invalid", "broker request 不合法")
        arguments = obj["arguments"]
        if operation == RESEARCH_MEMORY_SEAL_OPERATION:
            if uid not in settings["allowed_peer_uids"].get(operation, []):
                raise ContractError("broker_peer_forbidden", "peer 无权刷新 ResearchMemory seal")
            cfg = settings["research_memory_seal"]
            return refresh_research_memory_seal(
                ResearchMemorySealConfig(
                    ledger_path=Path(cfg["ledger_path"]), seal_path=Path(cfg["seal_path"]),
                    private_key=Path(cfg["private_key"]), public_key=Path(cfg["public_key"]),
                    ledger_owner_uid=cfg["ledger_owner_uid"],
                    trust_owner_uid=cfg["trust_owner_uid"]), arguments)
        if operation in WORK_OPS:
            base = strict_object(arguments, required={"stage"}, optional={
                "work_id", "attempt", "fencing_token", "producer", "payload",
                "consumer", "result", "include_fence"})
            stage = base["stage"]
            if stage not in STAGES:
                raise ContractError("work_stage_invalid", "work stage 不合法")
            rule = settings["work_stage_acl"][stage]
            consumer = rule["consumers"].get(str(uid))
            producer = rule["producers"].get(str(uid))
            producer_ops = {"work_enqueue", "work_result_list", "work_result_read", "work_ack"}
            if operation in producer_ops:
                if producer is None:
                    raise ContractError("broker_peer_forbidden", "peer 无权生产/收取该 stage")
            elif consumer is None:
                raise ContractError("broker_peer_forbidden", "peer 无权消费该 stage")
            spool = WorkSpool(Path(settings["work_root"]), create=False)
            if operation == "work_list":
                spool.recover_expired(
                    stage, lease_seconds=settings["work_lease_seconds"],
                    max_attempts=settings["work_max_attempts"])
                ready = Path(settings["work_root"]) / stage / "ready"
                return [path.stem for path in sorted(ready.iterdir(), key=lambda item: item.name)
                        if path.suffix == ".json" and WORK_ID.fullmatch(path.stem)
                        and path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1]
            if operation == "work_result_list":
                results = Path(settings["work_root"]) / stage / "results"
                paths = [path for path in sorted(results.iterdir(), key=lambda item: item.name)
                         if path.suffix == ".json" and WORK_ID.fullmatch(path.stem)
                         and path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1
                         and not (Path(settings["work_root"]) / stage / "acks" / path.name).exists()]
                if base.get("include_fence") is not True:
                    return [path.stem for path in paths]
                catalog = []
                for path in paths:
                    envelope = json.loads(path.read_text(encoding="utf-8"))
                    catalog.append({"work_id": path.stem,
                                    "attempt": envelope.get("attempt"),
                                    "fencing_token": envelope.get("fencing_token")})
                return catalog
            if operation == "work_enqueue":
                exact = strict_object(arguments, required={"stage", "work_id", "attempt",
                                                            "fencing_token", "producer", "payload"})
                if exact["producer"] != producer:
                    raise ContractError("work_producer_spoofed", "producer 名称与 peer uid 不一致")
                path = spool.enqueue(stage, exact["work_id"], exact["payload"],
                                     attempt=exact["attempt"], fencing_token=exact["fencing_token"],
                                     producer=exact["producer"])
                return {"work_id": path.stem}
            if not isinstance(base.get("work_id"), str) or WORK_ID.fullmatch(base["work_id"]) is None:
                raise ContractError("work_id_invalid", "work id 不合法")
            if operation == "work_claim":
                claim = spool.claim(stage, base["work_id"])
                return None if claim is None else {"work_id": claim.work_id,
                                                    "attempt": claim.attempt,
                                                    "fencing_token": claim.fencing_token,
                                                    "payload": claim.payload}
            if operation == "work_result":
                exact = strict_object(arguments, required={"stage", "work_id", "attempt",
                                                           "fencing_token", "consumer", "result"})
            elif operation == "work_ack":
                exact = strict_object(arguments, required={"stage", "work_id", "attempt",
                                                           "fencing_token", "result_hash"})
            else:
                exact = strict_object(arguments, required={"stage", "work_id", "attempt",
                                                           "fencing_token"})
            if type(exact["attempt"]) is not int or type(exact["fencing_token"]) is not int:
                raise ContractError("work_fence_invalid", "work fence 不合法")
            claim = Claim(stage, exact["work_id"], exact["attempt"], exact["fencing_token"],
                          Path(settings["work_root"]) / stage / "inflight" / f"{exact['work_id']}.json",
                          {})
            if operation == "work_heartbeat":
                if not claim.path.is_file() or claim.path.is_symlink():
                    raise ContractError("work_claim_missing", "inflight claim 不存在")
                envelope = json.loads(claim.path.read_text(encoding="utf-8"))
                if (envelope.get("attempt"), envelope.get("fencing_token")) != (
                        claim.attempt, claim.fencing_token):
                    raise ContractError("work_fence_invalid", "heartbeat fence 已过期")
                envelope["heartbeat_at"] = utc_now()
                tmp = claim.path.with_name(f".{claim.path.name}.{uuid.uuid4().hex}.tmp")
                try:
                    with tmp.open("xb") as stream:
                        stream.write(canonical_json(envelope) + b"\n")
                        stream.flush(); os.fsync(stream.fileno())
                    os.replace(tmp, claim.path)
                finally: tmp.unlink(missing_ok=True)
                return {"alive": True, "heartbeat_at": envelope["heartbeat_at"]}
            if operation == "work_result":
                if exact["consumer"] != consumer:
                    raise ContractError("work_consumer_spoofed", "consumer 名称与 peer uid 不一致")
                spool.submit_result(claim, exact["result"], consumer=consumer)
                return {"stored": True}
            if operation == "work_result_read":
                return spool.read_result(stage, exact["work_id"], attempt=exact["attempt"],
                                         fencing_token=exact["fencing_token"])
            spool.ack(claim, expected_result_hash=exact["result_hash"])
            return {"acked": True}
        if uid not in settings["allowed_peer_uids"].get(operation, []):
            raise ContractError("broker_peer_forbidden", "peer 无权执行该 operation")
        if operation == "activate_release":
            exact = strict_object(arguments, required={
                "expected_old", "new_release", "release_receipt",
                "verification_ref", "canary_ref"})
            if obj.get("active_path") != settings["active_path"]:
                raise ContractError("active_path_forbidden", "active path 不在 registry")
            from abcr.control.mission_pipeline import (load_json_artifact,
                                                       resolve_sealed_tree,
                                                       validate_broker_ref)
            release_receipt = broker._resolve_receipt(exact["release_receipt"],
                                                      exact["new_release"])
            release_tree = resolve_sealed_tree(
                {"operation": "seal_release",
                 "receipt_id": release_receipt["receipt_id"],
                 "object_id": release_receipt["object_id"],
                 "sealed_tree_hash": release_receipt["sealed_tree_hash"]},
                expected_operation="seal_release",
                trusted_root=broker.operation_roots["seal_release"])
            manifest_path = release_tree / "release-manifest.json"
            manifest_raw = manifest_path.read_bytes()
            manifest = _strict_json(manifest_raw)
            if (not isinstance(manifest, dict)
                    or canonical_json(manifest) + b"\n" != manifest_raw
                    or manifest.get("release_id") != exact["new_release"]):
                raise ContractError("release_manifest_invalid", "sealed release manifest 不合法")
            verification_ref = validate_broker_ref(
                exact["verification_ref"], expected_operation="seal_verification")
            verification = load_json_artifact(
                verification_ref, expected_operation="seal_verification",
                trusted_root=broker.operation_roots["seal_verification"],
                filename="verification.json")
            verification_doc = strict_object(verification, required={
                "schema_version", "kind", "attestation", "pipeline_context",
                "test_result_ref", "candidate_ref"})
            if (verification_doc["schema_version"] != 1
                    or verification_doc["kind"] != "verification"):
                raise ContractError("verification_invalid", "verification artifact 类型不合法")
            attestation = verification_doc["attestation"]
            if not isinstance(attestation, dict):
                raise ContractError("verification_invalid", "verification attestation 不合法")
            core_fields = {"mission_id", "fencing_token", "base_tree_hash",
                           "candidate_tree_hash", "profile_hash", "oracle_set_hash",
                           "changed_paths", "verdict", "verified_at", "isolation"}
            if (set(attestation) != core_fields | {"attestation_hash", "sealed"}
                    or attestation.get("verdict") != "PASS"
                    or sha256({key: attestation[key] for key in core_fields})
                    != attestation.get("attestation_hash")
                    or attestation.get("attestation_hash") != manifest.get("verification_hash")
                    or attestation.get("candidate_tree_hash") != manifest.get("tree_hash")):
                raise ContractError("verification_binding_invalid",
                                    "verification PASS/manifest binding 不合法")
            canary_ref = validate_broker_ref(exact["canary_ref"],
                                             expected_operation="seal_canary")
            canary_doc = load_json_artifact(
                canary_ref, expected_operation="seal_canary",
                trusted_root=broker.operation_roots["seal_canary"], filename="canary.json")
            canary_envelope = strict_object(canary_doc, required={
                "schema_version", "kind", "mission_id", "canary", "release_ref",
                "verification_ref", "old_release"})
            canary = canary_envelope["canary"]
            canary_core_fields = {"release_id", "expected_version", "observed_version",
                                  "semantic_ok", "reason", "checked_at"}
            expected_release_ref = {"operation": "seal_release",
                                    "receipt_id": release_receipt["receipt_id"],
                                    "object_id": release_receipt["object_id"],
                                    "sealed_tree_hash": release_receipt["sealed_tree_hash"]}
            if (canary_envelope["schema_version"] != 1
                    or canary_envelope["kind"] != "canary"
                    or not isinstance(canary, dict)
                    or set(canary) != canary_core_fields | {"result_hash"}
                    or canary.get("semantic_ok") is not True
                    or canary.get("release_id") != exact["new_release"]
                    or canary.get("observed_version") != canary.get("expected_version")
                    or sha256({key: canary[key] for key in canary_core_fields})
                    != canary.get("result_hash")
                    or canary_envelope["release_ref"] != expected_release_ref
                    or canary_envelope["verification_ref"] != verification_ref
                    or canary_envelope["mission_id"] != attestation.get("mission_id")
                    or canary_envelope["old_release"] != exact["expected_old"]):
                raise ContractError("canary_binding_invalid", "canary PASS/release binding 不合法")
            return broker.activate(
                Path(settings["active_path"]), expected_old=exact["expected_old"],
                new_release=exact["new_release"], release_receipt=release_receipt,
                verification_hash=attestation["attestation_hash"],
                canary_hash=canary["result_hash"])
        if operation == "restart_generation":
            exact = strict_object(arguments,
                                  required={"generation", "expected_release_id"})
            if not isinstance(settings["restart_generations"], dict):
                raise ContractError("restart_generation_config_invalid",
                                    "restart generations config 不合法")
            return broker.restart_generation(
                exact["generation"], expected_release_id=exact["expected_release_id"],
                generations=settings["restart_generations"])
        exact = strict_object(arguments, required={"source", "nonce", "expected_tree_hash"},
                              optional={"object_id"})
        if operation == "seal_approval_bundle":
            source = Path(exact["source"])
            entries = scan_tree(source)
            if len(entries) != 1 or entries[0].path != "validator.json":
                raise ContractError("validator_approval_tree_invalid",
                                    "approval staging 必须只含 validator.json")
            raw = (source / "validator.json").read_bytes()
            try:
                document = _strict_json(raw)
            except (ValueError, json.JSONDecodeError) as exc:
                raise ContractError("validator_approval_tree_invalid",
                                    "validator.json 不是严格 JSON") from exc
            candidate = broker_verify_candidate(
                document,
                validator_public_key_pem=Path(
                    settings["approval_validator_public_key"]).read_bytes())
            if raw != candidate.canonical_bytes:
                raise ContractError("validator_approval_noncanonical",
                                    "validator.json 必须逐字等于 canonical validator document")
        return broker.seal_tree(operation, Path(exact.pop("source")), **exact)

    try:
        settings, operation_roots, source_roots = load()
        if args.doctor:
            print(json.dumps({"ok": True, "service": "seal-broker",
                              "transport": "unix-peer-credentials"}, sort_keys=True))
            return 0
        broker = SealBroker(operation_roots, Path(settings["receipt_root"]),
                            source_roots=source_roots,
                            active_path=Path(settings["active_path"]),
                            operation_policies=settings["operation_policies"],
                            authority_uid=os.geteuid(),
                            receipt_owner_uid=settings["receipt_owner_uid"],
                            receipt_group_gid=settings["receipt_group_gid"])
        socket_path = Path(settings["socket_path"])
        launched = bool(os.environ.get("ABCR_SERVICE_LABEL"))
        if launched:
            server = launchd_listener()
            info = socket_path.lstat()
            if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0
                    or info.st_gid != settings["socket_gid"]
                    or stat.S_IMODE(info.st_mode) != 0o660):
                raise ContractError("launchd_socket_permissions", "Listener 必须为 root:broker-clients 0660")
        else:
            if socket_path.exists():
                info = socket_path.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                    raise ContractError("broker_socket_unsafe", "已有 socket path 不安全")
                socket_path.unlink()
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(socket_path))
            os.chown(socket_path, os.geteuid(), settings["socket_gid"])
            os.chmod(socket_path, 0o660)
            server.listen(16)
        with server:
            while True:
                connection, _ = server.accept()
                with connection:
                    try:
                        uid = peer_uid(connection)
                        raw = b""
                        while b"\n" not in raw and len(raw) <= 1024 * 1024:
                            chunk = connection.recv(65536)
                            if not chunk: break
                            raw += chunk
                        if len(raw) > 1024 * 1024 or raw.count(b"\n") != 1:
                            raise ContractError("broker_request_framing", "request framing 不合法")
                        result = dispatch(_strict_json(raw), uid, settings, broker)
                        response = {"ok": True, "result": result}
                    except Exception as exc:
                        code = exc.code if isinstance(exc, ContractError) else type(exc).__name__
                        response = {"ok": False, "error_code": code}
                    try:
                        connection.sendall(canonical_json(response) + b"\n")
                    except (BrokenPipeError, ConnectionResetError):
                        # restart_generation may intentionally terminate its
                        # operator caller.  The restarted reconciler replays the
                        # idempotent generation request and observes all-current.
                        pass
                if args.once: break
        return 0
    except Exception as exc:
        code = exc.code if isinstance(exc, (ContractError, ServiceRuntimeBlocked)) else type(exc).__name__
        print(json.dumps({"ok": False, "service": "seal-broker",
                          "error_code": code}, sort_keys=True), file=sys.stderr)
        return EX_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
