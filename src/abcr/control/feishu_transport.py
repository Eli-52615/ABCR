"""飞书传输层:把独立 ABCR 应用的长连接事件归一化后喂给 HumanGateway,
并用 tenant_access_token 发消息回 owner。

设计约束:
- **LIVE-only 部分只有长连接**。lark_oapi 惰性导入(仅 start_long_connection 内),
  token/发送/归一化用 stdlib urllib —— 模块可被 import 而不需要 SDK,
  CODE_RC 测试不受污染。
- 不共享 AILH 的 WebSocket app(清单 P3 forbidden)。凭据来自本应用独立的
  app_id/secret(staging feishu.env)。
- 不打印 secret 与 access_token:app_secret/_token 排除在 repr 之外,
  异常文本只带飞书返回的 code/msg。
- SDK 日志三件套(方案 §7.1):降级 WARNING + LarkLogRedactor 打码短时凭据
  (ws:// URL query 里的 ticket/access_key 等)+ 专用 0600 日志文件,
  不再裸走 stdout/stderr;实现全部 stdlib(logging),模块 import 不拉 lark_oapi。
- normalize_event / normalize_card_action 输出**平铺**结构,与
  identity.IdentityPolicy.actor_from_event 和 human_gateway.HumanGateway.ingest
  的消费字段一一对应;身份字段缺失时**不造默认值**,保留缺失交由 identity 抛
  identity_fields_missing;非 dict 的 sender/message/operator/context 一律按
  缺失处理(fail-closed,不抛 AttributeError)。
  app/bot sender 原样透传(sender_type 保留),由 identity 依 sender_type 永拒
  (app_bot_forbidden,即使 open_id 与 owner 碰撞)——传输层不做身份判断
  (方案 §7.1:身份只取 server event,永不从正文/显示名/卡片 value 推断)。
- send_text 的 receive_id_type 走白名单校验(RECEIVE_ID_TYPES),不在表内直接
  ValueError,杜绝 query 注入与手误。
"""
from __future__ import annotations

import json
import logging
import os
import re
import stat
import threading
import time
import traceback
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

BASE = "https://open.feishu.cn/open-apis"

#: token 提前刷新余量(秒):离过期不足此值即刷新,避免边界竞态。
TOKEN_REFRESH_MARGIN = 60

#: staging 目录(feishu.env 与默认 lark-ws.log 的落点;与 bootstrap 脚本一致)。
STAGING_DIR = Path.home() / "Library" / "Application Support" / "ABCR-Human-staging"

#: lark SDK 专用日志文件默认路径(0600;可由 start_long_connection 调用方覆盖)。
DEFAULT_LARK_LOG_PATH = STAGING_DIR / "lark-ws.log"

#: send_text 允许的 receive_id_type 白名单(飞书 im/v1/messages 官方取值)。
RECEIVE_ID_TYPES = frozenset({"chat_id", "open_id", "user_id", "union_id", "email"})

# ws(s):// URL 的 query 整段打码(长连接 URL 的 query 携带 ticket 等短时凭据)。
_WS_URL_QUERY = re.compile(r"(?i)(wss?://[^\s?'\"]+)\?\S*")
# 任意位置的短时凭据键值对打码(SDK ERROR/异常文本里可能裸出现,不在 URL 内)。
_CRED_PAIR = re.compile(
    r"(?i)([\"']?(?:ticket|access_key|access_token|tenant_access_token|app_secret|secret"
    r"|token|preview_token|signature)[\"']?\s*[:=]\s*)"
    r'(?:"([^"]*)"|\'([^\']*)\'|([^&\s,\}\]]+))')
# Authorization 头需要单独处理；若交给通用键值规则，`Bearer` 后的真正 token
# 会因中间空格而残留。兼容 header、异常文本和 JSON 风格的冒号/等号写法。
_BEARER_AUTH = re.compile(
    r"(?i)(\bauthorization[\"']?\s*[:=]\s*[\"']?bearer\s+)"
    r"([^\s,\"'\}\]]+)")


def redact_credentials(text: str) -> str:
    """打码短时凭据:先剥 ws(s):// URL 的整个 query,再打码裸键值对。

    host/path 保留(可诊断);value 一律换成 [REDACTED],绝不回显
    ticket/access_key/token 等(方案 §7.1:不记录带短时凭据的 WebSocket URL)。
    """
    text = _WS_URL_QUERY.sub(r"\1?[REDACTED]", text)
    text = _BEARER_AUTH.sub(lambda m: f"{m.group(1)}[REDACTED]", text)

    def _redact_pair(match: re.Match[str]) -> str:
        # 三个 value 分支依次为双引号、单引号、裸值；保留成对引号以免破坏
        # JSON/日志可读性，同时把带空格的整个引号值一并清除。
        if match.group(2) is not None:
            return f'{match.group(1)}"[REDACTED]"'
        if match.group(3) is not None:
            return f"{match.group(1)}'[REDACTED]'"
        return f"{match.group(1)}[REDACTED]"

    return _CRED_PAIR.sub(_redact_pair, text)


