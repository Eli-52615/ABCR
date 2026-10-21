# ABCR 工程包A · 账本 + 状态机 + Auditor（裁判 + 验船师）V1.0

> **执行者须知（先读这一段）**
> - 你是**窗口 A**，一个 Claude Opus 4.8 high 独立执行窗口，每日工作 **24 小时**。
> - 你的 worktree：`/Users/superagent/abcr-wt/a`（分支 `pkg/a`）。主仓 `/Users/superagent/abcr`（分支 main，只由 fable 在回归门合并，你不碰）。
> - 阶段制：**阶段0 接口冻结已由 fable 完成**（契约库 / fixture / 黄金十题 / 契约测试 kickoff 时已就位）→ 你现在执行**阶段1（无LLM最小闭环）**→ 回归门 **R1** → **阶段2（真实执行 + 故障注入）**→ 回归门 **R2**。任一门不过不进下一阶段。
> - fable **只在阶段门与 BLOCKER 时出现**：每日异步读你的 PROGRESS.md（≤20 分钟），只裁决 BLOCKER 与契约疑议；契约修订权在 fable，你不得自行偏离契约。
> - **本文档 + abcr 仓库 = 你的全部信息来源**。你不允许读 shared-brain 下任何文件、不允许读上位方案文档、不允许上网调研（网络白名单仅 pypi / hf-mirror.com / api.deepseek.com / github.com 克隆）。你需要的一切接口、schema、代码、命令、判据都已逐字嵌入本文；仓库内文件（`src/abcr/common/`、`fixtures/`、`tests/contract/`、`data/golden/golden10.json`）你可以且应该直接读。
> - 你的角色隐喻：**裁判 + 验船师**。你不造船（不生成、不评分——scorer 是 B 的）、不掌舵（不起草信封——那是 C 的），你只守账本的真、状态的序、审计的严。

---

## 0. 任务一页图

### 0.1 阶段1 交付清单（R1 前完成）

| 编号 | 交付物 | 路径 | 一句话验收 |
|---|---|---|---|
| A1-1 | ledger_ref 接管 + 补测 | `src/abcr/common/ledger_ref.py`、`tests/ledger/test_ledger_ref.py` | 断链/篡改/截断/fsync/并发 flock 用例全绿，契约测试不因本包改动新增红项 |
| A1-2 | schema 全字段校验器 | `src/abcr/ledger/schema.py`、`tests/ledger/test_schema.py` | 接受 fixture 全部记录；拒绝 12 个变异样本；int 拒 bool |
| A1-3 | 三层状态机 + TTL | `src/abcr/ledger/statemachine.py`、`tests/ledger/test_statemachine.py` | 非法迁移全部拒绝并给原因；TTL 表可查询 |
| A1-4 | DuckDB 只读视图 | `src/abcr/ledger/views.py`、`tests/ledger/test_views.py` | run 汇总 / 批次进度 / 异常清单三视图对 fixture 数据出对 |
| A1-5 | 独立复评器 rescore_v1 | `src/abcr/audit/rescore.py`、`scripts/a_rescore.py`、`scripts/a_rescore_compare.py`、`tests/audit/test_rescore.py` | 黄金十题 fixture 绿；compare 打印 MATCH 60/60（与 `fixtures/expected_scores.jsonl` 全同） |
| A1-6 | auditor v0（六项中的 1/2/4） | `src/abcr/audit/auditor.py`、`src/abcr/audit/health.py`、`scripts/a_audit.py`、`tests/audit/` | 对 fixture 批次出报告；g03/g07 已知错误分布被正确呈现 |
| A1-7 | audit 报告格式 | `reports/audit/<batch_id>.{json,md}` 生成逻辑 | 逐项 PASS/FAIL + 证据指针，JSON 与 MD 同源 |

> **R1 拆分（已裁决 AMENDMENT-30）**：R1 拆 R1-core（fixture 闭环六步最小件，先过门）与 R1-full（阶段2 期间完成、R2 前齐）。本包 R1-core = A1-1/A1-2/A1-3/A1-5/A1-6/A1-7；**A1-4 views 属 R1-full**，不卡 R1-core 门（判据 R1-A9 随 R1-full 验收）。

### 0.2 阶段2 交付清单（R2 前完成）

| 编号 | 交付物 | 路径 | 一句话验收 |
|---|---|---|---|
| A2-1 | auditor 3 防污染 | `src/abcr/audit/contamination.py` | 抽取语料∩评测题=∅ 哈希级；split hash 核对；judge 输入无条件字段；泄漏词表 grep |
| A2-2 | auditor 5 版本一致 | `src/abcr/audit/auditor.py` 扩展 | git clean / code_tree_hash / env lock 三查 |
| A2-3 | auditor 6 成本对账 | `src/abcr/audit/budget_recon.py` 内 | 预估 vs 实耗偏差 <10% 判据可执行 |
| A2-4 | budget_recon | `src/abcr/audit/budget_recon.py` | ¥150 顶、85%（¥127.5）熔断告警落账 + 落文件 |
| A2-5 | 冻结区 Seatbelt + 定稿仪式 | `src/abcr/sandboxing/profiles.py`、`scripts/a_freeze.py` | 沙箱内写冻结区 EPERM；定稿 = git tag + 哈希入账 + profile 生效 |
| A2-6 | 故障演练脚本四件 | `src/abcr/sandboxing/drills/`、`scripts/a_drill_*.py` | 四演练可由 fable 手跑，全部产出留痕断言（§7） |

### 0.3 你在回归门的判据项（细则见 §8）

- **R1**（fable 手跑演练脚本）：① `tests/contract/` 全绿不被你改动；② schema 校验器接受 fixture 全部记录、拒绝 12 变异样本；③ 哈希链断链检测可用；④ 状态机非法迁移拒绝；⑤ rescore_v1 对 6 个假 run 复评与 `expected_scores.jsonl` 全同、与 B 的 deterministic_v1 输出比对一致；⑥ auditor 报告正确呈现 g03/g07 已知错误分布；⑦ 你的单测全绿。
- **R2**：① 四故障演练全过（其中演练2、演练4 的检测者/防线就是你）；② 真实 7B mini 环批次的审计报告六项齐全；③ 预算 ≤¥150 逐实例登记、85% 熔断可触发（演练3）；④ 冻结区定稿仪式完成且 Seatbelt 拦截实测留痕；⑤ 复现包闭合验收所依赖的"从原始输出独立复算"由你的 rescore_v1 承担且与包内 scores 一致。

---

## 1. 项目背景速览、术语表、否证标准、呈现纪律

### 1.1 背景速览（≤12 行）

ABCR 是楠的人格向量实验项目：12 周研究，核心科学问题是**文本人格提示的行为效应是否由模型内部可命名的方向（residual stream 中的线性方向）中介**。主线配方是 Persona Vectors 式残差差分向量（正负人格系统提示下响应 token 平均激活之差，得到逐层向量，再做注入/消融干预）。当前处于 W1：目标是建成"最小纵向闭环"——一条真实实验链可重复运行：固定输入与模型 → baseline / 人格文本 / 残差干预三臂 → 逐步轨迹与激活摘要落盘 → 自动评分 → **独立复评一致** → 一键产出可复现实验包。同时按楠的阶段化指示建设**实验控制面**：先用假任务证明控制面是对的（阶段1），再用真实验证明它是有用的（阶段2）。三个执行窗口并行：A（你，账本/状态机/Auditor）、B（Operator/队列/rig/科学载荷）、C（Governor/信封/同步视图）。三包只通过账本文件、信封文件、run 产物和契约库 API 通信。W1 的产出不是证据，是**产生证据的机器及其正确性证明**——你是这台机器的验船师：账本可信、复评独立、审计严格，是整个项目对外可采信的根基。

### 1.2 术语表（逐字嵌入，勿另行发明措辞）

- **人格标签** = Big Five 等外部理论标签，仅用于对表文献；
- **行为控制原语** = 可测量、可干预并影响任务轨迹的内部方向或神经元集合（例：探索、验证、坚持、校准、质疑）;
- **自适应行为策略** = 按任务特征与历史反馈选择原语、方向、层和强度的路由策略。

补充工程术语：**run** = 一份声明式 config 的一次执行；**batch/批次** = 一个信封所辖的一组 run；**信封（envelope）** = 计划级审批对象（§3.6）；**冻结区** = `data/golden`、`data/splits`、`data/traits` 三目录（协议对象 FROZEN 后人是唯一写入者）；**direction-k** = 未过五检的候选方向（未过检前一律不称"人格向量"）。

### 1.3 否证标准（逐字嵌入；任一出现记**有效负结果**入账本，不得丢弃或重跑覆盖）

人格评分变化明显但能力变化在控制长度和格式后消失※；只有单个 benchmark、单个系数、单个模型有效；随机等范数方向产生同等增益；calibration 有增益 held-out 反转；动态路由不优于按 benchmark 固定人格（G1 后适用）；内部干预普遍不如文本提示；正负 steering 均只导致输出质量下降；量化模型有效而 BF16 不复现；LLM judge 喜欢 steered 输出但确定性准确率不变。※修正注（V1.3 M9）：长度不再作硬性条件化变量，改三段分解报告；硬性否证前提仅随机方向对照 / 流畅性 PPL / 格式遵循三项。

**对你的含义**：QUARANTINED / REJECTED / 负结果批次是**证据**不是垃圾——auditor 的处置动作永远是"留证 + 标记 + 告警"，绝不删除、绝不允许重跑覆盖同 run_id。

### 1.4 呈现纪律（逐字嵌入）

W1 一切数字带 `exploratory / rig-validation` 标注；mini 环产出不构成任何假设的证据；对外材料数字必须出自账本视图（三轨共享同一事实源）。QUARANTINED 批不删除、不采纳、不重跑覆盖——留证 + 人裁决。

**对你的含义**：你的 `views.py` 就是"账本视图"这个唯一事实源的实现；audit 报告与健康面板中的一切数字必须可回溯到 `ledger/` 与 `data/runs/` 的具体行（证据指针）。

---

## 2. 铁律与边界

### 2.1 三条铁律（逐字，全项目共同宪法）

> ① 三包只通过稳定接口（§2 账本文件 + 信封文件 + 契约库 API）通信，**禁止互相直接读写对方内部状态**；② 只在自己 worktree 内动归属矩阵分给自己的路径，不访问 shared-brain，网络白名单 = pypi / hf-mirror.com / api.deepseek.com / github.com 克隆；③ 每日收工写 `PROGRESS.md`，阻塞超 30 分钟记 BLOCKER 换任务，不钻兔子洞。

（铁律①中"§2"指上位契约文档章节，其全部相关内容已逐字嵌入本文 §3。）

### 2.2 目录归属矩阵（你的部分）

你**可以创建/修改**的路径（全部在 `/Users/superagent/abcr-wt/a` 内）：

```
src/abcr/common/ledger_ref.py      ← 维护权归你（kickoff 已交付权威实现，你接管）
src/abcr/ledger/                   ← schema.py writer.py statemachine.py views.py
src/abcr/audit/                    ← auditor.py rescore.py contamination.py health.py budget_recon.py
src/abcr/sandboxing/               ← profiles.py drills/
scripts/a_*.py                     ← 你的脚本一律 a_ 前缀
tests/ledger/ tests/audit/ tests/drills/
reports/audit/                     ← 审计报告产物（reports/ 下你只写这个子目录）
state/audit/                       ← 你的私有内部状态（告警文件、审计工作区；对 B/C 是黑箱）
PROGRESS.md                        ← 你 worktree 自己的（不合并）
```

你**只读不写**的路径：`src/abcr/common/approval_token.py`（C 维护）、`src/abcr/common/constants.py`（fable 维护）、`src/abcr/ops|rig|judge/`（B）、`src/abcr/governor|report/`（C）、`configs/`、`data/golden|benchmarks|splits|traits`、`fixtures/`、`tests/contract/`、`queue/`、`plans/`、`configs/envelopes/`。
你**经账本 API 追加**（不直接编辑文件）：`ledger/*.jsonl`（审计事件；全局链并发写互斥见 §3.7——已裁决 AMENDMENT-15）。
你**直接文件级追加**：`data/runs/<run_id>/scores.jsonl`（仅 rescore 的 scores 行）——已裁决（AMENDMENT-14）：scores.jsonl 为**非哈希链** append-only JSONL，多 scorer 直接文件级追加（写后 flush；只追加、不修改既有行），**不经 RunLedger**；防篡改由复现包整体哈希 + A/B 双实现比对承担。
（`writer.py` 定位说明：五链 RunLedger 实例化与审计事件追加的薄封装，阶段1 可为空壳，非 R1 判据——无独立任务卡。）

### 2.3 权限矩阵（逐字嵌入；你 = Auditor 列，但你审计所有列，故全表给你）

