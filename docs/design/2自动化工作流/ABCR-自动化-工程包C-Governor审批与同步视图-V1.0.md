# ABCR 工程包C · Governor审批与同步视图 V1.0

> **执行者须知（先读完本框再动手）**
> - 你是**窗口 C**（Claude Opus 4.8 high），三并行执行窗口之一。每日工作 **24 小时**。
> - 你的 worktree：`/Users/superagent/abcr-wt/c`，分支 `pkg/c`。只在这棵树内、只在归属矩阵分给你的路径上工作。
> - 项目按**阶段制**推进：阶段0 接口冻结（fable 已完成，契约全文嵌入本文 §3）→ 阶段1 无LLM最小闭环 → **回归门 R1** → 阶段2 真实执行 → **回归门 R2** → 阶段3 有限自治（本轮只交预置件，不接线）。任一回归门不过，不进下一阶段。
> - **fable 只在阶段门（R1/R2）与 BLOCKER 裁决时出现**，不参与日常编码。日常沟通唯一通道 = 你 worktree 根的 `PROGRESS.md`（格式见 §9）。阻塞超 30 分钟：记 BLOCKER、换下一张任务卡，不钻兔子洞。
> - **本文是你的全部输入**。你不允许读 shared-brain 下任何文件、不允许读《实现执行方案》原文、不允许上网调研（网络白名单见 §2.1 铁律②——你的包阶段1/2 零网络需求）。你能拿到的只有：本文 + `/Users/superagent/abcr` 仓库骨架（kickoff 已就位：契约库、fixture、黄金十题、契约测试）。本文引用的仓库内路径都是你拿得到的；本文嵌入的接口、代码、判据就是权威依据，不存在"另一份文档"。
> - **并行期可见性铁事实**：你的 worktree 里只有 kickoff 骨架 + 你自己写的代码。**A 包（账本/审计）与 B 包（Operator/rig）的模块在 R1 合并前不存在于你的树里**。你的一切依赖只能落在 `src/abcr/common/` 契约库、`fixtures/`、冻结 schema 本身。阶段1 测试用你自己按契约伪造的账本数据（任务卡里有生成器）。

---

## 0. 任务一页图

### 0.1 阶段1 交付清单（顺序即建议依赖序；R1-core / R1-full 拆分见表后注——AMENDMENT-30）

| 卡 | 交付 | 落点 | 验收锚 | 预计 |
|---|---|---|---|---|
| C1-1 | approval_token.py 维护权接管 + 补测 | `src/abcr/common/approval_token.py`、`tests/governor/test_approval_token.py` | 正样通过；六失败路径原因码各就位；契约测试不红 | 2h |
| C1-2 | envelope.py 信封校验/规范化/哈希 | `src/abcr/governor/envelope.py`、`tests/governor/test_envelope.py` | fixture 信封 validate 通过、sha 幂等稳定；≥8 变异样本拒绝 | 2h |
| C1-3 | abcrctl 人侧 CLI（draft/approve/reject/status） | `scripts/abcrctl` | approve 签发后自校验 verify ok；密钥首用生成 0600 | 3h |
| C1-4 | planner v0 固定规则计划器 | `src/abcr/governor/planner.py`、`plans/`、`tests/governor/test_planner.py` | 合法 spec 出草案+预检 PASS；越界 spec 逐项 FAIL 且不落草案 | 3h |
| C1-5 | triage v0 异常分诊 | `src/abcr/governor/triage.py`、`src/abcr/report/ledgerio.py`、`tests/governor/test_triage.py` | 模拟账本正确分桶；例外驱动排版（正常一行） | 2.5h |
| C1-6 | sync 四段同步视图 | `src/abcr/report/sync.py`、`src/abcr/report/blind.py`、`tests/report/test_sync.py` | 四段渲染入 `reports/`；逐数带 run_id；紧急段仅 A 级 | 3h |
| C1-7 | report 三层钻取 CLI | `src/abcr/report/views.py`、`src/abcr/report/cli.py`、`tests/report/test_views.py` | overview→批次/臂→单 run 单题原始输出，全程 ≤1 分钟 | 3h |

阶段1 合计 ≈ 18.5h ≈ 4.5 个工作日（4h/日）。

> **R1 拆分（已裁决——AMENDMENT-30）**：R1 门只验 **R1-core** = fixture 闭环六步所需最小件——你的 **C1-1（approval_token）+ C1-2（envelope）+ C1-3（abcrctl）**，7/14 上午过门；**C1-4 planner / C1-5 triage / C1-6 sync / C1-7 report 属 R1-full**，阶段2 期间完成、R2 前齐（验收判据不变，见 §8.1 标注）——阶段1 两个 4h 窗的工时由此立得住。
> **施工序注**：C1-7（views 查询面）**先于** C1-6（sync 渲染）施工——C1-6 的一切聚合取自 C1-7 的查询函数（卡编号保持不变，施工序以 §5 卡序为准，勿按编号序硬做）。

### 0.2 阶段2 交付清单（R2 前完成）

| 卡 | 交付 | 落点 | 验收锚 | 预计 |
|---|---|---|---|---|
| C2-1 | shadow 模式（草案 vs 人工决策差异记录） | `src/abcr/governor/shadow.py`、`plans/shadow/` | mini 环真实批次的 diff 记录存在且四关键维判定正确 | 2.5h |
| C2-2 | repro_pack.py 复现包出包 | `src/abcr/report/repro_pack.py`、`demos/repro-<batch_id>/` | 内容清单齐 + 全文件哈希；**仓库外**独立复算确定性分数全同 | 3.5h |
| C2-3 | 闭合验收协议文档（随包） | 包内 `ACCEPTANCE.md`（模板见 C2-3） | fable 开全新会话仅凭包复算一致（R2 ④） | 1h |
| C2-4 | 周证据对象包模板 | `reports/weekly/TEMPLATE-weekly-evidence.md` | 四节齐 + 对外禁令写入模板头注释 | 1h |
| C2-5 | 方向锁盲规则（W1 即建） | `src/abcr/report/blind.py` 强化 + `tests/report/test_blind.py` | `ABCR_PHASE=confirmation` 下输出无方向 token，测试绿 | 1.5h |
| C2-6 | sync/triage 真实数据适配 + 预算余量段 | `sync.py`、`triage.py` 增量 | 真实批次报告可读；G7 呈现纪律（exploratory 标注）全覆盖 | 1.5h |

### 0.3 你在回归门的判据项（细则与可执行核验见 §8）

- **R1（阶段1 末，fable 主持）**：fable 手跑演练脚本 `abcrctl approve fixtures/envelope_fixture.json --key fixtures/test_approval.key`（**必带 --key 旗标**：默认密钥是 state/approval.key，会以新生密钥重签，B dispatch 用 test key 验签必得 bad_signature）→ B dispatch 消费 → 6 假 run 执行（含 1 个 crash 断点续跑）→ 评分 → A 复评 → 审计 → **你的同步视图含该批全貌 + 三层钻取到单题原始输出**。你的判据：C-R1-1 ~ C-R1-8（§8.1）；按 AMENDMENT-30，R1 门只验 R1-core 判据（C-R1-1~4），C-R1-5~8 属 R1-full、阶段2 期间完成后对 fixture 批补验。全链零人工（批准动作除外）；契约测试仍全绿。
- **R2（阶段2 末）**：真实 7B mini 环批次从信封到审计报告全链。你的判据：C-R2-1 ~ C-R2-6（§8.2），核心两件——shadow 差异记录成立、**复现包闭合验收**（fable 开全新会话仅给包，从原始输出复算全部确定性分数一致）。

---

## 1. 项目背景速览 + 术语表 + 否证标准 + 呈现纪律

### 1.1 背景速览（≤12 行）

ABCR 是楠的人格向量实验项目：12 周研究「文本人格效应是否由可命名内部方向中介」，主线配方为 Persona Vectors 式残差差分向量（对模型 hidden states 做注入/消融干预，对照文本 persona 提示）。当前在 W1：按已冻结的《实现执行方案 V1.0》建设**实验控制面 + W1 最小纵向闭环**。控制面先用假任务证明自己是对的（阶段1），再用真实验证明自己是有用的（阶段2，7B mini 环是第一个真实负载）。三包分工：**A = 账本 + 状态机 + Auditor（裁判 + 验船师）**；**B = Operator + 队列 + 恢复 + rig + 科学载荷（运动员）**；**C = 你 = Governor + 审批信封 + 同步视图（大副）**。核心治理思想：**计划级批"信封"、运行级零审批**——人批准一个带预算与范围的信封，信封内的 run 全自动跑；信封外任何一维越界自动升协议级 = 拒绝执行。账本（append-only 哈希链 JSONL）是单一事实源；你的一切呈现数字必须出自账本查询，禁止自由回忆。W1 全部批次实际上都由人（楠或 fable 代）批准；阶段3 的有限自治（信封内自动派发）本轮只交预置件不接线。

### 1.2 术语表（逐字嵌入，勿另行发明措辞）

- **人格标签** = Big Five 等外部理论标签，仅用于对表文献。
- **行为控制原语** = 可测量、可干预并影响任务轨迹的内部方向或神经元集合（例：探索、验证、坚持、校准、质疑）。
- **自适应行为策略** = 按任务特征与历史反馈选择原语、方向、层和强度的路由策略。

### 1.3 否证标准（逐字嵌入；任一出现记**有效负结果**入账本，不得丢弃或重跑覆盖）

人格评分变化明显但能力变化在控制长度和格式后消失※；只有单个 benchmark、单个系数、单个模型有效；随机等范数方向产生同等增益；calibration 有增益 held-out 反转；动态路由不优于按 benchmark 固定人格（G1 后适用）；内部干预普遍不如文本提示；正负 steering 均只导致输出质量下降；量化模型有效而 BF16 不复现；LLM judge 喜欢 steered 输出但确定性准确率不变。※修正注（V1.3 M9）：长度不再作硬性条件化变量，改三段分解报告；硬性否证前提仅随机方向对照 / 流畅性 PPL / 格式遵循三项。

### 1.4 呈现纪律（逐字嵌入——这是你这个包的第一戒律）

W1 一切数字带 `exploratory / rig-validation` 标注；mini 环产出不构成任何假设的证据；对外材料数字必须出自账本视图（三轨共享同一事实源）。QUARANTINED 批不删除、不采纳、不重跑覆盖——留证 + 人裁决。

你是三包中**唯一的对外呈现出口**（同步视图、钻取、周证据包、复现包）。呈现纪律违规（数字无来源、exploratory 缺标注、确认期泄方向）在 R 门按 FAIL 计，与代码 bug 同责。

---

## 2. 铁律与边界

### 2.1 三条铁律（逐字，全项目共同宪法）

① 三包只通过稳定接口（§3 账本文件 + 信封文件 + 契约库 API）通信，**禁止互相直接读写对方内部状态**（`state/alerts/` 告警文件接口除外——AMENDMENT-18，见 §2.2）；② 只在自己 worktree 内动归属矩阵分给自己的路径，不访问 shared-brain，网络白名单 = pypi / hf-mirror.com / api.deepseek.com / github.com 克隆 / registry.ollama.ai（仅 B 拉第二 judge 模型一次）/ modelscope.cn（HF 镜像降级备选）/ 云实例 SSH 主机（云日回传）——AMENDMENT-26 增补，后三项皆 B 用，你的包阶段1/2 零网络；③ 每日收工写 `PROGRESS.md`，阻塞超 30 分钟记 BLOCKER 换任务，不钻兔子洞。

### 2.2 目录归属矩阵（你的部分）

你**可创建/修改**的路径（全部相对 worktree 根 `/Users/superagent/abcr-wt/c`）：

```
src/abcr/common/approval_token.py   ← 维护权归你（kickoff 已交付 canonical 全码，你接管）
src/abcr/governor/                  ← envelope.py planner.py triage.py（+你新增的 shadow.py）
src/abcr/report/                    ← views.py sync.py repro_pack.py weekly.py（+cli.py blind.py ledgerio.py）
src/abcr/notify.py                  ← 阶段3 接线，代码先交付（§7）
scripts/abcrctl                     ← 人侧 CLI（无前缀，C 专属）
scripts/c_*.py                      ← c_ 前缀脚本归你
configs/envelopes/                  ← 信封草案与已批信封（读写）
plans/                              ← 计划器工作区：specs/ precheck/ shadow/（读写）
reports/                            ← sync-*.md triage-*.md weekly/（产物，入 git 可选；命名分区见 AMENDMENT-31 注）
demos/                              ← 复现包产物（repro-<batch_id>/ 前缀）
tests/governor/  tests/report/      ← 你的测试
PROGRESS.md                         ← 你 worktree 自己的（不合并）
```

你**只读不写**的路径：`src/abcr/common/ledger_ref.py`（A 维护）、`src/abcr/common/constants.py`（fable 维护）、`src/abcr/ledger|audit|sandboxing/`（A）、`src/abcr/ops|rig|judge/`（B）、`ledger/`（abcrctl 三事件例外，见 §2.3——AMENDMENT-10）、`queue/`、`data/`（全部）、`fixtures/`、`tests/contract/`、`.env`。`state/` 特殊：`state/approval.key` 与 `state/approvals/consumed.json` 是你维护的令牌接口件（abcrctl 写 key；consumed.json 由 B 的消费接口写、你只读展示）；`state/alerts/` 是**告警文件接口**（已裁决——AMENDMENT-18，豁免"私有黑箱"铁律：B 写、A/C 只读；文件名 `<ts>-<kind>.json`，JSON 至少 `{ts, kind, severity(A/B/C), subject_id, reason}`）；`state/` 其余子路径是各包私有黑箱，别碰。

**reports/、demos/ 命名分区（已裁决——AMENDMENT-31）**：reports/ 与 demos/ 是三包共享命名空间——B 写 `b_*` 前缀与 `flip_demo_*`，A 写 `reports/audit/`，你限 `sync-* / triage-* / weekly/` 与 `demos/repro-*`。勿撞他包前缀。

### 2.3 权限矩阵（逐字嵌入；你 = Governor 列）

