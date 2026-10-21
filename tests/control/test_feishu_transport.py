"""feishu_transport 零网络测试。

覆盖:tenant_token 缓存/过期/非 0 code;send_text 组包与 Authorization 头 +
receive_id_type 白名单;normalize_event 对真实飞书 v2 事件样例的归一化(含
content 非法 JSON、缺字段、非 dict 段 fail-closed、app/bot sender 原样透传交
identity 拒绝);normalize_card_action(身份只取 operator/tenant_key/open_chat_id,
action value 不当身份,短时凭据不透传,缺字段 fail-closed);lark SDK 日志三件套
(LarkLogRedactor 打码 ws URL 短时凭据、专用日志文件 0600、不裸走 stdout/stderr);
load_credentials 正反例;repr/str/异常文本不泄露 secret;模块 import 不拉 lark_oapi。

全部通过 monkeypatch urllib.request.urlopen / tmp_path 实现,零网络。
"""
from __future__ import annotations

import json
import importlib.util
import logging
import os
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from abcr.control.contracts import ContractError
from abcr.control.feishu_transport import (
    RECEIVE_ID_TYPES,
    FeishuTransport,
    LarkLogRedactor,
    load_credentials,
    redact_credentials,
    setup_lark_logging,
)
from abcr.control.human_gateway import HumanGateway
from abcr.control.identity import IdentityPolicy
from abcr.control.store import ControlStore

SECRET = "s3cr3t-do-not-leak"


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeHTTP:
    """按调用顺序吐出预置响应,并记录 (Request, kwargs)。"""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []

    def __call__(self, req, **kwargs):
        self.requests.append((req, kwargs))
        if not self.payloads:
            raise AssertionError("unexpected extra HTTP call (network would have been hit)")
        return _Resp(self.payloads.pop(0))


def fake_http(monkeypatch, payloads):
    fake = _FakeHTTP(payloads)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


TOKEN_OK = {"code": 0, "msg": "ok", "tenant_access_token": "t-abc", "expire": 7200}


# ---------------------------------------------------------------- tenant_token
def test_tenant_token_caches_and_refreshes_on_expiry(monkeypatch):
    fake = fake_http(monkeypatch, [
        {"code": 0, "tenant_access_token": "t-1", "expire": 7200},
        {"code": 0, "tenant_access_token": "t-2", "expire": 7200},
    ])
    t = FeishuTransport("cli_x", SECRET)
    assert t.tenant_token(now=1000.0) == "t-1"
    # 距过期(1000+7200)还有 >60s → 命中缓存,不发第二次请求
    assert t.tenant_token(now=8000.0) == "t-1"
    assert len(fake.requests) == 1
    # 进入 60s 刷新余量 → 重新取
    assert t.tenant_token(now=8150.0) == "t-2"
    assert len(fake.requests) == 2
    # 新 token 的过期时间基于刷新时刻
    assert t.tenant_token(now=8150.0 + 7000) == "t-2"
    assert len(fake.requests) == 2
    # token 请求本身的组包:POST 到 internal 端点,body 带 app_id/app_secret
    req, _ = fake.requests[0]
    assert req.get_method() == "POST"
    assert req.full_url.endswith("/auth/v3/tenant_access_token/internal")
    body = json.loads(req.data)
    assert body == {"app_id": "cli_x", "app_secret": SECRET}


def test_tenant_token_nonzero_code_raises_without_secret(monkeypatch):
    fake_http(monkeypatch, [{"code": 10003, "msg": "invalid app_id"}])
    t = FeishuTransport("cli_x", SECRET)
    with pytest.raises(RuntimeError) as exc:
        t.tenant_token(now=0.0)
    text = str(exc.value)
    assert "10003" in text and "invalid app_id" in text
    assert SECRET not in text


