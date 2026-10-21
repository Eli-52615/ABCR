"""Owner-only, one-to-one Feishu identity boundary."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from abcr.control.contracts import Actor, ContractError


@dataclass(frozen=True)
class IdentityPolicy:
    owner_open_id: str
    owner_chat_id: str
    tenant_key: str
    app_id: str

    def actor_from_event(self, event: dict[str, Any]) -> Actor:
        # 方案 §7.1:app/bot sender 永拒。sender_type 存在且非真人 "user"
        # (app/bot/任何未知值)一律先拒——先于其余字段校验,即使 open_id 与
        # owner 碰撞也不放行。键缺失(内部平铺事件)交由后续 fail-closed 校验。
        sender_type = event.get("sender_type")
        if sender_type is not None and sender_type != "user":
            raise ContractError("app_bot_forbidden", "只接受真人发送者;app/bot sender 永拒",
                                {"sender_type": sender_type})
        try:
            actor = Actor(open_id=event["sender_open_id"], tenant_key=event["tenant_key"],
                          chat_id=event["chat_id"], chat_type=event["chat_type"])
        except (KeyError, TypeError) as exc:
            raise ContractError("identity_fields_missing", "飞书事件缺少身份字段") from exc
        if event.get("app_id") != self.app_id:
            raise ContractError("identity_mismatch", "飞书 app 身份不匹配")
        actor.validate(owner_open_id=self.owner_open_id, owner_chat_id=self.owner_chat_id,
                       tenant_key=self.tenant_key)
        return actor