| 路径/对象 | rig(B) | Operator(B) | Governor(C) | Auditor(A) | 人 |
|---|---|---|---|---|---|
| data/golden、data/splits、data/traits（冻结区） | 只读 | 只读 | 只读 | 只读 | 唯一写入者（经 B 起草、定稿仪式冻结） |
| data/runs/*/steps.jsonl、scores.jsonl | 追加(steps) / 追加(scorer 的 scores) | 只读 | 只读 | 追加(rescore 的 scores) | 只读 |
| ledger/*.jsonl（runs_index/batches/costs/instances/protocol） | 经账本 API 追加 | 经账本 API 追加 | **只读** | 追加(审计事件) | batches.jsonl 限 batch_drafted/batch_approved/batch_rejected 三事件经 abcrctl 追加（AMENDMENT-10），其余只读 |
| queue/ | — | 读写 | 只读 | 只读 | 读写 |
| configs/envelopes/、plans/ | — | 只读 | **读写（草案）** | 只读 | 审批签名 |
| state/（各包私有内部状态） | 各归属者私有 | 同 | 同 | 同 | — |

**接口 = 账本文件 + 信封文件 + data/runs 产物 + 契约库 API。各包内部状态（queue 细节、planner 中间物、审计工作区）互为黑箱。**

✅ **已裁决（AMENDMENT-10，取代此前"无落账者"缺口）**：`batch_drafted / batch_approved / batch_rejected(人工驳回)` 三事件由 **abcrctl（人侧 CLI）以"人"身份追加**至 batches.jsonl——权限矩阵"人"行修订为"batches.jsonl 限此三事件经 abcrctl 追加"；**Governor 进程本体（planner/triage/sync/views）仍对账本只读**；B 的 dispatch 落 `batch_dispatch_started` 起的事件（dispatch 侧拒绝另立 `batch_dispatch_rejected`，B 落账——AMENDMENT-13）。信封文件仍是 DRAFT/APPROVED 态的**权威载体**（`approval` 字段有无 + `.reject.json` 有无），账本事件为审计镜像：你的 status/sync 以信封文件为准展示这两态、以账本折叠展示 DISPATCHING 之后的态。落账实现见 C1-3 嵌码 `_ledger_append`（subject_id=batch_id, actor="human"）。

### 2.4 明确禁止清单

1. **不做一切执行与评分**——faketask/rig/scorer 是 B 的，rescore 是 A 的。你只读它们的产物。
2. **不写账本**（权限矩阵 Governor 进程本体=只读；唯一例外 = abcrctl 以"人"身份经 ledger_ref 落 `batch_drafted/batch_approved/batch_rejected` 三事件——AMENDMENT-10，见 §2.3。除此之外一切"该有个事件"的想法进 PROGRESS 契约疑议，不自行突破）。
3. **不做 boss_console 式界面**。一切交付是 CLI + Markdown/JSON 文件。
4. **不主动接线飞书**（阶段3 才接）。notify.py 只交代码 + mock 单测，`ABCR_NOTIFY_ENABLED=0` 默认关。
5. **planner/triage 零 LLM**——固定规则。禁止在这两个模块里调用任何模型（包括你自己"顺手判断一下"）。
6. **同步视图禁止自由回忆**——每个数字必须来自账本/scores 文件查询且带 run_id；模板里不许出现手写数字。
7. **确认期（ABCR_PHASE=confirmation）同步不含效应方向**（§C2-5，W1 即建代码路径）。
8. 不改 `tests/contract/`、不改 `constants.py`、不动 A/B 的目录；契约疑议只走 PROGRESS.md，**契约修订权在 fable**。
9. 不访问 shared-brain；不把任何密钥/凭证值写入 git（`state/`、`.env` 均已 gitignore，保持）；不建远端、不 `git push`。
10. 只 commit 到 `pkg/c` 分支；commit 信息格式 `[pkgC] description`（§9）。

---

## 3. 冻结契约摘录（阶段0 产物；修订权在 fable，修订即广播。本节 = 你需要的契约全文）

### 3.1 仓库、worktree 与路径全貌

仓库 `/Users/superagent/abcr`，本地 git 无远端（repo 级身份 abcr/abcr@local，不 push——楠 2026-06-10 决策）。fable 在 kickoff 已建三分支三 worktree：

```
主仓 /Users/superagent/abcr           分支 main（只由 fable 在回归门合并推进）
worktree /Users/superagent/abcr-wt/a  分支 pkg/a  ← 窗口 A
worktree /Users/superagent/abcr-wt/b  分支 pkg/b  ← 窗口 B
worktree /Users/superagent/abcr-wt/c  分支 pkg/c  ← 你
vendor   /Users/superagent/abcr-vendor/persona_vectors  ← 官方仓库 clone（git 之外，B 专属，你不碰）
```

目录归属全图（`共` = 阶段0 fable 交付后冻结，改动 = 契约修订）：

```
abcr/
├── .env .gitignore requirements-mac.txt README.md        共（.env 系 kickoff 注入**主仓根**且已 gitignore——不入 git、不随 worktree 检出；worktree 内用到需 ABCR_ROOT，见 §7.3）
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
│   ├── vectors/                                          B（向量产物落位，非冻结区——AMENDMENT-27）
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

`ledger/` 下**五个** append-only JSONL（第五链 protocol.jsonl 系 AMENDMENT-7 增补），全部走哈希链，**只能经 `src/abcr/common/ledger_ref.py` 的 API 写入**（你的进程本体只读、abcrctl 三事件例外见 §2.3，但必须懂它的记录形状才能查询）：

- `runs_index.jsonl` —— run 生命周期事件。事件词表（枚举冻结）：`run_registered, run_queued, run_started, step_progress, run_paused, run_resumed, run_failed, run_completed, run_scored, run_audited, run_accepted, run_quarantined, run_cancelled`。`step_progress` 由 B 每完成 N=5 个 item 追加一次（payload 含 steps_done/items_done），**这就是进度心跳**——"在岗"的唯一定义是账本 step 推进。**`run_registered` 事件 payload 必含 `batch_id` 辅助键（已裁决——AMENDMENT-19：这是 run↔batch 关联的账本通道；未启动 run 的钻取降级用信封 run_configs 对账）。**
- `batches.jsonl` —— 批次事件：`batch_drafted, batch_approved, batch_rejected, batch_dispatch_rejected, batch_dispatch_started, batch_settled, batch_audited, batch_reported`。语义（已裁决——AMENDMENT-13）：`batch_rejected` = **人工驳回**（abcrctl 落账——AMENDMENT-10）；`batch_dispatch_rejected` = 令牌校验失败或信封越界被 dispatch 拒绝（**B 落账**，payload 带原因码 + subject_id=batch_id）。
- `protocol.jsonl` —— 协议对象冻结事件：`artifact_frozen, artifact_superseded`（已裁决——AMENDMENT-7 第五链）。
- `costs.jsonl` —— `run_cost_estimated, run_cost_actual, budget_alert`。costs 事件 payload 必含 `{subject_id, amount_cny, basis}`（已裁决——AMENDMENT-9）。
- `instances.jsonl` —— `instance_registered, instance_started, instance_stopped, instance_idle_alert`。instances 事件 payload 必含 `{instance_id, vendor, spec, price_cny_per_h, batch_id}`（已裁决——AMENDMENT-9）。

**账本记录形状（ledger_ref 权威实现的输出，你的查询按此解析）**：每行一个 JSON 对象——
`{ts, run_id, event, ...payload, prev_hash, entry_hash}`。注意两个易错点：
① 顶层 `run_id` 字段是**链 id**（历史命名），恒为文件 stem（`runs_index`/`batches`/`costs`/`instances`）；**业务主体 id（具体 run/batch/instance）在 payload 键 `subject_id` 里**。例：`{"ts": "...", "run_id": "runs_index", "event": "run_started", "subject_id": "20260714T090000Z-ab12cd34ef56", ...}`。
② `ts` 为 UTC ISO8601（`timespec="seconds"`，带 +00:00）。
⚠️ `subject_id` 键名约定已冻结（AMENDMENT-4：全局账本事件主体一律 `subject_id` 键 + 辅助键，payload 不得用 run_id/batch_id 作键名）；若与 `tests/contract/` 现行断言或 fixture 记录不一致，**以仓库实物为准**并在 PROGRESS 契约疑议节报 fable——这是你 D1 要核对的事（§4.4）。

**哈希链协议**（你不算链，但 status/审读需要认知）：`GENESIS_HASH="0"*64`；`entry_hash = sha256(json.dumps(含prev_hash不含entry_hash的本条, ensure_ascii=False, sort_keys=True).encode() + prev_hash.encode())`；append 后 flush+fsync；每文件一条链。**全局五链并发写互斥（已裁决——AMENDMENT-15）**：ledger_ref.append 对 `<chain>.jsonl.lock` 持 fcntl.flock(LOCK_EX)、锁内重读链尾再写（全局链放弃链尾内存缓存）——abcrctl 落账与 B 的写者并发安全即由此保证。

**云侧链段（已裁决——AMENDMENT-2 原文）**：云机上产生的账本事件写**独立哈希链段**（`ledger/cloud-day<N>/` 子目录，各文件自成一链），随产物整体回传归档，不与 Mac 侧链拼接；Auditor 对账时按段独立 verify_chain。→ **对你的含义**：真实批次（阶段2 起）的事件可能分布在主链与云链段，你的一切账本装载必须合并读入 `ledger/<chain>.jsonl` **与** `ledger/cloud-day*/<chain>.jsonl`（只读合并视图，不拼链、不校验哈希——见 ledgerio 的 `read_chain_merged`）。

### 3.3 三层状态机（A 实现迁移守卫；你只做只读推导）

- **协议对象**：`DRAFT → REVIEW → FROZEN →（AMENDMENT→新版本）→ SUPERSEDED`。W1 冻结对象 = golden10、splits、traits、黄金判据。
- **批次对象**：`DRAFT → APPROVED → DISPATCHING → SETTLED → AUDITED → REPORTED`。APPROVED 必须携带有效审批令牌（§3.5）。
- **运行对象**：`PLANNED → QUEUED → RUNNING → {PAUSED, FAILED} → COMPLETED → SCORED → AUDITED → {ACCEPTED, REJECTED, QUARANTINED}`；终态另有 `CANCELLED`；FAILED 可 RESUME 回 RUNNING。
- **TTL 表（秒，constants.py 冻结，env 可覆盖）**：QUEUED 3600；RUNNING 心跳间隔上限 1800（零新 step_progress 即停摆告警）；COMPLETED→SCORED 7200；SCORED→AUDITED 7200。

事件→状态全映射（与 A 的 statemachine 同表，另加 AMENDMENT-13 两拒绝事件的呈现标记映射；你在 `report/ledgerio.py` 持只读副本，R1 后可自愿改 import A 的 `abcr.ledger.statemachine`——若切换，两拒绝事件的呈现标记映射保留在你侧）：

```
run:   run_registered→PLANNED  run_queued→QUEUED     run_started→RUNNING
       run_paused→PAUSED       run_resumed→RUNNING   run_failed→FAILED
       run_completed→COMPLETED run_scored→SCORED     run_audited→AUDITED
       run_accepted→ACCEPTED   run_quarantined→QUARANTINED  run_cancelled→CANCELLED
       （step_progress 不改状态，只刷心跳时间）
batch: batch_drafted→DRAFT  batch_approved→APPROVED  batch_dispatch_started→DISPATCHING
       batch_settled→SETTLED  batch_audited→AUDITED  batch_reported→REPORTED
       batch_rejected→REJECTED(呈现标记)  batch_dispatch_rejected→DISPATCH_REJECTED(呈现标记)
       （AMENDMENT-13 两拒绝事件；批次冻结状态机主线六态不含拒绝态，此二映射仅供你只读折叠呈现，
         迁移守卫语义以 A 的 statemachine 为准）
```

补充解释性约定（已裁决——AMENDMENT-5，你的呈现按此读）：事件词表无 `run_rejected`——REJECTED 经 `run_audited` 事件 payload `{"verdict": "rejected"}` 表达；"整批 QUARANTINED" 落账 = 批内全部 run 各追加 `run_quarantined` + 批次 `batch_audited` 事件 payload `{"verdict": "quarantined"}`（事件词表不再扩枚举）。

### 3.4 step 与 scores 记录 schema v1（你的钻取/同步读的就是这些字段）

**steps.jsonl**（`data/runs/<run_id>/steps.jsonl`，每行一条，append-only + 哈希链），48 业务字段：

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
| 17 | split_hash | str | 否 | §3.5 哈希协议 |
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
| 29 | chat_template_hash | str | 否 | 假任务 "fixture" |
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
| 45 | activation_summary | str | 是 | 摘要文件相对路径（10% 抽样） |
| 46 | state_snapshot_ref | str | 是 | 合成轨迹测试须演示非 null 写读 |
| 47 | protocol_ref | str | 否 | W1 = "W1-V0.9" |
| 48 | env_lock_ref | str | 否 | lockfile 相对路径 |

**scores.jsonl**（评分是独立 pass，可多 scorer 多次追加）：字段 `schema_version, run_id, item_id, trajectory_id, step_id, condition, random_seed, metric_name, metric_value, scorer_id, scorer_version, scored_at`。metric_name 枚举：`is_correct / trait_score / coherence_score / fluency_score / output_len_chars / output_len_tokens / hedging_rate / self_check_marker_rate / parse_ok`。**manipulation-check 指标与能力指标分列**（"行为动了但能力没动本身是发现"）。scorer_id 枚举：`deterministic_v1`（B）、`judge_deepseek_v1`（B）、`rescore_v1`（A）——B 与 A 对确定性指标是**有意双实现**。你的呈现里凡引用确定性指标，写明取自哪个 scorer_id；两者不一致本身是 A 审计的 FAIL 项，你在 triage 里呈现即可。

**run 产物布局**：`data/runs/<run_id>/{manifest.json, steps.jsonl, scores.jsonl, activations/, logs/}`。manifest 必含：run_id、config 全文内嵌、config_hash、git_commit、git_clean、code_tree_hash、model_id、model_revision、chat_template_hash、split_hash、engine/engine_version、torch_version、python_version、env_lock_ref、seeds、started_at/finished_at、status、non_citable、protocol_ref、batch_id。**复现包（C2-2）按此清单打包；`non_citable:true` 的 run 在你的一切呈现里必须显式标注。**

### 3.5 批次信封与审批令牌（契约 §2.6 逐字 + 哈希协议——你的包的心脏）

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
  "approval": {"token": {"...": "见 §C1-1 代码"}, "approved_at": "..."}
}
```

**审批令牌**：HMAC-SHA256，纯 stdlib，canonical 实现在 `src/abcr/common/approval_token.py`（kickoff 已就位，**你接管维护权**，全码见 C1-1）。载荷字段 `(token_id, scope, task_id→batch_id, changeset_sha256→envelope_sha256, expires_at, persona_change→false)`（字段名承 V2 canonical，箭头表示"该字段承载的 ABCR 语义"），序列化口径 `json.dumps(core, ensure_ascii=False, sort_keys=True)`（**默认 separators——签名互认的要害**）；envelope_sha256 = 对信封**去 approval 字段**后的规范化 JSON 取 sha256。**签发权在人**：密钥 `state/approval.key`（32 字节，0600，abcrctl 首用生成；fixture 用 `fixtures/test_approval.key`）；人跑 `abcrctl approve <envelope>` 签发；B 的 dispatch 只接受 verify 通过的信封（**校验顺序契约冻结：结构→scope→恒时比较签名→envelope 哈希→过期→已消费；fail-closed**）；批次 SETTLED 后才 consume。信封外任何一维（超预算、越 split、加臂）自动升协议级 = 拒绝执行 + 记账 + 告警。**确认期批次的"发射"永久保留人手，W1 全部批次实际上都由人批准。**

**哈希协议（全项目统一，与令牌相关的两条逐字）**：
- **prompt_hash / obs_hash / envelope_sha256 / config_hash**：sha256(UTF-8 字节)，JSON 一律 `ensure_ascii=False, sort_keys=True, separators=(",", ":")` 规范化。
- ⚠️ 注意**两个口径并存**：envelope_sha256 用紧凑 separators `(",", ":")`；令牌载荷签名用 `json.dumps` **默认** separators（`", "` 与 `": "`）。两处都冻结，混用即签名/哈希不互认（§10 坑 K1）。

### 3.6 config 与 run_id（planner 与钻取需要）

run config 单 JSON（必含 model/benchmark/condition/decoding/steering_position/protocol_ref，具体键形由 B 定义并落 `configs/experiments/`——你的 planner 只核对文件存在与信封维度，不解析 B 的内部键）。`config_hash = sha256(规范化 JSON)`（紧凑口径）；`run_id = f"{batch_id时间戳段}-{config_hash[:12]}"`（已裁决——AMENDMENT-22：时间戳分量取信封 batch_id 内嵌时间戳，确定性——同信封同 config 恒同 run_id，dispatch 幂等的根基；仅无信封的 `--dev` 裸跑用当刻 UTC；信封内 run_configs 的 config_hash 必须唯一，dispatch 发现重复即拒）。启动前置检查是 B 的事；`git_clean=false` 的 run 其 manifest 打 `non_citable:true`——你的呈现必须透传该标注。

