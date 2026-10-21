"""Immutable release preparation and broker-mediated activation/rollback."""
from __future__ import annotations

from dataclasses import dataclass
import ast
import json
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from abcr.control.black_box_oracle import is_release_eligible_isolation
from abcr.control.canary_controller import CanaryResult
from abcr.control.contracts import ContractError, canonical_json, sha256
from abcr.control.seal_broker import SealBroker
from abcr.control.verifier import VerificationAttestation, verify_verification_attestation
from abcr.control.worktree import TreeEntry, export_plain_tree, scan_tree, tree_hash

DEFAULT_RUNTIME_RELPATH = "env"
DEFAULT_PYTHON_RELPATH = "env/bin/python"
LOCK_CANDIDATES = ("requirements.lock", "requirements-mac.txt")
DEFAULT_SERVICE_CONFIG_RELPATH = "configs/control/service-topology-v1.json"


@dataclass(frozen=True)
class ReleaseManifest:
    release_id: str
    tree_hash: str
    runtime_digest: str
    lock_hash: str
    service_config_hash: str
    verification_hash: str
    # Complete, pre-seal file manifest.  seal-broker changes only modes to
    # 0440/0550; the stable launcher uses these records to verify all bytes and
    # reconstruct the attested pre-seal tree identity.
    tree_entries: tuple[dict[str, Any], ...] = ()
    runtime_relpath: str = DEFAULT_RUNTIME_RELPATH
    lock_relpath: str = ""
    service_config_relpath: str = DEFAULT_SERVICE_CONFIG_RELPATH


def _entry_dict(entry: TreeEntry) -> dict[str, Any]:
    return {"path": entry.path, "mode": entry.mode, "size": entry.size,
            "sha256": entry.sha256}


def _entry_dicts(entries: Iterable[TreeEntry]) -> tuple[dict[str, Any], ...]:
    return tuple(_entry_dict(item) for item in sorted(entries, key=lambda item: item.path))


def _safe_relative(root: Path, path: Path | str, field: str) -> str:
    raw = Path(path)
    if raw.is_absolute():
        try:
            raw = raw.relative_to(root.absolute())
        except ValueError as exc:
            raise ContractError("release_artifact_outside_tree",
                                f"{field} 必须位于 candidate tree 内") from exc
    pure = PurePosixPath(raw.as_posix())
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ContractError("release_artifact_path_invalid", f"{field} 路径不合法")
    return pure.as_posix()