| 路径/对象 | rig(B) | Operator(B) | Governor(C) | Auditor(A=你) | 人 |
|---|---|---|---|---|---|
| data/golden、data/splits、data/traits（冻结区） | 只读 | 只读 | 只读 | 只读 | 唯一写入者（经 B 起草、定稿仪式冻结） |
| data/runs/*/steps.jsonl、scores.jsonl | 追加(steps) / 追加(scorer 的 scores) | 只读 | 只读 | 追加(rescore 的 scores) | 只读 |
| ledger/*.jsonl（runs_index/batches/costs/instances） | 经账本 API 追加 | 经账本 API 追加 | 只读 | 追加(审计事件) | 只读 |
| queue/ | — | 读写 | 只读 | 只读 | 读写 |
| configs/envelopes/、plans/ | — | 只读 | 读写（草案） | 只读 | 审批签名 |
| state/（各包私有内部状态） | 各归属者私有 | 同 | 同 | 同 | — |

**接口 = 账本文件 + 信封文件 + data/runs 产物 + 契约库 API。各包内部状态（queue 细节、planner 中间物、审计工作区）互为黑箱。**

### 2.4 明确禁止清单

1. **不做生成、不做评分**——`deterministic_v1` / `judge_deepseek_v1` scorer 归 B；你只做**独立复评** `rescore_v1`（有意双实现，对冲同源 bug，禁止 import B 的 scorer 代码或复用其判分函数）。
2. **不起草信封、不签发令牌**——信封与 `approval_token.py` 归 C；你只需知道验证接口存在（§3.6），审计时校验信封结构与令牌消费痕迹。
3. **不做界面**（控制台/飞书/图形化恒排阶段3，且不归你）。
4. **不读 shared-brain 下任何文件；不读上位方案文档；不上网调研**（白名单外网络一律不碰；你的包阶段1 全程零 LLM、零网络——连 pip 都只在 §4 环境安装时用）。
5. **不改 `tests/contract/` 下任何文件**——契约测试是三包共同的地板；红了先自查，仍红走 PROGRESS 契约疑议，等 fable 裁决。
6. **不 push 远端、不装 gh、不设全局 git 身份**（纯本地仓库；repo 级身份 kickoff 已设）。
7. **不把任何 API key 值写入 repo**（.env 已 gitignore；你的包本就不需要 key）。
8. **不直接用文本编辑手段修改 `ledger/*.jsonl` / `steps.jsonl` / `scores.jsonl` 的既有行**——append-only 是全项目诚实性根基；你自己首先不能破。
9. **不越界修 B/C 的 bug**——发现对方问题写进 PROGRESS 契约疑议节（fable 广播），不动手。
10. **阻塞超 30 分钟必须记 BLOCKER 换下一张任务卡**——不钻兔子洞。

---

## 3. 冻结契约摘录（阶段0 产物，逐字嵌入；修订权在 fable，修订即广播）

### 3.1 仓库、worktree 与路径全貌

仓库 `/Users/superagent/abcr`，本地 git 无远端。fable 在 kickoff 创建三分支三 worktree：

```
主仓 /Users/superagent/abcr           分支 main（只由 fable 在回归门合并推进）
worktree /Users/superagent/abcr-wt/a  分支 pkg/a  ← 窗口 A（你）
worktree /Users/superagent/abcr-wt/b  分支 pkg/b  ← 窗口 B
worktree /Users/superagent/abcr-wt/c  分支 pkg/c  ← 窗口 C
vendor   /Users/superagent/abcr-vendor/persona_vectors  ← 官方仓库 clone（git 之外，B 专属）
```

目录归属（**只有归属者可创建/修改；`共`= 阶段0 fable 交付后冻结，改动=契约修订**）：

```
abcr/
├── .env .gitignore requirements-mac.txt README.md        共
├── src/abcr/
│   ├── common/            共→维护权分置：ledger_ref.py(A) approval_token.py(C) constants.py(fable)
│   ├── ledger/            A（schema.py writer.py statemachine.py views.py）
│   ├── audit/             A（auditor.py rescore.py contamination.py health.py budget_recon.py）
│   ├── sandboxing/        A（profiles.py drills/）
│   ├── ops/               B（faketask.py queue.py dispatch.py runstate.py heartbeat.py watchdog.py cloud.py）
│   ├── rig/               B（models.py hooks.py interventions/ scorer.py runner.py splits.py）
│   ├── judge/             B（deepseek_client.py blind_protocol.py consistency.py）
│   ├── governor/          C（envelope.py planner.py triage.py）
│   ├── report/            C（views.py sync.py repro_pack.py weekly.py）
│   └── notify.py          C（阶段3 接线，代码先交付）
├── scripts/               前缀归属：a_*.py(A) b_*.py(B) c_*.py(C)；abcrctl(C，人侧 CLI)
├── configs/
│   ├── models/ experiments/ benchmarks/                  B
│   └── envelopes/                                        C
├── data/
│   ├── golden/golden10.json                              共（冻结）
│   ├── benchmarks/ splits/ traits/                       B（定稿即冻结入 git）
│   └── runs/                                             运行时（gitignore）
├── fixtures/              共（阶段0：批次信封样例+假任务定义+期望分数+测试密钥）
├── ledger/ queue/ state/ plans/                          运行时（gitignore）
├── reports/ demos/                                       产物（入 git 可选）
├── tests/
│   ├── contract/          共（阶段0 契约测试，fable 交付；三包必须保持全绿）
│   ├── ledger/ audit/ drills/                            A
│   ├── ops/ rig/ judge/                                  B
│   └── governor/ report/                                 C
└── PROGRESS.md            各 worktree 自己的（不合并）
```

Makefile 并行期不存在；你在文档/PROGRESS 中定义 make 目标语义即可，fable 在 R1 门汇编。

### 3.2 账本（单一事实源）：文件、事件词表、哈希链

`ledger/` 下五个 append-only JSONL（第五链 protocol.jsonl 系 AMENDMENT-7 增补），全部走哈希链（协议见 §3.7），**只能经 `src/abcr/common/ledger_ref.py` 的 API 写入**（并发写互斥见 §3.7——已裁决 AMENDMENT-15）：

- `runs_index.jsonl` —— run 生命周期事件。事件词表（枚举冻结）：`run_registered, run_queued, run_started, step_progress, run_paused, run_resumed, run_failed, run_completed, run_scored, run_audited, run_accepted, run_quarantined, run_cancelled`。`step_progress` 由 B 每完成 N=5 个 item 追加一次（payload 含 steps_done/items_done），**这就是进度心跳**——"在岗"的唯一定义是账本 step 推进（治"进程活着工作流停摆"）。已裁决（AMENDMENT-19）：`run_registered` 事件 payload 必含 `batch_id` 辅助键（run↔batch 关联的账本通道）。
- `batches.jsonl` —— 批次事件：`batch_drafted, batch_approved, batch_rejected, batch_dispatch_rejected, batch_dispatch_started, batch_settled, batch_audited, batch_reported`。语义（已裁决 AMENDMENT-13，取代 AMENDMENT-1 初版）：`batch_rejected` = 人工驳回，abcrctl 落账；`batch_dispatch_rejected` = 令牌校验失败或信封越界被 dispatch 拒绝，B 落账，payload 带原因码 + subject_id=batch_id。
- `costs.jsonl` —— `run_cost_estimated, run_cost_actual, budget_alert`。payload 键名已裁决（AMENDMENT-9）：costs 事件必含 `{subject_id, amount_cny, basis}`（run 级事件另带 `batch_id` 辅助键）；`run_cost_estimated` 由 B 的 dispatch 消费信封时逐 run 落账（AMENDMENT-28①）。
- `instances.jsonl` —— `instance_registered, instance_started, instance_stopped, instance_idle_alert`（供应商、规格、时价、关联批次）。payload 必含（AMENDMENT-9）：`{instance_id, vendor, spec, price_cny_per_h, batch_id}`。
- `protocol.jsonl` —— 协议对象冻结事件：`artifact_frozen, artifact_superseded`（已批：AMENDMENT-7 第五链）。
- **云侧账本（已裁决 AMENDMENT-2）**：云机上产生的账本事件写**独立哈希链段**（`ledger/cloud-day<N>/` 子目录，各文件自成一链），随产物整体回传归档，不与 Mac 侧链拼接；Auditor 对账时**按段独立 verify_chain**，读取时合并为只读视图。

### 3.3 三层状态机（你实现迁移守卫；非终态携带 TTL，B 看门狗做全局对账）

- **协议对象**：`DRAFT → REVIEW → FROZEN →（AMENDMENT→新版本）→ SUPERSEDED`。W1 冻结对象 = golden10、splits、traits、黄金判据；冻结动作 = 人（楠或 fable 代）跑定稿仪式（git tag + 哈希入账 + 阶段2 起 Seatbelt 只读）。
- **批次对象**：`DRAFT → APPROVED → DISPATCHING → SETTLED → AUDITED → REPORTED`。APPROVED 必须携带有效审批令牌（§3.6）。
- **运行对象**：`PLANNED → QUEUED → RUNNING → {PAUSED, FAILED} → COMPLETED → SCORED → AUDITED → {ACCEPTED, REJECTED, QUARANTINED}`；终态另有 `CANCELLED`；FAILED 可 RESUME 回 RUNNING。
- **TTL 表（秒，constants.py 冻结，env 可覆盖）**：QUEUED 3600；RUNNING 心跳间隔上限 1800（零新 step_progress 即停摆告警）；COMPLETED→SCORED 7200；SCORED→AUDITED 7200。看门狗（B）每周期对账"账本状态 vs 进程表 vs（阶段2）云实例清单"，超时转异常并告警——任何长活状态无活体证据即异常，绝不允许幽灵状态滞留。

### 3.4 step 与 scores 记录 schema v1（你的校验器的唯一真值表）

**steps.jsonl**（每行一条，append-only + 哈希链），48 业务字段。裁定（D4）：`stop_reason`（生成级）与 `trajectory_stop_reason`（轨迹级）拆分；`trait_score/fluency_score` 在 steps 恒 null（append-only 禁回写），权威值在 scores.jsonl。

| # | 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|---|
| 1 | schema_version | str | 否 | 恒 "1.0" |
| 2 | run_id | str | 否 | §3.8 规则 |
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
| 17 | split_hash | str | 否 | §3.7 |
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
| 29 | chat_template_hash | str | 否 | §3.7；假任务 "fixture" |
| 30 | config_hash | str | 否 | §3.8 |
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
| 45 | activation_summary | str | 是 | 摘要文件相对路径（§3.9 抽样）|
| 46 | state_snapshot_ref | str | 是 | 合成轨迹测试须演示非 null 写读 |
| 47 | protocol_ref | str | 否 | W1 = "W1-V0.9" |
| 48 | env_lock_ref | str | 否 | lockfile 相对路径 |

**scores.jsonl**（评分是独立 pass，可多 scorer 多次追加）：`schema_version, run_id, item_id, trajectory_id, step_id, condition, random_seed, metric_name, metric_value, scorer_id, scorer_version, scored_at`。metric_name 枚举：`is_correct / trait_score / coherence_score / fluency_score / output_len_chars / output_len_tokens / hedging_rate / self_check_marker_rate / parse_ok`。**manipulation-check 指标与能力指标分列**（"行为动了但能力没动本身是发现"）。scorer_id：`deterministic_v1`（B，rig 侧）、`judge_deepseek_v1`（B）、`rescore_v1`（A=你，独立复评）——B 与你对确定性指标是**有意双实现**，对冲同源 bug；两者都必须过黄金十题（§3.10）。

校验器模式（你实现，照 V2 tasklog 范式）：SCHEMA_VERSION 常量 + frozenset 枚举 + 表驱动必需/可选字段 + 不抛异常的 `ValidationResult(ok, missing, anomalies)`；int 字段先拒 bool。

### 3.5 激活存储策略（审计 item1 需要认知）

全量激活不落盘。只存：① 抽取语料分层均值激活（B，官方流水线自产）；② 评测运行中按 item_id 哈希尾数确定性抽样 10% 题目的逐响应 token 在 v_p 上的投影标量序列 + 分层统计摘要（mean/P50/P90），存 `activations/<item_id>_<seed>.npz`。合成向量阶段同样走通此通路。

### 3.6 批次信封与审批令牌（你只校验结构与消费痕迹，不签发）

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

**审批令牌**：HMAC-SHA256，纯 stdlib，权威实现在 `src/abcr/common/approval_token.py`（C 维护，kickoff 已就位，你只读只调用）。载荷字段 `(token_id, scope, task_id→batch_id, changeset_sha256→envelope_sha256, expires_at, persona_change→false)`，序列化口径 `json.dumps(core, ensure_ascii=False, sort_keys=True)`；envelope_sha256 = 对信封去 approval 字段后的规范化 JSON（§3.7 同式）取 sha256。**签发权在人**：密钥 `state/approval.key`（32 字节，0600，abcrctl 首用生成；fixture 用 `fixtures/test_approval.key`）；人跑 `abcrctl approve <envelope>` 签发；B 的 dispatch 只接受 verify 通过的信封（校验顺序：结构→scope→恒时比较签名→envelope 哈希→过期→已消费；fail-closed）；批次 SETTLED 后才 consume。信封外任何一维（超预算、越 split、加臂）自动升协议级 = 拒绝执行 + 记账 + 告警。**确认期批次的"发射"永久保留人手，W1 全部批次实际上都由人批准。**

你的审计视角：审计一个批次时核验 ① 信封文件结构合法（schema.py 的 validate_envelope）；② approval.token 存在且 verify 通过（调 approval_token 的 verify 接口）——verify_secret 选择规则（确定性）：fixture 批（batch_id 与 `fixtures/envelope_fixture.json` 一致，或 run_configs 全为 engine=fake）用 `fixtures/test_approval.key`，其余一律 `state/approval.key`；审计报告须注明实际所用密钥；③ 批次 SETTLED 后 token 已消费（consumed 账本有其 token_id）；④ 批内每个 run 的实际参数（condition/split/seeds/item 数）不越信封 scope。

### 3.7 哈希协议（全项目统一，逐字）

- **账本哈希链**（`ledger_ref.py` 为权威实现）：`GENESIS_HASH="0"*64`；`entry_hash = sha256(json.dumps(含prev_hash不含entry_hash的本条, ensure_ascii=False, sort_keys=True).encode() + prev_hash.encode())`；append 后 flush+fsync；每文件一条链。**并发写互斥（已裁决 AMENDMENT-15）**：`ledger/` 全局五链的 `ledger_ref.append` 对 `<chain>.jsonl.lock` 持 `fcntl.flock(LOCK_EX)`，锁内重读链尾再写（全局链放弃链尾内存缓存）；`data/runs/<id>/steps.jsonl` 单写者，保留链尾缓存。kickoff 的 ledger_ref 按此实现。
- **code_tree_hash**：对 `src/ scripts/ configs/ data/traits data/golden data/benchmarks data/splits` 逐文件 sha256（exts = .py .json .md .yaml .txt，排除 `__pycache__ .git .venv`），`sha256(json.dumps(树, sort_keys=True))`。
- **chat_template_hash**：`sha256(tokenizer.chat_template.encode())` + 三条钉死样例逐字节比对（样例在工程包 B，你不需要）。
- **split_hash**：`sha256("\n".join(sorted(f"{item_id}\t{split}")).encode())`。切分：`int(sha256(f"{family}:{item_id}:abcr-w1-v1".encode()).hexdigest()[:8],16)%100`；<20 dev，<60 calibration，其余 holdout。salt `abcr-w1-v1` 为协议常量。
- **prompt_hash / obs_hash / envelope_sha256 / config_hash**：sha256(UTF-8 字节)，JSON 一律 `ensure_ascii=False, sort_keys=True, separators=(",", ":")` 规范化。

### 3.8 config 与 run_id、manifest

`config_hash = sha256(规范化 JSON)`；`run_id = f"{batch_id时间戳段}-{config_hash[:12]}"`（已裁决 AMENDMENT-22：时间戳分量取信封 batch_id 内嵌时间戳——确定性，同信封同 config 恒同 run_id，这是 dispatch 幂等的根基；仅无信封的 `--dev` 裸跑用当刻 UTC；信封内 run_configs 的 config_hash 必须唯一）。启动前置检查（B 负责执行，你负责审计其痕迹）：git clean（否则仅 `--dev` 且 manifest 打 `non_citable:true`）；model_revision / chat_template_hash / split_hash 与冻结清单逐项一致。

run 产物布局：`data/runs/<run_id>/{manifest.json, steps.jsonl, scores.jsonl, activations/, logs/}`。**manifest 必含键（显式编号 22 项——已裁决 AMENDMENT-31；item1 的键计数以此清单为唯一依据）**：① run_id ② config（全文内嵌）③ config_hash ④ git_commit ⑤ git_clean ⑥ code_tree_hash ⑦ model_id ⑧ model_revision ⑨ chat_template_hash ⑩ split_hash ⑪ engine ⑫ engine_version ⑬ torch_version ⑭ python_version ⑮ env_lock_ref ⑯ seeds ⑰ started_at ⑱ finished_at ⑲ status ⑳ non_citable ㉑ protocol_ref ㉒ batch_id。

### 3.9 黄金十题（golden10 —— B 判分器与你的复评器的共同真值；已冻结于 `data/golden/golden10.json`）

判分语义精确定义（两包**独立实现**；10 题 pass_sample 判 1、fail_sample 判 0 全对才过门）：

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

### 3.10 fixture（阶段1 三包共同的靶）

`fixtures/` 内容：① `envelope_fixture.json`——一个含 6 个假 run config 的信封（2 condition × 3 seed，benchmark=golden10，engine=fake）+ 用 `test_approval.key` 预签的有效令牌 + 一个坏令牌样例；② `faketask_spec.md`——确定性假任务定义：对 item_id=gXX 输出 golden10 的 pass_sample（其中 g03/g07 输出 fail_sample，制造已知错误分布），每 item 耗时 0.2s，暴露故障旋钮 `crash_at_item / hang_at_item / skip_ledger_writes / exit_without_done`（环境变量注入）；③ `expected_scores.jsonl`——该信封跑完后确定性期望分数（is_correct 8/10 题为 1）；④ `test_approval.key`。契约测试 `tests/contract/`：schema 校验器接受 fixture 全部记录、拒绝 12 个变异样本（缺字段/错类型/bool 混 int/枚举外值）；令牌正样验证通过、坏令牌六种失败路径各返回正确原因码；哈希链断链检测；状态机非法迁移拒绝。**裁定（解"契约测试悖论"）**：kickoff 版契约测试中依赖 `abcr.ledger.schema` / `abcr.ledger.statemachine`（A1-2/A1-3 交付物）的用例在模块缺失时为 **skip/xfail**（不算红）；若仓库实物不是如此，按契约疑议走 PROGRESS 上报，**而非**触发 BLOCKER 停摆（见 §4.3）。

---

## 4. 环境与启动

### 4.1 环境事实（2026-07-11 实测，写死不再探测）

| 项 | 事实 | 对你的含义 |
|---|---|---|
| 硬件 | Mac mini M4 16GB（Mac16,10），数据卷余 122Gi | 你的包无 ML 负载，无内存压力 |
| Python | 默认 python3=3.14.6（brew）；uv 0.11.3 已装并缓存 CPython 3.12.13 | **一律用仓库 venv（Python 3.12）**，绝不用系统 python3 |
| venv | kickoff 已建 `/Users/superagent/abcr/.venv`（`uv venv --python 3.12`），依赖已装（duckdb/pytest/pandas/pyarrow/typer/pydantic 等在 requirements-mac.txt） | worktree 里没有 .venv（gitignore），激活主仓那个 |
| 沙箱 | `/usr/bin/sandbox-exec` 可用（macOS 26.4.1 实测 deny file-write* 拦截 shell 重定向 / python open / rm） | 阶段2 冻结区保护的内核机制，模板已实测（§6 A2-5） |
| git | 2.53.0；无全局身份；repo 级身份 kickoff 已设（abcr/abcr@local）；**纯本地仓库不建远端不 push** | commit 直接可用 |
| 网络 | 白名单 pypi / hf-mirror.com / api.deepseek.com / github.com 克隆 | 你的包除装依赖外**零网络** |
| API | 无 Anthropic API（治理移除，禁 API 计费）；DeepSeek key 在 .env（B/C 用） | 你的包**零 LLM 调用** |

### 4.2 .env 字段含义（kickoff 已注入；你不改、不新增、不外泄）

| 字段 | 含义 | 你是否使用 |
|---|---|---|
| DEEPSEEK_API_KEY | judge 端点密钥（B 用） | 否 |
| OPENAI_BASE_URL=https://api.deepseek.com | judge OpenAI 兼容端点（B 用） | 否 |
| HF_ENDPOINT=https://hf-mirror.com | HF 下载镜像（huggingface.co 直连超时；B 用） | 否 |
| AUDITOR_FEISHU_APP_ID / SECRET | 飞书 bot 凭证（阶段3，C 用） | 否 |
| ABCR_STATE_DIR | state/ 根覆盖（缺省 = worktree 下 `state/`） | 是（读，勿写死绝对路径） |

### 4.3 启动与环境自检命令序列（每个工作日开工先跑）

```bash
cd /Users/superagent/abcr-wt/a
git branch --show-current                     # 预期输出: pkg/a
source /Users/superagent/abcr/.venv/bin/activate
python -V                                     # 预期: Python 3.12.x
export PYTHONPATH=$PWD/src                    # src 布局，无安装步骤，靠 PYTHONPATH
python -c "import duckdb, pytest; print('deps ok')"   # 预期: deps ok
python -m pytest tests/contract -q            # 预期: 无 FAIL（依赖 A1-2/A1-3 交付物的用例在交付前为 skip/xfail，不算红——见 §3.10 裁定；出现 FAIL 先停：见 §10 坑15）
ls -l /usr/bin/sandbox-exec                   # 预期: 存在（阶段2 用）
ls fixtures/ data/golden/golden10.json src/abcr/common/ledger_ref.py  # 预期: 都在
```

约定：本文一切验收命令都假设已执行上述 `cd + activate + export PYTHONPATH`。pytest 建议在 worktree 根跑（`python -m pytest`，不是裸 `pytest`，保证用 venv 解释器）。

### 4.4 kickoff 交付物核对（第一天第一件事）

逐项确认以下文件存在且可读（缺任何一项 = BLOCKER，写 PROGRESS 等 fable，不要自己造）：
`src/abcr/common/ledger_ref.py`、`src/abcr/common/approval_token.py`、`src/abcr/common/constants.py`、`data/golden/golden10.json`、`fixtures/envelope_fixture.json`、`fixtures/faketask_spec.md`、`fixtures/expected_scores.jsonl`、`fixtures/test_approval.key`、`tests/contract/`（非空）。
**先读一遍 `constants.py`**——枚举/TTL/GENESIS_HASH/salt 的冻结常量在那里；本文 §5 嵌入代码中的字面枚举仅为自包含可读，**落地实现一律 `from abcr.common import constants` 复用，不重复定义**；若 constants.py 与本文不一致，以 constants.py 为准并在 PROGRESS 契约疑议节报告。

---

## 5. 阶段1 任务卡

> 顺序即依赖序：A1-1 → A1-2 → A1-3 →（A1-4 与 A1-5 可并行）→ A1-6 → A1-7。每卡收尾：单测绿 + 契约测试**不因本包改动新增红项**（依赖 A1-2/A1-3 交付物的 kickoff 用例在交付前为 skip/xfail——见 §3.10 裁定；**A1-3 完成后契约测试须全绿**）+ commit（`[pkgA] ...`）。

### A1-1 ledger_ref.py 接管 + 补测试（预计 1.5h）

**目标**：接管 `src/abcr/common/ledger_ref.py` 维护权；为其补齐防回归测试。kickoff 交付的权威实现即下述全码（改写自 AILH V2 TraceWriter；append 后 flush+fsync、单写者链链尾内存缓存、全局链 flock 写互斥【已裁决 AMENDMENT-15】三处增强）——先与仓库实物 diff 确认一致，再补测试；**不重写、不"优化"接口**（B/C 已按此 API 编码）。（同目录归属的 `src/abcr/ledger/writer.py` = 五链 RunLedger 实例化与审计事件追加的薄封装，阶段1 可为空壳，非 R1 判据。）

**权威实现全码**（`src/abcr/common/ledger_ref.py`，kickoff 已就位，嵌此供你比对与理解）：

```python
"""运行账本 —— append-only JSONL + 哈希链 + fsync。
改写自 AILH V2 TraceWriter。
每条记录: {ts, run_id, event, ...payload, prev_hash, entry_hash}
  prev_hash  = 上一条的 entry_hash（首条为 GENESIS_HASH）
  entry_hash = sha256(canonical_json(含 prev_hash、不含 entry_hash 的本条) + prev_hash字节)
改一条 → 其后全部 prev_hash 失配 → verify_chain() 定位断链点。
相对原实现的三处增强：append 后 flush+os.fsync（原实现无，掉电会丢行）；
链尾哈希内存缓存（原实现每次 append 全文件重读，O(n^2)——仅单写者链 shared=False 依赖此假设）；
全局链并发写互斥（AMENDMENT-15）：shared=True（缺省，ledger/ 五链）时 append 对
<chain>.jsonl.lock 持 fcntl.flock(LOCK_EX)，锁内重读链尾再写（全局链放弃链尾缓存）；
data/runs/<id>/steps.jsonl 单写者用 shared=False 保留缓存。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

GENESIS_HASH = "0" * 64  # 协议常量：改动即令所有既有链失配


class LedgerTampered(Exception):
    """哈希链断链 —— 记录被改/删/插/截断。index=-1 表示链尾摘要漂移。"""
    def __init__(self, index: int, reason: str) -> None:
        self.index, self.reason = index, reason
        super().__init__(f"ledger tampered at record #{index}: {reason}")


def _entry_hash(rec_core: dict, prev_hash: str) -> str:
    """rec_core 必须含 prev_hash 字段、不含 entry_hash 字段（把本条钉死在前一条之后）。"""
    payload = json.dumps(rec_core, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload + prev_hash.encode("utf-8")).hexdigest()


class RunLedger:
    """单链 append-only 账本。只暴露 append，无 update/delete 接口。"""

    def __init__(self, root: Path, run_id: str, shared: bool = True) -> None:
        """shared=True（缺省，ledger/ 全局五链）：append 经 <chain>.jsonl.lock 的
        fcntl.flock(LOCK_EX) 互斥、锁内重读链尾再写（AMENDMENT-15）；
        shared=False（data/runs/<id>/steps.jsonl 单写者）：保留链尾内存缓存。"""
        self.run_id = run_id
        self.root = Path(root)
        self.path = self.root / f"{run_id}.jsonl"
        self.shared = shared
        self._tail: Optional[str] = None  # 链尾缓存；None=尚未从磁盘装载

    def _tail_hash(self) -> str:
        if self._tail is None:
            evs = self.events()
            self._tail = evs[-1]["entry_hash"] if evs else GENESIS_HASH
        return self._tail

    def append(self, event: str, **payload: Any) -> dict:
        """追加一条事件并链入哈希。payload 键不得用 ts/run_id/event/prev_hash/entry_hash。
        shared=True 时全程持 <chain>.jsonl.lock 排它锁并在锁内重读链尾（AMENDMENT-15）。"""
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.shared:                      # 单写者链（steps.jsonl）：保留链尾缓存
            return self._append_one(event, payload)
        lock_path = self.path.with_name(self.path.name + ".lock")   # <chain>.jsonl.lock
        with lock_path.open("a", encoding="utf-8") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                self._tail = None                # 全局链放弃链尾缓存：锁内重读链尾再写
                return self._append_one(event, payload)
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)

    def _append_one(self, event: str, payload: dict) -> dict:
        prev_hash = self._tail_hash()
        rec: dict = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": self.run_id,
            "event": event,
            **payload,
        }
        rec["prev_hash"] = prev_hash
        rec["entry_hash"] = _entry_hash(rec, prev_hash)  # 此刻 rec 含 prev、不含 entry
        with self.path.open("a", encoding="utf-8") as f:   # 'a' 追加：物理上只增不改
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())                            # 进程被杀/掉电不丢已 append 的行
        self._tail = rec["entry_hash"]
        return rec

    def events(self) -> List[dict]:
        if not self.path.exists():
            return []
        return [json.loads(ln) for ln in self.path.read_text(encoding="utf-8").splitlines()
                if ln.strip()]

    def verify_chain(self) -> bool:
        """重放整条链；改/删/插/截任一条即 raise LedgerTampered（定位条目下标）。"""
        prev = GENESIS_HASH
        for i, rec in enumerate(self.events()):
            if "prev_hash" not in rec or "entry_hash" not in rec:
                raise LedgerTampered(i, "missing chain field (prev_hash/entry_hash)")
            if rec["prev_hash"] != prev:
                raise LedgerTampered(
                    i, f"prev_hash break (expected {prev[:12]}…, got {str(rec['prev_hash'])[:12]}…)")
            core = {k: v for k, v in rec.items() if k != "entry_hash"}
            recomputed = _entry_hash(core, rec["prev_hash"])
            if recomputed != rec["entry_hash"]:
                raise LedgerTampered(
                    i, f"entry_hash mismatch (expected {recomputed[:12]}…, got {str(rec['entry_hash'])[:12]}…)")
            prev = rec["entry_hash"]
        return True

    def snapshot_digest(self) -> str:
        """链尾哈希=整条链累积指纹。空链返回 GENESIS_HASH。供异地留存后比对。"""
        evs = self.events()
        return evs[-1]["entry_hash"] if evs else GENESIS_HASH

    def verify_against_digest(self, expected_tail: str) -> bool:
        self.verify_chain()
        actual = self.snapshot_digest()
        if actual != expected_tail:
            raise LedgerTampered(-1, f"tail digest drift (expected {expected_tail[:12]}…, got {actual[:12]}…)")
        return True
```

**使用约定（写进模块 docstring 与 PROGRESS，三包同守）**：
- 五账本的实例化：`RunLedger(Path("ledger"), "runs_index")` → 文件 `ledger/runs_index.jsonl`，链 id = 文件 stem（类字段名叫 run_id 是历史命名，语义是 chain_id）。业务主体（具体 run/batch/instance 的 id）放 payload，**约定键名 `subject_id`**（因 `append()` 禁止 payload 用 `run_id` 键）。例：`ledger.append("run_started", subject_id="20260714T090000Z-ab12cd34ef56", actor="operator")`。已裁决（AMENDMENT-4）：全局账本文件中事件主体一律用 `subject_id` 键（run 事件填 run_id 值、batch 事件填 batch_id 值、instance 事件填 instance_id 值），payload 不得再用 run_id/batch_id 作键名者改用 subject_id + 辅助键。D1 与 fixture 实物核对一遍属常规自检，无需再报疑议。
- 写互斥纪律（已裁决 AMENDMENT-15）：`ledger/` 全局五链并发写经 `<chain>.jsonl.lock` 的 `fcntl.flock(LOCK_EX)` 互斥、锁内重读链尾再写（`shared=True`，缺省）；`data/runs/<id>/steps.jsonl` 单写者（`shared=False`）保留链尾缓存。你的审计事件追加走同一 API、同一纪律——与 B 的 watchdog/Operator 周期写者由 flock 天然互斥，无需靠时序错开。
- 篡改只能**检测**不能阻止：持写权限的进程可整链重算伪造。防重算的第二道防线 = R 门时 fable 在 worktree 外留存 `snapshot_digest()` 副本比对（fable 的事，你提供 `scripts/a_ledger_digest.py` 打印五链链尾即可（云链段逐段另列），10 余行脚本）。

**补测用例（`tests/ledger/test_ledger_ref.py`，最少覆盖）**：
1. 空链 append 3 条 → `verify_chain()` True，`snapshot_digest()` == 第 3 条 entry_hash；
2. 手改第 2 条任一字段（测试里直接改写文件）→ `verify_chain()` raise `LedgerTampered`，index==1，reason 含 "entry_hash mismatch"；
3. 删第 2 条 → raise，reason 含 "prev_hash break"；
4. 截断最后一条 → `verify_against_digest(旧链尾)` raise，index==-1；
5. 插入伪造条（prev_hash 接对但 entry_hash 自算不含正确前缀……即整体重排）→ raise；
6. payload 用保留键 `run_id` → 明确行为（当前实现会被 `**payload` 覆盖语义破坏——补一个显式 `ValueError` 守卫属于允许的维护性修改，加测试）；
7. 重开进程（新 RunLedger 实例）续 append → 链不断；
8. 并发追加同一全局链（`shared=True`，两实例/两进程交错 append 各 20 条）→ `verify_chain()` True、行数 40、无链分叉（AMENDMENT-15 flock 生效）。

**验收命令**：
```bash
python -m pytest tests/ledger/test_ledger_ref.py -v      # 预期: 8+ passed
python -m pytest tests/contract -q                        # 预期: 不新增红项（依赖 A1-2/A1-3 交付物的用例仍可为 skip/xfail——§3.10 裁定）
```

### A1-2 schema.py 全字段校验器（预计 3.5h）

**目标**：`src/abcr/ledger/schema.py`——四个校验入口：`validate_step`（48 字段）、`validate_score`、`validate_envelope`、`validate_ledger_event`。零外部依赖纯函数；不抛异常，返回 `ValidationResult`；int 先拒 bool。枚举/常量一律从 `abcr.common.constants` import（见 §4.4）。

**实现全码骨架**（可直接落地；若 constants.py 字段名不同，改 import 别改语义）：

```python
"""abcr.ledger.schema —— 全字段 schema 校验器（冻结契约 §2.5 的守卫实现）。

架构位置：包A·裁判侧。零外部依赖、零 LLM、纯函数（可独立复现）。
消费者：auditor（审计闸）、tests/contract、B/C 写入前自检（可选）。
模式出处：V2 tasklog 范式 = SCHEMA_VERSION 常量 + frozenset 枚举
+ 表驱动必需字段 + 不抛异常的 ValidationResult + int 字段先拒 bool。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from abcr.common import constants  # 枚举/TTL/GENESIS/salt 的冻结单一来源

SCHEMA_VERSION = "1.0"

# —— 以下枚举应等于 constants.py 中的冻结值（此处字面量仅为自包含说明）——
CONDITIONS = frozenset({
    "vanilla", "persona_text", "neutral_token", "length_instruct",
    "inject", "ablate", "inject_random", "ablate_random",
    "synthetic_test", "fake"})
STOP_REASONS = frozenset({"eos", "max_tokens", "error", "fake"})
TRAJECTORY_STOP_REASONS = frozenset({"task_done", "budget_exhausted", "max_steps", "error"})
TRAIT_POLES = frozenset({"pos", "neg"})
METHODS = frozenset({"prompt", "residual_inject", "residual_ablate"})
SAFETY_FLAGS = frozenset({"parse_fail", "truncated", "empty", "refusal", "repetition"})
METRIC_NAMES = frozenset({
    "is_correct", "trait_score", "coherence_score", "fluency_score",
    "output_len_chars", "output_len_tokens", "hedging_rate",
    "self_check_marker_rate", "parse_ok"})
SCORER_IDS = frozenset({"deterministic_v1", "judge_deepseek_v1", "rescore_v1"})
LEDGER_EVENTS: dict[str, frozenset[str]] = {
    "runs_index": frozenset({
        "run_registered", "run_queued", "run_started", "step_progress",
        "run_paused", "run_resumed", "run_failed", "run_completed",
        "run_scored", "run_audited", "run_accepted", "run_quarantined",
        "run_cancelled"}),
    "batches": frozenset({
        "batch_drafted", "batch_approved", "batch_rejected",
        "batch_dispatch_rejected",           # AMENDMENT-13：dispatch 侧拒绝（B 落账）
        "batch_dispatch_started",
        "batch_settled", "batch_audited", "batch_reported"}),
    "costs": frozenset({"run_cost_estimated", "run_cost_actual", "budget_alert"}),
    "instances": frozenset({
        "instance_registered", "instance_started", "instance_stopped",
        "instance_idle_alert"}),
    "protocol": frozenset({"artifact_frozen", "artifact_superseded"}),  # AMENDMENT-7 第五链
}


@dataclass
class ValidationResult:
    ok: bool
    missing: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return "PASS"
        return (f"FAIL (缺失: {', '.join(self.missing) or '-'}"
                f" | 异常: {', '.join(self.anomalies) or '-'})")


# (字段名, 允许类型, allow_none) —— 48 行与契约 §2.5 表逐行对应，顺序一致
_Num = (int, float)
_STEP_FIELDS: tuple[tuple[str, type | tuple[type, ...], bool], ...] = (
    ("schema_version", str, False), ("run_id", str, False),
    ("trajectory_id", str, False), ("step_id", int, False),
    ("parent_run", str, True), ("git_commit", str, False),
    ("model_id", str, False), ("model_revision", str, False),
    ("dtype", str, False), ("quantization", str, True),
    ("device", str, False), ("engine", str, False),
    ("engine_version", str, False), ("torch_version", str, True),
    ("cuda_version", str, True), ("benchmark", str, False),
    ("split_hash", str, False), ("item_id", str, False),
    ("condition", str, False), ("trait", str, True),
    ("trait_pole", str, True), ("method", str, True),
    ("layer", int, True), ("coefficient", _Num, True),
    ("intervention_strength", _Num, True), ("random_seed", int, False),
    ("env_seed", int, True), ("prompt_hash", str, False),
    ("chat_template_hash", str, False), ("config_hash", str, False),
    ("action", str, True), ("obs_hash", str, True),
    ("remaining_budget", _Num, True), ("output_text", str, False),
    ("parsed_answer", str, True), ("is_correct", bool, True),
    ("latency_ms", int, False), ("input_tokens", int, False),
    ("output_tokens", int, False), ("stop_reason", str, False),
    ("trajectory_stop_reason", str, True), ("trait_score", _Num, True),
    ("fluency_score", _Num, True), ("safety_flags", list, False),
    ("activation_summary", str, True), ("state_snapshot_ref", str, True),
    ("protocol_ref", str, False), ("env_lock_ref", str, False),
)

_SCORE_FIELDS: tuple[tuple[str, type | tuple[type, ...], bool], ...] = (
    ("schema_version", str, False), ("run_id", str, False),
    ("item_id", str, False), ("trajectory_id", str, False),
    ("step_id", int, False), ("condition", str, False),
    ("random_seed", int, False), ("metric_name", str, False),
    ("metric_value", _Num, False), ("scorer_id", str, False),
    ("scorer_version", str, False), ("scored_at", str, False),
)


def _check_fields(rec: dict, table: tuple, r: ValidationResult) -> None:
    """表驱动类型检查。要害：bool 是 int 的子类——数值字段先拒 bool。"""
    for name, typ, allow_none in table:
        if name not in rec:
            r.missing.append(name)
            continue
        val = rec[name]
        if val is None:
            if not allow_none:
                r.anomalies.append(f"{name}: 不可为 null")
            continue
        wants_bool = typ is bool
        if not wants_bool and isinstance(val, bool):
            r.anomalies.append(f"{name}: bool 冒充数值/其他类型")
            continue
        if not isinstance(val, typ):
            r.anomalies.append(f"{name}: 类型 {type(val).__name__} 不符")


def _finish(r: ValidationResult) -> ValidationResult:
    r.ok = not r.missing and not r.anomalies
    return r


def validate_step(rec: dict) -> ValidationResult:
    r = ValidationResult(ok=True)
    _check_fields(rec, _STEP_FIELDS, r)
    if rec.get("schema_version") not in (None,) and rec.get("schema_version") != SCHEMA_VERSION:
        r.anomalies.append("schema_version: 非 '1.0'")
    for f_ in ("step_id", "latency_ms", "input_tokens", "output_tokens"):
        v = rec.get(f_)
        if isinstance(v, int) and not isinstance(v, bool) and v < 0:
            r.anomalies.append(f"{f_}: 负值")
    for f_, enum in (("condition", CONDITIONS), ("stop_reason", STOP_REASONS)):
        v = rec.get(f_)
        if isinstance(v, str) and v not in enum:
            r.anomalies.append(f"{f_}: '{v}' 不在枚举")
    for f_, enum in (("trajectory_stop_reason", TRAJECTORY_STOP_REASONS),
                     ("trait_pole", TRAIT_POLES), ("method", METHODS)):
        v = rec.get(f_)
        if v is not None and isinstance(v, str) and v not in enum:
            r.anomalies.append(f"{f_}: '{v}' 不在枚举")
    flags = rec.get("safety_flags")
    if isinstance(flags, list):
        for x in flags:
            if not isinstance(x, str) or x not in SAFETY_FLAGS:
                r.anomalies.append(f"safety_flags: 非法元素 {x!r}")
    # 交叉一致性（D4 裁定 + 干预臂必填）
    if rec.get("trait_score") is not None:
        r.anomalies.append("trait_score: steps 内恒 null（权威值在 scores.jsonl）")
    if rec.get("fluency_score") is not None:
        r.anomalies.append("fluency_score: steps 内恒 null（权威值在 scores.jsonl）")
    if rec.get("condition") in ("inject", "ablate") and rec.get("trait") is None:
        r.anomalies.append("trait: 干预臂必填")
    # parsed_answer 为 null 时 safety_flags 应含 parse_fail —— 该联动检查归
    # auditor 健康面板（聚合层）承担，schema 层不重复告警。
    return _finish(r)


def validate_score(rec: dict) -> ValidationResult:
    r = ValidationResult(ok=True)
    _check_fields(rec, _SCORE_FIELDS, r)
    if rec.get("schema_version") != SCHEMA_VERSION:
        r.anomalies.append("schema_version: 非 '1.0'")
    if isinstance(rec.get("metric_name"), str) and rec["metric_name"] not in METRIC_NAMES:
        r.anomalies.append(f"metric_name: '{rec['metric_name']}' 不在枚举")
    if isinstance(rec.get("scorer_id"), str) and rec["scorer_id"] not in SCORER_IDS:
        r.anomalies.append(f"scorer_id: '{rec['scorer_id']}' 不在枚举")
    if isinstance(rec.get("condition"), str) and rec["condition"] not in CONDITIONS:
        r.anomalies.append(f"condition: '{rec['condition']}' 不在枚举")
    return _finish(r)


def validate_envelope(env: dict) -> ValidationResult:
    """信封结构校验（草案可无 approval；APPROVED 起必须有）。"""
    r = ValidationResult(ok=True)
    for k, typ in (("envelope_version", str), ("batch_id", str), ("protocol_ref", str),
                   ("scope", dict), ("budget", dict), ("deadline_utc", str),
                   ("run_configs", list), ("drafted_by", str)):
        if k not in env:
            r.missing.append(k)
        elif not isinstance(env[k], typ):
            r.anomalies.append(f"{k}: 类型不符")
    scope = env.get("scope") or {}
    for k in ("benchmark_families", "conditions", "splits",
              "item_limit_per_run", "seeds", "trait_whitelist"):
        if k not in scope:
            r.missing.append(f"scope.{k}")
    budget = env.get("budget") or {}
    for k in ("gpu_hours_max", "cost_cap_cny"):
        v = budget.get(k)
        if v is None:
            r.missing.append(f"budget.{k}")
        elif isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            r.anomalies.append(f"budget.{k}: 须为非负数值")
    bid = env.get("batch_id")
    if isinstance(bid, str):
        import re
        if not re.fullmatch(r"B-\d{8}T\d{6}Z-\d{4}", bid):
            r.anomalies.append("batch_id: 不符 B-<UTC:%Y%m%dT%H%M%SZ>-<4位序号>")
    for c in scope.get("conditions", []) or []:
        if c not in CONDITIONS:
            r.anomalies.append(f"scope.conditions: '{c}' 不在枚举")
    return _finish(r)


def validate_ledger_event(chain: str, rec: dict) -> ValidationResult:
    """chain ∈ {runs_index, batches, costs, instances, protocol}。"""
    r = ValidationResult(ok=True)
    if chain not in LEDGER_EVENTS:
        r.anomalies.append(f"未知账本链 '{chain}'")
        return _finish(r)
    for k in ("ts", "run_id", "event", "prev_hash", "entry_hash"):
        if k not in rec:
            r.missing.append(k)
        elif not isinstance(rec[k], str):
            r.anomalies.append(f"{k}: 须为 str")
    ev = rec.get("event")
    if isinstance(ev, str) and ev not in LEDGER_EVENTS[chain]:
        r.anomalies.append(f"event: '{ev}' 不在 {chain} 词表")
    if ev == "step_progress":
        for k in ("steps_done", "items_done"):
            v = rec.get(k)
            if v is None:
                r.missing.append(k)
            elif isinstance(v, bool) or not isinstance(v, int) or v < 0:
                r.anomalies.append(f"{k}: 须为非负 int（拒 bool）")
    return _finish(r)
```

**测试要求（`tests/ledger/test_schema.py`）**：① fixture 全量正样通过（跑 B 之前没有真实 steps——用 `fixtures/expected_scores.jsonl` 验 validate_score，自造一条符合 §3.4 全 48 字段的 step 正样验 validate_step，g 系列 fake 值照 §3.4 说明列）；② 自建 12 个变异样本各拒且 missing/anomalies 指名到字段（缺字段 ×3、错类型 ×3、bool 冒充 int ×2、枚举外值 ×2、trait_score 非 null ×1、step_id 负值 ×1）——契约测试里 fable 也有 12 个变异样本，两套并存无妨；③ `ValidationResult.summary()` 输出格式断言。

**验收命令**：
```bash
python -m pytest tests/ledger/test_schema.py -v   # 预期: 全绿
python -m pytest tests/contract -q                 # 预期: 不新增红项（schema 相关用例转绿；statemachine 用例在 A1-3 交付前仍可为 skip/xfail）
```

### A1-3 statemachine.py 三层状态机（预计 2h）

**目标**：`src/abcr/ledger/statemachine.py`——迁移合法性守卫（纯函数，供 B/C 调用与 auditor 复核）+ 事件→状态推导 + TTL 查询。**你不驱动状态、不修状态**（那是 B 的 watchdog 与人的事）；你提供"什么迁移合法"的唯一裁决函数与"从账本事件流推导当前状态"的唯一读法。

**实现全码骨架**：

```python
"""abcr.ledger.statemachine —— 三层状态机迁移守卫 + TTL 表（契约 §2.4 实现）。

架构位置：包A·裁判侧。纯函数、零 IO。B 的 dispatch/watchdog 在写账本前调
validate_transition 自检；auditor 事后重放事件流用 derive_run_state 复核。
"""
from __future__ import annotations

import os
from typing import Optional

# ---- 运行对象 ----
RUN_STATES = frozenset({
    "PLANNED", "QUEUED", "RUNNING", "PAUSED", "FAILED", "COMPLETED",
    "SCORED", "AUDITED", "ACCEPTED", "REJECTED", "QUARANTINED", "CANCELLED"})
RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    "PLANNED":   frozenset({"QUEUED", "CANCELLED"}),
    "QUEUED":    frozenset({"RUNNING", "CANCELLED"}),
    "RUNNING":   frozenset({"PAUSED", "FAILED", "COMPLETED", "CANCELLED"}),
    "PAUSED":    frozenset({"RUNNING", "CANCELLED"}),
    # AMENDMENT-16 审计豁免迁移：COMPLETED/FAILED/SCORED → AUDITED 均合法
    # （审计可介入任何非终态后）；三处置终态只能自 AUDITED 进入。
    "FAILED":    frozenset({"RUNNING", "CANCELLED", "AUDITED"}),   # FAILED 可 RESUME 回 RUNNING
    "COMPLETED": frozenset({"SCORED", "AUDITED"}),
    "SCORED":    frozenset({"AUDITED"}),
    "AUDITED":   frozenset({"ACCEPTED", "REJECTED", "QUARANTINED"}),
    "ACCEPTED":  frozenset(), "REJECTED": frozenset(),
    "QUARANTINED": frozenset(), "CANCELLED": frozenset(),
}
# ---- 批次对象 ----
BATCH_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"APPROVED"}), "APPROVED": frozenset({"DISPATCHING"}),
    "DISPATCHING": frozenset({"SETTLED"}), "SETTLED": frozenset({"AUDITED"}),
    "AUDITED": frozenset({"REPORTED"}), "REPORTED": frozenset(),
}
# ---- 协议对象 ----
PROTOCOL_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"REVIEW"}), "REVIEW": frozenset({"FROZEN"}),
    "FROZEN": frozenset({"SUPERSEDED"}), "SUPERSEDED": frozenset(),
}   # AMENDMENT = 新对象从 DRAFT 起，旧对象 FROZEN→SUPERSEDED

_TABLES = {"run": RUN_TRANSITIONS, "batch": BATCH_TRANSITIONS,
           "protocol": PROTOCOL_TRANSITIONS}

# 事件 → 运行状态（runs_index 词表全映射；step_progress 不改状态只刷心跳）
RUN_EVENT_STATE: dict[str, str] = {
    "run_registered": "PLANNED", "run_queued": "QUEUED",
    "run_started": "RUNNING", "run_paused": "PAUSED",
    "run_resumed": "RUNNING", "run_failed": "FAILED",
    "run_completed": "COMPLETED", "run_scored": "SCORED",
    "run_audited": "AUDITED", "run_accepted": "ACCEPTED",
    "run_quarantined": "QUARANTINED", "run_cancelled": "CANCELLED",
}
BATCH_EVENT_STATE: dict[str, str] = {
    "batch_drafted": "DRAFT", "batch_approved": "APPROVED",
    "batch_dispatch_started": "DISPATCHING", "batch_settled": "SETTLED",
    "batch_audited": "AUDITED", "batch_reported": "REPORTED",
    # AMENDMENT-13：batch_rejected（人工驳回，abcrctl 落账）与 batch_dispatch_rejected
    # （dispatch 拒绝，B 落账）只增事件、不增批次状态枚举——两者是不推进状态的标记
    # 事件（批次停在事件发生态：rejected 停在 DRAFT、dispatch_rejected 停在 APPROVED），
    # 驳回细节由 payload 原因码表达；故意不入本映射（状态推导中跳过、不判违规）。
}

# TTL 表（秒；constants.py 为冻结源，env 可覆盖）
def ttl_seconds() -> dict[str, int]:
    return {
        "QUEUED":            int(os.environ.get("ABCR_TTL_QUEUED_S", "3600")),
        "RUNNING_HEARTBEAT": int(os.environ.get("ABCR_TTL_RUNNING_HEARTBEAT_S", "1800")),
        "COMPLETED":         int(os.environ.get("ABCR_TTL_COMPLETED_S", "7200")),
        "SCORED":            int(os.environ.get("ABCR_TTL_SCORED_S", "7200")),
    }


def validate_transition(kind: str, cur: str, new: str) -> tuple[bool, str]:
    """迁移合法性唯一裁决。kind ∈ {run, batch, protocol}。不抛异常。"""
    table = _TABLES.get(kind)
    if table is None:
        return False, f"未知对象层 '{kind}'"
    if cur not in table:
        return False, f"未知状态 '{cur}'"
    if new not in table:
        return False, f"未知目标状态 '{new}'"
    if new in table[cur]:
        return True, "ok"
    return False, f"非法迁移 {cur} → {new}（合法目标: {sorted(table[cur]) or '无（终态）'}）"


def derive_run_state(events: list[dict]) -> tuple[Optional[str], list[str]]:
    """从 runs_index 单主体事件序列推导当前状态；顺带复核逐步迁移合法性。
    返回 (当前状态或 None, 违规清单)。auditor 复核入口。"""
    state: Optional[str] = None
    violations: list[str] = []
    for i, ev in enumerate(events):
        name = ev.get("event", "")
        if name == "step_progress":
            if state != "RUNNING":
                violations.append(f"#{i}: step_progress 出现在 {state} 态")
            continue
        target = RUN_EVENT_STATE.get(name)
        if target is None:
            violations.append(f"#{i}: 未知事件 '{name}'")
            continue
        if state is None:
            if target != "PLANNED":
                violations.append(f"#{i}: 首事件应为 run_registered，实为 '{name}'")
            state = target
            continue
        ok, why = validate_transition("run", state, target)
        if not ok:
            violations.append(f"#{i}: {why}")
        state = target
    return state, violations
```

**三条已裁决约定（写入 docstring 即可，无需再走契约疑议）**：
1. 已裁决（AMENDMENT-5）：事件词表无 `run_rejected`——REJECTED 状态经 `run_audited` 事件 payload `{"verdict": "rejected"}` 表达，`derive_run_state` 推导出 AUDITED 后由 auditor 读 verdict 细分；事件词表不再扩枚举。
2. 已裁决（AMENDMENT-5/16）："整批 QUARANTINED"（健康面板超阈处置）落账序 = 批内每 run **先**追加 `run_audited`（payload `{"verdict": "quarantined"}`）**再**追加 `run_quarantined`，批次追加 `batch_audited` 事件 payload `{"verdict": "quarantined"}`（批次状态机无 QUARANTINED 态，冻结词表如此）。
3. 已裁决（AMENDMENT-16）：审计豁免迁移——COMPLETED / FAILED / SCORED → AUDITED 均合法（审计可介入任何非终态后）；ACCEPTED / REJECTED / QUARANTINED 只能自 AUDITED 进入；审计处置落账一律先 `run_audited`（payload verdict）再终态事件。

**测试要求**（`tests/ledger/test_statemachine.py`）：三层各覆盖 ① 全部合法迁移逐条 True；② 非法迁移抽查 ≥8 条（如 RUNNING→SCORED、COMPLETED→RUNNING、DRAFT→SETTLED、FROZEN→REVIEW、终态→任意）返回 (False, 含"非法迁移"的原因)；③ `derive_run_state` 对合法序列（registered→queued→started→progress→completed→scored→audited）推导正确、对乱序序列报违规；④ TTL 表 env 覆盖生效（monkeypatch 环境变量）。

**验收命令**：
```bash
python -m pytest tests/ledger/test_statemachine.py -v   # 预期: 全绿
python -m pytest tests/contract -q                       # 预期: 全绿（A1-3 交付后 kickoff 的 skip/xfail 用例应全部转绿——契约测试含状态机非法迁移拒绝用例）
```

### A1-4 views.py DuckDB 只读视图（预计 2h；已裁决 AMENDMENT-30：本卡属 **R1-full**——可排在 R1-core 门后、阶段2 期间完成、R2 前齐，不卡 R1-core 门）

**目标**：`src/abcr/ledger/views.py`——用 DuckDB `read_json` 直读 JSONL 建**只读**视图（内存库，不落 .duckdb 文件，杜绝"第二事实源"）。三个推荐查询面：run 汇总 / 批次进度 / 异常清单。这是"对外数字必须出自账本视图"的实现。**归属说明（2026-07-11 修订）**：此视图是推荐查询面而非独占通道——阶段1 并行期 C 可依契约 schema 自建只读查询，R1 后自愿切换到你的 views；两者都只许只读。

**实现全码骨架**：

```python
"""abcr.ledger.views —— 账本 DuckDB 只读视图（对外数字的唯一合法出处）。

架构位置：包A·裁判侧。内存 DuckDB 直读 ledger/*.jsonl（含 ledger/cloud-day*/ 云链段
——AMENDMENT-2 合并只读装载）与 data/runs/*/scores.jsonl，
不落库文件（防第二事实源）。消费者：auditor 健康面板、C 的同步视图（只读）、人。
"""
from __future__ import annotations

from pathlib import Path

import duckdb


def connect(repo_root: Path) -> duckdb.DuckDBPyConnection:
    """建内存库并注册视图。JSONL 行结构异构，必须 union_by_name。"""
    con = duckdb.connect(":memory:")
    root = str(Path(repo_root).resolve())
    for chain in ("runs_index", "batches", "costs", "instances", "protocol"):
        # 主链 + 云链段（AMENDMENT-2：ledger/cloud-day<N>/ 各文件自成一链，合并只读装载）
        parts = [Path(root) / "ledger" / f"{chain}.jsonl"]
        parts += sorted(Path(root, "ledger").glob(f"cloud-day*/{chain}.jsonl"))
        files = [str(p) for p in parts if p.exists()]
        if files:
            file_list = ", ".join(f"'{f}'" for f in files)
            con.execute(f"""
                CREATE VIEW {chain} AS
                SELECT * FROM read_json([{file_list}],
                    format='newline_delimited', union_by_name=true,
                    maximum_object_size=16777216)""")
        else:  # 空账本也要有视图（查询面稳定）
            con.execute(f"CREATE VIEW {chain} AS SELECT NULL::VARCHAR AS ts, "
                        f"NULL::VARCHAR AS run_id, NULL::VARCHAR AS event, "
                        f"NULL::VARCHAR AS subject_id, "
                        f"NULL::VARCHAR AS entry_hash WHERE 1=0")
    scores_glob = f"{root}/data/runs/*/scores.jsonl"
    if any(Path(root, "data", "runs").glob("*/scores.jsonl")):
        con.execute(f"""
            CREATE VIEW all_scores AS
            SELECT * FROM read_json('{scores_glob}',
                format='newline_delimited', union_by_name=true)""")
    con.execute("""
        CREATE VIEW run_latest AS
        SELECT subject_id,
               arg_max(event, ts || entry_hash) AS last_event,
               max(ts) AS last_ts,
               count(*) AS n_events
        FROM runs_index
        WHERE subject_id IS NOT NULL
        GROUP BY subject_id""")
    con.execute("""
        CREATE VIEW batch_progress AS
        SELECT subject_id AS batch_id,
               arg_max(event, ts || entry_hash) AS last_event,
               max(ts) AS last_ts
        FROM batches
        WHERE subject_id IS NOT NULL
        GROUP BY subject_id""")
    con.execute("""
        CREATE VIEW anomalies AS
        SELECT subject_id, last_event, last_ts,
               date_diff('second', strptime(last_ts, '%Y-%m-%dT%H:%M:%S%z'), now()) AS age_s
        FROM run_latest
        WHERE last_event IN ('run_failed', 'run_paused', 'run_quarantined')
           OR (last_event IN ('run_queued', 'run_started', 'step_progress',
                              'run_completed', 'run_scored')
               AND date_diff('second',
                     strptime(last_ts, '%Y-%m-%dT%H:%M:%S%z'), now()) > 1800)""")
    return con


