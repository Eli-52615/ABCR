"""Sandboxed Codex mission builder over coordinator-prepared plain trees.

The trusted Operator, not this worker, resolves a sealed release and exports a
read-only plain base.  The worker derives that base from ``work_id`` and a
root-owned config.  The untrusted adapter sees only a writable candidate, a
private temporary directory and a finite adapter runtime through a fixed
Seatbelt profile.  No bare-process fallback exists.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from abcr.control.contracts import (ContractError, canonical_json, require_id,
                                    require_sha, sha256, strict_object)
from abcr.control.mission_pipeline import broker_ref
from abcr.control.queue_runtime import WorkBrokerClient
from abcr.control.worktree import export_plain_tree, reconstruct_diff, scan_tree, tree_hash


SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
OBJECTIVE_TOKEN = "{objective}"
PRODUCTION_ADAPTER_ROOT = Path(
    "/Library/Application Support/ABCR-Bootstrap/adapters/mission-builder")


class BuilderAdapter(Protocol):
    def run(self, tree: Path, objective: str) -> int: ...


class FakeBuilder:
    def __init__(self, mutation):
        self.mutation = mutation

    def run(self, tree: Path, objective: str) -> int:
        self.mutation(tree, objective)
        return 0


def _secure_directory(path: Path, *, owner_uid: int, group_gid: int | None,
                      modes: set[int], code: str) -> Path:
    raw = Path(path)
    try:
        resolved = raw.resolve(strict=True)
        info = raw.lstat()
    except OSError as exc:
        raise ContractError(code, "builder directory 不可用") from exc
    if (not raw.is_absolute() or raw.is_symlink() or resolved != raw.absolute()
            or not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid
            or (group_gid is not None and info.st_gid != group_gid)
            or stat.S_IMODE(info.st_mode) not in modes):
        raise ContractError(code, "builder directory owner/group/mode/path 不安全")
    return resolved


def _secure_regular_hash(path: Path, *, owner_uid: int, modes: set[int],
                         code: str, max_bytes: int = 4 * 1024 * 1024) -> str:
    raw = Path(path)
    try:
        resolved = raw.resolve(strict=True)
        before = raw.lstat()
    except OSError as exc:
        raise ContractError(code, "frozen builder file 不可用") from exc
    if (not raw.is_absolute() or raw.is_symlink() or resolved != raw.absolute()
            or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_uid != owner_uid or stat.S_IMODE(before.st_mode) not in modes
            or before.st_size > max_bytes):
        raise ContractError(code, "frozen builder file owner/mode/path 不安全")
    fd = os.open(raw, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                                 info.st_nlink, info.st_uid, stat.S_IMODE(info.st_mode))
        if identity(opened) != identity(before):
            raise ContractError(code, "frozen builder file changed before read")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ContractError(code, "frozen builder file exceeds size limit")
            digest.update(chunk)
        after = os.fstat(fd)
        if identity(after) != identity(opened):
            raise ContractError(code, "frozen builder file changed during read")
        return digest.hexdigest()
    finally:
        os.close(fd)


def _secure_unix_socket(path: Path, *, owner_uid: int) -> Path:
    """Bind egress to a socket whose containing namespace is not swappable."""
    raw = Path(path)
    parent = raw.parent
    try:
        resolved_parent = parent.resolve(strict=True)
        parent_info = parent.lstat()
        resolved = raw.resolve(strict=True)
        info = raw.lstat()
    except OSError as exc:
        raise ContractError("builder_egress_socket_unavailable",
                            "egress socket 不可用") from exc
    # Checking only the socket inode leaves an lstat/connect race when an
    # untrusted principal can rename entries in its parent directory.
    if (not raw.is_absolute() or raw.is_symlink()
            or resolved != raw.absolute()
            or not parent.is_absolute() or parent.is_symlink()
            or resolved_parent != parent.absolute()
            or not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != owner_uid
            or stat.S_IMODE(parent_info.st_mode) & 0o022
            or not stat.S_ISSOCK(info.st_mode) or info.st_uid != owner_uid
            or stat.S_IMODE(info.st_mode) != 0o660):
        raise ContractError("builder_egress_socket_unsafe",
                            "egress socket 或其命名目录不安全")
    return resolved


def _validated_argv(template: tuple[str, ...], expected_hash: str,
                    executable_hash: str, *, executable_owner_uid: int,
                    adapter_root: Path) -> tuple[str, ...]:
    require_sha(expected_hash, "codex_argv_sha256")
    require_sha(executable_hash, "codex_executable_sha256")
    if (not template or any(not isinstance(item, str) or not item or "\x00" in item
                            for item in template)
            or template.count(OBJECTIVE_TOKEN) != 1):
        raise ContractError("codex_argv_invalid", "Codex argv template 未冻结")
    position = template.index(OBJECTIVE_TOKEN)
    if position == 0 or template[position - 1] != "--":
        raise ContractError("codex_argv_invalid",
                            "objective placeholder 必须是 -- 后的独立 argv")
    if sha256(list(template)) != expected_hash:
        raise ContractError("codex_argv_hash_mismatch", "Codex argv template hash 漂移")
    executable = Path(template[0])
    root = Path(adapter_root).resolve(strict=True)
    try:
        resolved = executable.resolve(strict=True)
    except OSError as exc:
        raise ContractError("codex_executable_unsafe", "Codex adapter executable 不可用") from exc
    if (not executable.is_absolute() or executable.is_symlink()
            or resolved != executable.absolute() or not resolved.is_relative_to(root)):
        raise ContractError("codex_executable_unsafe", "Codex adapter 不在有限 runtime root")
    observed = _secure_regular_hash(
        executable, owner_uid=executable_owner_uid,
        modes={0o500, 0o510, 0o550, 0o555, 0o700, 0o710, 0o750, 0o755},
        code="codex_executable_unsafe", max_bytes=256 * 1024 * 1024)
    if observed != executable_hash:
        raise ContractError("codex_executable_hash_mismatch", "Codex adapter bytes 漂移")
    return template


@dataclass(frozen=True)
class SandboxedCodexAdapter:
    """A finite argv executed only through the reviewed Seatbelt profile."""

    argv_template: tuple[str, ...]
    argv_sha256: str
    executable_sha256: str
    executable_owner_uid: int
    adapter_root: Path
    runtime_root: Path
    runtime_owner_uid: int
    sandbox_profile: Path
    sandbox_profile_sha256: str
    sandbox_profile_owner_uid: int
    temporary_root: Path
    temporary_owner_uid: int
    egress_socket: Path | None = None
    timeout_seconds: int = 1800
    sandbox_exec: Path = SANDBOX_EXEC

    def _validate(self) -> tuple[Path, Path, Path, tuple[str, ...]]:
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 1800:
            raise ContractError("builder_timeout_invalid", "builder timeout 不合法")
        adapter = _secure_directory(
            self.adapter_root, owner_uid=self.runtime_owner_uid, group_gid=None,
            modes={0o550, 0o555, 0o750, 0o755}, code="builder_adapter_root_unsafe")
        runtime = _secure_directory(
            self.runtime_root, owner_uid=self.runtime_owner_uid, group_gid=None,
            modes={0o550, 0o555, 0o750, 0o755}, code="builder_runtime_root_unsafe")
        temporary = _secure_directory(
            self.temporary_root, owner_uid=self.temporary_owner_uid, group_gid=None,
            modes={0o700}, code="builder_tmp_root_unsafe")
        observed_profile = _secure_regular_hash(
            self.sandbox_profile, owner_uid=self.sandbox_profile_owner_uid,
            modes={0o400, 0o440, 0o444}, code="builder_sandbox_profile_unsafe")
        if observed_profile != self.sandbox_profile_sha256:
            raise ContractError("builder_sandbox_profile_hash_mismatch",
                                "builder sandbox profile bytes 漂移")
        argv = _validated_argv(
            self.argv_template, self.argv_sha256, self.executable_sha256,
            executable_owner_uid=self.executable_owner_uid, adapter_root=adapter)
        try:
            sandbox_info = self.sandbox_exec.lstat()
        except OSError as exc:
            raise ContractError("sandbox_exec_unavailable", "sandbox-exec 不可用") from exc
        if (self.sandbox_exec != SANDBOX_EXEC or self.sandbox_exec.is_symlink()
                or not stat.S_ISREG(sandbox_info.st_mode) or sandbox_info.st_uid != 0
                or stat.S_IMODE(sandbox_info.st_mode) & 0o022
                or not os.access(self.sandbox_exec, os.X_OK)):
            raise ContractError("sandbox_exec_unavailable", "sandbox-exec OS TCB 不安全")
        return adapter, runtime, temporary, argv

    def run(self, tree: Path, objective: str) -> int:
        if (not isinstance(objective, str) or not objective.strip()
                or len(objective) > 100_000 or "\x00" in objective):
            raise ContractError("objective_invalid", "mission objective 不合法")
        adapter, runtime, temporary, template = self._validate()
        candidate_raw = Path(tree)
        try:
            candidate = candidate_raw.resolve(strict=True)
            candidate_info = candidate_raw.lstat()
        except OSError as exc:
            raise ContractError("candidate_path_unsafe", "candidate tree 不可用") from exc
        if (not candidate_raw.is_absolute() or candidate_raw.is_symlink()
                or candidate != candidate_raw.absolute()
                or not stat.S_ISDIR(candidate_info.st_mode)
                or candidate_info.st_uid != os.geteuid()
                or stat.S_IMODE(candidate_info.st_mode) != 0o700):
            raise ContractError("candidate_path_unsafe", "candidate tree owner/mode 不安全")

        run_tmp = Path(tempfile.mkdtemp(prefix="abcr-builder-", dir=temporary))
        os.chmod(run_tmp, 0o700)
        try:
            expanded = tuple(objective if item == OBJECTIVE_TOKEN else item
                             for item in template)
            egress = "" if self.egress_socket is None else str(self.egress_socket)
            command = [
                str(self.sandbox_exec), "-f", str(self.sandbox_profile),
                "-D", f"CANDIDATE_ROOT={candidate}",
                "-D", f"TMPDIR={run_tmp}",
                "-D", f"ADAPTER_ROOT={adapter}",
                "-D", f"RUNTIME_ROOT={runtime}",
                "-D", f"BUILDER_EXECUTABLE={expanded[0]}",
                "-D", f"EGRESS_SOCKET={egress}",
                "--", *expanded,
            ]
            environment = {
                "PATH": "/usr/bin:/bin", "HOME": str(run_tmp),
                "TMPDIR": str(run_tmp), "LANG": "C", "LC_ALL": "C",
                "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                "PYTHONUTF8": "1",
            }
            if self.egress_socket is not None:
                # A reviewed adapter speaks the local broker protocol.  It gets
                # neither API keys nor a general proxy URL.
                environment["ABCR_EGRESS_SOCKET"] = str(self.egress_socket)
            process = subprocess.Popen(
                command, cwd=str(candidate), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=environment, shell=False, close_fds=True,
                start_new_session=True)
            try:
                return process.wait(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                raise ContractError("builder_timeout", "sandboxed builder 超时") from exc
        finally:
            shutil.rmtree(run_tmp, ignore_errors=True)


def _make_candidate_writable(base_tree: Path, candidate_tree: Path) -> None:
    base = {entry.path: entry for entry in scan_tree(base_tree)}
    root_info = candidate_tree.lstat()
    for dirpath, dirnames, filenames in os.walk(candidate_tree, followlinks=False):
        current = Path(dirpath)
        current_info = current.lstat()
        if (current.is_symlink() or not stat.S_ISDIR(current_info.st_mode)
                or current_info.st_dev != root_info.st_dev):
            raise ContractError("candidate_path_unsafe", "candidate tree 目录不安全")
        os.chmod(current, 0o700)
        for name in filenames:
            path = current / name
            rel = path.relative_to(candidate_tree).as_posix()
            info = path.lstat()
            if (path.is_symlink() or not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1 or info.st_dev != root_info.st_dev
                    or rel not in base):
                raise ContractError("candidate_path_unsafe", "candidate 初始文件集合不安全")
            os.chmod(path, base[rel].mode | stat.S_IWUSR)


def _normalize_candidate_modes(base_tree: Path, candidate_tree: Path) -> None:
    base = {entry.path: entry for entry in scan_tree(base_tree)}
    current = scan_tree(candidate_tree)
    for entry in current:
        path = candidate_tree / entry.path
        if entry.path in base:
            mode = base[entry.path].mode
        else:
            mode = 0o755 if entry.mode & 0o111 else 0o644
        os.chmod(path, mode)
    for dirpath, dirnames, _filenames in os.walk(candidate_tree, followlinks=False):
        current_dir = Path(dirpath)
        if current_dir.is_symlink():
            raise ContractError("candidate_path_unsafe", "candidate 目录禁止 symlink")
        os.chmod(current_dir, 0o700)


def build_candidate(adapter: BuilderAdapter, *, base_tree: Path, candidate_tree: Path,
                    objective: str, allowed_paths: tuple[str, ...]) -> dict:
    _make_candidate_writable(base_tree, candidate_tree)
    code = adapter.run(candidate_tree, objective)
    if code != 0:
        raise ContractError("builder_failed", f"builder exited {code}")
    _normalize_candidate_modes(base_tree, candidate_tree)
    return reconstruct_diff(base_tree, candidate_tree, allowed_globs=allowed_paths)


def _load_egress_policy(settings: dict[str, Any], *, argv_sha: str,
                        executable_sha: str, profile_sha: str) -> Path:
    if settings["egress_mode"] == "deny":
        raise ContractError("builder_egress_unqualified",
                            "受控 egress 未资格化；Seatbelt 保持 network deny")
    if settings["egress_mode"] != "unix_broker":
        raise ContractError("builder_egress_invalid", "未知 builder egress mode")
    if settings["egress_qualified"] is not True:
        raise ContractError("builder_egress_unqualified", "builder egress broker 未资格化")
    for name in ("egress_socket", "egress_policy_path", "egress_policy_sha256"):
        if not isinstance(settings[name], str) or not settings[name]:
            raise ContractError("builder_egress_invalid", f"{name} 缺失")
    policy_path = Path(settings["egress_policy_path"])
    observed = _secure_regular_hash(
        policy_path, owner_uid=0, modes={0o400, 0o440, 0o444},
        code="builder_egress_policy_unsafe")
    require_sha(settings["egress_policy_sha256"], "egress_policy_sha256")
    if observed != settings["egress_policy_sha256"]:
        raise ContractError("builder_egress_policy_hash_mismatch", "egress policy bytes 漂移")
    try:
        raw = policy_path.read_bytes()
        policy = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise ContractError("builder_egress_policy_invalid", "egress policy JSON 不合法") from exc
    exact = strict_object(policy, required={
        "schema_version", "mode", "socket_path", "endpoint_set_sha256",
        "adapter_argv_sha256", "adapter_executable_sha256",
        "sandbox_profile_sha256", "qualified_at", "valid_until"})
    for name in ("endpoint_set_sha256", "adapter_argv_sha256",
                 "adapter_executable_sha256", "sandbox_profile_sha256"):
        require_sha(exact[name], name)
    if (exact["schema_version"] != 1 or exact["mode"] != "unix_broker"
            or exact["socket_path"] != settings["egress_socket"]
            or exact["adapter_argv_sha256"] != argv_sha
            or exact["adapter_executable_sha256"] != executable_sha
            or exact["sandbox_profile_sha256"] != profile_sha
            or canonical_json(exact) + b"\n" != raw):
        raise ContractError("builder_egress_policy_invalid", "egress policy binding 不匹配")
    try:
        expires = datetime.fromisoformat(exact["valid_until"])
    except (TypeError, ValueError) as exc:
        raise ContractError("builder_egress_policy_invalid", "egress policy expiry 不合法") from exc
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ContractError("builder_egress_expired", "egress qualification 已过期")
    return _secure_unix_socket(Path(settings["egress_socket"]), owner_uid=0)


def _runtime_from_settings(settings: dict[str, Any]) -> tuple[dict[str, Any], SandboxedCodexAdapter]:
    required = {
        "prepared_base_root", "prepared_base_owner_uid", "prepared_base_group_gid",
        "candidate_root", "sandbox_tmp_root", "sandbox_profile",
        "sandbox_profile_sha256", "adapter_runtime_root", "adapter_runtime_owner_uid",
        "codex_argv", "codex_argv_sha256", "codex_executable_sha256",
        "autonomous_qualified", "egress_mode", "egress_qualified",
        "egress_socket", "egress_policy_path", "egress_policy_sha256",
    }
    exact = strict_object(settings, required=required)
    if exact["autonomous_qualified"] is not True:
        if exact["egress_mode"] != "deny":
            raise ContractError("builder_config_invalid",
                                "未资格化 builder 必须保持 egress_mode=deny")
        raise ContractError("builder_autonomous_unqualified",
                            "真实 Codex adapter/egress 尚未资格化")
    for name in ("prepared_base_owner_uid", "prepared_base_group_gid",
                 "adapter_runtime_owner_uid"):
        if type(exact[name]) is not int or exact[name] < 0:
            raise ContractError("builder_config_invalid", f"{name} 不合法")
    for name in ("prepared_base_root", "candidate_root", "sandbox_tmp_root",
                 "sandbox_profile", "adapter_runtime_root"):
        if not isinstance(exact[name], str) or not Path(exact[name]).is_absolute():
            raise ContractError("builder_config_invalid", f"{name} 必须是固定绝对路径")
    if (not isinstance(exact["codex_argv"], list)
            or any(not isinstance(item, str) for item in exact["codex_argv"])):
        raise ContractError("builder_config_invalid", "codex_argv 不合法")
    argv = tuple(exact["codex_argv"])
    require_sha(exact["codex_argv_sha256"], "codex_argv_sha256")
    require_sha(exact["codex_executable_sha256"], "codex_executable_sha256")
    require_sha(exact["sandbox_profile_sha256"], "sandbox_profile_sha256")
    adapter_root = Path(exact["adapter_runtime_root"])
    if adapter_root != PRODUCTION_ADAPTER_ROOT:
        raise ContractError("builder_adapter_root_unreviewed", "production adapter root 未冻结")
    egress_socket = _load_egress_policy(
        exact, argv_sha=exact["codex_argv_sha256"],
        executable_sha=exact["codex_executable_sha256"],
        profile_sha=exact["sandbox_profile_sha256"])
    adapter = SandboxedCodexAdapter(
        argv_template=argv, argv_sha256=exact["codex_argv_sha256"],
        executable_sha256=exact["codex_executable_sha256"],
        executable_owner_uid=exact["adapter_runtime_owner_uid"],
        adapter_root=adapter_root, runtime_root=adapter_root,
        runtime_owner_uid=exact["adapter_runtime_owner_uid"],
        sandbox_profile=Path(exact["sandbox_profile"]),
        sandbox_profile_sha256=exact["sandbox_profile_sha256"],
        sandbox_profile_owner_uid=0,
        temporary_root=Path(exact["sandbox_tmp_root"]),
        temporary_owner_uid=os.geteuid(), egress_socket=egress_socket)
    return exact, adapter


def main(argv: list[str] | None = None) -> int:
    """Consume frozen mission work only after real adapter/egress qualification."""
    from abcr.control.queue_runtime import queue_main

    def preflight(config: dict[str, Any]) -> None:
        exact, adapter = _runtime_from_settings(config["settings"])
        _secure_directory(
            Path(exact["prepared_base_root"]), owner_uid=exact["prepared_base_owner_uid"],
            group_gid=exact["prepared_base_group_gid"], modes={0o750},
            code="mission_input_root_unsafe")
        _secure_directory(
            Path(exact["candidate_root"]), owner_uid=os.geteuid(), group_gid=None,
            modes={0o700}, code="candidate_root_unsafe")
        adapter._validate()

    def make_handler(config: dict[str, Any]):
        settings, adapter = _runtime_from_settings(config["settings"])
        prepared_root = Path(settings["prepared_base_root"])
        candidates = Path(settings["candidate_root"])
        client = WorkBrokerClient(Path(config["broker_socket"]))

        def handle(payload: Any, work_id: str, fencing_token: int) -> dict[str, Any]:
            obj = strict_object(payload, required={
                "objective", "allowed_paths", "base_release", "base_tree_hash"},
                optional={"mission_id", "declared_risk", "old_release",
                          "expected_version"})
            mission_id = obj.get("mission_id", work_id)
            require_id(obj["base_release"], "base_release")
            require_sha(obj["base_tree_hash"], "base_tree_hash")
            if mission_id != work_id:
                raise ContractError("mission_work_identity_mismatch",
                                    "mission_id 必须与 queue work_id 一致")
            if (not isinstance(obj["objective"], str) or not obj["objective"].strip()
                    or len(obj["objective"]) > 100_000):
                raise ContractError("objective_invalid", "objective 不合法")
            allowed = obj["allowed_paths"]
            if (not isinstance(allowed, list) or not allowed
                    or any(not isinstance(item, str) or not item for item in allowed)):
                raise ContractError("allowed_paths_invalid", "allowed_paths 不合法")
            declared_risk = obj.get("declared_risk", "human_required")
            if declared_risk not in {"normal", "guarded", "human_required"}:
                raise ContractError("bad_declared_risk", "mission risk 不合法")

            # The queue cannot choose this path.  Only work_id plus the fixed
            # coordinator export root resolves the read-only base.
            base = prepared_root / work_id
            base = _secure_directory(
                base, owner_uid=settings["prepared_base_owner_uid"],
                group_gid=settings["prepared_base_group_gid"], modes={0o550},
                code="mission_prepared_base_unsafe")
            if tree_hash(scan_tree(base)) != obj["base_tree_hash"]:
                raise ContractError("mission_prepared_base_hash_mismatch",
                                    "coordinator plain base hash 不匹配")

            candidate = candidates / work_id
            if candidate.exists() or candidate.is_symlink():
                if candidate.is_symlink() or not candidate.is_dir():
                    raise ContractError("candidate_path_unsafe", "candidate path 不安全")
                result = reconstruct_diff(base, candidate, allowed_globs=tuple(allowed))
            else:
                staging = candidates / f".{work_id}.{fencing_token}.{uuid.uuid4().hex}.staging"
                try:
                    export_plain_tree(base, staging)
                    os.chmod(staging, 0o700)
                    result = build_candidate(
                        adapter, base_tree=base, candidate_tree=staging,
                        objective=obj["objective"], allowed_paths=tuple(allowed))
                    try:
                        os.rename(staging, candidate)
                    except FileExistsError:
                        result = reconstruct_diff(base, candidate, allowed_globs=tuple(allowed))
                finally:
                    if staging.exists():
                        shutil.rmtree(staging)
            observed = tree_hash(scan_tree(candidate))
            receipt = client.request("seal_attestation", {
                "source": str(candidate),
                "nonce": f"candidate:{work_id}:{fencing_token}",
                "expected_tree_hash": observed,
                "object_id": f"CND-{observed[:48]}"})
            candidate_ref = broker_ref(receipt, expected_operation="seal_attestation")
            return {**result, "candidate_tree_hash": candidate_ref["sealed_tree_hash"],
                    "candidate_ref": candidate_ref, "candidate_id": work_id,
                    "mission_id": mission_id, "declared_risk": declared_risk,
                    "old_release": obj.get("old_release"),
                    "expected_version": obj.get("expected_version")}
        return handle

    return queue_main(argv, service="mission-builder", stage="mission-build",
                      consumer="abcr-builder", preflight=preflight,
                      make_handler=make_handler)


if __name__ == "__main__":
    raise SystemExit(main())
