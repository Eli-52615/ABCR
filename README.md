# ABCR — AI Behavioral Controllability Research

**经引导的人格，能否可靠地、可以归因地提升智能体的能力？**

> **状态：研究进行中。** 实验控制面已经在真实 7B 模型批次上端到端通过验收门；**确认性实验（H1 / H2 / S1 / T1）还没有开始。** 本仓库里所有数字都是 `exploratory`（探索性）或 `rig-validation`（装置验证）性质，`citable=false`，不构成研究结论。
>
> 姊妹项目：[AILH](https://github.com/Eli-52615/AILH)，从 harness 侧研究智能体价值框架怎样塑造长期自主行为。

## 摘要

已有研究表明，人格提示能改变大语言模型智能体的行为和任务表现。但这类证据大多停留在文本层：我们分不清效应到底来自"人格"本身，还是来自更长的提示、更多的展开，或者模型原有的能力。如果人格要成为塑造智能体能力的可靠手段，并且最终能固化进模型、迁移到其他智能体上，就必须先回答它**是否以及怎样在模型内部起因果作用**。

ABCR 研究的正是这个问题。我们把文本人格当作对人格敏感的"测试场地"和剂量标尺，在残差流里用差分均值抽取命名人格方向，再用三组检验分离因果来源。**H1** 检验文本人格的效应能否由"人格策略特征 × 任务需求"的连续规律预测。**H2** 用投影消融检验这种效应是否部分经由可以命名的内部方向中介。**S1** 检验不经过文本、直接钳制注入能否独立产生方向一致、剂量相关的行为变化。每一个干预都强制配对对照：中性等 token 文本、同长度指令，以及等范数随机方向的注入和消融，用来排除"只是更长""只是更啰嗦""任何扰动都行"这类替代解释。在此之上，**T1** 会在冻结的 AILH harness 里做多轮轨迹试验，用带 sham 的动态触发设计，把"人格内容"的净效应和"触发与监测"本身的效应分开。

要让这样的结论硬性可靠，光有实验设计不够，执行过程本身也要可审计。所以我们同时构建了一套**账本先于叙事**的自动化实验控制面：实验计划必须经人签名审批，执行全程用哈希链记录，评分在仓库外独立复算，审计一律 fail-closed（宁可误报也不漏报）。目前，控制面已经在真实的 Qwen2.5-7B 批次上通过端到端验收门（独立复算一致率 1.0，装置验证性质）。我们希望这项工作为"人格调适能否成为可靠的能力手段"提供一条可以证伪、可以复算的检验路径。

<details>
<summary>English abstract</summary>

Persona prompting is known to change the behaviour and task performance of LLM agents, but most evidence stays at the text level and cannot separate the effect of the *persona* from longer prompts, more elaboration, or the model's own competence. ABCR asks whether guided personality can **reliably and attributably** improve agent capability. Using text personas as a persona-sensitive testbed and dose scale, we extract named persona directions from the residual stream (difference-of-means) and test causality three ways: **H1** — whether text-persona effects follow a continuous law of *persona strategy features × task demands*; **H2** — whether they are partially mediated by nameable internal directions (projection ablation); **S1** — whether clamped, text-free injection alone produces direction-consistent, dose-dependent behaviour change. Every intervention is force-paired with controls (neutral equal-token text, same-length instructions, equal-norm random-direction injection/ablation). **T1** then runs a multi-turn trajectory trial inside a frozen [AILH](https://github.com/Eli-52615/AILH) harness with sham-controlled dynamic triggering. To make such claims auditable, ABCR includes a ledger-first, fail-closed experiment control plane (human-signed approvals, hash-chained execution logs, out-of-repo independent rescoring). The control plane has passed an end-to-end gate on a real Qwen2.5-7B batch (rig validation); **confirmatory experiments have not started yet.** Documentation is primarily in Chinese.
</details>

## 一、研究目标

最终目标是：让 AI 在"任务 → 现实反馈"的循环中，抽象出自身行事的完整框架；实时对比"按自身框架行事会得到什么结果"和实际结果之间的偏差；再依据实际结果，逐任务或逐批次地更新框架里每一个相关节点。这里的框架指 harness 层（人设、编排架构、经验系统）加上模型层（权重 / LoRA）的总和。

要证明的命题是：**经引导的人格能显著提升 AI 的能力**（从任务表现上看），并且这种提升**来自人格调适**，而不是 harness 里的人设文本或模型本身的能力。理想情况下，成果能固化到模型层，并能在不同智能体之间推广。

推理链如下：

1. 人格调适存在增益能力的可能性（已有研究报告）。
2. 在 harness 各层中，prompting 对能力的影响最大。所以先用文本人格作为测试场地，观察哪些人格对哪些任务有增益。
3. 同步观察：文本人格改变时，模型内部的人格方向是否也被激活？两者方向是否一致，对应关系是什么？
4. 如果内部激活是行为改变的主要通道，就绕过文本，直接在模型内部激活"高增益人格"。这样可以避开文本激活带来的漂移和噪声，验证内部激活对能力的正面作用。

## 二、假设登记（摘要）

完整版本见 [`docs/design/1规划设计/ABCR-实验方案-V1.3.md`](docs/design/1规划设计/ABCR-实验方案-V1.3.md)。

| 编号 | 假设 | 主判据 |
|---|---|---|
| **H1** | 文本人格效应可以由"策略特征（核验 / 探索 / 坚持 / 谨慎）× 任务需求"的连续规律预测 | cell 级聚类 bootstrap；用留一人格、留一任务族的外部验证来界定"通用"这个措辞能不能用 |
| **H2** | 效应至少部分经由可以命名的内部方向中介 | 在合格 cell 内，投影消融带来的**绝对削减量**显著，而等范数随机方向的消融没有可比的削减 |
| **S1** | 不经文本、钳制剂量的注入，能产生方向一致、剂量相关的行为变化 | 剂量扫描的单调段；对照族在同剂量下没有这种模式。不设增益门槛，正负结果都发布 |
| **T1** | 多轮轨迹价值试验（7 臂，含文本 sham 和向量 sham） | 干预内容的效果 = 动态臂 vs sham（触发规则相同） |

**对照纪律。** 凡是干预都必须配对。同长度指令臂被明确定位为"夹逼上界"，而不是完美的中性条件。人格向量必须通过谱系、表达、词表、孪生、副作用五项检查，才能被命名，否则只能叫 `direction-k`。

## 三、实验控制面：账本先于叙事

**账本上没有记录的，就等于没发生过。** 一切结论都应该是账本上的查询结果。

```
① 提计划草案 (abcrctl draft)  →  ② 人签字批准 (abcrctl approve)  →  ③ 看账本 / 审计结论 (a_views / a_audit)
```

| 包 | 职责 |
|---|---|
| A：账本 / 状态机 / Auditor | 哈希链账本、批次状态机、六项审计 |
| B：Operator / rig 科学载荷 | 签发信封、分发执行、真模型 runner、hook / 向量注入 |
| C：Governor / 同步视图 / 复算 | 审批令牌、仓库外独立复算、自包含复现包 |

为了保证这一点，还配了这些机制：成本闸（付费测试在 import 之前就被拦下）、审批令牌防重放、在隔离 root 下执行、对抗性多轮审查（每一轮都配阴性对照）。

## 四、目前进展

| 时间 | 里程碑 | 性质 |
|---|---|---|
| 2026-07-11 ~ 14 | **W1**：从冻结配置到复现包的最小纵向闭环；在 Qwen2.5-7B 上复现 Persona Vectors 的抽取→注入链路（optimistic，L20：系数 +2.0 时 trait 分 82.9→100.0，−2.0 时降到 21.1，coherence ≈ 95） | exploratory，单 trait，judge = deepseek-chat |
| 2026-07-15 | **R1 门**：三包首次真正互相签核 | 工程 |
| 2026-07-16 | **R2 硬门**：真 7B golden10 批（`B-20260716T070201Z-0001`），A 审计 1–5 项 PASS，C 在仓库外独立复算一致率 1.0 / 1.0 | rig-validation |
| 2026-07-19 ~ 26 | 人格探索控制面接入真实运行；九轮对抗审查（所有阻断级 P0 都只在真实环境里暴露出来） | 工程 |
| 2026-07-26 ~ 27 | 最小快道实验闭环（分支 [`fastlane-minloop`](../../tree/fastlane-minloop)，还没并入 main） | 进行中 |
| 下一步 | 探索期（3 臂文本人格）→ W3 预注册冻结 → 确认期 | 未开始 |

`main` 分支只在通过回归门时前进；最新的进行中工作在 `fastlane-minloop`。

### 一条方法论上的发现

全部阻断级缺陷都**只在真实环境里才暴露**：真实体量的 manifest（比夹具大 3,435 倍）、真实 root 权限的语义、真实 macOS 账户环境、真实依赖产物。上千个绿色单测在夹具世界里一个都照不出来。**夹具的保真度就是审查的天花板。** 详见 [`docs/design/ABCR-ENGINEERING-HISTORY.md`](docs/design/ABCR-ENGINEERING-HISTORY.md)。

## 五、仓库结构

```
src/abcr/        核心库（runner、models、interventions、eval、ledger、audit、governor、control …）
scripts/         preflight_kickoff.py、abcrctl、run_r2_batch.sh、a_views.py 等入口
configs/         模型钉版、chat template 哈希、运行配置、schema
tests/           contract_pkgabc（控制面契约）、contract/（W1 归档）、control、ledger、audit …
data/ fixtures/  题目与 split（split 哈希在首轮前入库）、确定性测试夹具
repro_packs/     W1 复现包
docs/design/     全部设计文档（实验方案 V1.0→V1.3、自动化工作流、W1、人格探索落地）
docs/lit-review/ 文献综述流水线产物
results/r2/      R2 真批证据包
```

## 六、上手

两个 Python 环境：`.venv312` 是控制面（不需要 torch），`.venv` 用来跑真实模型（需要 torch）。下面的命令都**零成本、零联网**。

```bash
PYTHONPATH=src .venv312/bin/python scripts/preflight_kickoff.py   # 开工体检，30/30 PASS 才继续
PY=.venv312/bin/python bash scripts/run_r2_batch.sh fake           # 用 fake 引擎走完整条链路
PYTHONPATH=src .venv312/bin/python scripts/a_views.py runs         # 只读账本
```

给非工程背景读者的完整说明：[`docs/上手指南-如何开始实验.md`](docs/上手指南-如何开始实验.md)；W1 实验体的手册：[`docs/W1-quickstart.md`](docs/W1-quickstart.md)。

## 七、阅读说明

- 文档的主要工作语言是中文。文中的"楠"就是作者本人。
- 本仓库的代码和文档由作者与多个 AI 编程 agent 协作完成。`CLAUDE.md`、`DEVIATIONS.md`、`PROGRESS-*.md` 和 `STATUS-*.md` 是给这些 agent 的工作契约和过程记录，按原样保留。
- 呈现纪律：Mac 上的产物一律 `citable=false`，正式证据需要 24GB 云卡 bf16；所有实验只碰 dev split。
- **快照发布**：本仓库是作者本地主仓的快照，每个分支只有一个提交。文档里引用的提交哈希（例如 `ea61033`）指向本地主仓的历史，在这里查不到。
- **已知的可移植性限制**：`configs/models.yaml` 钉的是作者本机 modelscope 缓存路径，换一台机器需要按 `scripts/bootstrap.sh` 重新生成。W1 归档测试依赖的 `tests/fixtures/tinyqwen/` 是 bootstrap 生成的，没有入库。

## 许可

代码以 [Apache License 2.0](LICENSE) 发布。