# ------------------------------------------------------------------- send_text
def test_send_text_packaging_and_authorization_header(monkeypatch):
    fake = fake_http(monkeypatch, [TOKEN_OK, {"code": 0, "data": {"message_id": "om_9"}}])
    t = FeishuTransport("cli_x", SECRET)
    out = t.send_text(receive_id="ou_owner", text="已收到并安全入箱。", receive_id_type="open_id")
    assert out["data"]["message_id"] == "om_9"
    assert len(fake.requests) == 2
    req, _ = fake.requests[1]
    assert req.get_method() == "POST"
    assert req.full_url == (
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id")
    assert req.get_header("Authorization") == "Bearer t-abc"
    body = json.loads(req.data)
    assert body["receive_id"] == "ou_owner"
    assert body["msg_type"] == "text"
    # content 必须是 JSON 字符串(飞书要求双重编码)
    assert json.loads(body["content"]) == {"text": "已收到并安全入箱。"}


def test_send_text_default_receive_id_type_is_chat_id(monkeypatch):
    fake = fake_http(monkeypatch, [TOKEN_OK, {"code": 0, "data": {}}])
    FeishuTransport("cli_x", SECRET).send_text(receive_id="oc_1", text="hi")
    req, _ = fake.requests[1]
    assert "receive_id_type=chat_id" in req.full_url


def test_send_text_nonzero_code_raises_without_token_or_secret(monkeypatch):
    fake_http(monkeypatch, [TOKEN_OK, {"code": 230002, "msg": "bot not in chat"}])
    t = FeishuTransport("cli_x", SECRET)
    with pytest.raises(RuntimeError) as exc:
        t.send_text(receive_id="oc_1", text="hi")
    text = str(exc.value)
    assert "230002" in text
    assert "t-abc" not in text and SECRET not in text


@pytest.mark.parametrize("receive_id_type", sorted(RECEIVE_ID_TYPES))
def test_send_text_whitelist_members_accepted(monkeypatch, receive_id_type):
    fake = fake_http(monkeypatch, [TOKEN_OK, {"code": 0, "data": {}}])
    FeishuTransport("cli_x", SECRET).send_text(
        receive_id="rid", text="hi", receive_id_type=receive_id_type)
    req, _ = fake.requests[1]
    assert req.full_url.endswith(f"receive_id_type={receive_id_type}")


@pytest.mark.parametrize("bad", [
    "chat_id&uuid=x",       # query 注入
    "open_id ",             # 手误(尾随空格)
    "OPEN_ID",              # 大小写不豁免
    "e-mail", "message_id", "",
])
def test_send_text_receive_id_type_outside_whitelist_raises_without_http(monkeypatch, bad):
    fake = fake_http(monkeypatch, [])  # 任何 HTTP 调用都会 AssertionError
    t = FeishuTransport("cli_x", SECRET)
    with pytest.raises(ValueError) as exc:
        t.send_text(receive_id="rid", text="hi", receive_id_type=bad)
    assert "receive_id_type" in str(exc.value)
    assert fake.requests == []  # fail-closed:白名单先于取 token/发请求


# ------------------------------------------------------------- normalize_event
def v2_header(**over):
    header = {"event_id": "ev_001", "event_type": "im.message.receive_v1",
              "create_time": "1753142400000", "token": "", "app_id": "cli_abcr",
              "tenant_key": "tk_1"}
    header.update(over)
    return header


def v2_event(**over):
    event = {
        "sender": {"sender_id": {"union_id": "on_u", "user_id": "u1",
                                 "open_id": "ou_owner"},
                   "sender_type": "user", "tenant_key": "tk_1"},
        "message": {"message_id": "om_1", "create_time": "1753142400001",
                    "chat_id": "oc_chat", "chat_type": "p2p",
                    "message_type": "text",
                    "content": json.dumps({"text": "状态"}), "mentions": []},
    }
    event.update(over)
    return event


def owner_gateway(tmp_path) -> HumanGateway:
    return HumanGateway(ControlStore(tmp_path / "control.db"),
                        IdentityPolicy("ou_owner", "oc_chat", "tk_1", "cli_abcr"))


def test_normalize_real_sample_flat_shape_matches_identity_and_gateway(tmp_path):
    flat = FeishuTransport.normalize_event(v2_header(), v2_event())
    assert flat["sender_open_id"] == "ou_owner"
    assert flat["tenant_key"] == "tk_1"
    assert flat["chat_id"] == "oc_chat"
    assert flat["chat_type"] == "p2p"
    assert flat["app_id"] == "cli_abcr"
    assert flat["message_id"] == "om_1"
    assert flat["text"] == "状态"
    assert flat["event_id"] == "ev_001"
    assert flat["event_type"] == "im.message.receive_v1"
    assert flat["sender_type"] == "user"
    # 端到端:同一形状直接被 identity + gateway 消费(不改 identity/gateway)
    gateway = owner_gateway(tmp_path)
    actor = gateway.identity.actor_from_event(flat)
    assert (actor.open_id, actor.chat_id, actor.tenant_key) == ("ou_owner", "oc_chat", "tk_1")
    assert gateway.ingest(flat).code == "queued"
    assert gateway.ingest(flat).code == "duplicate_ignored"  # event_id 幂等


def test_normalize_content_illegal_json_becomes_empty_text():
    event = v2_event()
    event["message"]["content"] = "not-json{{"
    flat = FeishuTransport.normalize_event(v2_header(), event)
    assert flat["text"] == ""
    assert flat["message_id"] == "om_1"  # 其余字段不受影响


def test_normalize_non_text_message_keeps_type_and_empty_text():
    event = v2_event()
    event["message"]["message_type"] = "image"
    event["message"]["content"] = json.dumps({"image_key": "img_x"})
    flat = FeishuTransport.normalize_event(v2_header(), event)
    assert flat["message_type"] == "image"
    assert flat["text"] == ""


def test_normalize_missing_fields_stay_missing_and_identity_fails_closed(tmp_path):
    # content 整个缺失 → 不产出 text 键
    event = v2_event()
    del event["message"]["content"]
    flat = FeishuTransport.normalize_event(v2_header(), event)
    assert "text" not in flat
    # sender 整个缺失 → 无 sender_open_id,identity 报 identity_fields_missing
    event = v2_event()
    del event["sender"]
    flat = FeishuTransport.normalize_event(v2_header(), event)
    assert "sender_open_id" not in flat and "sender_type" not in flat
    with pytest.raises(ContractError) as exc:
        owner_gateway(tmp_path).identity.actor_from_event(flat)
    assert exc.value.code == "identity_fields_missing"
    # header 缺失 → 不造 app_id/tenant_key 默认值
    flat = FeishuTransport.normalize_event({}, v2_event())
    assert "app_id" not in flat and "tenant_key" not in flat and "event_id" not in flat


def test_normalize_app_sender_passthrough_rejected_by_identity(tmp_path):
    # app sender 无 open_id:原样透传(不在传输层过滤),identity 依 sender_type 永拒
    # (方案 §7.1;先于缺字段校验,拒绝不依赖字段恰好缺失)
    event = v2_event(sender={"sender_type": "app"})
    flat = FeishuTransport.normalize_event(v2_header(), event)
    assert flat["sender_type"] == "app" and "sender_open_id" not in flat
    with pytest.raises(ContractError) as exc:
        owner_gateway(tmp_path).identity.actor_from_event(flat)
    assert exc.value.code == "app_bot_forbidden"


def test_normalize_bot_sender_with_open_id_rejected_as_app_bot_forbidden(tmp_path):
    event = v2_event(sender={"sender_id": {"open_id": "ou_bot"}, "sender_type": "app"})
    flat = FeishuTransport.normalize_event(v2_header(), event)
    assert flat["sender_open_id"] == "ou_bot" and flat["sender_type"] == "app"
    with pytest.raises(ContractError) as exc:
        owner_gateway(tmp_path).identity.actor_from_event(flat)
    assert exc.value.code == "app_bot_forbidden"


@pytest.mark.parametrize("sender_type", ["app", "bot"])
def test_app_sender_with_owner_open_id_collision_still_rejected(tmp_path, sender_type):
    # 审查 F1 攻击 A3:sender_type=app/bot 且 open_id 与 owner **完全一致**,
    # chat/tenant/app 也全部匹配 —— 方案 §7.1「app/bot sender 永拒」:
    # 拒绝必须来自 sender_type 本身,不得依赖 open_id 恰好不相等。
    event = v2_event()
    event["sender"]["sender_type"] = sender_type
    flat = FeishuTransport.normalize_event(v2_header(), event)
    assert flat["sender_open_id"] == "ou_owner" and flat["sender_type"] == sender_type
    gateway = owner_gateway(tmp_path)
    with pytest.raises(ContractError) as exc:
        gateway.identity.actor_from_event(flat)
    assert exc.value.code == "app_bot_forbidden"
    # 端到端:同一事件走 ingest 也被拒,且不落 inbox/action(不产生任何持久痕迹)
    with pytest.raises(ContractError) as exc2:
        gateway.ingest(flat)
    assert exc2.value.code == "app_bot_forbidden"
    assert gateway.store.rows("inbox") == [] and gateway.store.rows("actions") == []


def test_normalize_group_chat_rejected_by_identity(tmp_path):
    event = v2_event()
    event["message"]["chat_type"] = "group"
    flat = FeishuTransport.normalize_event(v2_header(), event)
    with pytest.raises(ContractError) as exc:
        owner_gateway(tmp_path).identity.actor_from_event(flat)
    assert exc.value.code == "group_chat_forbidden"


@pytest.mark.parametrize("bad", ["not-a-dict", 42, ["x"], None, True])
def test_normalize_non_dict_sender_and_message_fail_closed(tmp_path, bad):
    # F5:非 dict 的 sender/message 按缺失处理——产出缺字段而非 AttributeError
    flat = FeishuTransport.normalize_event(v2_header(), {"sender": bad, "message": bad})
    assert "sender_open_id" not in flat and "sender_type" not in flat
    assert "message_id" not in flat and "chat_id" not in flat and "text" not in flat
    with pytest.raises(ContractError) as exc:
        owner_gateway(tmp_path).identity.actor_from_event(flat)
    assert exc.value.code == "identity_fields_missing"


def test_normalize_non_dict_sender_id_and_top_level_fail_closed():
    # sender_id 非 dict → 无 sender_open_id(sender_type 照常透传)
    event = v2_event(sender={"sender_id": "ou_fake_as_string", "sender_type": "user"})
    flat = FeishuTransport.normalize_event(v2_header(), event)
    assert "sender_open_id" not in flat and flat["sender_type"] == "user"
    # header/event 整体非 dict → 空产出,不抛 AttributeError
    assert FeishuTransport.normalize_event("junk", None) == {}


# ------------------------------------------------------- normalize_card_action
def card_header(**over):
    """伪 SDK 对象 marshal 后的 header(与 lark EventHeader 字段一致)。"""
    header = {"event_id": "ev_card_1", "event_type": "card.action.trigger",
              "create_time": "1753142400000", "token": "verify-tok",
              "app_id": "cli_abcr", "tenant_key": "tk_1"}
    header.update(over)
    return header


def card_event(**over):
    """伪 SDK 对象 marshal 后的 event(与 lark P2CardActionTriggerData 字段一致)。

    token / context.preview_token 是短时凭据;action.value 里塞了伪造身份,
    用于断言"value 绝不当身份"。
    """
    event = {
        "operator": {"tenant_key": "tk_1", "user_id": "u1",
                     "open_id": "ou_owner", "union_id": "on_u"},
        "token": "card-tok-SHORTLIVED",
        "action": {"value": {"cmd": "approve", "open_id": "ou_attacker",
                             "chat_id": "oc_attacker"},
                   "tag": "button"},
        "host": "im_message",
        "delivery_type": "",
        "context": {"open_message_id": "om_card_1", "open_chat_id": "oc_chat",
                    "preview_token": "pv-tok-SHORTLIVED"},
    }
    event.update(over)
    return event


def test_normalize_card_action_identity_from_operator_and_context_only():
    flat = FeishuTransport.normalize_card_action(card_header(), card_event())
    # 身份严格取 operator.open_id + tenant_key + context.open_chat_id(方案 §7.1)
    assert flat["sender_open_id"] == "ou_owner"
    assert flat["tenant_key"] == "tk_1"
    assert flat["chat_id"] == "oc_chat"
    assert flat["app_id"] == "cli_abcr"
    assert flat["event_id"] == "ev_card_1"
    assert flat["event_type"] == "card.action.trigger"
    assert flat["open_message_id"] == "om_card_1"
    # action value 原样透传,但 value 里伪造的 open_id/chat_id 绝不进身份字段
    assert flat["action_value"] == {"cmd": "approve", "open_id": "ou_attacker",
                                    "chat_id": "oc_attacker"}
    assert flat["action_tag"] == "button"
    assert flat["sender_open_id"] != "ou_attacker" and flat["chat_id"] != "oc_attacker"


def test_normalize_card_action_short_lived_tokens_never_pass_through():
    flat = FeishuTransport.normalize_card_action(card_header(), card_event())
    dumped = json.dumps({k: v for k, v in flat.items() if k != "action_value"})
    assert "card-tok-SHORTLIVED" not in dumped
    assert "pv-tok-SHORTLIVED" not in dumped
    assert "verify-tok" not in dumped
    assert "token" not in flat and "preview_token" not in flat


def test_normalize_card_action_missing_chat_type_fails_closed_at_identity(tmp_path):
    # 卡片事件天然无 chat_type → identity 缺字段拒绝(gateway 消费待接,fail-closed)
    flat = FeishuTransport.normalize_card_action(card_header(), card_event())
    assert "chat_type" not in flat and "message_id" not in flat
    with pytest.raises(ContractError) as exc:
        owner_gateway(tmp_path).identity.actor_from_event(flat)
    assert exc.value.code == "identity_fields_missing"


def test_normalize_card_action_missing_identity_fields_stay_missing(tmp_path):
    # operator 整个缺失 → 无 sender_open_id
    flat = FeishuTransport.normalize_card_action(card_header(), card_event(operator=None))
    assert "sender_open_id" not in flat
    with pytest.raises(ContractError) as exc:
        owner_gateway(tmp_path).identity.actor_from_event(flat)
    assert exc.value.code == "identity_fields_missing"
    # context 整个缺失 → 无 chat_id/open_message_id
    flat = FeishuTransport.normalize_card_action(card_header(), card_event(context=None))
    assert "chat_id" not in flat and "open_message_id" not in flat
    # header 缺失 → 不造 app_id/tenant_key;event_type 标注册类型(非身份字段)
    flat = FeishuTransport.normalize_card_action({}, card_event())
    assert "app_id" not in flat and "tenant_key" not in flat and "event_id" not in flat
    assert flat["event_type"] == "card.action.trigger"


@pytest.mark.parametrize("bad", ["str", 42, ["x"], True])
def test_normalize_card_action_non_dict_sections_fail_closed(bad):
    # F5:非 dict 的 operator/context/action 按缺失处理,不抛 AttributeError
    flat = FeishuTransport.normalize_card_action(
        card_header(), card_event(operator=bad, context=bad, action=bad))
    assert "sender_open_id" not in flat and "chat_id" not in flat
    assert "action_value" not in flat and "action_tag" not in flat
    # header/event 整体非 dict → 只剩标注的 event_type
    assert FeishuTransport.normalize_card_action(bad, bad) == {
        "event_type": "card.action.trigger"}


def test_normalize_card_action_operator_open_id_forged_as_owner_still_needs_full_match(tmp_path):
    # 即使 operator.open_id 与 owner 一致,chat_type 缺失仍 fail-closed
    #(identity 全字段校验;不因单字段匹配放行)
    flat = FeishuTransport.normalize_card_action(card_header(), card_event())
    assert flat["sender_open_id"] == "ou_owner"
    with pytest.raises(ContractError):
        owner_gateway(tmp_path).identity.actor_from_event(flat)


# ------------------------------------------------- lark SDK 日志三件套(F2)
WS_URL = ("wss://open-ws.feishu.cn/ws/v2?device_id=dev1"
          "&ticket=TICKET-SHORTLIVED&access_key=AK-SHORTLIVED")


def test_redact_credentials_masks_ws_url_query_and_bare_pairs():
    out = redact_credentials(f"connected to {WS_URL}")
    assert "TICKET-SHORTLIVED" not in out and "AK-SHORTLIVED" not in out
    assert "device_id" not in out  # query 整段剥除
    assert "wss://open-ws.feishu.cn/ws/v2?[REDACTED]" in out  # host/path 保留可诊断
    # 非 URL 处的裸键值对同样打码(ERROR/异常文本路径)
    out = redact_credentials("connect failed, err: ticket=tk-999 access_key=ak-1 code=1000")
    assert "tk-999" not in out and "ak-1" not in out
    assert "ticket=[REDACTED]" in out and "access_key=[REDACTED]" in out
    assert "code=1000" in out  # 非凭据键不受影响,保诊断性


@pytest.mark.parametrize("raw,secrets", [
    ("Authorization: Bearer bearer-secret", ("bearer-secret",)),
    ('{"tenant_access_token":"json-token"}', ("json-token",)),
    ("ticket: colon-ticket", ("colon-ticket",)),
    ("access_key='quoted-key'", ("quoted-key",)),
    ('token="quoted secret with spaces"', ("quoted secret with spaces",)),
    ('{"Authorization":"Bearer json-bearer"}', ("json-bearer",)),
])
def test_redact_credentials_masks_header_json_colon_and_quoted_values(raw, secrets):
    out = redact_credentials(raw)
    assert "[REDACTED]" in out
    assert all(secret not in out for secret in secrets)


def test_lark_log_redactor_masks_record_with_args_and_exc_info():
    redactor = LarkLogRedactor()
    # %-style args 的记录:先展开再打码
    record = logging.LogRecord("Lark", logging.WARNING, __file__, 1,
                               "connected to %s", (WS_URL,), None)
    assert redactor.filter(record) is True  # 不丢日志,只改写
    formatted = logging.Formatter("%(message)s").format(record)
    assert "TICKET-SHORTLIVED" not in formatted and "AK-SHORTLIVED" not in formatted
    # 携 exc_info 的 ERROR 记录:异常文本同样打码,且原始 traceback 不再展开
    try:
        raise ConnectionError(f"handshake rejected for {WS_URL}")
    except ConnectionError:
        record = logging.LogRecord("Lark", logging.ERROR, __file__, 1,
                                   "connect failed", (), sys.exc_info())
    assert redactor.filter(record) is True
    assert record.exc_info is None and record.exc_text is None
    formatted = logging.Formatter("%(message)s").format(record)
    assert "TICKET-SHORTLIVED" not in formatted and "AK-SHORTLIVED" not in formatted
    assert "ConnectionError" in formatted  # 异常类型保留可诊断


def test_setup_lark_logging_file_0600_no_bare_stream_and_idempotent(tmp_path, capsys):
    log_path = tmp_path / "lark-ws.log"
    # 预置一个宽权限旧文件:setup 必须显式收紧到 0600
    log_path.write_text("old\n")
    os.chmod(log_path, 0o644)
    # 模拟 lark_oapi/core/log.py import 时挂的裸 stdout handler
    logger = logging.getLogger("Lark")
    bare = logging.StreamHandler(sys.stdout)
    logger.addHandler(bare)
    try:
        logger = setup_lark_logging(log_path)
        assert logger.level == logging.WARNING and logger.propagate is False
        # 裸 stdout/stderr handler 已移除,只剩专用文件 handler
        assert bare not in logger.handlers and len(logger.handlers) == 1
        logger.warning("connected to %s", WS_URL)
        logger.error("connect failed, err: ticket=tk-err-1")
        logger.info("should be dropped by WARNING level")
        for handler in logger.handlers:
            handler.flush()
        assert stat.S_IMODE(os.stat(log_path).st_mode) == 0o600
        content = log_path.read_text()
        assert "TICKET-SHORTLIVED" not in content and "AK-SHORTLIVED" not in content
        assert "tk-err-1" not in content
        assert "[REDACTED]" in content and "connect failed" in content
        assert "should be dropped" not in content  # 降级生效
        assert capsys.readouterr().out == ""  # 不再裸走 stdout
        # 幂等:重复调用不叠加 handler/filter
        setup_lark_logging(log_path)
        assert len(logging.getLogger("Lark").handlers) == 1
        assert len(logging.getLogger("Lark").filters) == 1
    finally:
        lark_logger = logging.getLogger("Lark")
        for handler in list(lark_logger.handlers):
            lark_logger.removeHandler(handler)
            handler.close()
        for f in list(lark_logger.filters):
            lark_logger.removeFilter(f)


# ------------------------------------------------------------ load_credentials
def test_load_credentials_parses_comments_quotes_and_export(tmp_path):
    env = tmp_path / "feishu.env"
    env.write_text(
        "# ABCR 独立飞书应用凭据\n"
        "\n"
        'export ABCR_FEISHU_APP_ID="cli_test123"\n'
        "ABCR_FEISHU_APP_SECRET='sec_val'\n"
        "OTHER_KEY=ignored\n")
    env.chmod(0o600)
    assert load_credentials(str(env)) == ("cli_test123", "sec_val")


def test_load_credentials_missing_key_raises(tmp_path):
    env = tmp_path / "feishu.env"
    env.write_text("ABCR_FEISHU_APP_ID=cli_only\n")
    env.chmod(0o600)
    with pytest.raises(RuntimeError) as exc:
        load_credentials(str(env))
    assert "ABCR_FEISHU_APP_ID/ABCR_FEISHU_APP_SECRET" in str(exc.value)


def test_load_credentials_missing_file_raises(tmp_path):
    with pytest.raises(OSError):
        load_credentials(str(tmp_path / "absent.env"))


def test_load_credentials_rejects_non_0600_file(tmp_path):
    env = tmp_path / "feishu.env"
    env.write_text("ABCR_FEISHU_APP_ID=cli_x\nABCR_FEISHU_APP_SECRET=sec_x\n")
    env.chmod(0o640)
    with pytest.raises(RuntimeError, match="0600"):
        load_credentials(str(env))


def test_load_credentials_rejects_symlink(tmp_path):
    target = tmp_path / "target.env"
    target.write_text("ABCR_FEISHU_APP_ID=cli_x\nABCR_FEISHU_APP_SECRET=sec_x\n")
    target.chmod(0o600)
    link = tmp_path / "feishu.env"
    link.symlink_to(target)
    with pytest.raises(OSError):
        load_credentials(str(link))


def test_load_credentials_rejects_hardlink(tmp_path):
    target = tmp_path / "target.env"
    target.write_text("ABCR_FEISHU_APP_ID=cli_x\nABCR_FEISHU_APP_SECRET=sec_x\n")
    target.chmod(0o600)
    link = tmp_path / "feishu.env"
    os.link(target, link)
    with pytest.raises(RuntimeError, match="硬链接数"):
        load_credentials(str(link))


def test_load_credentials_rejects_wrong_owner(tmp_path, monkeypatch):
    env = tmp_path / "feishu.env"
    env.write_text("ABCR_FEISHU_APP_ID=cli_x\nABCR_FEISHU_APP_SECRET=sec_x\n")
    env.chmod(0o600)
    actual_uid = env.stat().st_uid
    monkeypatch.setattr(os, "geteuid", lambda: actual_uid + 1)
    with pytest.raises(RuntimeError, match="属主"):
        load_credentials(str(env))


def test_load_credentials_rejects_duplicate_key(tmp_path):
    env = tmp_path / "feishu.env"
    env.write_text(
        "ABCR_FEISHU_APP_ID=cli_x\n"
        "ABCR_FEISHU_APP_ID=cli_shadow\n"
        "ABCR_FEISHU_APP_SECRET=sec_x\n")
    env.chmod(0o600)
    with pytest.raises(RuntimeError, match="重复键"):
        load_credentials(str(env))


@pytest.mark.skipif(importlib.util.find_spec("lark_oapi") is None,
                    reason="installed lark_oapi SDK unavailable")
def test_start_long_connection_reconfigures_logger_after_real_sdk_import(tmp_path):
    """在全新解释器里走真实 SDK import；Client 替身只阻止网络。

    lark_oapi 1.7.1 import 会无条件追加 stdout handler。此测试若只预先调用
    setup_lark_logging、或预先 import SDK，都会漏掉真实的导入时序回归。
    """
    src = Path(__file__).resolve().parents[2] / "src"
    log_path = tmp_path / "lark-real-sdk.log"
    code = r'''
import builtins
import logging
import sys
from abcr.control.feishu_transport import FeishuTransport

real_import = builtins.__import__

class FakeClient:
    def __init__(self, *args, **kwargs):
        handlers = logging.getLogger("Lark").handlers
        assert len(handlers) == 1, handlers
        assert all(getattr(h, "stream", None) not in (sys.stdout, sys.stderr)
                   for h in handlers), handlers
    def start(self):
        return None

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    module = real_import(name, globals, locals, fromlist, level)
    if name == "lark_oapi":
        module.ws.Client = FakeClient
    return module

builtins.__import__ = guarded_import
FeishuTransport("cli_test", "secret-test").start_long_connection(
    lambda event: None, lark_log_path=sys.argv[1])
handlers = logging.getLogger("Lark").handlers
assert len(handlers) == 1, handlers
assert all(getattr(h, "stream", None) not in (sys.stdout, sys.stderr)
           for h in handlers), handlers
'''
    proc = subprocess.run(
        [sys.executable, "-c", code, str(log_path)],
        env={**os.environ, "PYTHONPATH": str(src)},
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ------------------------------------------------------------- secret hygiene
def test_repr_and_str_do_not_leak_secret_or_token(monkeypatch):
    fake_http(monkeypatch, [TOKEN_OK])
    t = FeishuTransport("cli_x", SECRET)
    assert t.tenant_token(now=0.0) == "t-abc"
    for text in (repr(t), str(t)):
        assert SECRET not in text
        assert "t-abc" not in text
    assert "cli_x" in repr(t)  # app_id 非机密,保留可诊断性


# ------------------------------------------------------------ import isolation
def test_module_import_is_stdlib_only_no_lark_oapi():
    src = Path(__file__).resolve().parents[2] / "src"
    code = ("import sys\n"
            "import abcr.control.feishu_transport\n"
            "assert 'lark_oapi' not in sys.modules, 'lark_oapi imported eagerly'\n")
    proc = subprocess.run([sys.executable, "-c", code],
                          env={**os.environ, "PYTHONPATH": str(src)},
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
