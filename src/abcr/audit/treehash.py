"""abcr.audit.treehash —— code_tree_hash 计算与三向对账（审计项5 的核心）。

架构位置：包A·验船师侧。§2.7/§3.7 冻结定义：对 src/ scripts/ configs/ data/traits
data/golden data/benchmarks data/splits data/items 承诺根下 **全部文件** 逐字节 sha256，
仅排除派生物（__pycache__/.git/.venv 目录、*.pyc/*.pyo/*.so 等编译/动态库产物），
code_tree_hash = sha256(json.dumps(树, sort_keys=True))。

V10 加固（后缀白名单 → 全文件 hash）：旧实现按 10 个后缀白名单过滤，任何不在集内
的后缀/无后缀文件可被替换而 code_tree_hash 不变——真实高危未覆盖面包括
configs/templates/*/chat_template.hash（完整性锚点）、data/splits/*.sha256（校验和锚点）、
scripts/abcrctl（无后缀可执行入口）。改为全文件逐字节 hash 后这些文件被替换必被抓住。

逐字移植自工程包A文档 §6·A2-2 骨架。`json.dumps(树, sort_keys=True)` 用默认 separators
（§3.7 原文口径，B 计算 manifest.code_tree_hash 必须同式）。消费者：version_check
（审计项5）、a_freeze（定稿仪式）、dispatch._code_tree_hash（生产端 manifest 写入，单一定义）。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# §3.7 单一定义（本模块为权威）：承诺根下全部文件逐字节 hash，不再按后缀白名单过滤。
# 生产端 dispatch._code_tree_hash 委托本实现（单一定义纪律，由组G 接线）。
CODE_TREE_ROOTS: tuple[str, ...] = (
    "src", "scripts", "configs", "data/traits", "data/golden",
    "data/benchmarks", "data/splits", "data/items")
# 【历史遗留 · 已不再作过滤器】V10 前的后缀白名单；保留符号仅供单一定义纪律的
# 兼容别名（dispatch._CODE_TREE_EXTS）与历史回归引用，hash_tree 不再据此过滤。
CODE_TREE_EXTS: tuple[str, ...] = (
    ".py", ".json", ".md", ".yaml", ".txt",
    ".sh", ".toml", ".jsonl", ".pyi", ".cfg")
_EXCLUDE_DIRS = ("__pycache__", ".git", ".venv")
# 派生物后缀：编译产物 / 动态库，重建即变、非源可信物，纳入承诺只会制造噪声 drift。
# 这是 **唯一** 的排除口径（与旧白名单方向相反：从"只收白名单"变为"只排派生物"）。
_EXCLUDE_EXTS = (".pyc", ".pyo", ".so", ".pyd", ".o", ".a", ".dylib", ".dll")


def hash_tree(repo_root: Path) -> dict[str, str]:
    """遍历冻结根集合，返回 {相对路径: sha256}。文件名排序保证确定性。

    V10：承诺根下 **全部文件** 逐字节 hash，仅跳过派生物目录与派生物后缀；
    不再按后缀白名单收窄——无后缀入口（scripts/abcrctl）、锚点文件
    （*.hash / *.sha256）等一律纳入，被替换即被抓住。符号链接不跟随其目标读取
    （os.walk 不进入 symlink 目录；符号链接文件按其自身内容读取会失败则跳过）。
    """
    out: dict[str, str] = {}
    for rel_root in CODE_TREE_ROOTS:
        root = Path(repo_root) / rel_root
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]
            for name in sorted(filenames):
                if name.endswith(_EXCLUDE_EXTS):
                    continue
                p = Path(dirpath) / name
                if not p.is_file():          # 断链符号链接/特殊文件：跳过（无字节可读）
                    continue
                rel = str(p.relative_to(repo_root))
                out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def code_tree_hash(repo_root: Path) -> str:
    """§2.7 冻结公式：sha256(json.dumps(树, sort_keys=True))。"""
    tree = hash_tree(repo_root)
    return hashlib.sha256(json.dumps(tree, sort_keys=True).encode("utf-8")).hexdigest()


def diff_trees(want: dict[str, str], have: dict[str, str]) -> dict[str, list[str]]:
    """三向对账：缺失 / 多出 / 内容漂移。全空 = 一致。"""
    return {
        "missing": sorted(set(want) - set(have)),
        "extra": sorted(set(have) - set(want)),
        "drift": sorted(r for r in set(want) & set(have) if want[r] != have[r]),
    }
