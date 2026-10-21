"""Root-side controller bundle; in-candidate diagnostics cannot authorize release.

信任链第一环:controller 跑完全部受信 oracle 后,用域分隔 Ed25519 **签名**这份
test result bundle。``bundle_hash`` 依然保留供人读,但它是自证哈希,不再是信任
根 —— 攻击者能重算 sha256,重算不出签名。
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from abcr.control.attestation import DOMAIN_TEST_RESULT, sign_attestation, verify_attestation
from abcr.control.black_box_oracle import (
    OracleReceipt, OracleRegistry, OracleSpec, SigningIdentity, isolation_label,
    run_external_oracle, verify_oracle_receipt,
)
from abcr.control.contracts import canonical_json, sha256, utc_now


@dataclass(frozen=True)
class TestResultBundle:
    mission_id: str
    fencing_token: int
    candidate_tree_hash: str
    acceptance_profile_hash: str
    oracle_set_hash: str
    oracle_receipts: tuple[OracleReceipt, ...]
    diagnostic_summary: dict[str, Any]
    verdict: str
    created_at: str
    bundle_hash: str
    isolation: str
    sealed: dict[str, Any] | None = field(default=None)

    @property
    def core(self) -> dict[str, Any]:
        """签名载荷 —— 由消费方独立重建后比对。"""
        return {"mission_id": self.mission_id, "fencing_token": self.fencing_token,
                "candidate_tree_hash": self.candidate_tree_hash,
                "acceptance_profile_hash": self.acceptance_profile_hash,
                "oracle_set_hash": self.oracle_set_hash,
                "oracle_receipts": [x.as_dict() for x in self.oracle_receipts],
                "diagnostic_summary": self.diagnostic_summary, "verdict": self.verdict,
                "created_at": self.created_at, "isolation": self.isolation}


def verify_test_result_bundle(bundle: TestResultBundle, *,
                              public_key: Path) -> tuple[bool, str]:
    """验签 bundle 本身 + 其中每一份 oracle receipt。fail-closed。"""
    if not isinstance(bundle.sealed, dict):
        return False, "test_bundle_unsigned"
    ok, reason = verify_attestation(bundle.sealed, public_key=public_key,
                                    domain=DOMAIN_TEST_RESULT, expected_core=bundle.core)
    if not ok:
        return False, reason
    for receipt in bundle.oracle_receipts:
        ok, reason = verify_oracle_receipt(receipt, public_key=public_key)
        if not ok:
            return False, f"oracle_receipt:{reason}"
    return True, "ok"


def run_profile(*, mission_id: str, fencing_token: int, candidate_tree_hash: str,
                profile: dict[str, Any], candidate_argv: tuple[str, ...],
                registry: OracleRegistry, isolation: Any, signer: SigningIdentity,
                diagnostic_summary: dict[str, Any] | None = None,
                cwd: str | None = None, candidate_uid: int | None = None,
                candidate_gid: int | None = None,
                sandbox_params: dict[str, str] | None = None) -> TestResultBundle:
    label = isolation_label(isolation)
    specs = tuple(OracleSpec(**raw) for raw in profile.get("external_oracles", []))
    required = tuple(profile.get("required_external_oracle_ids", []))
    if not required or set(required) != {x.oracle_id for x in specs}:
        receipts: tuple[OracleReceipt, ...] = ()
        verdict = "FAIL"
    else:
        receipts = tuple(run_external_oracle(
            spec, candidate_argv, registry, isolation=isolation, signer=signer, cwd=cwd,
            candidate_uid=candidate_uid, candidate_gid=candidate_gid,
            sandbox_params=sandbox_params,
        ) for spec in specs)
        verdict = "PASS" if all(x.verdict == "PASS" for x in receipts) else "FAIL"
    # 自查:任何一份 receipt 验签失败或隔离标签不一致,整份 bundle 降级为 FAIL。
    for receipt in receipts:
        ok, _ = verify_oracle_receipt(receipt, public_key=Path(signer.public_key))
        if not ok or receipt.isolation != label:
            verdict = "FAIL"
            break
    core = {"mission_id": mission_id, "fencing_token": fencing_token,
            "candidate_tree_hash": candidate_tree_hash,
            "acceptance_profile_hash": sha256(profile), "oracle_set_hash": registry.registry_hash,
            "oracle_receipts": [x.as_dict() for x in receipts],
            "diagnostic_summary": diagnostic_summary or {}, "verdict": verdict,
            "created_at": utc_now(), "isolation": label}
    sealed = sign_attestation(private_key=Path(signer.private_key),
                              public_key=Path(signer.public_key),
                              domain=DOMAIN_TEST_RESULT, core=core)
    return TestResultBundle(mission_id=mission_id, fencing_token=fencing_token,
                            candidate_tree_hash=candidate_tree_hash,
                            acceptance_profile_hash=core["acceptance_profile_hash"],
                            oracle_set_hash=core["oracle_set_hash"], oracle_receipts=receipts,
                            diagnostic_summary=core["diagnostic_summary"], verdict=verdict,
                            created_at=core["created_at"], bundle_hash=sha256(core),
                            isolation=label, sealed=sealed)


def seal_result(bundle: TestResultBundle, staging_root: Path) -> Path:
    root = Path(staging_root); root.mkdir(parents=True, exist_ok=True)
    final = root / f"{bundle.mission_id}-{bundle.fencing_token}.json"
    raw = canonical_json({**bundle.core, "bundle_hash": bundle.bundle_hash,
                          "sealed": bundle.sealed}) + b"\n"
    tmp = final.with_name(f".{final.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("xb") as fh:
            fh.write(raw); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, final); os.chmod(final, 0o440)
    finally: tmp.unlink(missing_ok=True)
    return final


def main(argv: list[str] | None = None) -> int:
    """Fail closed until the root controller queue/oracle binding is frozen."""
    from abcr.control.service_runtime import blocked_runtime_main
    return blocked_runtime_main(argv, service="test-controller",
                                required_capability="run_profile",
                                capabilities={"run_profile": run_profile})


if __name__ == "__main__":
    raise SystemExit(main())
