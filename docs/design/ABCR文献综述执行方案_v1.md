# ABCR 文献综述执行方案 v1.0

**文档性质**：决策仪器规格书，非学术仪式说明书
**三方分工**：本文档 = 方案层（上游判断）｜Claude Code = 执行层｜楠 = 裁决层
**时间盒**：14天，硬边界
**起草日**：2026-07-16

---

## 0. 给 Claude Code 的任务契约（先读这一节）

### 你的使命
在14天内，围绕ABCR的7条可证伪主张（见§2），产出一份**能支撑三个决策**的文献定位体系：
1. **新颖性判决**：每条主张判定为 REPLICATE / EXTEND / OPEN（语义见§2.3）
2. **方法进口清单**：可直接偷进ABCR设计v2和操作化表格的对照设计、测量方法、混淆清单
3. **定位骨架**：related work结构 + gap statement的证据弹药

### 你的自由度
检索管线架构、去重算法、存储格式、限流处理、并发策略、初筛的具体实现——全部你自决。本方案只锁定：检索源要求、产物schema、质量门、升级触发条件。

### 你的硬约束（违反任何一条即为执行失败）
1. **零幻觉引用**：任何论文进入定位表前，必须经API核实元数据（标题/作者/年份/venue/摘要一致）。核实失败的条目进隔离区并报告，**不得静默丢弃**。本方案种子集里所有标注〔记忆〕的条目都是待核实假设,不是事实。
2. **全程溯源**：定位表每一行必须记录来源（哪条查询/从哪篇滚雪球/哪个探针）。
3. **校准探针召回率100%**：§3每个前沿列有"必检出探针"。任何探针未被你的检索流程自然检出，说明检索有洞，必须书面解释并修补后重跑。
4. **当日升级规则**：任何论文摘要**同时**满足（提到 persona/personality/trait/character/steering 之一）且（提到 agent/agentic/task success/tool use/long-horizon 之一），当日列入升级清单报楠，不等批次。
5. **摘要不等于已读**：你的抽取初稿基于摘要+引言+实验设置节；标注清楚抽取深度。Tier-1精读是楠的活，你不越权下结论。
6. **日报**：每日产出一行统计——收获数/筛后保留数/隔离数/探针状态/升级数/异常。

---

## 1. 底层价值原则（七条，冲突时按序优先）

**P1 综述是决策仪器。** 唯一存在理由是支撑§0的三个决策输出。任何不服务于此的扩展（读起来有趣、领域完整性、写作美感）都是范围蔓延，砍掉。

**P2 以主张为单位，不以领域为单位。** ABCR的新颖性不住在任何单一领域里，住在几个领域的交叉点上。比较的基本单元是"主张×主张"，不是"论文×论文"。一篇论文可能对C1构成威胁、同时对C5构成礼物。

**P3 证伪优先（kill-first）。** 综述的第一任务是尝试廉价地杀死ABCR。检索顺序按杀伤力排：最近邻先查。"两周内自己找到致命论文"永远好于"三个月后被审稿人找到"。已预检出的2026年邻居（§2.4）在D0-D2优先精确定界。

**P4 覆盖有界，判断不外包。** 语料有界：筛选约150–300篇，抽取40–60篇，精读12–15篇。用饱和准则终止，不追求穷尽。AI做检索/初筛/抽取初稿；**凡是喂进判决的关键字段，由人核对**。

**P5 真实性硬约束。** 见§0约束1、5。另：抽取中的任何引述必须带定位锚（节号/页码）。

**P6 时间盒与提前坍缩。** 14天硬边界。若D2的杀伤查询确认某主张邻近度3成立，该主张的检索立即坍缩为"确认边界+改写主张"模式，省下的预算转给存活主张。

**P7 产物直接喂两个下游。** 一是给杨晓燕的操作化作业（文献里的证据标准、混淆清单直接偷用并注明出处）；二是ABCR设计v2变更清单。产物形态=表格+判决备忘录，禁止叙事综述文体。