### 3.7 黄金十题（golden10 —— 已冻结于 `data/golden/golden10.json`；你的复现包独立复评脚本需要判分语义）

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

### 3.8 fixture（阶段1 三包共同的靶；kickoff 已交付于 `fixtures/`）

① `envelope_fixture.json`——一个含 6 个假 run config 的信封（2 condition × 3 seed，benchmark=golden10，engine=fake）+ 用 `test_approval.key` 预签的有效令牌；①′ `envelope_fixture_badtoken.json`——坏令牌**独立样例文件**（文件名冻结——AMENDMENT-12；不在 envelope_fixture.json 内部）；② `faketask_spec.md`——确定性假任务定义：对 item_id=gXX 输出 golden10 的 pass_sample（其中 g03/g07 输出 fail_sample，制造已知错误分布），每 item 耗时 0.2s，暴露故障旋钮 `crash_at_item / hang_at_item / skip_ledger_writes / exit_without_done`（环境变量注入）；③ `expected_scores.jsonl`——该信封跑完后确定性期望分数（is_correct 8/10 题为 1）；④ `test_approval.key`。契约测试 `tests/contract/`：schema 校验器接受 fixture 全部记录、拒绝 12 个变异样本；**令牌正样验证通过、坏令牌六种失败路径各返回正确原因码**；哈希链断链检测；状态机非法迁移拒绝。

**fixture 对你的意义**：预签令牌是你 C1-1 的**真值锚**——你维护的 approval_token.py 必须让 fixture 正样 verify 通过、坏样返回正确原因码。你写的任何"维护性修改"若使契约测试变红，即为越权，立即回退。

### 3.9 激活存储策略（复现包打包需要认知）

全量激活不落盘。只存：① 抽取语料分层均值激活（B 自产）；② 评测运行中按 item_id 哈希尾数确定性抽样 10% 题目的逐响应 token 投影标量序列 + 分层统计摘要（mean/P50/P90），存 `data/runs/<run_id>/activations/<item_id>_<seed>.npz`。复现包把该目录整体收入（C2-2）。

---

## 4. 环境与启动

### 4.1 环境事实（2026-07-11 实测，写死不再探测）

| 项 | 事实 | 对你的含义 |
|---|---|---|
| 硬件 | Mac mini M4 16GB，数据卷余 122Gi | 你的包全程无模型负载，无内存压力 |
| Python | venv 已由 kickoff 建好：`/Users/superagent/abcr/.venv`（uv, CPython 3.12） | **不要自建 venv**；worktree 里没有 .venv（gitignore），激活主仓那个 |
| 依赖 | requirements-mac.txt 已装（duckdb / pytest / pandas / pyarrow / typer / pydantic / matplotlib 等） | 你需要的 duckdb、pytest、matplotlib（主图）都在；不新增依赖，需要就走 PROGRESS 申请 |
| 网络 | huggingface.co 直连超时；白名单以 §2.1 铁律②为准（AMENDMENT-26 全量）| 你的包阶段1/2 不需要任何网络；notify 阶段3 走飞书（接线检查单 §7.3） |
| git | 2.53.0；repo 级身份已设（abcr/abcr@local）；无远端 | 正常 commit 到 pkg/c，不 push |
| 沙箱 | /usr/bin/sandbox-exec 可用（macOS 26.4.1 实测） | 冻结区 Seatbelt 是 A 的活；你只需知道 §10 K10 的架构洞见 |

### 4.2 .env 字段含义（kickoff 已注入主仓根；勿 commit、勿打印值、勿新增字段）

| 字段 | 含义 | 你是否使用 |
|---|---|---|
| DEEPSEEK_API_KEY / OPENAI_API_KEY / OPENAI_BASE_URL | judge 端点（B 用） | 否 |
| HF_ENDPOINT=https://hf-mirror.com | HF 下载镜像（B 用） | 否 |
| AUDITOR_FEISHU_APP_ID / AUDITOR_FEISHU_APP_SECRET | 飞书 auditor bot 凭证 | **阶段3 才用**（notify.py 读；阶段1/2 不碰） |
| ABCR_STATE_DIR | 运行状态根，缺省 `state/`（相对当前工作目录=worktree 根） | 是（approval.key 与 consumed.json 的根；代码里读 env，勿写死绝对路径） |

你自定义的两个环境开关（不进 .env 契约，代码内默认值兜底）：`ABCR_PHASE`（exploration | confirmation，缺省 exploration，方向锁盲用）；`ABCR_NOTIFY_ENABLED`（0/1，缺省 0，notify 接线开关）。

### 4.3 启动与环境自检命令序列（每个工作日开工先跑）

```bash
cd /Users/superagent/abcr-wt/c
git branch --show-current                     # 预期输出: pkg/c
source /Users/superagent/abcr/.venv/bin/activate
python -V                                     # 预期: Python 3.12.x
export PYTHONPATH=$PWD/src                    # src 布局，无安装步骤，靠 PYTHONPATH
python -c "import duckdb, pytest; print('deps ok')"        # 预期: deps ok
python -c "import abcr.common.ledger_ref, abcr.common.approval_token, abcr.common.constants; print('contract libs ok')"
python -m pytest tests/contract -q            # 预期: 全绿（红了先停：§10 坑 K2）
ls fixtures/ data/golden/golden10.json        # 预期: 都在
mkdir -p plans/specs plans/precheck plans/shadow reports/weekly   # 你的工作区（幂等）
```

约定：本文一切验收命令都假设已执行上述 `cd + activate + export PYTHONPATH`。pytest 用 `python -m pytest`（不是裸 `pytest`），保证走 venv 解释器。

### 4.4 kickoff 交付物核对（D1 第一件事，逐项确认后才开工任务卡）

必须存在：`src/abcr/common/ledger_ref.py`、`src/abcr/common/approval_token.py`、`src/abcr/common/constants.py`、`data/golden/golden10.json`、`fixtures/envelope_fixture.json`、`fixtures/envelope_fixture_badtoken.json`（AMENDMENT-12）、`fixtures/faketask_spec.md`、`fixtures/expected_scores.jsonl`、`fixtures/test_approval.key`、`tests/contract/`（非空）。

四件核对（结果写进 D1 的 PROGRESS）：
1. **approval_token.py 实物 vs 本文 C1-1 嵌码 diff**：语义必须一致（载荷字段、序列化口径、校验顺序、原因码）。若实物与嵌码有差异，**以实物+契约测试为准**，在 PROGRESS 契约疑议节记录差异点；不要为了"贴合本文"改动导致契约测试变红。
2. **fixture 预签令牌的 `scope` 字段值**：冻结为 `"batch_approve"`（已裁决——AMENDMENT-11；即 C1-1 的 `EXPECTED_SCOPE`，同批冻结 consumed 账本路径 = `state/approvals/consumed.json`）。若 fixture 实物是别的值（如 `"merge"`），**那是 fixture 缺陷——报 BLOCKER 由 fable 重签 fixture，不改常量**、不以 fixture 反向覆盖冻结值。
3. **账本 `subject_id` 键名约定**：翻 `tests/contract/` 与 fixture 中账本样例记录确认（§3.2 ⚠️，AMENDMENT-4）。
4. **ledger_ref 公开 API 形状 + run↔batch 通道**：翻 `src/abcr/common/ledger_ref.py` 实物确认写入类/方法签名（本文假名 `RunLedger`、`append(event, subject_id=..., **payload)`），**以实物为准**——C1-3 落账（AMENDMENT-10）与 C1-5 测试生成器都依赖它；同时核对 fixture 账本样例中 `run_registered` 事件 payload 含 `batch_id`（AMENDMENT-19），核实不到即记 PROGRESS 契约疑议。

---

## 5. 阶段1 任务卡

> 顺序即依赖序：C1-1 → C1-2 → C1-3 →（C1-4 与 C1-5 可并行）→ **C1-7 → C1-6**（views 查询面先行、sync 渲染在后——C1-6 的聚合全部取自 C1-7 的查询函数；卡编号与文内节序保持不变，施工按本行顺序）。其中 **C1-1~C1-3 = R1-core**（R1 门必验），**C1-4~C1-7 = R1-full**（阶段2 期间完成、R2 前齐——AMENDMENT-30）。每卡收尾三件套：单测绿 + `python -m pytest tests/contract -q` 绿 + commit（`[pkgC] ...`）。

### C1-1 approval_token.py 维护权接管 + 补测试（预计 2h）

**目标**：接管 `src/abcr/common/approval_token.py`；为其补齐防回归测试。kickoff 交付的 canonical 实现即下述全码（改写自 AILH V2 权威实现 `boss/approval/approval_token.py`，纯 stdlib）——先与仓库实物 diff（§4.4），再补测试；**接口签名不重构**（B 的 dispatch 已按 verify/consume 接口编码）。

**核心设计（懂了再动手）**：签发权死锁在人——`sign_token` 需要 `human_secret`（HMAC 私钥字节），系统域代码（planner/dispatch/triage）**永不 import sign_token**，只能 verify+consume。令牌四性：①签名 = HMAC-SHA256 over 规范化载荷；②作用域绑定 = `changeset_sha256` 字段承载 envelope_sha256，防"批 A 施 B"；③有效期 = `expires_at` ISO 格式，naive 时间按 UTC 补 tzinfo；④一次性 = `token_id` 消费后落 consumed.json，重放即拒。

**权威实现全码**（`src/abcr/common/approval_token.py`）：

```python
"""abcr.common.approval_token —— 批次审批令牌（HMAC-SHA256，纯 stdlib）。

架构位置：包C·Governor 侧维护的公共契约库。签发权在人（scripts/abcrctl），
系统侧（B 的 dispatch）只 verify + consume。改写自 AILH V2 canonical 实现，
字段映射：task_id 承载 batch_id、changeset_sha256 承载 envelope_sha256。

序列化口径（签名互认的要害，勿动）：
  载荷 = json.dumps(core, ensure_ascii=False, sort_keys=True)   # 默认 separators
  注意：envelope_sha256 的规范化是另一口径 separators=(",", ":")，见 governor/envelope.py。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

EXPECTED_SCOPE = "batch_approve"   # 冻结值（AMENDMENT-11）；fixture 不符 = fixture 缺陷，报 BLOCKER 重签，勿改本常量（§4.4 核对项2）

_PAYLOAD_FIELDS = ("token_id", "scope", "task_id", "changeset_sha256",
                   "expires_at", "persona_change")


def default_key_path() -> Path:
    """人侧签发密钥缺省位置：<ABCR_STATE_DIR>/approval.key（契约 §3.5）。"""
    return Path(os.environ.get("ABCR_STATE_DIR", "state")) / "approval.key"


def default_consumed_store() -> Path:
    """一次性消费账本缺省位置：<ABCR_STATE_DIR>/approvals/consumed.json。"""
    return Path(os.environ.get("ABCR_STATE_DIR", "state")) / "approvals" / "consumed.json"


def load_or_create_key(path: Optional[Path] = None) -> bytes:
    """读密钥；不存在则生成 32 字节随机并 chmod 0600（首用生成——人侧 CLI 专用入口）。"""
    p = path or default_key_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(secrets.token_bytes(32))
        os.chmod(p, 0o600)
    return p.read_bytes()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _payload_bytes(token: dict) -> bytes:
    """签名覆盖的规范化载荷（不含 sig 本身）。默认 separators——勿改。"""
    core = {k: token[k] for k in _PAYLOAD_FIELDS}
    return json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")


# --- 人侧：签发（系统域代码不得 import 本函数）---
def sign_token(batch_id: str, envelope_sha256: str, *, human_secret: bytes,
               ttl_seconds: int = 24 * 3600,
               now: Optional[datetime] = None) -> dict:
    n = now or _now()
    token = {
        "token_id": secrets.token_hex(8),
        "scope": EXPECTED_SCOPE,
        "task_id": batch_id,                     # 字段名承 V2 canonical；值 = batch_id
        "changeset_sha256": envelope_sha256,     # 值 = envelope_sha256
        "expires_at": (n + timedelta(seconds=ttl_seconds)).isoformat(),
        "persona_change": False,
    }
    token["sig"] = hmac.new(human_secret, _payload_bytes(token), hashlib.sha256).hexdigest()
    return token


# --- 系统侧：校验 + 消费 ---
def verify_token(token: dict, *, expected_envelope_sha256: str, verify_secret: bytes,
                 consumed_store: Optional[Path] = None,
                 now: Optional[datetime] = None) -> Tuple[bool, str]:
    """校验顺序（契约冻结）：结构→scope→恒时比较签名→envelope 哈希→过期→已消费。
    任一不过返回 (False, 原因码)，调用方 fail-closed 拒绝。不抛异常。"""
    store = consumed_store or default_consumed_store()
    n = now or _now()
    for k in ("token_id", "sig", "scope", "task_id", "changeset_sha256",
              "expires_at", "persona_change"):
        if k not in token:
            return False, f"missing_field:{k}"
    if token["scope"] != EXPECTED_SCOPE:
        return False, "bad_scope"
    expect_sig = hmac.new(verify_secret, _payload_bytes(token), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect_sig, str(token.get("sig", ""))):
        return False, "bad_signature"
    if token["changeset_sha256"] != expected_envelope_sha256:
        return False, "changeset_mismatch"
    try:
        exp = datetime.fromisoformat(token["expires_at"])
    except (ValueError, TypeError):
        return False, "bad_expires_at"
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)   # naive 按 UTC 补 tzinfo
    if n >= exp:
        return False, "expired"
    if token["token_id"] in _load_consumed(store):
        return False, "already_consumed"
    return True, "ok"


def consume_token(token: dict, consumed_store: Optional[Path] = None) -> None:
    """标记令牌已用（一次一用）。业务动作（批次 SETTLED）成功之后才调用——失败不烧令牌，可重试。"""
    store = consumed_store or default_consumed_store()
    used = _load_consumed(store)
    used.add(token["token_id"])
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(sorted(used), ensure_ascii=False), encoding="utf-8")


def _load_consumed(consumed_store: Path) -> set:
    """consumed.json 损坏按空集处理（V2 原注：宁可承担重放风险也不让校验通道整体瘫痪；
    风险与对策见工程包 §10 坑 K5）。"""
    if not consumed_store.exists():
        return set()
    try:
        return set(json.loads(consumed_store.read_text(encoding="utf-8")))
    except Exception:
        return set()
```

相对 V2 原版的三处适配（若与 kickoff 实物 diff 时看到的正是这些，属预期）：① `persona_change` 纳入必备字段检查（原版缺字段时 `_payload_bytes` 会 KeyError 崩溃而非返回原因码）；② 增加 `default_key_path / default_consumed_store / load_or_create_key` 三个路径助手（ABCR_STATE_DIR 单一事实源）；③ scope 从 `"merge"` 改 `"batch_approve"`、sign_token 形参名直接用 batch_id/envelope_sha256（字段名不变）。

