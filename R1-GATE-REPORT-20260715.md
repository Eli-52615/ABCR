# R1 门报告 · ABCR 自动化控制面 · 2026-07-15

> fable 主持,r1-integration worktree(合并 pkg/a+pkg/b+pkg/c 于冻结基线)手跑全链演练。
> 演练环境:`.venv312`(CPython 3.12.13)+ `PYTHONPATH=src`。演练后 `git checkout -- fixtures/` 已还原。
> **结论:R1 门通过(全判据真绿,零人工——批准动作除外)。**

## 一、全链演练实录(canonical §0.3)

| 步 | 动作 | 结果 |
|---|---|---|
| 1 | `abcrctl approve fixtures/envelope_fixture.json --key fixtures/test_approval.key` | 退出 0;batches 链 `batch_approved` actor="human"(AMENDMENT-10) |
| 2 | `dispatch --envelope … --key …` | 退出 0;6 run 全 completed+scored;`batch_settled` |
| 3 | A `a_rescore.py` + `a_rescore_compare.py --against fixtures/expected_scores.jsonl` | **MATCH 60/60** 退出 0 |
| 4 | A `a_audit.py … --items 1,2,4 --apply` | overall **PASS**;item1/2/4 全 PASS;报告含 "g03/g07 判 0 双方一致——fixture 设计的已知错误分布,非异常" |
| 5 | A views(末态) | 6 run 末事件全 `run_accepted`、批次末 `batch_audited` |
| 6 | C `report.cli overview` | is_correct: deterministic_v1=0.8 / rescore_v1=0.8(双实现一致,g03/g07=0 已反映) |
| 7 | C 三层钻取 overview→batch→run --item g03 | 总耗时 **0.847s**(≤60s);g03 output 33 字符 = fail_sample `"hello, hello, hello, hello, hello"` |
| 8 | C `triage` | 生成 reports/triage-2026-07-15.md,分桶与账本一致 |

## 二、R1-A 判据矩阵(包A · 账本/审计)

| 判据 | 命令 | 结果 |
|---|---|---|
| R1-A1 契约测试全绿且 A 未改动 | `pytest tests/contract_pkgabc` + git log | **130 passed**;pkgA 对 contract_pkgabc 提交数 = 0 |
| R1-A2 A 单测全绿 | `pytest tests/ledger tests/audit` | **62 passed** |
| R1-A3 schema 收 fixture 拒变异 | `pytest -k schema` | **42 passed** |
| R1-A4 哈希链断链检测 | `pytest -k "tamper or chain"` | **51 passed** |
| R1-A5 状态机非法迁移拒绝 | `pytest -k "transition or statemachine"` | **46 passed** |
| R1-A6 rescore = expected | `a_rescore_compare` | **MATCH 60/60**,g03/g07=0,退出 0 |
| R1-A7 rescore = deterministic_v1 | `a_audit --items 2` | item2 rescore_comparison **PASS** |
| R1-A8 auditor 报告 + g03/g07 呈现 | `a_audit --items 1,2,4 --apply` | overall PASS,MD 含已知错误分布呈现句 |
| R1-A9 视图对该批出对 | 末态核验 | 6 run `run_accepted`、批次 `batch_audited` |

## 三、R1-B 判据矩阵(包B · Operator/rig)

| 判据 | 结果 |
|---|---|
| R1-B1 契约测试全绿 | 130 passed(共享同一套) |
| R1-B2 本包单测(not golden) | **51 passed** |
| R1-B3 坏令牌 fail-closed | dispatch(badtoken) **退出码 2**;batches `batch_dispatch_rejected` reason_code=bad_signature;告警文件 `state/alerts/*-envelope-rejected.json`;runs_index 无新事件(**双留痕 AMENDMENT-13**) |
| R1-B4 fixture 信封全链 | `b_r1_selfcheck.sh` → **R1 SELFCHECK PASS** |
| R1-B5 crash 断点续跑 | crash run 事件序 `run_registered→run_queued→run_started→run_failed→run_resumed→step_progress×2→run_completed→run_scored`;全 run steps 无重复 (item,seed) |
| R1-B6 心跳落账 | step_progress = **12**(6 run×2) |
| R1-B7 分数与期望一致 | selfcheck 断言③ 逐字节相等,PASS |
| R1-B8 账本链自洽 | verify_chain 不抛(selfcheck 断言②) |
| R1-B9 watchdog 检出停摆并冷却 | `pytest test_watchdog.py` **6 passed** |
| R1-B10 dispatch 幂等 | 重跑 settled 批 **退出码 0**、already-settled、零新事件(54→54) |

## 四、C-R1 判据矩阵(包C · Governor/同步视图)

| 判据 | 结果 |
|---|---|
| C-R1-1 契约测试全绿 | 130 passed |
| C-R1-2 C 单测全绿 | `pytest tests/governor tests/report` **57 passed** |
| C-R1-3 令牌真值锚 | `pytest test_approval_token.py` **14 passed** |
| C-R1-4 approve 签发可被 B 消费 | 步1 approve → 步2 dispatch 放行退出 0(**跨包真互签,本次修复前三仓从未互验过**) |
| C-R1-5 planner 出草案/拒越界 | test_planner 覆盖(57 passed 内) |
| C-R1-6 triage 分桶 | reports/triage-2026-07-15.md 生成,分桶与账本一致 |
| C-R1-7 sync 逐数带 run_id | test_sync 覆盖 |
| C-R1-8 三层钻取 ≤1min | **0.847s**;g03 原文 = fixture fail_sample |

## 五、集成整体

- 全包契约+单测(r1-integration 树):**300 passed**(not golden)。
- `preflight_kickoff.py`:**30/30 PASS**(拓扑/venv/契约库 import/fixture 跨模块互验/契约测试可收集全过)。
- 旧 W1 归档回归:stage1 **43 passed**(旧模块未被新增基线污染;stage2-4 为加载模型的慢测,非本次改动影响面)。

## 六、本次修复消除的最大工程风险

审计实测发现:修复前三仓的"全绿"互不可传递——A 的 MATCH 60/60 对 A 自造 fixture、B 的分数一致对 B 自拉平口径、C 的验签闭环对 C 自签令牌;**三套令牌六向互验全崩、三把测试密钥字节全不同、账本 API 三套签名,从未真正跨包互签互验过**。R1 步1→步2 的 `abcrctl approve`(C 签)→ `dispatch`(B 验)真跑通,是三仓历史上第一次跨包真互签,也是本次唯一契约基线收敛的最终验证。

—— fable,2026-07-15