def _load_topology(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("release_service_config_invalid", "service topology 不是有效 JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("services"), list):
        raise ContractError("release_service_config_invalid", "service topology 结构不合法")
    labels: set[str] = set()
    modules: set[str] = set()
    for item in value["services"]:
        if not isinstance(item, dict) or not isinstance(item.get("label"), str) or not isinstance(item.get("module"), str):
            raise ContractError("release_service_config_invalid", "service topology 条目不完整")
        if item["label"] in labels or item["module"] in modules:
            raise ContractError("release_service_config_invalid", "service topology label/module 重复")
        labels.add(item["label"]); modules.add(item["module"])
    return value


def _read_entry_bytes(root: Path, entry: TreeEntry) -> bytes:
    path = root / entry.path
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ContractError("release_artifact_unsafe", "artifact 无法 nofollow 打开") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != entry.mode or info.st_size != entry.size):
            raise ContractError("release_artifact_drift", "artifact inode/mode/size 已变化")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk: break
            chunks.append(chunk)
        raw = b"".join(chunks)
        if sha256(raw) != entry.sha256:
            raise ContractError("release_artifact_drift", "artifact bytes 已变化")
        return raw
    finally:
        os.close(fd)


@dataclass(frozen=True)
class _MaterialEvidence:
    root: Path
    entries: tuple[TreeEntry, ...]
    entry_map: dict[str, TreeEntry]
    runtime_digest: str
    lock_hash: str
    service_config_hash: str
    runtime_relpath: str
    lock_relpath: str
    service_config_relpath: str
    topology: dict[str, Any]


def _material_evidence(candidate_root: Path, *, runtime_root: Path | str | None,
                       lock_path: Path | str | None,
                       service_config_path: Path | str | None) -> _MaterialEvidence:
    root = Path(candidate_root)
    entries = scan_tree(root)
    for item in entries:
        if item.mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | 0o022):
            raise ContractError("release_file_mode_unsafe",
                                f"candidate file 不可被 group/world 写入: {item.path}")
    for dirpath, _, _ in os.walk(root, followlinks=False):
        mode = stat.S_IMODE(Path(dirpath).lstat().st_mode)
        if mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | 0o022):
            raise ContractError("release_directory_mode_unsafe",
                                "candidate directory 不可被 group/world 写入")
    by_path = {item.path: item for item in entries}

    runtime_rel = _safe_relative(root, runtime_root or DEFAULT_RUNTIME_RELPATH, "runtime_root")
    if runtime_rel != DEFAULT_RUNTIME_RELPATH:
        raise ContractError("release_runtime_path_invalid", "V1 runtime 必须冻结在 env/")
    runtime_entries = tuple(item for item in entries
                            if item.path == runtime_rel or item.path.startswith(runtime_rel + "/"))
    if not runtime_entries or DEFAULT_PYTHON_RELPATH not in by_path:
        raise ContractError("release_runtime_missing", "candidate 缺少 env/bin/python 冻结 runtime")
    if not by_path[DEFAULT_PYTHON_RELPATH].mode & 0o111:
        raise ContractError("release_python_not_executable", "env/bin/python 必须带 executable bit")
    runtime_digest = tree_hash(runtime_entries)

    if lock_path is None:
        lock_rel = next((item for item in LOCK_CANDIDATES if item in by_path), "")
        if not lock_rel:
            raise ContractError("release_lock_missing", "candidate 缺少冻结 dependency lock")
    else:
        lock_rel = _safe_relative(root, lock_path, "lock_path")
    if lock_rel not in by_path:
        raise ContractError("release_lock_missing", "dependency lock 不在 attested candidate tree")
    lock_hash = by_path[lock_rel].sha256

    config_rel = _safe_relative(root, service_config_path or DEFAULT_SERVICE_CONFIG_RELPATH,
                                "service_config_path")
    config_entry = by_path.get(config_rel)
    if config_entry is None:
        raise ContractError("release_service_config_missing", "candidate 缺少 service topology")
    topology = _load_topology(_read_entry_bytes(root, config_entry))
    service_config_hash = sha256(topology)

    # A second full scan makes artifact reads part of the same accepted tree
    # snapshot instead of trusting path bytes after a prior lstat.
    if scan_tree(root) != entries:
        raise ContractError("release_tree_toctou", "candidate tree 在重算 artifacts 时发生变化")
    return _MaterialEvidence(root, entries, by_path, runtime_digest, lock_hash,
                             service_config_hash, runtime_rel, lock_rel, config_rel, topology)


def _require_optional_match(supplied: str | None, actual: str, code: str, name: str) -> None:
    # Old keyword arguments remain accepted as assertions, never as sources of
    # identity.  A free string such as "runtime-v1" is therefore rejected.
    if supplied is not None and supplied != actual:
        raise ContractError(code, f"调用方提供的 {name} 与实物重算值不一致")


