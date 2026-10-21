"""Deterministic Chinese command router and durable proposal upload sessions."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from abcr.control.contracts import Actor, ContractError, ControlCommand, sha256
from abcr.control.store import ControlStore

_EXACT = {
    "状态": "status", "为什么停了": "explain_stop", "预算": "budget_status",
    "暂停": "pause", "恢复": "resume", "中止": "abort",
}
_ARG = (
    (re.compile(r"^确认提案\s+([A-Za-z0-9._:-]+)$"), "confirm_proposal", "proposal_id"),
    (re.compile(r"^运行快道\s+([A-Za-z0-9._:-]+)$"), "run_probe", "proposal_id"),
    (re.compile(r"^毕业这一针\s+([0-9a-f]{64})$"), "promote_probe", "row_hash"),
    (re.compile(r"^批准\s+([A-Za-z0-9._:-]+)\s+([0-9a-f]{6,64})\s+v([1-9][0-9]*)$"),
     "approve", ("request_id", "envelope_prefix", "version")),
    (re.compile(r"^拒绝\s+([A-Za-z0-9._:-]+)\s+(.+)$"), "reject", ("request_id", "reason")),
    (re.compile(r"^记录反思\s+([A-Za-z0-9._:-]+)\s+(.+)$"), "record_reflection",
     ("round_id", "reflection")),
)


@dataclass(frozen=True)
class RouteResult:
    intent: str | None
    payload: dict[str, Any]
    clarification: tuple[str, ...] = ()


def route_text(text: str) -> RouteResult:
    if not isinstance(text, str) or len(text.encode("utf-8")) > 8192 or "\x00" in text:
        return RouteResult(None, {}, ("消息过长或含无效字符，请使用分段提案导入。",))
    text = text.strip()
    if text in _EXACT:
        return RouteResult(_EXACT[text], {})
    for pattern, intent, fields in _ARG:
        match = pattern.fullmatch(text)
        if not match:
            continue
        values = match.groups()
        names = (fields,) if isinstance(fields, str) else fields
        payload = dict(zip(names, values))
        if "version" in payload: payload["version"] = int(payload["version"])
        return RouteResult(intent, payload)
    return RouteResult(None, {}, (
        "请使用“状态”“开始导入提案”或驾驶舱卡片给出的完整动作。",
        "批准必须包含 request id、内容指纹前缀和版本。",
    ))


class FrontDoor:
    def __init__(self, store: ControlStore):
        self.store = store

    def begin_upload(self, actor: Actor, message_id: str) -> str:
        session_id = "PS-" + sha256({"actor": actor.open_id, "message": message_id})[:18]
        self.store.create_upload(session_id, actor.open_id)
        return session_id

    def upload_part(self, actor: Actor, session_id: str, message_id: str,
                    seq: int | None, content: str) -> bool:
        _seq, inserted = self.store.append_upload_part(session_id, actor.open_id, message_id,
                                                       seq, content)
        return inserted

    def receive_part(self, actor: Actor, session_id: str, message_id: str, content: str,
                     *, scope: dict[str, Any], payload: dict[str, Any],
                     event_type: str = "message", event_id: str | None = None
                     ) -> tuple[str, bool, int, bool]:
        """Admit the message and store it as the next part in one transaction."""
        return self.store.receive_upload_part(
            message_id=message_id, sender_id=actor.open_id, scope=scope, payload=payload,
            session_id=session_id, content=content, event_type=event_type, event_id=event_id)

    @staticmethod
    def proposal_id(raw: str) -> str:
        return "PROP-" + sha256(raw.encode())[:18]

    def finish_upload(self, actor: Actor, session_id: str) -> tuple[str, str]:
        return self.store.complete_upload(session_id, actor.open_id,
                                          proposal_id_for=self.proposal_id)

    def command(self, actor: Actor, message_id: str, text: str) -> ControlCommand | RouteResult:
        routed = route_text(text)
        if routed.intent is None:
            return routed
        command_id = "CMD-" + sha256({"message": message_id, "text": text,
                                       "actor": actor.open_id})[:18]
        return ControlCommand(command_id, message_id, actor, routed.intent, routed.payload)
