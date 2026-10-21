"""genesis probation 资格化三件套的行为测试:协调器、canary 探针、abort。

协调器测试用一个进程内 MiniBroker(真实 AF_UNIX + 单请求单连接 framing)扮演
seal-broker,fixture 全部经真实 canonical/digest 构造;不打桩内部函数,只注入
路径与身份(与 genesis/selector 的测试注入惯例一致)。
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from abcr.control.contracts import canonical_json, sha256
from abcr.control.worktree import scan_tree, tree_hash

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str, name: str):
    path = ROOT / relative
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


GENESIS = _load("scripts/bootstrap_abcr_genesis.py", "test_qualify_genesis_mod")
QUALIFY = _load("scripts/qualify_abcr_genesis_probation.py", "test_qualify_mod")

MISSION_ID = "reviewed-runtime-qual-fixture-1"
COMMIT = "a" * 40


from abcr.control.work_spool import WorkSpool, SpoolError, Claim


class MiniBroker(threading.Thread):
    """真实 WorkSpool 支撑的 broker 替身:work_* op 直落真 spool,忠实复现
    ack 后结果隐藏、archive 重放、双 ack FileNotFoundError 等语义(panel 指出
    旧脚本化替身漏了这些)。seal_verification 仍脚本化返回收据。

    canary/activate 的"服务 drain"由测试用 drain_stage() 直接以 spool
    claim→submit_result 模拟(相当于 abcr-canary/abcr-activator 的 --once)。
    """

    def __init__(self, socket_path: Path, spool_root: Path):
        super().__init__(daemon=True)
        self.socket_path = socket_path
        self.spool = WorkSpool(spool_root, create=True)
        self.enqueued: list[dict] = []
        self.acked: list[dict] = []
        self.sealed: list[dict] = []
        self.seal_receipt = None
        self._stopping = threading.Event()
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(socket_path))
        self.server.listen(8)
        self.server.settimeout(0.2)

    def stop(self):
        self._stopping.set()
        self.join(timeout=5)
        self.server.close()

    def drain_stage(self, stage: str, handler) -> int:
        """模拟一次服务 --once:claim 一个 ready 项,跑 handler,submit_result。"""
        ready = self.spool._dir(stage, "ready")
        count = 0
        for path in sorted(ready.glob("*.json")):
            work_id = path.stem
            claim = self.spool.claim(stage, work_id)
            if claim is None:
                continue
            try:
                result = {"ok": True, "result": handler(claim.payload, work_id,
                                                         claim.fencing_token)}
            except Exception as exc:
                result = {"ok": False, "error_code": type(exc).__name__}
            self.spool.submit_result(claim, result, consumer="test-service")
            count += 1
        return count

    def _respond(self, operation: str, arguments: dict):
        stage = arguments.get("stage")
        if operation == "work_result_list":
            results_dir = self.spool._dir(stage, "results")
            acks_dir = self.spool._dir(stage, "acks")
            catalog = []
            for path in sorted(results_dir.glob("*.json")):
                if (acks_dir / path.name).exists():
                    continue
                envelope = json.loads(path.read_text())
                catalog.append({"work_id": path.stem, "attempt": envelope["attempt"],
                                "fencing_token": envelope["fencing_token"]})
            if arguments.get("include_fence") is not True:
                return [item["work_id"] for item in catalog]
            return catalog
        if operation == "work_result_read":
            return self.spool.read_result(stage, arguments["work_id"],
                                          attempt=arguments["attempt"],
                                          fencing_token=arguments["fencing_token"])
        if operation == "work_enqueue":
            self.enqueued.append(arguments)
            path = self.spool.enqueue(stage, arguments["work_id"], arguments["payload"],
                                      attempt=arguments["attempt"],
                                      fencing_token=arguments["fencing_token"],
                                      producer=arguments["producer"])
            return {"work_id": path.stem}
        if operation == "work_ack":
            self.acked.append(arguments)
            claim = Claim(stage, arguments["work_id"], arguments["attempt"],
                          arguments["fencing_token"],
                          self.spool._dir(stage, "inflight") / f"{arguments['work_id']}.json", {})
            self.spool.ack(claim, expected_result_hash=arguments["result_hash"])
            return {"acked": True}
        if operation == "seal_verification":
            self.sealed.append(arguments)
            return self.seal_receipt
        raise RuntimeError("broker_unsupported_op")

    def run(self):
        while not self._stopping.is_set():
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                continue
            with connection:
                raw = b""
                while b"\n" not in raw:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    raw += chunk
                if b"\n" not in raw:
                    continue
                request = json.loads(raw)
                try:
                    result = self._respond(request["operation"], request["arguments"])
                    payload = {"ok": True, "result": result}
                except Exception as exc:
                    # 镜像真 broker dispatch:异常一律映射为 type(exc).__name__。
                    code = "broker_unsupported_op" if str(exc) == "broker_unsupported_op" \
                        else type(exc).__name__
                    payload = {"ok": False, "error_code": code}
                connection.sendall(canonical_json(payload) + b"\n")


def _write(path: Path, raw: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        os.chmod(path, 0o600)
    path.write_bytes(raw)
    os.chmod(path, mode)


def _envelope(stage: str, result: dict) -> dict:
    return {"schema_version": 1, "stage": stage, "work_id": MISSION_ID,
            "attempt": 1, "fencing_token": 1, "consumer": "test",
            "result": result, "result_hash": sha256(result),
            "completed_at": "2026-07-25T00:00:00+00:00"}


class Rig:
    pass


def make_rig(tmp_path: Path, *, installer_body: bytes = b"probe_argv abcr_genesis_canary_probe.py\n",
             with_verification: bool = True) -> Rig:
    rig = Rig()
    rig.uid = os.getuid()
    rig.gid = os.getgid()
    rig.release_root = tmp_path / "releases"
    rig.receipt_root = tmp_path / "receipts"
    rig.component_root = tmp_path / "components"
    rig.active_path = tmp_path / "abcr" / "active.json"
    rig.staging_root = tmp_path / "staging"
    rig.receipt_root.mkdir(parents=True)
    rig.staging_root.mkdir(parents=True)
    (tmp_path / "abcr").mkdir(parents=True)

    rig.release_id = "REL-" + sha256(b"fixture-release")
    sealed = rig.release_root / rig.release_id
    rig.sealed = sealed
    manifest = {"release_id": rig.release_id,
                "tree_hash": sha256(b"tree"), "runtime_digest": sha256(b"run"),
                "lock_hash": sha256(b"lock"), "service_config_hash": sha256(b"svc"),
                "verification_hash": sha256(b"verify"),
                "tree_entries": [], "service_payloads": {}}
    _write(sealed / "release-manifest.json", canonical_json(manifest) + b"\n", 0o440)
    _write(sealed / "scripts" / "install_abcr_runtime.py", installer_body, 0o440)
    _write(sealed / "scripts" / "abcr_genesis_canary_probe.py", b"# probe\n", 0o440)
    rig.manifest = manifest
    rig.sealed_tree_hash = tree_hash(scan_tree(sealed))

    nonce = f"genesis:{GENESIS.AUTHORITY_SHA}:{COMMIT}:{rig.release_id}"
    source_tree_hash = sha256(b"source-tree")
    receipt_core = {"operation": "seal_release", "nonce": nonce,
                    "tree_hash": source_tree_hash, "object_id": rig.release_id}
    rig.receipt_id = sha256(receipt_core)
    receipt = {**receipt_core, "receipt_id": rig.receipt_id,
               "sealed_tree_hash": rig.sealed_tree_hash,
               "sealed_path": str(sealed), "created_at": "2026-07-25T00:00:00+00:00"}
    _write(rig.receipt_root / f"{rig.receipt_id}.json",
           canonical_json(receipt) + b"\n", 0o440)

    core = {"schema_version": 1, "ceremony": GENESIS.CEREMONY,
            "authority_sha256": GENESIS.AUTHORITY_SHA,
            "policy_sha256": GENESIS.POLICY_SHA, "human_approved": True,
            "reviewed_commit": COMMIT, "reviewed_release_path": str(sealed),
            "release_id": rig.release_id,
            "release_manifest_sha256": sha256(canonical_json(manifest) + b"\n"),
            "source_tree_hash": source_tree_hash, "broker_seal_nonce": nonce,
            "expected_receipt_id": rig.receipt_id, "tcb": {}}
    rig.authority_id = sha256(core)
    rig.authority = {**core, "authority_id": rig.authority_id}
    rig.authority_path = tmp_path / "genesis-authority-v1.json"
    _write(rig.authority_path, canonical_json(rig.authority) + b"\n", 0o444)

    if with_verification:
        ver_core = {"operation": "seal_verification",
                    "nonce": QUALIFY.NONCE_PREFIX + rig.authority_id + ":" + MISSION_ID,
                    "tree_hash": sha256(b"ver-tree"), "object_id": "VER-" + sha256(b"ver")[:48]}
        rig.ver_receipt_id = sha256(ver_core)
        ver_receipt = {**ver_core, "receipt_id": rig.ver_receipt_id,
                       "sealed_tree_hash": sha256(b"ver-sealed"),
                       "sealed_path": "/x", "created_at": "2026-07-25T00:00:00+00:00"}
        _write(rig.receipt_root / f"{rig.ver_receipt_id}.json",
               canonical_json(ver_receipt) + b"\n", 0o440)
    return rig


def write_activation_state(rig: Rig, canary_hash: str) -> None:
    record = {"release_id": rig.release_id, "previous_release": None,
              "release_receipt_id": rig.receipt_id,
              "verification_hash": rig.manifest["verification_hash"],
              "canary_hash": canary_hash, "activated_at": "2026-07-25T00:00:00+00:00"}
    _write(rig.active_path, canonical_json(record) + b"\n", 0o444)
    for name, record_ in (("active-slot.json", {"slot": "slot-b", "generation": 2,
                                                "probation": False}),
                          ("last-known-good.json", {"slot": "slot-b", "generation": 2,
                                                    "probation": False})):
        _write(rig.component_root / "seal-broker" / name,
               canonical_json(record_) + b"\n", 0o444)
    _write(rig.component_root / "launcher" / "active-slot.json",
           canonical_json({"slot": "slot-a", "generation": 1, "probation": False}) + b"\n",
           0o444)


def qualify_kwargs(rig: Rig, socket_path: Path) -> dict:
    return dict(genesis=GENESIS, broker_socket=socket_path,
                release_root=rig.release_root, active_path=rig.active_path,
                component_root=rig.component_root, authority_path=rig.authority_path,
                receipt_root=rig.receipt_root, expected_user=None,
                owner_uid=rig.uid, release_gid=rig.gid, poll_seconds=0.02)


@pytest.fixture()
def short_socket_dir():
    with tempfile.TemporaryDirectory(prefix="abcrq", dir="/tmp") as base:
        yield Path(base)


def _canary_ref():
    return {"operation": "seal_canary", "receipt_id": sha256(b"cny-receipt"),
            "object_id": "CNY-" + sha256(b"cny")[:48],
            "sealed_tree_hash": sha256(b"cny-tree")}


def _make_canary_handler(verdict="PASS", ref=None):
    ref = ref or _canary_ref()

    def handler(payload, work_id, fence):
        assert set(payload) == {"mission_id", "release_ref", "verification_ref",
                                "expected_version", "old_release"}
        return {"mission_id": work_id, "verdict": verdict, "broker_ref": ref}
    return handler


def _make_activate_handler(rig: Rig):
    def handler(payload, work_id, fence):
        assert set(payload) == {"canary_ref"}
        canary_hash = sha256(b"canary-" + rig.release_id.encode())
        write_activation_state(rig, canary_hash)  # 模拟 broker.activate 落 active.json
        return {"release_id": rig.release_id, "previous_release": None,
                "release_receipt_id": rig.receipt_id,
                "verification_hash": rig.manifest["verification_hash"],
                "canary_hash": canary_hash, "activated_at": "2026-07-25T00:00:00+00:00"}
    return handler


def _run_ceremony(rig, broker, socket_path, capsys, *, canary_verdict="PASS"):
    """按真实首次激活顺序交错运行:qualify(pending)→drain→qualify(pending)→drain→qualify(active)。"""
    outputs = []

    def one():
        rc = QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
        outputs.append((rc, json.loads(capsys.readouterr().out.strip())))
        return rc

    rc1 = one()                                        # 入队 canary → PENDING
    broker.drain_stage("canary", _make_canary_handler(canary_verdict))
    rc2 = one()                                        # 见 canary 结果
    if canary_verdict == "PASS":
        broker.drain_stage("activate", _make_activate_handler(rig))
        rc3 = one()                                    # 见 active.json → ACTIVE
        return outputs, (rc1, rc2, rc3)
    return outputs, (rc1, rc2)


def test_qualify_happy_path_sequential_drain_reaches_active(tmp_path, short_socket_dir, capsys):
    rig = make_rig(tmp_path)
    socket_path = short_socket_dir / "b.sock"
    broker = MiniBroker(socket_path, tmp_path / "spool")
    broker.start()
    try:
        outputs, rcs = _run_ceremony(rig, broker, socket_path, capsys)
    finally:
        broker.stop()
    assert rcs == (QUALIFY.PENDING_RC, QUALIFY.PENDING_RC, 0)
    assert outputs[0][1]["awaiting_stage"] == "canary"
    assert outputs[0][1]["drain_identity"] == "abcr-canary"
    assert outputs[1][1]["awaiting_stage"] == "activate"
    final = outputs[2][1]
    assert final == {"ok": True, "activation_state": "ACTIVE", "release_id": rig.release_id,
                     "canary_hash": sha256(b"canary-" + rig.release_id.encode()),
                     "live_pilot_qualified": False, "autonomous_qualified": False,
                     "cleanup_incomplete": False}
    stages = [item["stage"] for item in broker.enqueued]
    assert stages.count("canary") >= 1 and stages.count("activate") >= 1
    assert broker.enqueued[0]["payload"]["expected_version"] == rig.release_id


def test_qualify_rerun_before_ack_reconverges_not_wedged(tmp_path, short_socket_dir, capsys):
    """P1 回归:canary 已产出但未 ack 时,反复重跑必须收敛到 activate,而非楔死。"""
    rig = make_rig(tmp_path)
    socket_path = short_socket_dir / "b.sock"
    broker = MiniBroker(socket_path, tmp_path / "spool")
    broker.start()
    try:
        # 入队 canary + drain,得到可见未 ack 的 canary 结果
        QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
        capsys.readouterr()
        broker.drain_stage("canary", _make_canary_handler("PASS"))
        # 连续多次重跑(模拟崩溃/重试):每次都应推进到 activate-pending,canary 不被 ack
        for _ in range(3):
            rc = QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
            out = json.loads(capsys.readouterr().out.strip())
            assert rc == QUALIFY.PENDING_RC and out["awaiting_stage"] == "activate"
        # canary 结果始终未被 ack(仍可见)
        assert broker.acked == []
        # drain activate 后收敛
        broker.drain_stage("activate", _make_activate_handler(rig))
        rc = QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
        assert rc == 0
    finally:
        broker.stop()


def test_qualify_short_circuits_when_activation_already_recorded(tmp_path, capsys):
    rig = make_rig(tmp_path)
    canary_hash = sha256(b"prior-canary")
    write_activation_state(rig, canary_hash)
    missing_socket = tmp_path / "nonexistent.sock"
    rc = QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, missing_socket))
    assert rc == 0
    out = json.loads(capsys.readouterr().out.strip())
    assert out["canary_hash"] == canary_hash and out["activation_state"] == "ACTIVE"


def test_qualify_canary_fail_is_terminal_and_never_activates(tmp_path, short_socket_dir, capsys):
    rig = make_rig(tmp_path)
    socket_path = short_socket_dir / "b.sock"
    broker = MiniBroker(socket_path, tmp_path / "spool")
    broker.start()
    try:
        QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
        capsys.readouterr()
        broker.drain_stage("canary", _make_canary_handler("FAIL"))
        with pytest.raises(QUALIFY.QualifyBlocked) as blocked:
            QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
    finally:
        broker.stop()
    assert blocked.value.code == "genesis_canary_failed"
    assert not rig.active_path.exists()
    assert "activate" not in [item["stage"] for item in broker.enqueued]


def test_qualify_active_conflict_on_foreign_activation(tmp_path):
    rig = make_rig(tmp_path)
    foreign = {"release_id": "REL-" + sha256(b"foreign"), "previous_release": None,
               "release_receipt_id": rig.receipt_id,
               "verification_hash": rig.manifest["verification_hash"],
               "canary_hash": sha256(b"x"), "activated_at": "2026-07-25T00:00:00+00:00"}
    _write(rig.active_path, canonical_json(foreign) + b"\n", 0o444)
    with pytest.raises(QUALIFY.QualifyBlocked) as blocked:
        QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, tmp_path / "no.sock"))
    assert blocked.value.code == "genesis_qualify_active_conflict"


def test_qualify_promotion_not_completed_blocks(tmp_path):
    rig = make_rig(tmp_path)
    write_activation_state(rig, sha256(b"c"))
    # 把 seal-broker 指针退回 probation:True → 晋级未完成
    _write(rig.component_root / "seal-broker" / "active-slot.json",
           canonical_json({"slot": "slot-b", "generation": 2, "probation": True}) + b"\n", 0o444)
    with pytest.raises(QUALIFY.QualifyBlocked) as blocked:
        QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, tmp_path / "no.sock"))
    assert blocked.value.code == "genesis_probation_not_promoted"


def test_qualify_identity_gate_rejects_wrong_user(tmp_path):
    rig = make_rig(tmp_path)
    with pytest.raises(QUALIFY.QualifyBlocked) as blocked:
        QUALIFY.qualify(rig.authority_id, 1,
                        **{**qualify_kwargs(rig, tmp_path / "no.sock"),
                           "expected_user": "definitely-not-this-user"})
    assert blocked.value.code == "genesis_qualify_identity"


def test_qualify_probe_gate_blocks_before_any_enqueue(tmp_path, short_socket_dir):
    rig = make_rig(tmp_path, installer_body=b'probe_argv ["/usr/bin/false"]\n')
    socket_path = short_socket_dir / "b.sock"
    broker = MiniBroker(socket_path, tmp_path / "spool")
    broker.start()
    try:
        with pytest.raises(QUALIFY.QualifyBlocked) as blocked:
            QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
    finally:
        broker.stop()
    assert blocked.value.code == "genesis_canary_probe_unqualified"
    assert broker.enqueued == []


def test_qualify_rejects_tampered_authority(tmp_path):
    rig = make_rig(tmp_path)
    tampered = dict(rig.authority)
    tampered["release_id"] = "REL-" + sha256(b"other")
    _write(rig.authority_path, canonical_json(tampered) + b"\n", 0o444)
    with pytest.raises(QUALIFY.QualifyBlocked) as blocked:
        QUALIFY.qualify(rig.authority_id, 30,
                        **qualify_kwargs(rig, tmp_path / "no.sock"))
    assert blocked.value.code == "genesis_authority_binding_mismatch"


def test_qualify_rejects_pending_genesis_receipt(tmp_path):
    rig = make_rig(tmp_path)
    path = rig.receipt_root / f"{rig.receipt_id}.json"
    receipt = json.loads(path.read_bytes())
    receipt["genesis_pending"] = {"authority_id": rig.authority_id,
                                  "reviewed_commit": COMMIT}
    os.chmod(path, 0o640)
    _write(path, canonical_json(receipt) + b"\n", 0o440)
    with pytest.raises(QUALIFY.QualifyBlocked) as blocked:
        QUALIFY.qualify(rig.authority_id, 30,
                        **qualify_kwargs(rig, tmp_path / "no.sock"))
    assert blocked.value.code == "genesis_incomplete"


def test_seal_genesis_verification_builds_and_seals_artifact(tmp_path, short_socket_dir, capsys):
    rig = make_rig(tmp_path, with_verification=False)
    attestation_core = {
        "mission_id": MISSION_ID, "fencing_token": 1,
        "base_tree_hash": sha256(b"base"),
        "candidate_tree_hash": rig.manifest["tree_hash"],
        "profile_hash": sha256(b"profile"), "oracle_set_hash": sha256(b"oracles"),
        "changed_paths": [], "verdict": "PASS",
        "verified_at": "2026-07-25T00:00:00+00:00", "isolation": "sandbox-exec:" + sha256(b"sb")}
    attestation = {**attestation_core, "attestation_hash": sha256(attestation_core),
                   "sealed": {"signature_b64": "x"}}
    manifest = dict(rig.manifest)
    manifest["verification_hash"] = attestation["attestation_hash"]
    _write(rig.sealed / "release-manifest.json", canonical_json(manifest) + b"\n", 0o440)
    rig.manifest = manifest
    attestation_path = tmp_path / "attestation.json"
    _write(attestation_path, canonical_json(attestation) + b"\n", 0o444)

    socket_path = short_socket_dir / "b.sock"
    broker = MiniBroker(socket_path, tmp_path / "spool")
    broker.seal_receipt = {
        "receipt_id": sha256(b"ver-seal"), "operation": "seal_verification",
        "nonce": QUALIFY.NONCE_PREFIX + rig.authority_id + ":" + MISSION_ID,
        "object_id": "VER-" + sha256(b"obj")[:48], "tree_hash": sha256(b"t"),
        "sealed_tree_hash": sha256(b"s"), "sealed_path": "/x",
        "created_at": "2026-07-25T00:00:00+00:00"}
    broker.start()
    try:
        rc = QUALIFY.seal_genesis_verification(
            rig.authority_id, attestation_path, genesis=GENESIS,
            broker_socket=socket_path, release_root=rig.release_root,
            staging_root=rig.staging_root, authority_path=rig.authority_path,
            receipt_root=rig.receipt_root,
            expected_user=None, owner_uid=rig.uid, release_gid=rig.gid)
    finally:
        broker.stop()
    assert rc == 0
    out = json.loads(capsys.readouterr().out.strip())
    assert out["ok"] is True and out["mission_id"] == MISSION_ID
    assert len(broker.sealed) == 1
    staged = rig.staging_root / broker.sealed[0]["object_id"] / "verification.json"
    document = json.loads(staged.read_bytes())
    assert document["kind"] == "verification"
    assert document["attestation"]["attestation_hash"] == attestation["attestation_hash"]


def test_seal_genesis_verification_rejects_unusable_mission_id(tmp_path):
    rig = make_rig(tmp_path, with_verification=False)
    attestation_core = {
        "mission_id": "has:colon", "fencing_token": 1,
        "base_tree_hash": sha256(b"base"),
        "candidate_tree_hash": rig.manifest["tree_hash"],
        "profile_hash": sha256(b"profile"), "oracle_set_hash": sha256(b"oracles"),
        "changed_paths": [], "verdict": "PASS",
        "verified_at": "2026-07-25T00:00:00+00:00", "isolation": "sandbox-exec:" + sha256(b"sb")}
    attestation = {**attestation_core, "attestation_hash": sha256(attestation_core),
                   "sealed": {"signature_b64": "x"}}
    manifest = dict(rig.manifest)
    manifest["verification_hash"] = attestation["attestation_hash"]
    _write(rig.sealed / "release-manifest.json", canonical_json(manifest) + b"\n", 0o440)
    attestation_path = tmp_path / "attestation.json"
    _write(attestation_path, canonical_json(attestation) + b"\n", 0o444)
    with pytest.raises(QUALIFY.QualifyBlocked) as blocked:
        QUALIFY.seal_genesis_verification(
            rig.authority_id, attestation_path, genesis=GENESIS,
            broker_socket=tmp_path / "no.sock", release_root=rig.release_root,
            staging_root=rig.staging_root, authority_path=rig.authority_path,
            receipt_root=rig.receipt_root,
            expected_user=None, owner_uid=rig.uid, release_gid=rig.gid)
    assert blocked.value.code == "genesis_mission_id_unusable"


def test_seal_genesis_verification_rejects_conflicting_prior_receipt(tmp_path):
    """发现歧义防线:已存在同 authority 前缀但不同对象的 verification 收据 → 早停。"""
    rig = make_rig(tmp_path)
    attestation_core = {
        "mission_id": MISSION_ID, "fencing_token": 1, "base_tree_hash": sha256(b"base"),
        "candidate_tree_hash": rig.manifest["tree_hash"],
        "profile_hash": sha256(b"profile"), "oracle_set_hash": sha256(b"oracles"),
        "changed_paths": [], "verdict": "PASS",
        "verified_at": "2026-07-25T00:00:00+00:00", "isolation": "sandbox-exec:" + sha256(b"sb")}
    attestation = {**attestation_core, "attestation_hash": sha256(attestation_core),
                   "sealed": {"signature_b64": "x"}}
    manifest = dict(rig.manifest)
    manifest["verification_hash"] = attestation["attestation_hash"]
    _write(rig.sealed / "release-manifest.json", canonical_json(manifest) + b"\n", 0o440)
    attestation_path = tmp_path / "attestation.json"
    _write(attestation_path, canonical_json(attestation) + b"\n", 0o444)
    # make_rig 已放了一个 object_id 为 "VER-...obj" 的既存 verification 收据(不同对象)
    with pytest.raises(QUALIFY.QualifyBlocked) as blocked:
        QUALIFY.seal_genesis_verification(
            rig.authority_id, attestation_path, genesis=GENESIS,
            broker_socket=tmp_path / "no.sock", release_root=rig.release_root,
            staging_root=rig.staging_root, authority_path=rig.authority_path,
            receipt_root=rig.receipt_root,
            expected_user=None, owner_uid=rig.uid, release_gid=rig.gid)
    assert blocked.value.code == "genesis_verification_conflict"


PROBE = ROOT / "scripts" / "abcr_genesis_canary_probe.py"


def _run_probe(release_root: Path, request: dict) -> dict:
    """探针现在从固定 RELEASE_ROOT 解析请求指名的 release,测试据此注入根路径。"""
    probe_copy = release_root / "scripts" / "abcr_genesis_canary_probe.py"
    probe_copy.parent.mkdir(parents=True, exist_ok=True)
    source = PROBE.read_text(encoding="utf-8").replace(
        'RELEASE_ROOT = Path("/Users/superagent/.abcr/releases")',
        f'RELEASE_ROOT = Path({str(release_root.parent)!r})')
    probe_copy.write_text(source, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(probe_copy)],
        input=canonical_json(request) + b"\n", capture_output=True, timeout=60,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "src")})
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _probe_release(tmp_path: Path, *, payload_count: int = 12,
                   marker: bytes = b"t") -> tuple[Path, str]:
    core = {"tree_hash": sha256(marker), "runtime_digest": sha256(b"r"),
            "lock_hash": sha256(b"l"), "service_config_hash": sha256(b"s"),
            "verification_hash": sha256(b"v")}
    release_id = "REL-" + sha256(core)
    root = tmp_path / release_id
    manifest = {**core, "release_id": release_id,
                "service_payloads": {f"svc{i}": {} for i in range(payload_count)}}
    _write(root / "release-manifest.json", canonical_json(manifest) + b"\n", 0o444)
    return root, release_id


def test_canary_probe_passes_on_bound_release(tmp_path):
    root, release_id = _probe_release(tmp_path)
    response = _run_probe(root, {"expected_version": release_id, "release_id": release_id})
    assert response == {"observed_version": release_id, "semantic_ok": True,
                        "reason": "sealed_release_semantics_ok"}


def test_canary_probe_fails_when_requested_release_absent(tmp_path):
    root, release_id = _probe_release(tmp_path)
    other = "REL-" + sha256(b"different")
    response = _run_probe(root, {"expected_version": other, "release_id": other})
    assert response["semantic_ok"] is False
    assert response["reason"] == "release_directory_unavailable"


def test_canary_probe_validates_the_requested_release_not_its_own(tmp_path):
    """升级路径:探针属于旧 release,请求指向新 release,必须校验后者。"""
    own, _own_id = _probe_release(tmp_path, marker=b"own")
    other, other_id = _probe_release(tmp_path, marker=b"other")
    response = _run_probe(own, {"expected_version": other_id, "release_id": other_id})
    assert response == {"observed_version": other_id, "semantic_ok": True,
                        "reason": "sealed_release_semantics_ok"}


def test_canary_probe_fails_on_noncanonical_manifest(tmp_path):
    root, release_id = _probe_release(tmp_path)
    manifest_path = root / "release-manifest.json"
    _write(manifest_path, b"{ \"release_id\": \"" + release_id.encode() + b"\" }\n", 0o444)
    response = _run_probe(root, {"expected_version": release_id, "release_id": release_id})
    assert response["semantic_ok"] is False


def test_canary_probe_fails_on_wrong_payload_count(tmp_path):
    root, release_id = _probe_release(tmp_path, payload_count=11)
    response = _run_probe(root, {"expected_version": release_id, "release_id": release_id})
    assert response == {"observed_version": release_id, "semantic_ok": False,
                        "reason": "release_service_payloads_invalid"}


def _abort_rig(tmp_path: Path) -> dict:
    release_id = "REL-" + sha256(b"abort-release")
    paths = {
        "active_path": tmp_path / "abcr" / "active.json",
        "release_root": tmp_path / "releases",
        "receipt_root": tmp_path / "receipts",
        "component_root": tmp_path / "components",
        "selector_path": tmp_path / "libexec" / "abcr-bootstrap-selector",
        "authority_path": tmp_path / "trust" / "genesis-authority-v1.json",
        "completion_path": tmp_path / "trust" / "genesis-completed-v1.json",
        "attest_root": tmp_path / "attest",
        "work_root": tmp_path / "work",
        "library_quarantine_root": tmp_path / "aborted-lib",
        "user_quarantine_root": tmp_path / "aborted-user",
    }
    _write(paths["completion_path"], b"{}\n", 0o444)
    _write(paths["authority_path"], b"{}\n", 0o444)
    _write(paths["receipt_root"] / (sha256(b"r") + ".json"), b"{}\n", 0o440)
    _write(paths["release_root"] / release_id / "release-manifest.json", b"{}\n", 0o440)
    _write(paths["attest_root"] / "attestations" / "VER-x" / "verification.json", b"{}\n", 0o440)
    _write(paths["work_root"] / "canary" / "results" / "m.json", b"{}\n", 0o440)
    _write(paths["component_root"] / "seal-broker" / "active-slot.json", b"{}\n", 0o444)
    _write(paths["selector_path"], b"#!/bin/sh\n", 0o555)
    authority = {"authority_id": sha256(b"abort-authority"), "release_id": release_id}
    return {"paths": paths, "authority": authority, "release_id": release_id}


def test_abort_probation_archives_everything_and_writes_record(tmp_path):
    rig = _abort_rig(tmp_path)
    record = GENESIS.abort_probation(
        rig["authority"], job_probe=lambda label: False,
        socket_probe=lambda: False, **rig["paths"])
    assert record["state"] == "ABORTED"
    paths = rig["paths"]
    assert not paths["completion_path"].exists()
    assert not paths["authority_path"].exists()
    assert not (paths["release_root"] / rig["release_id"]).exists()
    assert not paths["selector_path"].exists()
    assert list(paths["receipt_root"].glob("*.json")) == []
    library = Path(record["library_quarantine"])
    assert (library / "abort-record.json").is_file()
    assert (library / "genesis-authority-v1.json").is_file()
    assert (Path(record["user_quarantine"]) / "releases" / rig["release_id"]).is_dir()
    # 幂等:重跑归档不到任何新东西,但仍成功并留下新的记录
    rerun = GENESIS.abort_probation(
        rig["authority"], job_probe=lambda label: False,
        socket_probe=lambda: False, **rig["paths"])
    assert rerun["archived"] == []


def test_abort_probation_refuses_after_activation(tmp_path):
    rig = _abort_rig(tmp_path)
    _write(rig["paths"]["active_path"], b"{}\n", 0o444)
    with pytest.raises(GENESIS.GenesisBlocked):
        GENESIS.abort_probation(rig["authority"], job_probe=lambda label: False,
                                socket_probe=lambda: False, **rig["paths"])


def test_abort_probation_requires_bootout(tmp_path):
    rig = _abort_rig(tmp_path)
    with pytest.raises(GENESIS.GenesisBlocked):
        GENESIS.abort_probation(rig["authority"],
                                job_probe=lambda label: label == "com.abcr.seal-broker",
                                socket_probe=lambda: False, **rig["paths"])


def _expire_inflight(broker, stage: str, work_id: str) -> None:
    """把 inflight 信封的时间戳改旧,模拟 drain 硬崩溃后的租约过期。"""
    path = broker.spool._dir(stage, "inflight") / f"{work_id}.json"
    envelope = json.loads(path.read_text())
    envelope["created_at"] = "2020-01-01T00:00:00+00:00"
    envelope.pop("heartbeat_at", None)
    os.chmod(path, 0o600)
    path.write_bytes(canonical_json(envelope) + b"\n")


def test_qualify_survives_activator_crash_fence_bump(tmp_path, short_socket_dir, capsys):
    """P1 回归:activator 崩溃 → 租约恢复抬升 fence → 仍收敛 ACTIVE,
    且遗留的 canary 结果被清理 ack(否则稳态 reconciler 会用旧 fence 永久冲突)。"""
    rig = make_rig(tmp_path)
    socket_path = short_socket_dir / "b.sock"
    broker = MiniBroker(socket_path, tmp_path / "spool")
    broker.start()
    try:
        QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
        capsys.readouterr()
        broker.drain_stage("canary", _make_canary_handler("PASS"))
        QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))  # 入队 activate
        capsys.readouterr()
        # activator 认领后硬崩溃(不提交结果),租约过期 → fence 抬升
        claim = broker.spool.claim("activate", MISSION_ID)
        assert claim is not None and claim.fencing_token == 1
        _expire_inflight(broker, "activate", MISSION_ID)
        requeued, quarantined = broker.spool.recover_expired(
            "activate", lease_seconds=10, max_attempts=5)
        assert (requeued, quarantined) == (1, 0)
        # 重跑:入队会撞 fence 分歧 → 必须报 PENDING 而非终局 rc78
        rc = QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
        out = json.loads(capsys.readouterr().out.strip())
        assert rc == QUALIFY.PENDING_RC and out["awaiting_stage"] == "activate"
        # 重新 drain(fence 已是 2)→ 收敛 ACTIVE
        broker.drain_stage("activate", _make_activate_handler(rig))
        rc = QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
        assert rc == 0
        # 关键断言:canary 与 activate 的结果都已被清理 ack(不再对 reconciler 可见)
        acked_stages = {item["stage"] for item in broker.acked}
        assert acked_stages == {"canary", "activate"}
        for stage in ("canary", "activate"):
            assert (broker.spool._dir(stage, "acks") / f"{MISSION_ID}.json").exists()
    finally:
        broker.stop()


def test_qualify_short_circuit_cleans_leftover_results(tmp_path, short_socket_dir, capsys):
    """幂等短路路径也必须清理遗留可见结果(P1 的另一半)。"""
    rig = make_rig(tmp_path)
    socket_path = short_socket_dir / "b.sock"
    broker = MiniBroker(socket_path, tmp_path / "spool")
    broker.start()
    try:
        QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
        capsys.readouterr()
        broker.drain_stage("canary", _make_canary_handler("PASS"))
        # 外部(例如另一次运行)已经完成激活:直接写好 active.json
        write_activation_state(rig, sha256(b"external-canary"))
        rc = QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
        assert rc == 0
        assert (broker.spool._dir("canary", "acks") / f"{MISSION_ID}.json").exists()
    finally:
        broker.stop()


class RejectingBroker(MiniBroker):
    """在 work_enqueue 上抛出指定 SpoolError,复现 broker 的永久性拒绝。"""

    def __init__(self, socket_path, spool_root, reason: str):
        super().__init__(socket_path, spool_root)
        self.reason = reason

    def _respond(self, operation, arguments):
        if operation == "work_enqueue":
            self.enqueued.append(arguments)
            raise SpoolError(self.reason)
        return super()._respond(operation, arguments)


def test_qualify_surfaces_enqueue_rejection_code_not_silent_loop(
        tmp_path, short_socket_dir, capsys):
    """入队被拒时必须把 broker 原始错误码带出来,而不是静默降级成不可区分的 PENDING。"""
    rig = make_rig(tmp_path)
    socket_path = short_socket_dir / "b.sock"
    broker = RejectingBroker(socket_path, tmp_path / "spool", "conflicting replay")
    broker.start()
    try:
        rc = QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
        out = json.loads(capsys.readouterr().out.strip())
    finally:
        broker.stop()
    assert rc == QUALIFY.PENDING_RC
    assert out["awaiting_stage"] == "canary"
    assert out["enqueue_conflict"] == "SpoolError"   # 原样带出,供运维判读


def test_qualify_active_readback_survives_missing_verification_receipt(
        tmp_path, short_socket_dir, capsys):
    """ACTIVE 只凭磁盘事实:收据被裁剪后重跑仍须 rc0,只是 cleanup_incomplete。"""
    rig = make_rig(tmp_path)
    write_activation_state(rig, sha256(b"already-active"))
    (rig.receipt_root / f"{rig.ver_receipt_id}.json").unlink()
    socket_path = short_socket_dir / "b.sock"
    broker = MiniBroker(socket_path, tmp_path / "spool")
    broker.start()
    try:
        rc = QUALIFY.qualify(rig.authority_id, 1, **qualify_kwargs(rig, socket_path))
        out = json.loads(capsys.readouterr().out.strip())
    finally:
        broker.stop()
    assert rc == 0 and out["activation_state"] == "ACTIVE"
    assert out["cleanup_incomplete"] is True         # 清理未达成,但如实上报


def test_qualify_reports_cleanup_incomplete_when_broker_unreachable(tmp_path, capsys):
    rig = make_rig(tmp_path)
    write_activation_state(rig, sha256(b"active-no-broker"))
    rc = QUALIFY.qualify(rig.authority_id, 1,
                         **qualify_kwargs(rig, tmp_path / "nonexistent.sock"))
    out = json.loads(capsys.readouterr().out.strip())
    assert rc == 0 and out["cleanup_incomplete"] is True


def test_cleanup_error_is_absent_on_a_clean_active_result(tmp_path, short_socket_dir, capsys):
    rig = make_rig(tmp_path)
    socket_path = short_socket_dir / "b.sock"
    broker = MiniBroker(socket_path, tmp_path / "spool")
    broker.start()
    try:
        outputs, rcs = _run_ceremony(rig, broker, socket_path, capsys)
    finally:
        broker.stop()
    assert rcs[-1] == 0
    final = outputs[-1][1]
    assert final["cleanup_incomplete"] is False
    assert "cleanup_error" not in final       # 干净路径不得出现该字段


def test_cleanup_error_names_a_documented_code(tmp_path, short_socket_dir, capsys):
    """收据被裁剪 → genesis_verification_missing;不得吐出裸异常类名。"""
    rig = make_rig(tmp_path)
    write_activation_state(rig, sha256(b"already-active"))
    (rig.receipt_root / f"{rig.ver_receipt_id}.json").unlink()
    socket_path = short_socket_dir / "b.sock"
    broker = MiniBroker(socket_path, tmp_path / "spool")
    broker.start()
    try:
        rc = QUALIFY.qualify(rig.authority_id, 5, **qualify_kwargs(rig, socket_path))
        out = json.loads(capsys.readouterr().out.strip())
    finally:
        broker.stop()
    assert rc == 0 and out["cleanup_incomplete"] is True
    assert out["cleanup_error"] == "genesis_verification_missing"


def test_cleanup_error_reports_queue_failure_when_broker_unreachable(tmp_path, capsys):
    rig = make_rig(tmp_path)
    write_activation_state(rig, sha256(b"active-no-broker"))
    rc = QUALIFY.qualify(rig.authority_id, 5,
                         **qualify_kwargs(rig, tmp_path / "nonexistent.sock"))
    out = json.loads(capsys.readouterr().out.strip())
    assert rc == 0 and out["cleanup_error"] == "queue_cleanup_failed"