def prepare_release(candidate_root: Path, attestation: VerificationAttestation, *,
                    verifier_public_key: Path,
                    runtime_root: Path | str | None = None,
                    lock_path: Path | str | None = None,
                    service_config_path: Path | str | None = None,
                    runtime_digest: str | None = None,
                    lock_hash: str | None = None,
                    service_config_hash: str | None = None) -> ReleaseManifest:
    """Verify attestation and derive every release digest from candidate bytes.

    The three historical ``*_hash`` keywords are compatibility assertions.  They
    cannot inject identity: when present they must equal independently recomputed
    evidence.
    """
    ok, reason = verify_verification_attestation(attestation,
                                                 public_key=Path(verifier_public_key))
    if not ok:
        raise ContractError("verification_unverified", f"验证 attestation 验签失败: {reason}")
    if sha256(attestation.core) != attestation.attestation_hash:
        raise ContractError("verification_tampered", "验证 attestation 内容被修改")
    if not is_release_eligible_isolation(attestation.isolation):
        raise ContractError("unsandboxed_result_forbidden",
                            f"候选未在真实沙箱内运行({attestation.isolation}),不得发布")
    if attestation.verdict != "PASS":
        raise ContractError("verification_not_pass", "验证未通过")

    evidence = _material_evidence(Path(candidate_root), runtime_root=runtime_root,
                                  lock_path=lock_path,
                                  service_config_path=service_config_path)
    observed = tree_hash(evidence.entries)
    if observed != attestation.candidate_tree_hash:
        raise ContractError("release_tree_drift", "release tree 与 attestation 不一致")
    _require_optional_match(runtime_digest, evidence.runtime_digest,
                            "release_runtime_digest_mismatch", "runtime_digest")
    _require_optional_match(lock_hash, evidence.lock_hash,
                            "release_lock_hash_mismatch", "lock_hash")
    _require_optional_match(service_config_hash, evidence.service_config_hash,
                            "release_service_config_hash_mismatch", "service_config_hash")
    core = {"tree_hash": observed, "runtime_digest": evidence.runtime_digest,
            "lock_hash": evidence.lock_hash,
            "service_config_hash": evidence.service_config_hash,
            "verification_hash": attestation.attestation_hash}
    return ReleaseManifest("REL-" + sha256(core), **core,
                           tree_entries=_entry_dicts(evidence.entries),
                           runtime_relpath=evidence.runtime_relpath,
                           lock_relpath=evidence.lock_relpath,
                           service_config_relpath=evidence.service_config_relpath)


def _service_payloads(evidence: _MaterialEvidence,
                      requested: dict[str, dict]) -> dict[str, dict[str, Any]]:
    services = evidence.topology["services"]
    by_label = {item["label"]: item for item in services}
    by_module = {item["module"]: item for item in services}
    declared = {item.path: _entry_dict(item) for item in evidence.entries}
    runtime_paths = {item.path for item in evidence.entries
                     if item.path.startswith(evidence.runtime_relpath + "/")}
    out: dict[str, dict[str, Any]] = {}
    for key, spec in requested.items():
        service = by_label.get(key) or by_module.get(key)
        if service is None:
            raise ContractError("release_service_unknown", f"service_payload 不在冻结 topology: {key}")
        module = service["module"]
        if module in out:
            raise ContractError("release_service_duplicate", "同一 service 被 label/module 重复声明")
        if not isinstance(spec, dict) or set(spec) - {"payload_files"}:
            raise ContractError("release_payload_spec_invalid",
                                "service_payload 调用方只可缩小 payload_files,不得自报 hash")
        suffix = "/" + module.replace(".", "/") + ".py"
        candidates = [path for path in runtime_paths
                      if path == suffix[1:] or path.endswith(suffix)]
        if len(candidates) != 1:
            raise ContractError("release_service_module_unbound",
                                f"runtime 中必须恰有一个 {module} 模块实物")
        module_rel = candidates[0]
        try:
            syntax = ast.parse(_read_entry_bytes(evidence.root, evidence.entry_map[module_rel]).decode("utf-8"),
                               filename=module_rel)
        except (UnicodeDecodeError, SyntaxError) as exc:
            raise ContractError("release_service_module_invalid",
                                f"{module} 不是有效 Python module") from exc
        if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
                   for node in syntax.body):
            raise ContractError("release_service_main_missing", f"{module} 缺少静态 main()")
        required = {DEFAULT_PYTHON_RELPATH, module_rel, evidence.lock_relpath,
                    evidence.service_config_relpath}
        if "payload_files" in spec:
            raw_paths = spec["payload_files"]
            if not isinstance(raw_paths, list) or any(not isinstance(item, str) for item in raw_paths):
                raise ContractError("release_payload_spec_invalid", "payload_files 必须是 path list")
            paths = set(raw_paths)
        else:
            # V1 exports the immutable runtime plus lock/topology.  It does not
            # silently include research data, split/golden files or repo state.
            paths = set(runtime_paths) | {evidence.lock_relpath, evidence.service_config_relpath}
        if not required.issubset(paths) or not paths.issubset(declared):
            raise ContractError("release_payload_files_incomplete",
                                "payload_files 缺少 runtime/module/lock/topology 或引用树外文件")
        selected = [declared[path] for path in sorted(paths)]
        out[module] = {
            "label": service["label"], "module": module, "entrypoint": "main",
            "python_relpath": DEFAULT_PYTHON_RELPATH,
            "python_sha256": declared[DEFAULT_PYTHON_RELPATH]["sha256"],
            "module_relpath": module_rel, "module_sha256": declared[module_rel]["sha256"],
            "lock_relpath": evidence.lock_relpath,
            "payload_files": sorted(paths), "payload_tree_hash": sha256(selected),
        }
    return out