**补测用例（`tests/governor/test_approval_token.py`，最少覆盖）**：
1. 正样：sign → verify == (True, "ok")；
2. 六失败路径逐一断言原因码：缺字段（删 `sig`）→ `missing_field:sig`；错 scope → `bad_scope`；篡改载荷任一字段（签名后改 `task_id`）→ `bad_signature`；envelope 哈希不符 → `changeset_mismatch`；过期（`ttl_seconds=-1` 或 `now` 拨后）→ `expired`；消费后重验 → `already_consumed`；
3. `expires_at` 非法字符串 → `bad_expires_at`；naive ISO 时间（无 tzinfo）不崩且按 UTC 判定；
4. consume 幂等（同 token 消费两次不炸，consumed.json 集合语义）；consumed.json 预置损坏内容（写入 `"not-json"`）→ verify 不崩；
5. `load_or_create_key`：首建后文件存在、`os.stat().st_mode & 0o777 == 0o600`、重复调用返回同一 key；
6. **fixture 真值锚**：用 `fixtures/test_approval.key` 验 `fixtures/envelope_fixture.json` 内预签令牌 == (True, "ok")（envelope_sha256 用 C1-2 的函数算——本用例 C1-2 完成后补上）。

**验收命令**：
```bash
python -m pytest tests/governor/test_approval_token.py -v   # 预期: 10+ passed
python -m pytest tests/contract -q                           # 预期: 仍全绿
```

### C1-2 envelope.py —— 信封校验、规范化与 envelope_sha256（预计 2h）

**目标**：`src/abcr/governor/envelope.py`。三职责：结构校验（§3.5 格式）、规范化 JSON、envelope_sha256。A 的 `ledger/schema.py` 另有审计侧信封校验（双视角，互不依赖）。

**实现全码**：

```python
"""abcr.governor.envelope —— 批次信封：格式校验、规范化、envelope_sha256（契约 §3.5/§3.7 实现）。

架构位置：包C·Governor 起草侧。abcrctl approve 用 envelope_sha256 绑定令牌；
B 的 dispatch 用同一函数核对（经本模块，勿自行序列化）。
关键不变量：approval 字段不进哈希 → 签发/换签不破坏令牌与信封的哈希绑定。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ENVELOPE_VERSION = "1.0"
BATCH_ID_RE = re.compile(r"^B-\d{8}T\d{6}Z-\d{4}$")

REQUIRED_TOP = ("envelope_version", "batch_id", "protocol_ref", "scope",
                "budget", "deadline_utc", "run_configs", "drafted_by")
REQUIRED_SCOPE = ("benchmark_families", "conditions", "splits",
                  "item_limit_per_run", "seeds", "trait_whitelist")
REQUIRED_BUDGET = ("gpu_hours_max", "cost_cap_cny")

# 契约 §3.4 condition 枚举（scope.conditions 的合法全集）
CONDITION_ENUM = frozenset({
    "vanilla", "persona_text", "neutral_token", "length_instruct", "inject",
    "ablate", "inject_random", "ablate_random", "synthetic_test", "fake"})
SPLIT_ENUM = frozenset({"dev", "calibration", "holdout"})


def canonical_json(obj: Any) -> str:
    """契约 §3.7 规范化口径（紧凑 separators——与令牌载荷的默认口径不同，勿混）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def envelope_sha256(env: dict) -> str:
    """对信封去 approval 字段后的规范化 JSON 取 sha256。"""
    core = {k: v for k, v in env.items() if k != "approval"}
    return hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()


def validate_envelope(env: dict) -> tuple[bool, list[str]]:
    """结构校验。返回 (ok, problems)。不抛异常；problems 逐条可读。"""
    problems: list[str] = []
    if not isinstance(env, dict):
        return False, ["信封不是 JSON 对象"]
    for k in REQUIRED_TOP:
        if k not in env:
            problems.append(f"缺顶层字段: {k}")
    if problems:
        return False, problems
    if env["envelope_version"] != ENVELOPE_VERSION:
        problems.append(f"envelope_version: '{env['envelope_version']}' != '{ENVELOPE_VERSION}'")
    if not BATCH_ID_RE.match(str(env["batch_id"])):
        problems.append("batch_id: 不符 B-<UTC:%Y%m%dT%H%M%SZ>-<4位序号>")
    scope = env["scope"]
    if not isinstance(scope, dict):
        problems.append("scope: 非对象")
    else:
        for k in REQUIRED_SCOPE:
            if k not in scope:
                problems.append(f"缺 scope.{k}")
        conds = scope.get("conditions", [])
        if not isinstance(conds, list) or not conds:
            problems.append("scope.conditions: 须为非空列表")
        else:
            for c in conds:
                if c not in CONDITION_ENUM:
                    problems.append(f"scope.conditions: '{c}' 不在枚举")
        splits = scope.get("splits", [])
        if not isinstance(splits, list) or not splits:
            problems.append("scope.splits: 须为非空列表")
        else:
            for s in splits:
                if s not in SPLIT_ENUM:
                    problems.append(f"scope.splits: '{s}' 不在枚举")
        lim = scope.get("item_limit_per_run")
        if not (isinstance(lim, int) and not isinstance(lim, bool) and lim > 0):
            problems.append("scope.item_limit_per_run: 须为正整数")
        seeds = scope.get("seeds", [])
        if (not isinstance(seeds, list) or not seeds
                or any(isinstance(x, bool) or not isinstance(x, int) for x in seeds)):
            problems.append("scope.seeds: 须为非空 int 列表")
        if not isinstance(scope.get("trait_whitelist"), list):
            problems.append("scope.trait_whitelist: 须为列表（可空）")
        if not isinstance(scope.get("benchmark_families"), list) or not scope.get("benchmark_families"):
            problems.append("scope.benchmark_families: 须为非空列表")
    budget = env["budget"]
    if not isinstance(budget, dict):
        problems.append("budget: 非对象")
    else:
        for k in REQUIRED_BUDGET:
            v = budget.get(k)
            if k not in budget:
                problems.append(f"缺 budget.{k}")
            elif isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                problems.append(f"budget.{k}: 须为非负数值")
    if not isinstance(env["run_configs"], list) or not env["run_configs"]:
        problems.append("run_configs: 须为非空列表")
    return (len(problems) == 0), problems


def load_envelope(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_envelope(path: Path, env: dict) -> None:
    """落盘形态自由（indent=2 供人读）；哈希只对 canonical_json 字符串算，与落盘形态无关。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(env, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
```

**测试要求（`tests/governor/test_envelope.py`）**：① fixture 信封 `validate_envelope` 通过、`envelope_sha256` 两次调用同值（幂等）；② **哈希不变量**：对 fixture 信封删除/替换 `approval` 字段后 sha 不变，改 `scope.item_limit_per_run` 后 sha 变；③ ≥8 个变异样本拒绝且 problems 指名道姓（缺 batch_id / batch_id 格式错 / conditions 空 / conditions 含枚举外值 / splits 含 "test" / item_limit_per_run 为 bool True / budget.cost_cap_cny 负数 / run_configs 空列表）；④ save→load 往返后 sha 不变（indent 落盘不影响 canonical 哈希）。

**验收命令**：
```bash
python -m pytest tests/governor/test_envelope.py -v   # 预期: 全绿
python - <<'EOF'
import sys; sys.path.insert(0, "src")
from abcr.governor.envelope import load_envelope, envelope_sha256, validate_envelope
env = load_envelope("fixtures/envelope_fixture.json")
ok, problems = validate_envelope(env)
print("validate:", ok, problems)
print("sha256:", envelope_sha256(env))
EOF
# 预期: validate: True []，随后打印 64 位十六进制且重复运行同值
```

### C1-3 abcrctl —— 人侧审批 CLI（预计 3h）

**目标**：`scripts/abcrctl`（可执行，`chmod +x`）。四命令：`draft / approve / reject / status`。这是**全项目唯一签发入口**；楠或 fable 在终端跑它。设计约束：stdlib argparse + ledger_ref（不引 typer，保持人侧工具最小依赖面）；一切输出中文可读；退出码 0=成功、2=校验失败、1=其他错误。**落账职责（AMENDMENT-10）**：draft/approve/reject 三命令在业务动作成功后，以"人"身份经 ledger_ref 向 batches.jsonl 各追加 `batch_drafted / batch_approved / batch_rejected` 事件（subject_id=batch_id, actor="human"）。

**实现全码**：

```python
#!/usr/bin/env python3
"""abcrctl —— ABCR 人侧审批 CLI（draft / approve / reject / status）。契约 §3.5。

架构位置：包C·人机边界。签发权在人：本 CLI 是唯一调用 sign_token 的地方。
落账（AMENDMENT-10）：draft/approve/reject 成功后以"人"身份经 ledger_ref 向
batches.jsonl 追加 batch_drafted/batch_approved/batch_rejected（subject_id=batch_id,
actor="human"）——这是 Governor 侧唯一的账本写入通道，进程本体其余部分恒只读。
用法（在 worktree 根）：
  scripts/abcrctl draft plans/specs/<name>.json          # 调 planner 出信封草案+预检
  scripts/abcrctl approve configs/envelopes/<id>.json [--ttl-hours 24] [--key PATH] [--out PATH]
  scripts/abcrctl reject configs/envelopes/<id>.json --reason "..."
  scripts/abcrctl status
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from abcr.common import approval_token as tok          # noqa: E402
from abcr.governor import envelope as envmod           # noqa: E402


def _ledger_append(event: str, batch_id: str, **payload) -> None:
    """AMENDMENT-10：三事件以"人"身份追加至 batches.jsonl（subject_id=batch_id,
    actor="human"）。写入类/方法签名以 ledger_ref 实物为准（§4.4 核对项4，
    文档假名 RunLedger）；并发互斥由 ledger_ref 的 flock 保证（AMENDMENT-15）。"""
    from abcr.common.ledger_ref import RunLedger
    led = RunLedger(ROOT_WT / "ledger" / "batches.jsonl")
    led.append(event, subject_id=batch_id, actor="human", **payload)


def cmd_draft(args: argparse.Namespace) -> int:
    from abcr.governor import planner
    result = planner.plan(Path(args.spec))
    print(result.render_text())
    if result.ok:
        _ledger_append("batch_drafted", result.batch_id)
    return 0 if result.ok else 2


def cmd_approve(args: argparse.Namespace) -> int:
    path = Path(args.envelope)
    env = envmod.load_envelope(path)
    ok, problems = envmod.validate_envelope(env)
    if not ok:
        print("拒绝签发：信封结构校验失败：", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    sha = envmod.envelope_sha256(env)
    key = tok.load_or_create_key(Path(args.key) if args.key else None)
    token = tok.sign_token(env["batch_id"], sha, human_secret=key,
                           ttl_seconds=int(float(args.ttl_hours) * 3600))
    env["approval"] = {
        "token": token,
        "approved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    out = Path(args.out) if args.out else path
    envmod.save_envelope(out, env)
    # 写回后自校验（防规范化实现漂移；approval 不进哈希 → sha 应不变）
    env2 = envmod.load_envelope(out)
    ok2, why = tok.verify_token(token, expected_envelope_sha256=envmod.envelope_sha256(env2),
                                verify_secret=key)
    if not ok2:
        print(f"签发自校验失败（{why}）——信封未生效，请报 BLOCKER", file=sys.stderr)
        return 1
    _ledger_append("batch_approved", env["batch_id"], token_id=token["token_id"])
    print(f"已签发并写回: {out}")
    print(f"  batch_id={env['batch_id']} token_id={token['token_id']} "
          f"expires_at={token['expires_at']}")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    path = Path(args.envelope)
    env = envmod.load_envelope(path)
    rej = {
        "batch_id": env.get("batch_id", "?"),
        "reason": args.reason,
        "rejected_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    out = path.with_suffix(".reject.json")
    out.write_text(json.dumps(rej, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _ledger_append("batch_rejected", env.get("batch_id", "?"), reason=args.reason)
    print(f"已驳回: {out}")
    return 0


def _consumed_ids() -> tuple[set, str]:
    """返回 (已消费 token_id 集合, health)。health ∈ {"ok","missing","corrupt"}；
    非 ok 时消费态不可信，status 必须显式标注（§10 K5——不许把缺失/损坏显示成"未消费"）。"""
    p = tok.default_consumed_store()
    if not p.exists():
        return set(), "missing"
    try:
        return set(json.loads(p.read_text(encoding="utf-8"))), "ok"
    except Exception:
        return set(), "corrupt"


def cmd_status(args: argparse.Namespace) -> int:
    envdir = ROOT_WT / "configs" / "envelopes"
    consumed, health = _consumed_ids()
    if health != "ok":
        print(f"⚠ consumed.json {'缺失' if health == 'missing' else '损坏'}——消费态不可信，"
              f"以下按未消费显示（K5）")
    rows: list[tuple[str, str, str]] = []
    for p in sorted(envdir.glob("*.json")):
        if p.name.endswith(".reject.json"):
            continue
        try:
            env = envmod.load_envelope(p)
        except Exception as e:
            rows.append((p.name, "损坏", str(e)))
            continue
        if p.with_suffix(".reject.json").exists():
            state = "REJECTED(人)"
        elif "approval" in env:
            tid = env["approval"].get("token", {}).get("token_id", "?")
            state = "APPROVED→已消费" if tid in consumed else "APPROVED(待/在派发)"
        else:
            state = "DRAFT(待批)"
        rows.append((env.get("batch_id", p.name), state, str(p)))
    if not rows:
        print("configs/envelopes/ 下无信封")
        return 0
    w = max(len(r[0]) for r in rows)
    for bid, state, note in rows:
        print(f"{bid:<{w}}  {state:<18}  {note}")
    print("\n（批次 DISPATCHING 之后的账本态请用: PYTHONPATH=src python -m abcr.report.cli overview）")
    return 0


ROOT_WT = Path.cwd()   # 约定：在 worktree 根运行


def main() -> int:
    ap = argparse.ArgumentParser(prog="abcrctl", description="ABCR 人侧审批 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("draft", help="从 plan-spec 起草信封（调 planner）")
    p.add_argument("spec"); p.set_defaults(fn=cmd_draft)
    p = sub.add_parser("approve", help="校验信封并签发令牌写回")
    p.add_argument("envelope"); p.add_argument("--ttl-hours", default="24")
    p.add_argument("--key", default=None); p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_approve)
    p = sub.add_parser("reject", help="人工驳回信封")
    p.add_argument("envelope"); p.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_reject)
    p = sub.add_parser("status", help="信封与令牌状态一览")
    p.set_defaults(fn=cmd_status)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
```

**测试要求（`tests/governor/test_abcrctl.py`，subprocess 方式跑 CLI，cwd=tmp 伪 worktree）**：① 对 fixture 信封副本（copy 到 tmp）approve：退出码 0、写回后含 `approval.token` 七字段、`state/approval.key`（重定向 ABCR_STATE_DIR 到 tmp）自动生成且 0600；② 两个明确断言：a) approve 只作用于 tmp 副本后，`fixtures/envelope_fixture.json` **原件字节不变**（测试里永远操作副本）；b) 原件内预签令牌用 `fixtures/test_approval.key` 重验仍 == (True, "ok")；③ 对结构破坏的信封 approve → 退出码 2 且无 approval 写入、无账本事件；④ reject 生成 `.reject.json`；⑤ status 对 DRAFT/APPROVED/REJECTED 三态显示正确；⑥ **落账断言（AMENDMENT-10）**：approve/reject（及 draft，若 planner 已就位）后 tmp 账本 `ledger/batches.jsonl` 末行 event/subject_id 正确且 payload `actor=="human"`；⑦ consumed.json 预置损坏内容 → status 输出「⚠ consumed.json 损坏」标注行且不崩（K5）。

