"""abcr.sandboxing.profiles —— 冻结区 Seatbelt profile 生成 + wrap 启动。

架构位置：包A·冻结区内核级只读防线。冻结区 = data/golden data/splits data/traits。机制：
macOS Seatbelt（/usr/bin/sandbox-exec）内核级 deny file-write*——应用层纪律可绕，内核裁决不可
（进程内 open('w')、shell 重定向、rm 全部被拦，2026-07-11 macOS 26.4.1 实测）。

血泪硬规则（逐条遵守）：① 路径必须 realpath 展开的绝对路径（Seatbelt 不解析 ~，/tmp 是
/private/tmp 符号链接）；② last-match-wins：deny 必排在覆盖它的 allow 之后；③ subpath 匹配整棵
子树，literal 匹配单文件；④ deny file-write* 覆盖写/删/改名/chmod；⑤ 只限写，读与网络全开。

逐字移植自工程包A文档 §6·A2-5 骨架（模板 A 黑名单式）。available() 显式暴露平台可用性——非
macOS/显式禁用时 wrap 原样返回命令，不静默降级。契约出处：工程包A §6·A2-5 + §8.2 R2-A4/A10。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
FROZEN_RELS: tuple[str, ...] = ("data/golden", "data/splits", "data/traits")

# 模板 B（白名单式）默认放行工作区外的系统写点（包裹 claude CLI 级大进程树时用）
_TEMPLATE_B_ALLOW = (
    "/Users/superagent/.claude", "/Users/superagent/.cache",
    "/Users/superagent/.local/state", "/private/tmp", "/tmp",
    "/private/var/folders")
_TEMPLATE_B_DENY_LITERAL = ("/Users/superagent/.claude/settings.json",)
_TEMPLATE_B_DENY_SUBPATH = (
    "/Users/superagent/.claude/plugins", "/Users/superagent/.ssh")


def available() -> bool:
    if os.environ.get("ABCR_SANDBOX_DISABLED") == "1":
        return False
    return sys.platform == "darwin" and os.path.exists(_SANDBOX_EXEC)


def _rp(p: str | Path) -> str:
    """realpath 展开（Seatbelt 不解析 ~，按 canonical 路径匹配 subpath）。"""
    return os.path.realpath(os.path.expanduser(str(p)))


def _frozen_parent_nodes(work_root: str | Path) -> tuple[str, ...]:
    """承载冻结子树的父目录节点（去重、realpath）。默认三区父节点均为 <root>/data。

    subpath 只守子树内部：`mv data/golden ...` 被拦，但 `mv data data.bak && mkdir data`
    这类"替换父目录、换入伪冻结子树"的写作用在父节点 <root>/data 上，subpath 不覆盖。
    用 literal 守父节点：只拦对 <root>/data 这一路径本身的写（rename/删除/替换），
    不拦 <root>/data/runs/... 等子路径（literal 不匹配子路径），故 data/runs 仍可写。
    """
    parents: list[str] = []
    for rel in FROZEN_RELS:
        parent = _rp((Path(work_root) / rel).parent)
        if parent not in parents:
            parents.append(parent)
    return tuple(parents)


def frozen_profile(work_root: str | Path) -> str:
    """模板 A（黑名单式）：全系统可写、仅冻结区三目录只读。包裹 B 的执行进程。"""
    lines = ["(version 1)", "(allow default)"]
    for rel in FROZEN_RELS:
        lines.append(f'(deny file-write* (subpath "{_rp(Path(work_root) / rel)}"))')
    for parent in _frozen_parent_nodes(work_root):   # 父节点 literal 守（防替换父目录换入伪子树）
        lines.append(f'(deny file-write* (literal "{parent}"))')
    return "\n".join(lines) + "\n"


def whitelist_profile(work_root: str | Path) -> str:
    """模板 B（白名单式）：默认禁写 + 放行工作区 + 系统写点，冻结区仍只读。
    阶段2 备选，包裹 claude CLI 级大进程树时用（last-match-wins：冻结区 deny 排最后）。"""
    root = _rp(work_root)
    lines = ["(version 1)", "(allow default)", "(deny file-write*)",
             f'(allow file-write* (subpath "{root}"))']
    for rel in FROZEN_RELS:
        lines.append(f'(deny file-write* (subpath "{_rp(Path(work_root) / rel)}"))')
    for parent in _frozen_parent_nodes(work_root):   # 父节点 literal 守（同 frozen_profile）
        lines.append(f'(deny file-write* (literal "{parent}"))')
    for p in _TEMPLATE_B_ALLOW:
        lines.append(f'(allow file-write* (subpath "{p}"))')
    for p in _TEMPLATE_B_DENY_LITERAL:
        lines.append(f'(deny file-write* (literal "{p}"))')
    for p in _TEMPLATE_B_DENY_SUBPATH:
        lines.append(f'(deny file-write* (subpath "{p}"))')
    return "\n".join(lines) + "\n"


def _write_profile_secure(path: str, content: str) -> None:
    """O_NOFOLLOW 拒符号链接劫持、O_TRUNC 覆盖预放置、0600 限权；失败抛错不降级裸跑。"""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(content)


def wrap(cmd: list[str], work_root: str | Path,
         profile_path: str = "/private/tmp/abcr-frozen.sb") -> list[str]:
    """把命令包进沙箱。非 macOS/显式禁用时原样返回（available() 显式暴露，不静默）。"""
    if not available():
        return cmd
    _write_profile_secure(profile_path, frozen_profile(work_root))
    return [_SANDBOX_EXEC, "-f", profile_path, *cmd]
