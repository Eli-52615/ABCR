"""Human-readable cards: decision first, evidence one level below."""
from __future__ import annotations

from typing import Any


def render_status_card(item: dict[str, Any]) -> str:
    return "\n".join((
        f"现在：{item.get('human_state', '状态未知')}",
        f"最后确认：{item.get('updated_at', '未知')}",
        f"已经做了：{item.get('done', '无可确认信息')}",
        f"接下来：{item.get('next', '等待可靠状态')}",
        f"预计：{item.get('eta', 'UNKNOWN')}",
        f"需要你：{item.get('needs_human', '否')}",
        f"证据：{item.get('evidence_ref', '无')}",
    ))


def render_approval_card(request: dict[str, Any]) -> str:
    return "\n".join((
        f"这轮验证：{request['hypothesis']}",
        f"人格/对照：{request['arms_summary']}",
        f"题目与 seed：{request['item_count']} 题；{request['seed_count']} 个 seed",
        f"预计费用：{request.get('cost', 'UNKNOWN')}；预计时间：{request.get('eta', 'UNKNOWN')}",
        f"内容指纹：{request['envelope_sha256']}",
        f"有效期：{request['expires_at']}",
        f"动作：批准 {request['request_id']} {request['envelope_sha256'][:12]} v{request['version']}",
    ))
