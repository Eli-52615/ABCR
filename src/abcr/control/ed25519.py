"""Ed25519 approval token v2 using the system OpenSSL binary.

Production verification needs only the public key.  The private key path is passed
solely to the human-domain signer process and is never returned or logged.
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from abcr.control.contracts import HEX64, ContractError, canonical_json, require_sha, sha256

OPENSSL_CANDIDATES = (
    "/opt/homebrew/opt/openssl@3/bin/openssl",
    "/opt/homebrew/bin/openssl",
    "/usr/local/opt/openssl@3/bin/openssl",
    "/usr/bin/openssl",
)
GIT_CANDIDATES = (
    "/opt/homebrew/bin/git",
    "/usr/local/bin/git",
    "/usr/bin/git",
)
TOKEN_VERSION = 2
ALGORITHM = "Ed25519"
TOKEN_VERSION_TEXT = "2.0"
APPROVAL_SCOPE = "batch_approve"
CONTEXT_FIELDS = (
    "aud", "deployment_id", "protocol_ref", "request_id", "request_version",
    "source_event_id", "tenant_key_hash", "chat_id_hash", "app_id_hash",
    "decision_nonce_hash", "goal_anchor_entry_hash", "goal_anchor_receipt_id",
    "batch_id", "envelope_sha256", "approver_id_hash",
)

# ---- goal anchor prefix proof (真验证，非存在性检查) ----------------------------
# 语义与 abcr.explore.memory.ResearchMemory 的 append-only 哈希链**逐字一致**：
#   entry_hash = sha256(canonical_json(不含 entry_hash 的整行))，行内含 prev_hash；
#   首行 prev_hash = ANCHOR_GENESIS。
# 该公式在此重算而非 import，是为了让本模块（签名信任根）保持零跨包依赖；
# tests/control/test_ed25519.py::test_anchor_chain_formula_matches_research_memory
# 用真实 ResearchMemory.append() 产出的链钉死两处定义，公式漂移即测试红。
#
# **信任根**：anchor_ledger / research_repo 两个路径来自调用方（operator）的受信配置，
# 绝不来自 bundle。bundle 只能提出主张，主张一律拿这两个外部事实源重算核对。
ANCHOR_GENESIS = "0" * 64
GOAL_ANCHOR_EVENT = "goal_anchor_frozen"
GOAL_ANCHOR_REVOKED_EVENT = "goal_anchor_revoked"
_ANCHOR_PAYLOAD_FIELDS = ("goal_sha256", "goal_path", "research_commit", "receipt_id",
                          "deployment_id", "protocol_ref")


def openssl_path() -> str:
    configured = os.environ.get("ABCR_OPENSSL")
    if configured:
        path = Path(configured)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise ContractError("openssl_path_invalid", "ABCR_OPENSSL 必须指向可执行绝对路径")
        return str(path)
    for candidate in OPENSSL_CANDIDATES:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise ContractError("openssl_missing", "找不到冻结 OpenSSL 可执行文件")


def git_path() -> str:
    configured = os.environ.get("ABCR_GIT")
    if configured:
        path = Path(configured)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise ContractError("git_path_invalid", "ABCR_GIT 必须指向可执行绝对路径")
        return str(path)
    for candidate in GIT_CANDIDATES:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise ContractError("git_missing", "找不到 git 可执行文件（research commit 无法验证）")


def _git(repo: Path, argv: list[str]) -> subprocess.CompletedProcess:
    """只读 git 调用。`-C <repo>` 之后的每个参数都由本模块构造或已通过 hex/路径校验。"""
    return _run([git_path(), "-C", str(repo), *argv])


def _run(argv: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=False, shell=False, timeout=10, env={"PATH": "/usr/bin:/bin"})


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    if not isinstance(text, str) or len(text) != 88 or not text.endswith("=="):
        raise ContractError("bad_signature_encoding", "signature 必须是 padded RFC4648 base64")
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception as exc:
        raise ContractError("bad_signature_encoding", "signature 无法解码") from exc
    if len(raw) != 64 or _b64(raw) != text:
        raise ContractError("bad_signature_encoding", "signature 不是 canonical Ed25519 base64")
    return raw


def public_fingerprint(public_key: Path) -> str:
    info = Path(public_key).lstat()
    if Path(public_key).is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ContractError("public_key_invalid", "public key 必须是单链接 regular file")
    proc = _run([openssl_path(), "pkey", "-pubin", "-in", str(public_key), "-outform", "DER"])
    if proc.returncode != 0:
        raise ContractError("public_key_invalid", "Ed25519 public key 无法解析")
    return sha256(proc.stdout)


def generate_keypair(private_key: Path, public_key: Path) -> None:
    """Fixture/bootstrap helper; normal operator code must never call it."""
    private_key.parent.mkdir(parents=True, exist_ok=True)
    proc = _run([openssl_path(), "genpkey", "-algorithm", "ED25519", "-out", str(private_key)])
    if proc.returncode != 0: raise ContractError("keygen_failed", "OpenSSL Ed25519 keygen failed")
    os.chmod(private_key, 0o600)
    proc = _run([openssl_path(), "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)])
    if proc.returncode != 0: raise ContractError("pubout_failed", "OpenSSL public key export failed")


def _payload(token: dict[str, Any]) -> bytes:
    return canonical_json({key: value for key, value in token.items() if key != "signature_b64"})


def sign_token_v2(*, private_key: Path, public_key: Path, context: dict[str, Any],
                  ttl_seconds: int = 3600, token_id: str | None = None,
                  issued_at: datetime | None = None,
                  now: datetime | None = None) -> dict[str, Any]:
    if set(context) != set(CONTEXT_FIELDS):
        raise ContractError("approval_context_fields", "approval request snapshot 字段不精确")
    for field in ("tenant_key_hash", "chat_id_hash", "app_id_hash", "decision_nonce_hash",
                  "goal_anchor_entry_hash", "envelope_sha256", "approver_id_hash"):
        require_sha(context[field], field)
    if not isinstance(context["request_version"], int) or isinstance(context["request_version"], bool):
        raise ContractError("request_version_invalid", "request_version 必须是整数")
    if context["aud"] != "abcr-operator":
        raise ContractError("approval_aud_invalid", "batch approval aud 必须是 abcr-operator")
    private_info = Path(private_key).lstat()
    if (Path(private_key).is_symlink() or not stat.S_ISREG(private_info.st_mode)
            or private_info.st_nlink != 1 or private_info.st_mode & 0o077):
        raise ContractError("private_key_permissions", "private key 必须是 0600 单链接 regular file")
    if isinstance(ttl_seconds, bool) or not 1 <= ttl_seconds <= 86400:
        raise ContractError("approval_ttl", "approval TTL 必须为 1..86400 秒")
    now = now or datetime.now(timezone.utc)
    issued_at = issued_at or now
    if issued_at.tzinfo is None or issued_at > now + timedelta(seconds=30):
        raise ContractError("issued_at_invalid", "issued_at 不合法")
    token = {"token_version": TOKEN_VERSION_TEXT, "alg": ALGORITHM,
             "key_id": public_fingerprint(public_key), **context,
             "token_id": token_id or secrets.token_hex(16), "scope": APPROVAL_SCOPE,
             "issued_at": issued_at.isoformat(),
             "expires_at": (issued_at + timedelta(seconds=ttl_seconds)).isoformat()}
    with tempfile.TemporaryDirectory(prefix="abcr-sign-") as tmp:
        msg = Path(tmp) / "message"; sig = Path(tmp) / "signature"
        msg.write_bytes(_payload(token))
        proc = _run([openssl_path(), "pkeyutl", "-sign", "-inkey", str(private_key),
                     "-rawin", "-in", str(msg), "-out", str(sig)])
        if proc.returncode != 0: raise ContractError("sign_failed", "Ed25519 签名失败")
        token["signature_b64"] = _b64(sig.read_bytes())
    return token


def verify_token_v2(token: dict[str, Any], *, public_key: Path,
                    expected_context: dict[str, Any],
                    now: datetime | None = None) -> tuple[bool, str]:
    required = {"token_version", "alg", "key_id", "token_id", "scope", "issued_at",
                "expires_at", "signature_b64", *CONTEXT_FIELDS}
    if set(token) != required: return False, "token_fields_mismatch"
    if (token["token_version"] != TOKEN_VERSION_TEXT or token["alg"] != ALGORITHM
            or token["scope"] != APPROVAL_SCOPE):
        return False, "token_protocol_mismatch"
    try: fingerprint = public_fingerprint(public_key)
    except (ContractError, OSError): return False, "public_key_invalid"
    if token["key_id"] != fingerprint: return False, "key_mismatch"
    if set(expected_context) != set(CONTEXT_FIELDS): return False, "expected_context_fields"
    if not all(isinstance(token[k], str) and token[k] for k in required - {"request_version"}):
        return False, "token_value_type"
    if any(token[field] != expected_context[field] for field in CONTEXT_FIELDS):
        return False, "request_snapshot_mismatch"
    try:
        issued = datetime.fromisoformat(token["issued_at"])
        expiry = datetime.fromisoformat(token["expires_at"])
    except (TypeError, ValueError): return False, "bad_expiry"
    if issued.tzinfo is None or expiry.tzinfo is None: return False, "bad_expiry"
    current = now or datetime.now(timezone.utc)
    if issued > current + timedelta(seconds=30): return False, "future_issued"
    if current >= expiry: return False, "expired"
    if expiry <= issued or expiry - issued > timedelta(seconds=86400): return False, "expiry_too_far"
    try: signature = _unb64(token["signature_b64"])
    except ContractError: return False, "bad_signature_encoding"
    with tempfile.TemporaryDirectory(prefix="abcr-verify-") as tmp:
        msg = Path(tmp) / "message"; sig = Path(tmp) / "signature"
        msg.write_bytes(_payload(token)); sig.write_bytes(signature)
        proc = _run([openssl_path(), "pkeyutl", "-verify", "-pubin", "-inkey", str(public_key),
                     "-rawin", "-in", str(msg), "-sigfile", str(sig)])
    return (True, "ok") if proc.returncode == 0 else (False, "bad_signature")


def identity_context_hash(field: str, value: str) -> str:
    """身份类 context 字段的**唯一**取值公式（域分隔）。

    域分隔（把字段名一起哈希）使得 tenant_key 的哈希无法冒充 chat_id 的哈希——
    即便攻击者拿到某个字段的合法取值，也不能把它挪到另一个字段位上。
    """
    if field not in CONTEXT_FIELDS:
        raise ContractError("identity_field_unknown", f"{field} 不是登记的 context 字段")
    if not isinstance(value, str) or not value:
        raise ContractError("identity_value_invalid", f"{field} 的原值必须是非空字符串")
    return sha256({"field": field, "value": value})


def _anchor_entry_hash(row: dict[str, Any]) -> str:
    return sha256({key: value for key, value in row.items() if key != "entry_hash"})


def _strict_json_object(raw: bytes, *, index: int) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in values:
            if key in out:
                raise ValueError(f"duplicate key {key}")
            out[key] = value
        return out
    value = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError(f"row {index} is not an object")
    return value


def verify_anchor_prefix_proof(anchor_ledger: Path, proof: tuple[str, ...]) -> dict[str, Any]:
    """真验证：proof 必须是 anchor_ledger 这条真实哈希链的**前缀**，逐环重算比对。

    proof[i] 必须同时满足两件事(缺一即拒)：
      1) 等于第 i 行内容重算出的 entry_hash —— 改行内容即断；
      2) 等于第 i+1 行的 prev_hash（i=0 时前置为 ANCHOR_GENESIS）—— 改链接即断。
    返回 proof 末端所指向的那一行（goal anchor 行）。
    """
    if not isinstance(proof, tuple) or not proof:
        raise ContractError("anchor_proof_missing", "缺少 goal anchor prefix proof")
    for item in proof:
        if not isinstance(item, str) or HEX64.fullmatch(item) is None:
            raise ContractError("anchor_proof_malformed", "anchor prefix proof 必须是小写 sha256 链")
    path = Path(anchor_ledger)
    if path.is_symlink() or not path.is_file():
        raise ContractError("anchor_ledger_unreachable", "anchor 账本不可达（拒绝跳过验证）")
    try:
        lines = [ln for ln in path.read_bytes().splitlines() if ln.strip()]
    except OSError as exc:
        raise ContractError("anchor_ledger_unreachable", "anchor 账本不可读") from exc
    if len(proof) > len(lines):
        raise ContractError("anchor_proof_too_long", "anchor proof 长于真实链（凭空捏造的尾部）")
    previous = ANCHOR_GENESIS
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(lines):
        try:
            row = _strict_json_object(raw, index=index)
        except (ValueError, TypeError) as exc:
            raise ContractError("anchor_ledger_corrupt", f"anchor 账本第 {index} 行不是 JSON") from exc
        if not isinstance(row, dict) or "entry_hash" not in row or "prev_hash" not in row:
            raise ContractError("anchor_ledger_corrupt", f"anchor 账本第 {index} 行缺少链字段")
        if row["prev_hash"] != previous:
            raise ContractError("anchor_chain_break", f"anchor 链在第 {index} 行断裂（prev_hash 失配）")
        recomputed = _anchor_entry_hash(row)
        if recomputed != row["entry_hash"]:
            raise ContractError("anchor_chain_break", f"anchor 账本第 {index} 行被篡改（entry_hash 失配）")
        if index < len(proof) and proof[index] != recomputed:
            raise ContractError("anchor_proof_mismatch", f"anchor proof 第 {index} 环与真实链不符")
        previous = recomputed
        rows.append(row)
    row = rows[len(proof) - 1]
    if row.get("event_type") != GOAL_ANCHOR_EVENT:
        raise ContractError("anchor_proof_not_goal_anchor",
                            f"anchor proof 末端不是 {GOAL_ANCHOR_EVENT} 行")
    payload = row.get("payload")
    if not isinstance(payload, dict) or any(
            not isinstance(payload.get(key), str) or not payload.get(key)
            for key in _ANCHOR_PAYLOAD_FIELDS):
        raise ContractError("anchor_payload_invalid", "goal anchor 行缺少必需 payload 字段")

    # A valid prefix is not automatically a current authorization.  Validate the
    # complete configured chain above, then require this row to remain the newest
    # unretracted anchor for the same goal.  Otherwise a caller could present a short
    # historic prefix and resurrect an anchor superseded or revoked later in the file.
    subject_id = row.get("subject_id")
    if not isinstance(subject_id, str) or not subject_id:
        raise ContractError("anchor_subject_invalid", "goal anchor 缺少 subject_id")
    for later in rows[len(proof):]:
        same_subject = later.get("subject_id") == subject_id
        if same_subject and later.get("event_type") == GOAL_ANCHOR_EVENT:
            raise ContractError("anchor_not_latest", "goal anchor 已被同一 goal 的更新锚替代")
        if later.get("event_type") == GOAL_ANCHOR_REVOKED_EVENT:
            revocation = later.get("payload")
            if not isinstance(revocation, dict):
                if same_subject:
                    raise ContractError("anchor_revocation_invalid", "goal anchor 撤销记录 payload 非法")
                continue
            target_hash = revocation.get("target_entry_hash")
            target_receipt = revocation.get("receipt_id")
            if target_hash is not None and (not isinstance(target_hash, str)
                                            or HEX64.fullmatch(target_hash) is None):
                if same_subject:
                    raise ContractError("anchor_revocation_invalid", "撤销 target_entry_hash 非法")
                continue
            if target_receipt is not None and (not isinstance(target_receipt, str)
                                               or not target_receipt):
                if same_subject:
                    raise ContractError("anchor_revocation_invalid", "撤销 receipt_id 非法")
                continue
            if target_hash is None and target_receipt is None:
                if same_subject:
                    raise ContractError("anchor_revocation_invalid", "撤销记录缺少目标")
                continue
            if target_hash == row["entry_hash"] or target_receipt == payload["receipt_id"]:
                raise ContractError("anchor_revoked", "goal anchor 已被撤销")
    return row


def verify_research_commit(research_repo: Path, *, research_commit: str, goal_path: str,
                           goal_sha256: str) -> bytes:
    """真验证：commit 对象必须在 research_repo 中真实存在，且该 commit 下的 goal 文件
    字节 sha256 必须等于 goal_sha256。仓库不可达 = 硬错误，**没有跳过分支**。"""
    require_sha(goal_sha256, "goal_sha256")
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", research_commit or "") is None:
        raise ContractError("research_commit_invalid", "research commit 必须是完整十六进制对象 id")
    candidate = Path(goal_path)
    if candidate.is_absolute() or ".." in candidate.parts or goal_path.startswith("-"):
        raise ContractError("bad_goal_path", "goal path 必须是规范相对路径")
    repo = Path(research_repo)
    if not repo.is_dir():
        raise ContractError("research_repo_unreachable", "research repo 路径不可达（拒绝跳过验证）")
    probe = _git(repo, ["rev-parse", "--git-dir"])
    if probe.returncode != 0:
        raise ContractError("research_repo_unreachable", "research repo 不是 git 仓库（拒绝跳过验证）")
    resolved = _git(repo, ["rev-parse", "--verify", "--end-of-options", f"{research_commit}^{{commit}}"])
    if resolved.returncode != 0:
        raise ContractError("research_commit_unknown", "research commit 在 research repo 中不存在")
    if resolved.stdout.decode("ascii", "replace").strip() != research_commit:
        raise ContractError("research_commit_unknown", "research commit 未解析到同一对象 id")
    blob = _git(repo, ["cat-file", "blob", f"{research_commit}:{goal_path}"])
    if blob.returncode != 0:
        raise ContractError("goal_blob_missing", "goal 文件在该 commit 下不存在")
    if sha256(blob.stdout) != goal_sha256:
        raise ContractError("goal_blob_mismatch", "该 commit 下的 goal 文件字节与 goal_sha256 不一致")
    return blob.stdout


ENVELOPE_BATCH_PREFIX = "EXP-"  # compile_goal 的自证前缀（batch_id = 前缀 + sha256(core)[:20]）
ENVELOPE_BATCH_DIGEST_LEN = 20


@dataclass(frozen=True)
class VerifiedAnchor:
    """validate() 的产物：**重算过的**事实，供 decide() 拿去钉 context。

    deployment_id / protocol_ref 亦是重算事实：envelope 自证值必须与 root-sealed
    ResearchMemory anchor 逐字相等，才可进入 token 的 CONTEXT_FIELDS。
    """
    goal_anchor_entry_hash: str
    goal_anchor_receipt_id: str
    research_commit: str
    goal_sha256: str
    request_id: str
    batch_id: str
    envelope_sha256: str
    deployment_id: str
    protocol_ref: str


@dataclass(frozen=True)
class ApprovalRequestBundle:
    request_id: str
    goal_bytes_b64: str
    goal_sha256: str
    research_commit: str
    artifact_frozen_receipt: dict[str, Any]
    envelope: dict[str, Any]
    envelope_sha256: str
    anchor_prefix_proof: tuple[str, ...]

    def validate(self, *, research_repo: Path, anchor_ledger: Path,
                 anchor_seal_path: Path | None = None,
                 anchor_sealer_public_key: Path | None = None,
                 anchor_seal_owner_uid: int = 0,
                 anchor_ledger_owner_uid: int | None = None,
                 allow_unsealed_fixture: bool = False) -> VerifiedAnchor:
        """把 bundle 的每一条主张拿外部事实源重算核对，返回**重算出的**事实。

        research_repo / anchor_ledger 是必填的受信配置路径：不可达即硬错误，
        没有「路径缺失就退化为形状检查」的分支——那正是本缺陷的成因。
        """
        if not allow_unsealed_fixture:
            if anchor_seal_path is None or anchor_sealer_public_key is None:
                raise ContractError("research_memory_seal_required",
                                    "生产审批必须验证 root-owned ResearchMemory 外部 seal")
            # Local import avoids putting the append-only research package on the
            # token-verification module's import path at process start.
            from abcr.explore.memory import ResearchMemory
            ResearchMemory(Path(anchor_ledger), owner_uid=anchor_ledger_owner_uid).verify_external_seal(
                Path(anchor_seal_path), public_key=Path(anchor_sealer_public_key),
                expected_owner_uid=anchor_seal_owner_uid)
        elif anchor_seal_path is not None or anchor_sealer_public_key is not None:
            raise ContractError("research_memory_seal_config",
                                "fixture bypass 与外部 seal 参数不可混用")
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ContractError("request_id_invalid", "approval request id 缺失")
        require_sha(self.goal_sha256, "goal_sha256")
        require_sha(self.envelope_sha256, "envelope_sha256")
        if not isinstance(self.research_commit, str) or re.fullmatch(
                r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.research_commit) is None:
            raise ContractError("research_commit_invalid", "research commit 必须是完整十六进制对象 id")

        # goal 字节：base64 必须 canonical 回环（P2：Zm9vYh== 这类非规范尾比特必须拒）
        if not isinstance(self.goal_bytes_b64, str):
            raise ContractError("goal_bytes_encoding", "goal bytes base64 非法")
        try: goal_bytes = base64.b64decode(self.goal_bytes_b64, validate=True)
        except Exception as exc: raise ContractError("goal_bytes_encoding", "goal bytes base64 非法") from exc
        if _b64(goal_bytes) != self.goal_bytes_b64:
            raise ContractError("goal_bytes_encoding", "goal bytes 不是 canonical base64")
        if sha256(goal_bytes) != self.goal_sha256: raise ContractError("goal_bytes_mismatch", "goal bytes hash 不一致")
        if sha256(self.envelope) != self.envelope_sha256: raise ContractError("envelope_bytes_mismatch", "envelope hash 不一致")
        if not isinstance(self.envelope, dict) or not isinstance(self.envelope.get("batch_id"), str) \
                or not self.envelope["batch_id"]:
            raise ContractError("envelope_batch_id_missing", "envelope 缺少 batch_id")
        if not isinstance(self.artifact_frozen_receipt, dict):
            raise ContractError("artifact_receipt_mismatch", "artifact_frozen receipt 不匹配")
        if self.artifact_frozen_receipt.get("goal_hash") != self.goal_sha256:
            raise ContractError("artifact_receipt_mismatch", "artifact_frozen receipt 不匹配")
        if self.artifact_frozen_receipt.get("research_commit") != self.research_commit:
            raise ContractError("artifact_receipt_mismatch", "receipt 的 research_commit 与 bundle 不一致")
        receipt_id = self.artifact_frozen_receipt.get("receipt_id")
        if not isinstance(receipt_id, str) or not receipt_id:
            raise ContractError("artifact_receipt_mismatch", "receipt 缺少 receipt_id")

        # 1) anchor prefix proof 必须是真实链的前缀，逐环重算（不是「非空字符串」检查）
        anchor_row = verify_anchor_prefix_proof(anchor_ledger, self.anchor_prefix_proof)
        payload = anchor_row["payload"]
        # 2) bundle 的主张必须与链上 anchor 行逐字段一致（链是真，bundle 是主张）
        if payload["goal_sha256"] != self.goal_sha256:
            raise ContractError("anchor_goal_mismatch", "anchor 行的 goal_sha256 与 bundle 不一致")
        if payload["research_commit"] != self.research_commit:
            raise ContractError("anchor_commit_mismatch", "anchor 行的 research_commit 与 bundle 不一致")
        if payload["receipt_id"] != receipt_id:
            raise ContractError("anchor_receipt_mismatch", "anchor 行的 receipt_id 与 receipt 不一致")
        # 3) research commit 必须真实存在，且该 commit 下的 goal 文件字节 hash 对得上。
        #    goal_path 取自**链上**（受信）而非 bundle（可控），杜绝换路径打靶。
        committed = verify_research_commit(research_repo, research_commit=self.research_commit,
                                           goal_path=payload["goal_path"],
                                           goal_sha256=self.goal_sha256)
        if committed != goal_bytes:
            raise ContractError("goal_bytes_mismatch", "goal bytes 与 commit 内字节不一致")

        # 4) 被批之物必须可证明地属于被锚定的 goal（F1 修复）。
        #    envelope 是 compile_goal 的产物，自带 goal 身份字段
        #    （goal_hash / research_commit / goal_receipt_id），且 batch_id 是对
        #    envelope 其余全部字段的自证哈希（batch_id = "EXP-"+sha256(core)[:20]）。
        #    bundle 不可信 → 逐条把 envelope 钉死在**已重算的**锚定事实上。签名前拒。
        deployment_id, protocol_ref = self._verify_envelope_binds_goal(receipt_id)
        if payload["deployment_id"] != deployment_id:
            raise ContractError("anchor_deployment_mismatch",
                                "envelope deployment_id 未锚定到 ResearchMemory")
        if payload["protocol_ref"] != protocol_ref:
            raise ContractError("anchor_protocol_mismatch",
                                "envelope protocol_ref 未锚定到 ResearchMemory")
        return VerifiedAnchor(
            goal_anchor_entry_hash=anchor_row["entry_hash"], goal_anchor_receipt_id=receipt_id,
            research_commit=self.research_commit, goal_sha256=self.goal_sha256,
            request_id=self.request_id, batch_id=self.envelope["batch_id"],
            envelope_sha256=self.envelope_sha256,
            deployment_id=deployment_id, protocol_ref=protocol_ref)

    def _verify_envelope_binds_goal(self, receipt_id: str) -> tuple[str, str]:
        """envelope 的 goal 身份、自证 batch_id、request_id 绑定校验。

        返回 (deployment_id, protocol_ref)——被锚 goal 所覆盖的、可安全进 token 的取值。
        任一不符即在**出卡片/签名之前**拒绝。goal_sha256 / research_commit 已在上游
        被重算并与链核对，故此处用 self.goal_sha256 / self.research_commit 即锚定事实。
        """
        env = self.envelope
        if env.get("goal_hash") != self.goal_sha256:
            raise ContractError("envelope_goal_mismatch",
                                "envelope 的 goal_hash 与被锚定 goal 不一致")
        if env.get("research_commit") != self.research_commit:
            raise ContractError("envelope_commit_mismatch",
                                "envelope 的 research_commit 与被锚定 goal 不一致")
        if env.get("goal_receipt_id") != receipt_id:
            raise ContractError("envelope_receipt_mismatch",
                                "envelope 的 goal_receipt_id 与锚定 receipt 不一致")
        # batch_id 自证：等于 compile_goal 对 envelope 其余字段的确定性派生。杜绝
        # 攻击者把自撰 batch_id（如 "b-attacker-chosen"）塞进被批准物。
        batch_id = env["batch_id"]
        core = {key: value for key, value in env.items() if key != "batch_id"}
        expected_batch = ENVELOPE_BATCH_PREFIX + sha256(core)[:ENVELOPE_BATCH_DIGEST_LEN]
        if batch_id != expected_batch:
            raise ContractError("envelope_batch_id_forged",
                                "batch_id 不是 envelope 的自证派生（疑似自撰 batch）")
        # deployment_id / protocol_ref 是被自证 batch 覆盖的非空字符串；它们进 token
        # 的唯一来源即此处（decide 不得旁路直接读 bundle.envelope）。
        for key in ("deployment_id", "protocol_ref"):
            if not isinstance(env.get(key), str) or not env[key]:
                raise ContractError("envelope_field_missing", f"envelope 缺少 {key}")
        # request_id 必须绑定到被锚 goal 的自证 batch，不能是自由值。
        if self.request_id != batch_id:
            raise ContractError("request_id_unbound",
                                "request_id 必须等于被锚定 goal 的自证 batch_id")
        return env["deployment_id"], env["protocol_ref"]