def run_summary(repo_root: Path) -> list[tuple]:
    """run 汇总（run_id、最新事件、事件数、最新时间）。"""
    return connect(repo_root).execute(
        "SELECT * FROM run_latest ORDER BY last_ts DESC").fetchall()
```

**实施要点**：① `subject_id`（业务主体键，已裁决 AMENDMENT-4，见 A1-1 约定）为聚合键；② anomalies 的 1800s 陈旧阈值应从 `statemachine.ttl_seconds()["RUNNING_HEARTBEAT"]` 取，别写死（骨架为可读性写了字面量）；②′ 账本 ts 精度到秒，同秒多事件时 `arg_max(event, ts || entry_hash)` 的 tie-break 无语义——SQL 视图是便捷查询面，**精确状态推导恒用 `statemachine.derive_run_state`（Python 按文件行序）**，两者结论冲突以后者为准；③ 提供 `scripts/a_views.py`（typer CLI：`python scripts/a_views.py runs|batches|anomalies|scores`，打表格到终端），这是 fable 与 C 阶段1 查账的入口；④ 全模块只 SELECT，出现任何 INSERT/UPDATE/COPY 即违反契约。

**验收命令**（先用 A1-1 测试造一份小账本，或等 B 的 fixture 批次跑完后对真数据再验一遍）：
```bash
python -m pytest tests/ledger/test_views.py -v   # 预期: 全绿（测试内自造 ledger 临时目录）
python scripts/a_views.py runs                    # 预期: 表格输出，不报错
```

### A1-5 rescore_v1 独立复评器（预计 3h）

**目标**：`src/abcr/audit/rescore.py`——从 `data/runs/<run_id>/steps.jsonl` 的**原始 output_text** 出发，独立重算确定性指标与 manipulation-check 指标，追加写 `data/runs/<run_id>/scores.jsonl`（`scorer_id="rescore_v1"`）。**禁止 import B 的 `rig/scorer.py` 或复用其任何判分代码**——你与 B 是有意双实现，golden10 判分规则以 §3.9 表和 `data/golden/golden10.json` 为共同真值，各自独立写代码。

**golden10 判分实现全码**（依 §3.9 逐条翻译，直接可用）：

```python
"""abcr.audit.rescore —— 独立复评器 rescore_v1（审计六项之"重评分比对"的数据源）。

架构位置：包A·验船师侧。与 B 的 deterministic_v1 有意双实现（对冲同源 bug）。
输入：data/runs/<run_id>/steps.jsonl 的原始 output_text（铁律：一切重算不依赖重新生成）。
输出：同目录 scores.jsonl 追加行，scorer_id="rescore_v1"。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

RESCORER_ID = "rescore_v1"
RESCORER_VERSION = "1.0.0"


def _strip_fence(t: str) -> str:
    """剥 ```json 围栏（g05 用）。"""
    s = t.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        s = s.rstrip()
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def _g05(t: str) -> int:
    try:
        return int(json.loads(_strip_fence(t)) == {"a": 1, "b": 2})
    except (ValueError, TypeError):
        return 0


GOLDEN_RULES: dict[str, Callable[[str], int]] = {
    "g01": lambda t: int((lambda ls: len(ls) == 3 and all(l.startswith("- ") for l in ls))
                         (t.strip().split("\n"))),
    "g02": lambda t: int(t.strip() == "391"),
    "g03": lambda t: int(t.strip() == "hello,hello,hello,hello,hello"),
    "g04": lambda t: int(t.count("可复现") >= 2),
    "g05": _g05,
    "g06": lambda t: int(t.strip() == "ABCDE"),
    "g07": lambda t: int(t.strip() == "3"),
    "g08": lambda t: int(t.strip() == "rcba"),
    "g09": lambda t: int(t.strip()[:1] == "A"),
    "g10": lambda t: int((lambda s: s.startswith("数据") and s.endswith("。") and len(s) <= 20)
                         (t.strip())),
}

# manipulation-check 词表与句切分符集 —— 已裁决（AMENDMENT-6/21）：本表与符集已由
# fable 抄入 src/abcr/common/constants.py，A/B 共 import 词表常量、独立实现计数；
# 下方字面量仅为自包含说明，落地一律 from abcr.common import constants 取用。
HEDGING_WORDS: tuple[str, ...] = (
    "可能", "也许", "或许", "大概", "不确定", "似乎", "恐怕",
    "maybe", "perhaps", "possibly", "might", "not sure")
SELF_CHECK_MARKERS: tuple[str, ...] = (
    "让我检查", "再确认", "验证一下", "复核", "等等，",
    "double-check", "let me verify", "wait,")
_SENT_SEPS = "。！？!?.；"   # AMENDMENT-21 冻结符集（换行另行处理，见 _sentences）


def _sentences(t: str) -> list[str]:
    out, buf = [], []
    for ch in t:
        buf.append(ch)
        if ch in _SENT_SEPS or ch == "\n":
            s = "".join(buf).strip()
            if s:
                out.append(s)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _marker_rate(t: str, words: tuple[str, ...]) -> float:
    """含至少一个词表词的句子占比；空文本 = 0.0。"""
    sents = _sentences(t)
    if not sents:
        return 0.0
    hit = sum(1 for s in sents if any(w.lower() in s.lower() for w in words))
    return hit / len(sents)


def rescore_step(step: dict) -> list[dict]:
    """对一条 step 记录产出 rescore_v1 的 scores 行（能力指标 + manipulation-check 分列）。"""
    text: str = step["output_text"]
    base = {
        "schema_version": "1.0",
        "run_id": step["run_id"], "item_id": step["item_id"],
        "trajectory_id": step["trajectory_id"], "step_id": step["step_id"],
        "condition": step["condition"], "random_seed": step["random_seed"],
        "scorer_id": RESCORER_ID, "scorer_version": RESCORER_VERSION,
        "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    rows: list[dict] = []

    def emit(name: str, value: float | int) -> None:
        rows.append({**base, "metric_name": name, "metric_value": value})

    rule = GOLDEN_RULES.get(step["item_id"])
    if rule is not None:                       # golden10 之外的任务族：W1 只 golden10，
        emit("is_correct", rule(text))         # ifeval_zh_v1 判分规则由 B 定稿后（阶段2）
    emit("parse_ok", int(bool(text.strip())))  # 同步给你一份纯函数规则表（走契约广播）
    emit("output_len_chars", len(text))
    emit("output_len_tokens", int(step["output_tokens"]))  # 转录 step 记录值（不可独立重算）
    emit("hedging_rate", round(_marker_rate(text, HEDGING_WORDS), 6))
    emit("self_check_marker_rate", round(_marker_rate(text, SELF_CHECK_MARKERS), 6))
    return rows


def rescore_run(run_dir: Path) -> int:
    """整 run 复评：读 steps.jsonl → 逐条 rescore → 追加 scores.jsonl。幂等：
    已存在 rescore_v1 行的 (item_id, step_id, seed, metric) 跳过。返回新增行数。"""
    steps_p, scores_p = run_dir / "steps.jsonl", run_dir / "scores.jsonl"
    steps = [json.loads(l) for l in steps_p.read_text(encoding="utf-8").splitlines() if l.strip()]
    seen: set[tuple] = set()
    if scores_p.exists():
        for l in scores_p.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            if r.get("scorer_id") == RESCORER_ID:
                seen.add((r["item_id"], r["step_id"], r["random_seed"], r["metric_name"]))
    n = 0
    with scores_p.open("a", encoding="utf-8") as f:
        for st in steps:
            for row in rescore_step(st):
                key = (row["item_id"], row["step_id"], row["random_seed"], row["metric_name"])
                if key in seen:
                    continue
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                n += 1
    return n
```

