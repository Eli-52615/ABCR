"""Root-side controller bundle; in-candidate diagnostics cannot authorize release.

信任链第一环:controller 跑完全部受信 oracle 后,用域分隔 Ed25519 **签名**这份
test result bundle。``bundle_hash`` 依然保留供人读,但它是自证哈希,不再是信任
根 —— 攻击者能重算 sha256,重算不出签名。
"""
from __future__ import annotations

import os
import uuid
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from abcr.control.attestation import DOMAIN_TEST_RESULT, sign_attestation, verify_attestation
from abcr.control.black_box_oracle import (
    OracleReceipt, OracleRegistry, OracleSpec, SigningIdentity, isolation_label,
    run_external_oracle, verify_oracle_receipt,
)
from abcr.control.contracts import ContractError, canonical_json, require_id, require_sha, sha256, strict_object, utc_now
from abcr.control.mission_pipeline import (artifact_object_id, resolve_sealed_tree,
                                           seal_json_artifact)
from abcr.control.worktree import scan_tree, tree_hash
from abcr.control.worktree import export_plain_tree
from abcr.control.queue_runtime import WorkBrokerClient


CANDIDATE_ROOT_TOKEN = "{candidate_root}"
CANDIDATE_ADAPTER_MODULE = "abcr.control.candidate_oracle_adapter"
CANDIDATE_ADAPTER_RELPATH = (
    "env/lib/python3.12/site-packages/abcr/control/candidate_oracle_adapter.py")
FROZEN_CANDIDATE_ARGV_TEMPLATE = (
    CANDIDATE_ROOT_TOKEN + "/env/bin/python", "-I", "-m",
    CANDIDATE_ADAPTER_MODULE,
)


def validate_candidate_argv_template(value: Any) -> tuple[str, ...]:
    """Accept the one reviewed template; configuration cannot add an argv."""
    if (not isinstance(value, list) or tuple(value) != FROZEN_CANDIDATE_ARGV_TEMPLATE
            or sum(item.count(CANDIDATE_ROOT_TOKEN) for item in value
                   if isinstance(item, str)) != 1):
        raise ContractError("candidate_argv_template_invalid",
                            "candidate argv template 必须是冻结 runtime adapter")
    return tuple(value)