**验收命令**：
```bash
chmod +x scripts/abcrctl
python -m pytest tests/governor/test_abcrctl.py -v      # 预期: 全绿
# 手工冒烟（操作副本，勿动 fixture 原件）：
cp fixtures/envelope_fixture.json configs/envelopes/_smoke.json
ABCR_STATE_DIR=state scripts/abcrctl approve configs/envelopes/_smoke.json
scripts/abcrctl status        # 预期: _smoke 显示 APPROVED(待/在派发)
scripts/abcrctl reject configs/envelopes/_smoke.json --reason "冒烟测试"
scripts/abcrctl status        # 预期: 显示 REJECTED(人)
rm configs/envelopes/_smoke.json configs/envelopes/_smoke.reject.json
# 注: 冒烟落进 ledger/batches.jsonl 的 batch_approved/batch_rejected 事件保留即可——
# 运行时目录 gitignored，append-only 不删行。
```

⚠️ R1 演练时 fable 会按上位脚本逐字跑 `abcrctl approve fixtures/envelope_fixture.json --key fixtures/test_approval.key`（**必带 --key 旗标**：不带则默认用 state/approval.key——首用会新生成密钥并就地重签，B 的 dispatch 用 test key 验签必得 bad_signature，R1 现场直接失败）。对 fixture 原件就地写回没问题：approve 换掉 approval 字段不影响 envelope_sha256（哈希不含 approval）；演练后 `git checkout -- fixtures/envelope_fixture.json` 还原。把这两句写进你的 PROGRESS 备忘，R1 现场提醒 fable。

### C1-4 planner.py —— 固定规则计划器 v0（预计 3h；零 LLM）

**目标**：`src/abcr/governor/planner.py`。输入 plan-spec JSON → 输出三件：信封草案（`configs/envelopes/<batch_id>.json`，无 approval 字段）+ 预算预估 + 符合性预检清单（`plans/precheck/<batch_id>.precheck.{json,md}`）。**任一预检 FAIL → 不落信封草案文件**（预检报告照落）。规则与格式由本卡冻结（planner 内部规则，不是三包契约；调整走 PROGRESS 报备即可）。

**plan-spec 格式 v1（`plans/specs/<name>.json`；人或你手写）**：

```json
{
  "planspec_version": "1.0",
  "goal": "自由文本，人读，不进任何机器判断",
  "protocol_ref": "W1-V0.9",
  "benchmark_families": ["golden10"],
  "conditions": ["fake"],
  "splits": ["dev"],
  "item_limit_per_run": 10,
  "seeds": [1, 2, 3],
  "trait_whitelist": [],
  "run_configs": ["configs/experiments/fake_a.json", "configs/experiments/fake_b.json"],
  "budget": {"gpu_hours_max": 0.5, "cost_cap_cny": 10.0},
  "deadline_hours": 24,
  "engine_class": "fake"
}
```

**预检规则 v0（全部确定性；逐条产出 PASS/FAIL + 证据句）**：

| # | 规则 | 判据 |
|---|---|---|
| P1 | split 只 dev | `set(splits) == {"dev"}` |
| P2 | 条件白名单 | `set(conditions) ⊆ CONDITION_ENUM`（envelope.py 枚举）且非空 |
| P3 | 批预算合规 | `cost_cap_cny ≤ 60.0` 且 `gpu_hours_max ≤ 6.0`（单批上限，planner 常量） |
| P4 | W1 总预算内 | `cost_cap_cny ≤ 150.0 − 已实耗`；已实耗 = `ledger/costs.jsonl` 中 `run_cost_actual` 事件 payload `amount_cny` 求和（键名冻结——AMENDMENT-9；含云链段，用 ledgerio.read_chain_merged；账本缺失 → 按 0 并在报告注明"账本无实耗记录"） |
| P5 | trait 白名单 | `set(trait_whitelist) ⊆ {"conscientiousness","openness","neuroticism","optimistic","sycophantic"}`（3 锚 + 官方复现两候选；planner 常量，traits 定稿后如有出入走 PROGRESS 改） |
| P6 | 规模上限 | `item_limit_per_run ≤ 250` 且 `1 ≤ len(seeds) ≤ 5` |
| P7 | run_configs 实在 | 非空且每个路径文件存在（相对 worktree 根） |
| P8 | 预估不超信封 | 预算预估（下式）`est_gpu_hours ≤ gpu_hours_max` 且 `est_cost_cny ≤ cost_cap_cny` |

**预算预估 v0 公式**（常数为 planner 内部估计值，**未实测**，偏差在阶段2 用 costs.jsonl 实耗回校）：
`est_total_items = len(run_configs) × item_limit_per_run`；`est_gpu_hours = est_total_items × SEC_PER_ITEM[engine_class] / 3600`（`fake=0.2`、`mac_3b=3.0`、`cloud_7b=6.0` 秒/item）；`est_cost_cny = est_gpu_hours × 2.5`（AutoDL 24GB 卡时价近似；fake/mac 按 0 元）。

**实现骨架**（签名冻结供 abcrctl 调用；函数体按上表实现）：

```python
"""abcr.governor.planner —— 固定规则计划器 v0（零 LLM，契约外规则由工程包C 冻结）。

架构位置：包C·Governor。plan-spec → 信封草案 + 预算预估 + 符合性预检。
本模块永不签发令牌、永不写账本；产物只落 configs/envelopes/ 与 plans/precheck/。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

MAX_BATCH_COST_CNY = 60.0
MAX_BATCH_GPU_HOURS = 6.0
W1_TOTAL_BUDGET_CNY = 150.0
SEC_PER_ITEM = {"fake": 0.2, "mac_3b": 3.0, "cloud_7b": 6.0}   # 未实测估计值
CNY_PER_GPU_HOUR = 2.5                                          # 未实测估计值
TRAIT_WHITELIST = frozenset({"conscientiousness", "openness", "neuroticism",
                             "optimistic", "sycophantic"})


@dataclass
class PlanResult:
    ok: bool
    batch_id: str
    checks: list[dict] = field(default_factory=list)   # [{"rule","passed","evidence"}]
    estimate: dict = field(default_factory=dict)        # {"est_total_items","est_gpu_hours","est_cost_cny"}
    envelope_path: str | None = None                    # FAIL 时 None
    precheck_path: str = ""

    def render_text(self) -> str: ...                   # 人读摘要（abcrctl draft 打印）


def next_batch_id(envdir: Path) -> str:
    """B-<UTC:%Y%m%dT%H%M%SZ>-<4位序号>；序号 = 当日已有信封数+1（单人操作，不设并发防护）。"""
    ...

def spent_cny(costs_path: Path) -> tuple[float, str]:
    """汇总 run_cost_actual 的 payload amount_cny（AMENDMENT-9 键名；主链+云链段
    合并读，见 ledgerio.read_chain_merged）；缺文件→(0.0, 注记)。"""
    ...

def plan(spec_path: Path, envdir: Path = Path("configs/envelopes"),
         precheck_dir: Path = Path("plans/precheck"),
         costs_path: Path = Path("ledger/costs.jsonl")) -> PlanResult:
    """主入口：读 spec → 八项预检 → 预估 → （全 PASS 才）落信封草案；预检报告恒落。"""
    ...
```

信封草案由 spec 直映射：`drafted_by="governor-rules-v1"`、`deadline_utc = now + deadline_hours`、其余字段同名搬运（`engine_class`/`goal`/`deadline_hours`/`planspec_version` 不进信封）。precheck MD 含：逐规则 PASS/FAIL 表、预估三数、已实耗与余额、spec 原文路径。

**测试要求（`tests/governor/test_planner.py`）**：① 合法 fake spec（tmp 下造两个空 config 文件）→ ok=True、信封落地且 `validate_envelope` 通过、预检 8/8 PASS；② 逐项越界 spec 各一：splits=["holdout"]→P1 FAIL、conditions=["magic"]→P2、cost_cap_cny=999→P3、trait_whitelist=["evil"]→P5、run_configs 指向不存在文件→P7、item_limit 太大致预估超 gpu_hours_max→P8——各用例断言 ok=False、信封文件**不存在**、precheck 报告存在且 FAIL 行指名规则；③ P4：tmp 造 costs.jsonl（按 §3.2 记录形状写两条 `run_cost_actual`，payload `amount_cny` 各 70.0——AMENDMENT-9 键名）→ cost_cap_cny=20 的 spec FAIL P4；④ batch_id 格式匹配 `BATCH_ID_RE`。

**验收命令**：
```bash
python -m pytest tests/governor/test_planner.py -v     # 预期: 全绿
mkdir -p plans/specs && cat > plans/specs/smoke_fake.json <<'EOF'
{"planspec_version":"1.0","goal":"planner 冒烟","protocol_ref":"W1-V0.9",
 "benchmark_families":["golden10"],"conditions":["fake"],"splits":["dev"],
 "item_limit_per_run":10,"seeds":[1,2,3],"trait_whitelist":[],
 "run_configs":["fixtures/envelope_fixture.json"],
 "budget":{"gpu_hours_max":0.5,"cost_cap_cny":10.0},"deadline_hours":24,"engine_class":"fake"}
EOF
scripts/abcrctl draft plans/specs/smoke_fake.json
# 预期: 打印 8/8 PASS + 预估三数 + 新信封路径 configs/envelopes/B-*.json；退出码 0
scripts/abcrctl status && rm configs/envelopes/B-*.json   # 冒烟后清场
```

### C1-5 triage.py —— 异常分诊 v0（预计 2.5h；例外驱动）

**目标**：`src/abcr/governor/triage.py` + 只读装载层 `src/abcr/report/ledgerio.py`。读账本 → 规则分桶 → 异常摘要 MD `reports/triage-<YYYY-MM-DD>.md`。**例外驱动**：正常合计一行；篇幅全部给偏差、失败、待决。零 LLM。

**只读装载层全码**（`src/abcr/report/ledgerio.py`——triage/sync/views 共用；C 侧自建，R1 后可自愿改用 A 的 `abcr.ledger.views`，两者都只许只读）：

```python
"""abcr.report.ledgerio —— 账本只读装载与状态折叠（包C 自建只读查询层）。

架构位置：包C·呈现侧的数据入口。只 open 读文件，永不写 ledger/。
状态映射与契约 §3.3 全表一致（本地只读副本，另含 AMENDMENT-13 两拒绝事件的
呈现标记映射；R1 合并后可自愿切 A 的 statemachine，标记映射保留本侧）。
装载一律走 read_chain_merged（主链 + ledger/cloud-day*/ 云链段——AMENDMENT-2）。
"""
from __future__ import annotations

import json
from pathlib import Path

RUN_EVENT_STATE: dict[str, str] = {
    "run_registered": "PLANNED", "run_queued": "QUEUED", "run_started": "RUNNING",
    "run_paused": "PAUSED", "run_resumed": "RUNNING", "run_failed": "FAILED",
    "run_completed": "COMPLETED", "run_scored": "SCORED", "run_audited": "AUDITED",
    "run_accepted": "ACCEPTED", "run_quarantined": "QUARANTINED",
    "run_cancelled": "CANCELLED",
}
BATCH_EVENT_STATE: dict[str, str] = {
    "batch_drafted": "DRAFT", "batch_approved": "APPROVED",
    "batch_dispatch_started": "DISPATCHING", "batch_settled": "SETTLED",
    "batch_audited": "AUDITED", "batch_reported": "REPORTED",
    # AMENDMENT-13 两拒绝事件：批次冻结状态机主线无拒绝态，以下为呈现折叠专用标记态
    # （你只读折叠、不做迁移校验；迁移守卫语义以 A 的 statemachine 为准）。
    "batch_rejected": "REJECTED", "batch_dispatch_rejected": "DISPATCH_REJECTED",
}


def read_chain(path: Path) -> list[dict]:
    """读一条账本链的全部记录（文件序即链序）。缺文件返回 []。"""
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def read_chain_merged(ledger_dir: Path, chain: str) -> list[dict]:
    """主链 + 云链段合并只读视图（AMENDMENT-2）：先 ledger/<chain>.jsonl，再按目录名序
    依次装载 ledger/cloud-day*/<chain>.jsonl。各段自成一链——只合并记录、不拼哈希、
    不跨段校验。triage/sync/views/planner 的一切账本装载一律走本函数。"""
    events = read_chain(Path(ledger_dir) / f"{chain}.jsonl")
    for seg in sorted(Path(ledger_dir).glob("cloud-day*")):
        if seg.is_dir():
            events += read_chain(seg / f"{chain}.jsonl")
    return events


def fold_subjects(events: list[dict], state_map: dict[str, str]) -> dict[str, dict]:
    """按 payload.subject_id 折叠出每主体现状。
    返回 {subject_id: {"state","last_ts","last_progress_ts","events"}}。"""
    out: dict[str, dict] = {}
    for ev in events:
        sid = ev.get("subject_id")
        if sid is None:
            continue
        rec = out.setdefault(sid, {"state": None, "last_ts": None,
                                   "last_progress_ts": None, "events": []})
        rec["events"].append(ev)
        rec["last_ts"] = ev.get("ts")
        name = ev.get("event", "")
        if name == "step_progress":
            rec["last_progress_ts"] = ev.get("ts")
            continue
        st = state_map.get(name)
        if st is not None:
            rec["state"] = st
    return out
```

**分桶规则 v0**（`triage.py` 按此实现；`now` 可注入便于测试）：

| 桶 | 规则 | 篇幅 |
|---|---|---|
| A级（紧急） | `costs.jsonl` 有 `budget_alert`；任一 run 现态 QUARANTINED；`state/alerts/*.json` 存在（告警文件接口，已裁决——AMENDMENT-18：B 写、A/C 只读，文件名 `<ts>-<kind>.json`，JSON 至少 {ts, kind, severity(A/B/C), subject_id, reason}——你只读解析、按 severity 归桶）；`batches.jsonl` 有 `batch_dispatch_rejected`（B 的 dispatch 拒绝落账——AMENDMENT-13）；实耗 ≥ 85%×150 元 | 逐条全文 |
| 失败未收敛 | run 现态 FAILED（无后续 resumed→completed） | 逐条：run_id、失败事件 payload、事件链摘要 |
| 停摆 | run 现态 RUNNING 且 `now − max(last_progress_ts, last_ts) > 1800s` | 逐条 |
| TTL 超时 | QUEUED>3600s；COMPLETED 未 SCORED>7200s；SCORED 未 AUDITED>7200s（用该态最后事件 ts 起算） | 逐条 |
| 待决 | 待批信封（configs/envelopes/ 有 DRAFT）；批次现态 SETTLED 未 AUDITED、AUDITED 未 REPORTED | 逐条 |
| 已收敛偏差 | 事件链中出现过 run_failed 但现态 ∈ {COMPLETED,SCORED,AUDITED,ACCEPTED}（断点续跑成功） | 每条一行 |
| 正常 | 其余 | 合计一行："正常 run N 个（COMPLETED x / SCORED y / ...）" |

**告警三级映射（已裁决——AMENDMENT-31，误报预算用）**：每个异常条目除工作流桶外再标 `severity`——**A** = 预算（budget_alert / 实耗≥85%）、污染（QUARANTINED）、冻结区违规、停摆、云实例空转（instance_idle_alert）；**B** = 失败未收敛、审计不一致、TTL 超时；**C** = 其余（待决、已收敛偏差等）。MD 尾部输出计数行 **「今日 A+B 告警数 N/3」**（A+B 合计每日 ≤3 为健康线；连续超线即视为告警系统故障，次日 sync morning 段强制置顶「告警系统降敏待决」条目——见 C1-6）。severity 亦是 `state/alerts` 文件（AMENDMENT-18）与 notify 接线（§7.3）的共用分级。

