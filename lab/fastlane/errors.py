"""快道自己的失败类型。

单独成模块，是为了让 `split_adapter` 与 `loop` 共用同一套错误而不互相 import。

为什么不直接用科学核心的 `ContractError`：页面要按来源分类展示。
"科学核心拒绝了这个请求" 和 "快道自己的输入校验没过" 对人是两件事，
混成一种错误会让人分不清该改假设还是该去查数据。
"""
from __future__ import annotations

from typing import Any


class FastlaneError(RuntimeError):
    """快道层的失败。`code` 是稳定的机器契约，`message` 是给人看的话。"""

    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}
