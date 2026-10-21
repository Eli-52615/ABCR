"""Finite-operation sealing broker core (transport/peer-credential wrapper is external)."""
from __future__ import annotations

import json
import os
import shutil
import stat
import uuid
from pathlib import Path
from typing import Any

from abcr.control.contracts import ContractError, canonical_json, sha256, utc_now
from abcr.control.worktree import scan_tree, tree_hash

OPS = frozenset({"seal_dev_bundle", "seal_test_result", "seal_verification",
                 "seal_canary", "seal_release", "activate_release", "restart_generation"})


class SealBroker:
    def __init__(self, operation_roots: dict[str, Path], receipt_root: Path, *,
                 source_roots: dict[str, Path], active_path: Path | None = None):
        unknown = set(operation_roots) - OPS
        if unknown: raise ValueError(f"unknown broker operations: {unknown}")
        self.operation_roots = {k: Path(v).resolve() for k, v in operation_roots.items()}
        self.source_roots = {k: Path(v).resolve() for k, v in source_roots.items()}
        seal_ops = set(operation_roots) - {"activate_release", "restart_generation"}
        if not seal_ops.issubset(self.source_roots):
            raise ValueError("every seal operation requires a fixed staging source root")
        self.receipt_root = Path(receipt_root); self.receipt_root.mkdir(parents=True, exist_ok=True)
        self.active_path = Path(active_path).resolve() if active_path is not None else None

    def seal_tree(self, operation: str, source: Path, *, nonce: str,
                  expected_tree_hash: str, object_id: str | None = None) -> dict[str, Any]:
        if operation not in self.operation_roots or operation in {"activate_release", "restart_generation"}:
            raise ContractError("broker_operation_forbidden", "broker operation 不允许 seal tree")
        raw_source = Path(source)
        if raw_source.is_symlink():
            raise ContractError("broker_source_forbidden", "source 不能是 symlink")
        source = raw_source.resolve(); observed = tree_hash(scan_tree(source))
        if source.parent != self.source_roots[operation]:
            raise ContractError("broker_source_forbidden", "source 不在该 operation 的固定 staging 根")
        if observed != expected_tree_hash: raise ContractError("seal_tree_mismatch", "staging tree hash 不一致")
        object_id = object_id or observed
        if "/" in object_id or ".." in object_id or not object_id:
            raise ContractError("broker_object_id", "sealed object id 不合法")
        if operation == "seal_release" and not object_id.startswith("REL-"):
            raise ContractError("broker_release_id", "seal_release 必须使用 REL- object id")
        receipt_id = sha256({"operation": operation, "nonce": nonce, "tree_hash": observed,
                             "object_id": object_id})
        receipt_path = self.receipt_root / f"{receipt_id}.json"
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (receipt.get("operation"), receipt.get("nonce"), receipt.get("tree_hash"),
                    receipt.get("object_id")) != (operation, nonce, observed, object_id):
                raise ContractError("broker_receipt_conflict", "receipt replay 内容冲突")
            sealed = Path(receipt.get("sealed_path", ""))
            if (sealed.resolve() != (self.operation_roots[operation] / object_id).resolve()
                    or not sealed.is_dir()
                    or tree_hash(scan_tree(sealed)) != receipt.get("sealed_tree_hash")):
                raise ContractError("broker_receipt_target_invalid", "receipt 对应 sealed target 缺失或损坏")
            return receipt
        target_root = self.operation_roots[operation]; target_root.mkdir(parents=True, exist_ok=True)
        final = target_root / object_id
        if not final.exists():
            tmp = target_root / f".{object_id}.{uuid.uuid4().hex}.tmp"
            shutil.copytree(source, tmp, symlinks=True)
            # Re-scan after copy closes symlink/hardlink/special and TOCTOU windows.
            if tree_hash(scan_tree(tmp)) != observed:
                shutil.rmtree(tmp); raise ContractError("seal_copy_drift", "copy 后 tree hash 漂移")
            for entry in scan_tree(tmp): os.chmod(tmp / entry.path, 0o550 if entry.mode & 0o111 else 0o440)
            os.rename(tmp, final); os.chmod(final, 0o550)
        else:
            source_content = [(x.path, x.size, x.sha256) for x in scan_tree(source)]
            target_content = [(x.path, x.size, x.sha256) for x in scan_tree(final)]
            if source_content != target_content:
                raise ContractError("broker_existing_target_mismatch", "已存在 sealed target 内容冲突")
        sealed_tree_hash = tree_hash(scan_tree(final))
        receipt = {"receipt_id": receipt_id, "operation": operation, "nonce": nonce,
                   "object_id": object_id,
                   "tree_hash": observed, "sealed_tree_hash": sealed_tree_hash,
                   "sealed_path": str(final), "created_at": utc_now()}
        tmp_receipt = receipt_path.with_name(f".{receipt_path.name}.{uuid.uuid4().hex}.tmp")
        tmp_receipt.write_bytes(canonical_json(receipt) + b"\n"); os.replace(tmp_receipt, receipt_path)
        os.chmod(receipt_path, 0o440)
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
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ContractError("release_receipt_unreadable", "封存收据无法解析") from exc
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
            if active_path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ContractError("active_file_unsafe", "active pointer 必须是单链接 regular file")
        current = json.loads(active_path.read_text()) if active_path.exists() else None
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


def main(argv: list[str] | None = None) -> int:
    """Fail closed until a peer-credential-authenticated socket adapter exists."""
    from abcr.control.service_runtime import blocked_runtime_main
    return blocked_runtime_main(argv, service="seal-broker",
                                required_capability="seal_tree",
                                capabilities={"seal_tree": SealBroker.seal_tree})


if __name__ == "__main__":
    raise SystemExit(main())