class LarkLogRedactor(logging.Filter):
    """lark SDK 日志打码 filter:消息、异常与 stack 文本统一过 redact_credentials。

    不丢日志(恒返 True),只改写内容;有异常信息时先格式化、打码,再并入
    msg 并清掉 exc_info/exc_text,防止 Formatter 事后展开未打码的原始 traceback。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_credentials(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        if isinstance(record.exc_info, tuple) and record.exc_info[0] is not None:
            exc_text = "".join(traceback.format_exception(*record.exc_info))
            record.msg = f"{record.getMessage()}\n{redact_credentials(exc_text)}".rstrip()
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        elif record.exc_text:
            record.exc_text = redact_credentials(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_credentials(record.stack_info)
        return True


class _Lark0600FileHandler(logging.FileHandler):
    """0600 打开(O_APPEND)的日志文件 handler;文件已存在时显式收紧权限。"""

    def _open(self):
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.chmod(self.baseFilename, 0o600)  # 已存在文件 os.open 的 mode 不生效,显式收紧
        return os.fdopen(fd, "a", encoding="utf-8")


def setup_lark_logging(log_path: str | Path | None = None) -> logging.Logger:
    """配置 lark SDK 的 "Lark" logger:降级 + 打码 filter + 0600 专用日志文件三件套。

    - logger 名 "Lark" 与 lark_oapi/core/log.py 对齐;该模块 import 时挂的裸
      stdout StreamHandler 在此移除,日志只进专用文件,不再裸走 stdout/stderr;
    - LarkLogRedactor 同时挂在 logger 与 handler 上(propagate 关闭);
    - 幂等:重复调用不叠加 handler/filter(旧 handler 先关闭再替换);
    - stdlib-only:不导入 lark_oapi,CODE_RC 测试可零网络直测。
    """
    path = Path(log_path) if log_path is not None else DEFAULT_LARK_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("Lark")
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        existing.close()
    for existing_filter in list(logger.filters):
        logger.removeFilter(existing_filter)
    redactor = LarkLogRedactor()
    handler = _Lark0600FileHandler(str(path))
    handler.setFormatter(logging.Formatter(
        "[lark] [%(asctime)s] [%(levelname)s] %(message)s"))
    handler.addFilter(redactor)
    logger.addFilter(redactor)
    logger.addHandler(handler)
    return logger


@dataclass
class FeishuTransport:
    app_id: str
    app_secret: str = field(repr=False)
    _token: str = field(default="", repr=False)
    _token_expiry: float = field(default=0.0, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False,
                                  repr=False, compare=False)

    # ---- tenant_access_token(stdlib;带过期缓存)----
    def tenant_token(self, *, now: float | None = None) -> str:
        now = now if now is not None else time.time()
        with self._lock:
            if self._token and now < self._token_expiry - TOKEN_REFRESH_MARGIN:
                return self._token
            req = urllib.request.Request(
                f"{BASE}/auth/v3/tenant_access_token/internal",
                data=json.dumps({"app_id": self.app_id,
                                 "app_secret": self.app_secret}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
            if body.get("code") != 0:
                # 只带 code/msg;绝不把请求体(含 secret)或 token 写进异常文本。
                raise RuntimeError(
                    f"tenant_access_token 失败: code={body.get('code')} msg={body.get('msg')}")
            self._token = body["tenant_access_token"]
            self._token_expiry = now + int(body.get("expire", 7200))
            return self._token

    # ---- 发文本消息(stdlib)----
    def send_text(self, *, receive_id: str, text: str,
                  receive_id_type: str = "chat_id") -> dict[str, Any]:
        if receive_id_type not in RECEIVE_ID_TYPES:
            # 白名单校验:不在表内直接拒(fail-closed),不发任何请求;
            # 同时杜绝把任意字符串拼进 URL query 的注入面。
            raise ValueError(
                f"receive_id_type 不在白名单: {receive_id_type!r}"
                f"(允许: {sorted(RECEIVE_ID_TYPES)})")
        req = urllib.request.Request(
            f"{BASE}/im/v1/messages?receive_id_type={receive_id_type}",
            data=json.dumps({"receive_id": receive_id, "msg_type": "text",
                             "content": json.dumps({"text": text})}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.tenant_token()}"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
        if body.get("code") != 0:
            # 失败交由上层 outbox 重试(方案 §7.2:发送失败只重试 outbox);
            # 异常文本只带 code/msg,不带 Authorization/token。
            raise RuntimeError(
                f"feishu send_text 失败: code={body.get('code')} msg={body.get('msg')}")
        return body

    # ---- 事件归一化:lark 长连接两段(header+event)→ gateway 期望的平铺结构 ----
    @staticmethod
    def normalize_event(header: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        """把飞书 v2 事件(header + event 两段)拍平成本仓 gateway 期望的形状。

        消费方字段(必须逐项对齐,不一致改这里,不改 identity/gateway):
        - identity.actor_from_event: sender_open_id / tenant_key / chat_id /
          chat_type(缺任一 → identity_fields_missing);app_id(不匹配 → 拒);
          sender_type(存在且非 "user" → app_bot_forbidden,方案 §7.1 永拒);
        - human_gateway.ingest: message_id / text(非 str → message_invalid),
          event_type / event_id(可缺,gateway 有默认与回退)。

        规则:
        - 身份字段缺失时不造默认值(键直接不出现),让 identity fail-closed;
        - 非 dict 的 header/event/sender/sender_id/message 一律按缺失处理
          (fail-closed 产出缺字段,不抛 AttributeError);
        - app/bot sender 原样透传(sender_type 保留),由 identity 永拒
          (app_bot_forbidden);
        - message.content 是 JSON 字符串 {"text": ...}:非法 JSON 或非 text 类
          消息归一为 text="";content 整个缺失则不产出 text 键
          (gateway 报 message_invalid)。
        """
        header = header if isinstance(header, dict) else {}
        event = event if isinstance(event, dict) else {}
        out: dict[str, Any] = {}
        for key in ("app_id", "tenant_key", "event_id", "event_type"):
            value = header.get(key)
            if value is not None:
                out[key] = value
        sender = event.get("sender")
        sender = sender if isinstance(sender, dict) else {}
        if "sender_type" in sender:
            out["sender_type"] = sender["sender_type"]
        sender_id = sender.get("sender_id")
        open_id = sender_id.get("open_id") if isinstance(sender_id, dict) else None
        if open_id is not None:
            out["sender_open_id"] = open_id
        message = event.get("message")
        message = message if isinstance(message, dict) else {}
        for key in ("message_id", "chat_id", "chat_type", "message_type"):
            value = message.get(key)
            if value is not None:
                out[key] = value
        content = message.get("content")
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except ValueError:
                out["text"] = ""
            else:
                text = parsed.get("text") if isinstance(parsed, dict) else None
                out["text"] = text if isinstance(text, str) else ""
        return out

    # ---- 卡片回传归一化:card.action.trigger(header+event)→ 平铺结构 ----
    @staticmethod
    def normalize_card_action(header: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        """把飞书卡片回传(card.action.trigger,header + event 两段)拍平成与
        消息事件同构的平铺结构。

        身份严格取 server event(方案 §7.1):
        - sender_open_id ← event.operator.open_id;
        - tenant_key / app_id / event_id ← header(与 normalize_event 同源);
        - chat_id ← event.context.open_chat_id。
        **绝不**从卡片 action value / 显示名 / 正文推断身份:action.value 以
        `action_value` 键**原样透传**(连同 action.tag → `action_tag`),
        只作业务负载,即使里面伪造了 open_id 也不会进身份字段。

        凭据红线:event.token(卡片更新短时凭据)与 context.preview_token
        **不进输出**。

        event_type:header 有则用 header 的;缺失时标 "card.action.trigger"
        (本归一化只注册在该事件类型上,不算造身份)。
        卡片事件天然不带 chat_type/message_id,输出即不含这些键——喂给
        identity.actor_from_event 会因缺字段 fail-closed 拒绝
        (identity_fields_missing);context.open_message_id 以原名透传,
        不改名为 message_id,避免与消息事件的 dedupe 语义混淆。

        **gateway 消费待接**:human_gateway/identity 目前只消费
        im.message.receive_v1 平铺事件;本方法只完成 transport 侧归一化+注册,
        不修改 human_gateway/identity。

        非 dict 的 header/event/operator/context/action 一律按缺失处理
        (fail-closed 产出缺字段,不抛 AttributeError)。
        """
        header = header if isinstance(header, dict) else {}
        event = event if isinstance(event, dict) else {}
        out: dict[str, Any] = {}
        for key in ("app_id", "tenant_key", "event_id"):
            value = header.get(key)
            if value is not None:
                out[key] = value
        header_type = header.get("event_type")
        out["event_type"] = (header_type if isinstance(header_type, str) and header_type
                             else "card.action.trigger")
        operator = event.get("operator")
        if isinstance(operator, dict):
            open_id = operator.get("open_id")
            if open_id is not None:
                out["sender_open_id"] = open_id
        context = event.get("context")
        if isinstance(context, dict):
            chat_id = context.get("open_chat_id")
            if chat_id is not None:
                out["chat_id"] = chat_id
            open_message_id = context.get("open_message_id")
            if open_message_id is not None:
                out["open_message_id"] = open_message_id
        action = event.get("action")
        if isinstance(action, dict):
            if "value" in action:
                out["action_value"] = action["value"]
            tag = action.get("tag")
            if tag is not None:
                out["action_tag"] = tag
        return out

    # ---- 长连接接收(lark_oapi 惰性导入;LIVE-only)----
    def start_long_connection(self, on_event: Callable[[dict[str, Any]], None], *,
                              lark_log_path: str | Path | None = None) -> None:
        """启动飞书长连接;im.message.receive_v1 与 card.action.trigger 均归一化
        后回调同一 on_event。

        阻塞运行(SDK 内部起线程)。lark_oapi 仅在此导入。
        SDK 日志三件套(方案 §7.1):级别降为 WARNING + LarkLogRedactor 打码
        (ticket/access_key 等短时凭据与带凭据的 ws URL)+ 专用 0600 日志文件
        (默认 staging 目录 lark-ws.log,可用 lark_log_path 覆盖),不再裸走
        stdout/stderr。ERROR 路径:client.start() 的异常文本同样打码后重抛。

        卡片回传经 normalize_card_action 归一化(身份只取 operator.open_id +
        tenant_key + context.open_chat_id);gateway 消费待接,见其 docstring。
        """
        import lark_oapi as lark  # LIVE-only,惰性
        # lark_oapi.core.log 在 import 时无条件向 "Lark" logger 追加裸 stdout
        # StreamHandler。必须在 import **之后**重配；反过来会让 SDK 的导入副作用
        # 绕过 0600 文件与 redactor。
        setup_lark_logging(lark_log_path)

        def _marshal(part) -> dict[str, Any]:
            # SDK 对象 → dict;非 dict 结果按空处理(fail-closed)
            data = json.loads(lark.JSON.marshal(part)) if part else {}
            return data if isinstance(data, dict) else {}

        def _dispatch(data) -> None:
            on_event(self.normalize_event(_marshal(data.header), _marshal(data.event)))

        def _dispatch_card(data):
            on_event(self.normalize_card_action(_marshal(data.header), _marshal(data.event)))
            return None  # 不做卡片内联更新;None 即"无 toast/卡片变更"

        handler = (lark.EventDispatcherHandler.builder("", "")
                   .register_p2_im_message_receive_v1(_dispatch)
                   .register_p2_card_action_trigger(_dispatch_card).build())
        client = lark.ws.Client(self.app_id, self.app_secret,
                                event_handler=handler, log_level=lark.LogLevel.WARNING)
        try:
            client.start()
        except Exception as exc:
            # ERROR 路径:异常文本过打码;from None 掐断链路,防止未打码的
            # 原始异常(可能含带 ticket 的 ws URL)随 traceback 泄露。
            raise RuntimeError(
                f"feishu 长连接异常: {redact_credentials(str(exc))}") from None


def load_credentials(env_path: str) -> tuple[str, str]:
    """从 .env 读 ABCR_FEISHU_APP_ID / ABCR_FEISHU_APP_SECRET。

    支持注释/空行/可选 `export ` 前缀/成对引号。异常文本不含文件内容。
    """
    path = Path(env_path)
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise RuntimeError("当前平台缺少 O_NOFOLLOW，拒绝不安全地读取飞书凭据")
    flags = os.O_RDONLY | no_follow
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        mode = stat.S_IMODE(info.st_mode)
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError(f"飞书凭据文件不是普通文件: {env_path}")
        if info.st_nlink != 1:
            raise RuntimeError(f"飞书凭据文件硬链接数必须为 1: {env_path}")
        if info.st_uid != os.geteuid():
            raise RuntimeError(f"飞书凭据文件属主必须是当前进程 euid: {env_path}")
        if mode != 0o600:
            raise RuntimeError(f"飞书凭据文件权限必须严格为 0600: {env_path}")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1  # ownership 已交给 stream
            lines = stream.read().splitlines()
    finally:
        if fd >= 0:
            os.close(fd)

    app_id = secret = ""
    seen: set[str] = set()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[len("export "):].strip()
        if k in seen:
            raise RuntimeError(f"飞书凭据文件包含重复键 {k!r}: {env_path}")
        seen.add(k)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        if k == "ABCR_FEISHU_APP_ID":
            app_id = v
        elif k == "ABCR_FEISHU_APP_SECRET":
            secret = v
    if not app_id or not secret:
        raise RuntimeError(f"未在 {env_path} 找到 ABCR_FEISHU_APP_ID/ABCR_FEISHU_APP_SECRET")
    return app_id, secret