CLI：`PYTHONPATH=src python -m abcr.governor.triage [--ledger-dir ledger] [--out reports/] [--now ISO]`。MD 每条目带 subject_id（run_id/batch_id）与证据 ts。账本装载走 `ledgerio.read_chain_merged`（含云链段——AMENDMENT-2）。

**测试要求（`tests/governor/test_triage.py`）**：conftest 提供 `make_fixture_ledger(tmp_path)` 生成器——**用 `abcr.common.ledger_ref.RunLedger` 往 tmp 账本目录写**（写 tmp 不违"只读真账本"边界；类名/append 签名以实物为准——§4.4 核对项4），按 fixture 剧本造 6 run：4 个 registered→queued→started→step_progress→completed→scored；1 个 …→failed→resumed→completed→scored（已收敛）；1 个 …→started 后无事件（停摆，测试注入 now=+1h）；`run_registered` payload 一律含 `batch_id`（AMENDMENT-19）。断言：停摆桶恰 1 条、已收敛偏差恰 1 条、失败未收敛 0 条、正常行计数正确、MD 中正常桶只占一行、尾部含「今日 A+B 告警数」计数行。

**验收命令**：
```bash
python -m pytest tests/governor/test_triage.py -v      # 预期: 全绿
PYTHONPATH=src python -m abcr.governor.triage --ledger-dir ledger --out reports/
cat reports/triage-*.md   # 空账本预期: 各桶为空 + "正常 run 0 个" 一行（不炸）
```

### C1-6 sync.py —— 四段同步视图（预计 3h）

**目标**：`src/abcr/report/sync.py`。渲染 `reports/sync-<YYYY-MM-DD>-<段>.md`，段 ∈ `morning / afternoon / evening / urgent`。**数据只来自账本/scores 查询（ledgerio + views），禁止自由回忆；逐数带 run_id。**

| 段 | 名 | 内容（全部由查询函数产出） |
|---|---|---|
| morning | 上午·计划与待批 | 待批信封表（batch_id、scope 摘要、预算、precheck 结论）；待决桶（triage 复用）；今日预算余量（150 − costs 实耗）；若前日 A+B 告警超线（>3/日）——**强制置顶「告警系统降敏待决」条目**（AMENDMENT-31） |
| afternoon | 下午·进展与偏差 | 各批次现态；RUNNING run 的最新 items_done/steps_done（step_progress payload）；偏差 = triage 的失败/停摆/TTL 三桶原样嵌入 |
| evening | 晚间·结果、失败与明日建议 | 今日到 SCORED/AUDITED 的 run 逐条（run_id + 各 metric 均值，注明 scorer_id）；失败清单；**「今日 A+B 告警数 N/3」计数行**（triage severity 三级映射——AMENDMENT-31）；明日建议（**规则模板**：FAILED 未收敛→"建议续跑 <run_id>"；SETTLED 未审→"待 A 审计 <batch_id>"；DRAFT 信封→"待批 <batch_id>"——零 LLM 拼接） |
| urgent | 紧急·仅A级 | 仅 triage A级桶；空则整段一行"无 A 级异常" |

实现要点：① 每个数字的渲染统一走 `def cite(value: object, run_id: str) -> str: return f"{value}（run {run_id}）"` 之类的带源函数——约束口径：**测试对渲染产物断言**（凡匹配统计数字模式的行必须同行含 run_id/subject_id）；"统计值只经 cite()/render_effect 出口"为 code review 自查项，**不对源码做字面数字断言**（格式化符 `:.4f`、预算常量 150、TTL 等必然以字面量存在，源码级断言不可操作）；② evening 的效应类对比（条件间均值差）必须经 `blind.render_effect`（C1-6 先接探索期直通，C2-5 补确认期剥方向）——**臂级聚合数字以贡献 run_id 列表随行注明**（render_effect 的 `source_run_ids` 参数，见 C2-5 嵌码）；③ 所有聚合从 `views.py`（C1-7）的查询函数取——**按 §5 卡序 C1-7 先行完成**（views 查询面在前、sync 渲染在后）；④ 每份 MD 头部自动注入呈现纪律行：`> 数字均为 exploratory / rig-validation；mini 环产出不构成任何假设的证据。`

CLI：`PYTHONPATH=src python -m abcr.report.sync --segment morning [--date YYYY-MM-DD] [--ledger-dir ledger] [--runs-dir data/runs] [--out reports/]`。

**测试要求（`tests/report/test_sync.py`）**：复用 make_fixture_ledger + tmp 下造 2 个 run 的 `data/runs/<run_id>/scores.jsonl`（按 §3.4 scores 字段手写数行）。断言：四段各渲染成功且文件名正确；**渲染产物中凡匹配统计数字模式的行同行含其 run_id/subject_id**（效应对比行以 render_effect 的 source_run_ids 注明贡献 run 列表）；evening 含「今日 A+B 告警数 N/3」计数行；urgent 对无 A 级账本输出单行；头部纪律行存在。

**验收命令**：
```bash
python -m pytest tests/report/test_sync.py -v          # 预期: 全绿
for seg in morning afternoon evening urgent; do
  PYTHONPATH=src python -m abcr.report.sync --segment $seg --out reports/
done && ls reports/sync-*.md                            # 预期: 四文件
```

### C1-7 report 三层钻取 CLI（预计 3h）

**目标**：`src/abcr/report/views.py`（DuckDB read_json 只读查询）+ `src/abcr/report/cli.py`。三层：宏观汇总 → 臂/批次 → 单 run 单题原始输出，**全程 ≤1 分钟**。阶段1 自建查询（契约 schema 冻结保证兼容），R1 后可自愿切换 A 的 `abcr.ledger.views`（两者都只许只读）。

**views.py 查询面（签名冻结供 sync/cli 用；DuckDB 用内存库连 read_json，不建持久 .duckdb 文件）**：

```python
"""abcr.report.views —— DuckDB 只读查询面（包C 自建；对 ledger/ 与 data/runs/ 只 SELECT）。"""
from __future__ import annotations

from pathlib import Path
import duckdb


def _read_json(con: duckdb.DuckDBPyConnection, path: str) -> str:
    # DuckDB ≥0.9 语法；若装的版本报参数不识别，改用 read_ndjson_auto('<path>')（§10 K7）
    return f"read_json_auto('{path}', format='newline_delimited', union_by_name=true)"


def overview(ledger_dir: Path, runs_dir: Path) -> dict:
    """L1：批次现态计数、run 现态计数、per-condition 确定性指标均值（分 scorer_id）。"""
    ...

def batch_detail(batch_id: str, ledger_dir: Path, runs_dir: Path) -> dict:
    """L2：该批 run 清单（run_id/condition/seed/现态）+ 臂级聚合（condition×metric 均值与 n）。"""
    ...

def run_item(run_id: str, item_id: str, runs_dir: Path) -> dict:
    """L3：单 run 单题——steps.jsonl 中该 item 全部记录（output_text 原文）+ scores 各行。"""
    ...
```

臂级聚合 SQL 样例（嵌入 views.py）：

```sql
SELECT condition, metric_name, scorer_id,
       avg(CAST(metric_value AS DOUBLE)) AS mean_value, count(*) AS n
FROM read_json_auto('data/runs/*/scores.jsonl', format='newline_delimited', union_by_name=true)
WHERE run_id IN (/* 批内 run_id 列表：对 runs_index 的 run_registered 事件按 payload.batch_id
                    过滤折叠得出（AMENDMENT-19）；未启动 run（PLANNED/QUEUED 无 manifest）的
                    钻取降级用信封 run_configs 对账 */)
GROUP BY condition, metric_name, scorer_id
ORDER BY condition, metric_name, scorer_id;
```

状态折叠不走 SQL（账本事件序依赖文件序），用 `ledgerio.fold_subjects`（装载经 `read_chain_merged`，含云链段——AMENDMENT-2）；DuckDB 只做 scores/steps 聚合。**空数据护栏**：`read_json_auto` 对无匹配文件的 glob 直接抛 IO Error（"No files found"）——每个查询函数下 SQL 前先用 Python `glob` 判空，**空则不下 SQL、直接返回零值结构**（空账本验收命令即测此路径；症状收录 §10 K7）。CLI：

```
PYTHONPATH=src python -m abcr.report.cli overview
PYTHONPATH=src python -m abcr.report.cli batch <batch_id>
PYTHONPATH=src python -m abcr.report.cli run <run_id> --item <item_id>   # 打印 output_text 原文
```

L3 打印原文时：全文输出不截断（这是"钻到原始输出"的意义）；只对控制字符做 repr 转义。

**测试要求（`tests/report/test_views.py`）**：tmp 造 2 run × 3 item 的 steps.jsonl/scores.jsonl（含 g03 已知错样）→ overview 计数正确；batch_detail 臂级均值手算相符；run_item 返回的 output_text 与写入原文逐字节相等。

**验收命令**：
```bash
python -m pytest tests/report/test_views.py -v          # 预期: 全绿
time (PYTHONPATH=src python -m abcr.report.cli overview) # 预期: real < 5s（空数据）
# R1 现场（有 fixture 批数据后）三连，总耗时 ≤1 分钟：
time (PYTHONPATH=src python -m abcr.report.cli overview \
  && PYTHONPATH=src python -m abcr.report.cli batch <batch_id> \
  && PYTHONPATH=src python -m abcr.report.cli run <run_id> --item g03)
```

---

## 6. 阶段2 任务卡

> 进入条件：R1 已过（fable 宣布），你的树已含 R1 合并产物（fable 会把 main 合回或指示 rebase——以 R1 门现场指示为准）。此后 A 的 views/statemachine、B 的 scorer 在你树里可见，"自愿切换"决策窗口打开。

### C2-1 shadow 模式 —— 草案 vs 人工决策差异记录（预计 2.5h）

**目标**：`src/abcr/governor/shadow.py`。阶段2 起对**真实批次**（首个 = 云日 7B mini 环）：你的 planner 出计划草案 → 人（楠/fable）自行决定最终信封并 approve → 你记录"草案 vs 人工最终决策"的结构化差异。**人批人派不变**；差异记录是阶段3 毕业的证据流。

**关键差异定义（冻结措辞，毕业判据用）**：预算维度（`budget.gpu_hours_max`、`budget.cost_cap_cny`）/ 条件集合（`set(scope.conditions)`）/ split 选择（`set(scope.splits)`）/ 题量（`scope.item_limit_per_run`）**任一不同即关键差异；措辞差异不算**。seeds、trait_whitelist、deadline、run_configs 路径、goal 文本 = 非关键（照记，不入判定）。

**差异记录格式 v1**（`plans/shadow/<batch_id>.shadow.json`；配套草案快照 `<batch_id>.draft.json`）：

```json
{
  "shadow_version": "1.0",
  "batch_id": "B-20260716T020000Z-0001",
  "draft_path": "plans/shadow/B-20260716T020000Z-0001.draft.json",
  "draft_envelope_sha256": "<64hex>",
  "final_envelope_path": "configs/envelopes/B-20260716T020000Z-0001.json",
  "final_envelope_sha256": "<64hex>",
  "compared_at": "<UTC ISO>",
  "dimensions": {
    "budget.gpu_hours_max":  {"draft": 4.0, "final": 4.0, "key": true,  "diff": false},
    "budget.cost_cap_cny":   {"draft": 60.0, "final": 50.0, "key": true, "diff": true},
    "conditions":            {"draft": ["vanilla","persona_text","inject"], "final": ["vanilla","persona_text","inject"], "key": true, "diff": false},
    "splits":                {"draft": ["dev"], "final": ["dev"], "key": true, "diff": false},
    "item_limit_per_run":    {"draft": 50, "final": 50, "key": true, "diff": false},
    "seeds":                 {"draft": [1,2], "final": [1,2,3], "key": false, "diff": true},
    "trait_whitelist":       {"draft": ["conscientiousness"], "final": ["conscientiousness"], "key": false, "diff": false}
  },
  "key_difference": true,
  "notes": "人工把 cost_cap 从 60 收紧到 50（预算保守化）"
}
```

实现：`compare(draft: dict, final: dict) -> dict`（纯函数，集合比较对列表先 set 化）；CLI `PYTHONPATH=src python -m abcr.governor.shadow --draft plans/shadow/<id>.draft.json --final configs/envelopes/<id>.json [--notes "..."]`。工作流约定（写进模块 docstring）：abcrctl draft 产草案后**立即** `cp` 一份快照到 `plans/shadow/<batch_id>.draft.json`（人随后可能就地改信封）；人 approve 后跑 shadow 比对。notes 由人口述、你转录——只记事实不记评价。

**测试**（`tests/governor/test_shadow.py`）：四个关键维逐一制造差异 → `key_difference=true`；仅 seeds/goal 差异 → false；列表乱序不算差异（set 语义）。
**验收命令**：`python -m pytest tests/governor/test_shadow.py -v`（全绿）。

### C2-2 repro_pack.py —— 复现包出包（预计 3.5h；R2 ④ 的主角）

**目标**：`src/abcr/report/repro_pack.py`。对一个已 SETTLED（最好已 AUDITED）批次出**自包含**复现包 `demos/repro-<batch_id>/`：

```
demos/repro-<batch_id>/
├── README.md                    ← 复跑与复评命令 + 诚实条款（模板见下）
├── ACCEPTANCE.md                ← 闭合验收协议（C2-3 模板实例化）
├── pack_manifest.json           ← 包级清单：逐文件 sha256+bytes、run_ids、承诺三级、标注
├── configs/                     ← 信封原件 + 全部 run config 原件
├── runs/<run_id>/manifest.json  ← 原件复制（含 config 全文、全部哈希、non_citable 标记）
├── runs/<run_id>/steps.jsonl    ← steps 级原始输出 JSONL（原件，含 output_text 全文）
├── runs/<run_id>/scores.jsonl   ← 全部 scorer 的分数行
├── activations/<run_id>/        ← 激活摘要 npz（10% 抽样原件）
├── env/requirements.lock.txt    ← 出包时 `pip freeze` 全量
├── env/versions.json            ← {python, torch, duckdb, platform, 出包 git_commit}
├── figures/main.png             ← 主图 = 双联图（已裁决——AMENDMENT-31）：左 = 三臂逐 seed is_correct 均值点图（每 seed 一点）；右 = 每臂 output_len_tokens 分布（箱线/小提琴，W2 长度三段分解预热）；图注含 "rig-validation, not evidence"；matplotlib，数据出自 views
└── tools/
    ├── rescore_copy.py          ← 出包时从 A 的 src/abcr/audit/rescore.py 判分函数逐字节复制（独立复算**主副本**——AMENDMENT-20）
    ├── scorer_copy.py           ← 出包时从 B 的 src/abcr/rig/scorer.py 逐字节复制（第二副本，双实现对照随包走）
    └── rescore_standalone.py    ← 独立复评入口：stdlib + 同目录两副本，不 import abcr 包
```

`pack_manifest.json` 必含：`pack_version, batch_id, created_at, git_commit, run_ids, files:[{path,sha256,bytes}], labels:["exploratory","rig-validation"], commitments:{artifact_level:true, statistical_level:true, single_machine_deterministic:true, cross_hardware_bit_level:false}`。

**README 诚实条款（逐字写入模板，不许改写）**：

> 本项目承诺的复现 = ① 工件级（原始输出永久保存，任何再分析不依赖重新生成）+ ② 统计级（同 config 重跑，聚合指标在自身抽样波动内一致）+ ③ 单机确定级（同机同环境 temp 0 双跑一致）。**不承诺跨硬件 bit 级一致**——浮点归约序差异是行业已知事实，声称 bit 级可复现反而不诚实。本包一切数字为 exploratory / rig-validation 性质，mini 环产出不构成任何假设的证据。

