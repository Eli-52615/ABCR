"""Trusted parent-process black-box oracles for candidate verification.

Candidate stdout, JUnit and exit status are data, never verdicts.  A PASS exists
only after the trusted parent completes every frozen oracle assertion.

隔离是**强制**的,不是可选项。``run_external_oracle`` 的 ``isolation`` 参数没有
默认值:调用方要么给出真实 sandbox profile 路径,要么显式传入
``FIXTURE_UNSANDBOXED`` 哨兵。哨兵会被记录进 receipt 并对下游可见,而下游
(``verify_result`` / ``prepare_release``)一律拒绝用哨兵跑出的结果发布 ——
fixture 跑得动,但绝无可能悄悄发布出去。

Receipt 本身由受信父进程用域分隔 Ed25519 签名。裸 sha256 是自证哈希,任何人
都能重算;只有签名能证明「这份 receipt 出自真的跑过 oracle 的父进程」。
"""
from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from abcr.control.attestation import DOMAIN_ORACLE_RECEIPT, sign_attestation, verify_attestation
from abcr.control.contracts import ContractError, canonical_json, sha256, utc_now


@dataclass(frozen=True)
class SigningIdentity:
    """受信父进程的签名身份。private key 只在签名进程内使用。"""
    private_key: Path
    public_key: Path


class _FixtureUnsandboxed:
    """显式哨兵。必须被 import 出来使用 —— 裸字符串不接受,防止手滑绕过隔离。"""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "FIXTURE_UNSANDBOXED"


FIXTURE_UNSANDBOXED = _FixtureUnsandboxed()
UNSANDBOXED_LABEL = "FIXTURE_UNSANDBOXED"
SANDBOX_LABEL_PREFIX = "sandbox-exec:"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"

Isolation = "str | _FixtureUnsandboxed"


def isolation_label(isolation: Any) -> str:
    """把 isolation 参数规约成一个可记录、可被下游判定的标签。

    fail-closed:任何无法确认为真实 sandbox profile 的取值都退化成哨兵标签,
    因此绝不会有「看起来像沙箱但其实没沙箱」的结果通过下游闸。
    """
    if isolation is FIXTURE_UNSANDBOXED:
        return UNSANDBOXED_LABEL
    if isinstance(isolation, _FixtureUnsandboxed):
        return UNSANDBOXED_LABEL
    if not isinstance(isolation, (str, Path)) or not str(isolation):
        raise ContractError("isolation_required",
                            "isolation 必须是 sandbox profile 路径或 FIXTURE_UNSANDBOXED 哨兵")
    if str(isolation) == UNSANDBOXED_LABEL:
        # 字符串形态的哨兵不接受:哨兵必须是显式 import 的对象。
        raise ContractError("isolation_sentinel_must_be_object",
                            "FIXTURE_UNSANDBOXED 必须传对象而非字符串")
    profile = Path(os.path.abspath(str(isolation)))
    if profile.is_symlink() or not profile.is_file():
        return UNSANDBOXED_LABEL
    try:
        return SANDBOX_LABEL_PREFIX + sha256(profile.read_bytes())
    except OSError:
        return UNSANDBOXED_LABEL


def is_release_eligible_isolation(label: Any) -> bool:
    """只有真实 sandbox profile 跑出来的结果才允许进入发布链路。"""
    return (isinstance(label, str) and label.startswith(SANDBOX_LABEL_PREFIX)
            and len(label) == len(SANDBOX_LABEL_PREFIX) + 64)


@dataclass(frozen=True)
class OracleSpec:
    oracle_id: str
    version: str
    request: dict[str, Any]
    timeout_seconds: float = 5.0
    max_response_bytes: int = 65536


@dataclass(frozen=True)
class OracleReceipt:
    oracle_id: str
    version: str
    input_hash: str
    result_hash: str | None
    verdict: str
    reason: str
    completed_at: str
    isolation: str = UNSANDBOXED_LABEL
    sealed: dict[str, Any] | None = field(default=None)

    @property
    def core(self) -> dict[str, Any]:
        """签名载荷 —— 不含 sealed 自身。"""
        return {"oracle_id": self.oracle_id, "version": self.version,
                "input_hash": self.input_hash, "result_hash": self.result_hash,
                "verdict": self.verdict, "reason": self.reason,
                "completed_at": self.completed_at, "isolation": self.isolation}

    def as_dict(self) -> dict[str, Any]:
        return {**self.core, "sealed": self.sealed}


def verify_oracle_receipt(receipt: OracleReceipt, *, public_key: Path) -> tuple[bool, str]:
    """独立重建 core 后验签。fail-closed。"""
    if not isinstance(receipt.sealed, dict):
        return False, "oracle_receipt_unsigned"
    return verify_attestation(receipt.sealed, public_key=public_key,
                              domain=DOMAIN_ORACLE_RECEIPT, expected_core=receipt.core)


OracleAssertion = Callable[[dict[str, Any], Any], tuple[bool, str]]


def _strict_json(raw: bytes) -> Any:
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out: raise ValueError("duplicate key")
            out[key] = value
        return out
    def constant(value): raise ValueError(f"non-finite constant {value}")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


