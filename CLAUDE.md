# ABCR — Claude Code 工作指南

> ⚠️ **2026-07-15 起本仓进入「自动化控制面」阶段**（工程包A/B/C 三窗并行，pkg/a|b|c worktree）。
> 权威增量契约见 `FABLE-BROADCAST-20260715.md`（AMENDMENT-32~42）。要点：
> - 开工第一动作：`PYTHONPATH=src .venv312/bin/python scripts/preflight_kickoff.py` 全 PASS 才开工（AMENDMENT-42）。
> - commit 前缀用 `[pkgA]/[pkgB]/[pkgC]`（疑议#13 裁决；下文旧「[A/B/C]」前缀仅适用于已归档的旧 W1 实验）。
> - 各窗口进度文件 = `PROGRESS-A/B/C.md`；契约测试 = `tests/contract_pkgabc/`（AMENDMENT-32；`tests/contract/` 下 stage1-4 为旧 W1 归档，零触碰）。
> - 控制面 venv = `.venv312`（旧 `.venv` 供旧 W1 回归专用）；一律 `PYTHONPATH=$PWD/src`，禁 `pip install -e .`。
> 下文「执行纪律/呈现纪律」两节对新阶段依然有效；「三包并行」一节的旧拆分（Runner/Hook/Scorer）已归档，新拆分=A 账本审计 / B Operator+rig / C Governor+同步视图。

## 执行纪律

1. 文档没写的细节：独立决策，在 DEVIATIONS.md 追加一行（前缀 `[A/B/C]`），不回查任何外部文件。
2. 只写所有权矩阵中属于自己的文件；消费他包产物只认冻结路径，缺位走本文档后备；不跨窗口沟通。
3. 按阶段推进：完成阶段 N 自验后更新 STATUS-{A/B/C}.md，停在阶段门等统一回归。
4. 每完成一个 WBS 条目 git commit（前缀 `[A/B/C]`）；遇 index.lock 等 2s 重试 ≤5 次。
5. 验收断言必须真实跑过、输出留存；失败如实报告，禁止降低断言换绿。
6. 治理三条：本窗口不跑 /boss；本仓永不 git push；仓内路径规避子串 "/persona/"、"v_core"、"judgment_engine"。

## 呈现纪律

- Mac 产物一律 `citable=false`（正式证据要 24GB 云卡 bf16）。
- 一切只碰 dev split。
- 对外数字必带 exploratory / rig-validation 标注。
- fail 方向 = fail-closed：宁可误报也不漏报。
- ¥150 预算常量（本周不租卡，无 GPU 开支）。

## 三包并行

本仓三包（A=Runner/Ledger, B=Hook/Vector/PV, C=Scorer/Audit/ReproPack）并行开发，文件所有权互斥，详见各包执行文档。