**实施要点**：① 入口脚本 `scripts/a_rescore.py <run_dir 或 batch_id>`（batch_id 时经账本找该批全部 run）；② 复评完成后经账本 API 追加 `run_scored` 事件？——**不追加**：`run_scored` 语义归 B 的 scorer；你复评不改 run 状态，比对结果进 auditor 报告（item 2）；③ 对 `data/golden/golden10.json` 内 pass_sample/fail_sample 的自检测试是**过门硬条件**：10 题 pass_sample 全判 1、fail_sample 全判 0；④ g05 注意 fixture 的 fake 输出可能带围栏也可能不带——两种都要过；⑤ 词表与句切分符集已裁决（AMENDMENT-6/21），无需再报疑议——落地从 constants.py import，勿各抄一份；⑥ 指标语义已冻结（AMENDMENT-21）：`parse_ok = int(bool(output_text.strip()))`、`output_len_chars = len(output_text)`（不 strip）、`output_len_tokens` = 转录 step 的 output_tokens 值——骨架即此实现，B 同式。

**交付物补列 · `scripts/a_rescore_compare.py`（R1-A6 的核验脚本）接口规格**：参数 `--runs <run 目录 glob 或 batch_id>`（缺省 `data/runs/*`；传 batch_id 时经账本折叠该批 run 集）与 `--against <expected.jsonl>`；比对对象 = rescore_v1 产出的 `is_correct` 行；join 键 = `(item_id, random_seed, condition, metric_name)`——expected_scores.jsonl 无法预知 run_id，**不按 run_id join**；输出契约：全同 → 打印 `MATCH N/N` 且 exit 0；任何不同 → 逐行打印 `MISMATCH <键> expected=<v1> got=<v2>` 且 exit 1。

