"""Patch only the marked read-only snapshot block in a Feishu document."""
from __future__ import annotations

from abcr.control.contracts import ContractError, ControlSnapshot, sha256

BEGIN = "<!-- ABCR-SNAPSHOT:BEGIN -->"
END = "<!-- ABCR-SNAPSHOT:END -->"


def render_snapshot(snapshot: ControlSnapshot) -> str:
    lines = [f"更新时间：{snapshot.generated_at}", f"状态级别：{snapshot.severity.value}"]
    for name, value in snapshot.sections.items(): lines.append(f"## {name}\n{value}")
    return "\n\n".join(lines)


def patch_marked_block(document: str, snapshot: ControlSnapshot) -> tuple[str, str]:
    if document.count(BEGIN) != 1 or document.count(END) != 1 or document.index(BEGIN) > document.index(END):
        raise ContractError("doc_marker_invalid", "镜像文档必须恰有一对有序标记")
    before, tail = document.split(BEGIN, 1); _, after = tail.split(END, 1)
    block = render_snapshot(snapshot)
    patched = before + BEGIN + "\n" + block + "\n" + END + after
    return patched, sha256(block.encode())