def stage_release(candidate_root: Path, staging_root: Path, manifest: ReleaseManifest,
                  *, service_payloads: dict[str, dict]) -> tuple[Path, str]:
    """Build a finite release manifest entirely from re-observed source bytes."""
    evidence = _material_evidence(Path(candidate_root),
                                  runtime_root=manifest.runtime_relpath,
                                  lock_path=manifest.lock_relpath,
                                  service_config_path=manifest.service_config_relpath)
    observed_entries = _entry_dicts(evidence.entries)
    if (tree_hash(evidence.entries) != manifest.tree_hash
            or observed_entries != manifest.tree_entries
            or evidence.runtime_digest != manifest.runtime_digest
            or evidence.lock_hash != manifest.lock_hash
            or evidence.service_config_hash != manifest.service_config_hash):
        raise ContractError("release_manifest_material_mismatch",
                            "stage 前 candidate/runtime/lock/topology 与 manifest 不一致")
    core = {"tree_hash": manifest.tree_hash, "runtime_digest": manifest.runtime_digest,
            "lock_hash": manifest.lock_hash,
            "service_config_hash": manifest.service_config_hash,
            "verification_hash": manifest.verification_hash}
    if manifest.release_id != "REL-" + sha256(core):
        raise ContractError("release_manifest_identity_mismatch", "release_id 与实物摘要不一致")
    completed_payloads = _service_payloads(evidence, service_payloads)

    staging_root = Path(staging_root); staging_root.mkdir(parents=True, exist_ok=True)
    destination = staging_root / f"{manifest.release_id}.staging"
    if destination.exists():
        raise ContractError("release_staging_exists", "release staging 必须是新目录")
    export_plain_tree(candidate_root, destination)
    payload = {**manifest.__dict__, "tree_entries": list(manifest.tree_entries),
               "service_payloads": completed_payloads}
    path = destination / "release-manifest.json"
    with path.open("xb") as fh:
        fh.write(canonical_json(payload) + b"\n"); fh.flush(); os.fsync(fh.fileno())
    return destination, tree_hash(scan_tree(destination))


def activate_release(broker: SealBroker, *, active_path: Path, old_release: str | None,
                     manifest: ReleaseManifest, seal_receipt: dict[str, Any],
                     canary: CanaryResult) -> dict[str, Any]:
    if not canary.semantic_ok or canary.release_id != manifest.release_id:
        raise ContractError("canary_not_pass", "外部 canary 未通过")
    return broker.activate(active_path, expected_old=old_release, new_release=manifest.release_id,
                           release_receipt=seal_receipt,
                           verification_hash=manifest.verification_hash,
                           canary_hash=canary.result_hash)


def main(argv: list[str] | None = None) -> int:
    """Fail closed until prepare/activate queue payloads are frozen end to end."""
    from abcr.control.service_runtime import blocked_runtime_main
    return blocked_runtime_main(argv, service="release-activator",
                                required_capability="activate_release",
                                capabilities={"activate_release": activate_release})


if __name__ == "__main__":
    raise SystemExit(main())