---

## 2. ABCR主张分解与判决语义

### 2.1 七条主张（本综述的脊柱）

| 编号 | 主张 | 一句话可证伪表述 |
|---|---|---|
| C1 | 人格文本→行为 | 人格文本条件相对**等长中性对照**会稳定改变agent任务行为与成功率，且超越语言风格层 |
| C2 | 内部方向介导 | 该效应至少部分由残差流中的线性方向介导；投影消融该方向会削弱文本人格效应 |
| C3 | 方向注入复现 | 不用人格文本、仅注入内部方向，可产生方向一致、剂量相关的行为变化 |
| C4 | 任务×策略匹配 | 不同任务的最优人格/策略条件不同（存在系统性交互效应），且可用于条件选择 |
| C5 | 行为原语可测 | 核验/探索/坚持/校准可从轨迹中有效测量，与语言风格可区分（判别效度） |
| C6 | 测量链/中介结构 | 人格→中间策略→可观察动作→任务结果的中介链可建立并检验 |
| C7 | 长程漂移交互 | 多轮长程中人格条件发生漂移，且漂移与恢复/止损行为存在交互 |

### 2.2 每条主张的杀伤条件（什么发现构成致命/重创）

- **C1致命**：已有论文在**agentic任务**（多步、工具使用）上，用等长/中性/同长展开等严格对照，证明人格条件改变任务成功率。若仅在静态基准（QA/推理）上成立→重创但不致命，C1转为"行为域扩展"主张。
- **C2/C3**：方向抽取、消融、注入方法学已被特质类工作（拒绝方向、人格向量）确立——这两条本来就是"已知方法、新结果变量"型主张。致命条件仅为：已有工作把方向干预直接链接到**任务成功率**并做了剂量-反应分析。
- **C4致命**：已有系统性的人格×任务交互研究**加**自适应选择机制，且覆盖长程agentic任务。仅覆盖认知基准→C4收缩到agentic域。
- **C5**：已有经过效度检验的轨迹级行为原语测量框架→**这是礼物不是杀伤**：策略转为"采纳+扩展"，不自建分类学；新颖性移到"人格干预下的原语变化"。真正致命=连"人格干预下测原语"也有人做完。
- **C6致命**：已有人格→行为→结果的中介分析（含统计检验）。
- **C7致命**：已有漂移×恢复行为的交互研究。

### 2.3 判决语义（三值，禁止二值化）

- **REPLICATE**：拥挤。ABCR做它只有内部校准价值，无发表价值。
- **EXTEND**：存在直接邻居，但在明确维度X上有缺口（行为域/对照严谨度/结果变量/测量层）。发表叙事="我们在X上推进"。
- **OPEN**：无邻近度≥2的邻居。发表叙事="首次"，但需自证不是检索遗漏——OPEN判决要求该前沿探针全中+饱和达标+两轮滚雪球空手。

### 2.4 预检出邻居（2026-07-16两次快速检索的结果；**初步定界，非结论**——Code须拉全文精确核界）

| arXiv/来源 | 内容速记 | 初判威胁 |
|---|---|---|
| 2604.11048 | NPTI神经元级大五人格诱导×六认知基准；效应稳定、任务依赖；提出动态人格路由DPR | **C4在静态基准≈邻近度3**；C1≈2；注意它同时占了"神经元级干预"话语 |
| 2602.12285 | 首个系统研究：人口学人格设定损害agent任务执行（稳健性/偏见框架） | C1在agentic域≈2–3，**必须精读**：它用demographic personas非策略原语，框架是偏见不是匹配优化 |
| 2603.18507 (PRISM) | 专家人格提升对齐但损害精度；意图驱动人格路由；含2023–2026正反两派文献图谱 | C1/C4≈2；其related work一节可直接作F1滚雪球起点 |
| 2604.07102 | 人格向量转向在教育应用：整体降低答案质量，任务敏感度差异达11倍 | C3副作用/steering tax证据；≈2 |
| OpenReview HpUDi5Pe8S (AAAI26 Bridge) | 用人格向量替代文本提示做长上下文人格维持；称提示法难持久且增幻觉 | C3/C7≈2 |
| 2605.20530 (AgentAtlas) | 六状态控制决策分类（行动/询问/拒绝/停止/确认/恢复）+九类轨迹失败分类 | **C5的礼物候选**：与核验/坚持/止损原语高度重叠，评估采纳 |
| Wang et al. 2026（轨迹分析survey：failure attribution to enhancement） | 轨迹分析综述已存在 | F5地图源；C5判决的必读 |
| 2605.16282 | agent安全benchmark的六轴方法学分类 | 边缘；F6方法学参照 |