def resolve_candidate_argv(template: Any, run_tree: Path, *,
                           expected_tree_hash: str, candidate_uid: int,
                           candidate_gid: int) -> tuple[str, ...]:
    """Bind the fixed template to the controller-created immutable run tree.

    The work payload contributes no path or argv byte.  The executable and
    adapter must both be regular files in the exact candidate tree whose hash
    the controller already committed to the signed result.
    """
    frozen = validate_candidate_argv_template(template)
    require_sha(expected_tree_hash, "candidate_tree_hash")
    root = Path(run_tree)
    root_info = root.lstat()
    if (root.is_symlink() or not stat.S_ISDIR(root_info.st_mode)
            or root.resolve() != root.absolute()
            or root_info.st_uid != candidate_uid or root_info.st_gid != candidate_gid
            or stat.S_IMODE(root_info.st_mode) != 0o500):
        raise ContractError("candidate_run_root_unsafe", "candidate run tree owner/mode 不安全")
    entries = scan_tree(root)
    if tree_hash(entries) != expected_tree_hash:
        raise ContractError("candidate_run_copy_drift", "candidate execution copy 漂移")
    # ``TreeEntry`` intentionally commits file modes but not Unix ownership or
    # directory metadata.  Check those properties separately so changing uid,
    # gid, or a directory mode cannot preserve the hash and enter the sandbox.
    # The seal broker and the controller both normalize this exact shape:
    # directories 0500, executable files 0550, data/code files 0440.
    for directory, names, files in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        current_info = current.lstat()
        if (current.is_symlink() or not stat.S_ISDIR(current_info.st_mode)
                or current_info.st_uid != candidate_uid
                or current_info.st_gid != candidate_gid
                or stat.S_IMODE(current_info.st_mode) != 0o500):
            raise ContractError("candidate_run_tree_unsafe",
                                "candidate run tree directory owner/mode 不安全")
        for name in (*names, *files):
            child = current / name
            child_info = child.lstat()
            if name in names:
                if (child.is_symlink() or not stat.S_ISDIR(child_info.st_mode)
                        or child_info.st_uid != candidate_uid
                        or child_info.st_gid != candidate_gid
                        or stat.S_IMODE(child_info.st_mode) != 0o500):
                    raise ContractError("candidate_run_tree_unsafe",
                                        "candidate run tree directory owner/mode 不安全")
                continue
            mode = stat.S_IMODE(child_info.st_mode)
            if (child.is_symlink() or not stat.S_ISREG(child_info.st_mode)
                    or child_info.st_nlink != 1
                    or child_info.st_uid != candidate_uid
                    or child_info.st_gid != candidate_gid
                    or mode not in {0o440, 0o550}):
                raise ContractError("candidate_run_tree_unsafe",
                                    "candidate run tree file owner/mode 不安全")
    by_path = {item.path: item for item in entries}
    python_rel = "env/bin/python"
    executable = root / python_rel
    adapter = root / CANDIDATE_ADAPTER_RELPATH
    try:
        info = executable.lstat()
        adapter_info = adapter.lstat()
        python_entry = by_path[python_rel]
        adapter_entry = by_path[CANDIDATE_ADAPTER_RELPATH]
    except (OSError, KeyError) as exc:
        raise ContractError("candidate_frozen_runtime_missing",
                            "candidate 缺少冻结 interpreter/adapter") from exc
    if (executable.is_symlink() or adapter.is_symlink()
            or not stat.S_ISREG(info.st_mode) or not stat.S_ISREG(adapter_info.st_mode)
            or info.st_nlink != 1 or adapter_info.st_nlink != 1
            or info.st_uid != candidate_uid or info.st_gid != candidate_gid
            or adapter_info.st_uid != candidate_uid or adapter_info.st_gid != candidate_gid
            or stat.S_IMODE(info.st_mode) != 0o550
            or stat.S_IMODE(adapter_info.st_mode) != 0o440
            or python_entry.mode != 0o550 or adapter_entry.mode != 0o440):
        raise ContractError("candidate_frozen_runtime_unsafe",
                            "candidate interpreter/adapter owner/mode 不安全")
    resolved = str(executable.absolute())
    argv = tuple(resolved if item == CANDIDATE_ROOT_TOKEN + "/env/bin/python" else item
                 for item in frozen)
    if (argv[0] != resolved or any(CANDIDATE_ROOT_TOKEN in item for item in argv)):
        raise ContractError("candidate_argv_resolution_invalid", "candidate argv 模板替换不精确")
    return argv


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
    """Run trusted external-oracle profiles from the fenced test queue."""
    from abcr.control.queue_runtime import queue_main

    def preflight(config: dict) -> None:
        settings = strict_object(config["settings"], required={
            "profile", "candidate_argv_template", "oracle_assertions", "sandbox_profile",
            "controller_private_key", "controller_public_key", "candidate_uid",
            "candidate_gid", "result_root", "trusted_candidate_root",
            "candidate_run_root"})
        validate_candidate_argv_template(settings["candidate_argv_template"])
        for key in ("sandbox_profile", "controller_private_key", "controller_public_key"):
            path = Path(settings[key])
            if path.is_symlink() or not path.is_file():
                raise ContractError("controller_trust_file_missing", f"{key} 不可用")
        for key in ("result_root", "trusted_candidate_root", "candidate_run_root"):
            result_root = Path(settings[key])
            if result_root.is_symlink() or not result_root.is_dir():
                raise ContractError("controller_result_root_invalid", f"{key} 不可用")
        if (type(settings["candidate_uid"]) is not int or settings["candidate_uid"] == 0
                or type(settings["candidate_gid"]) is not int):
            raise ContractError("candidate_identity_invalid", "candidate uid/gid 不合法")
        if not isinstance(settings["profile"], dict) or not isinstance(settings["oracle_assertions"], list):
            raise ContractError("oracle_profile_invalid", "oracle profile 不合法")

    def make_handler(config: dict):
        settings = config["settings"]
        registry = OracleRegistry()
        for item in settings["oracle_assertions"]:
            spec = strict_object(item, required={"oracle_id", "version", "kind"})
            if spec["kind"] != "equality":
                raise ContractError("oracle_assertion_unknown", "oracle assertion kind 未冻结")

            def equality(request: dict[str, Any], result: Any) -> tuple[bool, str]:
                expected = request.get("expected")
                return result == expected, "equal" if result == expected else "not_equal"

            registry.register(spec["oracle_id"], spec["version"], equality)
        signer = SigningIdentity(Path(settings["controller_private_key"]),
                                 Path(settings["controller_public_key"]))

        client = WorkBrokerClient(Path(config["broker_socket"]))

        def handle(payload, work_id: str, fencing_token: int) -> dict:
            obj = strict_object(payload, required={"mission_id", "candidate_ref",
                                                   "pipeline_context"},
                                optional={"diagnostic_summary"})
            require_id(obj["mission_id"], "mission_id")
            if obj["mission_id"] != work_id or not isinstance(obj["pipeline_context"], dict):
                raise ContractError("mission_work_identity_mismatch", "test work identity 不匹配")
            candidate = resolve_sealed_tree(
                obj["candidate_ref"], expected_operation="seal_attestation",
                trusted_root=Path(settings["trusted_candidate_root"]))
            candidate_tree_hash = tree_hash(scan_tree(candidate))
            run_tree = Path(settings["candidate_run_root"]) / f"{work_id}-{fencing_token}"
            if not run_tree.exists():
                export_plain_tree(candidate, run_tree)
                for directory, names, files in os.walk(run_tree, topdown=False,
                                                        followlinks=False):
                    for name in files:
                        path = Path(directory) / name
                        mode = stat.S_IMODE(path.lstat().st_mode)
                        os.chown(path, settings["candidate_uid"], settings["candidate_gid"])
                        os.chmod(path, 0o550 if mode & 0o111 else 0o440)
                    for name in names:
                        path = Path(directory) / name
                        os.chown(path, settings["candidate_uid"], settings["candidate_gid"])
                        os.chmod(path, 0o500)
                os.chown(run_tree, settings["candidate_uid"], settings["candidate_gid"])
                os.chmod(run_tree, 0o500)
            candidate_argv = resolve_candidate_argv(
                settings["candidate_argv_template"], run_tree,
                expected_tree_hash=candidate_tree_hash,
                candidate_uid=settings["candidate_uid"],
                candidate_gid=settings["candidate_gid"])
            tmp_root = Path(settings["candidate_run_root"]) / f".{work_id}-{fencing_token}.tmp"
            if not tmp_root.exists():
                tmp_root.mkdir(mode=0o700)
                os.chown(tmp_root, settings["candidate_uid"], settings["candidate_gid"])
            diagnostic = obj.get("diagnostic_summary", {})
            if not isinstance(diagnostic, dict):
                raise ContractError("diagnostic_summary_invalid", "diagnostic summary 不合法")
            bundle = run_profile(
                mission_id=obj["mission_id"], fencing_token=fencing_token,
                candidate_tree_hash=candidate_tree_hash, profile=settings["profile"],
                candidate_argv=candidate_argv, registry=registry,
                isolation=Path(settings["sandbox_profile"]), signer=signer,
                diagnostic_summary=diagnostic, candidate_uid=settings["candidate_uid"],
                candidate_gid=settings["candidate_gid"], cwd=str(run_tree),
                sandbox_params={"CANDIDATE_ROOT": str(run_tree),
                                "RUNTIME_ROOT": str(run_tree / "env"),
                                "TMPDIR": str(tmp_root)})
            if tree_hash(scan_tree(run_tree)) != candidate_tree_hash:
                raise ContractError("candidate_mutated_during_test", "candidate 测试期间发生写入")
            document = {"schema_version": 1, "kind": "test-result",
                        "bundle": asdict(bundle),
                        "pipeline_context": obj["pipeline_context"],
                        "candidate_ref": obj["candidate_ref"]}
            object_id = artifact_object_id("TST", document)
            reference = seal_json_artifact(
                client, operation="seal_test_result",
                staging_root=Path(settings["result_root"]), object_id=object_id,
                filename="test-result.json", document=document,
                nonce=f"test:{work_id}:{fencing_token}")
            return {"mission_id": work_id, "verdict": bundle.verdict,
                    "broker_ref": reference}
        return handle

    return queue_main(argv, service="test-controller", stage="test",
                      consumer="abcr-test-controller", preflight=preflight,
                      make_handler=make_handler)


if __name__ == "__main__":
    raise SystemExit(main())