**验收命令**：
```bash
python -m pytest tests/audit/test_rescore.py -v
# 必含用例: test_golden10_pass_samples_all_1, test_golden10_fail_samples_all_0,
#           test_idempotent_rerun_adds_zero_rows
# B 的 fixture 批次落盘后（R1 演练时）:
python scripts/a_rescore.py data/runs/<某假run_id>   # 预期: 新增行数>0，二跑=0
python scripts/a_rescore_compare.py --runs 'data/runs/*' --against fixtures/expected_scores.jsonl && echo OK
# 预期: 打印 "MATCH 60/60"（6 run×10 题）后输出 OK；g03/g07 为 0、其余 8 题为 1（与 R1-A6 同一口径）
```

### A1-6 auditor v0：六项中的 1 / 2 / 4（预计 3h）

**目标**：`src/abcr/audit/auditor.py`（编排 + item1/2）、`src/abcr/audit/health.py`（item4）与 `scripts/a_audit.py`（typer CLI 入口：位置参数 `batch_id`、`--items` 逗号分隔清单、`--apply` 开关；产出 `reports/audit/<batch_id>.{json,md}`——四处验收命令所引即此脚本）。输入 batch_id，输出结构化审计结果（报告格式见 A1-7）。阶段1 只做三项：

**item 1 · manifest 完整性**：对批内每 run 逐项核验——
- `manifest.json` 存在且含 §3.8 全部必含键（缺键逐个列出）；
- `steps.jsonl` 行数（粒度分明，勿混）：**单 run** 行数 == 该 run 实际 item 数 × 步数（W1 单轮 = 1 步；fixture 批 = 每 run 10 题 × 1 步 = 10 行——seed 已摊进 run 维度，单 run 断言**不再乘 seeds**）；**批粒度**总行数 == item 数 × |seeds| × |conditions|；每行过 `validate_step`；
- `scores.jsonl` 每行过 `validate_score`；
- 账本五链 `verify_chain()` 全过（含云链段 `ledger/cloud-day<N>/` 逐段独立 verify——AMENDMENT-2；读取合并只读，空链跳过）；该 run 在 runs_index 有完整生命周期事件（`derive_run_state` 无违规、终点 ≥ COMPLETED）；
- config_hash 重算一致：manifest 内嵌 config 按 §3.7 规范化 JSON 取 sha256 == manifest.config_hash == run_id 后缀 12 位；
- activation_summary 非 null 的 step，其指向的 `activations/*.npz` 文件存在（阶段1 fixture 无激活，SKIP 并注明）。