**初步战略含义（待综述证伪）**：ABCR的锚点应从"人格影响任务表现"（正被圈占）移向"**人格/方向干预→轨迹级策略原语→长程任务结果的完整因果链，agentic环境，严格混淆控制**"。C6（中介链）+ C5（原语判别效度）+ C4的agentic版本，是最可能的存活细胞组合。

---

## 3. 六个检索前沿（F1–F6）

**种子集置信度标记**：〔实〕=今日检索核实过ID/来源｜〔记忆〕=出自方案作者记忆，题名/年份/venue可能有偏差，**必须API核实后才能入表**。种子集的作用是给检索冷启动加温+提供滚雪球根节点，不是完整清单——2025H2至今的增量全靠Code的查询与引用图谱扫出。

### F1 人格/角色提示 → 任务表现（映射C1、C4）

**边界**：干预=文本层人格/角色/风格提示；结果=任务表现（正确率/成功率/推理质量），不含纯风格评估。排除：纯对话质量、纯安全性研究（除非同时测任务表现）。

**种子集**：
- 〔记忆〕Zheng et al. 2024, "When 'A Helpful Assistant' Is Not Really Helpful"——162个角色、无系统性收益的关键阴性结果
- 〔记忆〕Kong et al. 2024, "Better Zero-Shot Reasoning with Role-Play Prompting" (NAACL)——阳性结果
- 〔记忆〕Xu et al. 2023, ExpertPrompting
- 〔记忆〕Salewski et al. 2023, "In-Context Impersonation..." (NeurIPS)——人格改变表现与偏差
- 〔记忆〕Gupta et al. 2024, "Bias Runs Deep" (ICLR)——社会人口学人格损害推理
- 〔记忆〕Deshpande et al. 2023, 人格指派提升毒性——副作用线
- 〔实〕2604.11048（DPR）、2603.18507（PRISM）、2602.12285（Biased Agents）、2604.07102（教育域）
- 〔记忆〕Kim et al. 2025（人格降低零样本推理）、Truong et al. 2025（提示风格致精度下降）——见PRISM引文图谱

**杀伤查询K1**：`(persona OR personality OR role prompt OR trait) AND (agent OR agentic OR tool use OR long-horizon OR multi-step) AND (task success OR performance OR reliability OR pass rate)`，限2025–2026
**杀伤查询K3**：追踪引用2604.11048的全部论文（DPR家族）+ 引用2602.12285的全部论文

**必检出探针**：Zheng 2024 helpful assistant阴性结果论文；2604.11048；2602.12285
**预期产量**：筛选60–90，入表15–20

### F2 激活转向与人格向量（映射C2、C3）

**边界**：干预=激活层（转向向量/方向注入/消融/SAE特征）；含转向副作用与可靠性批评。排除：纯权重编辑（ROME类）除非直接涉人格特质。

