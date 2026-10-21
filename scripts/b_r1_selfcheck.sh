#!/bin/bash
# scripts/b_r1_selfcheck.sh —— R1 演练自证（在 worktree 根、venv 激活后执行）
set -euo pipefail
export PYTHONPATH=src

# 冻结基线（AMENDMENT-41）：fixtures 由 scripts/kickoff_make_fixtures.py 单点维护并入 git，
# selfcheck 只消费不再自产（b_make_fixtures.py 已废弃删除）。缺失即视为基线未就位 → 硬失败。
for f in fixtures/envelope_fixture.json fixtures/test_approval.key fixtures/expected_scores.jsonl; do
  [ -f "$f" ] || { echo "缺冻结 fixture: $f（跑 scripts/preflight_kickoff.py 核验基线）" >&2; exit 1; }
done

# 干净现场（精确清理——⚠️ 绝不 rm -rf state 整目录：会连带删掉 state/approval.key，阶段2 真密钥
# 误删即事故。fixture 令牌消费记录 state/approvals/ 随现场重置——selfcheck 本就是从零重演）
rm -rf ledger queue data/runs state/runs state/alerts state/approvals state/watchdog-dispatched.json
mkdir -p data/runs

# 1. 正常全链（令牌为 fixture 预签，人批环节由 fixture 代表）
python -m abcr.ops.dispatch --envelope fixtures/envelope_fixture.json --key fixtures/test_approval.key

# 2. crash 续跑演练：重置后对其中一个 run 注入 crash，再原命令重跑收敛（同上精确清理）
rm -rf ledger queue data/runs state/runs state/alerts state/approvals state/watchdog-dispatched.json
mkdir -p data/runs
ABCR_FAKETASK_CRASH_AT_ITEM=g05 \
  python -m abcr.ops.dispatch --envelope fixtures/envelope_fixture.json --key fixtures/test_approval.key || true
python -m abcr.ops.dispatch --envelope fixtures/envelope_fixture.json --key fixtures/test_approval.key

# 3. 断言：无重复 (run_id,item_id,seed)、账本链完好、分数与期望一致
python scripts/b_r1_assert.py
echo "R1 SELFCHECK PASS"