**item 2 · 重评分比对**：join B 的 `deterministic_v1` 行与你的 `rescore_v1` 行（键 = run_id, item_id, step_id, random_seed, metric_name），确定性指标（is_correct / parse_ok / output_len_chars）逐格相等；任何不等 = FAIL，证据列出双方值与该 step 的 output_text 前 80 字符。fixture 批同时比对 `fixtures/expected_scores.jsonl`（三方一致才 PASS）。

**item 4 · 健康面板**：从 steps 聚合五率——parse 失败率（safety_flags 含 parse_fail）、拒答率（refusal）、截断率（truncated）、空输出率（empty）、重复退化率（repetition）。**阈值（你的职权内默认值，写入报告头部，env 可覆盖）**：parse_fail>0.20、refusal>0.20、truncated>0.30、empty>0.05、repetition>0.20（对整批聚合）。任一超阈 → 处置 = **整批 QUARANTINED**（落账序按 A1-3 约定2 / AMENDMENT-16：批内每 run **先**追加 `run_audited` payload `{"verdict":"quarantined"}` **再**追加 `run_quarantined`，批次追加 `batch_audited` payload verdict:"quarantined"），报告 FAIL 并给出超阈率、命中 step 的 (run_id, item_id) 清单。**fixture 批的正确行为**：g03/g07 是 is_correct=0 的已知错误分布（判分错，不是 parse 失败）——五率应全部为 0、健康面板 PASS，而 item2 比对确认 g03/g07 的 0 分被双方一致复算。报告必须明示"g03/g07 低分 = fixture 设计的已知错误分布，非异常"，这句呈现是 R1 判据。

**编排接口**：

```python
def audit_batch(repo_root: Path, batch_id: str,
                items: tuple[int, ...] = (1, 2, 4)) -> "AuditReport":
    """按 items 执行审计项，返回 AuditReport（见 A1-7）。任何检查抛异常 =
    该项 FAIL 附 traceback 摘要，绝不让审计器自己崩掉（fail-safe，验船师恒在场）。"""
```

处置动作落账默认 **dry-run**，`--apply` 才真写账本——防误伤；R1 演练用 `--apply`。已裁决（AMENDMENT-16）的两条落账路径：① overall=**PASS** 且 `--apply`：逐 run 依序追加 `run_audited`（payload `{"verdict":"pass"}`）+ `run_accepted`，批次追加 `batch_audited`（payload `{"verdict":"pass"}`）——R1-A9 的视图判据（6 run 全 ACCEPTED、批次 AUDITED）以此为准；② 健康面板超阈且 `--apply`：按 item4 的 QUARANTINED 落账序。

**验收命令**：
```bash
python -m pytest tests/audit/test_auditor_v0.py tests/audit/test_health.py -v
# R1 演练时（B 的 fixture 批已跑完、你已 rescore）:
python scripts/a_audit.py <fixture_batch_id> --items 1,2,4 --apply
# 预期: item1 PASS；item2 PASS（三方一致，g03/g07 判 0 一致）；item4 PASS（五率为 0）
# 且 reports/audit/<batch_id>.md 含 "g03/g07 …… 已知错误分布" 呈现句
```

### A1-7 audit 报告格式（预计 1h）

**目标**：`AuditReport` 数据结构 + 双格式输出：`reports/audit/<batch_id>.json`（机器可读）与 `.md`（人读），同源生成（MD 由 JSON 渲染，禁止两处手写）。

**JSON 结构（冻结为你的输出契约，C 的同步视图会消费它）**：

```json
{
  "audit_schema_version": "1.0",
  "batch_id": "B-20260714T090000Z-0001",
  "generated_at": "2026-07-14T12:00:00+00:00",
  "auditor_version": "a-audit/1.0.0",
  "thresholds": {"parse_fail": 0.2, "refusal": 0.2, "truncated": 0.3,
                  "empty": 0.05, "repetition": 0.2},
  "items": [
    {"id": 1, "name": "manifest_completeness", "verdict": "PASS",
     "evidence": ["run 20260714T090001Z-…: manifest 22/22 键齐；steps 10 行全过 schema",
                   "ledger 五链 verify_chain 通过（云链段无，SKIP）"]},
    {"id": 2, "name": "rescore_comparison", "verdict": "PASS",
     "evidence": ["6 run × 10 item × is_correct 三方一致（deterministic_v1 = rescore_v1 = expected）",
                   "g03/g07 判 0 双方一致 —— fixture 设计的已知错误分布，非异常"]},
    {"id": 4, "name": "health_panel", "verdict": "PASS",
     "evidence": ["parse_fail 0/60=0.0 (阈 0.2) …五率逐条…"],
     "disposition": null}
  ],
  "overall": "PASS",
  "evidence_pointers": {"ledger_tail": {"runs_index": "<链尾hash>", "batches": "<…>"},
                         "runs": ["data/runs/<run_id>", "..."]}
}
```

规则：verdict ∈ {PASS, FAIL, SKIP}（SKIP 必附原因）；overall = 全 PASS 才 PASS；FAIL 项的 evidence 必须含**证据指针**（具体文件路径 + 行定位/链尾哈希），让人 1 分钟内能钻到原始记录；`disposition` 记处置动作（如 "quarantined 6 runs, dry_run=false"）。MD 版：标题 + overall 徽记 + 逐项表格 + FAIL 项证据代码块。

**验收命令**：
```bash
python -m pytest tests/audit/test_report_format.py -v   # JSON schema 断言 + MD 同源渲染断言
```

---

## 6. 阶段2 任务卡

> 进入条件：R1 门过（fable 宣布）。R1 后 fable 合并三分支到 main，你在 pkg/a 上继续（先 `git merge main` 取回 B/C 的阶段1 代码——只 merge，不改动他们的文件）。

### A2-1 auditor 3 · 防污染检查（预计 3h）

**目标**：`src/abcr/audit/contamination.py`，四道检查：

1. **抽取语料 ∩ 评测题 = ∅（哈希级）**：对 `data/traits/<trait>/` 内抽取用 instruction/prompt 集与 `data/benchmarks/`、`data/golden/` 内评测题，各自做规范化（strip + NFC + 折叠空白）后逐条 sha256，两集合交集必须为空；非空 = FAIL 列出命中对。
2. **split hash 核对**：按 §3.7 split 协议对 `data/splits/` 每个任务族重算 `split_hash`，与冻结入 git 的值、与批内 steps 的 split_hash 字段三方一致；且确认期（W1）批次只允许 dev split 的 item 出现——扫描 steps.item_id 是否全部属 dev（用 §3.7 的确定性切分公式独立重算归属，salt `abcr-w1-v1`）。
3. **judge 输入结构检查（不含条件字段）**：B 的 judge 调用按契约必须盲评。数据源已冻结（AMENDMENT-8）：`data/runs/<run_id>/logs/judge_calls.jsonl`——B 的 judge 客户端必须落此档，每行 `{ts, judge_model, item_id, messages 完整体, params}`（不含任何密钥）。逐条断言 messages 中**不出现**：condition 枚举词、trait_pole 标签（pos/neg）、臂标识词（"steered / inject / ablate / coef / layer=" 等）。断言集**不含 trait 名**（已裁决 AMENDMENT-31：官方 eval_prompt 必然含 trait 名，予以豁免）。按冻结路径直接实现，无需可配置路径、无需 D1 对齐。
4. **泄漏词表 grep**：词表 = CONDITIONS 全枚举 + trait_pole 标签 + `("steer", "steering", "inject", "ablat", "coefficient", "layer=", "persona_text", "vanilla")`；作用面 = judge 输入留痕（依 AMENDMENT-31 豁免 trait 名）+ `data/traits/` 评测题（questions）文本——**仅此作用面**的词表额外含批内 trait 名（防 trait 工件把条件词/trait 名写进题面）。命中即 FAIL 并给出 (文件, 行号, 命中词)。

**验收命令**：
```bash
python -m pytest tests/audit/test_contamination.py -v
# 用例须含: 人造一条含 "inject" 的 judge 留痕 → FAIL 并指到行；干净留痕 → PASS；
#          人造抽取/评测重叠句 → FAIL 列出哈希命中对
```

### A2-2 auditor 5 · 版本一致（预计 2h）

**目标**：三查——
1. **git clean**：manifest.git_clean 为 true 的 run，用 `git -C <repo> status --porcelain`（对 run 记录的 git_commit checkout 不可行，改为核 manifest 自述与 non_citable 标注的一致性：git_clean=false 而 non_citable=false = FAIL）；
2. **code_tree_hash 重算**：按 §3.7 定义对当前 worktree 重算，与 manifest.code_tree_hash 比对——不一致本身不必然 FAIL（审计时代码可能已推进），报告呈现"生成该数据的代码树哈希"与"当前哈希"，二者不同标注 `code_drift: true`；但**复现包出包前**（fable 调用时传 `--strict`）必须一致否则 FAIL。
3. **env lock**：manifest.env_lock_ref 指向的 lockfile 存在、非空、含 python 版本行；与 steps 的 env_lock_ref 一致。

**hash_tree / manifest 对账实现全码**（移植自 V2 hash-mode 对账，扩展多根多后缀以符合 §3.7 code_tree_hash 定义）：

```python
"""abcr.audit.treehash —— code_tree_hash 计算与三向对账（审计项5 的核心）。

架构位置：包A·验船师侧。§2.7 冻结定义：对 src/ scripts/ configs/ data/traits
data/golden data/benchmarks data/splits 逐文件 sha256（exts=.py .json .md .yaml .txt，
排除 __pycache__ .git .venv），code_tree_hash = sha256(json.dumps(树, sort_keys=True))。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

CODE_TREE_ROOTS: tuple[str, ...] = (
    "src", "scripts", "configs", "data/traits", "data/golden",
    "data/benchmarks", "data/splits")
CODE_TREE_EXTS: tuple[str, ...] = (".py", ".json", ".md", ".yaml", ".txt")
_EXCLUDE_DIRS = ("__pycache__", ".git", ".venv")


def hash_tree(repo_root: Path) -> dict[str, str]:
    """遍历冻结根集合，返回 {相对路径: sha256}。文件名排序保证确定性。"""
    out: dict[str, str] = {}
    for rel_root in CODE_TREE_ROOTS:
        root = Path(repo_root) / rel_root
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]
            for name in sorted(filenames):
                if not name.endswith(CODE_TREE_EXTS):
                    continue
                p = Path(dirpath) / name
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
```

（注意与被移植源的差异：源码版只收 `.py` 且 `json.dumps` 无统一空格约定——本实现按 §3.7 冻结定义扩了后缀与根集合。`json.dumps(树, sort_keys=True)` 用默认 separators，这与 §3.7 原文一致，**B 计算 manifest.code_tree_hash 必须同式**——阶段2 首日与 B 用同一 fixture 目录交叉验一次哈希相等，防"双实现哈希不等"这种低级劫难，写 PROGRESS 留痕。）

**验收命令**：
```bash
python -m pytest tests/audit/test_treehash.py -v
# 用例: 同一临时目录两次 hash 相等；改 1 字节 → drift 指到该文件；删文件 → missing
python -c "from pathlib import Path; from abcr.audit.treehash import code_tree_hash; print(code_tree_hash(Path('.')))"
# 预期: 稳定输出 64 位十六进制（连跑两次相同）
```

### A2-3 auditor 6 · 成本对账 + A2-4 budget_recon（合并实施，预计 4h）

**目标**：`src/abcr/audit/budget_recon.py`——两个职责：

1. **审计项6 · 成本对账**：对每个已 SETTLED 批次，join `costs.jsonl` 的 `run_cost_estimated` 与 `run_cost_actual`（键 subject_id；`run_cost_estimated` 由 B 的 dispatch 消费信封时逐 run 落账——已裁决 AMENDMENT-28①，预估侧数据源有生产方）：|actual−estimated|/estimated ≥ 10% = 该 run FAIL（证据给出双值）；批内任何 run 缺 `run_cost_actual` = FAIL（"跑了没记账"是硬伤）；`instances.jsonl` 每个 `instance_started` 必须有配对 `instance_stopped`（云纪律"完成即关机"），缺配对且距 started 超 1h = FAIL。
2. **预算熔断**：W1 云实耗上限 **¥150**（`ABCR_BUDGET_CAP_CNY` 覆盖，缺省 150）；∑run_cost_actual +（进行中实例的 时价×已运行小时 估计）≥ 85%（¥127.5）→ 熔断告警：经账本 API 追加 `budget_alert` 事件（payload: total_cny, cap_cny, ratio, breakdown）+ 写告警文件 `state/audit/alerts/budget-<UTC时间戳>.json`（阶段2 告警落文件/控制台，不接飞书）。同一告警 24h 冷却去重（state/audit/ 下节流文件，tmp+replace 原子写）。**熔断是告警不是拦截**——停批的决定在人（楠付费开机 = 发射钮，关停同理）；你的职责是让超线**不可能无声**。

**实现骨架**：