**种子集**：
- 〔记忆〕Chen et al. 2025, "Persona Vectors" (Anthropic)——**最近邻之王，Tier-1必precision读**：核实其结果变量是否触及任务成功率（方案作者记忆：聚焦特质表达监控与预防性转向，未做任务结果链——此记忆恰是C2/C3新颖性成立的前提，最高优先级核实）
- 〔记忆〕Zou et al. 2023, Representation Engineering；Turner et al. 2023, ActAdd；Rimsky et al. 2024, CAA (ACL)；Li et al. 2023, ITI (NeurIPS)
- 〔记忆〕Arditi et al. 2024, 拒绝行为由单一方向介导 (NeurIPS)——**投影消融+等范数随机对照的方法学源头，ABCR第二层直接进口**
- 〔记忆〕Tan et al. 2024, 转向向量的泛化与可靠性分析 (NeurIPS)——脆性证据
- 〔记忆〕Templeton et al. 2024 Scaling Monosemanticity；Gemma Scope；Todd et al. 2024 Function Vectors；Ilharco et al. 2023 Task Arithmetic
- 〔记忆〕Betley et al. 2025, Emergent Misalignment；OpenAI 2025人格特征与失配泛化跟进
- 〔记忆〕Anthropic 2025, Assistant Axis／人格回路（楠已读，提供PDF给Code入库）
- 〔记忆〕"Steering off Course" 2025——转向可靠性批评
- 〔实〕OpenReview HpUDi5Pe8S；2604.07102

**杀伤查询K2**：`(persona vector OR activation steering OR representation engineering OR steering vector) AND (task performance OR capability OR success rate OR agent)`，限2024–2026
**必检出探针**：Chen et al. persona vectors；Arditi et al. refusal direction
**预期产量**：筛选50–70，入表12–18

### F3 角色扮演一致性与漂移（映射C7、C1边界）

**边界**：角色保持、一致性评估、漂移测量。排除：角色扮演产品/数据集论文中不含测量方法学的部分。本前沿做轻量遍（预算最低），目标是C7定界+给OC项目顺带攒地图。

**种子集**：〔记忆〕Shanahan et al. 2023 (Nature)；Shao et al. 2023 Character-LLM；Wang et al. RoleLLM；Tu et al. 2024 CharacterEval；Wang et al. 2024 InCharacter（心理测量式角色访谈）；PersonaGym；人格漂移测量与控制（Li et al. 2024?）；Persona Hub (Ge et al. 2024)；〔实〕2606.14695（Persona-Pruner，其related work含2026角色扮演转向文献）

**必检出探针**：Shanahan Nature角色扮演论文；InCharacter
**预期产量**：筛选30–40，入表8–10

### F4 LLM心理测量与效度批判（映射C5的理据层）

**边界**：给LLM施测人格问卷的工作+对该范式的效度批评。**本前沿的核心猎物是"问卷-行为gap"证据**——它是ABCR选择行为测量而非自评测量的文献理据，直接写进给晓燕的作业。

**种子集**：〔记忆〕Serapio-García et al. 2023（大五在LLM的心理测量效度）；Jiang et al. 2023 MPI (NeurIPS)；Huang et al. 2024 PsychoBench (ICLR)；Röttger et al. 2024问卷范式批评 (ACL)；Dominguez-Olmedo et al., LLM问卷响应的质疑 (NeurIPS 2024)；自评量表不可靠类论文；TRAIT等人格benchmark

**必检出探针**：PsychoBench；Serapio-García 2023
**预期产量**：筛选30–40，入表8–12

### F5 Agent行为原语与长程基准（映射C5、C6、C7；ABCR结果变量的仪器库）

**边界**：四原语各设子线——核验（自纠/自评/反思）、探索（搜索策略/方案多样性）、坚持与止损（重试/放弃/过度思考）、校准（言语化置信度）；加轨迹失败分类学与长程可靠性基准。

