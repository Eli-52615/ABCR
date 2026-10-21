"""Independent verifier: validates trusted receipts and structural release facts.

信任链第二环:verifier **先验 controller 的签名**(独立重建 core),验不过一律
fail-closed 抛错 —— 绝不产出 attestation。验过之后,verifier 用自己的域
(``DOMAIN_VERIFICATION``)签一份验证证明。域分隔保证一份 test result 证明
无法被当成 verification 证明使用。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from abcr.control.attestation import DOMAIN_VERIFICATION, sign_attestation, verify_attestation
from abcr.control.black_box_oracle import (
    OracleReceipt, SigningIdentity, UNSANDBOXED_LABEL, is_release_eligible_isolation,
)
from abcr.control.contracts import ContractError, require_sha, sha256, strict_object, utc_now
from abcr.control.test_controller import TestResultBundle, verify_test_result_bundle
from abcr.control.policy import effective_mission_risk
from abcr.control.mission_pipeline import (artifact_object_id, load_json_artifact,
                                           seal_json_artifact)
from abcr.control.queue_runtime import WorkBrokerClient


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
                  signer: SigningIdentity,
                  fencing_token: int | None = None) -> VerificationAttestation:
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
    accepted_fence = bundle.fencing_token if fencing_token is None else fencing_token
    core = {"mission_id": bundle.mission_id, "fencing_token": accepted_fence,
            "base_tree_hash": base_tree_hash, "candidate_tree_hash": expected_candidate_tree_hash,
            "profile_hash": expected_profile_hash, "oracle_set_hash": bundle.oracle_set_hash,
            "changed_paths": list(normalized_paths), "verdict": verdict,
            "verified_at": utc_now(), "isolation": bundle.isolation}
    sealed = sign_attestation(private_key=Path(signer.private_key),
                              public_key=Path(signer.public_key),
                              domain=DOMAIN_VERIFICATION, core=core)
    return VerificationAttestation(mission_id=bundle.mission_id, fencing_token=accepted_fence,
                                   base_tree_hash=base_tree_hash,
                                   candidate_tree_hash=expected_candidate_tree_hash,
                                   profile_hash=expected_profile_hash,
                                   oracle_set_hash=bundle.oracle_set_hash,
                                   changed_paths=normalized_paths, verdict=verdict,
                                   verified_at=core["verified_at"],
                                   attestation_hash=sha256(core),
                                   isolation=bundle.isolation, sealed=sealed)


def main(argv: list[str] | None = None) -> int:
    """Consume signed controller bundles from the fenced verify queue."""
    from abcr.control.queue_runtime import queue_main

    def preflight(config: dict) -> None:
        settings = strict_object(config["settings"], required={
            "controller_public_key", "verifier_private_key", "verifier_public_key",
            "path_registry", "trusted_test_result_root", "verification_staging_root"})
        for key in ("controller_public_key", "verifier_private_key", "verifier_public_key"):
            path = Path(settings[key])
            if path.is_symlink() or not path.is_file():
                raise ContractError("verifier_key_missing", f"{key} 不可用")
        if not isinstance(settings["path_registry"], dict):
            raise ContractError("path_registry_invalid", "path registry 不合法")
        for key in ("trusted_test_result_root", "verification_staging_root"):
            path = Path(settings[key])
            if path.is_symlink() or not path.is_dir():
                raise ContractError("verifier_artifact_root_invalid", f"{key} 不可用")

    def decode_bundle(raw: Any) -> TestResultBundle:
        obj = strict_object(raw, required={
            "mission_id", "fencing_token", "candidate_tree_hash",
            "acceptance_profile_hash", "oracle_set_hash", "oracle_receipts",
            "diagnostic_summary", "verdict", "created_at", "bundle_hash",
            "isolation", "sealed"})
        if not isinstance(obj["oracle_receipts"], list):
            raise ContractError("oracle_receipts_invalid", "oracle receipts 不合法")
        receipts = []
        fields = {"oracle_id", "version", "input_hash", "result_hash", "verdict",
                  "reason", "completed_at", "isolation", "sealed"}
        for item in obj["oracle_receipts"]:
            receipts.append(OracleReceipt(**strict_object(item, required=fields)))
        return TestResultBundle(**{**obj, "oracle_receipts": tuple(receipts)})

    def make_handler(config: dict):
        settings = config["settings"]
        signer = SigningIdentity(Path(settings["verifier_private_key"]),
                                 Path(settings["verifier_public_key"]))
        client = WorkBrokerClient(Path(config["broker_socket"]))

        def handle(payload, work_id: str, fencing_token: int) -> dict:
            obj = strict_object(payload, required={"test_result_ref", "source_fencing_token"})
            if type(obj["source_fencing_token"]) is not int or obj["source_fencing_token"] < 1:
                raise ContractError("fencing_token_invalid", "source fencing token 不合法")
            sealed_test = load_json_artifact(
                obj["test_result_ref"], expected_operation="seal_test_result",
                trusted_root=Path(settings["trusted_test_result_root"]),
                filename="test-result.json")
            test_doc = strict_object(sealed_test, required={
                "schema_version", "kind", "bundle", "pipeline_context", "candidate_ref"})
            if test_doc["schema_version"] != 1 or test_doc["kind"] != "test-result":
                raise ContractError("test_artifact_kind_invalid", "test artifact 类型不合法")
            context = strict_object(test_doc["pipeline_context"], required={
                "candidate_id", "base_tree_hash", "changed_paths", "declared_risk",
                "old_release", "expected_version"})
            bundle = decode_bundle(test_doc["bundle"])
            if bundle.mission_id != work_id:
                raise ContractError("mission_work_identity_mismatch", "test artifact identity 漂移")
            expected = {
                "base_tree_hash": context["base_tree_hash"],
                "expected_candidate_tree_hash": bundle.candidate_tree_hash,
                "expected_profile_hash": bundle.acceptance_profile_hash,
                "expected_oracle_registry_hash": bundle.oracle_set_hash,
            }
            for name, value in expected.items():
                require_sha(value, name)
            if (not isinstance(context["changed_paths"], list)
                    or any(not isinstance(item, str) for item in context["changed_paths"])):
                raise ContractError("changed_paths_invalid", "changed paths 不合法")
            if bundle.fencing_token != obj["source_fencing_token"]:
                raise ContractError("fencing_token_mismatch", "bundle fencing token 不一致")
            result = verify_result(
                bundle, base_tree_hash=expected["base_tree_hash"],
                expected_candidate_tree_hash=expected["expected_candidate_tree_hash"],
                expected_profile_hash=expected["expected_profile_hash"],
                expected_oracle_registry_hash=expected["expected_oracle_registry_hash"],
                declared_risk=context["declared_risk"],
                changed_paths=tuple(context["changed_paths"]),
                path_registry=settings["path_registry"],
                controller_public_key=Path(settings["controller_public_key"]), signer=signer,
                fencing_token=fencing_token)
            document = {"schema_version": 1, "kind": "verification",
                        "attestation": asdict(result), "pipeline_context": context,
                        "test_result_ref": obj["test_result_ref"],
                        "candidate_ref": test_doc["candidate_ref"]}
            object_id = artifact_object_id("VER", document)
            reference = seal_json_artifact(
                client, operation="seal_verification",
                staging_root=Path(settings["verification_staging_root"]),
                object_id=object_id, filename="verification.json", document=document,
                nonce=f"verify:{work_id}:{fencing_token}")
            return {"mission_id": work_id, "verdict": result.verdict,
                    "broker_ref": reference}
        return handle

    return queue_main(argv, service="verifier", stage="verify",
                      consumer="abcr-verifier", preflight=preflight,
                      make_handler=make_handler)


if __name__ == "__main__":
    raise SystemExit(main())