```python
"""abcr.audit.budget_recon —— 成本对账 + ¥150/85% 熔断告警（审计项6）。"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

DEVIATION_MAX = 0.10          # 审计项6 判据：预估 vs 实耗偏差 <10%
ALERT_COOLDOWN_S = 86400.0


def budget_cap_cny() -> float:
    """函数内读 env（照 A1-3 ttl_seconds() 写法）——模块导入期读会让测试的
    env 覆盖/monkeypatch 失效。"""
    return float(os.environ.get("ABCR_BUDGET_CAP_CNY", "150"))


def fuse_ratio() -> float:
    return float(os.environ.get("ABCR_BUDGET_FUSE_RATIO", "0.85"))


def _read_chain(repo_root: Path, chain: str) -> list[dict]:
    """装载主链 + 云链段（AMENDMENT-2：ledger/cloud-day<N>/ 各文件自成一链，
    verify 按段独立、读取合并只读）。"""
    paths = [Path(repo_root) / "ledger" / f"{chain}.jsonl"]
    paths += sorted(Path(repo_root, "ledger").glob(f"cloud-day*/{chain}.jsonl"))
    out: list[dict] = []
    for p in paths:
        if p.exists():
            out.extend(json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
                       if l.strip())
    return out


def total_actual_cny(repo_root: Path) -> float:
    return sum(float(e.get("amount_cny", 0.0)) for e in _read_chain(repo_root, "costs")
               if e.get("event") == "run_cost_actual")


def running_estimate_cny(repo_root: Path) -> float:
    """进行中实例估计（AMENDMENT-28②）：instances 链 started 无 stopped 者，
    按 payload.price_cny_per_h（AMENDMENT-9 键名）× 已运行小时累加。"""
    inst = _read_chain(repo_root, "instances")
    stopped = {e.get("subject_id") for e in inst if e.get("event") == "instance_stopped"}
    now = datetime.now(timezone.utc)
    total = 0.0
    for e in inst:
        if e.get("event") != "instance_started" or e.get("subject_id") in stopped:
            continue
        started = datetime.fromisoformat(e.get("started_at") or e["ts"])  # payload 优先
        hours = max((now - started).total_seconds(), 0.0) / 3600.0
        total += float(e.get("price_cny_per_h", 0.0)) * hours
    return total


def reconcile_batch(repo_root: Path, batch_id: str) -> dict:
    """审计项6：逐 run 预估/实耗偏差 + 实例开关机配对。返回结构化结果供 AuditReport。"""
    costs = _read_chain(repo_root, "costs")
    est = {e["subject_id"]: float(e["amount_cny"]) for e in costs
           if e.get("event") == "run_cost_estimated" and e.get("batch_id") == batch_id}
    act = {e["subject_id"]: float(e["amount_cny"]) for e in costs
           if e.get("event") == "run_cost_actual" and e.get("batch_id") == batch_id}
    fails: list[str] = []
    for rid, e_v in est.items():
        if rid not in act:
            fails.append(f"{rid}: 有预估无实耗（跑了没记账）")
        elif e_v > 0 and abs(act[rid] - e_v) / e_v >= DEVIATION_MAX:
            fails.append(f"{rid}: 偏差 {abs(act[rid]-e_v)/e_v:.1%} ≥ 10%"
                         f"（估 {e_v} 实 {act[rid]}）")
    inst = _read_chain(repo_root, "instances")
    started = {e["subject_id"]: (e.get("started_at") or e["ts"])   # payload.started_at 优先
               for e in inst if e.get("event") == "instance_started"}  # （演练注入用），缺省回退链 ts
    stopped = {e["subject_id"] for e in inst if e.get("event") == "instance_stopped"}
    for iid, ts in started.items():
        if iid not in stopped:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(ts)).total_seconds()
            if age > 3600:
                fails.append(f"instance {iid}: started 无 stopped 已 {age/3600:.1f}h（完成即关机违约）")
    return {"verdict": "FAIL" if fails else "PASS", "evidence": fails or ["偏差全部 <10%；实例开关机配对完整"]}


def check_fuse(repo_root: Path, ledger_append) -> dict | None:
    """85% 熔断：超线→ budget_alert 入账 + 告警文件；24h 冷却。ledger_append =
    costs 链 RunLedger.append 的绑定（由调用方注入，走 AMENDMENT-15 flock 写互斥）。
    演练（AMENDMENT-17）：repo_root 指向隔离 root 即可，节流/告警文件随之隔离。"""
    cap = budget_cap_cny()
    total = total_actual_cny(repo_root) + running_estimate_cny(repo_root)  # AMENDMENT-28②
    ratio = total / cap
    if ratio < fuse_ratio():
        return None
    throttle = Path(repo_root) / "state" / "audit" / "budget_alert_throttle.json"
    try:
        last = json.loads(throttle.read_text(encoding="utf-8")).get("ts", 0.0)
    except (OSError, ValueError):
        last = 0.0
    if time.time() - last < ALERT_COOLDOWN_S:
        return None
    payload = {"total_cny": round(total, 2), "cap_cny": cap,
               "ratio": round(ratio, 4), "actor": "budget_recon"}
    ledger_append("budget_alert", subject_id="W1", **payload)
    alerts = Path(repo_root) / "state" / "audit" / "alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (alerts / f"budget-{ts}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    throttle.parent.mkdir(parents=True, exist_ok=True)
    tmp = throttle.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
    tmp.replace(throttle)
    return payload
```

（payload 键名已裁决（AMENDMENT-9），无需再与 B 对齐：costs 事件必含 `{subject_id, amount_cny, basis}`（run 级事件另带 `batch_id` 辅助键）；instances 事件必含 `{instance_id, vendor, spec, price_cny_per_h, batch_id}`。AMENDMENT-9 适用于 run_cost_estimated / run_cost_actual 两事件；`budget_alert` 的 payload 按本卡定义（total_cny / cap_cny / ratio / actor），A 是其唯一写者。）

**验收命令**：
```bash
python -m pytest tests/audit/test_budget_recon.py -v
# 用例: 偏差 9% PASS / 11% FAIL；缺实耗 FAIL；实例无 stopped 超 1h FAIL；
#      人造 costs 总额 ¥128 → check_fuse 产出告警且 budget_alert 入账；重复调用 24h 内不重复告警；
#      进行中实例（started 无 stopped）按 price_cny_per_h×已运行小时计入熔断分子（AMENDMENT-28②）；
#      ABCR_BUDGET_CAP_CNY monkeypatch 覆盖生效（常量为函数内读取，导入期不固化）
```

### A2-5 冻结区 Seatbelt + 定稿仪式（预计 3h）

**目标**：`src/abcr/sandboxing/profiles.py`（profile 生成器）+ `scripts/a_freeze.py`（定稿仪式）。冻结区 = `data/golden`、`data/splits`、`data/traits`。机制：macOS Seatbelt（`/usr/bin/sandbox-exec`）内核级 deny file-write*——应用层纪律可被绕过，内核裁决不可（进程内 `open(...,'w')`、shell 重定向、rm 全部被拦，2026-07-11 本机 macOS 26.4.1 实测）。

**Profile 模板（实测通过，逐字嵌入）**——模板 A（黑名单式：全系统可写、仅冻结区只读），用于包裹 B 的执行进程：

```
; abcr-frozen.sb —— 模板 A：冻结区只读，其余全开（Seatbelt 语义: 最后命中生效）
(version 1)
(allow default)
(deny file-write* (subpath "/Users/superagent/abcr-wt/b/data/golden"))
(deny file-write* (subpath "/Users/superagent/abcr-wt/b/data/splits"))
(deny file-write* (subpath "/Users/superagent/abcr-wt/b/data/traits"))
```

模板 B（白名单式：默认禁写 + 放行工作区，包裹 claude CLI 级大进程树时用；阶段2 备选，非必交）：

```
(version 1)
(allow default)
(deny file-write*)
(allow file-write* (subpath "/Users/superagent/abcr-wt/b"))
(deny file-write* (subpath "/Users/superagent/abcr-wt/b/data/golden"))
(deny file-write* (subpath "/Users/superagent/abcr-wt/b/data/splits"))
(deny file-write* (subpath "/Users/superagent/abcr-wt/b/data/traits"))
(allow file-write* (subpath "/Users/superagent/.claude"))
(allow file-write* (subpath "/Users/superagent/.cache"))
(allow file-write* (subpath "/Users/superagent/.local/state"))
(allow file-write* (subpath "/private/tmp"))
(allow file-write* (subpath "/tmp"))
(allow file-write* (subpath "/private/var/folders"))
(deny file-write* (literal "/Users/superagent/.claude/settings.json"))
(deny file-write* (subpath "/Users/superagent/.claude/plugins"))
(deny file-write* (subpath "/Users/superagent/.ssh"))
```

**硬规则（血泪实测，逐条遵守）**：① 路径必须 realpath 展开的绝对路径——Seatbelt 不解析 `~`，且 macOS 上 `/tmp` 是 `/private/tmp` 的符号链接，规则要写 `/private/tmp`（保险起见两个都写）；落地前逐路径跑 `python3 -c "import os;print(os.path.realpath(os.path.expanduser('<路径>')))"`。② **最后命中生效（last-match-wins）**：deny 行必须排在覆盖它的 allow 行之后，顺序不能颠倒。③ `subpath` 匹配整棵子树，`literal` 匹配单文件。④ deny file-write* 覆盖写/删/改名/chmod（rm 实测被拦）。⑤ 只限写；读与网络全开。

**Profile 生成器骨架**（`profiles.py`；哪个 worktree 跑真实负载就生成哪个路径的 profile——mini 环在 B 的 worktree/云机跑，路径参数化，别写死）：

```python
"""abcr.sandboxing.profiles —— 冻结区 Seatbelt profile 生成 + wrap 启动。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
FROZEN_RELS: tuple[str, ...] = ("data/golden", "data/splits", "data/traits")


def available() -> bool:
    if os.environ.get("ABCR_SANDBOX_DISABLED") == "1":
        return False
    return sys.platform == "darwin" and os.path.exists(_SANDBOX_EXEC)


def _rp(p: str | Path) -> str:
    """realpath 展开（Seatbelt 不解析 ~，按 canonical 路径匹配 subpath）。"""
    return os.path.realpath(os.path.expanduser(str(p)))


def frozen_profile(work_root: str | Path) -> str:
    lines = ["(version 1)", "(allow default)"]
    for rel in FROZEN_RELS:
        lines.append(f'(deny file-write* (subpath "{_rp(Path(work_root) / rel)}"))')
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
```

**定稿仪式 `scripts/a_freeze.py <artifact_rel_path>`（人跑，你写脚本）步骤**：① 断言目标在冻结区三目录内且 git 已跟踪、工作区 clean；② 逐文件 sha256 + 目录树哈希（复用 treehash）；③ 经账本 API 落协议事件至第五链 `ledger/protocol.jsonl`——已批（AMENDMENT-7）：协议对象冻结事件立第五链（事件 `artifact_frozen / artifact_superseded`，payload: artifact, tree_hash, git_tag, actor="human"），无需再报疑议；④ `git tag freeze/<artifact名>-<UTC日期>`；⑤ 重新生成 Seatbelt profile（新冻结物自动纳入 deny）；⑥ 打印验证命令让人当场自证（见下）。

**验收命令（沙箱拦截实测，R2 演练4 的基础）**：
```bash
SB=/private/tmp/abcr-frozen.sb
python -c "from pathlib import Path; from abcr.sandboxing.profiles import frozen_profile; \
Path('$SB').write_text(frozen_profile('.'))"
/usr/bin/sandbox-exec -f $SB cat data/golden/golden10.json | head -3
# 预期: 正常读出
/usr/bin/sandbox-exec -f $SB /bin/sh -c "echo x >> data/golden/golden10.json"; echo "exit=$?"
# 预期: Operation not permitted, exit=1
/usr/bin/sandbox-exec -f $SB python -c "open('data/golden/x.txt','w')"
# 预期: PermissionError [Errno 1]
/usr/bin/sandbox-exec -f $SB /bin/rm data/golden/golden10.json
# 预期: Operation not permitted；golden10.json 安然无恙
python -m pytest tests/drills/test_seatbelt.py -v   # 上述四断言的自动化版
```

### A2-6 故障演练脚本四件（预计 4h）

规格全文在 §7（专项章）。交付物：`scripts/a_drill_1_kill.py`、`a_drill_2_fake_completion.py`、`a_drill_3_idle_instance.py`、`a_drill_4_frozen_write.sh` + `src/abcr/sandboxing/drills/` 内的共用断言库 + `tests/drills/`。**R2 门由 fable 手跑这些脚本**——所以每个脚本必须：单命令可跑、自带前置检查（缺依赖就 SKIP 并说清缺什么）、结束时打印 `DRILL {n} VERDICT: PASS|FAIL` + 留痕清单路径。

---

## 7. 专项章 · 故障演练脚本规格（四演练，R2 门 fable 手跑）

> 共同约定：演练在 **fixture 假任务负载**上做（零成本、确定性），不碰真实模型。**演练隔离（已裁决 AMENDMENT-17）**：故障演练一律在**临时隔离 root**（`state/audit/drills/<ts>/` 下的账本副本）上跑，**真链零写入**——演练脚本先把 `ledger/`（及所需 `data/runs/`）复制进隔离 root；注入与检测（auditor / budget_recon / reconcile 等的 `repo_root` 参数）一律指向隔离 root；演练注入事件 payload 必带 `actor="drill"`；演练用独立节流文件（隔离 root 自带 `state/audit/`，天然不触碰真实节流文件）。演练产物统一落 `state/audit/drills/<drill_n>-<UTC时间戳>/`（隔离账本副本、注入参数、捕获输出、断言结果 JSON）。故障旋钮环境变量已冻结（AMENDMENT-3）：`ABCR_FAKETASK_CRASH_AT_ITEM / ABCR_FAKETASK_HANG_AT_ITEM / ABCR_FAKETASK_SKIP_LEDGER_WRITES / ABCR_FAKETASK_EXIT_WITHOUT_DONE`。B 的 dispatch/resume 命令行入口以 B 的 `scripts/b_*.py` 实物为准（R2 前经 PROGRESS 与 fable/B 对齐一次，把最终命令回填进演练脚本；需 dispatch 的演练【1/2】把账本根指向隔离 root 的旗标/环境变量同此一并对齐）。

### 演练 1 · 杀 RUNNING 进程（恢复与续跑对账）

| 项 | 规格 |
|---|---|
| 注入方法 | 起一个 fixture 单 run 批次（B dispatch，后台运行）；轮询 runs_index 等到该 run 首个 `step_progress` 落账；对执行进程 `kill -9 <pid>`（pid 从 B 的 runstate 状态文件 `state/runs/<run_id>.json` 的 pid 字段读） |
| 期望检测者 | **B**：进程重启时 runstate `scan_orphans` 把残留 running 转 suspended；或 watchdog STALLED 告警（RUNNING 心跳陈旧） |
| 期望处置 | B 的续跑路径重入（`can_resume` 守卫过 → 只跑未完成 item，幂等不重做已完成 item），run 最终 COMPLETED |
| 留痕断言（你的脚本负责） | ① runs_index 含事件序 `run_started → step_progress+ → (run_failed 或 run_paused) → run_resumed → run_completed`，`derive_run_state` 无违规；② 账本五链（空链跳过）`verify_chain()` 全过（被杀进程 fsync 已保证不留半行——若出现坏行即 FAIL，说明 fsync 纪律破了）；③ steps.jsonl 无重复 (item_id, seed, step_id)（幂等证明）；④ rescore 该 run 与 expected 一致（杀进程不损数据） |
| 判 PASS | 四断言全过且全程无人工修数据 |

### 演练 2 · faketask skip_ledger_writes 伪报完成无 step（你是防线）

| 项 | 规格 |
|---|---|
| 注入方法 | `export ABCR_FAKETASK_SKIP_LEDGER_WRITES=1`（旋钮语义：假任务照常"跑完"并宣称完成，但不落 step_progress/steps 行）后 dispatch 一个 fixture 单 run 批次 |
| 期望检测者 | **A（你）**：auditor item 1 manifest 完整性——steps.jsonl 行数(0 或残缺) ≠ 信封期望(10)；runs_index 缺 step_progress 心跳与状态事件断档 |
| 期望处置 | auditor `--apply` 将该批 QUARANTINED（落账序按 AMENDMENT-16：批内 run **先**落 `run_audited` payload verdict:"quarantined" **再**落 `run_quarantined`，批次 `batch_audited` payload verdict:"quarantined"）；audit 报告 item1 FAIL 附证据（期望行数 vs 实际行数、缺失 item 清单） |
| 留痕断言 | ① `reports/audit/<batch_id>.json` overall=FAIL 且 item1 verdict=FAIL、证据含行数对比；② runs_index 含 `run_audited`（verdict:"quarantined"）与 `run_quarantined`，且 `derive_run_state` 无违规（审计豁免迁移 COMPLETED→AUDITED 合法——AMENDMENT-16）；③ QUARANTINED 数据原样留存（目录未删、未被重跑同 run_id 覆盖）；④ 链完整 |
| 判 PASS | "伪报完成"没有骗过审计：无 step 的"完成"被拦在 ACCEPTED 之外 |