class OracleRegistry:
    def __init__(self): self._assertions: dict[tuple[str, str], OracleAssertion] = {}

    def register(self, oracle_id: str, version: str, assertion: OracleAssertion) -> None:
        key = (oracle_id, version)
        if key in self._assertions: raise ContractError("oracle_duplicate", "oracle 已登记")
        self._assertions[key] = assertion

    def get(self, oracle_id: str, version: str) -> OracleAssertion:
        try: return self._assertions[(oracle_id, version)]
        except KeyError as exc: raise ContractError("oracle_unknown", "oracle id/version 未冻结") from exc

    @property
    def registry_hash(self) -> str:
        return sha256(sorted(f"{a}:{b}" for a, b in self._assertions))


def run_external_oracle(spec: OracleSpec, candidate_argv: tuple[str, ...],
                        registry: OracleRegistry, *,
                        isolation: Any,
                        signer: SigningIdentity,
                        cwd: str | None = None,
                        candidate_uid: int | None = None,
                        candidate_gid: int | None = None,
                        sandbox_params: dict[str, str] | None = None) -> OracleReceipt:
    """跑一个受信 oracle。``isolation`` 与 ``signer`` 都是必填。"""
    assertion = registry.get(spec.oracle_id, spec.version)
    label = isolation_label(isolation)
    nonce = secrets.token_hex(32)
    request = {"protocol": "abcr-oracle-v1", "oracle_id": spec.oracle_id,
               "version": spec.version, "nonce": nonce, "request": spec.request}
    raw = canonical_json(request) + b"\n"
    base = {"oracle_id": spec.oracle_id, "version": spec.version,
            "input_hash": sha256(raw), "completed_at": utc_now(), "isolation": label}

    def finish(*, result_hash: str | None, verdict: str, reason: str) -> OracleReceipt:
        receipt = OracleReceipt(**base, result_hash=result_hash, verdict=verdict, reason=reason)
        sealed = sign_attestation(private_key=Path(signer.private_key),
                                  public_key=Path(signer.public_key),
                                  domain=DOMAIN_ORACLE_RECEIPT, core=receipt.core)
        return OracleReceipt(**base, result_hash=result_hash, verdict=verdict,
                             reason=reason, sealed=sealed)

    if not candidate_argv or any(not isinstance(x, str) or "\x00" in x for x in candidate_argv):
        return finish(result_hash=None, verdict="FAIL", reason="invalid_candidate_argv")
    if os.geteuid() == 0 and (candidate_uid is None or candidate_gid is None or candidate_uid == 0):
        return finish(result_hash=None, verdict="FAIL", reason="root_candidate_forbidden")
    if os.geteuid() != 0 and candidate_uid not in {None, os.geteuid()}:
        return finish(result_hash=None, verdict="FAIL", reason="candidate_uid_unavailable")
    argv = list(candidate_argv)
    if label != UNSANDBOXED_LABEL:
        profile = os.path.abspath(str(isolation))
        if not os.path.isfile(SANDBOX_EXEC) or not os.access(SANDBOX_EXEC, os.X_OK):
            return finish(result_hash=None, verdict="FAIL", reason="sandbox_exec_unavailable")
        params: list[str] = []
        for key, value in sorted((sandbox_params or {}).items()):
            if not isinstance(key, str) or not isinstance(value, str) or "=" in key:
                return finish(result_hash=None, verdict="FAIL", reason="sandbox_param_invalid")
            params += ["-D", f"{key}={value}"]
        argv = [SANDBOX_EXEC, "-f", profile, *params, *argv]
    elif isolation is not FIXTURE_UNSANDBOXED and not isinstance(isolation, _FixtureUnsandboxed):
        # 请求了真沙箱但 profile 不可用 —— 绝不静默降级成裸跑。
        return finish(result_hash=None, verdict="FAIL", reason="sandbox_profile_invalid")

    def drop_privileges() -> None:
        if os.geteuid() == 0:
            os.setgroups([])
            os.setgid(int(candidate_gid))
            os.setuid(int(candidate_uid))
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, shell=False, start_new_session=True,
                                cwd=cwd, env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                                preexec_fn=drop_privileges if os.geteuid() == 0 else None)
        stdout, _ = proc.communicate(raw, timeout=spec.timeout_seconds)
    except subprocess.TimeoutExpired:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        proc.communicate()
        return finish(result_hash=None, verdict="FAIL", reason="timeout")
    except OSError:
        return finish(result_hash=None, verdict="FAIL", reason="candidate_exec_error")
    if len(stdout) > spec.max_response_bytes:
        return finish(result_hash=None, verdict="FAIL", reason="response_too_large")
    # Exit 0 is intentionally irrelevant; missing a complete framed response still fails.
    lines = stdout.splitlines()
    if len(lines) != 1:
        return finish(result_hash=None, verdict="FAIL", reason="missing_or_extra_response")
    try:
        response = _strict_json(lines[0])
    except (ValueError, UnicodeDecodeError, RecursionError):
        return finish(result_hash=None, verdict="FAIL", reason="invalid_json_response")
    if not isinstance(response, dict) or set(response) != {"nonce", "result"} or response["nonce"] != nonce:
        return finish(result_hash=None, verdict="FAIL", reason="response_binding_mismatch")
    try:
        ok, reason = assertion(spec.request, response["result"])
        result_hash = sha256(response)
    except Exception:
        return finish(result_hash=sha256(lines[0]), verdict="FAIL", reason="trusted_assertion_error")
    return finish(result_hash=result_hash, verdict="PASS" if ok else "FAIL", reason=reason)


def equality_assertion(request: dict[str, Any], result: Any) -> tuple[bool, str]:
    return (result == request.get("expected"), "equal" if result == request.get("expected") else "not_equal")
