from __future__ import annotations

import gzip
import hashlib
import io
import importlib.machinery
import importlib.util
import json
import os
import socket
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest

from abcr.control import release_policy
from abcr.control.contracts import ContractError, sha256
from abcr.control.mission_coordinator import (PreparedMissionBase,
                                              TrustedMissionCoordinator)
from abcr.control.mission_pipeline import reconcile_queued_missions
from abcr.control.mission_worker import (OBJECTIVE_TOKEN, SANDBOX_EXEC,
                                         SandboxedCodexAdapter,
                                         _secure_unix_socket,
                                         _runtime_from_settings,
                                         _validated_argv)
from abcr.control.release import BOOTSTRAP_REQUIRED_PATHS
from abcr.control.release_policy import FROZEN_SCIENTIFIC_SHA256


ROOT = Path(__file__).resolve().parents[2]
BUILDER_PROFILE = ROOT / "ops/sandbox/abcr-builder.sb"


def _immutable_tree(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        current = Path(dirpath)
        for name in filenames:
            os.chmod(current / name, 0o440)
        for name in dirnames:
            os.chmod(current / name, 0o550)
        os.chmod(current, 0o550)


def _coordinator(tmp_path: Path) -> tuple[TrustedMissionCoordinator, Path, Path]:
    root = tmp_path.resolve()
    releases = root / "releases"
    prepared = root / "prepared"
    releases.mkdir(mode=0o750)
    prepared.mkdir(mode=0o750)
    os.chmod(releases, 0o750)
    os.chmod(prepared, 0o750)
    return (TrustedMissionCoordinator(
        release_root=releases, prepared_root=prepared,
        coordinator_uid=os.getuid(), reader_gid=os.getgid(),
        release_owner_uid=os.getuid()), releases, prepared)


def test_trusted_coordinator_exports_only_plain_read_only_tree(tmp_path: Path) -> None:
    coordinator, releases, prepared = _coordinator(tmp_path)
    source = releases / "REL-1"
    (source / "src").mkdir(parents=True)
    (source / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git/config").write_text("secret git remote\n", encoding="utf-8")
    _immutable_tree(source)

    first = coordinator.prepare(mission_id="MIS-1", release_id="REL-1")
    second = coordinator.prepare(mission_id="MIS-1", release_id="REL-1")

    exported = prepared / "MIS-1"
    assert first == second
    assert first.release_id == "REL-1" and len(first.base_tree_hash) == 64
    assert (exported / "src/app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (exported / ".git").exists()
    assert (exported.stat().st_mode & 0o777) == 0o550
    assert ((exported / "src/app.py").stat().st_mode & 0o777) == 0o440


@pytest.mark.parametrize("private_path", [
    "ledger/events.json", "evidence/run.json", "data/benchmarks/items.json",
    "src/private.pem", ".env",
])
def test_trusted_coordinator_rejects_private_material(
        tmp_path: Path, private_path: str) -> None:
    coordinator, releases, _prepared = _coordinator(tmp_path)
    source = releases / "REL-2"
    path = source / private_path
    path.parent.mkdir(parents=True)
    path.write_text("must not reach builder\n", encoding="utf-8")
    _immutable_tree(source)

    with pytest.raises(ContractError) as caught:
        coordinator.prepare(mission_id="MIS-2", release_id="REL-2")

    assert caught.value.code == "mission_base_private_material"


class _ReadyStore:
    def ready_missions(self):
        return [{
            "mission_id": "MIS-3", "risk": "normal", "base_release": "REL-3",
            "attempt": 0, "fencing_token": 0,
            "payload": {
                "objective": "change one bounded file", "non_goals": [],
                "incident_evidence": {}, "base_release": "REL-3",
                "allowed_paths": ["src/*.py"], "acceptance_profile": "safe-v1",
                "declared_risk": "normal", "rollback_release": "REL-2",
            },
        }]

    def mark_mission_enqueued(self, mission_id, *, expected_attempt, fencing_token):
        assert (mission_id, expected_attempt, fencing_token) == ("MIS-3", 1, 1)
        return True


class _CaptureBroker:
    def __init__(self):
        self.arguments = None

    def request(self, operation, arguments):
        assert operation == "work_enqueue"
        self.arguments = arguments
        return {"work_id": arguments["work_id"]}


class _PreparedCoordinator:
    def prepare(self, *, mission_id, release_id):
        assert (mission_id, release_id) == ("MIS-3", "REL-3")
        return PreparedMissionBase(mission_id, release_id, "a" * 64)


def test_queue_payload_has_hash_and_release_id_but_no_source_path() -> None:
    broker = _CaptureBroker()

    assert reconcile_queued_missions(
        _ReadyStore(), broker, _PreparedCoordinator()) == 1

    payload = broker.arguments["payload"]
    assert payload["base_release"] == "REL-3"
    assert payload["base_tree_hash"] == "a" * 64
    assert not set(payload) & {"base_tree", "base_path", "release_path", "source"}
    assert all(not (isinstance(value, str) and value.startswith("/"))
               for value in payload.values())


def _blocked_settings() -> dict:
    return {
        "prepared_base_root": "/fixed/prepared", "prepared_base_owner_uid": 0,
        "prepared_base_group_gid": 0, "candidate_root": "/fixed/candidates",
        "sandbox_tmp_root": "/fixed/tmp", "sandbox_profile": "/fixed/profile.sb",
        "sandbox_profile_sha256": None,
        "adapter_runtime_root": "/Library/Application Support/ABCR-Bootstrap/adapters/mission-builder",
        "adapter_runtime_owner_uid": 0, "codex_argv": [],
        "codex_argv_sha256": None, "codex_executable_sha256": None,
        "autonomous_qualified": False, "egress_mode": "deny",
        "egress_qualified": False, "egress_socket": None,
        "egress_policy_path": None, "egress_policy_sha256": None,
    }


def test_unqualified_builder_config_is_honestly_blocked_before_spawn() -> None:
    with pytest.raises(ContractError) as caught:
        _runtime_from_settings(_blocked_settings())

    assert caught.value.code == "builder_autonomous_unqualified"


def test_egress_socket_in_swappable_parent_is_rejected() -> None:
    # Darwin's sockaddr_un is only 104 bytes; keep this adversarial path short.
    with tempfile.TemporaryDirectory(prefix="abcr-egr-", dir="/tmp") as raw:
        parent = Path(raw)
        parent.chmod(0o777)
        path = parent / "e.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        path.chmod(0o660)
        try:
            with pytest.raises(ContractError) as caught:
                _secure_unix_socket(path, owner_uid=os.getuid())
        finally:
            listener.close()

    assert caught.value.code == "builder_egress_socket_unsafe"


def test_objective_must_be_a_literal_argv_after_double_dash() -> None:
    template = ("/usr/bin/true", OBJECTIVE_TOKEN)

    with pytest.raises(ContractError) as caught:
        _validated_argv(
            template, sha256(list(template)), "0" * 64,
            executable_owner_uid=0, adapter_root=Path("/usr/bin"))

    assert caught.value.code == "codex_argv_invalid"


_C_PROBE = r"""
#include <arpa/inet.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

static int readable(const char *path) {
    FILE *stream = fopen(path, "rb");
    if (stream == NULL) return 0;
    fclose(stream);
    return 1;
}

static int tcp_connectable(int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return 0;
    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = htons((unsigned short)port);
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    int result = connect(fd, (struct sockaddr *)&address, sizeof(address)) == 0;
    close(fd);
    return result;
}

static int unix_connectable(const char *path) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return 0;
    struct sockaddr_un address;
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    if (strlen(path) >= sizeof(address.sun_path)) return 0;
    strcpy(address.sun_path, path);
    int result = connect(fd, (struct sockaddr *)&address, sizeof(address)) == 0;
    close(fd);
    return result;
}

int main(int argc, char **argv) {
    if (argc != 11) return 90;
    FILE *result = fopen("sandbox-result.txt", "wb");
    if (result == NULL) return 91;
    for (int index = 1; index <= 6; index++)
        fprintf(result, "%d ", readable(argv[index]));
    fprintf(result, "%d %d\n", tcp_connectable(atoi(argv[7])),
            unix_connectable(argv[8]));
    fclose(result);
    return 0;
}
"""


@pytest.mark.skipif(not SANDBOX_EXEC.is_file(), reason="sandbox-exec unavailable")
def test_real_seatbelt_denies_keys_ledger_release_spool_base_and_network() -> None:
    with tempfile.TemporaryDirectory(prefix="abcr-builder-test-", dir="/tmp") as raw:
        root = Path(raw).resolve()
        candidate = root / "candidate"
        adapter_root = root / "adapter"
        temporary = root / "tmp"
        secrets = root / "outside"
        for path, mode in ((candidate, 0o700), (adapter_root, 0o755),
                           (temporary, 0o700), (secrets, 0o700)):
            path.mkdir()
            os.chmod(path, mode)

        key = secrets / "private.pem"
        ledger = secrets / "ledger.jsonl"
        release = secrets / "sealed-release.py"
        spool = secrets / "ready-work.json"
        prepared = secrets / "coordinator-base.py"
        for path in (key, ledger, release, spool, prepared):
            path.write_text("sentinel\n", encoding="utf-8")
        escape = candidate / "escape-to-key"
        escape.symlink_to(key)

        source = adapter_root / "probe.c"
        executable = adapter_root / "probe"
        source.write_text(_C_PROBE, encoding="utf-8")
        subprocess.run(
            ["/usr/bin/clang", "-Os", "-o", str(executable), str(source)],
            check=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False)
        source.unlink()
        os.chmod(executable, 0o550)
        os.chmod(adapter_root, 0o550)

        profile = root / "builder.sb"
        profile.write_bytes(BUILDER_PROFILE.read_bytes())
        os.chmod(profile, 0o400)

        tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_server.bind(("127.0.0.1", 0))
        tcp_server.listen(1)
        unix_path = secrets / "broker.sock"
        unix_server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        unix_server.bind(str(unix_path))
        unix_server.listen(1)
        try:
            argv_template = (
                str(executable), str(key), str(ledger), str(release), str(spool),
                str(prepared), str(escape), str(tcp_server.getsockname()[1]),
                str(unix_path), "--", OBJECTIVE_TOKEN,
            )
            adapter = SandboxedCodexAdapter(
                argv_template=argv_template,
                argv_sha256=sha256(list(argv_template)),
                executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                executable_owner_uid=os.getuid(), adapter_root=adapter_root,
                runtime_root=adapter_root, runtime_owner_uid=os.getuid(),
                sandbox_profile=profile,
                sandbox_profile_sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),
                sandbox_profile_owner_uid=os.getuid(), temporary_root=temporary,
                temporary_owner_uid=os.getuid(), egress_socket=None,
                timeout_seconds=10)
            marker = root / "objective-was-a-shell"

            code = adapter.run(candidate, f"; /usr/bin/touch {marker}; #")
        finally:
            tcp_server.close()
            unix_server.close()

        assert code == 0
        assert (candidate / "sandbox-result.txt").read_text().split() == ["0"] * 8
        assert not marker.exists()


def _load_installer():
    path = ROOT / "scripts/install_abcr_runtime.py"
    loader = importlib.machinery.SourceFileLoader("abcr_installer_policy_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_installer_verify_receipt_invokes_independent_scientific_rescan(
        tmp_path: Path, monkeypatch) -> None:
    installer = _load_installer()
    release_id = "REL-" + "b" * 64
    release_root = tmp_path / "releases"
    release = release_root / release_id
    release.mkdir(parents=True)
    receipt_root = tmp_path / "receipts"
    receipt_root.mkdir()
    core = {"operation": "seal_release", "nonce": "n", "tree_hash": "a" * 64,
            "object_id": release_id}
    receipt_id = installer.digest(core)
    observed = [{"path": "safe.py", "mode": 0o440, "size": 1,
                 "sha256": "c" * 64}]
    receipt = {**core, "receipt_id": receipt_id,
               "sealed_tree_hash": installer.digest(observed),
               "sealed_path": str(release), "created_at": "now"}
    monkeypatch.setattr(installer, "RELEASE_ROOT", release_root)
    monkeypatch.setattr(installer, "RECEIPT_ROOT", receipt_root)
    monkeypatch.setattr(installer, "require_real_dir", lambda *args, **kwargs: None)
    monkeypatch.setattr(installer, "read_json", lambda *args, **kwargs: receipt)
    monkeypatch.setattr(installer, "tree_entries", lambda *args, **kwargs: observed)
    called = []

    def stop_after_policy(root, entries, *, owner_uid):
        called.append((root, entries, owner_uid))
        raise installer.InstallBlocked("policy sentinel")

    monkeypatch.setattr(
        installer, "enforce_release_scientific_content_policy", stop_after_policy)

    with pytest.raises(installer.InstallBlocked, match="policy sentinel"):
        installer.verify_receipt(receipt_id)

    assert called == [(release, observed, 0)]
    assert installer.FROZEN_SCIENTIFIC_SHA256 == FROZEN_SCIENTIFIC_SHA256
    assert installer._SCIENTIFIC_SEGMENTS == release_policy._SENSITIVE_SEGMENTS
    assert installer._SCIENTIFIC_DATA_SUFFIXES == release_policy._DATA_SUFFIXES
    assert installer._POLICY_MAX_MEMBERS == release_policy._MAX_ARCHIVE_MEMBERS
    assert installer._POLICY_MAX_MEMBER_BYTES == release_policy._MAX_ARCHIVE_MEMBER_BYTES
    assert installer._POLICY_MAX_TOTAL_BYTES == release_policy._MAX_ARCHIVE_TOTAL_BYTES
    assert installer._POLICY_MAX_ARCHIVE_DEPTH == release_policy._MAX_ARCHIVE_DEPTH
    assert (installer._POLICY_UNSUPPORTED_ARCHIVE_MAGIC
            == release_policy._UNSUPPORTED_ARCHIVE_MAGIC)


def test_installer_scientific_rescan_rejects_renamed_frozen_bytes(
        tmp_path: Path) -> None:
    installer = _load_installer()
    release = tmp_path / "release"
    path = release / "assets/runtime-table.bin"
    path.parent.mkdir(parents=True)
    raw = (ROOT / "data/benchmarks/ifeval_zh_v1.json").read_bytes()
    path.write_bytes(raw)
    observed = [{"path": "assets/runtime-table.bin",
                 "mode": path.stat().st_mode & 0o777, "size": len(raw),
                 "sha256": hashlib.sha256(raw).hexdigest()}]

    with pytest.raises(installer.InstallBlocked, match="frozen scientific bytes"):
        installer.enforce_release_scientific_content_policy(
            release, observed, owner_uid=os.getuid())


def test_installer_scientific_rescan_rejects_gzipped_frozen_bytes(
        tmp_path: Path) -> None:
    installer = _load_installer()
    release = tmp_path / "release"
    path = release / "assets/runtime-cache.dat"
    path.parent.mkdir(parents=True)
    raw = gzip.compress((ROOT / "data/benchmarks/ifeval_zh_v1.json").read_bytes())
    path.write_bytes(raw)
    observed = [{"path": "assets/runtime-cache.dat",
                 "mode": path.stat().st_mode & 0o777, "size": len(raw),
                 "sha256": hashlib.sha256(raw).hexdigest()}]

    with pytest.raises(installer.InstallBlocked, match="frozen scientific bytes"):
        installer.enforce_release_scientific_content_policy(
            release, observed, owner_uid=os.getuid())


@pytest.mark.parametrize("wrapper", ["plain", "zip", "gzip"])
def test_installer_rescan_rejects_normalized_dataset_after_rename(
        tmp_path: Path, wrapper: str) -> None:
    installer = _load_installer()
    benchmark = json.loads((ROOT / "data/benchmarks/ifeval_zh_v1.json")
                           .read_text(encoding="utf-8"))
    normalized = json.dumps(
        benchmark["items"], ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    assert hashlib.sha256(normalized).hexdigest() in FROZEN_SCIENTIFIC_SHA256
    if wrapper == "plain":
        raw = normalized
    elif wrapper == "gzip":
        raw = gzip.compress(normalized)
    else:
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("pkg/assets/table.bin", normalized)
        raw = archive.getvalue()
    release = tmp_path / "release"
    path = release / "assets/runtime-cache.dat"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    observed = [{"path": "assets/runtime-cache.dat",
                 "mode": path.stat().st_mode & 0o777, "size": len(raw),
                 "sha256": hashlib.sha256(raw).hexdigest()}]

    with pytest.raises(installer.InstallBlocked, match="frozen scientific bytes"):
        installer.enforce_release_scientific_content_policy(
            release, observed, owner_uid=os.getuid())


def test_installer_rejects_manifest_that_omits_a_sealed_file() -> None:
    installer = _load_installer()
    declared = [{"path": "env/bin/python", "mode": 0o555, "size": 1,
                 "sha256": "a" * 64}]
    core = {"tree_hash": installer.digest(declared),
            "runtime_digest": "b" * 64, "lock_hash": "c" * 64,
            "service_config_hash": "d" * 64, "verification_hash": "e" * 64}
    manifest = {"release_id": "REL-" + installer.digest(core), **core,
                "tree_entries": declared, "runtime_relpath": "env",
                "lock_relpath": "requirements.lock",
                "service_config_relpath": "configs/control/service-topology-v1.json",
                "service_payloads": {}}
    observed = [
        {"path": "env/bin/python", "mode": 0o550, "size": 1,
         "sha256": "a" * 64},
        {"path": "injected.py", "mode": 0o440, "size": 1,
         "sha256": "f" * 64},
        {"path": "release-manifest.json", "mode": 0o440, "size": 1,
         "sha256": "0" * 64},
    ]

    with pytest.raises(installer.InstallBlocked, match="differs"):
        installer.validate_release_manifest(manifest, observed)


def test_installer_accepts_exact_manifest_after_broker_mode_normalization() -> None:
    installer = _load_installer()
    declared = [{"path": "env/bin/python", "mode": 0o555, "size": 1,
                 "sha256": "a" * 64}]
    core = {"tree_hash": installer.digest(declared),
            "runtime_digest": "b" * 64, "lock_hash": "c" * 64,
            "service_config_hash": "d" * 64, "verification_hash": "e" * 64}
    manifest = {"release_id": "REL-" + installer.digest(core), **core,
                "tree_entries": declared, "runtime_relpath": "env",
                "lock_relpath": "requirements.lock",
                "service_config_relpath": "configs/control/service-topology-v1.json",
                "service_payloads": {}}
    observed = [
        {"path": "env/bin/python", "mode": 0o550, "size": 1,
         "sha256": "a" * 64},
        {"path": "release-manifest.json", "mode": 0o440, "size": 1,
         "sha256": "0" * 64},
    ]

    installer.validate_release_manifest(manifest, observed)


def test_release_cannot_omit_genesis_or_builder_sandbox_tcb() -> None:
    assert {
        "scripts/bootstrap_abcr_genesis.py",
        "ops/install/genesis-authority-v1.json",
        "ops/sandbox/abcr-builder.sb",
    }.issubset(BOOTSTRAP_REQUIRED_PATHS)
