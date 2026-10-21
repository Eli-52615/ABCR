#!/usr/bin/env python3
"""preflight_kickoff.py —— kickoff/阶段门实物验收闸（AMENDMENT-42，fable 维护）。

用途：凡文档/广播声明的实物前提，开工前必须由本脚本核验通过；任一不实存即 FAIL
并停工上报（PROGRESS 记 BLOCKER），**绝不允许"文档说已交付"替代实物核验**——
本工作流 2026-07-14 事故（kickoff 从未执行而三窗口被文档告知"已就位"）的防复发条款。

用法（任一 worktree 根或主仓根）：
    PYTHONPATH=src <主仓>/.venv312/bin/python scripts/preflight_kickoff.py
退出码：0=全过；1=存在 FAIL。
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

MAIN_REPO = Path("/Users/superagent/shared-brain/ABCR/abcr")
WT = Path("/Users/superagent/shared-brain/ABCR/abcr-wt")
CWD = Path.cwd()

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    print(f"== kickoff preflight（cwd={CWD}）==")

    # 1) 仓库拓扑
    check("主仓存在", (MAIN_REPO / ".git").exists())
    r = subprocess.run(["git", "-C", str(MAIN_REPO), "branch", "--list",
                        "main", "pkg/a", "pkg/b", "pkg/c"],
                       capture_output=True, text=True)
    branches = {b.strip().lstrip("+* ") for b in r.stdout.splitlines() if b.strip()}
    for b in ("main", "pkg/a", "pkg/b", "pkg/c"):
        check(f"分支 {b}", b in branches)
    for w in ("a", "b", "c"):
        p = WT / w
        is_wt = (p / ".git").is_file()   # 真 worktree 的 .git 是文件（gitdir 指针），独立仓是目录
        check(f"worktree {p}", p.exists() and is_wt,
              "" if is_wt else "存在但不是主仓 worktree（独立仓？）" if p.exists() else "不存在")

    # 2) venv 与解释器（AMENDMENT-40）
    venv = MAIN_REPO / ".venv312" / "bin" / "python"
    check("控制面 venv .venv312", venv.exists())
    if venv.exists():
        v = subprocess.run([str(venv), "-V"], capture_output=True, text=True).stdout.strip()
        check("Python 3.12.x", v.startswith("Python 3.12"), v)

    # 3) 契约库可 import（在 cwd 的 src 布局下）
    sys.path.insert(0, str(CWD / "src"))
    for mod in ("abcr.common.constants", "abcr.common.ledger_ref",
                "abcr.common.approval_token", "abcr.governor.envelope",
                "abcr.ledger.schema", "abcr.ledger.statemachine"):
        try:
            importlib.import_module(mod)
            check(f"import {mod}", True)
        except Exception as e:
            check(f"import {mod}", False, repr(e))

    # 4) 冻结实物存在
    for rel in ("data/golden/golden10.json", "fixtures/envelope_fixture.json",
                "fixtures/envelope_fixture_badtoken.json", "fixtures/test_approval.key",
                "fixtures/faketask_spec.md", "fixtures/expected_scores.jsonl",
                "requirements-mac.txt", "FABLE-BROADCAST-20260715.md"):
        check(rel, (CWD / rel).exists())

    # 5) fixture 跨模块互验（不是"文件在"而是"链路通"）
    try:
        from abcr.common import approval_token as tok
        from abcr.governor.envelope import envelope_sha256, load_envelope
        key_p = CWD / "fixtures" / "test_approval.key"
        env = load_envelope(CWD / "fixtures" / "envelope_fixture.json")
        key = key_p.read_bytes()
        det = hashlib.sha256(b"abcr-w1-fixture-test-approval-key").digest()
        check("test_approval.key 为 AMENDMENT-34 确定性值", key == det)
        body = {k: v for k, v in env.items() if k != "approval"}
        ok, reason = tok.verify_token(
            env["approval"]["token"], expected_envelope_sha256=envelope_sha256(body),
            verify_secret=key, consumed_store=CWD / "state" / "_preflight_consumed.json")
        check("fixture 预签令牌验签", ok and reason == "ok", reason)
        bad = load_envelope(CWD / "fixtures" / "envelope_fixture_badtoken.json")
        ok2, reason2 = tok.verify_token(
            bad["approval"]["token"], expected_envelope_sha256=envelope_sha256(body),
            verify_secret=key, consumed_store=CWD / "state" / "_preflight_consumed.json")
        check("坏令牌拒绝路径", (not ok2) and reason2 == "bad_signature", reason2)
        g10 = json.loads((CWD / "data/golden/golden10.json").read_text(encoding="utf-8"))
        check("golden10 结构（AMENDMENT-3）",
              g10.get("schema_version") == "1.0" and len(g10.get("items", [])) == 10)
        n_expected = sum(1 for ln in (CWD / "fixtures/expected_scores.jsonl")
                         .read_text(encoding="utf-8").splitlines() if ln.strip())
        check("expected_scores 60 行", n_expected == 60, str(n_expected))
    except Exception as e:
        check("fixture 跨模块互验", False, repr(e))

    # 6) 契约测试可收集（AMENDMENT-32 路径）
    ct = CWD / "tests" / "contract_pkgabc"
    check("tests/contract_pkgabc 非空", ct.exists() and any(ct.glob("test_*.py")))

    # 7) 环境注记（不阻塞项，只提示）
    if not (MAIN_REPO / ".env").exists():
        print("  [NOTE] 主仓 .env 未注入（DEEPSEEK_API_KEY 等）——不阻塞 R1，阻塞 B1-10/云日")

    fails = [n for n, ok, _ in _results if not ok]
    print(f"== 结果：{len(_results) - len(fails)}/{len(_results)} PASS ==")
    if fails:
        print("FAIL 项：" + "; ".join(fails))
        print("→ 停工，PROGRESS 记 BLOCKER，等 fable/楠 处置。不得以文档承诺替代实物。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