### 演练 3 · 实例空转模拟（预算告警触发）

| 项 | 规格 |
|---|---|
| 注入方法 | **全程在隔离 root 的账本副本上**（AMENDMENT-17：真链零写入；演练所需 instances 事件由 A 的 drill 脚本在隔离副本内自行追加——隔离副本非生产账本，不算越权）：脚本经账本 API（隔离副本 instances 链）追加 `instance_registered` + `instance_started`（payload 按 AMENDMENT-9 键名: subject_id="drill-inst-01", instance_id="drill-inst-01", vendor="drill", spec="drill", price_cny_per_h=6.0, batch_id=null, actor="drill"；RunLedger.append 的 ts 是内部生成的，故在 payload 里带 `started_at` 业务时间戳字段（2 小时前），检测逻辑以 payload.started_at 为准、缺省回退链 ts——A2-3 骨架即此实现），**不**追加 instance_stopped；另经隔离副本 costs 链人造 `run_cost_actual` 若干条（payload 带 actor="drill"）使累计 ≥ ¥128（85% 线） |
| 期望检测者 | **A（你）**：budget_recon（`repo_root` = 隔离 root）——空转检查（started 无 stopped 超 1h）+ 85% 熔断 |
| 期望处置 | ① `budget_alert` 事件入隔离副本 costs 链；② 告警文件落隔离 root 的 `state/audit/alerts/budget-*.json`（repo_root 参数化，产物天然隔离）；③ reconcile 结果含 "instance drill-inst-01: started 无 stopped" FAIL 行（阶段2 告警落文件/控制台，不接飞书） |
| 留痕断言 | ① 隔离副本 costs 链尾部存在 budget_alert 且 payload.ratio ≥ 0.85；② 告警文件存在且字段齐；③ 24h 冷却生效（脚本连调两次，第二次不新增告警——节流文件在隔离 root 下，独立于真实节流，AMENDMENT-17）；④ 演练注入的人造行在演练目录 README 中登记（人造账目要可识别：payload 带 actor="drill"）；⑤ 真实 `ledger/` 链在演练前后逐字节不变（真链零写入的证明） |
| 判 PASS | 空转+超线均"不可能无声" |

### 演练 4 · 沙箱内越权写冻结区（EPERM + 留痕）

| 项 | 规格 |
|---|---|
| 注入方法 | `a_drill_4_frozen_write.sh`：先记录冻结区全树哈希（treehash）；然后在 Seatbelt 包裹下依次尝试四种写法——shell 追加重定向、`python -c "open(...,'w')"`、`/bin/rm`、`/bin/mv`——目标均为 `data/golden/golden10.json` |
| 期望检测者 | **内核 Seatbelt**（不是任何应用层代码）——这正是演练要证明的：防线在 syscall 层 |
| 期望处置 | 四种写法全部 `Operation not permitted` / `PermissionError [Errno 1]`，退出码非 0 |
| 留痕断言 | ① 四次尝试的 stderr 逐条捕获进演练目录（含 "Operation not permitted" 字样）；② 冻结区树哈希前后逐字节一致（treehash diff 三向全空）；③ 沙箱外对照组（不包 sandbox-exec 写 `/private/tmp` 下副本）成功——证明失败确因沙箱而非其他 |
| 判 PASS | 冻结区在内核层不可写的证明成立且全程留痕 |

---

## 8. 测试与验收总表（R1/R2 门你的全部判据项，逐条可执行核验）

### 8.1 R1 门（fable 主持 ≈1h；R1 演练全链 = `scripts/abcrctl approve fixtures/envelope_fixture.json --key fixtures/test_approval.key` → B dispatch → 6 假 run（含 1 个 crash 续跑）→ scorer 评分 → 你 rescore 比对 → 你 auditor 出报告 → C `abcrctl status` 批次全貌（C 四段 sync 与本包 A1-4 views 属 R1-full，不卡此门——AMENDMENT-30）。判据：全链零人工——批准动作除外）

| # | 判据 | 核验命令 | 预期 |
|---|---|---|---|
| R1-A1 | 契约测试全绿且未被你改动 | `python -m pytest tests/contract -q && git log --oneline -- tests/contract` | 全绿；git log 无 [pkgA] 提交 |
| R1-A2 | 你的全部单测绿 | `python -m pytest tests/ledger tests/audit -q` | 全绿 |
| R1-A3 | schema 收 fixture 全部记录、拒 12 变异 | `python -m pytest tests/contract -k schema -v` | 全绿 |
| R1-A4 | 哈希链断链检测 | `python -m pytest tests/ledger/test_ledger_ref.py -k tamper -v` | 全绿 |
| R1-A5 | 状态机非法迁移拒绝 | `python -m pytest tests/ledger/test_statemachine.py tests/contract -k transition -v` | 全绿 |
| R1-A6 | rescore 与 expected_scores.jsonl 全同 | `python scripts/a_rescore.py <各假run>` 后 `python scripts/a_rescore_compare.py --runs 'data/runs/*' --against fixtures/expected_scores.jsonl`（接口规格见 A1-5） | "MATCH 60/60"（6 run×10 题）且 g03/g07 为 0；exit 0 |
| R1-A7 | rescore 与 B 的 deterministic_v1 一致 | `python scripts/a_audit.py <fixture_batch_id> --items 2` | item2 PASS |
| R1-A8 | auditor 报告 + g03/g07 呈现 | `python scripts/a_audit.py <fixture_batch_id> --items 1,2,4 --apply && cat reports/audit/<batch_id>.md` | overall PASS；MD 含"已知错误分布"呈现句 |
| R1-A9 | 视图对该批出对（R1-full 项——AMENDMENT-30，views 未交付时顺延至 R1-full 验收） | `python scripts/a_views.py runs && python scripts/a_views.py batches` | 6 run 末事件全 `run_accepted`（ACCEPTED——R1-A8 `--apply` PASS 落账后，AMENDMENT-16）；批次末事件 `batch_audited`（AUDITED） |

### 8.2 R2 门（fable 主持 ≈2h）

| # | 判据 | 核验命令 | 预期 |
|---|---|---|---|
| R2-A1 | 演练1 杀进程 | `python scripts/a_drill_1_kill.py` | DRILL 1 VERDICT: PASS |
| R2-A2 | 演练2 伪报完成 | `python scripts/a_drill_2_fake_completion.py` | DRILL 2 VERDICT: PASS（含 QUARANTINED 落账） |
| R2-A3 | 演练3 实例空转 | `python scripts/a_drill_3_idle_instance.py` | DRILL 3 VERDICT: PASS（budget_alert 入账+落文件） |
| R2-A4 | 演练4 越权写冻结区 | `bash scripts/a_drill_4_frozen_write.sh` | DRILL 4 VERDICT: PASS（EPERM×4+哈希不变） |
| R2-A5 | 真实批次审计六项齐 | `python scripts/a_audit.py <7B_mini环_batch_id> --items 1,2,3,4,5,6` | 报告六项各有 verdict，无 SKIP（激活抽样项除外按实况） |
| R2-A6 | 防污染四道 | `python -m pytest tests/audit/test_contamination.py -q` + 上一行 item3 | 全绿；item3 PASS |
| R2-A7 | 版本一致 | 上 R2-A5 中 item5 + `python -c "...code_tree_hash..."` 双跑稳定 | PASS |
| R2-A8 | 成本对账 <10% + ≤¥150 逐实例登记 | 上 R2-A5 中 item6 + `python scripts/a_views.py` 查 instances | PASS；每 instance 有 started/stopped 配对与核价 |
| R2-A9 | 85% 熔断可触发 | 演练3 覆盖 | 同 R2-A3 |
| R2-A10 | 冻结区定稿仪式 | `python scripts/a_freeze.py data/golden`（人跑，你在场） | git tag + 哈希入账 + profile 生效 + 当场四验证命令过 |
| R2-A11 | 复现包独立复算（G5/闭合验收的你侧） | fable 新会话仅凭包独立复算——已裁决（AMENDMENT-20）：复现包同时打包你的 rescore 判分副本与 B 的 scorer 副本（均 stdlib 自包含，出包时空 PYTHONPATH import 自检），独立复算以**你的副本为主**（包内含 README） | 从原始 output_text 复算的分数与包内 deterministic_v1 与 rescore_v1 两组分数分别一致 |

（W1 出口门 G1–G7 中与你直接相关：G2 schema 就绪——R1-A3；G5 闭环闭合——R2-A11；G6 预算——R2-A8；G7 呈现纪律——你的报告与视图是数字唯一出处。）

---

## 9. 代码规范与 PROGRESS.md 格式

### 9.1 代码规范

- Python 3.12；**所有函数签名必须有 type hints**（含返回类型；内部辅助函数也不豁免）。
- **每个模块 docstring 说明其架构位置**（本文各骨架的 docstring 即示范：包归属 + 消费者 + 契约出处）。
- 测试用 pytest；测试文件与被测模块同名对应（`test_<module>.py`）；不用 unittest 风格类除非必要。
- 零外部依赖偏好：schema/statemachine/rescore/treehash 全部 stdlib（duckdb 仅 views、审计聚合可用 pandas——requirements-mac.txt 已含）。
- 不硬编码绝对路径（worktree 路径经参数/环境变量传入）；不硬编码 key。
- commit 格式：`[pkgA] description`，如 `[pkgA] add statemachine transition guard`。小步提交，每张任务卡 ≥1 commit；**只 commit 不 push**。
- 禁止改动 `tests/contract/`、B/C 归属路径、`constants.py`、`approval_token.py`（§2.4）。

### 9.2 PROGRESS.md 格式（每日收工必写，fable 唯一日常读物）

```markdown
# PROGRESS — pkg/a
## 2026-07-14（第 N 个工作日，4h）
### 完成
- [A1-2] schema.py 四入口 + 28 测试用例绿（commit abc1234）
### 未完成
- [A1-3] statemachine derive_run_state 写了一半，明日续
### BLOCKER
- （无 / 或：tests/contract/test_ledger.py::test_payload_key 期望 payload 键 "run"，
  与本包 subject_id 约定冲突——已停手待裁决，先切 A1-4）
### 契约疑议
- rescore manipulation 词表 constants.py 未含，本包按文档 §5/A1-5 表实现，
  请 fable 广播 B 对齐（双实现必须同定义）
```

纪律：BLOCKER = 阻塞超 30 分钟的事项，记完就换任务卡；契约疑议只提问题与你的临时选择，**不自行改契约物**；每节可空但四节标题必须在。

---

## 10. 已知坑与注意事项（坑 → 症状 → 规避）

1. **`json.dumps` 序列化口径不统一** → 双方哈希/签名不互认（envelope_sha256、config_hash 算不对，令牌 verify 恒 bad_signature）→ 规避：§3.7 口径背下来——普通哈希 `ensure_ascii=False, sort_keys=True, separators=(",", ":")`；**账本 entry_hash 与令牌载荷用默认 separators**（`ensure_ascii=False, sort_keys=True`，不带 separators 参数）。两处不同是契约现状，别"统一"它。
2. **bool 是 int 子类** → `isinstance(True, int)` 为真，脏数据 `"step_id": true` 悄悄过校验 → 规避：一切数值字段先 `isinstance(v, bool)` 拒掉（骨架 `_check_fields` 已内置，新增检查照抄）。
3. **payload 值非 JSON 原生可序列化**（set/datetime/float NaN）→ 账本 append 抛错或哈希不可复现 → 规避：append 前只传 str/int/float/list/dict/None；时间一律 ISO str。
4. **绕开 flock 的并发写同一链** → 链分叉断链 → 规避：全局五链一律走 `shared=True` 的 `ledger_ref.append`（`<chain>.jsonl.lock` flock 互斥 + 锁内重读链尾——AMENDMENT-15）；只有 `data/runs/<id>/steps.jsonl` 单写者才允许 `shared=False` 的链尾缓存；测试并发写只对 shared=True 链做，**绝不**绕过 API 直写链文件。
5. **审计器自己崩 = 验船师离场** → 一个 run 的坏 manifest 让整批审计中断 → 规避：每项检查独立 try/except，异常转该项 FAIL 附 traceback 摘要（fail-safe 包裹是 V2 生产纪律）。
6. **半写文件**（先 open("w") 后序列化，进程被杀留 0 字节）→ 下游读空档永久失灵 → 规避：一切整文件写=先 `json.dumps` 成字符串、写 tmp、`os.replace` 原子切换（告警文件、节流文件、报告 JSON 都照此）；JSONL 追加则靠 ledger_ref 的 flush+fsync。
7. **Seatbelt 路径没 realpath** → deny 规则悄悄不生效（`~` 不解析、`/tmp` 是符号链接）→ 症状：演练4 竟然写成功 → 规避：profile 内路径逐条 realpath；`/tmp` 写成 `/private/tmp`（或两个都写）。
8. **Seatbelt last-match-wins 顺序反了** → deny 被后面的 allow 翻盘 → 规避：deny 恒排最后；改 profile 后必跑 A2-5 的四条验证命令。
9. **`sandbox-exec` deprecated 警告** → 看到 deprecation 字样以为不可用 → 事实：macOS 26.4.1 本机 2026-07-11 实测完全可用；忽略警告，照用。
10. **DuckDB 读异构 JSONL 缺列报错** → `read_json` 各行键不同（事件 payload 异构）→ 规避：恒带 `union_by_name=true, format='newline_delimited'`；大 output_text 行加 `maximum_object_size`。
11. **views 把自己变成第二事实源** → 有人把 DuckDB 落成 .duckdb 文件并直接维护 → 规避：`:memory:` 连接、每次查询现读 JSONL；views.py 内出现任何非 SELECT 语句即违契。
12. **rescore "顺手" import B 的判分函数** → 双实现退化为单实现，同源 bug 失去对冲 → 规避：`abcr.audit.rescore` 的 import 列表里不得出现 `abcr.rig`；code review 自查这一行。
13. **重跑覆盖 QUARANTINED 数据** → 有效负结果被销毁（违反否证纪律，项目级事故）→ 规避：auditor 处置只追加事件与标记；任何"清理 data/runs"的冲动都非法；同 run_id 目录已存在时续跑只能走幂等对账，不能删目录重建。
14. **审计与执行共享节流/状态** → "双保险互抵"（V2 实测教训：一方先扫吃掉节流额度，另一方漏报）→ 规避：你的告警节流文件在 `state/audit/` 下自持，不 import B 的 watchdog 状态，不共享冷却计数。
15. **契约测试红了先改测试** → 三包地板被单方挖穿 → 规避：`tests/contract/` 你无写权；红了 = 你的代码错或契约有缺陷，前者改自己，后者走 PROGRESS 疑议。
16. **未定事项与已裁决事项的诚实标注**：唯一仍未定项 = **B 的 dispatch/resume 命令行入口**（R2 前经 PROGRESS 对齐后回填演练脚本，含指向演练隔离 root 的旗标）。以下五项曾列为未冻结、现已全部裁决——按对应任务卡执行、无需再报疑议：① faketask 旋钮环境变量已冻结（AMENDMENT-3：`ABCR_FAKETASK_CRASH_AT_ITEM / _HANG_AT_ITEM / _SKIP_LEDGER_WRITES / _EXIT_WITHOUT_DONE`）；② judge 留痕路径/字段已冻结（AMENDMENT-8，A2-1 检查3）；③ costs/instances 事件 payload 键名已冻结（AMENDMENT-9，A2-3/4）；④ `ledger/protocol.jsonl` 第五链已批（AMENDMENT-7，A2-5）；⑤ manipulation-check 词表与句切分符集已冻结（AMENDMENT-6/21，A1-5）。

---

*工程包A V1.0 终。契约修订权在 fable；本文与 `tests/contract/`、`src/abcr/common/constants.py` 冲突时，以仓库实物为准并即时上报 PROGRESS 契约疑议节。*