README 另含两组命令：**复评**（`python tools/rescore_standalone.py --pack . --report rescore_report.json`——从 runs/*/steps.jsonl 的 output_text 以 A 的 rescore_copy 判分函数重算全部确定性指标，并与 scores.jsonl 中 deterministic_v1 / rescore_v1 两组分别对比——AMENDMENT-20）与**复跑**（指向原仓库 dispatch 命令 + config 原件；明示复跑需要原仓库与模型权重，包内不含权重）。

`rescore_standalone.py` 要点（已裁决——AMENDMENT-20）：遍历 runs/*/steps.jsonl → 对每条以 **A 的 rescore_copy 判分函数为主**重算全部确定性指标（golden10 按 §3.7 规则；ifeval 族按副本内置规则）→ 与 scores.jsonl 中 `scorer_id='deterministic_v1'`（B）与 `scorer_id='rescore_v1'`（A）**两组分数分别**逐 (run_id,item_id,seed,metric) 对比 → 输出各组一致率（`agreement_deterministic_v1` / `agreement_rescore_v1`）与不一致清单——用 B 的 scorer 核 B 的分数是同源比对，独立复算必须以 A 副本为主、scorer_copy 仅作双实现对照；**judge 指标（trait_score 等）不在复算范围**（非确定性，README 说明）。校验前先按 pack_manifest 逐文件核 sha256，不符即报污染、退出码 2。

**出包自检（已裁决——AMENDMENT-20）**：repro_pack 出包末步以**空 PYTHONPATH** 的 subprocess（`env={"PYTHONPATH": ""}`，cwd=包内 tools/）执行 `python -c "import rescore_copy, scorer_copy"` 验证两副本 stdlib 自包含——契约已同批冻结"B 的 scorer.py 确定性判分函数保持 stdlib 自包含（不 import torch/numpy/abcr 他模块）"；import 失败即**拒绝出包并报 BLOCKER**（把 C-R2-3/4 的现场风险提前到出包时）。

**验收命令**（对 R1 的 fixture 批先行自测；R2 用 mini 环批重跑同式）：
```bash
PYTHONPATH=src python -m abcr.report.repro_pack --batch <batch_id> --out demos/
# 包自检 + 仓库外独立复算（关键：cd 出仓库，证明自包含）：
cp -r demos/repro-<batch_id> /tmp/pack-test && cd /tmp/pack-test
python tools/rescore_standalone.py --pack . --report rescore_report.json
python -c "import json; r=json.load(open('rescore_report.json')); \
print(r['agreement_deterministic_v1'], r['agreement_rescore_v1']); \
assert r['agreement_deterministic_v1']==1.0 and r['agreement_rescore_v1']==1.0"
cd /Users/superagent/abcr-wt/c && rm -rf /tmp/pack-test
```

### C2-3 闭合验收协议文档（预计 1h）

**目标**：`ACCEPTANCE.md` 模板（repro_pack 出包时实例化填 batch_id/文件数/预期一致率）。这是给"**只拿到包的全新会话**"的完整指令书，R2 ④ fable 照此执行。模板正文（逐节要求）：

1. **前提声明**：你（验收会话）只拥有本目录；**禁止**访问原仓库、shared-brain、网络；一切依据 = 包内文件。
2. **完整性核验**：`python -c` 一行脚本逐文件对 `pack_manifest.json` 核 sha256（命令写死在模板里）。
3. **独立复算**：`python tools/rescore_standalone.py --pack . --report rescore_report.json`；预期两组一致率均 == 1.0（以 A 的 rescore_copy 重算，对 deterministic_v1 与 rescore_v1 分别对比——AMENDMENT-20）；任何不一致逐条列 (run_id,item_id,metric,scorer_id,期望,实得)。
4. **判定**：一致率 100% 且完整性核验通过 = PASS；否则 FAIL 并原样报告（不许"大体一致"措辞）。
5. **报告格式**：PASS/FAIL + 核验文件数 + 复算覆盖 (run,item,metric) 三元组数 + 不一致清单 + 验收会话环境（python 版本、平台）。

**验收**：模板 lint——对 fixture 批出的包实例化后，人肉走一遍四步（你自己在干净 shell、`cd /tmp` 下扮演验收会话），全程未回读仓库即算通过；把走查记录贴 PROGRESS。

### C2-4 周证据对象包模板（预计 1h）

**目标**：`reports/weekly/TEMPLATE-weekly-evidence.md` + 生成器 `src/abcr/report/weekly.py`（模板实例化 + 从 views 拉数字，人工补图与叙述）。模板头注释**逐字**：

```markdown
<!--
对外禁令（全部禁止，违者撤回重写）：
1. 只发愿景不发证据；2. 把 exploratory 数字当结论表述；
3. 用 judge 单一分数宣称"突破"；4. 只晒代码量/工程量；5. 藏负结果。
一切数字必须出自账本视图（report.cli / views），带 run_id 与 exploratory / rig-validation 标注。
确认期（ABCR_PHASE=confirmation）本模板输出不得含效应方向（blind.render_effect 强制）。
-->
```

四节结构：**① 一张图**（figures/ 引用 + 图注含数据来源批次）；**② 一段可复现说明**（复现包路径 + rescore_standalone 一行命令）；**③ 本周失败**（triage 失败桶 + 有效负结果，逐条 run_id——此节不可为空，实在没有写"本周无失败记录"并附账本查询命令为证）；**④ 下周假设**（下周要证伪什么，一句一条）。

**验收**：`PYTHONPATH=src python -m abcr.report.weekly --week 2026-W29 --out reports/weekly/`产出实例；四节齐 + 头注释在 + 数字带 run_id。

### C2-5 方向锁盲规则 —— W1 即建代码路径（预计 1.5h）

**目标**：强化 `src/abcr/report/blind.py`，确认期同步**不含效应方向**。相位判断硬编码读 env（不做配置系统）：

```python
"""abcr.report.blind —— 方向锁盲（确认期同步不含效应方向；契约级呈现纪律，W1 即建）。

架构位置：包C·一切效应呈现的强制闸。sync/weekly/cli 中凡呈现"条件间差异"，
必须经 render_effect；确认期剥除方向，解盲权在人（确认期结束后）。
"""
from __future__ import annotations

import os

DIRECTION_TOKENS = ("↑", "↓", "高于", "低于", "上升", "下降", "降低", "正向", "负向",
                    "更好", "更差", "提升", "优于", "劣于", ">", "<",
                    "pos>neg", "neg>pos")   # 无重复项（V1.0 曾重复"下降"，测试有防回归断言）


def current_phase() -> str:
    """exploration | confirmation；缺省 exploration（W1 全程）。"""
    return os.environ.get("ABCR_PHASE", "exploration")


def render_effect(metric_name: str, value_a: float, value_b: float,
                  label_a: str, label_b: str,
                  source_run_ids: list[str] | None = None) -> str:
    """探索期完整呈现；确认期只报量级，不报方向、不报两臂各自数值。
    source_run_ids = 本对比数字的贡献 run 列表——呈现纪律"逐数带 run_id"对
    臂级聚合数的落地：聚合数字以贡献 run_id 列表随行注明（C-R1-7 抽查可回溯）。"""
    delta = value_a - value_b
    runs = f"（runs: {','.join(source_run_ids)}）" if source_run_ids else ""
    if current_phase() == "confirmation":
        return (f"{metric_name}: |Δ|={abs(delta):.4f}"
                f"（方向锁盲：确认期不呈现方向与臂别数值，解盲由人于确认期后执行）{runs}")
    sign = ">" if delta > 0 else ("<" if delta < 0 else "=")
    return (f"{metric_name}: {label_a}={value_a:.4f} {sign} {label_b}={value_b:.4f}"
            f"（Δ={delta:+.4f}）{runs}")


def assert_no_direction(text: str) -> None:
    """确认期渲染后自检：正文含方向 token 即 raise（fail-closed，宁可不出报告不泄方向）。"""
    if current_phase() != "confirmation":
        return
    for t in DIRECTION_TOKENS:
        if t in text:
            raise ValueError(f"方向锁盲违规: 输出含方向 token {t!r}")
```

接线：sync 的 evening 段与 weekly 生成器在写盘前对**效应呈现区块**调 `assert_no_direction`（全模板过一遍会误伤普通措辞，只检效应区块；区块边界用渲染函数聚合，不用正则挖全文）。

**测试**（`tests/report/test_blind.py`）：monkeypatch `ABCR_PHASE=confirmation` → render_effect 输出不含任何 DIRECTION_TOKENS 且不含两臂原值字符串；`=exploration` → 含完整方向；带 `source_run_ids` 时两相位输出均含 `runs:` 注明行；词表防回归断言 `assert len(set(DIRECTION_TOKENS)) == len(DIRECTION_TOKENS)`（V1.0 词表曾重复"下降"）；assert_no_direction 在 confirmation 下对 "A 高于 B" raise、探索期不 raise；sync evening 集成用例：确认期渲染成功且效应区块无方向。
**验收命令**：`python -m pytest tests/report/test_blind.py -v && ABCR_PHASE=confirmation python -m pytest tests/report/test_sync.py -v`（全绿）。

### C2-6 sync/triage 真实数据适配 + 预算余量段（预计 1.5h）

**目标**：① sync morning 增预算段——`costs.jsonl` 的 `run_cost_estimated / run_cost_actual / budget_alert` 汇总 + 余额（150 − 实耗）+ 85% 熔断线距离，逐数带 subject_id；② instances 段——`instances.jsonl` 折叠出未 stopped 的实例（**云实例空转是 A 级显示项**：`instance_idle_alert` 入 triage A级桶）；③ 真批次可读性打磨：mini 环批次跑完后人工读一遍四段+triage，修排版不修数据口径；④ 全部呈现确认 `non_citable` 与 `exploratory` 标注透传（G7）。
**验收**：R2 现场对真实 mini 环批次四段 + triage + overview 全部产出且 fable 确认可读；`grep -L "exploratory" reports/sync-*.md` 为空（每份都有标注行）。

---

## 7. 专项章：阶段3 预置件规格（本轮只交代码与文档，不接线）

### 7.1 notify.py —— 飞书告警 + 按类冷却（全码交付；`ABCR_NOTIFY_ENABLED=0` 默认关）

来源：AILH V2 生产告警机制（feishu_push + health_notify）提炼的最小实现，保留全部关键纪律：per-kind 24h 冷却、**发送成功才记冷却（失败下轮重试——铃必须响到为止）**、原子写状态（tmp+replace）、长文 4000 字分片、fail-safe 不外抛。依赖 lark-oapi 与 python-dotenv（requirements-mac.txt 已含）。**接线开关**：`ABCR_NOTIFY_ENABLED != "1"` 时 `alert()` 直接返回 False 不发送——阶段1/2 恒关，接线是阶段3 楠拍板后的事。

**全码**（`src/abcr/notify.py`）：

```python
"""abcr.notify —— 飞书告警（按 kind 24h 冷却）。阶段3 接线，阶段1/2 代码先行。

架构位置：包C·对人通知出口。app 凭证直发纯文本（不 @ 任何人 → 人可见、
不触发任何 bot）。纪律（承 V2 health_notify）：发送成功才记冷却；失败不记、
下轮重试；状态原子落盘。接线开关 ABCR_NOTIFY_ENABLED（缺省 0=关）。
依赖: lark-oapi, python-dotenv（均在 requirements-mac.txt）。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# 项目根 .env（src/abcr/notify.py → parents[2] = 仓库根；ABCR_ROOT 可覆盖）
_ROOT = Path(os.environ.get("ABCR_ROOT", Path(__file__).resolve().parents[2]))
load_dotenv(_ROOT / ".env")

COOLDOWN_S = int(os.environ.get("ABCR_ALERT_COOLDOWN_S", str(24 * 3600)))
MAX_MSG_LEN = 4000   # 飞书文本消息分片长度（与 V2 生产同值）


def _state_path() -> Path:
    """冷却状态文件路径——调用期求值（勿改回模块级常量：import 早于测试的
    monkeypatch，模块级读 ABCR_STATE_DIR 会让 tmp 重定向失效、冷却写进真 state/）。"""
    return Path(os.environ.get("ABCR_STATE_DIR", "state")) / "alert-cooldown.json"


def _enabled() -> bool:
    return os.environ.get("ABCR_NOTIFY_ENABLED", "0") == "1"


def _send_feishu(text: str) -> bool:
    """app 凭证直发纯文本。失败只返回 False，绝不外抛。"""
    app_id = os.environ.get("AUDITOR_FEISHU_APP_ID", "") or os.environ.get("FEISHU_APP_ID", "")
    app_secret = (os.environ.get("AUDITOR_FEISHU_APP_SECRET", "")
                  or os.environ.get("FEISHU_APP_SECRET", ""))
    chat_id = os.environ.get("ABCR_FEISHU_CHAT_ID", "")
    if not (app_id and app_secret and chat_id):
        print("[abcr-alert] 飞书凭据/chat_id 缺失，跳过发送", file=sys.stderr)
        return False
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
        client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
        ok = True
        for i in range(0, len(text), MAX_MSG_LEN):
            body = (CreateMessageRequestBody.builder()
                    .receive_id(chat_id).msg_type("text")
                    .content(json.dumps({"text": text[i:i + MAX_MSG_LEN]})).build())
            req = (CreateMessageRequest.builder()
                   .receive_id_type("chat_id").request_body(body).build())
            resp = client.im.v1.message.create(req)
            if not resp.success():
                print(f"[abcr-alert] 飞书发送失败 code={resp.code} msg={resp.msg}",
                      file=sys.stderr)
                ok = False
        return ok
    except Exception as e:  # noqa: BLE001 — 告警绝不反噬主流程
        print(f"[abcr-alert] 飞书通路异常: {type(e).__name__}: {e}", file=sys.stderr)
        return False


def _age_s(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        t = datetime.fromisoformat(str(raw))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except (ValueError, TypeError):
        return None   # 解析失败=视为无记录 → 放行（宁可多响不漏响）


def alert(kind: str, msg: str) -> bool:
    """按 kind 冷却发告警。True=已发送；False=开关关/冷却内静默/发送失败。

    kind 命名约定：`<类>:<主体>`（如 "budget:W1"、"quarantined:B-...-0001"），
    冷却按完整 kind 字符串独立计——同类不同主体各自冷却。
    """
    if not _enabled():
        print(f"[abcr-alert] ABCR_NOTIFY_ENABLED!=1，静默丢弃 [{kind}]", file=sys.stderr)
        return False
    sp = _state_path()
    try:
        state = json.loads(sp.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except Exception:  # noqa: BLE001 — 文件缺/坏 = 空状态
        state = {}
    age = _age_s(state.get(kind))
    if age is not None and 0 <= age < COOLDOWN_S:
        return False   # 冷却内 → 静默
    text = (f"🔔 ABCR 告警 [{kind}]（{datetime.now().astimezone():%m-%d %H:%M}）\n"
            f"{msg}\n同类告警 {COOLDOWN_S // 3600}h 内不再重复通知。")
    if not _send_feishu(text):
        return False   # 不记冷却 → 下次调用重试
    state[kind] = datetime.now(timezone.utc).isoformat()
    try:   # 原子写状态（tmp + replace，与 V2 同范式）
        sp.parent.mkdir(parents=True, exist_ok=True)
        tmp = sp.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(sp)
    except Exception:  # noqa: BLE001 — 状态写失败最坏=多响一次，可接受
        pass
    return True


if __name__ == "__main__":   # 冒烟: PYTHONPATH=src python -m abcr.notify smoke "测试消息"
    k = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    m = sys.argv[2] if len(sys.argv) > 2 else "ABCR 告警通路冒烟测试"
    print("sent" if alert(k, m) else "suppressed-or-failed")
```