**种子集**：
- 核验：〔记忆〕Huang et al. 2024 "LLMs Cannot Self-Correct Reasoning Yet" (ICLR)——**关键阴性结果**；Kamoi et al. 2024自纠survey (TACL)；Reflexion；Self-Refine；CRITIC
- 探索：〔记忆〕Tree of Thoughts (NeurIPS 2023)；LATS
- 坚持/止损：〔记忆〕"The Danger of Overthinking: Reasoning-Action Dilemma in Agentic Tasks" (2025)；overthinking/underthinking 2025文献
- 校准：〔记忆〕Lin et al. 2022言语化不确定性；Xiong et al. 2024 (ICLR)；〔实〕"Agentic Confidence Calibration"（2026，见VoltAgent清单）
- 基准与可靠性：〔记忆〕τ-bench（pass^k可靠性指标——**ABCR主结果指标的直接进口源**）；SWE-bench；WebArena；AgentBench；GAIA；OSWorld；TheAgentCompany；METR长任务时间跨度 (2025)
- 失败分类：〔记忆〕MAST多智能体失败分类 (2025)；〔实〕AgentAtlas 2605.20530；轨迹分析survey (Wang et al. 2026)；TrajAD；工具调用12类错误分类

**杀伤查询K4**：`(verification OR self-correction OR persistence OR give-up OR stop OR exploration OR calibration) AND (agent trajectory OR agentic behavior) AND (taxonomy OR measure OR metric)`，限2025–2026
**必检出探针**：τ-bench；AgentAtlas；Self-Correct阴性结果论文
**预期产量**：筛选60–80，入表15–20

### F6 提示干预实验方法学与评测统计（横切全部主张；喂设计v2）

**边界**：提示敏感性与格式混淆、长度/冗长混淆、LLM-as-judge效度、评测统计实践、构念效度理论。

**种子集**：〔记忆〕Sclar et al. 2024格式敏感性 (ICLR)；Mizrahi et al. 多提示评测；Zheng et al. 2023 MT-Bench与judge冗长偏差；Wang et al. 2023 "LLMs are not Fair Evaluators"（位置偏差）；Dubois et al. 2024长度控制AlpacaEval——**等长对照的方法学直接进口**；Miller 2024 "Adding Error Bars to Evals"（Anthropic）——**统计方案直接进口**；Biderman et al. 2024可复现评测经验；judge元评测类
理论锚（不检索，直接精读）：Cronbach & Meehl 1955构念效度；Messick 1995；Raji et al. 2021 benchmark构念效度批评

**杀伤查询K5**：`(mediation OR causal chain OR mechanism) AND (persona OR prompt) AND (behavior) AND (outcome OR performance)`——C6专用
**必检出探针**：Sclar 2024；length-controlled AlpacaEval；Adding Error Bars
**预期产量**：筛选40–50，入表10–15

### 术语扩展表（Code构造查询时的同义词义务）

| 概念 | 必须覆盖的变体 |
|---|---|
| 人格 | persona / personality / character / role / trait / disposition / identity / style |
| 转向 | steering / activation addition / representation engineering / inference-time intervention / activation editing / feature steering |
| 核验 | verification / self-correction / self-critique / self-refine / reflection / checking |
| 探索 | exploration / search strategy / diversity / branching |
| 坚持 | persistence / perseverance / retry / overthinking / give up / early stopping / abstention |
| 校准 | calibration / verbalized confidence / uncertainty expression / overconfidence |
| 任务结果 | task success / pass@k / pass^k / resolution rate / completion / reliability |
| 中文线索源 | 知乎/机器之心/PaperWeekly——**仅作线索，一律回溯到论文原文才可入表** |

---

## 4. 方法论：半系统化快速综述

**范式定位**：介于叙事综述与PRISMA之间。借系统综述的可复核性（预定义查询、筛选规则、溯源、饱和准则），弃其穷尽性仪式（不做双盲双筛、不注册协议）。单人+AI两周语境下的最优点。

### 4.1 流程七阶段

