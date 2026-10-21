"""abcr.notify —— 飞书告警（按 kind 24h 冷却）。阶段3 接线，阶段1/2 代码先行。

架构位置：包C·对人通知出口。app 凭证直发纯文本（不 @ 任何人 → 人可见、
不触发任何 bot）。纪律（承 V2 health_notify）：发送成功才记冷却；失败不记、
下轮重试；状态原子落盘。接线开关 ABCR_NOTIFY_ENABLED（缺省 0=关）。
依赖: lark-oapi, python-dotenv（均在 requirements-mac.txt）。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# 项目根 .env（src/abcr/notify.py → parents[2] = 仓库根；ABCR_ROOT 可覆盖）
_ROOT = Path(os.environ.get("ABCR_ROOT", Path(__file__).resolve().parents[2]))
load_dotenv(_ROOT / ".env")

COOLDOWN_S = int(os.environ.get("ABCR_ALERT_COOLDOWN_S", str(24 * 3600)))
MAX_MSG_LEN = 4000   # 飞书文本消息分片长度（与 V2 生产同值）


def _state_path() -> Path:
    """冷却状态文件路径——调用期求值（勿改回模块级常量：import 早于测试的
    monkeypatch，模块级读 ABCR_STATE_DIR 会让 tmp 重定向失效、冷却写进真 state/）。"""
    return Path(os.environ.get("ABCR_STATE_DIR", "state")) / "alert-cooldown.json"


def _enabled() -> bool:
    return os.environ.get("ABCR_NOTIFY_ENABLED", "0") == "1"


def _send_feishu(text: str) -> bool:
    """app 凭证直发纯文本。失败只返回 False，绝不外抛。"""
    app_id = os.environ.get("AUDITOR_FEISHU_APP_ID", "") or os.environ.get("FEISHU_APP_ID", "")
    app_secret = (os.environ.get("AUDITOR_FEISHU_APP_SECRET", "")
                  or os.environ.get("FEISHU_APP_SECRET", ""))
    chat_id = os.environ.get("ABCR_FEISHU_CHAT_ID", "")
    if not (app_id and app_secret and chat_id):
        print("[abcr-alert] 飞书凭据/chat_id 缺失，跳过发送", file=sys.stderr)
        return False
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
        client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
        ok = True
        for i in range(0, len(text), MAX_MSG_LEN):
            body = (CreateMessageRequestBody.builder()
                    .receive_id(chat_id).msg_type("text")
                    .content(json.dumps({"text": text[i:i + MAX_MSG_LEN]})).build())
            req = (CreateMessageRequest.builder()
                   .receive_id_type("chat_id").request_body(body).build())
            resp = client.im.v1.message.create(req)
            if not resp.success():
                print(f"[abcr-alert] 飞书发送失败 code={resp.code} msg={resp.msg}",
                      file=sys.stderr)
                ok = False
        return ok
    except Exception as e:  # noqa: BLE001 — 告警绝不反噬主流程
        print(f"[abcr-alert] 飞书通路异常: {type(e).__name__}: {e}", file=sys.stderr)
        return False


def _age_s(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        t = datetime.fromisoformat(str(raw))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except (ValueError, TypeError):
        return None   # 解析失败=视为无记录 → 放行（宁可多响不漏响）


def alert(kind: str, msg: str) -> bool:
    """按 kind 冷却发告警。True=已发送；False=开关关/冷却内静默/发送失败。

    kind 命名约定：`<类>:<主体>`（如 "budget:W1"、"quarantined:B-...-0001"），
    冷却按完整 kind 字符串独立计——同类不同主体各自冷却。
    """
    if not _enabled():
        print(f"[abcr-alert] ABCR_NOTIFY_ENABLED!=1，静默丢弃 [{kind}]", file=sys.stderr)
        return False
    sp = _state_path()
    try:
        state = json.loads(sp.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except Exception:  # noqa: BLE001 — 文件缺/坏 = 空状态
        state = {}
    age = _age_s(state.get(kind))
    if age is not None and 0 <= age < COOLDOWN_S:
        return False   # 冷却内 → 静默
    text = (f"🔔 ABCR 告警 [{kind}]（{datetime.now().astimezone():%m-%d %H:%M}）\n"
            f"{msg}\n同类告警 {COOLDOWN_S // 3600}h 内不再重复通知。")
    if not _send_feishu(text):
        return False   # 不记冷却 → 下次调用重试
    state[kind] = datetime.now(timezone.utc).isoformat()
    try:   # 原子写状态（tmp + replace，与 V2 同范式）
        sp.parent.mkdir(parents=True, exist_ok=True)
        tmp = sp.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(sp)
    except Exception:  # noqa: BLE001 — 状态写失败最坏=多响一次，可接受
        pass
    return True


if __name__ == "__main__":   # 冒烟: PYTHONPATH=src python -m abcr.notify smoke "测试消息"
    k = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    m = sys.argv[2] if len(sys.argv) > 2 else "ABCR 告警通路冒烟测试"
    print("sent" if alert(k, m) else "suppressed-or-failed")
