"""Genesis canary probe: real, read-only semantic check of the sealed release.

canary-controller 以冻结 argv 运行本探针(sealed `env/bin/python -I -B` + 本文件),
stdin 一行 canonical JSON `{"expected_version","release_id"}`,stdout 一行
`{"observed_version","semantic_ok","reason"}`,退出码 0。非零退出码由上游记为
`probe_process_failed`。本探针没有 verdict 权力之外的任何副作用:不写任何文件、
不碰网络。

它回答的是一个**有限且明确**的问题:请求指名的那个 release 的 manifest 是否
canonical、其 release_id 是否与自身 core 摘要自洽、是否恰好声明 12 个服务载荷。
它**不**重算整棵树的 hash,也**不**执行被检 release 的任何字节——全树完整性由
canary 阶段之前的 `resolve_sealed_tree`(封印树重扫比对收据)以及 activation 时
broker 的再复验负责,本探针不重复那一层。

替换掉安装器旧的 `/usr/bin/false` 显式失败占位;探针本体被封印在 release 内,
因此其字节被 release tree hash 与 canary 阶段的全树复验覆盖。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MAX_REQUEST_BYTES = 64 * 1024
RELEASE_ROOT = Path("/Users/superagent/.abcr/releases")
RELEASE_ID = re.compile(r"^REL-[0-9a-f]{64}$")
MANIFEST_CORE = ("tree_hash", "runtime_digest", "lock_hash",
                 "service_config_hash", "verification_hash")


def _emit(observed: str | None, ok: bool, reason: str) -> int:
    sys.stdout.write(json.dumps(
        {"observed_version": observed, "semantic_ok": bool(ok), "reason": reason[:256]},
        ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0


def _strict(raw: bytes) -> dict:
    def unique(pairs: list) -> dict:
        out: dict = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate key")
            out[key] = value
        return out

    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    if not isinstance(value, dict):
        raise ValueError("request is not an object")
    return value


def main() -> int:
    raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
    if not raw or len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
        return _emit(None, False, "request_framing_invalid")
    if sys.stdin.buffer.read(1):
        return _emit(None, False, "request_framing_invalid")
    try:
        request = _strict(raw)
        if set(request) != {"expected_version", "release_id"}:
            return _emit(None, False, "request_shape_invalid")
        expected = request["expected_version"]
        release_id = request["release_id"]
        if (not isinstance(expected, str) or not isinstance(release_id, str)
                or RELEASE_ID.fullmatch(release_id) is None or expected != release_id):
            return _emit(None, False, "request_identity_invalid")

        # 冻结运行时可导入性:canonical 原语必须来自本封印环境。
        from abcr.control.contracts import canonical_json, sha256

        # 校验**请求指名的那个 release**,而不是探针自身所在的目录。自证路径的写法
        # 在 genesis 时恰好正确,却让任何升级的 canary 结构性必败(探针属于旧 release,
        # 请求携带新 release_id,身份永不相等)。release_id 已由正则钉死为
        # REL-<64hex>,拼接到固定根下不存在穿越风险。
        release_root = RELEASE_ROOT / release_id
        if release_root.is_symlink() or not release_root.is_dir():
            return _emit(None, False, "release_directory_unavailable")
        manifest_path = release_root / "release-manifest.json"
        manifest_raw = manifest_path.read_bytes()
        manifest = _strict(manifest_raw)
        if canonical_json(manifest) + b"\n" != manifest_raw:
            return _emit(None, False, "release_manifest_noncanonical")
        observed = manifest.get("release_id")
        if not isinstance(observed, str) or observed != release_id:
            return _emit(None, False, "release_manifest_identity_mismatch")
        core = {field: manifest.get(field) for field in MANIFEST_CORE}
        if any(not isinstance(value, str) for value in core.values()):
            return _emit(observed, False, "release_manifest_core_invalid")
        if observed != "REL-" + sha256(core):
            return _emit(observed, False, "release_id_binding_mismatch")
        payloads = manifest.get("service_payloads")
        if not isinstance(payloads, dict) or len(payloads) != 12:
            return _emit(observed, False, "release_service_payloads_invalid")
        return _emit(observed, True, "sealed_release_semantics_ok")
    except Exception as exc:  # fail-closed:任何异常都是明确的 FAIL,不抛出
        return _emit(None, False, f"probe_error:{type(exc).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
