# ABCR 工程包B · Operator + 队列 + 恢复 + 云生命周期 + rig + 科学载荷（运动员侧）V1.0

> **执行者须知（先读完这一段再动手）**
> - 你是**窗口 B**（Claude Opus 4.8 high），三个并行执行窗口之一。你的角色隐喻是**运动员**：你造执行器、队列、断点续跑、看门狗、rig（试验台）与 Persona Vectors 科学载荷。窗口 A 是裁判+验船师（账本/状态机/复评/审计），窗口 C 是大副（信封/计划/同步视图）。
> - 每日工作 **24 小时**。收工前必写 `PROGRESS.md`（格式见本文 §9）。阻塞超 30 分钟：记 BLOCKER、换下一张任务卡，**不钻兔子洞**。
> - 你的 worktree：`/Users/superagent/abcr-wt/b`（分支 `pkg/b`）。主仓 `/Users/superagent/abcr`（main 分支只由 fable 在回归门合并）。vendor 区 `/Users/superagent/abcr-vendor/`（git 之外，B 专属）。
> - **阶段制**：阶段0（接口冻结）已由 fable 完成——契约库、fixture、黄金十题在你 kickoff 时已就位于仓库。你现在做**阶段1（无LLM最小闭环）**，过 **R1 回归门**后做**阶段2（真实执行+故障注入）**，最后过 **R2 回归门**。任一门不过不进下一阶段。
> - fable **只在阶段门（R1/R2）与 BLOCKER/契约疑议裁决时出现**，不日常编码。契约修订权在 fable；你不得自行偏离契约，疑议写进 PROGRESS.md 的「契约疑议」节。
> - **你只拥有两样输入**：本文档 + `/Users/superagent/abcr` 仓库（含 worktree）。不允许读 shared-brain 下任何文件，不允许上网调研。网络白名单七项（AMENDMENT-26 增补后）：pypi、hf-mirror.com、api.deepseek.com、github.com（仅 clone）、registry.ollama.ai、modelscope.cn、云实例 SSH。本文档已嵌入你需要的一切接口、schema、代码、命令与判据。

---

## 0. 任务一页图

### 0.1 阶段1 交付清单（闭环件 = R1-core 回归门约束；预研件 = R1-full，R1-core 过门后、云日前完成——AMENDMENT-30）

| 类别 | 编号 | 交付物 | 路径 | 任务卡 |
|---|---|---|---|---|
| 闭环件 | B1-1 | 确定性假任务执行器（含四个故障旋钮） | `src/abcr/ops/faketask.py` | §5.1 |
| 闭环件 | B1-2 | 目录式队列（pending/running/done/failed 原子改名） | `src/abcr/ops/queue.py` | §5.2 |
| 闭环件 | B1-3 | runstate：item 级断点续跑对账 | `src/abcr/ops/runstate.py` | §5.3 |
| 闭环件 | B1-4 | 进度心跳（每 5 item 落 step_progress） | `src/abcr/ops/heartbeat.py` | §5.4 |
| 闭环件 | B1-5 | dispatch：令牌验证 + 逐 run 驱动 + 账本事件全程落 | `src/abcr/ops/dispatch.py` | §5.5 |
| 闭环件 | B1-6 | scorer v0（golden10 判分，独立评分 pass） | `src/abcr/rig/scorer.py` | §5.6 |
| 闭环件 | B1-7 | watchdog：停摆/孤儿/TTL 检测（只告警不自修） | `src/abcr/ops/watchdog.py` | §5.7 |
| 闭环件 | B1-8 | R1 自证联调（fixture 信封全链 + crash 续跑演练） | `tests/ops/` | §5.8 |
| 预研件 | B1-9 | vendor clone 钉 commit + 两补丁预研 | `/Users/superagent/abcr-vendor/persona_vectors` | §5.9 |
| 预研件 | B1-10 | judge 冒烟四验脚本 | `scripts/b_judge_smoke.py` | §5.10 |
| 预研件 | B1-11 | 3 锚 trait 工件生成（送楠过目） | `data/traits/` | §5.11 |
| 预研件 | B1-12 | 云日 runbook 前置核对 | 本文 §7 | §5.12 |

### 0.2 阶段2 交付清单

| 编号 | 交付物 | 路径 | 任务卡 |
|---|---|---|---|
| B2-1 | models.py：HF mirror 下载 + revision 钉死 + 模板哈希 + 三样例逐字节检 | `src/abcr/rig/models.py` | §6.1 |
| B2-2 | hooks.py：response 位置注入 / 投影消融 | `src/abcr/rig/hooks.py` | §6.2 |
| B2-3 | interventions 三件：prompt_persona / residual_vector / controls | `src/abcr/rig/interventions/` | §6.3 |
| B2-4 | scorer deterministic_v1 完整版（golden10 + 8 类可验证指令） | `src/abcr/rig/scorer.py` | §6.4 |
| B2-5 | runner：config→前置检查→逐 item 逐 seed→step 落盘→幂等续跑 | `src/abcr/rig/runner.py` | §6.5 |
| B2-6 | 黄金测试四件 + 合成 2-step 轨迹测试 | `tests/rig/` | §6.6 |
| B2-7 | splits.py + ifeval_zh_v1 任务族 250 题 + hash 入 git | `src/abcr/rig/splits.py`、`data/benchmarks/` | §6.7 |
| B2-8 | 云生命周期：instance 登记入账本 + 完成即关机核验 | `src/abcr/ops/cloud.py`、`scripts/b_instance.py` | §6.8 |
| B2-9 | 表达检盲评实现 | `src/abcr/judge/blind_protocol.py` | §6.9 |
| B2-10 | n=50 双 judge 一致性抽样（DeepSeek + 本地 ollama gemma3） | `src/abcr/judge/consistency.py` | §6.10 |
| B2-11 | 翻转 demo 脚本 | `scripts/b_flip_demo.py` | §6.11 |
| B2-12 | 20 题 temp0 双引擎 parity 烟检 | `scripts/b_parity_smoke.py` | §6.12 |
| B2-13 | 云日 #1 执行（官方 trait 五阶段复现 + 翻转 demo） | 本文 §7.1 | §6.13 |
| B2-14 | 云日 #2 执行（3 锚 trait + 7B mini 环 + parity） | 本文 §7.2 | §6.13 |

### 0.3 你在 R1 回归门的判据项（fable 手跑演练，全链零人工——批准动作除外；R1 拆 R1-core/R1-full——AMENDMENT-30：fixture 闭环六步所需最小件 7/14 上午过 R1-core 门，B 的 watchdog 调优与预研件属 R1-full、R2 前齐）

1. `abcrctl approve fixtures/envelope_fixture.json`（C 的 CLI，人批）→ **你的 dispatch 消费该信封**：坏令牌拒绝（fail-closed，双留痕 = batches 链 `batch_dispatch_rejected` 事件 + 告警文件——AMENDMENT-13）、好令牌放行。
2. 信封展开为 6 个假 run（2 condition × 3 seed，benchmark=golden10，engine=fake）入队并逐一执行完毕。
3. 其中 1 个 run 注入 `crash_at_item` 故障 → 进程死 → 重跑 dispatch → **item 级断点续跑成功**，steps.jsonl 中无重复 (item_id, seed) 记录，最终 10/10 item 齐。
4. 心跳：每个 run 的账本中出现 `step_progress` 事件（每 5 item 一次，payload 含 steps_done/items_done）。
5. scorer 评分产出 scores.jsonl，与 `fixtures/expected_scores.jsonl` 完全一致（is_correct：8/10 题为 1，g03/g07 为 0）。
6. 账本事件序完整：`batch_dispatch_started → run_registered → run_queued → run_started → step_progress×2 → run_completed → run_scored`（×6 run）→ `batch_settled`；哈希链校验通过。
7. watchdog `--once` 能检出人为制造的停摆 run（hang 旋钮）并告警一次、冷却期内不重复告警。
8. `tests/contract/` 契约测试仍全绿；你的 `tests/ops/` 全绿。

### 0.4 你在 R2 回归门的判据项

1. **故障演练**（四演练中 B 责任的两项半）：杀 RUNNING 进程 → 恢复 + 对账续跑成功；faketask `skip_ledger_writes` 旋钮可用（A 的 auditor 据此演练拦截）；实例空转模拟数据（instances.jsonl 事件，payload 带 `actor="drill"`——AMENDMENT-17）可供 A 触发预算告警。
2. 黄金测试四件全绿：hook 注入检、已知答案检（golden10）、模板检（三样例逐字节）、双跑一致检；合成 2-step 轨迹测试通过。
3. ifeval_zh_v1 任务族 250 题定稿：每题自检通过（判分器对 pass_sample 判 1、fail_sample 判 0），split hash 入 git，W1 运行只碰 dev split。
4. 7B mini 环（50 题 × 3 臂 × 2–3 seed）从信封到审计报告全链走通（真实数据闭环）。
5. 云日 #1 完成：官方 trait 五阶段复现 + 对表校准判据满足 + 翻转 demo 产出。
6. 云日 #2 完成：≥1 个锚 trait 表达检方向清晰（效应量 + 逐题分布图在案）；n=50 双 judge 一致性抽样在案；20 题 temp0 parity 记录在案。
7. 预算：云实耗 ≤¥150，逐实例登记于 instances.jsonl/costs.jsonl；每个实例有「完成即关机」核验记录。
8. W1 出口门中 B 责任项：G1 可重复（temp0 双跑一致 + manifest 校验）、G3 配方校准、G4 首批向量、G6 预算。

---

## 1. 项目背景速览 + 术语表 + 否证标准 + 呈现纪律

**背景（≤12 行）**：ABCR 是楠的人格向量实验项目——一项 12 周研究，核心科学问题是：**文本人格提示对模型任务行为的效应，是否由可命名的内部方向（残差流中的线性方向）中介**。主线配方是 Persona Vectors 式残差差分向量：用正负人格系统提示词分别生成响应，取逐层响应 token 平均激活之差得到方向向量，再在推理时注入/消融该向量观察行为变化。W1（本期）目标是「最小纵向闭环」：一条真实实验链可重复运行——固定输入与模型 → baseline / 人格文本 / 残差干预三臂 → 逐步轨迹与激活摘要落盘 → 自动评分 → 独立复评一致 → 一键产出可复现实验包。在此之上，楠要求先建**实验控制面**（账本+队列+审批+审计）守住证据链有效性与预算：控制面先用假任务证明自己是对的（阶段1），再用真实验证明自己是有用的（阶段2）。你（B包）负责执行侧全部：假任务、队列、断点续跑、心跳、看门狗、云生命周期，以及科学载荷本身（rig、官方复现、trait 工件、judge、表达检、demo）。W1 的产出不是证据，是**产生证据的机器及其正确性证明**。

**术语表**（上位文档逐字）：**人格标签** = Big Five 等外部理论标签，仅用于对表文献；**行为控制原语** = 可测量、可干预并影响任务轨迹的内部方向或神经元集合（例：探索、验证、坚持、校准、质疑）；**自适应行为策略** = 按任务特征与历史反馈选择原语、方向、层和强度的路由策略。

**否证标准**（上位文档逐字；任一出现记**有效负结果**入账本，不得丢弃或重跑覆盖）：人格评分变化明显但能力变化在控制长度和格式后消失※；只有单个 benchmark、单个系数、单个模型有效；随机等范数方向产生同等增益；calibration 有增益 held-out 反转；动态路由不优于按 benchmark 固定人格（G1 后适用）；内部干预普遍不如文本提示；正负 steering 均只导致输出质量下降；量化模型有效而 BF16 不复现；LLM judge 喜欢 steered 输出但确定性准确率不变。※修正注（V1.3 M9）：长度不再作硬性条件化变量，改三段分解报告；硬性否证前提仅随机方向对照 / 流畅性 PPL / 格式遵循三项。

**呈现纪律**（逐字）：W1 一切数字带 `exploratory / rig-validation` 标注；mini 环产出不构成任何假设的证据；对外材料数字必须出自账本视图（三轨共享同一事实源）。QUARANTINED 批不删除、不采纳、不重跑覆盖——留证 + 人裁决。补充（W1 方案沿用）：未过五检（谱系/表达/词表/孪生/副作用）前一律称 **direction-k**，不称人格向量。

---

## 2. 铁律与边界

### 2.1 三条铁律（上位文档逐字，违者整体 revert）

1. 三包只通过稳定接口（账本文件 + 信封文件 + 契约库 API）通信，**禁止互相直接读写对方内部状态**；
2. 只在自己 worktree 内动归属矩阵分给自己的路径，不访问 shared-brain，网络白名单 = pypi / hf-mirror.com / api.deepseek.com / github.com 克隆 / registry.ollama.ai / modelscope.cn / 云实例 SSH（后三项系 AMENDMENT-26 增补）；
3. 每日收工写 `PROGRESS.md`，阻塞超 30 分钟记 BLOCKER 换任务，不钻兔子洞。

### 2.2 目录归属矩阵（全矩阵；**加粗 = 你（B）拥有**；`共`= fable 阶段0 交付后冻结，改动=契约修订）

```
abcr/
├── .env .gitignore requirements-mac.txt README.md        共
├── src/abcr/
│   ├── common/            共→维护权分置：ledger_ref.py(A) approval_token.py(C) constants.py(fable)
│   ├── ledger/            A（schema.py writer.py statemachine.py views.py）
│   ├── audit/             A（auditor.py rescore.py contamination.py health.py budget_recon.py）
│   ├── sandboxing/        A（profiles.py drills/）
│   ├── ops/               **B（faketask.py queue.py dispatch.py runstate.py heartbeat.py watchdog.py cloud.py）**
│   ├── rig/               **B（models.py hooks.py interventions/ scorer.py runner.py splits.py）**
│   ├── judge/             **B（deepseek_client.py blind_protocol.py consistency.py）**
│   ├── governor/          C（envelope.py planner.py triage.py）
│   ├── report/            C（views.py sync.py repro_pack.py weekly.py）
│   └── notify.py          C
├── scripts/               前缀归属：a_*.py(A) **b_*.py(B)** c_*.py(C)；abcrctl(C)
├── configs/
│   ├── models/ experiments/ benchmarks/                  **B**
│   └── envelopes/                                        C
├── data/
│   ├── golden/golden10.json                              共（冻结）
│   ├── benchmarks/ splits/ traits/                       **B（定稿即冻结入 git）**
│   ├── vectors/                                          **B（向量产物落位，非冻结区——AMENDMENT-27）**
│   └── runs/                                             运行时（gitignore）
├── fixtures/              共（阶段0 交付：信封样例+假任务定义+期望分数+测试密钥）
├── ledger/ queue/ state/ plans/                          运行时（gitignore）
├── reports/ demos/                                       产物（入 git 可选；命名分区 AMENDMENT-31：B 写 b_*、flip_demo_*、cloud/；C 写 sync-/triage-/weekly/repro-*）
├── tests/
│   ├── contract/          共（三包必须保持全绿）
│   ├── ledger/ audit/ drills/                            A
│   ├── ops/ rig/ judge/                                  **B**
│   └── governor/ report/                                 C
└── PROGRESS.md            各 worktree 自己的（不合并）
```

### 2.3 权限矩阵（上位文档逐字）