**mock 单测（`tests/report/test_notify.py`，零网络，阶段1/2 就写好）**：monkeypatch `abcr.notify._send_feishu` 为记录桩 + `ABCR_NOTIFY_ENABLED=1` + `ABCR_STATE_DIR=tmp`。用例：① 开关关（unset/0）→ 返回 False 且桩未被调；② 首发 True 且冷却文件生成；③ 同 kind 立刻再发 → False（suppressed）且桩只调过一次；④ 桩返回 False（发送失败）→ 不记冷却，再调仍会尝试；⑤ 冷却文件预置垃圾内容 → 不崩、按空状态放行；⑥ 不同 kind 互不影响。**验收**：`python -m pytest tests/report/test_notify.py -v` 全绿。

### 7.2 信封内自动派发开关（只交规格与毕业检查器，不接线）

- **毕业判据（冻结）**：累计 **20 个 run** 的 shadow 批次记录中，草案与人工决策**零关键差异**（关键差异定义见 C2-1，逐字同一）**且** 这些批次的 auditor 报告全绿。达成后才允许讨论开启；**确认期发射恒人工，不受此开关影响**。
- **开关形态（规格，未生效）**：信封新增可选字段 `"auto_dispatch": true`。⚠️ 信封 schema 是冻结契约（§3.5）——**加字段 = 契约修订，须 fable 走 AMENDMENT 广播后方可实装**；本轮你只交付：规格文本（本节）+ 毕业检查器。到点后流程 = 你在 PROGRESS 出示毕业证据 → 楠点头 → fable 修订契约 → B 的 dispatch 才认这个字段。
- **毕业检查器**：`scripts/c_shadow_graduation.py`——扫 `plans/shadow/*.shadow.json`，对 `key_difference==false` 的批次从账本折叠其 run 数求和（run↔batch 关联走 runs_index 的 `run_registered.batch_id`——AMENDMENT-19；未启动 run 以信封 run_configs 对账，装载经 read_chain_merged 含云链段）；读 `reports/audit/<batch_id>.json` 的整体 verdict（A 的报告，PASS 才计入。`reports/audit/` 归 A——命名分区 AMENDMENT-31；**verdict 键形是跨包接口，检查器上线前须在 PROGRESS 契约疑议节核实 A 包同版约定**，本轮假数据测试不受影响）；打印 `GRADUATED`（≥20 run 且全绿）或 `NOT_GRADUATED` + 逐批证据行。验收：对测试造的 shadow 记录 + 假审计报告，两种结论各正确打印。

### 7.3 飞书接线检查单（阶段3 开工首日，与楠一起过）

1. 楠拍板 bot 身份（默认复用 AUDITOR bot——.env 已有凭证对）与目标群（沿用 V2-1 或新建 ABCR 群）。
2. **bot 必须已在目标群里**（未入群 create 必失败 resp.code≠0——先拉 bot 进群再冒烟）。
3. `.env` 补 `ABCR_FEISHU_CHAT_ID=<oc_ 开头群id>`（该值不在 kickoff 注入清单里，由楠提供；勿 commit）。**.env 位置 = 主仓根 `/Users/superagent/abcr/.env`**（gitignore，不随 worktree 检出——worktree 里没有这个文件）；在 worktree 内跑冒烟须先 `export ABCR_ROOT=/Users/superagent/abcr`，否则 notify 的 load_dotenv 按 `__file__` 推根落在 worktree、读不到 .env。
4. `.env` 置 `ABCR_NOTIFY_ENABLED=1`（在此之前一切 alert 调用静默——检查单过完才改）。
5. 冒烟：`PYTHONPATH=src python -m abcr.notify smoke "ABCR 接线冒烟"` → 群里见消息；**立刻再跑一次预期 suppressed-or-failed（冷却生效，属预期而非故障）**。
6. 接线点清单（代码里已预留调用位，此时取消注释/开启）：triage A级桶逐条 `alert(f"<类>:<主体>", ...)`；watchdog 停摆（B 侧自有通路，不经你）；budget 85% 熔断线。
7. 复核冷却状态文件落 `state/alert-cooldown.json`（gitignore 内）。

---

## 8. 测试与验收总表（R 门判据；每条都是可执行核验）

### 8.1 R1 门·你的判据项（fable 主持演练时逐条打勾；AMENDMENT-30 拆分：C-R1-1~4 = R1-core，R1 门（7/14 上午）验；C-R1-5~8 = R1-full，阶段2 期间完成、R2 前对 fixture 批补验——判据本身不变）

| # | 判据 | 核验命令 | 预期 |
|---|---|---|---|
| C-R1-1 | 契约测试全绿 | `python -m pytest tests/contract -q` | 全绿 |
| C-R1-2 | 你的全部单测绿 | `python -m pytest tests/governor tests/report -q` | 全绿 |
| C-R1-3 | 令牌真值锚：fixture 正样过、坏样原因码对 | `python -m pytest tests/governor/test_approval_token.py -v` | 含 fixture 锚用例，全绿 |
| C-R1-4 | approve 签发可被 B 消费 | fable 演练：`scripts/abcrctl approve fixtures/envelope_fixture.json --key fixtures/test_approval.key`（必带 --key，见 C1-3 备忘）→ B dispatch 放行 | dispatch 退出码 0；演练后 `git checkout -- fixtures/` |
| C-R1-5 | planner 合法出草案/越界拒草案 | C1-4 验收命令两组 | PASS 组落信封、FAIL 组不落 |
| C-R1-6 | triage 分桶正确（含续跑已收敛行） | 对演练后真账本跑 `python -m abcr.governor.triage`（crash-resume run 应现身"已收敛偏差"） | 分桶与账本一致 |
| C-R1-7 | sync 四段含该批全貌、逐数带 run_id（臂级聚合数字以贡献 run_id 列表随行注明——render_effect source_run_ids） | 四段生成后 fable 抽查任一数字回溯账本行 | 抽查数字（含聚合行）可回溯；头部纪律行在 |
| C-R1-8 | 三层钻取 ≤1 分钟到单题原文 | C1-7 的 time 三连（batch/run/item 用演练批实值） | 总 real ≤ 60s；g03 原文=fixture fail_sample |

### 8.2 R2 门·你的判据项

| # | 判据 | 核验命令 | 预期 |
|---|---|---|---|
| C-R2-1 | shadow 差异记录成立 | mini 环批次的 `plans/shadow/<id>.shadow.json` 存在；`python -m pytest tests/governor/test_shadow.py -q` | 四关键维判定正确 |
| C-R2-2 | 复现包内容清单齐 + 全哈希 | 出包后 `python -c` 核 pack_manifest 逐文件 sha256 | 全符 |
| C-R2-3 | 仓库外独立复算全同 | C2-2 验收命令（/tmp 下跑 rescore_standalone，A 副本为主——AMENDMENT-20） | agreement_deterministic_v1==1.0 且 agreement_rescore_v1==1.0 |
| C-R2-4 | 闭合验收（R2 ④） | fable 开全新会话仅给包，按 ACCEPTANCE.md 四步走 | PASS 报告 |
| C-R2-5 | 方向锁盲 | `ABCR_PHASE=confirmation python -m pytest tests/report/test_blind.py tests/report/test_sync.py -q` | 全绿 |
| C-R2-6 | 周证据包模板合规 | weekly 实例四节齐 + 头禁令注释 | 齐 |
| C-R2-7 | G7 呈现纪律 | `grep -L "exploratory" reports/sync-*.md`；抽查 non_citable 透传 | grep 输出为空；标注在 |
| C-R2-8 | 阶段3 预置件就位（不接线） | `python -m pytest tests/report/test_notify.py -q`；`ABCR_NOTIFY_ENABLED=0`（或未设）下 alert 静默 | 全绿；静默 |

---

## 9. 代码规范与 PROGRESS.md 格式

**代码规范**：Python 一切函数签名带 type hints（含返回值）；每个模块 docstring 首段说明其在三包架构中的位置（本文各嵌码即范例）；核心逻辑有 pytest 单测（放 `tests/governor/` 或 `tests/report/`）；命名 snake_case；不硬编码任何密钥/凭证（读 env）；不新增第三方依赖（requirements-mac.txt 之外要用先走 PROGRESS）。commit 信息格式 **`[pkgC] description`**（如 `[pkgC] add envelope canonicalization and sha256`），小步提交，每张任务卡至少一个 commit。

**PROGRESS.md 格式（每日收工必写，追加式，最新在顶）**：

```markdown
## 2026-07-14（D1）
### 完成
- C1-1 approval_token 接管：与 kickoff 实物 diff 一致（差异点：无）；补测 12 用例全绿（commit abc1234）
### 未完成
- C1-2 envelope.py 写到 validate 的 budget 分支（预计明日 1h 收尾）
### BLOCKER
-（无 / 或：描述 + 已尝试什么 + 需要 fable 什么裁决）
### 契约疑议
-（无 / 或：一句话疑议 + 所依契约条文位置。例：ledger_ref 实物 append 签名与本文假名不符——§4.4 核对项4）
```

四节缺一不可；没有内容的节写"（无）"。BLOCKER 定义：阻塞你超 30 分钟且自己解不开的事——记下即换卡，别等。

---

## 10. 已知坑与注意事项（坑 → 症状 → 规避）

- **K1 两个序列化口径并存**：令牌载荷签名用 `json.dumps` **默认** separators；envelope_sha256/config_hash 用**紧凑** `(",", ":")`。→ 症状：自己算的 sig/sha 与对方不互认、fixture 锚用例红。→ 规避：签名只经 `_payload_bytes`、信封哈希只经 `canonical_json`，**C 包代码内**不出现第三处 json.dumps 序列化用于哈希/签名；也不要"顺手统一"这两处——都是冻结口径。另注：账本链 entry_hash（§3.2）是 A 的第三口径（默认 separators + prev_hash 拼接），你只读不算链，勿套紧凑口径去复核链哈希。
- **K2 契约测试红 ≠ 你先改契约**：→ 症状：`tests/contract` 红。→ 规避：先停，查是不是自己的 approval_token/envelope 改动引起；不是则原样记 PROGRESS 契约疑议，等 fable。契约测试文件本身你永远不改。
- **K3 对称 HMAC 的边界（架构洞见，来自 V2 生产教训）**：应用层校验跑在被治理进程自己的进程空间里，被治理者理论上可自改校验；且 HMAC 对称——**能读 key 即能签**。V2 的真保证是内核级 Seatbelt deny 令牌账本目录（且 Seatbelt 只 deny 写、读全开，故 V2 把校验+消费放在沙箱外进程）。ABCR W1 的现实：人机同域、批次全由人批，**"人侧独占签发"靠纪律（系统域代码不 import sign_token）而非内核**——这是已声明的 W1 折衷。→ 规避：① 系统域不 import sign_token 写进 code review 自查；② 阶段3 若真开自动派发，在 PROGRESS 提请把 `state/approvals/` 与 `approval.key` 纳入 A 的 Seatbelt 恒 deny 清单（deny 行须排在所有 allow 之后——last-match-wins），或改非对称签名——先立字据后开闸。
- **K4 approval.key 上云即扩散**：云日 B 会把 key 带上云机（B 包已知条款）。→ 规避：云日收工提醒楠轮换（删 `state/approval.key`，abcrctl 首用重生成；未消费令牌作废重签）；key 永不进 git/复现包/tar（repro_pack 的文件收集用白名单式路径，不用 `cp -r 整目录`）。
- **K5 consumed.json 两个已知弱点**：读-改-写无文件锁（多进程并发消费会互相覆盖）；损坏时按空集处理（重放风险换可用性——canonical 语义如此）。→ 症状：并发下丢消费记录。→ 规避：W1 单消费者（B 的 dispatch 串行）成立，够用；sync/status 展示消费态时把"consumed.json 缺失/损坏"显式标注出来而不是显示"未消费"。
- **K6 `datetime.fromisoformat` 的 naive 时间**：→ 症状：比较 naive 与 aware datetime 抛 TypeError。→ 规避：一切解析后 `tzinfo is None` 即 `replace(tzinfo=timezone.utc)`（令牌代码与 ledgerio 时间比较统一走此式）。
- **K7 DuckDB read_json 版本差异（未实测本机 duckdb 具体版本）**：→ 症状：`format='newline_delimited'` 或 `union_by_name` 参数不识别。→ 规避：改 `read_ndjson_auto('<path>')`；再不行降级 ledgerio 纯 Python 聚合（数据量 W1 极小，性能无虞）。账本事件**顺序**永远不依赖 SQL（文件序即链序），只用 DuckDB 做 scores/steps 聚合。**另一症状**：glob 无任何匹配文件时 `read_json_auto` 抛 IO Error（"No files found"）——空数据不是异常路径，查询前先 Python glob 判空、空则不下 SQL 直接返回零值结构（C1-7 要点）。
- **K8 glob 在 SQL 字符串里的注入面**：run_id/item_id 进 SQL 一律参数化（`con.execute(sql, [run_id])`），不做 f-string 拼接——run_id 虽受格式约束，习惯不留口子。
- **K9 fixture 是共用冻结物**：→ 症状：测试把 `fixtures/envelope_fixture.json` 改脏，A/B 的测试跟着红。→ 规避：一切测试对 fixture **先 copy 到 tmp_path 再操作**；R1 演练的就地 approve 是唯一例外（事后 `git checkout -- fixtures/`）。
- **K10 账本只读纪律的诱惑点**：写 triage/sync 时会很想"顺手补一条账本事件"。→ 规避：Governor 对 ledger/ 恒只读（§2.3）；一切"该有个事件"的想法进 PROGRESS 契约疑议。测试要写账本 → 只写 tmp_path 下的测试账本。
- **K11 中文输出的 ensure_ascii**：→ 症状：报告/JSON 里中文变 `\uXXXX`。→ 规避：一切 `json.dumps(..., ensure_ascii=False)`（嵌码已统一）；但**哈希/签名口径里的 ensure_ascii=False 是冻结协议的一部分**，不是风格偏好，勿改。
- **K12 notify 冒烟第二次必 suppressed**：属冷却预期而非故障（K 之名录以免误报 bug）。bot 未入群 → resp.code≠0 必失败：先拉群再冒烟（§7.3）。
- **K13 macOS 差异**：`/tmp` 是 `/private/tmp` 符号链接——你在 /tmp 下做包外复算没问题，但**若阶段3 参与沙箱相关事宜，profile 路径必须 realpath**（A 的领域，此处仅备忘）。`date` 等 BSD 工具参数与 GNU 不同，脚本里日期一律用 Python 生成。
- **K14 "≤1 分钟钻取"是体验判据不是基准测试**：→ 规避：不为它上缓存/索引等复杂度（D6 红线：控制面不吞噬研究时间）；DuckDB 内存直查 + W1 数据量（百级 run）本来就秒级，超时先查是不是误扫了 `data/runs/` 之外的大目录。

---

*（完）工程包C V1.0 ｜ 上位：ABCR-实现执行方案-V1.0（契约已全文嵌入 §3，执行窗口无需也不得回读上位文档）｜ 契约修订权：fable ｜ 疑议通道：PROGRESS.md*