1. **种子核实**（D0）：本方案全部〔记忆〕条目过API，产出核实版种子表；核实失败者进隔离区
2. **查询收获**（D1–6）：六前沿查询+五条杀伤查询；检索源要求覆盖 Semantic Scholar（主源，供引用图谱）、arXiv、OpenReview、ACL Anthology；补充：楠手动Google Scholar抽查
3. **滚雪球**（D4–10）：Tier-1论文的后向引文+前向被引（S2 API）；每前沿最多两轮
4. **筛选**（滚动）：题目+摘要级；LLM预筛用保守阈值（宁可误入不可误出），边界案例进楠的每日裁决队列（目标≤15分钟/天）
5. **抽取**（D5–11）：按§4.2 schema入表；Tier-1由楠对照PDF复核关键字段
6. **聚类与综合**（D12–13）：按主张聚类，产出每主张热图与判决备忘录
7. **判决**（D14，Gate 2）

### 4.2 定位表 schema（核心产物，CSV/SQLite任选）

| 字段 | 说明 |
|---|---|
| ID / 引文（已核实）/ 年份+venue | 溯源三件套 |
| 前沿 | F1–F6 |
| 干预变量 | 操纵了什么（人格文本/方向注入/无干预观察…） |
| 对照条件 | **重点字段**：有无等长对照/中性对照/仅vanilla/无对照 |
| 结果变量 | 测什么（任务成功率/特质表达/风格/偏差…） |
| 测量方法 | judge/问卷/行为编码/基准分 |
| 模型与规模 | 开权重否、参数量 |
| 任务域 | 静态QA/推理/agentic单步/agentic长程 |
| 主要发现 | ±方向+效应量级 |
| 混淆控制质量 | 0=无 1=部分 2=严格（长度+风格+统计） |
| 相邻主张 / 邻近度 | C1–C7 / 0–3 |
| ABCR差异 | **楠亲笔填写，不得生成** |
| 可偷方法 | 对照设计/指标/量表/统计法 |
| 抽取深度+锚点 | 摘要级/全文级；引述带节号 |

### 4.3 邻近度评分（0–3）

- **3**：同问题+同类结果变量（人格/方向干预→任务结果）。例：2604.11048相对C4在静态基准
- **2**：同问题但结果变量或任务域不同。例：Persona Vectors相对C2（特质表达为果，非任务成功率——待核实）
- **1**：同域不同问题
- **0**：背景/方法工具

每主张的判决由其邻近度分布计算：存在3→REPLICATE或强EXTEND（看域差）；最高为2→EXTEND；最高≤1且饱和达标→OPEN。

### 4.4 质量门与饱和

- **引用存在性**：100%过API
- **抽取一致性**：入表行的"主要发现"须能被摘要原文支撑；Tier-1双人（Code初抽+楠复核）
- **饱和准则**：某前沿连续两轮滚雪球新增相关条目<10% **且** 探针全中 → 该前沿封闭

---

## 5. 时间节奏（14天，三道Gate）

| 天 | 动作 | 责任 |
|---|---|---|
| D0（半天） | 管线就绪；种子核实；五条杀伤查询全部跑完 | Code |
| **D2 = Gate 0** | **杀伤报告**：预检出8邻居的精确定界（各自的干预/结果变量/任务域/对照质量）+杀伤查询新发现。任何主张判邻近度3→当日重定位会（楠+方案层），先改主张再继续 | 三方 |
| D1–3 | F1、F2收获+筛选（杀伤力最高的两个前沿） | Code+楠裁边界 |
| D4–6 | F4、F5、F6收获+筛选；Tier-1滚雪球启动 | Code |
| **D7 = Gate 1** | 中期审：覆盖统计+探针清单+每主张初版热图；楠选定Tier-1精读清单（12–15篇） | 三方 |
| D8–11 | 抽取收尾；楠精读Tier-1（约2篇/天）并填"ABCR差异"列；F3轻遍 | 楠主导 |
| D12–13 | 综合：每主张判决备忘录；方法进口清单→直接并入操作化七问表；gap statement三稿 | 楠+方案层 |
| **D14 = Gate 2** | 终判：新颖性判决文档+设计v2变更清单+给晓燕作业的引用弹药打包 | 三方 |