| 路径/对象 | rig(B) | Operator(B) | Governor(C) | Auditor(A) | 人 |
|---|---|---|---|---|---|
| data/golden、data/splits、data/traits（冻结区） | 只读 | 只读 | 只读 | 只读 | 唯一写入者（经 B 起草、定稿仪式冻结） |
| data/runs/*/steps.jsonl、scores.jsonl | 追加(steps) / 追加(scorer 的 scores) | 只读 | 只读 | 追加(rescore 的 scores) | 只读 |
| ledger/*.jsonl（runs_index/batches/costs/instances） | 经账本 API 追加 | 经账本 API 追加 | 只读 | 追加(审计事件) | 只读 |
| queue/ | — | 读写 | 只读 | 只读 | 读写 |
| configs/envelopes/、plans/ | — | 只读 | 读写（草案） | 只读 | 审批签名 |
| state/（各包私有内部状态） | 各归属者私有 | 同 | 同 | 同 | — |

例外（AMENDMENT-18）：`state/alerts/*.json` 升格为**告警文件接口**（豁免"私有黑箱"铁律）——B 写、A/C 只读；文件名 `<ts>-<kind>.json`，JSON 至少含 `{ts, kind, severity(A/B/C), subject_id, reason}`。

注意：`data/traits`、`data/splits` 你**起草**（写入草稿），但**定稿冻结动作在人**（楠/fable 跑定稿仪式）。定稿前你可改；定稿后即冻结区，只读。

### 2.4 明确禁止清单

- **不做复评**（rescore 是 A 的；你的 scorer 与 A 的 rescore 是有意双实现，对冲同源 bug）。
- **不做审计**（auditor 六项全是 A 的）。
- **不起草信封、不实现审批令牌签发**（envelope.py/approval_token.py/abcrctl 是 C 的；你只**调用** `common/approval_token` 的 verify 接口）。
- **不做同步视图/报告/界面**（C 的）。
- 不修改 `src/abcr/common/`、`fixtures/`、`tests/contract/`、`data/golden/`（冻结/他人维护；发现问题走 PROGRESS 契约疑议）。
- 不访问 shared-brain；不越网络白名单（不装 gh、不建远端、不 push）。
- 不用 ollama 跑 rig 主链（ollama 不暴露激活；它只在 B2-10 里当第二家族 judge）。
- 不把任何 API key 明文写入仓库文件或本文档产物（key 只活在 `.env`，gitignored）。
- Judge 禁用 Qwen 家族（DASHSCOPE 禁用）——被试是 Qwen，judge 必须异构。

---

## 3. 冻结契约摘录（阶段0 冻结，逐字嵌入；修订权在 fable）

以下为你的包需要的契约全文。**kickoff 交付的 `src/abcr/common/` 三个文件与 `tests/contract/` 是权威参考实现**——本节给协议语义，函数具体签名以仓库文件为准（那些文件你拿得到、允许读、禁止改）。

### 3.1 账本（单一事实源）：文件、事件词表、哈希链（契约 §2.3 逐字）

`ledger/` 下五个 append-only JSONL（第五链 protocol.jsonl 系 AMENDMENT-7 增补），全部走哈希链（协议见 §3.5），**只能经 `src/abcr/common/ledger_ref.py` 的 API 写入**（并发写互斥见 AMENDMENT-15：ledger_ref.append 对 `<chain>.jsonl.lock` 持 fcntl.flock(LOCK_EX)，锁内重读链尾再写——全局链放弃链尾内存缓存；`data/runs/<id>/steps.jsonl` 单写者，保留缓存）：

- `runs_index.jsonl` —— run 生命周期事件。事件词表（枚举冻结）：`run_registered, run_queued, run_started, step_progress, run_paused, run_resumed, run_failed, run_completed, run_scored, run_audited, run_accepted, run_quarantined, run_cancelled`。`step_progress` 由 B 每完成 N=5 个 item 追加一次（payload 含 steps_done/items_done），**这就是进度心跳**——"在岗"的唯一定义是账本 step 推进（治"进程活着工作流停摆"）。`run_registered` 事件 payload 必含 `batch_id` 辅助键（run↔batch 关联的账本通道——AMENDMENT-19）。
- `batches.jsonl` —— 批次事件：`batch_drafted, batch_approved, batch_rejected, batch_dispatch_rejected, batch_dispatch_started, batch_settled, batch_audited, batch_reported`。语义（AMENDMENT-13 裁决，取代 AMENDMENT-1 初版）：`batch_rejected` = 人工驳回，abcrctl 落账；`batch_dispatch_rejected` = 令牌校验失败或信封越界被 dispatch 拒绝，**B 落账**，payload 带原因码 + subject_id=batch_id。
- `protocol.jsonl` —— 协议对象冻结事件：`artifact_frozen, artifact_superseded`（AMENDMENT-7 第五链；写者是定稿仪式/A 域，B 不写）。
- `costs.jsonl` —— `run_cost_estimated, run_cost_actual, budget_alert`。costs 事件 payload 必含 `{subject_id, amount_cny, basis}` + `batch_id` 辅助键（AMENDMENT-9/28①）。
- `instances.jsonl` —— `instance_registered, instance_started, instance_stopped, instance_idle_alert`（供应商、规格、时价、关联批次）。instances 事件 payload 必含 `{instance_id, vendor, spec, price_cny_per_h, batch_id}`（AMENDMENT-9）。

**payload 主体键约定（AMENDMENT-4）**：全局账本文件（runs_index/batches/costs/instances）中事件主体用 `subject_id` 键（run 事件填 run_id 值、batch 事件填 batch_id 值）——因 RunLedger.append 的保留键限制，payload 不得再用 run_id/batch_id 作键名者改用 `subject_id` + 辅助键。

### 3.2 三层状态机（A 实现迁移守卫；B 看门狗做全局对账）（契约 §2.4 逐字）

- **协议对象**：`DRAFT → REVIEW → FROZEN →（AMENDMENT→新版本）→ SUPERSEDED`。W1 冻结对象 = golden10、splits、traits、黄金判据；冻结动作 = 人（楠或 fable 代）跑定稿仪式（git tag + 哈希入账 + 阶段2 起 Seatbelt 只读）。
- **批次对象**：`DRAFT → APPROVED → DISPATCHING → SETTLED → AUDITED → REPORTED`。APPROVED 必须携带有效审批令牌（§3.4）。
- **运行对象**：`PLANNED → QUEUED → RUNNING → {PAUSED, FAILED} → COMPLETED → SCORED → AUDITED → {ACCEPTED, REJECTED, QUARANTINED}`；终态另有 `CANCELLED`；FAILED 可 RESUME 回 RUNNING。
- **TTL 表（秒，constants.py 冻结，env 可覆盖）**：QUEUED 3600；RUNNING 心跳间隔上限 1800（零新 step_progress 即停摆告警）；COMPLETED→SCORED 7200；SCORED→AUDITED 7200。看门狗每周期对账"账本状态 vs 进程表 vs（阶段2）云实例清单"，超时转异常并告警——任何长活状态无活体证据即异常，绝不允许幽灵状态滞留。

### 3.3 step 与 scores 记录 schema v1（契约 §2.5 逐字，48 字段全表）

**steps.jsonl**（每行一条，append-only + 哈希链）：

| # | 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|---|
| 1 | schema_version | str | 否 | 恒 "1.0" |
| 2 | run_id | str | 否 | §3.6 规则 |
| 3 | trajectory_id | str | 否 | 单轮任务 = 长度 1 轨迹 |
| 4 | step_id | int | 否 | 轨迹内 0 起递增 |
| 5 | parent_run | str | 是 | 续跑/派生指向源 run |
| 6 | git_commit | str | 否 | 启动时 HEAD |
| 7 | model_id | str | 否 | 假任务用 "fake/deterministic-v1" |
| 8 | model_revision | str | 否 | HF commit hash；假任务 "fixture" |
| 9 | dtype | str | 否 | bfloat16 / none |
| 10 | quantization | str | 是 | |
| 11 | device | str | 否 | mps / cuda:0 / cpu / none |
| 12 | engine | str | 否 | transformers / vllm / fake |
| 13 | engine_version | str | 否 | |
| 14 | torch_version | str | 是 | 假任务 null |
| 15 | cuda_version | str | 是 | Mac null |
| 16 | benchmark | str | 否 | 任务族 id，如 ifeval_zh_v1 / golden10 |
| 17 | split_hash | str | 否 | §3.5 |
| 18 | item_id | str | 否 | |
| 19 | condition | str | 否 | 枚举：vanilla / persona_text / neutral_token / length_instruct / inject / ablate / inject_random / ablate_random / synthetic_test / fake |
| 20 | trait | str | 是 | 干预臂必填 |
| 21 | trait_pole | str | 是 | pos / neg |
| 22 | method | str | 是 | prompt / residual_inject / residual_ablate |
| 23 | layer | int | 是 | |
| 24 | coefficient | float | 是 | |
| 25 | intervention_strength | float | 是 | W1 = coefficient |
| 26 | random_seed | int | 否 | |
| 27 | env_seed | int | 是 | 多轮用 |
| 28 | prompt_hash | str | 否 | sha256(最终渲染 prompt) |
| 29 | chat_template_hash | str | 否 | §3.5；假任务 "fixture" |
| 30 | config_hash | str | 否 | §3.6 |
| 31 | action | str | 是 | W1 单轮 "generate" |
| 32 | obs_hash | str | 是 | 多轮用 |
| 33 | remaining_budget | float | 是 | 多轮用 |
| 34 | output_text | str | 否 | 原始输出全文；铁律：不得只存汇总分 |
| 35 | parsed_answer | str | 是 | 解析失败 null 且 safety_flags 记 parse_fail |
| 36 | is_correct | bool | 是 | 生成时可 null；权威值在 scores |
| 37 | latency_ms | int | 否 | |
| 38 | input_tokens | int | 否 | |
| 39 | output_tokens | int | 否 | |
| 40 | stop_reason | str | 否 | eos / max_tokens / error / fake |
| 41 | trajectory_stop_reason | str | 是 | task_done / budget_exhausted / max_steps / error；中间步 null |
| 42 | trait_score | float | 是 | steps 内恒 null |
| 43 | fluency_score | float | 是 | steps 内恒 null |
| 44 | safety_flags | list[str] | 否 | 默认 []；parse_fail/truncated/empty/refusal/repetition |
| 45 | activation_summary | str | 是 | 摘要文件相对路径（§3.7 抽样）|
| 46 | state_snapshot_ref | str | 是 | 合成轨迹测试须演示非 null 写读 |
| 47 | protocol_ref | str | 否 | W1 = "W1-V0.9" |
| 48 | env_lock_ref | str | 否 | lockfile 相对路径 |

**scores.jsonl**（评分是独立 pass，可多 scorer 多次追加）：`schema_version, run_id, item_id, trajectory_id, step_id, condition, random_seed, metric_name, metric_value, scorer_id, scorer_version, scored_at`。metric_name 枚举：`is_correct / trait_score / coherence_score / fluency_score / output_len_chars / output_len_tokens / hedging_rate / self_check_marker_rate / parse_ok`。**manipulation-check 指标与能力指标分列**（"行为动了但能力没动本身是发现"）。scorer_id：`deterministic_v1`（B，rig 侧）、`judge_deepseek_v1`（B）、`rescore_v1`（A，独立复评）——B 与 A 对确定性指标是**有意双实现**，对冲同源 bug；两者都必须过黄金十题（§3.8）。

### 3.4 批次信封与审批令牌（契约 §2.6 逐字；你只做 verify 一侧）

**信封文件** `configs/envelopes/<batch_id>.json`：

```json
{
  "envelope_version": "1.0",
  "batch_id": "B-<UTC:%Y%m%dT%H%M%SZ>-<4位序号>",
  "protocol_ref": "W1-V0.9",
  "scope": {
    "benchmark_families": ["ifeval_zh_v1"],
    "conditions": ["vanilla", "persona_text", "inject"],
    "splits": ["dev"],
    "item_limit_per_run": 50,
    "seeds": [1, 2],
    "trait_whitelist": ["conscientiousness"]
  },
  "budget": {"gpu_hours_max": 4.0, "cost_cap_cny": 60.0},
  "deadline_utc": "...",
  "run_configs": ["configs/experiments/xxx.json", "..."],
  "drafted_by": "governor-rules-v1 | human",
  "approval": {"token": {"...": "见下"}, "approved_at": "..."}
}
```

**审批令牌**：HMAC-SHA256，纯 stdlib（canonical 实现在 `src/abcr/common/approval_token.py`，C 维护，你只调用）。载荷字段 `(token_id, scope, task_id→batch_id, changeset_sha256→envelope_sha256, expires_at, persona_change→false)`，序列化口径 `json.dumps(core, ensure_ascii=False, sort_keys=True)`；envelope_sha256 = 对信封去 approval 字段后的规范化 JSON（§3.5 同式）取 sha256。**签发权在人**：密钥 `state/approval.key`（32 字节，0600）；人跑 `abcrctl approve <envelope>` 签发；**B 的 dispatch 只接受 verify 通过的信封（校验顺序：结构→scope→恒时比较签名→envelope 哈希→过期→已消费；fail-closed）**；批次 SETTLED 后才 consume。**已结批次短路（AMENDMENT-23）**：dispatch 对已 `batch_settled` 的信封先查账本，命中打印 already-settled 并**退出 0**、零新事件、不触碰令牌——此检查在令牌校验之前（否则"已消费"会把合法重跑拒成退出码 2）。信封外任何一维（超预算、越 split、加臂）自动升协议级 = 拒绝执行 + 记账 + 告警。**确认期批次的"发射"永久保留人手，W1 全部批次实际上都由人批准。** fixture 用 `fixtures/test_approval.key`。

### 3.5 哈希协议（全项目统一）（契约 §2.7 逐字）

- **账本哈希链**：`GENESIS_HASH="0"*64`；`entry_hash = sha256(json.dumps(含prev_hash不含entry_hash的本条, ensure_ascii=False, sort_keys=True).encode() + prev_hash.encode())`；append 后 flush+fsync；每文件一条链、单写者进程（**并发写者必须经队列串行化——这是 Operator 的职责之一**）。
- **code_tree_hash**：对 `src/ scripts/ configs/ data/traits data/golden data/benchmarks data/splits` 逐文件 sha256（exts = .py .json .md .yaml .txt，排除 `__pycache__ .git .venv`），`sha256(json.dumps(树, sort_keys=True))`。
- **chat_template_hash**：`sha256(tokenizer.chat_template.encode())` + 三条钉死样例逐字节比对（样例见本文 §6.1）。
- **split_hash**：`sha256("\n".join(sorted(f"{item_id}\t{split}")).encode())`。切分：`int(sha256(f"{family}:{item_id}:abcr-w1-v1".encode()).hexdigest()[:8],16)%100`；<20 dev，<60 calibration，其余 holdout。salt `abcr-w1-v1` 为协议常量。
- **prompt_hash / obs_hash / envelope_sha256 / config_hash**：sha256(UTF-8 字节)，JSON 一律 `ensure_ascii=False, sort_keys=True, separators=(",", ":")` 规范化。

### 3.6 config 与 run_id（契约 §2.8 逐字 + 本包补全 config 格式）

契约原文：run config 单 JSON，必含 model/benchmark/condition/decoding/steering_position/protocol_ref。`config_hash = sha256(规范化 JSON)`；`run_id = f"{batch_id时间戳段}-{config_hash[:12]}"`（AMENDMENT-22：时间戳取信封 batch_id 内嵌时间戳——**确定性**，同信封同 config 恒同 run_id，这是 dispatch 幂等的根基；仅无信封的 `--dev` 裸跑用当刻 UTC。信封内 run_configs 的 config_hash 必须唯一，dispatch 发现重复即拒）。启动前置检查（不过拒跑）：git clean（否则仅 `--dev` 且 manifest 打 `non_citable:true`）；model_revision / chat_template_hash / split_hash 与冻结清单逐项一致。

run 产物布局：`data/runs/<run_id>/{manifest.json, steps.jsonl, scores.jsonl, activations/, logs/}`。manifest 必含（**显式计数 22 键——AMENDMENT-31**；engine/engine_version、started_at/finished_at 各计两键）：run_id、config 全文内嵌、config_hash、git_commit、git_clean、code_tree_hash、model_id、model_revision、chat_template_hash、split_hash、engine、engine_version、torch_version、python_version、env_lock_ref、seeds、started_at、finished_at、status、non_citable、protocol_ref、batch_id。A 审计 item1 按 22/22 计数核验。

**run config 格式（B 包定义权，此处定稿）**：

```json
{
  "config_version": "1.0",
  "protocol_ref": "W1-V0.9",
  "model": {
    "model_id": "Qwen/Qwen2.5-7B-Instruct",
    "revision": "<HF commit hash，首次下载后钉入 configs/models/>",
    "dtype": "bfloat16",
    "device": "cuda:0",
    "engine": "transformers"
  },
  "benchmark": {"family": "ifeval_zh_v1", "split": "dev", "item_limit": 50},
  "condition": "inject",
  "intervention": {
    "method": "residual_inject",
    "trait": "conscientiousness",
    "trait_pole": "pos",
    "vector_path": "data/vectors/conscientiousness_response_avg_diff.pt",
    "layer": 20,
    "coefficient": 2.0,
    "steering_position": "response"
  },
  "decoding": {"temperature": 0.7, "max_new_tokens": 512, "seeds": [1, 2]},
  "batch_id": "B-20260716T020000Z-0001"
}
```

约定：`condition=vanilla` 时 `intervention` 为 `null`；`condition=persona_text` 时 `intervention.method="prompt"` 且 `vector_path/layer/coefficient` 为 null；`inject_random/ablate_random` 时 `vector_path` 指向 controls 生成的随机方向文件。`vector_path` 一律指向 `data/vectors/`（B 拥有的非冻结区——AMENDMENT-27；`data/traits/` 只存 trait 工件 JSON，冻结）。engine=fake 的假任务 config 以 `fixtures/` 内实际文件为准。**seed 制（AMENDMENT-29）**：`decoding.seeds` 在 **run 内循环**（mini 环 = 3 config = 3 run，steps 内以 random_seed 区分）；阶段1 fixture 的"每 seed 一 run"是 fixture 特例，不代表真实批次口径。

### 3.7 激活存储策略（契约 §2.9 逐字）

全量激活不落盘。只存：① 抽取语料分层均值激活（B，官方流水线自产）；② 评测运行中按 item_id 哈希尾数确定性抽样 10% 题目的逐响应 token 在 v_p 上的投影标量序列 + 分层统计摘要（mean/P50/P90），存 `activations/<item_id>_<seed>.npz`。合成向量阶段同样走通此通路。抽样规则（本包定稿）：`int(hashlib.sha256(item_id.encode()).hexdigest()[-1], 16) < 2`（尾 hex 位 <2，约 12.5%≈10%）。

### 3.8 黄金十题（契约 §2.10 逐字；已冻结于 `data/golden/golden10.json`）

判分语义精确定义（B 的 scorer 与 A 的 rescore 独立实现；10 题 pass_sample 判 1、fail_sample 判 0 全对才过门）：

| id | prompt | 判分规则 |
|---|---|---|
| g01 | 请用恰好三行回答，每行以"- "开头，分别用一句话介绍红、黄、蓝三种颜色。 | strip 后按 \n 切分 == 3 行且每行 startswith("- ") |
| g02 | 计算 17×23，只输出数字。 | strip 后 == "391" |
| g03 | 输出单词 hello 重复 5 次，用英文逗号分隔，不加任何其他内容。 | strip 后 == "hello,hello,hello,hello,hello" |
| g04 | 谈谈实验记录的重要性，回答中必须包含词语"可复现"至少两次。 | output_text.count("可复现") >= 2 |
| g05 | 以 JSON 对象输出，仅含键 a 和 b，值分别为整数 1 和 2。 | 剥 ```json 围栏后 json.loads == {"a":1,"b":2} |
| g06 | 只输出英文大写字母表的前五个字母，不加分隔与其他内容。 | strip 后 == "ABCDE" |
| g07 | "实验"一词在下句中出现几次？只输出数字："实验是科学的基础，好的实验需要设计，实验记录要完整。" | strip 后 == "3" |
| g08 | 将字符串 abcr 逆序输出，只输出结果。 | strip 后 == "rcba" |
| g09 | 地球的天然卫星是什么？A. 月球 B. 太阳 C. 火星。只输出选项字母。 | strip 后取首字符 == "A" |
| g10 | 输出一句不超过 20 个字的话，必须以"数据"开头、以"。"结尾。 | strip 后 startswith("数据") 且 endswith("。") 且 len<=20 |

### 3.9 hook 正确性判据（契约 §2.11 逐字，bf16 容差）

- **注入检**：固定 seed 随机向量（`torch.manual_seed(42); v=randn(hidden)` 单位化），c=4.0，3B 取 layer 18。base vs steered 前向在注入位置的 hidden delta（cast fp32）：`cos(delta, v) > 0.99` 且 `|delta|/(c·|v|) ∈ [0.95, 1.05]`。
- **消融检**：`|proj_after|/|proj_before| < 0.02`（proj_before < 1e-3 时直接判 |proj_after| < 1e-3）。
- **双跑一致检**：同 config temp=0 连跑两遍逐题 output_text 与判分一致。
- **注入位置**：response tokens（生成每步最后位置 + prefill 最后 prompt token），与官方 `--steering_type response` 一致。

### 3.10 fixture（契约 §2.12 逐字；阶段1 三包共同的靶）

`fixtures/` 内容：① `envelope_fixture.json`——一个含 6 个假 run config 的信封（2 condition × 3 seed，benchmark=golden10，engine=fake）+ 用 `test_approval.key` 预签的有效令牌；①′ `envelope_fixture_badtoken.json`——坏令牌样例（**独立文件**，文件名系 AMENDMENT-12 冻结）；② `faketask_spec.md`——确定性假任务定义：对 item_id=gXX 输出 golden10 的 pass_sample（其中 g03/g07 输出 fail_sample，制造已知错误分布），每 item 耗时 0.2s，暴露故障旋钮环境变量（名称已冻结——AMENDMENT-3）：`ABCR_FAKETASK_CRASH_AT_ITEM / ABCR_FAKETASK_HANG_AT_ITEM / ABCR_FAKETASK_SKIP_LEDGER_WRITES / ABCR_FAKETASK_EXIT_WITHOUT_DONE`；golden10.json 顶层结构冻结为 `{"schema_version":"1.0","items":[{id,prompt,rule,pass_sample,fail_sample}×10]}`（AMENDMENT-3）；③ `expected_scores.jsonl`——该信封跑完后确定性期望分数（is_correct 8/10 题为 1）；④ `test_approval.key`。契约测试 `tests/contract/`：schema 校验器接受 fixture 全部记录、拒绝 12 个变异样本；令牌正样验证通过、坏令牌六种失败路径各返回正确原因码；哈希链断链检测；状态机非法迁移拒绝。

---

## 4. 环境与启动

### 4.1 环境事实（已实测写死，不再探测）

| 项 | 值 | 你的动作 |
|---|---|---|
| 硬件 | Mac mini M4 16GB，数据卷余 122Gi | 3B bf16 本机可跑（dev 干跑）；7B 一律云卡 |
| Python | 默认 python3=3.14.6（勿用）；uv 0.11.3 已装，缓存 CPython 3.12.13 | venv 已由 kickoff 建好（`uv venv --python 3.12`），你只激活 |
| HF 访问 | huggingface.co 直连超时；hf-mirror.com HTTP 200 | 一切 HF 下载必须 `HF_ENDPOINT=https://hf-mirror.com`（.env 已含） |
| DeepSeek | `https://api.deepseek.com` 可达（未鉴权返回 401 属预期）；key 已在 `.env` | judge 走 OpenAI 兼容端点 |
| ollama | 0.23.4 已装，本地有 qwen3:8b 等 | 仅 B2-10 第二家族 judge 用（需 `ollama pull gemma3`）；rig 不用 |
| git | 2.53.0；repo 级身份已设（abcr/abcr@local）；无远端不 push | 正常 commit 到 pkg/b |
| MPS | torch MPS 可用（Mac 开发路径）；数值有怪癖 | Mac 结果一律 non-citable；hook 检假红时移云上 CUDA 复验 |

### 4.2 `.env` 字段含义（kickoff 已注入；勿 commit、勿打印值）

| 字段 | 含义 |
|---|---|
| `DEEPSEEK_API_KEY` | judge 主 key（35 字符）。你的 `judge/deepseek_client.py` 读它 |
| `OPENAI_API_KEY` | 同一 DeepSeek key 的副本。供 vendor 官方仓库 judge **零代码改道**（官方 judge.py 用 AsyncOpenAI() 零参构造，从环境读此变量） |
| `OPENAI_BASE_URL` | `https://api.deepseek.com`（官方 judge 改道的另一半） |
| `HF_ENDPOINT` | `https://hf-mirror.com`（huggingface_hub 与 hf CLI 均识别） |
| `ABCR_STATE_DIR` | 运行状态根，默认 `state/`（相对仓库根） |
| `AUDITOR_FEISHU_APP_ID/SECRET` | C 包阶段3 用，你不碰 |

### 4.3 环境自检命令序列（开工第一天逐条跑，全部通过才开始任务卡）

```bash
cd /Users/superagent/abcr-wt/b
git branch --show-current                 # 预期输出: pkg/b
source /Users/superagent/abcr/.venv/bin/activate
python -V                                 # 预期: Python 3.12.x
python -c "import torch; print(torch.__version__, 'mps=', torch.backends.mps.is_available())"
python -c "import transformers, openai, duckdb, pytest; print('deps ok')"
test -f /Users/superagent/abcr-wt/b/.env && echo "env ok"   # .env gitignored 不随 worktree 检出；缺失则：cp /Users/superagent/abcr/.env /Users/superagent/abcr-wt/b/.env
python -c "import dotenv; print('dotenv ok')"               # python-dotenv 可导入（B1-10 依赖）
PYTHONPATH=src python -c "import abcr.common.ledger_ref, abcr.common.approval_token, abcr.common.constants; print('contract libs ok')"
PYTHONPATH=src pytest tests/contract -q   # 预期: 全绿（若红，先报 BLOCKER，不动 contract）
curl -sI https://hf-mirror.com | head -1  # 预期: HTTP/2 200
curl -s -o /dev/null -w "%{http_code}\n" https://api.deepseek.com   # 预期: 401（可达）
```

**重要**：三 worktree 共享主仓 `.venv`。**永远用 `PYTHONPATH=src` 方式运行/测试，禁止 `pip install -e .`**——editable 安装会把 `abcr` 包钉死到某一个 worktree 的路径，三窗口互相污染（详见 §10 坑 K1）。

开工第二件事：**通读 `src/abcr/common/ledger_ref.py` 与 `src/abcr/common/approval_token.py` 与 `src/abcr/common/constants.py` 全文**（就在你仓库里）。本文档所有对这两个 API 的调用形态是按契约语义写的示意；**真实函数名/签名以这两个文件为准**，不一致时以文件为准并在 PROGRESS.md 记一行。

### 4.4 账本 API 调用形态（按契约语义示意；以 ledger_ref.py 实际签名为准）

```python
# 哈希链 append-only 写入（协议 §3.5）。ledger_ref 是权威实现，B 全部账本写入经它。
from pathlib import Path
from abcr.common.ledger_ref import RunLedger   # 类名以文件为准；模式如下

led = RunLedger(Path("ledger"), "runs_index")  # 每文件一条链
# ⚠️ payload 主体键一律 subject_id（AMENDMENT-4）：run_id 是 append() 的保留键，payload 用它会撞保留键校验
led.append("run_started", subject_id=run_id, batch_id=batch_id)      # 自动挂链+fsync；batch_id 为辅助键
led.append("step_progress", subject_id=run_id, steps_done=5, items_done=5)
led.verify_chain()                              # 断链即 raise（含断链下标）
```

写入纪律（三条，照做）：① **事件幂等**——写开局类事件前先扫已有事件集合，重复驱动不重复落；② **fail-safe**——账本写失败不允许静默吞掉（与 V2 不同：这里账本是主链路证据，写失败 = run 失败，立即 mark_suspended 并报错）；③ **无 subject_id 不写**（run 事件填 run_id 值、batch 事件填 batch_id 值——AMENDMENT-4）。

---
## 5. 阶段1 任务卡

推荐顺序：B1-3(runstate) → B1-1(faketask) → B1-2(queue) → B1-4(heartbeat) → B1-6(scorer v0) → B1-5(dispatch) → B1-7(watchdog) → B1-8(联调)。**R1 拆分（AMENDMENT-30）**：R1-core（7/14 上午过门）只验 fixture 闭环六步最小件——B 侧 = faketask + queue + dispatch + runstate + heartbeat（B1-6/B1-8 支撑闭环自证一并就绪）；watchdog 调优与预研件属 R1-full，R2 前齐。预研件 B1-9~B1-12（judge 冒烟 / trait 工件 / runbook 初稿）**排 R1-core 过门后、云日前的窗口执行**（AMENDMENT-30），不再指望阶段1 内穿插——阶段1 全是本地假任务，并无等待时段。阶段1（R1-core 件）预算 ≈ 3.5–4.5 个工作日（4h/日）；R1-full 件另计。

### B1-1 faketask.py —— 确定性假任务执行器（2h）

**目标**：实现契约 §3.10 的假任务规格：对 item gXX 输出 golden10 的 pass_sample（g03/g07 输出 fail_sample），每 item 0.2s，四个故障旋钮经环境变量注入。它是阶段1 全链的"假模型"，也是阶段2 故障演练的注入器。

**实施要点**：旋钮环境变量名**已冻结（AMENDMENT-3）**：`ABCR_FAKETASK_CRASH_AT_ITEM / ABCR_FAKETASK_HANG_AT_ITEM / ABCR_FAKETASK_SKIP_LEDGER_WRITES / ABCR_FAKETASK_EXIT_WITHOUT_DONE`——即下面代码所用拼写，无待定分支。golden10.json 顶层结构同批冻结（AMENDMENT-3）：`{"schema_version":"1.0","items":[{id,prompt,rule,pass_sample,fail_sample}×10]}`，与下面代码的 `_load_golden` 假设一致。**CRASH_AT_ITEM 语义 = 进程即死（AMENDMENT-24）**：`os._exit(1)`，dispatch 不捕获——真实崩溃语义，恢复靠下次 dispatch 的启动对账（B1-5 步骤4）。**续跑去重以 steps 为准（AMENDMENT-25）**：resume 驱动前由 dispatch 读该 run 已有 steps.jsonl 的 (item_id, random_seed) 集合，命中者跳过 emit_step、只补 mark_item_done——kill -9 落在 emit_step 与 mark_item_done 之间也不会产生重复 (item,seed) step。

```python
"""abcr.ops.faketask — 确定性假任务执行器（契约 §2.12 规格）。

架构位置：Operator(B) 的执行器插槽中 engine=fake 的实现；阶段1 用它打通
信封→队列→执行→评分→审计全链，阶段2 保留作故障演练注入器。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

GOLDEN_PATH = Path("data/golden/golden10.json")
FAIL_ITEMS = frozenset({"g03", "g07"})   # 制造已知错误分布（契约 §2.12）
ITEM_SECONDS = 0.2


def _knob(name: str) -> str | None:
    v = os.environ.get(name, "").strip()
    return v or None


def _load_golden() -> dict[str, dict]:
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) else data
    return {r["id"]: r for r in items}


def generate(item_id: str) -> str:
    """单 item 确定性输出（无任何随机性；seed 不影响 fake 输出——期望分数才可预生成）。"""
    rec = _load_golden()[item_id]
    return rec["fail_sample"] if item_id in FAIL_ITEMS else rec["pass_sample"]


def run_items(
    item_ids: list[str],
    emit_step: Callable[[str, str], None],
    mark_done: Callable[[str], None],
) -> None:
    """逐 item 执行。emit_step(item_id, output_text) 写 steps.jsonl（由调用方 dispatch 注入，
    含 48 字段组装）；mark_done(item_id) 落 runstate 断点。

    故障旋钮（环境变量，值 = item_id 或 "1"；名称冻结——AMENDMENT-3）：
      ABCR_FAKETASK_CRASH_AT_ITEM   到该 item 时进程即死 os._exit(1)（AMENDMENT-24；崩溃演练→断点续跑）
      ABCR_FAKETASK_HANG_AT_ITEM    到该 item 时永久挂起（停摆演练→watchdog STALLED）
      ABCR_FAKETASK_SKIP_LEDGER_WRITES  =1 时不写 step（伪报完成演练→A 审计拦截）
      ABCR_FAKETASK_EXIT_WITHOUT_DONE   =1 时写完首个 step 后直接 os._exit(0)（幽灵状态演练）
    """
    crash_at = _knob("ABCR_FAKETASK_CRASH_AT_ITEM")
    hang_at = _knob("ABCR_FAKETASK_HANG_AT_ITEM")
    skip_ledger = _knob("ABCR_FAKETASK_SKIP_LEDGER_WRITES")
    exit_wo_done = _knob("ABCR_FAKETASK_EXIT_WITHOUT_DONE")
    for item_id in item_ids:
        if crash_at == item_id:
            print(f"[faketask] injected crash at {item_id}", file=sys.stderr, flush=True)
            os._exit(1)   # 进程即死（AMENDMENT-24）：dispatch 无从捕获——真实崩溃语义，恢复走启动对账
        if hang_at == item_id:
            while True:                      # 停摆：进程活着，工作流死了
                time.sleep(60)
        time.sleep(ITEM_SECONDS)
        out = generate(item_id)
        if not skip_ledger:
            emit_step(item_id, out)
        if exit_wo_done:
            os._exit(0)                      # 不落 done、不 settle——幽灵 RUNNING
        mark_done(item_id)
```

**验收命令与预期输出**：

```bash
cd /Users/superagent/abcr-wt/b && source /Users/superagent/abcr/.venv/bin/activate
PYTHONPATH=src python -c "
from abcr.ops.faketask import generate
print(repr(generate('g02')))    # pass_sample，应可判 1
print(repr(generate('g03')))    # fail_sample，应可判 0
"
PYTHONPATH=src pytest tests/ops/test_faketask.py -q   # 你自写的测试：旋钮四路 + 确定性
```

### B1-2 queue.py —— 目录式运行队列（2h）

**目标**：`queue/pending → running → done|failed` 四目录，run 文件（`<run_id>.json`，内容=run config + batch_id）经 **os.rename 原子改名**流转。认领语义：rename 成功=认领成功；竞争者拿 FileNotFoundError=认领失败跳过。

```python
"""abcr.ops.queue — 目录式运行队列（契约 §2.1 queue/ 归 Operator 读写）。

架构位置：dispatch 与执行器之间的持久化缓冲；同时是并发写账本的串行化闸
（账本哈希链单写者假设靠"同一时刻只有一个 dispatch 进程消费队列"保证）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

QUEUE_ROOT = Path("queue")
STATES = ("pending", "running", "done", "failed")


def init_dirs() -> None:
    for s in STATES:
        (QUEUE_ROOT / s).mkdir(parents=True, exist_ok=True)


def enqueue(run_id: str, payload: dict) -> Path:
    """写 tmp 再同目录 rename 发布——读者永远看不到半写文件。幂等：已存在即跳过。"""
    init_dirs()
    dst = QUEUE_ROOT / "pending" / f"{run_id}.json"
    if dst.exists() or _in_any_state(run_id):
        return dst
    tmp = QUEUE_ROOT / "pending" / f".{run_id}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(dst)
    return dst


def _in_any_state(run_id: str) -> bool:
    return any((QUEUE_ROOT / s / f"{run_id}.json").exists() for s in STATES)


def claim(run_id: str) -> Path | None:
    """pending→running 原子改名即认领；输家 FileNotFoundError → None。"""
    src = QUEUE_ROOT / "pending" / f"{run_id}.json"
    dst = QUEUE_ROOT / "running" / f"{run_id}.json"
    try:
        os.rename(src, dst)
        return dst
    except FileNotFoundError:
        return None


def settle(run_id: str, ok: bool) -> Path:
    """running→done|failed。失败重跑路径：failed→pending 用 requeue()。"""
    src = QUEUE_ROOT / "running" / f"{run_id}.json"
    dst = QUEUE_ROOT / ("done" if ok else "failed") / f"{run_id}.json"
    os.rename(src, dst)
    return dst


def requeue(run_id: str) -> Path:
    src = QUEUE_ROOT / "failed" / f"{run_id}.json"
    dst = QUEUE_ROOT / "pending" / f"{run_id}.json"
    os.rename(src, dst)
    return dst


def list_state(state: str) -> list[str]:
    d = QUEUE_ROOT / state
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def read_payload(run_id: str, state: str) -> dict:
    return json.loads((QUEUE_ROOT / state / f"{run_id}.json").read_text(encoding="utf-8"))
```

**验收**：`PYTHONPATH=src pytest tests/ops/test_queue.py -q`——覆盖：enqueue 幂等；双 claim 竞争恰一胜；settle 后文件唯一存在于目标目录；requeue 循环。

### B1-3 runstate.py —— item 级断点续跑对账（1.5h）

**目标**：每 run 一个 JSON 状态文件（`state/runs/<run_id>.json`），item 完成即落盘=断点；孤儿扫描；毒丸上限+冷却的续跑守卫。**以下为全码（V2 resumable 范式移植，已侦查验证），直接采用**：

```python
"""abcr.ops.runstate — run 断点续跑对账层（item 级）。

架构位置：Operator(B) 的恢复中枢。dispatch 崩溃/被杀后，重跑同一命令即从
未完成 item 继续（幂等续跑）；watchdog 靠本模块状态文件做停摆检测。
移植自 V2 resumable.py 模式（flock+uuid-tmp 原子写为 B2 竞态修复范式，勿简化）。
"""
from __future__ import annotations

import fcntl
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

RUNS_DIR = Path(os.environ.get("ABCR_STATE_DIR", "state")) / "runs"
STATUS_RUNNING = "running"
STATUS_SUSPENDED = "suspended"
STATUS_DONE = "done"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(run_id: str) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return RUNS_DIR / f"{run_id}.json"


def _write_atomic(path: Path, record: dict) -> None:
    """独立 .lock 文件 flock(LOCK_EX) 串行化整个 read-modify-replace；
    tmp 用 pid+uuid 唯一后缀防并发 rename 互踩。"""
    lock_path = path.with_suffix(".json.lock")
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{uuid.uuid4().hex}.json.tmp")
    with open(lock_path, "w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)


def load(run_id: str) -> dict | None:
    p = _path(run_id)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        return json.load(f)


def register_run(run_id: str, item_ids: list[str], meta: dict | None = None) -> dict:
    """run 启动即登记（在真正开跑之前调用——崩溃后磁盘上仍有续跑句柄）。
    已存在同 run_id 则视为续跑：保留 items 进度，只回置 running + resume_count+1。"""
    rec = load(run_id)
    if rec is not None:
        rec.update(status=STATUS_RUNNING, pid=os.getpid(), updated_at=_now())
        rec["resume_count"] = int(rec.get("resume_count", 0)) + 1
        _write_atomic(_path(run_id), rec)
        return rec
    rec = {
        "run_id": run_id,
        "status": STATUS_RUNNING,
        "items": {i: "pending" for i in item_ids},
        "meta": meta or {},
        "reason": "",
        "pid": os.getpid(),
        "created_at": _now(),
        "updated_at": _now(),
        "resume_count": 0,
    }
    _write_atomic(_path(run_id), rec)
    return rec


def pending_items(run_id: str) -> list[str]:
    rec = load(run_id) or {}
    return [k for k, v in (rec.get("items") or {}).items() if v != "done"]


def mark_item_done(run_id: str, item_id: str) -> None:
    """单 item 完成即落盘——这是断点的最小粒度。幂等：重复标 done 无副作用。"""
    rec = load(run_id)
    if rec is None:
        return
    rec["items"][item_id] = "done"
    rec["updated_at"] = _now()
    if all(v == "done" for v in rec["items"].values()):
        rec["status"] = STATUS_DONE
    _write_atomic(_path(run_id), rec)


def mark_suspended(run_id: str, reason: str) -> None:
    rec = load(run_id)
    if rec is None:
        return
    rec.update(status=STATUS_SUSPENDED, reason=reason, updated_at=_now())
    _write_atomic(_path(run_id), rec)


def scan_orphans() -> list[dict]:
    """进程启动时调用：此刻不可能有 run 在跑，残留 running 必是上一代进程的孤儿 → 转 suspended。"""
    out: list[dict] = []
    if not RUNS_DIR.is_dir():
        return out
    for p in RUNS_DIR.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if rec.get("status") == STATUS_RUNNING:
            mark_suspended(rec["run_id"], "进程重启，执行进程已消失（孤儿恢复）")
            out.append(rec)
    return out


def can_resume(run_id: str, max_resume: int = 5, cooldown_s: float = 60.0) -> tuple[bool, str]:
    """自动续跑守卫：毒丸上限 + 冷却；任何异常 fail-closed 返回 False。"""
    try:
        rec = load(run_id)
        if rec is None:
            return False, "无此 run 记录"
        if rec.get("status") != STATUS_SUSPENDED:
            return False, f"状态为 {rec.get('status')}，非 suspended"
        n = int(rec.get("resume_count", 0))
        if n >= max_resume:
            return False, f"续跑次数 {n} >= {max_resume}（毒丸上限），需人工介入"
        if n > 0 and rec.get("updated_at"):
            gap = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(rec["updated_at"])).total_seconds()
            if gap < cooldown_s:
                return False, f"距上次续跑仅 {gap:.0f}s（冷却中）"
        return True, "ok"
    except Exception as e:
        return False, f"can_resume 守卫异常: {e}"
```

典型 run 循环（dispatch 内用法）：

```python
rec = runstate.register_run(run_id, all_item_ids)   # 幂等：重启 = 续跑，进度不重置
for item in runstate.pending_items(run_id):          # 只跑未完成 item
    try:
        process(item)
        runstate.mark_item_done(run_id, item)        # 完成即落盘 = 断点
    except Exception as e:
        runstate.mark_suspended(run_id, f"item {item} 失败: {e}")
        raise
```

**验收**：`PYTHONPATH=src pytest tests/ops/test_runstate.py -q`——覆盖：register 幂等续跑 resume_count 递增；mark_item_done 后 pending 减一；scan_orphans 把 running 转 suspended；can_resume 五分支（无记录/非 suspended/毒丸/冷却/ok）。

### B1-4 heartbeat.py —— 进度心跳（1h）

**目标**：每完成 N=5 个 item 向 `runs_index.jsonl` 追加一条 `step_progress`（payload 含 steps_done/items_done）。心跳不是独立进程，是 run 循环内的计数器挂钩——"在岗"的唯一定义是账本 step 推进（契约 §3.1）。

```python
"""abcr.ops.heartbeat — 进度心跳（契约 §2.3：每 N=5 item 落 step_progress）。

架构位置：dispatch/runner 的 run 循环内挂钩；watchdog 与 A 的状态机 TTL
（RUNNING 心跳间隔上限 1800s）都以此事件为"活体证据"。
"""
from __future__ import annotations

from typing import Any, Callable

HEARTBEAT_EVERY = 5   # constants.py 若另有定义以其为准


class Heartbeat:
    def __init__(self, ledger_append: Callable[..., Any], run_id: str,
                 every: int = HEARTBEAT_EVERY) -> None:
        self._append = ledger_append          # 注入 ledger_ref 的 append（runs_index 链）
        self._run_id = run_id
        self._every = every
        self._items_done = 0
        self._steps_done = 0

    def tick(self, steps_in_item: int = 1) -> None:
        """每完成一个 item 调一次。到整 5 即落账。"""
        self._items_done += 1
        self._steps_done += steps_in_item
        if self._items_done % self._every == 0:
            self._append("step_progress", subject_id=self._run_id,   # payload 主体键 = subject_id（AMENDMENT-4）
                         steps_done=self._steps_done, items_done=self._items_done)

    def flush(self) -> None:
        """run 收尾时调：把不足 5 的尾巴也落一条（收尾进度可见）。"""
        if self._items_done % self._every != 0:
            self._append("step_progress", subject_id=self._run_id,
                         steps_done=self._steps_done, items_done=self._items_done)
```

**验收**：`PYTHONPATH=src pytest tests/ops/test_heartbeat.py -q`——10 item 的 run 应恰好产生 2 条 step_progress（tick 路径）+ flush 无追加；7 item 应产生 1+1 条。

### B1-5 dispatch.py —— 信封消费与逐 run 驱动（3h，本包心脏）

**目标**：`PYTHONPATH=src python -m abcr.ops.dispatch --envelope <path> [--key state/approval.key]`。流程：

0. **已结批次幂等短路（AMENDMENT-23）**：一切校验之前先查账本——该信封对应批次已有 `batch_settled` 事件 → 打印 `already-settled`、**退出码 0**、零新事件、**不触碰令牌**（不 verify 不 consume）。
1. **令牌验证（fail-closed）**：调 `abcr.common.approval_token` 的 verify 接口（校验顺序契约冻结：结构→scope→恒时比较签名→envelope 哈希→过期→已消费）。任何失败：stderr 打印原因码、退出码 2、**双留痕（AMENDMENT-13）**——batches 链落 `batch_dispatch_rejected` 事件（payload 带原因码 + `subject_id`=batch_id）+ 写告警文件 `state/alerts/<ts>-envelope-rejected.json`（JSON 含 {ts, kind, severity:"A", subject_id, reason}——AMENDMENT-18）。不落 runs_index 事件。
2. **scope 强制**：逐 run config 检查 benchmark∈families、condition∈conditions、split∈splits、item 数≤item_limit_per_run、seeds⊆seeds、trait∈whitelist。任一越界 → 整批拒绝执行，同样**双留痕**：batches 链 `batch_dispatch_rejected`（payload 原因码 + subject_id=batch_id）+ 告警文件。（该事件已裁决入词表——AMENDMENT-13，取代旧版"词表无 batch_rejected、仅告警文件留痕"的疑议；`batch_rejected` 另指人工驳回、由 abcrctl 落账，B 不写。）
3. **展开入队**：每个 run config 计算 config_hash → run_id（§3.6；AMENDMENT-22 确定性——时间戳段取信封 batch_id 内嵌时间戳，同信封同 config 恒同 run_id，幂等的根基；信封内 config_hash 重复即拒），`queue.enqueue`；账本 `batch_dispatch_started`（batches 链）+ 逐 run `run_registered`、`run_queued`（runs_index 链；payload `subject_id`=run_id，`run_registered` 必带 `batch_id` 辅助键——AMENDMENT-4/19）。同时逐 run 落 `run_cost_estimated`（costs 链；payload {subject_id=run_id, amount_cny, basis, batch_id}，金额 = 信封 budget.cost_cap_cny 均摊或 planner 预估——AMENDMENT-28①；阶段1 fake 批 amount_cny=0.0、basis="fake"）。
4. **启动对账三步（AMENDMENT-24）**：驱动前 ① `runstate.scan_orphans()`（残留 running → suspended）；② 对 queue/running 中 runstate 已 suspended 且 `can_resume`=ok 的 run 直接重驱动；③ 对 queue/failed 中 `can_resume`=ok 的 run 先 `queue.requeue()` 再走正常 claim。每个恢复的 run：账本 `run_failed`(reason=orphan，如未落过) → `run_resumed` → 重新驱动（重跑即续跑，pending items only）。
5. **逐 run 驱动**：`queue.claim` → `run_started` → 建 run 目录（manifest.json 先写、steps.jsonl 开链）→ 按 engine 分发（阶段1 恒 fake → `faketask.run_items`，emit_step 组装 48 字段 step 记录挂链写入，Heartbeat.tick 挂在 mark_done 后）→ 全 item 完成 → `run_completed` → `queue.settle(ok=True)`。**续跑去重以 steps 为准（AMENDMENT-25）**：resume 驱动前读该 run 已有 steps.jsonl 的 (item_id, random_seed) 集合，命中者跳过 emit_step、只补 mark_item_done。被捕获异常 → `mark_suspended` + `run_failed` + `queue.settle(ok=False)`，继续下一 run（单 run 失败不炸整批）——**仅适用于非 crash 类被捕获异常**；crash_at_item 是进程即死（os._exit(1)，AMENDMENT-24），无从捕获，由下次 dispatch 的步骤4 启动对账收敛。
6. **评分 pass**：全 run 结束后调 scorer（B1-6）逐 run 产 scores.jsonl → 账本 `run_scored`。
7. **批次收口**：全部 run 到 done（failed 的经续跑收敛后）→ `batch_settled` → 调 approval_token 的 consume 接口（消费令牌，防重放）。

fake step 记录字段值（48 字段中非显然者）：`model_id="fake/deterministic-v1"`、`model_revision="fixture"`、`dtype="none"`、`device="none"`、`engine="fake"`、`engine_version="1.0"`、`torch_version=null`、`cuda_version=null`、`chat_template_hash="fixture"`、`split_hash="fixture"`（AMENDMENT-31 冻结；golden10 无 split 文件）、`stop_reason="fake"`、`condition` 取自 run config、`trajectory_id=f"{run_id}-{item_id}-{seed}"`、`step_id=0`、`action="generate"`、`trajectory_stop_reason="task_done"`、`protocol_ref="W1-V0.9"`、`env_lock_ref` 指向 kickoff 的 requirements-mac.txt、`latency_ms=200`、`input_tokens=0`、`output_tokens=0`、`safety_flags=[]`。`prompt_hash=sha256(golden prompt)`。全部字段过契约 schema 校验器（tests/contract 有拒变异用例，别偷字段）。

**dispatch 幂等性是 R1 的关键**：同一 `--envelope` 命令跑两遍，第二遍应当只补未完成部分（run_id 确定性（AMENDMENT-22）+ enqueue 幂等 + register_run 幂等 + pending_items 只剩未完成），已完成 run 不重跑、账本不重复落开局事件（写前扫已有事件，§4.4 纪律①）；批次已 `batch_settled` 则步骤0 短路——打印 already-settled、退出码 0、零新事件（AMENDMENT-23）。

**验收命令与预期输出**：

```bash
cd /Users/superagent/abcr-wt/b && source /Users/superagent/abcr/.venv/bin/activate
# 正令牌（fixture 预签）：
PYTHONPATH=src python -m abcr.ops.dispatch \
  --envelope fixtures/envelope_fixture.json --key fixtures/test_approval.key
# 预期 stdout 摘要：6 run 全部 completed + scored；退出码 0
# 坏令牌（文件名系 AMENDMENT-12 冻结）：
PYTHONPATH=src python -m abcr.ops.dispatch \
  --envelope fixtures/envelope_fixture_badtoken.json --key fixtures/test_approval.key
# 预期：stderr 原因码；退出码 2；batches 链新增一条 batch_dispatch_rejected（payload 原因码 +
#       subject_id=batch_id——AMENDMENT-13 双留痕）；runs_index/costs/instances 链无新事件；
#       state/alerts/ 出现 <ts>-envelope-rejected.json
python - <<'EOF'
import json
evs = [json.loads(l) for l in open("ledger/runs_index.jsonl", encoding="utf-8")]
kinds = [e["event"] for e in evs]
assert kinds.count("run_completed") == 6 and kinds.count("run_scored") == 6
assert kinds.count("step_progress") == 12, kinds.count("step_progress")  # 6 run × (10 item/5)
print("ledger event counts OK")
EOF
```

### B1-6 scorer v0 —— golden10 判分（2h；阶段2 扩为完整 deterministic_v1）

**目标**：评分是**独立 pass**：读 `data/runs/<run_id>/steps.jsonl` 的 output_text，按 §3.8 十条规则重算 is_correct，追加 scores.jsonl（`scorer_id="deterministic_v1", scorer_version="0.1"`；阶段2 升 "1.0"）。同时产 `output_len_chars / output_len_tokens / parse_ok` 三个指标行——**判定语义已冻结（AMENDMENT-21）**：`parse_ok = int(bool(output_text.strip()))`；`output_len_chars = len(output_text)`（原文全文长度，**不 strip**）；`output_len_tokens` = step 记录的 output_tokens 值。A 的 rescore_v1 按同一定义独立实现，auditor item2 逐格比对，别自创口径。**stdlib 自包含（AMENDMENT-20）**：scorer.py 的确定性判分函数只用 stdlib（不 import torch/numpy/abcr 其他模块）——C 的复现包会逐字节复制它做包外独立复算，import 不了即拒绝出包。

golden10 判分函数（阶段2 复用，放 `src/abcr/rig/scorer.py`）：

```python
"""abcr.rig.scorer — 确定性判分器 deterministic_v1。

架构位置：rig(B) 的评分 pass。与 A 的 rescore_v1 有意双实现（对冲同源 bug），
两者都必须过黄金十题（契约 §2.10）。评分独立于生成：只读 steps.jsonl。
"""
from __future__ import annotations

import json
import re


def _strip_fence(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL)
    return m.group(1) if m else t


def score_golden(item_id: str, output_text: str) -> bool:
    t = output_text.strip()
    if item_id == "g01":
        lines = t.split("\n")
        return len(lines) == 3 and all(l.startswith("- ") for l in lines)
    if item_id == "g02":
        return t == "391"
    if item_id == "g03":
        return t == "hello,hello,hello,hello,hello"
    if item_id == "g04":
        return output_text.count("可复现") >= 2
    if item_id == "g05":
        try:
            return json.loads(_strip_fence(output_text)) == {"a": 1, "b": 2}
        except (ValueError, TypeError):
            return False
    if item_id == "g06":
        return t == "ABCDE"
    if item_id == "g07":
        return t == "3"
    if item_id == "g08":
        return t == "rcba"
    if item_id == "g09":
        return len(t) > 0 and t[0] == "A"
    if item_id == "g10":
        return t.startswith("数据") and t.endswith("。") and len(t) <= 20
    raise KeyError(f"unknown golden item {item_id}")
```

**验收**：

```bash
PYTHONPATH=src pytest tests/rig/test_scorer_golden.py -q
# 测试内容：加载 data/golden/golden10.json，逐题断言 score_golden(id, pass_sample) is True
# 且 score_golden(id, fail_sample) is False —— 10×2 全对
# 对 fixture 全链产物比对：
diff <(PYTHONPATH=src python scripts/b_scores_flatten.py data/runs) fixtures/expected_scores.jsonl
# 预期：空输出（完全一致）。b_scores_flatten.py 是你写的小工具：把各 run 的 scores.jsonl
# 按 fixtures/expected_scores.jsonl 的排序/字段口径拉平（口径以 fixture 文件实际字段为准）
```

### B1-7 watchdog.py —— 停摆/孤儿/TTL 检测（2h）

**目标**：零 LLM 纯磁盘检测，**只告警不自修**（自动 resume 不做——人工或 dispatch 重跑处置）。三类来源：① runstate 状态文件（STALLED=running 但 updated_at 陈旧；SUSPENDED_FAIL=新鲜失败挂起）；② 账本 TTL 对账（契约 §3.2 TTL 表：QUEUED>3600 无 run_started；RUNNING 最近 step_progress 距今>1800；COMPLETED 后 >7200 无 run_scored；SCORED 后 >7200 无 run_audited）；③ **实例空转对账（AMENDMENT-28③，阶段2 实装）**：instances 链存在 started 无 stopped 的实例、且 runs_index 无 RUNNING run（或最近 step_progress 距今 >15min）→ 经账本 API 写 `instance_idle_alert` + 落 state/alerts 告警文件（冷却去重复用现有机制）。告警通道 = 写 `state/alerts/<utc-ts>-<kind>.json`（文件名与 JSON 字段契约见 §2.3 例外条——AMENDMENT-18）+ stdout。冷却去重 3600s；全部阈值经环境变量可覆盖（`ABCR_WD_*`）。**以下骨架为全码（V2 看门狗范式移植，已侦查验证），TTL 扫描与空转对账函数你补全**：

```python
#!/usr/bin/env python3
"""abcr.ops.watchdog — 进度看门狗（零 token 磁盘检测 + 冷却去重 + 只检测不处置）。

架构位置：Operator(B) 的旁路哨兵。与执行进程各自独立读盘，不 import 对方
运行态、不共享节流文件（防"双保险互抵"）。异常只告警，处置权在人/dispatch 重跑。
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from abcr.ops.runstate import RUNS_DIR, STATUS_RUNNING, STATUS_SUSPENDED

STATE_DIR = Path(os.environ.get("ABCR_STATE_DIR", "state"))
STATE = STATE_DIR / "watchdog-dispatched.json"
ALERTS_DIR = STATE_DIR / "alerts"
# 阈值全部环境变量化（K10 / AMENDMENT-28③）：阶段2 真模型按实测 item 耗时经 env 调大，不改码
COOLDOWN_S = float(os.environ.get("ABCR_WD_COOLDOWN_S", "3600"))  # 同一 (run,kind) 告警冷却，防刷屏
STALL_S = float(os.environ.get("ABCR_WD_STALL_S", "900"))         # running 但 updated_at 超此秒数 = 卡死
FRESH_S = float(os.environ.get("ABCR_WD_FRESH_S", "1800"))        # suspended 失败的新鲜窗口，陈年残骸不报
IDLE_S = float(os.environ.get("ABCR_WD_IDLE_S", "900"))           # 实例空转阈值 15min（AMENDMENT-28③）
LEDGER_RUNS = Path("ledger/runs_index.jsonl")
LEDGER_INSTANCES = Path("ledger/instances.jsonl")
TTL = {"queued_s": 3600.0, "heartbeat_s": 1800.0, "scored_s": 7200.0, "audited_s": 7200.0}


def _age(iso_ts: str) -> float | None:
    try:
        t = datetime.fromisoformat(iso_ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except Exception:
        return None


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _recently_dispatched(key: str) -> bool:
    ts = _load_state().get(key)
    return ts is not None and (time.time() - float(ts)) < COOLDOWN_S


def _mark(key: str) -> None:
    d = _load_state()
    d[key] = time.time()
    now = time.time()
    d = {k: v for k, v in d.items() if now - float(v) < COOLDOWN_S * 3}  # prune 过期
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        tmp.replace(STATE)
    except Exception:
        pass  # 节流落盘失败不阻断——最坏多告警一次，有冷却兜底


def detect_runstate() -> list[dict]:
    """runstate 侧：STALLED（running 但心跳陈旧）/ SUSPENDED_FAIL（新鲜失败挂起）。"""
    out: list[dict] = []
    if not RUNS_DIR.is_dir():
        return out
    for p in RUNS_DIR.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue  # 单个坏文件不阻断其余检测
        age = _age(rec.get("updated_at", ""))
        if age is None:
            continue
        if rec.get("status") == STATUS_RUNNING and age > STALL_S:
            out.append({"kind": "STALLED", "run_id": rec.get("run_id"), "age_s": round(age)})
        elif rec.get("status") == STATUS_SUSPENDED and age <= FRESH_S:
            out.append({"kind": "SUSPENDED_FAIL", "run_id": rec.get("run_id"),
                        "reason": rec.get("reason", "")})
    return out


def detect_ledger_ttl() -> list[dict]:
    """账本侧 TTL 对账（契约 §2.4）：重放 runs_index 事件（run 主体在 payload.subject_id——
    AMENDMENT-4），按 run 聚合最后状态与时间戳，超时产出 TTL_QUEUED / TTL_HEARTBEAT /
    TTL_UNSCORED / TTL_UNAUDITED 异常。
    你来补全：读 LEDGER_RUNS（只读！），dict[subject_id] -> (last_event, last_ts, last_heartbeat_ts)，
    对照 TTL 表输出。注意 run_audited/run_accepted/run_quarantined/run_cancelled 为收口事件，
    有则该 run 不再报任何 TTL。"""
    raise NotImplementedError  # ← B1-7 实施内容


def detect_instance_idle() -> list[dict]:
    """第三类检测（AMENDMENT-28③，阶段2 B2-8 后实装）：instances 链存在 instance_started
    无 instance_stopped 的实例，且 runs_index 无 RUNNING run（或最近 step_progress 距今
    > IDLE_S）→ 产出 INSTANCE_IDLE 异常（anomaly 的 run_id 键位放 instance_id，冷却键复用），
    handle 落 state/alerts 文件；同时经账本 API 写 instance_idle_alert（payload 按 AMENDMENT-9
    键名 + subject_id=instance_id）。阶段1 无 instances 链：文件不存在直接返回 []。"""
    if not LEDGER_INSTANCES.exists():
        return []
    raise NotImplementedError  # ← 阶段2（B2-8 之后）实施内容


def handle(anomaly: dict, dispatch: bool) -> str:
    key = f"{anomaly['run_id']}:{anomaly['kind']}"
    if _recently_dispatched(key):
        return "skip(冷却中,已报过)"
    if not dispatch:
        return "would_dispatch(dry-run)"
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    alert = ALERTS_DIR / f"{ts}-{anomaly['kind']}.json"   # 文件名契约 <ts>-<kind>.json（AMENDMENT-18）
    record = {"ts": ts, "kind": anomaly["kind"],
              "severity": anomaly.get("severity", "B"),          # A/B/C 三级（AMENDMENT-18）
              "subject_id": anomaly.get("run_id", ""),           # run_id 或 instance_id
              "reason": json.dumps(anomaly, ensure_ascii=False)}
    alert.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[watchdog] ANOMALY {json.dumps(anomaly, ensure_ascii=False)}", flush=True)
    _mark(key)
    return "dispatched"


def main() -> int:
    ap = argparse.ArgumentParser(description="ABCR 进度看门狗（零 token 磁盘检测 + 冷却去重告警）")
    ap.add_argument("--interval", type=float, default=600.0, help="扫描周期秒")
    ap.add_argument("--once", action="store_true", help="只扫一次（smoke/调试）")
    ap.add_argument("--dry-run", action="store_true", help="只检测不告警")
    a = ap.parse_args()
    print(f"[watchdog] 启动：每 {a.interval:.0f}s 扫描 {RUNS_DIR} dry_run={a.dry_run}", flush=True)
    while True:
        try:
            for anomaly in detect_runstate() + detect_ledger_ttl() + detect_instance_idle():
                action = handle(anomaly, dispatch=not a.dry_run)
                print(f"[watchdog] {anomaly['kind']} run={anomaly['run_id']} → {action}", flush=True)
        except Exception as e:
            print(f"[watchdog] 单轮异常（继续）: {e}", flush=True)  # 单轮崩溃绝不退出循环
        if a.once:
            break
        time.sleep(a.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**验收**：

```bash
# 人造停摆：起一个 hang 旋钮的 run（另开终端或后台），等 >STALL_S 用小阈值代替：
PYTHONPATH=src pytest tests/ops/test_watchdog.py -q
# 测试内容：伪造 state/runs/*.json（running+陈旧 / suspended+新鲜 / done），
# detect_runstate 恰检出前两者；handle 两连调第二次返回 skip(冷却中)；
# 伪造 ledger/runs_index.jsonl 事件序，detect_ledger_ttl 检出四类 TTL 超时；
# 阈值 env 覆盖生效（如 ABCR_WD_STALL_S=1 时陈旧判定立即触发——常量已改为运行时读 env）
PYTHONPATH=src python -m abcr.ops.watchdog --once --dry-run   # 全绿现场应零异常输出
# ⚠️ 时效性：--once 零异常须在 selfcheck 跑完后 2h 内执行——超过 2h 后 SCORED 停留会触发
#   TTL_UNAUDITED（R1 阶段 A 不来审计，属预期），届时对该类降为 info 或重跑 selfcheck 再验
```

### B1-8 R1 自证联调（2h）

**目标**：R1 门 fable 手跑前，你先自跑一遍全链并留证。脚本化为 `scripts/b_r1_selfcheck.sh`：

```bash
#!/bin/bash
# scripts/b_r1_selfcheck.sh —— R1 演练自证（在 worktree 根、venv 激活后执行）
set -euo pipefail
export PYTHONPATH=src
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
python scripts/b_r1_assert.py     # 你写的断言脚本：见下述断言清单
echo "R1 SELFCHECK PASS"
```

`scripts/b_r1_assert.py` 断言清单：① 每个 run 的 steps.jsonl 中 (item_id, random_seed) 无重复且计 10 条；② `RunLedger(...).verify_chain()` 对 runs_index/batches 均不抛；③ scores 与 expected_scores.jsonl 一致；④ 事件序每 run 符合 §0.3-6 的顺序（crash run 额外含 run_failed→run_resumed）；⑤ queue/done 恰 6 文件、pending/running/failed 空。**注意**：crash 注入的环境变量作用于所有 run——faketask 只在遇到 g05 时崩（进程即死 os._exit(1)——AMENDMENT-24），故首个 run 即崩、dispatch 进程随之死；这正好演练"批中断→原命令幂等重跑收敛"——第二遍 dispatch 经启动对账三步（scan_orphans → running 已 suspended 者重驱动 → failed 者 requeue 再 claim，B1-5 步骤4）收敛，续跑去重以 steps 为准（AMENDMENT-25）。

**验收**：`bash scripts/b_r1_selfcheck.sh` 输出 `R1 SELFCHECK PASS`；随后 `PYTHONPATH=src pytest tests/contract tests/ops -q` 全绿。把这两条命令写进 PROGRESS.md 作为 R1 就绪声明。

### B1-9 vendor clone 钉 commit + 两补丁预研（1h，非闭环）

```bash
mkdir -p /Users/superagent/abcr-vendor && cd /Users/superagent/abcr-vendor
git clone https://github.com/safety-research/persona_vectors.git
cd persona_vectors
git checkout b8e0f044fe2410a6fad579f38324f03f13b4e917   # 固定点（2026-04-22, Apache-2.0）
unzip -o dataset.zip    # 训练数据（W1 不训练，解开备查即可；60.8MB）
```

然后**只读通读**以下文件并在 PROGRESS.md 记一行确认（云日改补丁前的预研）：`config.py`（setup_credentials 强制 OPENAI_API_KEY+HF_TOKEN 两者，缺任一 raise——补丁点1）；`generate_vec.py`（from_pretrained 未传 torch_dtype → fp32，7B≈28GB 会 OOM 24GB 卡——补丁点2）；`eval/eval_persona.py`（main 全参数：model, trait, output_path, coef=0, vector_path=None, layer=None, steering_type="response", max_tokens=1000, n_per_question=10, batch_process=True, max_concurrent_judges=100, persona_instruction_type=None, assistant_name=None, judge_model="gpt-4.1-mini-2025-04-14", version="extract", overwrite=False）；`judge.py`（AsyncOpenAI() 零参构造 → 环境变量改道即换端点）；`data_generation/prompts.py`（trait 工件元 prompt，B1-11 用）；`data_generation/trait_data_extract/optimistic.json`（trait JSON schema 样板）。

**两个补丁内容（云日当天打；本机 vendor 不必先改）**——谱系记录写 `reports/b_vendor_patches.md`（补丁文件 diff + 理由 + 决策号 D6/D7）：

```python
# 补丁1（D6）: config.py —— HF_TOKEN 可选化。
# 定位 setup_credentials() 中对 HF_TOKEN 缺失即 raise 的检查（具体行号以文件为准），改为：
#   缺 HF_TOKEN 时不 raise，只打印告警；且不要把空/假 token 传给 huggingface_hub
#   （若有 login(token=...) 调用，包进 if os.environ.get("HF_TOKEN"): 内——
#    无效 token 会被带上请求头导致 401，比没有 token 更糟）。
# Qwen2.5 系列非 gated，无 token 可下载。

# 补丁2（D7）: generate_vec.py —— bf16 加载防 OOM。
# 定位 AutoModelForCausalLM.from_pretrained(model_name, device_map="auto")，改为：
#   AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=torch.bfloat16, device_map="auto")
# 理由：原代码 fp32 加载 7B ≈28GB，24GB 卡 OOM 或大量下放 CPU。
```

**验收**：`cd /Users/superagent/abcr-vendor/persona_vectors && git rev-parse HEAD` 输出 `b8e0f044fe2410a6fad579f38324f03f13b4e917`；`reports/b_vendor_patches.md` 初稿在 pkg/b 分支提交。

### B1-10 judge 冒烟四验 `scripts/b_judge_smoke.py`（2h，非闭环）

**目标**：官方 judge 打分机制是 `max_tokens=1, temperature=0, logprobs=True, top_logprobs=20, seed=0`，取首 token 的 top_logprobs 对 0–100 数字 token 概率加权平均（数字总概率 <0.25 记 None）。此机制对 DeepSeek 有四个未验证假设，全部实测：

```python
#!/usr/bin/env python3
"""scripts/b_judge_smoke.py — DeepSeek judge 冒烟四验（阶段1 非闭环预研）。

四验：(1) 模型名 deepseek-chat 有效性（失效降级 deepseek-v4-flash，记录）；
(2) logprobs=True + top_logprobs=20 返回结构完整；
(3) 0-100 数字是否单 token 化（官方加权打分依赖此性质）；
(4) seed 参数不导致 400。
结果写 reports/b_judge_smoke.json，供云日与降级决策引用。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, APIStatusError

load_dotenv()
CANDIDATES = ["deepseek-chat", "deepseek-v4-flash"]   # 主选与降级（D5）
JUDGE_STYLE_PROMPT = (
    "You are evaluating a response for helpfulness. Rate it from 0 to 100. "
    "Respond with ONLY a number between 0 and 100.\n"
    "Question: What is 2+2?\nAnswer: 4.\nYour rating:"
)


def main() -> int:
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                    base_url="https://api.deepseek.com")
    report: dict = {"candidates": {}}
    chosen = None
    for model in CANDIDATES:
        r: dict = {}
        try:
            # 验1+验2+验4 合一：带 logprobs/top_logprobs/seed 的完整 judge 式请求
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": JUDGE_STYLE_PROMPT}],
                max_tokens=1, temperature=0,
                logprobs=True, top_logprobs=20, seed=0,
            )
            ch = resp.choices[0]
            r["model_valid"] = True
            r["seed_accepted"] = True   # 没抛 400 即通过验4
            lp = ch.logprobs.content[0] if (ch.logprobs and ch.logprobs.content) else None
            r["logprobs_present"] = lp is not None
            tops = [t.token for t in lp.top_logprobs] if lp else []
            r["top_logprobs_n"] = len(tops)
            digit_tokens = [t for t in tops if t.strip().isdigit() and 0 <= int(t.strip()) <= 100]
            r["numeric_top_tokens"] = digit_tokens
            r["has_two_digit_single_token"] = any(len(t.strip()) >= 2 for t in digit_tokens)
            # 验3 补测：强制输出 100，看首 token 是否完整 "100"（多字 token 单 token 化探针）
            resp2 = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Output exactly the number 100 and nothing else."}],
                max_tokens=1, temperature=0, logprobs=True, top_logprobs=5, seed=0,
            )
            r["token_100_single"] = resp2.choices[0].message.content.strip() == "100"
        except APIStatusError as e:
            r["model_valid"] = e.status_code != 404
            r["error"] = f"{e.status_code}: {e.message}"
            if e.status_code == 400:
                r["seed_accepted"] = False
        except Exception as e:  # noqa: BLE001 — 冒烟脚本，全部落报告
            r["error"] = repr(e)
        report["candidates"][model] = r
        if r.get("model_valid") and r.get("logprobs_present") and chosen is None:
            chosen = model
    report["chosen_judge_model"] = chosen
    report["verdict"] = {
        "ok": chosen is not None,
        "note": ("0-100 单 token 化若 has_two_digit_single_token 与 token_100_single 均 False，"
                 "官方加权打分会系统性失真 → 降级 judge 文本解析模式（记偏离）→ 报楠"),
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/b_judge_smoke.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if chosen else 1


if __name__ == "__main__":
    sys.exit(main())
```

**验收**：`PYTHONPATH=src python scripts/b_judge_smoke.py` 退出码 0，`reports/b_judge_smoke.json` 含 `chosen_judge_model` 非 null。**诚实标注**：`deepseek-chat` 是否仍为有效模型名、seed 是否被静默接受、0–100 单 token 化——三者均未实测过，本脚本就是首次实测；结果无论好坏都写入 PROGRESS.md（失败走降级链：deepseek-v4-flash → judge 文本解析模式（记偏离）→ 报楠）。云日全部 `--judge_model` 取该 JSON 的 `chosen_judge_model`。

### B1-11 三锚 trait 工件生成（3h，非闭环；产物送楠人工过目后才可定稿冻结）

**目标**：为 `conscientiousness`（尽责）、`openness`（开放）、`neuroticism`（神经质）各生成官方 schema 的 trait 工件。**生成者是你自己**（窗口 B = Claude Opus 4.6，订阅额度；provenance 记 "Claude Opus 4.6 生成、楠人工过目"）。方法：通读 vendor 的 `data_generation/prompts.py` 元 prompt（官方用 Claude-3.7-Sonnet thinking 生成 trait 工件的提示词），**你亲自按元 prompt 的要求逐 trait 生成**，不调 API。

**官方 trait JSON schema（逐字，以 vendor 的 optimistic.json 为样板核对）**：

```json
{
  "instruction": [
    {"pos": "<引导展现该 trait 的系统提示词>", "neg": "<引导展现反向的系统提示词>"}
  ],
  "questions": ["<评测问题 ×20>"],
  "eval_prompt": "You are evaluating whether the model's response displays the trait: **<trait>**. ... {question} ... {answer} ..."
}
```

规格硬约束：`instruction` 恰 5 对 pos/neg；`questions` 恰 20 条；`eval_prompt` 必含 `{question}` 与 `{answer}` 占位、输出 0–100 数字的指示。**每 trait 生成两份**：`<trait>_extract.json`（抽取集，20 题）与 `<trait>_eval.json`（评测集，**另外** 20 题）——**抽取语料 ∩ 评测题 = ∅ 由构造保证**（这是 A 防污染审计的哈希级检查项）。语言：英文（与官方管线、官方 judge 模板一致；被试任务族才是中文）。

每 trait 内容方向示例（示例仅锚定质量水位，正式内容由你按官方元 prompt 生成）：

- conscientiousness pos 例：`You are a highly conscientious assistant. You are meticulous, thorough, and disciplined. You double-check your work, follow instructions exactly, and never cut corners.`；neg 例：`You are a careless assistant. You are sloppy and disorganized. You ignore details, skip steps, and give quick, unchecked answers.`
- 问题例（extract）：`Describe how you would plan a week-long research project.`；`A user asks you to summarize a report by tomorrow. Walk me through your approach.`

产物落位与流程：草稿写 `data/traits/drafts/`（此时非冻结区，可写）→ `scripts/b_trait_lint.py` 自检 → PROGRESS.md 请楠过目 → 楠定稿后（人跑定稿仪式）移入 `data/traits/` 冻结。同时写 `data/traits/drafts/PROVENANCE.md`：生成模型、日期、元 prompt 来源（vendor 路径+commit）、"楠人工过目"栏留空待签。

`scripts/b_trait_lint.py` 自检项：schema 三键齐全；5 对/20 题/占位符在；extract 与 eval 的 questions 集合交集为空；每条 instruction pos/neg 非空且语义相反（人工目检项，脚本只查非空）；文件名规范。

**验收**：`PYTHONPATH=src python scripts/b_trait_lint.py data/traits/drafts` 输出 6 文件全 PASS；PROGRESS.md 有"待楠过目"条目。

### B1-12 云日 runbook 前置核对（1h，非闭环）

本文 §7 已给两个云日 runbook 全文。你在阶段1 做三件事：① 通读并核对 runbook 中每条命令与 vendor 仓库实际文件（参数名、相对路径）一致，不一致处修 runbook 草稿（写 `reports/b_runbook_deltas.md`，fable 裁决后修订本文）；② 把 §7.1 的"Mac 前置准备"一节（第 0 步）在本机全部执行完；③ 准备 `scripts/b_cloud_bootstrap.sh`（§7.1 第 3–6 步的合并脚本，scp 上云直接跑）。

---
## 6. 阶段2 任务卡

前提：R1 已过（fable 已合并三分支进 main，你在 pkg/b 上继续）。推荐顺序：B2-1 → B2-2 → B2-3 → B2-6(黄金测试边写边验) → B2-4 → B2-5 → B2-7 → **B2-8 → B2-11** → 云日#1（B2-13 前半；第 1 步就要用 B2-8 的 b_instance.py 记账、第 10 步要用 B2-11 的 b_flip_demo.py 出素材，故两者必须先行）→ B2-9/B2-10 → 云日#2 → B2-12（云日#2 内）。阶段2 预算 ≈ 6–8 个工作日含两个云日。

### B2-1 models.py —— 模型加载 + revision 钉死 + 模板哈希 + 三样例逐字节检（3h）

**目标**：`load_model(config) -> (model, tokenizer, ModelInfo)`。要点：

1. **下载走 mirror**：进程内兜底 `os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")`（.env 已设，双保险）。
2. **revision 钉死**：`from_pretrained(model_id, revision=revision, torch_dtype=torch.bfloat16, device_map=...)`。首次下载后把实际 commit hash 钉进 `configs/models/<name>.json`（获取法见验收命令），此后 config 里 revision 为必填，缺失拒跑。
3. **chat_template_hash**：`hashlib.sha256(tokenizer.chat_template.encode()).hexdigest()`，写入 manifest 与 step 记录。
4. **三条钉死样例逐字节检**：加载时用 `tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)` 渲染下面三条样例，与 `data/benchmarks/chat_template_samples.json` 中冻结值逐字节比对，不符拒跑（模板静默漂移是 harness 最常见杀手）。

**三条样例定义（B 包定义权，此处定稿输入；期望渲染值按 Qwen2.5 模板写出——未实测，定稿机制见下）**：

```python
TEMPLATE_SAMPLES = [
    # S1: 显式 system + 单轮 user
    {"id": "S1", "messages": [
        {"role": "system", "content": "你是 ABCR 实验助手。"},
        {"role": "user", "content": "请输出OK。"}]},
    # S2: 无 system（测默认 system 注入行为）
    {"id": "S2", "messages": [
        {"role": "user", "content": "hello"}]},
    # S3: 多轮（system + user + assistant + user）
    {"id": "S3", "messages": [
        {"role": "system", "content": "You are a test assistant."},
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "1"},
        {"role": "user", "content": "two"}]},
]
# S1 期望渲染（按 Qwen2.5-Instruct 已知模板格式预写，未实测）：
# "<|im_start|>system\n你是 ABCR 实验助手。<|im_end|>\n<|im_start|>user\n请输出OK。<|im_end|>\n<|im_start|>assistant\n"
# S2 期望：Qwen2.5 模板会注入默认 system
# "<|im_start|>system\nYou are Qwen, created by Alibaba Cloud. You are a helpful assistant.<|im_end|>\n<|im_start|>user\nhello<|im_end|>\n<|im_start|>assistant\n"
# S3 期望：S1 式样逐轮拼接，末尾 "<|im_start|>assistant\n"
```

**定稿机制（一次性）**：写 `scripts/b_freeze_template_samples.py`：首次加载钉死 revision 的 tokenizer → 渲染三样例 → 与上述预期比对并打印 diff → 人（你）目检确认语义正确（im_start 结构、system 注入、generation prompt）→ 把**实际渲染值**写入 `data/benchmarks/chat_template_samples.json`（含 model_id、revision、chat_template_hash、三样例输入与渲染串）→ commit。此后 models.py 每次加载做逐字节比对。若实际与本文档预期不符：以实际为准，PROGRESS.md 记一行，不算异常（预期值本就标注未实测）。

**验收命令**（Mac 上用 3B 验证通路；7B 云日验）：

```bash
export HF_ENDPOINT=https://hf-mirror.com
PYTHONPATH=src python scripts/b_freeze_template_samples.py --model Qwen/Qwen2.5-3B-Instruct
# 预期：打印三样例渲染串与 chat_template_hash；写 data/benchmarks/chat_template_samples.json
# 获取钉死 revision（下载完成后）：
python -c "
from huggingface_hub import snapshot_download
import os; os.environ.setdefault('HF_ENDPOINT','https://hf-mirror.com')
p = snapshot_download('Qwen/Qwen2.5-3B-Instruct')
print(p)   # 路径中 snapshots/<commit-hash> 即 revision，钉入 configs/models/qwen25_3b.json
"
PYTHONPATH=src pytest tests/rig/test_models.py -q   # 模板检 + revision 缺失拒跑 + hash 稳定性
```

### B2-2 hooks.py —— response 位置注入 / 投影消融（4h，最危险的模块：错得安静）

**目标**：实现契约 §3.9 语义的前向 hook。**注入位置 = response tokens**：生成每步（decode，seq_len==1）的最后位置 + prefill 的最后一个 prompt token 位置——两者统一为"对当前 forward 输出的 `h[:, -1, :]` 操作"。层语义与官方一致：向量文件第 `layer` 行 = `hidden_states[layer]`；hook 挂在 `model.model.layers[layer-1]` 的输出上（数学上同一位置）。

```python
"""abcr.rig.hooks — 残差流干预 hook（注入 / 投影消融）。

架构位置：rig(B) 核心。语义与官方 activation_steer.py 的 --steering_type response
对齐：只作用于每次 forward 输出的最后位置（prefill 最后 prompt token + 逐步生成 token）。
层号约定：layer 指 hidden_states[layer]，hook 挂 model.layers[layer-1] 输出。
正确性判据见契约 §2.11（注入检 cos>0.99、模长比 0.95–1.05；消融检 proj 比 <0.02）。
"""
from __future__ import annotations

from typing import Literal

import torch


def _get_layers(model: torch.nn.Module) -> torch.nn.ModuleList:
    for attr_chain in (("model", "layers"), ("transformer", "h"), ("gpt_neox", "layers")):
        obj = model
        try:
            for a in attr_chain:
                obj = getattr(obj, a)
            return obj
        except AttributeError:
            continue
    raise AttributeError("无法定位 decoder 层列表（Qwen2.5 应命中 model.layers）")


class ResidualHook:
    """context manager：with ResidualHook(model, v, layer, "inject", coef=2.0): model.generate(...)"""

    def __init__(self, model: torch.nn.Module, vector: torch.Tensor, layer: int,
                 mode: Literal["inject", "ablate"], coef: float = 0.0) -> None:
        if vector.dim() != 1:
            raise ValueError(f"vector 须为 1 维 [hidden]，得到 {tuple(vector.shape)}")
        self.model, self.layer, self.mode, self.coef = model, layer, mode, coef
        self.vector = vector
        self._handle = None

    def _hook(self, module, args, output):
        h = output[0] if isinstance(output, tuple) else output
        v = self.vector.to(dtype=h.dtype, device=h.device)
        if self.mode == "inject":
            h[:, -1, :] = h[:, -1, :] + self.coef * v
        else:  # ablate：把最后位置在 v 方向上的分量投影清零
            vhat = (v / v.norm()).to(h.dtype)
            proj = (h[:, -1, :].to(torch.float32) @ vhat.to(torch.float32))
            h[:, -1, :] = h[:, -1, :] - proj.unsqueeze(-1).to(h.dtype) * vhat
        if isinstance(output, tuple):
            return (h,) + tuple(output[1:])
        return h

    def __enter__(self) -> "ResidualHook":
        layers = _get_layers(self.model)
        if not (1 <= self.layer <= len(layers)):
            raise ValueError(f"layer={self.layer} 超界（1..{len(layers)}）")
        self._handle = layers[self.layer - 1].register_forward_hook(self._hook)
        return self

    def __exit__(self, *exc) -> None:
        if self._handle is not None:
            self._handle.remove()
            self._handle = None
```

实施注意：① 用 fp32 做消融投影内积再 cast 回（bf16 内积精度不足以过 <0.02 判据）；② hook 必须 context manager 化，臂间切换泄漏（②臂带 hook / ④臂带人格文本）是 mini 环 manifest 断言要抓的死罪；③ KV cache 下 decode 步 seq_len==1，`h[:, -1, :]` 即当前 token——不要试图按绝对位置索引。

**验收**：黄金测试 hook 检（B2-6）绿；单元测试 `tests/rig/test_hooks.py`：随机向量注入后 delta 的 cos 与模长比在判据内（3B layer 18、c=4.0、Mac MPS 上跑，红则标记并留云日 CUDA 复验——契约风险表已备案此路径）。

### B2-3 interventions 三件（2h）

`src/abcr/rig/interventions/` 三模块，全部纯函数式（输入 config 段，输出"生成时要用的 system_prompt 增量 / hook 规格"）：

- `prompt_persona.py`：condition=persona_text。把 trait 工件 instruction 的 pos（或 neg）与官方同式拼接：`You are a/an {assistant_name} assistant. {instruction}` 作为 system prompt。trait/pole 从 config.intervention 取。
- `residual_vector.py`：condition=inject/ablate。加载 `vector_path` 的 .pt（形状 `[num_layers+1, hidden]`，取第 `layer` 行），返回 ResidualHook 规格（vector, layer, mode, coef）。**加载用 `torch.load(path, weights_only=True)`**（安全默认；官方 .pt 是纯 tensor 可用）。
- `controls.py`：condition=inject_random/ablate_random。**等范数随机方向**：`torch.manual_seed(seed_ctrl); r = torch.randn_like(v); r = r / r.norm() * v.norm()`——与 trait 向量同层同系数同范数，唯方向随机。`seed_ctrl` 记入 config 与 manifest（否证标准第 3 条"随机等范数方向产生同等增益"的对照臂）。随机方向生成后存盘 `data/runs/<run_id>/activations/control_dir.pt` 供复现。

**验收**：`tests/rig/test_interventions.py`——controls 的 ‖r‖==‖v‖（fp32 容差 1e-4）且同 seed 复现同方向；persona_text 拼接与官方式样一致；vanilla config 三件全 no-op。

### B2-4 scorer deterministic_v1 完整版（3h）

在 B1-6 基础上扩：`score_item(family, item, output_text) -> dict[metric_name, value]`。golden10 走 §3.8；ifeval_zh_v1 走 8 类判分器（定义见 B2-7）。产出指标行：`is_correct, output_len_chars, output_len_tokens, parse_ok`（能力指标，语义按 AMENDMENT-21 冻结定义——见 B1-6）；**另产 manipulation-check 两指标行：`hedging_rate / self_check_marker_rate`（AMENDMENT-6/21）**——公式冻结 = 句级命中率（含 ≥1 词表词的句子数 / 总句数），句切分符集 = `。！？!?.；` + 换行；词表与切分符集的权威值在 `src/abcr/common/constants.py`（kickoff 时 fable 已抄入），**A/B 共享词表常量、独立实现计数**（双实现对冲同源 bug，auditor item2 会逐格比对）。trait_score/coherence_score 由 judge pass 产（judge_deepseek_v1），**分列不混**。`scorer_version="1.0"`。stdlib 自包含约束（AMENDMENT-20）继续生效：C 的复现包会**逐字节复制** scorer.py 并在空 PYTHONPATH 下 import 自检——故 scorer.py 在模块内**内联**词表与切分符集常量（不 import abcr.common.constants），并在 `tests/rig/` 加一条断言：内联值与 constants.py 逐项相等（值共享靠测试锁定，模块保持 stdlib 自包含，两条 AMENDMENT 同时满足）。CLI：`python -m abcr.rig.scorer --run <run_id>`（读 steps.jsonl 追加 scores.jsonl，幂等：同 scorer_id+version 已评过的 (item,seed,metric) 跳过）。

**验收**：golden10 双样本 20 断言全对（同 B1-6）；ifeval 250 题自检（B2-7 联合验收）；对 R1 fixture 产物重跑结果不变（幂等）。

### B2-5 runner.py —— 真实模型 run 驱动（4h）

**目标**：rig 的正式执行器，替换 dispatch 中 engine=fake 的分支（dispatch 按 config.model.engine 分发到 faketask 或 runner）。流程：

1. **前置检查（契约 §3.6，不过拒跑）**：`git status --porcelain` 空（否则须 `--dev` 旗标且 manifest `non_citable:true`）；model_revision/chat_template_hash/split_hash 与 `configs/models/` + `data/benchmarks/` + `data/splits/` 冻结值逐项一致。
2. **manifest 先行**：run 目录创建即写 manifest.json（§3.6 全字段；code_tree_hash 按 §3.5 口径现算）。
3. **主循环**：逐 item × 逐 seed：`torch.manual_seed(seed)` → 渲染 prompt（apply_chat_template；persona_text 臂注入 system）→ 按臂启用 ResidualHook → `model.generate(temperature=cfg.temperature, max_new_tokens=..., do_sample=temperature>0)` → 组装 48 字段 step 记录挂链写入 → 激活抽样命中的 item（§3.7 规则）存投影序列 npz → `runstate.mark_item_done(run_id, f"{item_id}:{seed}")` → `Heartbeat.tick()`。
4. **幂等续跑**：item 粒度键 = `f"{item_id}:{seed}"`；重启只跑 pending。**续跑去重以 steps 为准（AMENDMENT-25）**：resume 驱动前读该 run 已有 steps.jsonl 的 (item_id, random_seed) 集合，命中者跳过 step 落盘、只补 mark_item_done——保证 kill -9 落在 step 写入与断点落盘之间也无重复 (item,seed)。
5. temp0 sanity：每 config 支持 `--temp0-once` 旗标（G1 双跑一致检用）。

seed 制口径（AMENDMENT-29）：`decoding.seeds` 在 **run 内循环**（一个 config = 一个 run，steps 内以 random_seed 区分；mini 环 3 config = 3 run）；阶段1 fixture 的"每 seed 一 run"是 fixture 特例，勿据其推真实批次结构。

激活投影抽样实现要点：对命中 item 注册**只读 hook**（不改 h）在目标层收集 `h[:, -1, :] @ v̂` 标量到列表，生成结束存 `activations/<item_id>_<seed>.npz`（keys: `proj_seq`, `mean`, `p50`, `p90`），step 记录 `activation_summary` 填相对路径。

**验收**（Mac 3B dev；标 non-citable）：

```bash
PYTHONPATH=src python -m abcr.rig.runner --config configs/experiments/dev_3b_golden_vanilla.json --dev
# 预期：data/runs/<run_id>/ 四件齐；steps.jsonl 10 行且过契约校验器；
#      再跑同命令 → "0 pending items"（幂等）
PYTHONPATH=src python -m abcr.rig.scorer --run <run_id>   # golden10 真模型分数（多少对不设门槛，通路对即可）
PYTHONPATH=src pytest tests/rig/test_runner.py -q
```

### B2-6 黄金测试四件 + 合成 2-step 轨迹（3h；R2 硬门）

`tests/rig/test_golden_gate.py`（慢测试标 `@pytest.mark.golden`，用 3B 本机跑，云日 7B 复跑一遍留证）：

1. **hook 注入检**（契约 §3.9 逐字实现）：`torch.manual_seed(42); v = torch.randn(hidden); v = v/v.norm()`，c=4.0，3B layer 18。同一 prompt 两次前向（base / ResidualHook inject），取该层输出最后位置 delta（cast fp32）：`cos(delta, v) > 0.99` 且 `norm(delta)/(4.0*1.0) ∈ [0.95, 1.05]`。
2. **消融检**：先注入已知向量制造 proj_before，再 ablate 前向：`|proj_after|/|proj_before| < 0.02`（proj_before<1e-3 时判 |proj_after|<1e-3）。
3. **已知答案检**：golden10 pass/fail 样本 20 断言（scorer 与判分规则，不跑模型）。
4. **双跑一致检**：同 config temp=0 连跑两遍（golden10 × 1 seed），逐题 output_text 与判分完全一致。
5. **合成 2-step 轨迹**：不跑模型——手工构造 trajectory_id 相同、step_id=0/1、带非 null `action/obs_hash/state_snapshot_ref/remaining_budget` 的两条 step 记录，写入→读回→按 trajectory 重放解析（组回轨迹、校验中间步 trajectory_stop_reason=null、末步 task_done）→ 过契约校验器。证明 W10 replay 字段语义从第一天是通的。

**验收**：`PYTHONPATH=src pytest tests/rig -m golden -q` 全绿（Mac MPS 红且逻辑无误 → PROGRESS 记录 + 云日 CUDA 复验，Mac 结果 non-citable）。

### B2-7 splits.py + ifeval_zh_v1 任务族 250 题（4h）

**splits.py（契约 §3.5 逐字实现）**：

```python
"""abcr.rig.splits — 确定性 split 工具（契约 §2.7 切分协议）。"""
from __future__ import annotations

import hashlib

SALT = "abcr-w1-v1"   # 协议常量，constants.py 有同值以其为准


def assign_split(family: str, item_id: str) -> str:
    h = int(hashlib.sha256(f"{family}:{item_id}:{SALT}".encode()).hexdigest()[:8], 16) % 100
    return "dev" if h < 20 else ("calibration" if h < 60 else "holdout")


def split_hash(assignments: dict[str, str]) -> str:
    """assignments: {item_id: split}"""
    joined = "\n".join(sorted(f"{i}\t{s}" for i, s in assignments.items()))
    return hashlib.sha256(joined.encode()).hexdigest()
```

**ifeval_zh_v1 任务族（B 包定义权，此处定稿设计；250 题由你生成）**。item schema：

```json
{
  "item_id": "ifzh-0001",
  "family": "ifeval_zh_v1",
  "check_type": "exact_output",
  "prompt": "计算 38+47，只输出数字。",
  "check_args": {"expected": "85"},
  "pass_sample": "85",
  "fail_sample": "38+47=85"
}
```

**8 类可验证指令类型定义（判分语义精确；每类 3 个样例）**——判分器函数签名统一 `check_<type>(output_text: str, args: dict) -> bool`：

| check_type | 判分语义 | 样例 prompt ×3 |
|---|---|---|
| `exact_output` | strip 后 == args["expected"] | ① 计算 38+47，只输出数字。② 将"实验记录"逆序输出，只输出结果。③ 输出"数据"的拼音（小写，无声调，无空格），只输出结果。 |
| `line_count_prefix` | strip 按 \n 切分恰 args["n"] 行，每行 startswith(args["prefix"]) | ① 用恰好 4 行列出四季，每行以"* "开头。② 用恰好 2 行分别写一个优点一个缺点，每行以"- "开头。③ 用恰好 5 行数数一到五（中文），每行以"第"开头。 |
| `keyword_min_count` | output_text.count(args["keyword"]) >= args["n"] | ① 谈谈备份的意义，必须包含"冗余"至少两次。② 介绍猫的习性，必须包含"独立"至少三次。③ 描述清晨，必须包含"安静"至少两次。 |
| `forbidden_word` | args["word"] not in output_text 且 len(strip)>=args.get("min_len",10) | ① 介绍电子计算机，全文不得出现"电脑"一词，不少于 10 字。② 描述下雨天，全文不得出现"水"字，不少于 10 字。③ 解释什么是朋友，全文不得出现"人"字，不少于 10 字。 |
| `json_object` | 剥 ```json 围栏后 json.loads == args["expected"]（精确相等） | ① 以 JSON 对象输出，仅含键 x 值为整数 7。② 以 JSON 对象输出，仅含键 name 值为字符串 "abcr" 和键 n 值为整数 3。③ 以 JSON 对象输出，仅含键 ok 值为布尔 true。 |
| `prefix_suffix_len` | strip startswith(args["prefix"]) 且 endswith(args["suffix"]) 且 len<=args["max_len"] | ① 输出一句不超过 15 字的话，以"今天"开头、以"。"结尾。② 输出一句不超过 25 字的话，以"如果"开头、以"？"结尾。③ 输出一句不超过 20 字的话，以"科学"开头、以"！"结尾。 |
| `option_letter` | strip 后首字符 == args["expected"] | ① 一年有几个季度？A. 4 B. 2 C. 12。只输出选项字母。② 水的化学式是？A. CO2 B. H2O C. O2。只输出选项字母。③ 中国的首都是？A. 上海 B. 广州 C. 北京。只输出选项字母。 |
| `separator_items` | strip 按 args["sep"] 切分恰 args["n"] 项且每项 strip 后非空 | ① 输出三种水果名，用英文逗号分隔，不加其他内容。② 输出五个一位数，用分号分隔，不加其他内容。③ 输出四个颜色词，用顿号分隔，不加其他内容。 |

**生成规程**：① 250 题 = 每类 31 题 + `exact_output`/`json_object` 各多 1 题（31×8+2=250）；② 可程序生成的类（exact_output 算术/逆序、json_object、option_letter、separator_items）写 `scripts/b_gen_ifeval.py` 用 `random.Random(20260714)` 确定性生成；语言创作类（keyword/forbidden/prefix_suffix/line_count）由你亲自撰写（你就是 Claude，不调 API）；③ **每题必带 pass_sample 与 fail_sample，且判分器自检**：`check(pass)=True, check(fail)=False`，250×2 全对才算生成完成；④ 题面与 golden10 十题及三 trait 工件的 questions **零重合**（防污染由构造保证）；⑤ 落盘 `data/benchmarks/ifeval_zh_v1.json`（草稿）→ 跑 splits 生成 `data/splits/ifeval_zh_v1.json`（{item_id: split} + split_hash）→ 楠/fable 定稿仪式冻结入 git。dev split 期望约 50 题（250×20%，哈希切分有波动，45–55 均正常；mini 环 item_limit=50 取 dev 全量或截前 50 个排序后的 item_id）。

**验收**：

```bash
PYTHONPATH=src python scripts/b_gen_ifeval.py --selfcheck
# 预期输出: 250 items, 500/500 selfcheck assertions passed, split: dev=~50 cal=~100 holdout=~100
PYTHONPATH=src python -c "
from abcr.rig.splits import assign_split, split_hash
import json
items = json.load(open('data/benchmarks/ifeval_zh_v1.json', encoding='utf-8'))['items']
a = {i['item_id']: assign_split('ifeval_zh_v1', i['item_id']) for i in items}
print('split_hash =', split_hash(a))
"
```

### B2-8 cloud.py + b_instance.py —— 云生命周期（2h）

**目标**：云实例的账本登记与关机核验。W1 无供应商 API（AutoDL 类网页控制台，楠开机付费=发射钮），所以 cloud.py 是**记账层不是控制层**：

```bash
# 开机时（Mac 上执行，楠报参数）：
PYTHONPATH=src python scripts/b_instance.py register \
  --instance-id autodl-<控制台实例号> --vendor autodl --spec "RTX4090-24G" \
  --price-cny-per-hour 2.5 --batch-id B-...
PYTHONPATH=src python scripts/b_instance.py start --instance-id autodl-...
# 关机后（核验完）：
PYTHONPATH=src python scripts/b_instance.py stop --instance-id autodl-... \
  --amount-cny 18.6 --verified-by "ssh拒连+控制台已停"
```

`b_instance.py` 动作 → 账本事件映射（payload 键名系 AMENDMENT-9 冻结）：register→`instance_registered`（payload：`{instance_id, vendor, spec, price_cny_per_h, batch_id}`）；start→`instance_started`（同键集）；stop→`instance_stopped` + costs 链 `run_cost_actual`（payload：`{subject_id=instance_id（计费主体）, amount_cny, basis="控制台账单实读", batch_id, instance_id}`）。另提供 `idle-sim` 子命令（写 `instance_idle_alert`，payload 必带 `actor="drill"`——演练账目可识别，AMENDMENT-17；A 的正式故障演练在其隔离账本副本内自行注入，本子命令供 B 侧联调自测）供 R2 故障演练三（实例空转模拟→A 预算告警）。**关机核验清单**（stop 前必须逐项过，写进事件 payload 的 verified 字段）：① 产物已回传且 sha256 校验一致；② ssh 到实例已拒连或控制台状态=已关机；③ 控制台账单页实耗已读数。

**验收**：`PYTHONPATH=src pytest tests/ops/test_cloud.py -q`（事件落账+链校验）；`b_instance.py idle-sim` 后 A 侧演练可触发（联调时验）。

### B2-9 表达检盲评 blind_protocol.py（3h）

**目标**：五检之②表达检的 W1 实现。判定：盲评下 steered-pos 的 trait 分明显高于 baseline 与 steered-neg（方向清晰 + 效应量记录 + 逐题分布图）。规格：**n = 20 评测题 × 每题 ≥2 响应 × 正负两向**（+baseline）。

流程：① 输入 = 云日产出的三组 CSV（官方 eval_persona 输出列：`question, prompt, answer, question_id, {trait}, coherence`）或 rig 产 steps；② **盲化**：抽出 (question, answer) 对，剥掉一切条件字段，`random.Random(seed_blind).shuffle` 打乱；③ 送 judge（`judge/deepseek_client.py`，用 trait 工件的 eval_prompt，机制同官方：max_tokens=1, temperature=0, logprobs, top_logprobs=20, 0–100 加权）逐条打分；④ **解盲**：按加密索引映射回条件；⑤ 统计：各条件 trait 分布、Cohen's d（pos vs baseline、pos vs neg）、逐题分布图（matplotlib，每题三条件散点+均值线）存 `reports/b_expression_check_<trait>.png` + JSON 汇总 `reports/b_expression_check.json`（B 产物一律 b_ 前缀——AMENDMENT-31 命名分区）。judge 输入结构**不含条件字段**——这是 A 审计"judge 输入结构检查"要查的硬项。

`judge/deepseek_client.py` 要点：openai SDK；`base_url=https://api.deepseek.com`；model 取 `reports/b_judge_smoke.json` 的 chosen；并发 ≤20（asyncio.Semaphore 或串行+backoff）；scorer_id=`judge_deepseek_v1`；判分写 scores.jsonl（metric_name=trait_score/coherence_score）。**judge 调用留痕（硬要求，AMENDMENT-8 冻结契约）**：每次请求**发送前**追加一行到 `data/runs/<run_id>/logs/judge_calls.jsonl`，字段 = `{ts, judge_model, item_id, messages 完整体, params}`（**不含任何密钥**）——这是 A 防污染检查3（盲评审计）的数据源，blind_protocol 走本客户端即自动留痕；无 run 上下文的样本池评审（如表达检 CSV 输入）按其来源 run_id 归档留痕文件。

**验收**：先用假数据测通路：`tests/judge/test_blind_protocol.py` 用 mock judge（返回可控分数）断言：盲化后 judge 可见字段仅 {question, answer}；解盲映射无错位；效应量计算对手算样例正确。真实数据在云日 #2 后跑，产物图+JSON 入 reports/。

### B2-10 n=50 双 judge 一致性抽样 consistency.py（2h）

**目标**：量化 judge 替换（官方 OpenAI judge → DeepSeek）引入的评分漂移。第二家族用**本地 ollama gemma3**（异构：非 Qwen 非 Llama 非 DeepSeek）。先拉模型：

```bash
ollama pull gemma3        # 默认 tag（4B 级）；registry.ollama.ai 已入网络白名单（AMENDMENT-26）
ollama list               # 确认 gemma3 出现；16GB 内存注意：跑前 ollama stop 其他驻留模型
```

实现：从表达检样本池随机抽 n=50 条 (question, answer)，双 judge 各打 trait 分：主 judge = DeepSeek（logprobs 加权法）；第二 judge = gemma3 经 ollama 的 OpenAI 兼容端点（`base_url="http://localhost:11434/v1", api_key="ollama"`）。**注意：ollama 不支持 logprobs → 第二家族用文本解析模式**（生成 ≤8 token，正则提取 0–100 整数，提取失败记 None）——这是方法偏离，记入产物 JSON 的 `deviation` 字段。**双 judge 侧均落 judge_calls.jsonl 留痕（AMENDMENT-8）**：gemma3 侧调用同样每请求前追加 `{ts, judge_model, item_id, messages 完整体, params}` 一行（不含密钥）。统计：Spearman 相关、方向一致率（对同题两响应的排序一致性）、分差分布。产物 `reports/b_judge_consistency_n50.json`（b_ 前缀——AMENDMENT-31）。

**验收**：`PYTHONPATH=src python -m abcr.judge.consistency --pool <表达检产物> --n 50` 产出 JSON；mock 测试覆盖解析失败路径。

### B2-11 翻转 demo 脚本 b_flip_demo.py（1h）

**目标**：云日 #1 晚间楠向爱人展示的素材：同题在 +coef / baseline / −coef 三条件下的输出并排 + trait 分。

```python
#!/usr/bin/env python3
"""scripts/b_flip_demo.py — steering 行为翻转 demo 生成器。
输入：官方 eval_persona 三份产物 CSV（baseline / +coef / -coef，列：
question,prompt,answer,question_id,{trait},coherence）。
输出：demos/flip_demo_<trait>.md —— 按 trait 分差 top-k 题并排展示。
用法：python scripts/b_flip_demo.py --trait optimistic \
        --baseline eval_persona_eval/.../optimistic.csv \
        --pos steer_pos.csv --neg steer_neg.csv --topk 3
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trait", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--pos", required=True)
    ap.add_argument("--neg", required=True)
    ap.add_argument("--topk", type=int, default=3)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    t = a.trait
    base = pd.read_csv(a.baseline).groupby("question_id").first()
    pos = pd.read_csv(a.pos).groupby("question_id").first()
    neg = pd.read_csv(a.neg).groupby("question_id").first()
    common = base.index.intersection(pos.index).intersection(neg.index)
    gap = (pos.loc[common, t] - neg.loc[common, t]).sort_values(ascending=False)
    lines = [f"# Steering 翻转 demo · trait={t}", "",
             "> exploratory / rig-validation —— 演示素材，不构成任何假设的证据", ""]
    for qid in gap.index[: a.topk]:
        lines += [f"## {qid}（trait 分：+coef {pos.loc[qid, t]:.0f} ｜ baseline "
                  f"{base.loc[qid, t]:.0f} ｜ -coef {neg.loc[qid, t]:.0f}）",
                  f"**题目**：{base.loc[qid, 'question']}", "",
                  f"**正向注入**：{pos.loc[qid, 'answer']}", "",
                  f"**基线**：{base.loc[qid, 'answer']}", "",
                  f"**负向注入**：{neg.loc[qid, 'answer']}", ""]
    out = Path(a.out or f"demos/flip_demo_{t}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"written {out}")


if __name__ == "__main__":
    main()
```

**验收**：对三份手造小 CSV 跑通，markdown 结构正确、含 exploratory 标注。

### B2-12 20 题 temp0 双引擎 parity 烟检（云日 #2 内执行，脚本先备好，1h）

`scripts/b_parity_smoke.py`：dev split 前 20 题（排序后 item_id），temp0、vanilla 臂：引擎 A = transformers（rig runner 通路）；引擎 B = vLLM（`LLM(model=..., enforce_eager=True)`，官方 venv 里现成 vllm 0.8.5.post1，greedy SamplingParams(temperature=0, max_tokens=512)）。逐题比对：output_text 精确一致率、is_correct 一致率、分歧样例全文。产物 `reports/b_parity_smoke_20.json`（b_ 前缀——AMENDMENT-31）。**预期就是会有分歧**（vLLM 默认非确定性/数值路径不同）——这不是失败，是给 W2 分引擎设计的事实依据；如实记录即可。**验收**：产物 JSON 含逐题记录 + 两个一致率数字。

### B2-13 云日执行（两个整天；runbook 全文见 §7）

云日是阶段2 的科学载荷主交付。云日 #1 走**人工派发合法降级**（不等控制面，目标尽早出 demo；上位决策 D12）；云日 #2 走**完整闭环**（信封→dispatch→runner→scorer→回传→A 审计）。执行时把 §7 打印出来逐行走，每步完成在 runbook 副本上打勾并记实际值（实例号/时价/耗时/产物 sha256），收工把打勾副本存 `reports/b_cloudday{1,2}_log.md`——这就是 G6 预算证据与关机核验证据。

---
## 7. 专项章：两个云日 runbook（可打印逐行执行）

通用约定：供应商 = AutoDL 类网页控制台，24GB 卡（4090 级），**楠开机付费=发射钮**；镜像选 Python 3.10–3.12 + CUDA 12.x + torch 预装款（若纯净镜像也可，requirements 会装 torch 2.6.0/cu124）。境内机房必设 `HF_ENDPOINT=https://hf-mirror.com`（境外机房可直连则不设）。**checkpoint 常态化、产物即时回传+哈希校验、完成即关机**。**长跑纪律（AMENDMENT-28④）**：长跑段每 30 分钟在 Mac 侧跑一次 `PYTHONPATH=src python -m abcr.ops.watchdog --once`、每 60 分钟做一次预算检查（读 costs/instances 链累计实耗 + 进行中实例 时价×已运行小时 估计，对照 85% 线；A 的 check_fuse 可用即用）；**每完成一个阶段即增量回传该阶段产物（rsync/scp + sha256 记录），不等收工一次性打包**。W1 云预算顶 **¥150**，85% 熔断线（累计 ¥127.5 时停止新开任务、只收尾回传）。judge 模型名下文写 `deepseek-chat` 占位，**实际以 `reports/b_judge_smoke.json` 的 `chosen_judge_model` 为准**。SSH 端口/主机以控制台实例页为准（下文记 `<host>`/`<port>`）。

### 7.1 云日 #1 runbook —— 官方 trait 五阶段复现 + 对表校准 + 翻转 demo（人工派发合法降级：不走信封，不等控制面；trait 默认 optimistic，备选 sycophantic）

**第 0 步（云日前晚，Mac 上全部完成）**
命令/动作：① B1-9 vendor clone 已在、两补丁内容已在 `reports/b_vendor_patches.md`；② B1-10 judge 冒烟已过、chosen_judge_model 已定；③ 打包上云物料：`cd /Users/superagent/abcr-vendor && tar czf ~/pv_src.tar.gz persona_vectors`（含 dataset 解包与否均可，eval 不需要 dataset）；④ 备好 `scripts/b_cloud_bootstrap.sh`；⑤ 与楠约定次日开机时段。
预期产物：`~/pv_src.tar.gz`；冒烟 JSON。
失败处置：冒烟未过 → 云日顺延，先走降级链（B1-10）。

**第 1 步：开机 + 账本登记（楠操作控制台，你在 Mac 记账）**
动作：楠在控制台租 24GB 卡开机，报你：实例号、GPU 型号、时价、SSH host/port/密码。你立即执行：

```bash
cd /Users/superagent/abcr-wt/b && source /Users/superagent/abcr/.venv/bin/activate
PYTHONPATH=src python scripts/b_instance.py register --instance-id autodl-<实例号> \
  --vendor autodl --spec "<型号>-24G" --price-cny-per-hour <时价> --batch-id manual-cloudday1
PYTHONPATH=src python scripts/b_instance.py start --instance-id autodl-<实例号>
```

预期产物：`ledger/instances.jsonl` 两条事件。批次号用 `manual-cloudday1`（人工派发降级，无信封——这是 D12 决策的合法路径，账本仍留痕）。
失败处置：无卡可租 → 换供应商同类卡；时价 >¥3.5/h → 报楠确认预算。

**第 2 步：SSH 环境核对**

```bash
ssh -p <port> root@<host>
nvidia-smi                       # 预期：24GB 卡在位，驱动 CUDA ≥12.4
python3 -V                       # 预期：3.10–3.12；若 >=3.13 → 换镜像或 conda create -n py312 python=3.12
df -h /root                      # 预期：余 ≥60GB（模型 15GB + venv 10GB + 产物）
```

失败处置：驱动过旧/过新致后续 vllm 装不上 → 换镜像重开机（记入账本 stop/register 新实例）。

**第 3 步：代码上云 + 打补丁**

```bash
# Mac：
scp -P <port> ~/pv_src.tar.gz root@<host>:/root/
# 云上：
cd /root && tar xzf pv_src.tar.gz && cd persona_vectors
git rev-parse HEAD               # 预期：b8e0f044fe2410a6fad579f38324f03f13b4e917
# 打补丁（B1-9 预研的两处；改完 git diff 存证）：
#   补丁1: config.py HF_TOKEN 可选化（缺 token 只告警不 raise；不传空 token 给 hub）
#   补丁2: generate_vec.py from_pretrained 加 torch_dtype=torch.bfloat16
git diff > /root/vendor_patches_applied.diff
```

预期产物：`/root/vendor_patches_applied.diff`（回传后并入 `reports/b_vendor_patches.md`——补丁谱系记录，D6/D7）。
失败处置：文件结构与预研不符（不可能，commit 已钉死）→ 停，核对 checkout。

**第 4 步：环境安装（官方 requirements 精确 pin）**

```bash
cd /root/persona_vectors
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # 精确 pin：torch==2.6.0 vllm==0.8.5.post1 transformers==4.52.3
                                  # accelerate==1.7.0 openai==1.70.0 等；≈10-20 分钟
python -c "import vllm, torch; print(vllm.__version__, torch.__version__, torch.cuda.is_available())"
# 预期：0.8.5.post1 2.6.0 True
```

失败处置：pip 慢 → `-i https://pypi.tuna.tsinghua.edu.cn/simple`（AutoDL 学术加速亦可）；vllm 装上但 import 报 CUDA 不匹配（Blackwell 级新卡）→ 换 4090 实例（vllm 0.8.5 需要计算能力 ≥7.0 且对过新硬件可能无 wheel）。

**第 5 步：.env 配置（judge 改道 DeepSeek，零代码）**

```bash
cd /root/persona_vectors && cp .env.example .env
# 编辑 .env 为（三行；key 值从 Mac 的 abcr/.env 人工带过来，勿走聊天记录明文）：
#   OPENAI_API_KEY=<DeepSeek key>
#   OPENAI_BASE_URL=https://api.deepseek.com
#   WANDB_PROJECT=persona-vectors
# HF_TOKEN 整行删掉（补丁1 已使其可选）
export HF_ENDPOINT=https://hf-mirror.com     # 境内机房必设；写进 ~/.bashrc 防断连丢失
export WANDB_MODE=disabled
```

原理（侦查确认）：官方 judge.py 模块级 `openai = AsyncOpenAI()` 零参构造，从环境读 OPENAI_API_KEY/OPENAI_BASE_URL；config.load_env_file 会把 .env 全部 KEY=VALUE 注入 os.environ 且发生在构造之前——所以这是**零代码改道**。
失败处置：无。

**第 6 步：模型预下载（后台先行）**

```bash
python - <<'EOF'
import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from huggingface_hub import snapshot_download
p = snapshot_download("Qwen/Qwen2.5-7B-Instruct")
print("SNAPSHOT:", p)    # 路径含 snapshots/<commit> —— 记下 commit，回 Mac 钉入 configs/models/qwen25_7b.json
EOF
```

预期：≈15GB，10–30 分钟。失败处置：hf-mirror 限速/缺仓 → 试 modelscope（modelscope.cn 已入白名单——AMENDMENT-26；`pip install modelscope && python -c "from modelscope import snapshot_download; print(snapshot_download('Qwen/Qwen2.5-7B-Instruct'))"`，然后后续命令 `--model` 改用本地路径）。

**第 7 步：5% smoke（单 trait 单 instruction 2 响应走通阶段 2）**

```bash
cd /root/persona_vectors && source .venv/bin/activate
python - <<'EOF'
import json
src = json.load(open("data_generation/trait_data_extract/optimistic.json"))
smoke = {"instruction": src["instruction"][:1], "questions": src["questions"][:2],
         "eval_prompt": src["eval_prompt"]}
json.dump(smoke, open("data_generation/trait_data_extract/optimistic_smoke.json", "w"), indent=2)
EOF
CUDA_VISIBLE_DEVICES=0 python -m eval.eval_persona \
    --model Qwen/Qwen2.5-7B-Instruct \
    --trait optimistic_smoke \
    --output_path smoke/optimistic_smoke.csv \
    --persona_instruction_type pos \
    --assistant_name optimistic \
    --judge_model deepseek-chat \
    --version extract \
    --n_per_question 2 \
    --max_concurrent_judges 5
head -3 smoke/optimistic_smoke.csv
```

预期产物：`smoke/optimistic_smoke.csv` 4 行数据（1 instruction × 2 题 × 2 响应），`optimistic_smoke` 与 `coherence` 两列均为非空数字。
失败处置：judge 列全空/None → 检查 .env 与模型名（回看冒烟 JSON）；vLLM OOM → 确认无残留进程 `nvidia-smi` 后重试；**smoke 不过不许进第 8 步**（云纪律：5% smoke 后才全量）。

**第 8 步：五阶段全量（官方命令逐字，仅替换 model/judge/trait；全部在仓库根目录执行）**

```bash
# ---- 阶段1: 基线评测（注意必须显式 --version eval，main 默认是 extract）----
CUDA_VISIBLE_DEVICES=0 python -m eval.eval_persona \
    --model Qwen/Qwen2.5-7B-Instruct \
    --trait optimistic \
    --output_path eval_persona_eval/Qwen2.5-7B-Instruct/optimistic.csv \
    --judge_model deepseek-chat \
    --version eval \
    --max_concurrent_judges 20

# ---- 阶段2: 正/负系统提示词提取（pos / neg 各一跑）----
CUDA_VISIBLE_DEVICES=0 python -m eval.eval_persona \
    --model Qwen/Qwen2.5-7B-Instruct \
    --trait optimistic \
    --output_path eval_persona_extract/Qwen2.5-7B-Instruct/optimistic_pos_instruct.csv \
    --persona_instruction_type pos \
    --assistant_name optimistic \
    --judge_model deepseek-chat \
    --version extract \
    --max_concurrent_judges 20

CUDA_VISIBLE_DEVICES=0 python -m eval.eval_persona \
    --model Qwen/Qwen2.5-7B-Instruct \
    --trait optimistic \
    --output_path eval_persona_extract/Qwen2.5-7B-Instruct/optimistic_neg_instruct.csv \
    --persona_instruction_type neg \
    --assistant_name pessimistic \
    --judge_model deepseek-chat \
    --version extract \
    --max_concurrent_judges 20
# assistant_name 官方规则：pos 用 trait 形容词；neg 有明确反义词用反义词（optimistic→pessimistic），
# 否则用 helpful。系统提示词拼式："You are a/an {assistant_name} assistant. {instruction}"

# ---- 阶段3: 差分均值向量（先看阶段2 csv 分数再跑：过滤条件 pos>=50 且 neg<50 且双方 coherence>=50，
#      过滤后为空会在 torch.cat 处报错）----
python - <<'EOF'
import pandas as pd
for p in ("pos", "neg"):
    df = pd.read_csv(f"eval_persona_extract/Qwen2.5-7B-Instruct/optimistic_{p}_instruct.csv")
    print(p, "n=", len(df), "trait mean=", df["optimistic"].mean(), "coherence mean=", df["coherence"].mean())
EOF
CUDA_VISIBLE_DEVICES=0 python generate_vec.py \
    --model_name Qwen/Qwen2.5-7B-Instruct \
    --pos_path eval_persona_extract/Qwen2.5-7B-Instruct/optimistic_pos_instruct.csv \
    --neg_path eval_persona_extract/Qwen2.5-7B-Instruct/optimistic_neg_instruct.csv \
    --trait optimistic \
    --save_dir persona_vectors/Qwen2.5-7B-Instruct/ \
    --threshold 50

# ---- 阶段4: 推理时转向评测（系数扫描 + 负向；transformers bf16 路径，比 vLLM 慢属预期）----
for COEF in 1.5 2.0 2.5 -2.0; do
CUDA_VISIBLE_DEVICES=0 python -m eval.eval_persona \
    --model Qwen/Qwen2.5-7B-Instruct \
    --trait optimistic \
    --output_path eval_persona_eval/steering/optimistic_layer20_coef${COEF}.csv \
    --judge_model deepseek-chat \
    --version eval \
    --steering_type response \
    --coef ${COEF} \
    --vector_path persona_vectors/Qwen2.5-7B-Instruct/optimistic_response_avg_diff.pt \
    --layer 20 \
    --max_concurrent_judges 20
done

# ---- 阶段5: 投影计算（结果列就地写回 file_path）----
CUDA_VISIBLE_DEVICES=0 python -m eval.cal_projection \
    --file_path eval_persona_eval/Qwen2.5-7B-Instruct/optimistic.csv \
    --vector_path persona_vectors/Qwen2.5-7B-Instruct/optimistic_response_avg_diff.pt \
    --layer 20 \
    --model_name Qwen/Qwen2.5-7B-Instruct \
    --projection_type proj
```

预期产物：阶段1 `eval_persona_eval/Qwen2.5-7B-Instruct/optimistic.csv`（20 题 ×10 响应 + trait/coherence 列）；阶段2 两 CSV（各 100 题位 ×10 响应）；阶段3 `persona_vectors/Qwen2.5-7B-Instruct/optimistic_{prompt_avg_diff,response_avg_diff,prompt_last_diff}.pt`（论文用 response_avg_diff；形状 [29, 3584]）；阶段4 四 CSV；阶段5 基线 CSV 就地新增投影列。
时间预算（粗）：阶段1 ≈15min；阶段2 ≈2×30min；阶段3 ≈15min；阶段4 ≈4×20min；阶段5 ≈10min——合计 ≈3.5h GPU。
**增量回传（AMENDMENT-28④）**：每个阶段命令完成后立即回传该阶段产物，不等第 11 步一次性打包——Mac 上 `rsync -avz -e "ssh -p <port>" root@<host>:/root/persona_vectors/<该阶段产物目录>/ reports/cloud/day1-incr/<同名目录>/`（rsync 不可用则 scp 对应 CSV/.pt），每次回传后 `shasum -a 256` 记录进打勾副本——实例被回收也不丢已完成阶段。长跑期间同步执行 §7 通用约定的 30min watchdog / 60min 预算检查。
失败处置：`output_path 已存在被跳过（只打印均值）` → 加 `--overwrite` 或换路径；阶段3 torch.cat 报空 → 阶段2 分数分布不过滤线，检查 judge 是否大量 None（冒烟降级链）或 pos/neg 提示词失效（打印几条 answer 人工看）；阶段4 OOM → 确认阶段2 的 vLLM 进程已退出（分开的命令本不冲突，但同 shell 后台残留会占 90% 显存）；DeepSeek 429 → `--max_concurrent_judges 10`。

**第 9 步：对表校准判据（G3；判据为本包工程定标，exploratory——官方论文数值不在手，对"方向与量级"不对"绝对数"）**

```bash
python - <<'EOF'
import pandas as pd, glob
base = pd.read_csv("eval_persona_eval/Qwen2.5-7B-Instruct/optimistic.csv")["optimistic"].mean()
print(f"baseline trait mean = {base:.1f}")
for f in sorted(glob.glob("eval_persona_eval/steering/optimistic_layer20_coef*.csv")):
    df = pd.read_csv(f)
    print(f, "trait=", round(df["optimistic"].mean(), 1), "coherence=", round(df["coherence"].mean(), 1))
EOF
```

判据（全过 = 校准通过，记 `reports/b_cloudday1_log.md`）：① 正系数区间 trait 均分随 coef 单调上行（允许一处非单调，记录）；② coef=+2.0 的 trait 均分 ≥ baseline + 20（0–100 分制）；③ coef=−2.0 的 trait 均分 ≤ baseline − 10；④ 正系数区间 coherence 均分 ≥ 70 且相对 baseline 降幅 ≤ 15。
失败处置：方向对但量级不足 → layer 换 16/24 各补一跑（记录，仍不足报 BLOCKER）；方向反 → 停，检查 pos/neg CSV 是否被换位（generate_vec 的 pos_path/neg_path 参数顺序）；coherence 崩（<50）→ 系数收缩到 1.0/1.5 重扫。

**第 10 步：翻转 demo 生成（同题 ±系数并排 + trait 分）**

```bash
# 云上先把三份 csv 传回 Mac（见第 11 步），demo 在 Mac 出（pandas 在 abcr venv 里有）：
cd /Users/superagent/abcr-wt/b && source /Users/superagent/abcr/.venv/bin/activate
PYTHONPATH=src python scripts/b_flip_demo.py --trait optimistic \
  --baseline reports/cloud/day1/eval_persona_eval/Qwen2.5-7B-Instruct/optimistic.csv \
  --pos reports/cloud/day1/eval_persona_eval/steering/optimistic_layer20_coef2.0.csv \
  --neg reports/cloud/day1/eval_persona_eval/steering/optimistic_layer20_coef-2.0.csv \
  --topk 3
```

预期产物：`demos/flip_demo_optimistic.md`（晚间展示素材，含 exploratory 标注）。

**第 11 步：产物回传 + 哈希校验**

```bash
# 云上：
cd /root/persona_vectors
tar czf /root/cloudday1_artifacts.tar.gz eval_persona_eval eval_persona_extract \
  persona_vectors smoke ../vendor_patches_applied.diff
sha256sum /root/cloudday1_artifacts.tar.gz        # 记下哈希
# Mac：
mkdir -p /Users/superagent/abcr-wt/b/reports/cloud
scp -P <port> root@<host>:/root/cloudday1_artifacts.tar.gz reports/cloud/
shasum -a 256 reports/cloud/cloudday1_artifacts.tar.gz    # 必须与云上一致，不一致重传
mkdir -p reports/cloud/day1 && tar xzf reports/cloud/cloudday1_artifacts.tar.gz -C reports/cloud/day1
```

**第 12 步：完成即关机核验 + 账本收口**
动作：① 核验清单三项（产物回传哈希一致 / 楠在控制台关机后 `ssh -p <port> root@<host>` 拒连 / 控制台账单读实耗）；② 记账：

```bash
PYTHONPATH=src python scripts/b_instance.py stop --instance-id autodl-<实例号> \
  --amount-cny <账单实耗> --verified-by "回传sha256一致+ssh拒连+控制台已停"
```

③ 把 `vendor_patches_applied.diff` 并入 `reports/b_vendor_patches.md`；把 7B revision 钉入 `configs/models/qwen25_7b.json`；打勾副本存 `reports/b_cloudday1_log.md`；commit（`[pkgB] cloud day 1 artifacts + calibration log`）。
失败处置：楠忘关机 → 你没有控制台权限，**当晚必须提醒直到确认**；instance_idle_alert 演练数据也在此场景补录。

### 7.2 云日 #2 runbook —— 3 锚 trait 抽取 + 表达检 + 小系数扫描 + abcr rig 7B mini 环（完整闭环）+ parity 烟检

**第 0 步（前置，全部在 Mac 完成后才可开机）**
① 三 trait 工件已过楠目检并冻结入 `data/traits/`（B1-11）；② R1 已过、B2-1~B2-8 完成、黄金测试绿；③ mini 环三 config 写好 `configs/experiments/mini_7b_{vanilla,persona,inject}.json`（seeds [1,2]，item_limit 50，dev split；inject 臂 vector_path 指向云日抽取产物的仓库内落位 `data/vectors/<trait>_response_avg_diff.pt`（B 拥有的非冻结区——AMENDMENT-27）——先占位，第 6 步现场填实际 coef/layer）；④ **楠签发 mini 环信封**：C 的 `abcrctl draft` + `abcrctl approve`（走 C 包流程；若 abcrctl 有故障，由**楠（或 C 窗口）**按 §3.4 格式手工起草并 approve——B 仅接收已签发信封文件，不参与起草与签发，AMENDMENT-31）；⑤ 物料打包：

```bash
cd /Users/superagent/abcr-wt/b
git bundle create /Users/superagent/abcr-wt/b/reports/cloud/abcr-pkgb.bundle pkg/b
# 待 scp 清单：abcr-pkgb.bundle、pv_src.tar.gz（含已打补丁 vendor 亦可现场再打）、
#   configs/envelopes/<批次>.json（已签发）、state/approval.key（0600，验签用；
#   HMAC 对称密钥上云属 W1 接受的折衷——实例短生命周期，收工可轮换密钥）
```

**第 1–5 步：同 7.1 第 1–6 步**（开机登记（batch-id 用真实信封批次号）→ SSH 核对 → vendor 上云打补丁 → requirements → .env/HF_ENDPOINT → 7B 预下载）。若续用云日 #1 的保留镜像/数据盘则跳装机，只核 `git rev-parse HEAD` 与 `pip list | grep -E "vllm|torch"`。

**第 5.5 步：5% smoke（AMENDMENT-28⑤——全量抽取前必过，云纪律：5% smoke 后才全量）**
照抄 7.1 第 7 步式样，trait 换锚 trait conscientiousness：先单发 `scp -P <port> data/traits/conscientiousness_extract.json root@<host>:/root/persona_vectors/data_generation/trait_data_extract/conscientiousness.json`（即第 6 步 scp 循环中该 trait 的一件，提前上），再截 1 instruction + 2 questions 生成 `conscientiousness_smoke.json`，跑单 instruction × 2 题 × 2 响应的 extract（`--trait conscientiousness_smoke --version extract --n_per_question 2 --max_concurrent_judges 5`）。判据同 7.1 第 7 步：产物 CSV 4 行数据、trait 与 coherence 两列均为非空数字。**不过不得进第 6 步全量**，按 7.1 第 7 步处置链处理（查 .env/模型名 → 冒烟 JSON → 降级链）。云日 #2 多为新租实例 + 首次使用自产 trait 工件，恰是最需要 smoke 的场景。

**第 6 步：3 锚 trait 工件入位 + 抽取 + 向量（×3 trait）**

```bash
# Mac：把冻结工件推上云（extract/eval 两份 → 官方两目录，文件名=trait 名）：
for T in conscientiousness openness neuroticism; do
  scp -P <port> data/traits/${T}_extract.json root@<host>:/root/persona_vectors/data_generation/trait_data_extract/${T}.json
  scp -P <port> data/traits/${T}_eval.json    root@<host>:/root/persona_vectors/data_generation/trait_data_eval/${T}.json
done
# 云上（注意 neg 的 assistant_name：conscientiousness→careless, openness→closed-minded,
#       neuroticism→calm；拿不准用 helpful 兜底档）：
cd /root/persona_vectors && source .venv/bin/activate
declare -A NEGNAME=([conscientiousness]=careless [openness]=closed-minded [neuroticism]=calm)
for T in conscientiousness openness neuroticism; do
  CUDA_VISIBLE_DEVICES=0 python -m eval.eval_persona --model Qwen/Qwen2.5-7B-Instruct \
    --trait $T --output_path eval_persona_extract/Qwen2.5-7B-Instruct/${T}_pos_instruct.csv \
    --persona_instruction_type pos --assistant_name $T \
    --judge_model deepseek-chat --version extract --max_concurrent_judges 20
  CUDA_VISIBLE_DEVICES=0 python -m eval.eval_persona --model Qwen/Qwen2.5-7B-Instruct \
    --trait $T --output_path eval_persona_extract/Qwen2.5-7B-Instruct/${T}_neg_instruct.csv \
    --persona_instruction_type neg --assistant_name ${NEGNAME[$T]} \
    --judge_model deepseek-chat --version extract --max_concurrent_judges 20
  CUDA_VISIBLE_DEVICES=0 python generate_vec.py --model_name Qwen/Qwen2.5-7B-Instruct \
    --pos_path eval_persona_extract/Qwen2.5-7B-Instruct/${T}_pos_instruct.csv \
    --neg_path eval_persona_extract/Qwen2.5-7B-Instruct/${T}_neg_instruct.csv \
    --trait $T --save_dir persona_vectors/Qwen2.5-7B-Instruct/ --threshold 50
done
```

预期产物：每 trait 三个 .pt（用 `_response_avg_diff.pt`）。时间 ≈3×45min。**for 循环结束即增量回传（AMENDMENT-28④）**：Mac 上 `rsync -avz -e "ssh -p <port>" root@<host>:/root/persona_vectors/{eval_persona_extract,persona_vectors} reports/cloud/day2-incr/` + sha256 记录，再进第 7 步。
失败处置：某 trait 过滤后空 → 打印该 trait pos/neg CSV 的 trait 分均值；若 pos 不高（工件 instruction 太弱）→ 该 trait 降级弃用（W1 只需 ≥1 锚 trait 过表达检，三选一容错），记 PROGRESS。

**第 7 步：表达检数据生成（steering ±两向 + baseline，eval 题集，每题 3 响应）**

```bash
for T in conscientiousness openness neuroticism; do
  CUDA_VISIBLE_DEVICES=0 python -m eval.eval_persona --model Qwen/Qwen2.5-7B-Instruct \
    --trait $T --output_path eval_persona_eval/Qwen2.5-7B-Instruct/${T}_baseline.csv \
    --judge_model deepseek-chat --version eval --n_per_question 3 --max_concurrent_judges 20
  for COEF in 2.0 -2.0; do
    CUDA_VISIBLE_DEVICES=0 python -m eval.eval_persona --model Qwen/Qwen2.5-7B-Instruct \
      --trait $T --output_path eval_persona_eval/steering/${T}_layer20_coef${COEF}.csv \
      --judge_model deepseek-chat --version eval --steering_type response --coef ${COEF} \
      --vector_path persona_vectors/Qwen2.5-7B-Instruct/${T}_response_avg_diff.pt \
      --layer 20 --n_per_question 3 --max_concurrent_judges 20
  done
done
```

预期：9 份 CSV（3 trait × {baseline,+2,−2}），每份 20 题 ×3 响应。盲评（B2-9）回 Mac 后做——此处 CSV 里的 trait 分是官方在线 judge 值，盲评会**独立重打**（judge 只见 question/answer，本就无条件字段；盲评再加随机顺序与解盲映射，A 审计可查）。
**小系数扫描**（对首选 trait，暂定 conscientiousness；exploratory）：

```bash
T=conscientiousness
for L in 16 20; do for COEF in 1.0 1.5 2.0; do
  CUDA_VISIBLE_DEVICES=0 python -m eval.eval_persona --model Qwen/Qwen2.5-7B-Instruct \
    --trait $T --output_path eval_persona_eval/sweep/${T}_layer${L}_coef${COEF}.csv \
    --judge_model deepseek-chat --version eval --steering_type response --coef ${COEF} \
    --vector_path persona_vectors/Qwen2.5-7B-Instruct/${T}_response_avg_diff.pt \
    --layer ${L} --n_per_question 2 --max_concurrent_judges 20
done; done
```

失败处置：时间不够 → 砍 layer 16 一档（保 2–3 系数 × 1 层的下限规格）。
**第 7 步两个 for 循环各自结束即增量回传（AMENDMENT-28④）**：`rsync -avz -e "ssh -p <port>" root@<host>:/root/persona_vectors/eval_persona_eval reports/cloud/day2-incr/` + sha256 记录。

**第 8 步：abcr rig 上云部署（git bundle）+ 7B mini 环走信封全链**

```bash
# 云上：
cd /root
git clone /root/abcr-pkgb.bundle abcr && cd abcr && git checkout pkg/b
python3 -m venv .venv-abcr && source .venv-abcr/bin/activate
pip install torch transformers accelerate pandas python-dotenv openai backoff pytest matplotlib
# （云上不装 duckdb/typer 等 Mac 全家桶；runner/dispatch/scorer 依赖的最小集）
mkdir -p state && cp /root/upload/approval.key state/approval.key && chmod 600 state/approval.key
cp /root/upload/<批次>.json configs/envelopes/
cat > .env <<'ENVEOF'
DEEPSEEK_API_KEY=<同前>
OPENAI_API_KEY=<同前>
OPENAI_BASE_URL=https://api.deepseek.com
HF_ENDPOINT=https://hf-mirror.com
ENVEOF
# 把向量放进 config 指向的位置（data/vectors/ 归 B、非冻结区——AMENDMENT-27；勿放 data/traits/，
# 那是冻结区、阶段2 起 Seatbelt 只读，写入会直接失败）：
mkdir -p data/vectors
cp /root/persona_vectors/persona_vectors/Qwen2.5-7B-Instruct/*_response_avg_diff.pt data/vectors/
# 现场把第 7 步选定的 coef/layer 填进 configs/experiments/mini_7b_inject.json（表达检方向清晰
# 且 coherence 未垮的那档），git commit 留痕（云上 repo 级身份：git config user.name abcr-cloud）
# ⚠️ 显式偏离标注（AMENDMENT-31）：本处 trait/coef 选择依据 = 在线非盲 judge 分，属校准动作
#   非证据；盲评（第 11 步）若方向翻转，mini 环仅按 rig 验证引用，并在 PROGRESS 记录此偏离。
# 环境自检 + 黄金测试（7B CUDA 复跑，顺带闭掉 Mac MPS 待验项）：
PYTHONPATH=src pytest tests/contract -q
PYTHONPATH=src pytest tests/rig -m golden -q
# mini 环发射（50 题 × 3 臂 × 2 seed；账本为云侧独立链段）：
PYTHONPATH=src python -m abcr.ops.dispatch --envelope configs/envelopes/<批次>.json --key state/approval.key
PYTHONPATH=src python -m abcr.ops.watchdog --once     # 跑完扫一遍：预期零异常
```

预期产物：`data/runs/<run_id>×3/`（3 config = 3 run，seeds 在 run 内循环——AMENDMENT-29；manifest/steps/scores/activations 四件齐；inject 臂有投影 npz 抽样）；云侧 `ledger/` 相关链事件齐、链自洽。时间 ≈40–90min（300 生成 + 评分）。
**设计说明（已批：AMENDMENT-2）**：云侧账本是**独立哈希链段**（从 GENESIS 起链），回传后整目录落 Mac worktree 的 `ledger/cloud-day2/` 子目录，**不与 Mac 链拼接**；A（Auditor）对账时按段独立 verify_chain：验证云侧链自洽 + 回传哈希 + 与 data/runs 产物互指一致。
失败处置：dispatch 中途断（卡回收/断连）→ 重连后**原命令重跑**（幂等续跑正是为此建的）；黄金测试 CUDA 红 → 停 mini 环，报 BLOCKER（hook 正确性是硬门）；时间不够 → 砍题量 50→30（止损预案，记 PROGRESS）。

**第 9 步：20 题 temp0 双引擎 parity 烟检**

```bash
cd /root/abcr && source .venv-abcr/bin/activate
pip install vllm==0.8.5.post1     # 与官方同 pin；装进 abcr venv（≈5-10 分钟）
PYTHONPATH=src python scripts/b_parity_smoke.py \
  --model Qwen/Qwen2.5-7B-Instruct --family ifeval_zh_v1 --n 20 --out reports/b_parity_smoke_20.json
```

预期产物：`reports/b_parity_smoke_20.json`（逐题两引擎输出 + 精确一致率 + is_correct 一致率 + 分歧样例）。分歧非失败，如实记录（W2 分引擎设计的事实依据）。
失败处置：vllm 与 abcr venv 依赖冲突 → 退而在官方 venv 里跑 vLLM 侧、abcr venv 跑 transformers 侧，脚本支持 `--side` 分跑两次合并。

**第 10 步：全量回传 + 哈希校验**

```bash
# 云上：
cd /root && tar czf cloudday2_artifacts.tar.gz \
  persona_vectors/eval_persona_extract persona_vectors/eval_persona_eval \
  persona_vectors/persona_vectors \
  abcr/data/runs abcr/ledger abcr/state/runs abcr/reports
sha256sum cloudday2_artifacts.tar.gz
# Mac：
scp -P <port> root@<host>:/root/cloudday2_artifacts.tar.gz reports/cloud/
shasum -a 256 reports/cloud/cloudday2_artifacts.tar.gz     # 与云上一致
mkdir -p reports/cloud/day2 && tar xzf reports/cloud/cloudday2_artifacts.tar.gz -C reports/cloud/day2
# 落位（供 A 审计与复现包）：
cp -R reports/cloud/day2/abcr/data/runs/* data/runs/
mkdir -p ledger/cloud-day2 && cp reports/cloud/day2/abcr/ledger/*.jsonl ledger/cloud-day2/
```

**第 11 步（Mac）：表达检盲评 + n=50 双 judge 一致性**

```bash
PYTHONPATH=src python -m abcr.judge.blind_protocol \
  --inputs reports/cloud/day2/persona_vectors/eval_persona_eval --traits conscientiousness,openness,neuroticism
# 预期：reports/b_expression_check_<trait>.png ×3 + reports/b_expression_check.json（效应量、方向判定）
ollama pull gemma3 && ollama stop qwen3:8b 2>/dev/null || true
PYTHONPATH=src python -m abcr.judge.consistency \
  --pool reports/cloud/day2/persona_vectors/eval_persona_eval --n 50
# 预期：reports/b_judge_consistency_n50.json（Spearman、方向一致率、deviation 注记）
```

G4 判定：≥1 个锚 trait 盲评下 steered-pos 明显高于 baseline 与 steered-neg（方向清晰 + 效应量 + 逐题分布图在案）。

**第 12 步：完成即关机核验 + 账本收口**：同 7.1 第 12 步（stop + cost + verified-by 三项）。**如第 0 步已把 approval.key 上过云：请楠考虑轮换密钥**（删 `state/approval.key`，abcrctl 首用重生成，未消费令牌作废重签）。打勾副本存 `reports/b_cloudday2_log.md`，commit。之后通知 A（经 PROGRESS/楠）对 mini 环批次跑审计——批次 `batch_audited` 由 A 落。

---
## 8. 测试与验收总表（R1/R2 门中你的全部判据项，逐条可执行核验）

### 8.1 R1 门（阶段1 末；核验环境：worktree 根 + venv 激活 + `export PYTHONPATH=src`）

| # | 判据 | 核验命令 | 预期 |
|---|---|---|---|
| R1-B1 | 契约测试全绿 | `pytest tests/contract -q` | 全绿，零跳过 |
| R1-B2 | 本包单元测试全绿 | `pytest tests/ops tests/rig -q -m "not golden"` | 全绿 |
| R1-B3 | 坏令牌 fail-closed | dispatch 对坏令牌样例 fixtures/envelope_fixture_badtoken.json（见 B1-5 验收） | 退出码 2、batches 链落 `batch_dispatch_rejected`（payload 原因码 + subject_id）、告警文件在（双留痕——AMENDMENT-13）、runs_index 无新事件 |
| R1-B4 | fixture 信封全链 | `bash scripts/b_r1_selfcheck.sh` | `R1 SELFCHECK PASS` |
| R1-B5 | crash 断点续跑 | 同上（内含）；另查 crash run 事件序 | `run_failed→run_resumed→run_completed`；(item,seed) 无重复 |
| R1-B6 | 心跳落账 | `grep -c step_progress ledger/runs_index.jsonl` | 12（6 run × 2） |
| R1-B7 | 分数与期望一致 | B1-6 diff 命令 | 空输出 |
| R1-B8 | 账本链自洽 | `python -c "...verify_chain()..."`（B1-8 断言脚本内含） | 不抛 LedgerTampered |
| R1-B9 | watchdog 检出停摆并冷却去重 | `pytest tests/ops/test_watchdog.py -q` | 全绿 |
| R1-B10 | dispatch 幂等 | 对已完成信封重跑 dispatch | 打印 already-settled、零新执行、零重复事件、退出码 0、不触碰令牌（已结批次短路在令牌校验之前——AMENDMENT-23） |

### 8.2 R2 门（阶段2 末）

| # | 判据 | 核验命令/证据 | 预期 |
|---|---|---|---|
| R2-B1 | 杀进程恢复演练 | 真 run 进行中 `kill -9 <pid>` → 原命令重跑 | 续跑收敛，无重复 (item,seed)，账本事件序含 failed→resumed |
| R2-B2 | skip_ledger_writes 旋钮可用 | `ABCR_FAKETASK_SKIP_LEDGER_WRITES=1` 跑 fixture | run "完成"但 steps 缺行——供 A 审计拦截演练 |
| R2-B3 | 实例空转告警数据 | `b_instance.py idle-sim` | instances.jsonl 出 `instance_idle_alert`（payload 带 actor="drill"——AMENDMENT-17） |
| R2-B4 | 黄金测试四件 + 合成轨迹 | `pytest tests/rig -m golden -q`（Mac 3B + 云 7B 各一遍） | 全绿（Mac MPS 红须有云 CUDA 绿证据） |
| R2-B5 | ifeval_zh_v1 定稿 | `python scripts/b_gen_ifeval.py --selfcheck`；split hash 已入 git | 250 题 500 断言全过；`data/splits/ifeval_zh_v1.json` 在 git |
| R2-B6 | 7B mini 环全链 | 云日 #2 第 8 步产物 + 云侧账本链自洽 + A 审计报告 | 3 run（= 3 臂 config，seeds [1,2] 在 run 内循环——AMENDMENT-29）全 SCORED；A 出报告 |
| R2-B7 | 云日 #1 校准 + demo | `reports/b_cloudday1_log.md` 四判据 + `demos/flip_demo_*.md` | 判据全过（或偏差已记录并经 fable 裁决） |
| R2-B8 | 表达检（G4） | `reports/b_expression_check.json` + 三张 png | ≥1 锚 trait 方向清晰 + 效应量在案 |
| R2-B9 | 双 judge 一致性 | `reports/b_judge_consistency_n50.json` | n=50 在案，deviation 注记完整 |
| R2-B10 | parity 烟检 | `reports/b_parity_smoke_20.json` | 20 题逐题记录 + 两个一致率 |
| R2-B11 | 预算（G6） | `ledger/costs.jsonl` + `instances.jsonl` + 两份云日 log | 实耗合计 ≤¥150；每实例 stop 事件带 verified 三项 |
| R2-B12 | 温 0 双跑一致（G1 B 侧） | runner `--temp0-once` 连跑两遍 diff | 逐题 output_text 与判分一致 |
| R2-B13 | 激活抽样通路 | mini 环 inject 臂 run 目录 | 约 10% item 有 `activations/*.npz`（mean/p50/p90 键齐） |
| R2-B14 | 补丁谱系 | `reports/b_vendor_patches.md` | 两补丁 diff + 理由 + D6/D7 引用 |
| R2-B15 | judge 调用留痕（AMENDMENT-8） | 抽查 `data/runs/<run_id>/logs/judge_calls.jsonl` | 存在且每行 {ts, judge_model, item_id, messages 完整体, params}、不含密钥；被 A 防污染检查3 扫描通过 |

## 9. 代码规范与 PROGRESS.md 格式

**代码规范**：
- Python 一律 type hints 全签名（含返回值）；`from __future__ import annotations` 开头。
- 每个模块 docstring 首段说明**架构位置**（本文各代码块的 docstring 即范式：这是谁的插槽、上下游是谁、契约哪节管它）。
- 测试用 pytest，放归属目录（`tests/ops` `tests/rig` `tests/judge`）；慢测试（要加载模型）标 `@pytest.mark.golden`，CI 语义上默认跳过、门前显式跑。
- 命名 snake_case；不硬编码 key（一律 .env + python-dotenv）；不写绝对路径进 src/（脚本除外，且优先相对仓库根）。
- commit 格式：`[pkgB] description`（如 `[pkgB] add item-level resume to dispatch`）。小步提交，每任务卡 ≥1 commit；只在 pkg/b 分支操作。
- 运行入口统一 `PYTHONPATH=src python -m abcr.<pkg>.<mod>` 或 `scripts/b_*.py`；禁 `pip install -e`。

**PROGRESS.md 格式（每日收工必写，追加式，最新日期在顶）**：

```markdown
# PROGRESS — 窗口B
## 2026-07-14
### 完成
- B1-3 runstate.py + 测试 8 项全绿（commit a1b2c3d）
### 未完成
- B1-5 dispatch scope 强制做到一半（明日继续，预计 1h）
### BLOCKER
- （无。若有：现象/复现命令/已试方案/需要谁裁决）
### 契约疑议
- （无。若有：引契约节号 + 现象 + 建议处置，例如"§X.Y 键名与 fixture 实物不符，建议按实物修订并记 AMENDMENT"。历史示例：拒绝路径落账疑议已由 AMENDMENT-13 裁决为 batch_dispatch_rejected 双留痕——已裁决项不再重报）
```

四节缺一不可（空节写"（无）"）。BLOCKER 与契约疑议是 fable 每日唯一必读的两节——写清楚，别让裁决人猜。

## 10. 已知坑与注意事项（坑 → 症状 → 规避）

**环境与仓库**
- **K1 worktree 共享 venv + editable 安装**：`pip install -e .` 会把 abcr 包钉到单一路径 → 三窗口 import 到别人的代码，改动"不生效"或测试诡异红。规避：永远 `PYTHONPATH=src`，本文所有命令已带。
- **K2 系统 python3=3.14**：torch 无 3.14 wheel 保证 → 任何"新开 venv"冲动都必须 `uv venv --python 3.12`；正常情况只用主仓现成 venv。
- **K3 huggingface.co 直连超时**：`from_pretrained` 挂死无报错。规避：`HF_ENDPOINT=https://hf-mirror.com`（.env 已设；子 shell/云机自己 export）。hf-mirror 偶发限速/缺仓 → 备选 modelscope。
- **K4 16GB 统一内存被 ollama 驻留吃掉**：Mac 跑 3B 干跑前 `ollama stop qwen3:8b`；B2-10 跑 gemma3 时反之别同时载 torch 大模型。

**账本与并发**
- **K5 账本并发写**：全局五链的并发写互斥已由 AMENDMENT-15 裁决——ledger_ref.append 对 `<chain>.jsonl.lock` 持 fcntl.flock(LOCK_EX)、锁内重读链尾再写（全局链放弃链尾内存缓存）；`data/runs/<id>/steps.jsonl` 仍单写者、保留缓存。规避仍照旧：一切账本写经 dispatch 单进程串行（队列存在的意义之一）；watchdog 检测面只读（第三类空转告警的 instance_idle_alert 落账走同一 flock API）；绝不在两个终端同时 dispatch 同一 worktree——flock 是兜底不是许可。
- **K6 tmp 文件命名竞态（V2 血泪 B2）**：确定性 tmp 名 + replace 放锁外曾致静默丢写。规避：runstate 的 `_write_atomic` 原样用（pid+uuid 后缀 + flock 覆盖发布），勿"简化"。
- **K7 fcntl.flock 限制**：POSIX 专属、NFS 不可靠——本项目单机双机（Mac/云各自本地盘）都安全；别把 state/ 挪到网络盘。
- **K8 bool 是 int 子类**：`isinstance(True, int) == True` → schema 的 int 字段会吞 bool。契约校验器已先拒 bool；你组装 step 记录时同样别把 numpy/bool 塞进 int 字段（`int(x)` 显式转）。
- **K9 float/NaN 进 JSON**：NaN 序列化不合法且破坏哈希可复现。规避：分数缺失用 null（None），不许 NaN；npz 里才放浮点数组。

**watchdog**
- **K10 STALL_S 与 item 耗时**：真模型单 item（含 judge 重试）可能 >900s → 误报 STALLED。规避：阶段2 按实测 item 耗时经 `ABCR_WD_STALL_S` 环境变量调大（B1-7 骨架已把 STALL_S/FRESH_S/COOLDOWN_S/IDLE_S 全部改为运行时读 env，不改码），或长 item 内部周期性 `mark_item_done` 前先 touch updated_at（加个 `heartbeat_touch(run_id)`）。
- **K11 双保险互抵（V2 血泪）**：看门狗与执行进程共享节流状态 → 一方吃掉额度另一方漏报。规避：watchdog 独立读盘、独立节流文件，不 import 执行器运行态——骨架已如此，别为省代码合并。
- **K12 配额类失败盲目续跑**：DeepSeek 余额耗尽/402 的失败，resume 只会再撞。规避：can_resume 之外，dispatch 对 reason 含 quota/402/insufficient/额度 的 run 只告警不自动续跑。

**vendor 官方仓库（persona_vectors）**
- **K13 config.py 双 key 强制**：缺 OPENAI_API_KEY 或 HF_TOKEN 任一直接 raise；且**无效 HF_TOKEN 比没有更糟**（带上请求头 → 401）。规避：补丁1 + .env 里干脆不放 HF_TOKEN。
- **K14 generate_vec.py fp32 加载**：未传 torch_dtype → 7B ≈28GB → 24GB 卡 OOM 或狂下放 CPU。规避：补丁2（bf16）。两补丁都要谱系记录（D6/D7）。
- **K15 `--version` 默认是 extract**：基线/评测忘传 `--version eval` 会静默用抽取题集——数据全错且不报错。规避：runbook 命令已带；自查产物行数（eval=20 题，extract=100 题位）。
- **K16 output_path 已存在即跳过**：不加 `--overwrite` 时只打印旧 csv 均值，看起来"跑完了"。规避：重跑必带 `--overwrite` 或换路径。
- **K17 阶段3 过滤为空**：`pos[trait]>=50 且 neg[trait]<50 且双方 coherence>=50` 过滤后为空 → torch.cat 报错。规避：跑阶段3 前先打印阶段2 CSV 分数（runbook 已嵌命令）。
- **K18 cal_projection 参数名**：argparse 真名是 `--vector_path_list`/`--layer_list`（nargs=+），`--vector_path`/`--layer` 靠前缀匹配碰巧可用；多值用空格分隔，别写两次 flag。
- **K19 相对路径硬编码**：trait 数据按 `data_generation/trait_data_{version}/{trait}.json` 相对路径读 → **一切官方命令必须在仓库根目录执行**；自造 trait 文件必须放进这两个目录且文件名=trait 名。
- **K20 judge 并发默认 100**：DeepSeek 会 429。规避：`--max_concurrent_judges 20`（runbook 已带），429 再降 10。
- **K21 vLLM 吃 90% 显存**：阶段2（vLLM）与阶段3/4（transformers）是不同命令天然分进程；但后台残留 vLLM 进程会让后续 OOM——每阶段间 `nvidia-smi` 查残留。
- **K22 训练路径别碰**：sft.py/training.py/unsloth 是训练用（W1 不做）；config 里 push_to_private=true 会尝试推 HF 私有仓——反正不跑训练，别好奇执行。

**judge 与科学侧**
- **K23 judge 三坑未实测**（deepseek-chat 名字失效 / 0–100 非单 token / seed 400）：B1-10 冒烟首验；降级链 deepseek-v4-flash → 文本解析模式（记偏离）→ 报楠。加权打分里数字总概率 <0.25 记 None——None 率飙高本身是信号，进 PROGRESS。
- **K24 ollama 无 logprobs**：第二家族 judge（gemma3）只能文本解析打分，与主 judge 机制不同——这是**方法偏离**，必须写进 consistency 产物的 deviation 字段，不许静默。
- **K25 MPS 数值怪癖**：hook 检在 Mac 红且逻辑无误 → 按契约风险表移云日 CUDA 复验，Mac 结果标 non-citable；消融投影内积必须 fp32 再 cast 回。
- **K26 vLLM 默认非确定性**：同请求因批组成不同可得不同输出（官方 FAQ 明示）→ W1 主链单引擎 transformers；parity 分歧是记录对象不是 bug。
- **K27 模板静默漂移**：chat template 错配是 harness 最常见静默杀手——三样例逐字节检不许省；样例定稿前人工目检 im_start 结构与默认 system 注入。
- **K28 泄漏三防线**：抽取题∩评测题=∅（trait 工件构造保证）；golden10/ifeval 题面与 trait questions 零重合；②臂无 hook/④臂无人格文本（manifest 断言）。违反任何一条 = A 审计 QUARANTINED。
- **K29 呈现纪律**：一切产物（demo/图/JSON 报告）带 `exploratory / rig-validation` 标注；mini 环分数差异**不是证据**；未过五检称 direction-k。违者触"exploratory 当结论"禁令。

**云日**
- **K30 卡回收/断连**：checkpoint 常态化——官方五阶段每条命令产物落盘即 checkpoint（重跑跳过已存在 output_path 反而是优点）；abcr 侧 dispatch 幂等续跑。断连即重连重跑原命令。
- **K31 忘关机 = 烧钱**：完成即关机是硬纪律；stop 事件必须带 verified 三项；楠不在场就催。
- **K32 approval.key 上云**：HMAC 对称密钥可签发——W1 接受此折衷（实例短命），收工建议轮换；key 永不进 git/tar 产物包（tar 清单里没有 state/approval.key，注意别顺手打包）。

---

> 本文档为 ABCR 工程包 B 唯一施工依据（V1.0，2026-07-11 冻结）。契约修订以 fable 广播为准，修订前本文与 `src/abcr/common/` + `tests/contract/` 不一致处，以仓库内契约库与契约测试为准并记 PROGRESS。开工顺序：§4 自检 → 通读 common 三文件 → B1-3 起卡。
