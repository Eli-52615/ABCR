"""Genesis probation qualification: drive the first release activation fail-closed.

首次激活是一个**多身份、单步推进**的仪式,因为 launcher 路由的 canary/activator
服务在 active.json 存在前无法启动(abcr-launch.resolve_active 硬性要求它),而
active.json 只能由激活动作写出。因此首次激活必须绕开 launchd,由运维按固定顺序
交错运行本协调器(abcr-operator)与两个服务的直接 ``-m … --once`` drain
(abcr-canary / abcr-activator)。

两个互斥模式(都不需要 root):

1. ``--seal-genesis-verification AUTHORITY_ID --attestation PATH``(abcr-verifier)
   把外部 verifier 的 PASS attestation 封为 activation 必需的 `seal_verification`
   工件(唯一写动作是在 abcr-verifier 自己的 0700 staging 目录里落一份 canonical
   JSON,再交 broker 封印)。相同 attestation 字节 → 内容幂等;若已存在同 authority
   但不同对象的 verification 收据,本模式显式报错指向 abort,不制造发现歧义。

2. ``--qualify AUTHORITY_ID [--timeout-seconds N]``(abcr-operator)
   逐项自证 authority/receipt/封印树后**单步推进**:
   - active.json 已就位且匹配 → 打印 ACTIVE(rc 0);
   - canary/activate 结果尚未产出 → 幂等入队后打印 PENDING(rc 75),
     运维随即运行对应服务的 ``--once`` drain,再重跑本命令;入队被 broker 拒绝时
     PENDING 会带 ``enqueue_conflict``,而它**几乎总是字符串 ``SpoolError``**:
     spool 的全部拒绝原因(良性 fence 抬升、异 payload、信封被篡改、多状态)都塌成
     这一个串(SpoolError 不是 ContractError,broker 兜底成类名),而 producer 无权
     list ready/inflight,做不到更细的分辨。注意它**不可能**是
     ``broker_peer_forbidden``:协调器的第一个 broker 调用是同为 producer op 的
     ``work_result_list``,ACL 问题会先在那里以普通 rc78 暴露。只有 peer uid 映射到
     别的 producer 名这种配置错误才会在此得到 ``work_producer_spoofed``。故:见
     ``SpoolError`` 先 drain 再重跑,同码重现则按 runbook §7 由 root 侧直接检查
     work spool 判因,**不得继续重试**;
   - 任一绑定/晋级校验失败或 canary FAIL → 打印错误(rc 78),终局。
   **关键不变量:在 active.json 确认之前绝不 ack 任何结果**——canary 结果因此始终
   可见,驱动 activate 的幂等重入;收尾 ack 仅在成功后做,且其成败经
   ``cleanup_incomplete`` 如实上报(为 true 时遗留结果可能让稳态 reconciler 冲突,
   需人工排空),不影响 ACTIVE 判定本身。

判定唯一以磁盘事实(root 落下的 active.json + selector 晋级的 bootstrap 指针)为准,
绝不采信任何进程自报;verification 收据的发现只服务于清理,不是 ACTIVE 的前置。
canary FAIL 对本 mission_id 是终局(结果封存后 work_id 一次性),恢复只能走
`--abort-probation` 重走 genesis。

与仓内其他 ceremony 入口一致,函数通过关键字参数注入路径/身份(生产默认值即
部署常量);这不扩大权力面——调用方仍受 broker peer-uid ACL 与文件属主校验
约束,注入只服务于测试。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pwd
import re
import stat
import sys
import time
from pathlib import Path
from typing import Any

from abcr.control.contracts import ContractError, canonical_json, sha256
from abcr.control.mission_pipeline import artifact_object_id, validate_broker_ref, seal_json_artifact
from abcr.control.queue_runtime import WorkBrokerClient
from abcr.control.work_spool import WORK_ID
from abcr.control.worktree import scan_tree, tree_hash

HEX64 = re.compile(r"^[0-9a-f]{64}$")
RELEASE_ID_RE = re.compile(r"^REL-[0-9a-f]{64}$")
PENDING_RC = 75
BROKER_SOCKET = Path("/var/run/abcr-seal-broker.sock")
RELEASE_ROOT = Path("/Users/superagent/.abcr/releases")
ACTIVE_PATH = Path("/Users/superagent/.abcr/active.json")
COMPONENT_ROOT = Path("/Library/Application Support/ABCR-Bootstrap/components")
VERIFICATION_STAGING = Path("/Library/Application Support/ABCR-Bootstrap/staging/seal_verification")
NONCE_PREFIX = "genesis-verification:"
ATTESTATION_FIELDS = frozenset({
    "mission_id", "fencing_token", "base_tree_hash", "candidate_tree_hash",
    "profile_hash", "oracle_set_hash", "changed_paths", "verdict",
    "verified_at", "attestation_hash", "isolation", "sealed"})


class QualifyBlocked(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _genesis_constants() -> Any:
    """从同封印树的 genesis 脚本加载冻结常量,避免第二份可漂移的复制品。"""
    path = Path(__file__).resolve().parent / "bootstrap_abcr_genesis.py"
    spec = importlib.util.spec_from_file_location("abcr_genesis_constants", path)
    if spec is None or spec.loader is None:
        raise QualifyBlocked("genesis_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _strict(raw: bytes, *, error: str) -> dict[str, Any]:
    def unique(pairs: list) -> dict:
        out: dict = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate key")
            out[key] = value
        return out
    try:
        value = json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    except ValueError as exc:
        raise QualifyBlocked(error) from exc
    if not isinstance(value, dict):
        raise QualifyBlocked(error)
    return value


def _require_file(path: Path, *, uid: int, gid: int | None, mode: int,
                  max_bytes: int, error: str) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise QualifyBlocked(error) from exc
    if (path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != uid or (gid is not None and info.st_gid != gid)
            or stat.S_IMODE(info.st_mode) != mode or info.st_size > max_bytes):
        raise QualifyBlocked(error)
    return path.read_bytes()


def _load_authority(genesis: Any, authority_id: str, *, authority_path: Path,
                    owner_uid: int) -> dict[str, Any]:
    raw = _require_file(authority_path, uid=owner_uid, gid=None, mode=0o444,
                        max_bytes=256 * 1024, error="genesis_authority_unavailable")
    value = _strict(raw, error="genesis_authority_invalid")
    if raw != canonical_json(value) + b"\n":
        raise QualifyBlocked("genesis_authority_noncanonical")
    if set(value) != set(genesis.AUTHORITY_FIELDS):
        raise QualifyBlocked("genesis_authority_shape_invalid")
    core = {key: value[key] for key in value if key != "authority_id"}
    if (value["authority_id"] != authority_id or sha256(core) != authority_id
            or value.get("ceremony") != genesis.CEREMONY
            or value.get("authority_sha256") != genesis.AUTHORITY_SHA
            or value.get("policy_sha256") != genesis.POLICY_SHA
            or value.get("human_approved") is not True):
        raise QualifyBlocked("genesis_authority_binding_mismatch")
    if RELEASE_ID_RE.fullmatch(str(value.get("release_id"))) is None:
        raise QualifyBlocked("genesis_authority_release_invalid")
    return value


def _release_read_gid() -> int:
    import grp
    try:
        return grp.getgrnam("abcr-release-read").gr_gid
    except KeyError as exc:
        raise QualifyBlocked("genesis_accounts_missing") from exc


def _receipt_core_ok(genesis: Any, value: dict[str, Any], receipt_id: str) -> bool:
    if set(value) != set(genesis.RECEIPT_FIELDS):
        return False
    core = {"operation": value["operation"], "nonce": value["nonce"],
            "tree_hash": value["tree_hash"], "object_id": value["object_id"]}
    return value["receipt_id"] == receipt_id and sha256(core) == receipt_id


def _load_receipt(genesis: Any, receipt_root: Path, receipt_id: str, *,
                  owner_uid: int, group_gid: int | None, error: str) -> dict[str, Any]:
    path = receipt_root / f"{receipt_id}.json"
    raw = _require_file(path, uid=owner_uid, gid=group_gid, mode=0o440,
                        max_bytes=64 * 1024, error=error)
    value = _strict(raw, error=error)
    if "genesis_pending" in value:
        raise QualifyBlocked("genesis_incomplete")
    if not _receipt_core_ok(genesis, value, receipt_id):
        raise QualifyBlocked(error)
    return value


def _load_manifest(sealed: Path, release_id: str, *, owner_uid: int,
                   group_gid: int | None) -> dict[str, Any]:
    raw = _require_file(sealed / "release-manifest.json", uid=owner_uid, gid=group_gid,
                        mode=0o440, max_bytes=64 * 1024 * 1024,
                        error="genesis_release_manifest_unavailable")
    manifest = _strict(raw, error="genesis_release_manifest_invalid")
    if canonical_json(manifest) + b"\n" != raw:
        raise QualifyBlocked("genesis_release_manifest_noncanonical")
    if (manifest.get("release_id") != release_id
            or HEX64.fullmatch(str(manifest.get("verification_hash"))) is None
            or HEX64.fullmatch(str(manifest.get("tree_hash"))) is None):
        raise QualifyBlocked("genesis_release_manifest_identity_mismatch")
    return manifest


def _decode_attestation(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    document = _strict(raw, error="genesis_attestation_invalid")
    value = document.get("attestation") if isinstance(document.get("attestation"), dict) else document
    if not isinstance(value, dict) or set(value) != ATTESTATION_FIELDS:
        raise QualifyBlocked("genesis_attestation_shape_invalid")
    core = {key: value[key] for key in value if key not in ("attestation_hash", "sealed")}
    if sha256(core) != value["attestation_hash"] or value.get("verdict") != "PASS":
        raise QualifyBlocked("genesis_attestation_binding_mismatch")
    return value


def _require_identity(expected_user: str | None) -> None:
    if expected_user is None:
        return
    if sys.platform != "darwin" or pwd.getpwuid(os.geteuid()).pw_name != expected_user:
        raise QualifyBlocked("genesis_qualify_identity")


def seal_genesis_verification(authority_id: str, attestation_path: Path, *,
                              genesis: Any | None = None,
                              broker_socket: Path = BROKER_SOCKET,
                              release_root: Path = RELEASE_ROOT,
                              staging_root: Path = VERIFICATION_STAGING,
                              authority_path: Path | None = None,
                              receipt_root: Path | None = None,
                              expected_user: str | None = "abcr-verifier",
                              owner_uid: int = 0,
                              release_gid: int | None = None,
                              stream=None) -> int:
    _require_identity(expected_user)
    genesis = genesis or _genesis_constants()
    if release_gid is None and expected_user is not None:
        release_gid = _release_read_gid()
    receipt_root = receipt_root or Path(genesis.RECEIPT_ROOT)
    authority = _load_authority(genesis, authority_id,
                                authority_path=authority_path or Path(genesis.AUTHORITY_PATH),
                                owner_uid=owner_uid)
    release_id = authority["release_id"]
    sealed = release_root / release_id
    manifest = _load_manifest(sealed, release_id, owner_uid=owner_uid,
                              group_gid=release_gid)
    attestation = _decode_attestation(Path(attestation_path))
    if (attestation["attestation_hash"] != manifest["verification_hash"]
            or attestation["candidate_tree_hash"] != manifest["tree_hash"]):
        raise QualifyBlocked("genesis_attestation_release_mismatch")
    mission_id = attestation["mission_id"]
    if not isinstance(mission_id, str) or WORK_ID.fullmatch(mission_id) is None:
        raise QualifyBlocked("genesis_mission_id_unusable")
    document = {
        "schema_version": 1, "kind": "verification", "attestation": attestation,
        "pipeline_context": {
            "candidate_id": mission_id,
            "base_tree_hash": attestation["base_tree_hash"],
            "changed_paths": attestation["changed_paths"],
            "declared_risk": "genesis", "old_release": None,
            "expected_version": release_id},
        "test_result_ref": None, "candidate_ref": None}
    object_id = artifact_object_id("VER", document)
    nonce = NONCE_PREFIX + authority_id + ":" + mission_id
    # 防发现歧义:若已存在同 authority 前缀但不同对象的 verification 收据,
    # 停在 seal 阶段并显式指向 abort,而不是让 --qualify 之后永久 ambiguous。
    existing = _scan_verification_receipts(
        genesis, receipt_root, authority_id,
        owner_uid=owner_uid, group_gid=release_gid)
    for receipt in existing:
        if receipt["object_id"] != object_id:
            raise QualifyBlocked("genesis_verification_conflict")
    client = WorkBrokerClient(broker_socket)
    reference = seal_json_artifact(
        client, operation="seal_verification", staging_root=staging_root,
        object_id=object_id, filename="verification.json", document=document,
        nonce=nonce)
    out = stream or sys.stdout
    out.write(canonical_json({"ok": True, "verification_ref": reference,
                              "mission_id": mission_id}).decode("utf-8") + "\n")
    return 0


def _scan_verification_receipts(genesis: Any, receipt_root: Path, authority_id: str, *,
                                owner_uid: int, group_gid: int | None
                                ) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    prefix = NONCE_PREFIX + authority_id + ":"
    if receipt_root.is_symlink() or not receipt_root.is_dir():
        return matches
    for path in sorted(receipt_root.iterdir()):
        if path.suffix != ".json" or HEX64.fullmatch(path.stem) is None:
            continue
        raw = _require_file(path, uid=owner_uid, gid=group_gid, mode=0o440,
                            max_bytes=64 * 1024, error="genesis_receipt_unreadable")
        value = _strict(raw, error="genesis_receipt_unreadable")
        if value.get("operation") == "seal_verification" and str(value.get("nonce", "")).startswith(prefix):
            if not _receipt_core_ok(genesis, value, path.stem):
                raise QualifyBlocked("genesis_receipt_unreadable")
            matches.append(value)
    return matches


def _discover_verification(genesis: Any, receipt_root: Path, authority_id: str, *,
                           owner_uid: int, group_gid: int | None
                           ) -> tuple[dict[str, str], str]:
    matches = _scan_verification_receipts(genesis, receipt_root, authority_id,
                                          owner_uid=owner_uid, group_gid=group_gid)
    if not matches:
        raise QualifyBlocked("genesis_verification_missing")
    if len(matches) > 1:
        raise QualifyBlocked("genesis_verification_ambiguous")
    receipt = matches[0]
    mission_id = str(receipt["nonce"]).rsplit(":", 1)[1]
    if WORK_ID.fullmatch(mission_id) is None:
        raise QualifyBlocked("genesis_mission_id_unusable")
    ref = validate_broker_ref(
        {"operation": "seal_verification", "receipt_id": receipt["receipt_id"],
         "object_id": receipt["object_id"], "sealed_tree_hash": receipt["sealed_tree_hash"]},
        expected_operation="seal_verification")
    return ref, mission_id


def _probe_gate(sealed: Path) -> None:
    installer = sealed / "scripts" / "install_abcr_runtime.py"
    probe = sealed / "scripts" / "abcr_genesis_canary_probe.py"
    raw = installer.read_bytes()
    if b"/usr/bin/false" in raw or b"abcr_genesis_canary_probe.py" not in raw:
        raise QualifyBlocked("genesis_canary_probe_unqualified")
    if probe.is_symlink() or not probe.is_file():
        raise QualifyBlocked("genesis_canary_probe_unqualified")


def _read_active(active_path: Path, *, expected_release: str, expected_receipt: str,
                 expected_verification: str, owner_uid: int) -> dict[str, Any] | None:
    if not active_path.exists() and not active_path.is_symlink():
        return None
    raw = _require_file(active_path, uid=owner_uid, gid=None, mode=0o444,
                        max_bytes=64 * 1024, error="genesis_qualify_active_conflict")
    record = _strict(raw, error="genesis_qualify_active_conflict")
    if (record.get("release_id") != expected_release
            or record.get("previous_release") is not None
            or record.get("release_receipt_id") != expected_receipt
            or record.get("verification_hash") != expected_verification
            or HEX64.fullmatch(str(record.get("canary_hash"))) is None):
        raise QualifyBlocked("genesis_qualify_active_conflict")
    return record


def _pointer(path: Path, *, owner_uid: int) -> dict[str, Any]:
    raw = _require_file(path, uid=owner_uid, gid=None, mode=0o444, max_bytes=64 * 1024,
                        error="genesis_probation_pointer_unreadable")
    return _strict(raw, error="genesis_probation_pointer_unreadable")


def _check_promotions(component_root: Path, *, owner_uid: int) -> None:
    broker_active = _pointer(component_root / "seal-broker" / "active-slot.json",
                             owner_uid=owner_uid)
    broker_lkg = _pointer(component_root / "seal-broker" / "last-known-good.json",
                          owner_uid=owner_uid)
    # 不得硬编码 slot-b/generation 2:那只是"首次安装恰好写出的一代",安装器一旦
    # 被再跑一次就会变成 slot-a/generation 3,使本闸永久不可满足、genesis 被楔死。
    # 语义上要求的其实是:已晋级(probation 为 false),且 active 与 last-known-good
    # 指向同一 slot/generation —— 即这一代已经被 selector 完整接受。
    if (broker_active.get("probation") is not False
            or broker_lkg.get("probation") is not False
            or broker_active.get("slot") != broker_lkg.get("slot")
            or broker_active.get("generation") != broker_lkg.get("generation")
            or not isinstance(broker_active.get("generation"), int)):
        raise QualifyBlocked("genesis_probation_not_promoted")
    launcher_active = _pointer(component_root / "launcher" / "active-slot.json",
                               owner_uid=owner_uid)
    if launcher_active.get("probation") is not False:
        raise QualifyBlocked("genesis_probation_not_promoted")


def _poll_result(client: WorkBrokerClient, stage: str, work_id: str) -> dict[str, Any] | None:
    catalog = client.request("work_result_list", {"stage": stage, "include_fence": True})
    if not isinstance(catalog, list):
        raise QualifyBlocked("broker_response_invalid")
    entry = next((item for item in catalog
                  if isinstance(item, dict) and item.get("work_id") == work_id), None)
    if entry is None:
        return None
    if type(entry.get("attempt")) is not int or type(entry.get("fencing_token")) is not int:
        raise QualifyBlocked("broker_response_invalid")
    envelope = client.request("work_result_read", {
        "stage": stage, "work_id": work_id,
        "attempt": entry["attempt"], "fencing_token": entry["fencing_token"]})
    if not isinstance(envelope, dict) or not isinstance(envelope.get("result"), dict):
        raise QualifyBlocked("broker_response_invalid")
    return envelope


def _enqueue(client: WorkBrokerClient, stage: str, work_id: str, *, attempt: int,
             fencing_token: int, payload: dict[str, Any]) -> str | None:
    """入队;成功返回 None,被拒返回 broker 的**原始错误码**。

    spool.enqueue 内容幂等:同 work_id + 完全相同 payload + 相同 fence 直接返回既有
    信封。被拒的成因客户端**无法区分**,至少包括:
      * 同 payload 但 fence 已被 lease 恢复抬升 —— 崩溃重跑后的良性交错,重 drain 即解;
      * 同 work_id 不同 payload(conflicting replay)、ready 信封被篡改(nlink≠1)、
        work identity 同时存在于多个状态、producer/ACL 不符 —— 这些**不会**因为再
        drain 一次就消失,是完整性告警。
    因此:既不静默吞掉(会把告警变成静默死循环),也不直接判终局(会把良性交错误
    升级成销毁式 abort)。做法是把错误码原样带出,先复查一次结果(并发 drain 可能
    刚完成),仍无结果则让调用方报 PENDING 并附带该码。

    **诚实边界**:``WorkSpool.enqueue`` 的全部拒绝原因都以 ``SpoolError`` 抛出,而
    它不是 ``ContractError``,broker 一律映射成字符串 ``"SpoolError"``(见
    seal_broker 的 dispatch 兜底)。因此实际上本码几乎总是这一个串,只是"broker
    拒绝了入队"这一个比特,不能区分良性 fence 抬升与完整性告警。调用点之前已经
    成功做过 ``work_result_list``(同为 producer op),所以 ACL 类拒绝不会走到这里;
    剩下唯一可能的非 SpoolError 取值是 producer 名映射错配导致的
    ``work_producer_spoofed``。runbook §7 据此规定处置。
    """
    try:
        client.request("work_enqueue", {
            "stage": stage, "work_id": work_id, "attempt": attempt,
            "fencing_token": fencing_token, "producer": "abcr-operator",
            "payload": payload})
        return None
    except ContractError as exc:
        if _poll_result(client, stage, work_id) is not None:
            return None
        return exc.code or "work_enqueue_rejected"


def _cleanup_acks(broker_socket: Path, mission_id: str) -> bool:
    """ACTIVE 确认后清空本 mission 的可见结果;返回是否全部清理成功。

    必须在**每一条**通往 ACTIVE 的路径上执行(含幂等短路),否则遗留的可见 canary
    结果会让稳态 operator-reconciler 反复用旧 fence 重放 activate;若 activate 曾因
    崩溃被 lease 恢复而 fence 抬升,重放会永久 `conflicting replay`,饿死整个
    activate 阶段。

    清理失败不推翻已成立的 ACTIVE(判定只认磁盘事实),但**必须让运维看见**——
    返回值会作为 `cleanup_incomplete` 出现在成功输出里,否则本函数要防的问题会
    在一次瞬时失败后静默存活。
    """
    client = WorkBrokerClient(broker_socket)  # 构造不连接,连接失败在下面各调用处显现
    complete = True
    for stage in ("canary", "activate"):
        try:
            envelope = _poll_result(client, stage, mission_id)
        except Exception:
            complete = False
            continue
        if envelope is not None and not _best_effort_ack(client, stage, envelope):
            complete = False
    return complete


def _cleanup_acks_discovered(broker_socket: Path, genesis: Any, receipt_root: Path,
                             authority_id: str, *, owner_uid: int,
                             group_gid: int | None) -> tuple[bool, str | None]:
    """短路路径的清理:返回 (是否完成, 未完成原因码)。

    ACTIVE 判定只凭 active.json 与 bootstrap 指针——把 verification 收据扫描当作
    ACTIVE 的前置,会让"已激活系统"在 receipt 目录被裁剪/轮转时报终局错误。但发现
    失败**不得被压成一个无信息的布尔**:收据完整性异常(如 mode/属主漂移)在本轮
    之前是终局告警,这里必须把原因码原样带出,由运维判读,而不是静默降级。
    """
    try:
        _ref, mission_id = _discover_verification(
            genesis, receipt_root, authority_id,
            owner_uid=owner_uid, group_gid=group_gid)
    except QualifyBlocked as exc:
        # QualifyBlocked 的码是本模块自有的封闭集合(genesis_* 家族),可直接上报。
        return False, exc.code
    except Exception:
        # 其余异常的类名不属于任何已文档化的取值集合,归一到一个固定码,避免
        # ACTIVE 记录里出现 runbook 没有定义的字符串。
        return False, "verification_discovery_failed"
    if _cleanup_acks(broker_socket, mission_id):
        return True, None
    return False, "queue_cleanup_failed"


def _best_effort_ack(client: WorkBrokerClient, stage: str, envelope: dict[str, Any]) -> bool:
    """收尾清理 ack;返回是否成功。

    active.json 已确认后才调用,失败不改变 ACTIVE 判定,但会经 `cleanup_incomplete`
    上报。与 operator-reconciler 并发时对方可能先 ack(留下 FileNotFoundError),
    那种情况下结果同样已不可见,视为清理达成。
    """
    try:
        client.request("work_ack", {
            "stage": stage, "work_id": envelope["work_id"],
            "attempt": envelope["attempt"], "fencing_token": envelope["fencing_token"],
            "result_hash": envelope["result_hash"]})
        return True
    except ContractError as exc:
        # 对方已 ack:inflight 信封已归档,结果亦已从 work_result_list 隐去。
        return exc.code == "FileNotFoundError"
    except Exception:
        return False


def _stage_outcome(envelope: dict[str, Any], *, failure_code: str) -> dict[str, Any]:
    result = envelope["result"]
    if result.get("ok") is not True:
        code = result.get("error_code")
        raise QualifyBlocked(code if isinstance(code, str) and code else failure_code)
    inner = result.get("result")
    if not isinstance(inner, dict):
        raise QualifyBlocked("broker_response_invalid")
    return inner


def _wait_result(client: WorkBrokerClient, stage: str, work_id: str, *,
                 deadline: float, poll_seconds: float) -> dict[str, Any] | None:
    """有界等待:结果出现即返回,否则到点返回 None(交由调用方报 PENDING)。

    单步语义:若运维采用后台并发 drain,短等待即命中;若采用顺序 drain,返回
    None → 打印 PENDING → 运维手动 drain 后重跑。两种编排都收敛。
    """
    while True:
        envelope = _poll_result(client, stage, work_id)
        if envelope is not None:
            return envelope
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll_seconds)


def qualify(authority_id: str, timeout_seconds: int, *,
            genesis: Any | None = None,
            broker_socket: Path = BROKER_SOCKET,
            release_root: Path = RELEASE_ROOT,
            active_path: Path = ACTIVE_PATH,
            component_root: Path = COMPONENT_ROOT,
            authority_path: Path | None = None,
            receipt_root: Path | None = None,
            expected_user: str | None = "abcr-operator",
            owner_uid: int = 0,
            release_gid: int | None = None,
            poll_seconds: float = 2.0,
            stream=None) -> int:
    _require_identity(expected_user)
    genesis = genesis or _genesis_constants()
    if release_gid is None:
        release_gid = _release_read_gid()
    authority_path = authority_path or Path(genesis.AUTHORITY_PATH)
    receipt_root = receipt_root or Path(genesis.RECEIPT_ROOT)
    deadline = time.monotonic() + timeout_seconds

    # P0 authority + genesis receipt + 封印树自证
    authority = _load_authority(genesis, authority_id, authority_path=authority_path,
                                owner_uid=owner_uid)
    release_id = authority["release_id"]
    expected_receipt_id = authority["expected_receipt_id"]
    receipt = _load_receipt(genesis, receipt_root, expected_receipt_id,
                            owner_uid=owner_uid, group_gid=release_gid,
                            error="genesis_receipt_unreadable")
    sealed = release_root / release_id
    if (receipt["operation"] != "seal_release" or receipt["object_id"] != release_id
            or receipt["nonce"] != authority["broker_seal_nonce"]
            or receipt["tree_hash"] != authority["source_tree_hash"]
            or receipt["sealed_path"] != str(sealed)):
        raise QualifyBlocked("genesis_receipt_binding_mismatch")
    if tree_hash(scan_tree(sealed)) != receipt["sealed_tree_hash"]:
        raise QualifyBlocked("sealed_tree_drift")
    manifest = _load_manifest(sealed, release_id, owner_uid=owner_uid,
                              group_gid=release_gid)
    release_ref = validate_broker_ref(
        {"operation": "seal_release", "receipt_id": expected_receipt_id,
         "object_id": release_id, "sealed_tree_hash": receipt["sealed_tree_hash"]},
        expected_operation="seal_release")

    def emit_active(canary_hash: str, *, cleanup_complete: bool,
                    cleanup_error: str | None = None) -> int:
        out = stream or sys.stdout
        record = {"ok": True, "activation_state": "ACTIVE", "release_id": release_id,
                  "canary_hash": canary_hash, "live_pilot_qualified": False,
                  "autonomous_qualified": False,
                  "cleanup_incomplete": not cleanup_complete}
        if cleanup_error is not None:
            record["cleanup_error"] = cleanup_error
        out.write(canonical_json(record).decode("utf-8") + "\n")
        return 0

    def emit_pending(next_stage: str, drain_identity: str,
                     conflict: str | None = None) -> int:
        out = stream or sys.stdout
        record = {"ok": True, "activation_state": "PENDING", "release_id": release_id,
                  "awaiting_stage": next_stage, "drain_identity": drain_identity}
        if conflict is not None:
            # 见 _enqueue 文档:spool 级原因塌成 "SpoolError",broker 级带真实码。
            record["enqueue_conflict"] = conflict
        out.write(canonical_json(record).decode("utf-8") + "\n")
        return PENDING_RC

    def confirm_active() -> dict[str, Any] | None:
        return _read_active(active_path, expected_release=release_id,
                            expected_receipt=expected_receipt_id,
                            expected_verification=manifest["verification_hash"],
                            owner_uid=owner_uid)

    # P1 幂等短路:ACTIVE 只凭磁盘事实(active.json + bootstrap 指针),清理是附带
    # 动作——mission_id 的发现放在清理内部做 best-effort,绝不成为 ACTIVE 的前置。
    active = confirm_active()
    if active is not None:
        _check_promotions(component_root, owner_uid=owner_uid)
        complete, reason = _cleanup_acks_discovered(
            broker_socket, genesis, receipt_root, authority_id,
            owner_uid=owner_uid, group_gid=release_gid)
        return emit_active(active["canary_hash"], cleanup_complete=complete,
                           cleanup_error=reason)

    # P2 发现 verification 工件与 mission_id
    verification_ref, mission_id = _discover_verification(
        genesis, receipt_root, authority_id, owner_uid=owner_uid, group_gid=release_gid)

    # P3 探针门:必须在第一次入队之前(canary FAIL 对该 mission_id 是终局)
    _probe_gate(sealed)

    client = WorkBrokerClient(broker_socket)

    # P4 canary:入队 → 等结果。**不 ack**——保持结果可见以驱动 activate 幂等重入。
    canary_env = _poll_result(client, "canary", mission_id)
    if canary_env is None:
        conflict = _enqueue(client, "canary", mission_id, attempt=1, fencing_token=1,
                            payload={"mission_id": mission_id, "release_ref": release_ref,
                                     "verification_ref": verification_ref,
                                     "expected_version": release_id, "old_release": None})
        if conflict is not None:
            return emit_pending("canary", "abcr-canary", conflict)
        canary_env = _wait_result(client, "canary", mission_id,
                                  deadline=deadline, poll_seconds=poll_seconds)
        if canary_env is None:
            return emit_pending("canary", "abcr-canary")
    canary = _stage_outcome(canary_env, failure_code="genesis_canary_failed")
    if canary.get("verdict") != "PASS" or canary.get("mission_id") != mission_id:
        raise QualifyBlocked("genesis_canary_failed")
    canary_ref = validate_broker_ref(canary.get("broker_ref"),
                                     expected_operation="seal_canary")

    # P5 activate:入队(承载 canary_ref,fence 继承 canary 结果)→ 等结果。
    # activate 入队发生在 canary ack 之前;canary 结果仍可见,崩溃重跑可重建。
    activate_env = _poll_result(client, "activate", mission_id)
    if activate_env is None:
        conflict = _enqueue(client, "activate", mission_id, attempt=canary_env["attempt"],
                            fencing_token=canary_env["fencing_token"],
                            payload={"canary_ref": canary_ref})
        if conflict is not None:
            return emit_pending("activate", "abcr-activator", conflict)
        activate_env = _wait_result(client, "activate", mission_id,
                                    deadline=deadline, poll_seconds=poll_seconds)
        if activate_env is None:
            return emit_pending("activate", "abcr-activator")
    record = _stage_outcome(activate_env, failure_code="genesis_activation_failed")
    if (record.get("release_id") != release_id
            or record.get("previous_release") is not None
            or record.get("release_receipt_id") != expected_receipt_id
            or record.get("verification_hash") != manifest["verification_hash"]
            or HEX64.fullmatch(str(record.get("canary_hash"))) is None):
        raise QualifyBlocked("genesis_activation_binding_mismatch")

    # P6 终局自证:一切以磁盘事实为准;确认后才做收尾清理 ack
    active = confirm_active()
    if active is None:
        raise QualifyBlocked("genesis_activation_not_observed")
    _check_promotions(component_root, owner_uid=owner_uid)
    complete = _cleanup_acks(broker_socket, mission_id)
    return emit_active(active["canary_hash"], cleanup_complete=complete,
                       cleanup_error=None if complete else "queue_cleanup_failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qualify-abcr-genesis-probation")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--qualify", metavar="AUTHORITY_ID")
    modes.add_argument("--seal-genesis-verification", metavar="AUTHORITY_ID")
    parser.add_argument("--attestation", type=Path)
    # 顺序仪式下协调器是"单步推进":入队后短等一下,没结果就报 PENDING 交给运维
    # drain。默认 300s 会让 B1/B3 无输出地阻塞 5 分钟,与 §7 的单步语义不符。
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        authority_id = args.qualify or args.seal_genesis_verification
        if HEX64.fullmatch(authority_id or "") is None:
            raise QualifyBlocked("genesis_authority_id_invalid")
        if args.seal_genesis_verification:
            if args.attestation is None:
                raise QualifyBlocked("genesis_attestation_required")
            return seal_genesis_verification(authority_id, args.attestation)
        if args.attestation is not None:
            raise QualifyBlocked("genesis_qualify_arguments_invalid")
        if not 5 <= args.timeout_seconds <= 3600:
            raise QualifyBlocked("genesis_timeout_invalid")
        return qualify(authority_id, args.timeout_seconds)
    except QualifyBlocked as exc:
        print(canonical_json({"ok": False, "error_code": exc.code}).decode("utf-8"),
              file=sys.stderr)
        return 78
    except ContractError as exc:
        print(canonical_json({"ok": False, "error_code": exc.code}).decode("utf-8"),
              file=sys.stderr)
        return 78
    except Exception as exc:  # fail-closed:未知异常同样只留代码,不落半成品
        print(canonical_json({"ok": False, "error_code": type(exc).__name__}).decode("utf-8"),
              file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