**每日节律**：Code跑批处理；楠每日60–90分钟判断时段（边界裁决+抽取复核）；方案层（chat）在三道Gate及任何邻近度3出现时介入。
**并行提醒**：B的15条片段练习、"核验"操作化七问表初稿与本综述并行推进——F5/F6的方法进口随到随喂给那两条线，**不等D14**。

---

## 6. 三方接口契约

**方案层（本文档作者）产出**：主张与判决语义、前沿与种子、查询与探针、schema与评分规则、Gate裁决支持、邻近度3事件的重定位分析。**不产出**：代码、管线、检索实现细节。

**Code产出**：核实版种子表→收获日志（查询→数量）→筛选表→定位表→每主张热图→隔离区清单→升级清单→日报。**不产出**：新颖性结论、"ABCR差异"列内容、gap statement。

**楠产出**：C1–C7冻结令（开工前唯一前置）、每日边界裁决、Tier-1精读与差异列、gap statement亲笔三稿、三道Gate的裁决。

**升级路径**：Code→楠（当日升级规则触发）；楠→方案层（Gate或重定位需求）。

---

## 7. 执行细节核对清单

### 7.1 开工前（楠，30分钟内完成）
- [ ] C1–C7措辞冻结（这是你唯一必须先做的决定；改主张=改整个综述的靶心）
- [ ] 日历锁定14天+每日60–90分钟判断时段
- [ ] 倒排：D14产物 → 操作化方案定稿 → 发晓燕（她秋招提前批已开始，最迟D16发出）
- [ ] 把已读的Anthropic材料（Persona Vectors、Assistant Axis等）PDF交给Code入库，省一轮抓取

### 7.2 Code自检（每日）
- [ ] 引用核实率=100%；隔离区有清单有原因
- [ ] 探针状态表：已检出/未检出+解释
- [ ] 升级规则扫描已跑（persona×agent交叉命中）
- [ ] 每行有溯源；无"摘要冒充全文"的抽取深度标注缺失

### 7.3 失败模式对抗表

| 失败模式 | 对抗机制 |
|---|---|
| 引文幻觉 | §0约束1；种子集〔记忆〕标记制 |
| 检索过窄（术语变体漏检） | §3术语扩展表为查询构造义务 |
| 无限扩张 | 饱和准则+14天硬盒+每前沿产量上限 |
| 综述写成读书报告 | 判决备忘录模板：主张→邻近度分布→判决→证据行ID→设计v2含义，五段，禁叙事 |
| 只搜英文 | 中文平台线索扫描（K6），回溯原文才入表 |
| 新颖性二值化 | REPLICATE/EXTEND/OPEN三值语义强制 |
| survey依赖 | survey只作地图与滚雪球根，其断言不得直接作为主张证据 |
| 把"未检出"当"不存在" | OPEN判决的三重前置：探针全中+饱和+两轮滚雪球空手 |

---

## 8. 产物清单（D14交付）

1. **定位表**（活文档，CSV/SQLite）——40–60行已抽取条目
2. **六前沿地图**——每前沿一段150字现状描述+3–5篇代表作
3. **七份判决备忘录**（C1–C7）——含判决、证据行、设计v2含义
4. **方法进口清单**——按"进入操作化表/进入设计v2/进入统计方案"三类分拣
5. **Gap statement三稿**——楠亲笔，供晓燕与后续审稿比较
6. **给晓燕作业的引用弹药包**——问卷-行为gap证据、混淆反例文献、对照设计出处
7. **BibTeX库**——全部核实条目

---

*方案层署名：本方案的种子集与预检出邻居基于2026-07-16两次快速网络检索与方案作者训练知识（可靠截至2026年1月），其中〔记忆〕条目一律视为待核实假设。综述的最终判决权属于定位表中的证据，不属于本方案的任何预判——包括§2.4的初步战略含义。*
