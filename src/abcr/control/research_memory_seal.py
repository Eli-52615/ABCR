"""Root/seal-broker operation for guarded ResearchMemory seal refresh.

The request contains only an optimistic concurrency snapshot.  Ledger, seal and key
paths are fixed trusted configuration and can never be supplied by the Operator.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from abcr.control.contracts import (ContractError, require_id, require_sha, sha256,
                                    strict_object)
from abcr.control.ed25519 import public_fingerprint
from abcr.explore.memory import ResearchMemory


OPERATION = "seal_research_memory"


@dataclass(frozen=True)
class ResearchMemorySealConfig:
    ledger_path: Path
    seal_path: Path
    private_key: Path
    public_key: Path
    ledger_owner_uid: int
    trust_owner_uid: int = 0


def parse_refresh_request(value: Any) -> dict[str, Any]:
    request = strict_object(
        value,
        required={"nonce", "expected_length", "expected_head_entry_hash",
                  "expected_ledger_sha256"})
    require_id(request["nonce"], "nonce")
    if (type(request["expected_length"]) is not int
            or request["expected_length"] <= 0):
        raise ContractError("research_memory_refresh_request", "expected_length 必须为正整数")
    require_sha(request["expected_head_entry_hash"], "expected_head_entry_hash")
    require_sha(request["expected_ledger_sha256"], "expected_ledger_sha256")
    return request


def _secure_regular(path: Path, *, owner_uid: int, private: bool = False) -> None:
    if not path.is_absolute():
        raise ContractError("research_memory_seal_config", "broker 固定路径必须是绝对路径")
    try:
        info = path.lstat()
    except OSError as exc:
        raise ContractError("research_memory_seal_config", "broker 固定文件不可达") from exc
    if (path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != owner_uid or info.st_mode & 0o022
            or (private and stat.S_IMODE(info.st_mode) != 0o600)):
        raise ContractError("research_memory_seal_config", "broker 固定文件 owner/mode/link 不安全")


def _secure_directory(path: Path, *, owner_uid: int) -> None:
    if not path.is_absolute():
        raise ContractError("research_memory_seal_config", "broker 固定目录必须是绝对路径")
    try:
        info = path.lstat()
    except OSError as exc:
        raise ContractError("research_memory_seal_config", "broker 固定目录不可达") from exc
    if (path.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid
            or info.st_mode & 0o022):
        raise ContractError("research_memory_seal_config", "broker 固定目录 owner/mode 不安全")


def _validate_config(config: ResearchMemorySealConfig) -> None:
    if (type(config.ledger_owner_uid) is not int or config.ledger_owner_uid < 0
            or type(config.trust_owner_uid) is not int or config.trust_owner_uid < 0):
        raise ContractError("research_memory_seal_config", "broker owner uid 不合法")
    if os.geteuid() != config.trust_owner_uid:
        raise ContractError("research_memory_seal_wrong_uid", "seal refresh 必须由 trust owner 执行")
    ledger = Path(config.ledger_path)
    seal = Path(config.seal_path)
    private = Path(config.private_key)
    public = Path(config.public_key)
    if len({ledger, seal, private, public}) != 4:
        raise ContractError("research_memory_seal_config", "broker 固定路径不得重叠")
    _secure_regular(ledger, owner_uid=config.ledger_owner_uid)
    _secure_directory(ledger.parent, owner_uid=config.ledger_owner_uid)
    _secure_directory(seal.parent, owner_uid=config.trust_owner_uid)
    _secure_regular(private, owner_uid=config.trust_owner_uid, private=True)
    _secure_regular(public, owner_uid=config.trust_owner_uid)


def _prefix_bytes(path: Path, length: int) -> bytes:
    lines = path.read_bytes().splitlines(keepends=True)
    if len(lines) < length:
        raise ContractError("research_memory_reseal_refused", "ResearchMemory 被截短，拒绝刷新 seal")
    return b"".join(lines[:length])


def _refresh_locked(config: ResearchMemorySealConfig, request: dict[str, Any],
                    memory: ResearchMemory) -> dict[str, Any]:
    current = memory.seal_core()
    expected = (request["expected_length"], request["expected_head_entry_hash"],
                request["expected_ledger_sha256"])
    observed = (current["length"], current["head_entry_hash"], current["ledger_sha256"])
    if expected != observed:
        raise ContractError("research_memory_refresh_cas", "ResearchMemory 已变化，刷新请求失效")

    seal_path = Path(config.seal_path)
    if seal_path.exists() or seal_path.is_symlink():
        prior_document = memory.read_external_seal(
            seal_path, public_key=Path(config.public_key),
            expected_owner_uid=config.trust_owner_uid)
        prior = prior_document["core"]
        if prior == current:
            document = prior_document
        else:
            if prior["ledger_path"] != current["ledger_path"]:
                raise ContractError("research_memory_reseal_refused",
                                    "既有 seal 属于另一 ResearchMemory 路径")
            prior_length = prior["length"]
            prefix_sha = sha256(_prefix_bytes(Path(config.ledger_path), prior_length))
            if current["length"] < prior_length or prefix_sha != prior["ledger_sha256"]:
                raise ContractError("research_memory_reseal_refused",
                                    "ResearchMemory 不是既有 seal 的 append-only 扩展")
            document = memory.write_external_seal(
                seal_path, private_key=Path(config.private_key),
                public_key=Path(config.public_key))
    else:
        document = memory.write_external_seal(
            seal_path, private_key=Path(config.private_key),
            public_key=Path(config.public_key))

    verified = memory.verify_external_seal(
        seal_path, public_key=Path(config.public_key),
        expected_owner_uid=config.trust_owner_uid)
    receipt_core = {
        "operation": OPERATION,
        "nonce": request["nonce"],
        "length": verified["length"],
        "head_entry_hash": verified["head_entry_hash"],
        "ledger_sha256": verified["ledger_sha256"],
        "seal_core_sha256": sha256(document["core"]),
        "key_id": public_fingerprint(Path(config.public_key)),
    }
    return {**receipt_core, "receipt_id": sha256(receipt_core),
            "sealed_at": document["sealed"]["issued_at"]}


def refresh_research_memory_seal(config: ResearchMemorySealConfig,
                                 request_value: Any) -> dict[str, Any]:
    """Authenticate the prior seal, allow only append-only extension, then refresh.

    A caller cannot choose paths or keys.  Replaying the request after a successful
    refresh is idempotent; rechain, truncation, prior-seal corruption and expectation
    drift all fail closed before the private key is used.  The ledger writer and this
    root operation share one flock, closing the append-between-check-and-sign window.
    """
    request = parse_refresh_request(request_value)
    _validate_config(config)
    memory = ResearchMemory(Path(config.ledger_path), owner_uid=config.ledger_owner_uid)
    with memory.exclusive_lock():
        return _refresh_locked(config, request, memory)
