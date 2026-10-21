#!/usr/bin/env python3
"""LIVE 工具:发现 owner 身份(open_id/tenant_key/chat_id/chat_type)。**不进默认回归**。

用法(需要网络 + staging 凭据;用 .venv312,lark_oapi 已装):
    PYTHONPATH=src .venv312/bin/python scripts/feishu_discover_owner.py

行为(防"首条 p2p 抢注":候选须人工核对,绝不自动生效):
- 从 ~/Library/Application Support/ABCR-Human-staging/feishu.env 读凭据
  (ABCR_FEISHU_APP_ID / ABCR_FEISHU_APP_SECRET;0600);
- 起飞书长连接;收到**第一条 p2p(一对一)消息**时,只写
  discovered-owner.candidate.json(0600)并打印身份四元组
  (open_id/tenant_key/chat_id/chat_type),同时提示:
  **请核对 open_id 是否本人,确认后手动改名为 discovered-owner.json 方可生效**;
- 之后继续监听:后续**不同 sender** 的 p2p 只把身份四元组追加进 candidate 文件的
  others 数组(只记身份,不记正文),供人工比对;同一 sender 的重复消息忽略;
- Ctrl-C 退出。

红线:
- **绝不自动落 discovered-owner.json**:任何抢先给应用发消息的人最多成为
  candidate,生效必须由人核对 open_id 后手动改名;
- **绝不把消息正文当命令**:本工具不读取、不打印、不解析 text,只取身份字段;
- **绝不记录 secret/token**:凭据只进内存交给 SDK,app_id 打印时打码;
  lark SDK 日志由 transport 路由到 staging 目录 lark-ws.log(0600,凭据打码);
- 非 p2p(群聊)消息只提示忽略,不提取身份(方案 §7.1:生产只接受一对一)。
"""
from __future__ import annotations

import json
import os
import stat
import sys
import threading
import uuid
import fcntl
from datetime import datetime, timezone
from pathlib import Path

# 脚本自带 src 引导,便于直接运行(与 PYTHONPATH=src 等价、幂等)
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from abcr.control.feishu_transport import FeishuTransport, load_credentials  # noqa: E402

STAGING_DIR = Path.home() / "Library" / "Application Support" / "ABCR-Human-staging"
ENV_PATH = STAGING_DIR / "feishu.env"
#: 候选文件:本工具唯一会写的产物。
CANDIDATE_PATH = STAGING_DIR / "discovered-owner.candidate.json"
#: 生效文件:**本工具绝不写它**,只在提示里指路(人工核对后手动改名)。
FINAL_PATH = STAGING_DIR / "discovered-owner.json"
LOCK_PATH = STAGING_DIR / ".discover-owner.lock"


def _mask(value: str) -> str:
    return value[:8] + "…" if len(value) > 8 else "…"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _secure_parent(path: Path) -> None:
    info = os.lstat(path.parent)
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise RuntimeError("owner discovery directory must be euid-owned and private")


def _write_0600(path: Path, payload: dict) -> None:
    """Atomic private write; never follows an attacker-supplied candidate symlink."""
    _secure_parent(path)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        if fd >= 0:
            os.close(fd)
        tmp.unlink(missing_ok=True)


def _read_existing_candidate(path: Path) -> dict | None:
    if not path.exists() and not path.is_symlink():
        return None
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600):
            raise RuntimeError("existing owner candidate is not a safe 0600 regular file")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            value = json.load(stream)
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(value, dict) or not isinstance(value.get("open_id"), str):
        raise RuntimeError("existing owner candidate is malformed")
    others = value.get("others")
    if not isinstance(others, list):
        raise RuntimeError("existing owner candidate has invalid others")
    return value


def main() -> int:
    STAGING_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    _secure_parent(CANDIDATE_PATH)
    if FINAL_PATH.exists() or FINAL_PATH.is_symlink():
        raise RuntimeError(
            f"owner identity already finalized at {FINAL_PATH}; refusing discovery overwrite")
    lock_fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    app_id, app_secret = load_credentials(str(ENV_PATH))
    print(f"[discover] 凭据已读取(app_id={_mask(app_id)};secret 不显示)")
    print("[discover] 建立飞书长连接…请用 owner 账号给应用发一条**私聊**消息。")

    state: dict = {"candidate": _read_existing_candidate(CANDIDATE_PATH)}
    state_lock = threading.Lock()
    if state["candidate"] is not None:
        print("[discover] 已载入现有 candidate；不会覆盖首个候选，只追加不同 sender 供比对。")

    def on_event(flat: dict) -> None:
        # 只取身份字段;正文永不读取/打印/解析(不是命令通道)。
        if flat.get("sender_type") != "user":
            print("[discover] 忽略一条非真人 sender 事件。")
            return
        if flat.get("chat_type") != "p2p":
            print("[discover] 忽略一条非一对一消息(群聊不用于身份发现)。")
            return
        open_id = flat.get("sender_open_id")
        tenant_key = flat.get("tenant_key")
        chat_id = flat.get("chat_id")
        if not (open_id and tenant_key and chat_id):
            print("[discover] 忽略一条身份字段不全的消息(可能是 app/bot sender)。")
            return
        quad = {"open_id": open_id, "tenant_key": tenant_key,
                "chat_id": chat_id, "chat_type": "p2p"}
        with state_lock:
            candidate = state["candidate"]
            if candidate is None:
                candidate = {**quad, "discovered_at": _now_iso(), "others": []}
                state["candidate"] = candidate
                _write_0600(CANDIDATE_PATH, candidate)
                first = True
            elif open_id == candidate["open_id"]:
                return
            elif any(other.get("open_id") == open_id for other in candidate["others"]):
                return
            else:
                candidate["others"].append({**quad, "seen_at": _now_iso()})
                _write_0600(CANDIDATE_PATH, candidate)
                first = False
        if first:
            print("[discover] 收到候选 owner 身份(**尚未生效**):")
            print(f"  open_id    = {open_id}")
            print(f"  tenant_key = {tenant_key}")
            print(f"  chat_id    = {chat_id}")
            print("  chat_type  = p2p")
            print(f"[discover] 已写入 {CANDIDATE_PATH}(0600)。")
            print("[discover] 请核对 open_id 是否本人;确认后手动改名方可生效:")
            print(f'  mv "{CANDIDATE_PATH}" "{FINAL_PATH}"')
            print("[discover] 本工具绝不自动写 discovered-owner.json(防首条 p2p 抢注)。")
            print("[discover] 继续监听:后续不同 sender 的 p2p 会记入 others 数组供比对。"
                  "按 Ctrl-C 退出。")
            return
        print("[discover] 警告:收到**不同 sender** 的 p2p(身份与候选不一致),"
              "已追加进 candidate 的 others 数组供人工比对(只记身份,不记正文):")
        print(f"  open_id    = {open_id}")
        print(f"  tenant_key = {tenant_key}")
        print(f"  chat_id    = {chat_id}")

    transport = FeishuTransport(app_id, app_secret)
    try:
        transport.start_long_connection(on_event)  # 阻塞
    except KeyboardInterrupt:
        print("\n[discover] 已退出。")
    finally:
        os.close(lock_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
