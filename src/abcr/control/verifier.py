"""Independent verifier: validates trusted receipts and structural release facts.

信任链第二环:verifier **先验 controller 的签名**(独立重建 core),验不过一律
fail-closed 抛错 —— 绝不产出 attestation。验过之后,verifier 用自己的域
(``DOMAIN_VERIFICATION``)签一份验证证明。域分隔保证一份 test result 证明
无法被当成 verification 证明使用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from abcr.control.attestation import DOMAIN_VERIFICATION, sign_attestation, verify_attestation
from abcr.control.black_box_oracle import (
    SigningIdentity, UNSANDBOXED_LABEL, is_release_eligible_isolation,
)
from abcr.control.contracts import ContractError, sha256, utc_now
from abcr.control.test_controller import TestResultBundle, verify_test_result_bundle
from abcr.control.policy import effective_mission_risk


@dataclass(frozen=True)
class VerificationAttestation:
    mission_id: str
    fencing_token: int
    base_tree_hash: str
    candidate_tree_hash: str
    profile_hash: str
    oracle_set_hash: str
    changed_paths: tuple[str, ...]
    verdict: str
    verified_at: str
    attestation_hash: str
    isolation: str = UNSANDBOXED_LABEL
    sealed: dict[str, Any] | None = field(default=None)

    @property
    def core(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "fencing_token": self.fencing_token,
                "base_tree_hash": self.base_tree_hash,
                "candidate_tree_hash": self.candidate_tree_hash,
                "profile_hash": self.profile_hash, "oracle_set_hash": self.oracle_set_hash,
                "changed_paths": list(self.changed_paths), "verdict": self.verdict,
                "verified_at": self.verified_at, "isolation": self.isolation}


def verify_verification_attestation(attestation: VerificationAttestation, *,
                                    public_key: Path) -> tuple[bool, str]:
    if not isinstance(attestation.sealed, dict):
        return False, "verification_unsigned"
    return verify_attestation(attestation.sealed, public_key=public_key,
                              domain=DOMAIN_VERIFICATION, expected_core=attestation.core)


def verify_result(bundle: TestResultBundle, *, base_tree_hash: str,
                  expected_candidate_tree_hash: str, expected_profile_hash: str,
                  expected_oracle_registry_hash: str, declared_risk: str,
                  changed_paths: tuple[str, ...],
                  path_registry: dict[str, dict[str, Any]],
                  controller_public_key: Path,
                  signer: SigningIdentity) -> VerificationAttestation:
    # ---- 信任链第一道闸:controller 签名。验不过绝不往下走。 ----
    ok, reason = verify_test_result_bundle(bundle, public_key=Path(controller_public_key))
    if not ok:
        raise ContractError("test_bundle_unverified",
                            f"controller test result bundle 验签失败: {reason}")
    # bundle_hash 仍需自洽(人读一致性),但它不是信任根。
    if sha256(bundle.core) != bundle.bundle_hash:
        raise ContractError("test_bundle_tampered", "controller test result bundle hash 不一致")
    # ---- P0-6:哨兵隔离跑出来的结果一律不得进入发布链路。 ----
    if not is_release_eligible_isolation(bundle.isolation):
        raise ContractError("unsandboxed_result_forbidden",
                            f"候选未在真实沙箱内运行({bundle.isolation}),结果不得用于发布")
    for receipt in bundle.oracle_receipts:
        if not is_release_eligible_isolation(receipt.isolation):
            raise ContractError("unsandboxed_result_forbidden",
                                f"oracle receipt 隔离不合格: {receipt.isolation}")
    if bundle.candidate_tree_hash != expected_candidate_tree_hash:
        raise ContractError("candidate_tree_drift", "candidate tree hash 漂移")
    if bundle.acceptance_profile_hash != expected_profile_hash:
        raise ContractError("profile_drift", "acceptance profile 漂移")
    if bundle.oracle_set_hash != expected_oracle_registry_hash:
        raise ContractError("oracle_registry_drift", "trusted oracle registry 漂移")
    effective_risk, normalized_paths = effective_mission_risk(
        declared_risk, list(changed_paths), path_registry)
    expected_oracle_ids = tuple(sorted({
        oracle_id
        for path in normalized_paths
        for glob, rule in path_registry.items()
        if __import__("fnmatch").fnmatch(path, glob)
        for oracle_id in rule.get("required_external_oracle_ids", [])
    }))
    observed = tuple(x.oracle_id for x in bundle.oracle_receipts)
    receipts_ok = observed == expected_oracle_ids and all(x.verdict == "PASS" for x in bundle.oracle_receipts)
    verdict = "PASS" if bundle.verdict == "PASS" and receipts_ok and effective_risk != "human_required" else (
        "NEEDS_HUMAN" if effective_risk == "human_required" else "FAIL")
    core = {"mission_id": bundle.mission_id, "fencing_token": bundle.fencing_token,
            "base_tree_hash": base_tree_hash, "candidate_tree_hash": expected_candidate_tree_hash,
            "profile_hash": expected_profile_hash, "oracle_set_hash": bundle.oracle_set_hash,
            "changed_paths": list(normalized_paths), "verdict": verdict,
            "verified_at": utc_now(), "isolation": bundle.isolation}
    sealed = sign_attestation(private_key=Path(signer.private_key),
                              public_key=Path(signer.public_key),
                              domain=DOMAIN_VERIFICATION, core=core)
    return VerificationAttestation(mission_id=bundle.mission_id, fencing_token=bundle.fencing_token,
                                   base_tree_hash=base_tree_hash,
                                   candidate_tree_hash=expected_candidate_tree_hash,
                                   profile_hash=expected_profile_hash,
                                   oracle_set_hash=bundle.oracle_set_hash,
                                   changed_paths=normalized_paths, verdict=verdict,
                                   verified_at=core["verified_at"],
                                   attestation_hash=sha256(core),
                                   isolation=bundle.isolation, sealed=sealed)


def main(argv: list[str] | None = None) -> int:
    """Fail closed until signed-result queue and trusted key bindings are frozen."""
    from abcr.control.service_runtime import blocked_runtime_main
    return blocked_runtime_main(argv, service="verifier",
                                required_capability="verify_result",
                                capabilities={"verify_result": verify_result})


if __name__ == "__main__":
    raise SystemExit(main())
