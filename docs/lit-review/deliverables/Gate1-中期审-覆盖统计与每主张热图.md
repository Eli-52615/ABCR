# Gate1 中期审：覆盖统计与每主张热图（初版）

生成：2026-07-17 ｜ agent：Gate1中期审材料 ｜ 输入：定位表.csv（102行）、Gate0-杀伤报告.md、探针状态表.md、收获日志.md、Gate0结构化摘要

**口径与读表规则（先读此段）**

- 邻近度刻度（沿Gate0）：3=同问题+同类结果变量；2=同问题不同结果变量或任务域；1=同域不同问题；0=背景。
- **定位表的邻近度是行级值**：一行只有一个邻近度，对该行「相邻主张」列出的全部主张共用——它是该行对其**最近主张**的值，对其余所列主张构成**上界**而非精确值。Gate0八邻居有逐主张邻近度，本热图对这八行以Gate0逐主张值校正（合并视图）；其余94行只有行级上界。
- **§4.3机械判决规则**：存在3→REPLICATE或强EXTEND（看域差）；最高2→EXTEND；最高≤1且饱和→OPEN候选（OPEN候选须过三重前置：探针全中+饱和+滚雪球空手）。
- **最终判决权属楠，本文件全部判决倾向均为规则推导。**

---

## 1 覆盖统计

### 1.1 总量

| 指标 | 值 |
|---|---|
| 定位表总行数（不含表头） | **102**（R001–R102） |
| 上游收获漏斗 | raw 2742 → keep 329 + borderline 132 = 461 → 深抽取入定位表 102 |
| 抽取深度 | 全文级 77 ｜ 摘要级 25 |
| 升级命中 | 是 39 ｜ 否 63 |
| 行级邻近度分布 | 3级 38 ｜ 2级 38 ｜ 1级 9 ｜ 0级 17 |
| 跨前沿重复收录（异key同论文，CSV复核注自曝） | 3对：R009=R087（F1/F6）、R012=R058（F1/F3）、R013=R057（F1/F3）——**102行=99篇唯一论文** |

### 1.2 各前沿行数 vs 预期产量区间

| 前沿 | 定位表行数 | 收获keep | keep+borderline | 收获日志记载的预期区间 | 相对预期 |
|---|---|---|---|---|---|
| F1 | 26 | 32 | 48 | 未记载 | —（无区间可比） |
| F2 | 24 | 75 | 93 | 12–20 | 收获93远超预设上限20（日志注：Persona Vectors后12个月文献爆发，宁可误入）；定位表24为深抽取收敛值 |
| F3 | 10 | 30 | 45 | 未记载 | —（无区间可比） |
| F4 | 10 | 43 | 60 | 未记载 | —（无区间可比） |
| F5 | 16 | 84 | 121 | 15–25 | 收获121远超预期上限25（日志注：2026年仪器文献爆发，逐条核实非放水）；定位表16为深抽取收敛值 |
| F6 | 10 | 35 | 50 | 10–16 | 收获50超预期上限16（日志注：评测统计文献爆发，保守筛选）；定位表10为深抽取收敛值 |
| F0 | 6 | 30 | 44 | 未记载 | —（无区间可比；F0定位=只收杀伤条目） |
| **合计** | **102** | **329** | **461** | — | — |

> 预期产量区间仅F2/F5/F6在收获日志中留有记载（且为收获层keep+borderline口径、非定位表口径）；F1/F3/F4/F0的预期区间未随输入提供，无法比对——此为覆盖统计的已知盲区，如楠手中有各前沿定位表配额，请以其为准补对。

### 1.3 任务域分布（关键词机械分桶）

| 任务域桶 | 行数 |
|---|---|
| 纯静态QA/问卷/评测方法学 | 38 |
| agentic长程 | 25 |
| agentic其他（+静态混合） | 15 |
| agentic单步~短程 | 7 |
| agentic多步/多轮 | 5 |
| 多轮对话(非agentic) | 4 |
| agentic其他 | 3 |
| agentic具身 | 2 |
| agentic长程（+静态混合） | 2 |
| 序贯决策（+静态混合） | 1 |
| **合计** | **102** |

> agentic/序贯类合计60行、纯静态/问卷/方法学38行、多轮对话(非agentic)4行。分桶为任务域字段的关键词机械归类，混合域按agentic优先计。

### 1.4 年份分布（×前沿）

| 年份 | F1 | F2 | F3 | F4 | F5 | F6 | F0 | 合计 |
|---|---|---|---|---|---|---|---|---|
| 2023 | 1 | 0 | 0 | 0 | 0 | 2 | 0 | 3 |
| 2024 | 1 | 1 | 2 | 0 | 0 | 2 | 0 | 6 |
| 2025 | 13 | 3 | 6 | 3 | 0 | 4 | 2 | 31 |
| 2026 | 11 | 20 | 2 | 7 | 16 | 2 | 4 | 62 |

> 2025+2026合计93/102（91%）；F5全部16行为2026年——行为原语仪器线是纯新生领域；2023–2024的9行为奠基/方法学锚（Salewski、Zheng、Li指令漂移、Sclar、Miller、Dubois等）。

### 1.5 混淆控制质量分布（×前沿）

| 前沿 | 质量2(严对照) | 质量1(部分) | 质量0(无/不适用) | 小计 |
|---|---|---|---|---|
| F1 | 7 | 19 | 0 | 26 |
| F2 | 8 | 16 | 0 | 24 |
| F3 | 3 | 7 | 0 | 10 |
| F4 | 6 | 3 | 1 | 10 |
| F5 | 1 | 13 | 2 | 16 |
| F6 | 3 | 4 | 3 | 10 |
| F0 | 2 | 4 | 0 | 6 |
| **合计** | **30** | **66** | **6** | **102** |

> 质量2仅30/102（29%）：全场2/3的近邻文献对照不严（无等长中性对照/无统计检验/无安慰剂方向）——这本身就是ABCR「严格对照」卖点的量化依据。质量0共6行均为survey/元评测/批判类（R070/R072/R074/R093/R094/R096），不适用对照概念。

### 1.6 每主张触及行数×行级邻近度总矩阵

| 主张 | 触及行数 | 3级 | 2级 | 1级 | 0级 | Gate0八邻居内该主张最高（逐主张口径） |
|---|---|---|---|---|---|---|
| C1 | 46 | 21 | 15 | 3 | 7 | 3（2602.12285，宽口径） |
| C2 | 12 | 7 | 4 | 1 | 0 | 2（2604.11048 / 2604.07102） |
| C3 | 29 | 18 | 11 | 0 | 0 | 2（同左） |
| C4 | 33 | 18 | 9 | 1 | 5 | 3（2604.11048，静态） |
| C5 | 38 | 9 | 15 | 5 | 9 | 2（AgentAtlas） |
| C6 | 8 | 2 | 0 | 1 | 5 | 1（相关性/口头机制/工程归因） |
| C7 | 20 | 10 | 8 | 0 | 2 | 2（HpUDi5Pe8S，名义占位） |

---

## 2 每主张初版热图（C1–C7）

每节含：触及行全表（行级邻近度降序）→ 邻近度分布条形图 → Gate0合并视图 → §4.3机械判决推导。**最终判决权属楠。**

⚠️ 热图计数单位=定位表**行**而非论文：3对异key同论文（R009=R087、R012=R058、R013=R057）未去重——主张节内同论文双计：**C1同现1对**（R009=3/R087=2），**C4与C7各同现2对**（R012=3/R058=2、R013=3/R057=2），读条形图时按论文数应相应扣减；同一论文两侧邻近度不一致（3 vs 2）本身也是抽取口径需楠仲裁的点。

### C1（触及46行）

> 主张锚：重定位后口径（Gate0材料）：特质级人格干预（prompt+激活双通道）在等长中性对照与统计检验下对agentic任务成功率的因果效应及其行为原语中介。

| ID | 引文短式 | 邻近度(行级) | 任务域 | 一句发现 |
|---|---|---|---|---|
| R001 | Chen 2026《A Systematic Analysis of the Impact of Persona…》 | 3 | 静态QA/推理 | 效应强任务依赖且跨架构可复现:IFEval所有人格+10.9%~+15.1%(SA≈0.98),BBH所有人格下降(E_L最重-39.5%,SA=1.00) |
| R002 | Hu 2026《Expert Personas Improve LLM Alignment but Dama…》 | 3 | 静态QA/生成+安全 | 任务型二分:预训练依赖任务一致受损(MMLU 68.0%vs基线71.6%,长人格66.3%更重 |
| R003 | Cao 2026《From Biased Chatbots to Biased Agents: Examini…》 | 3 | agentic长程(多步规划/具身/系统操作) | 人口学人格致agent性能系统性波动,最大-26.2%(DeepSeek V3 Card Game,'from Africa'人格) |
| R004 | Kim 2026《Persona Switch: Mixing Distinct Perspectives i…》 | 3 | 静态推理QA | 单用role-play常逊于zero-shot(如LLaMA-3.1-8B平均67.6%vs贪心69.7%),但两策略实例级对错互补(Fig.1) |
| R005 | Keluskar 2026《When Does Personality Composition Matter for M…》 | 3 | agentic多agent长程(编码协作/研究协作/买卖谈判… | 低宜人性使沟通全域同向剧变(φ0.44→0.93,p<0.003,d最大-12.39)但结果效应依任务结构:编码milestone 3/4模型无显著变化(仅… |
| R006 | Abdullahi 2026《The Persona Paradox: Medical Personas as Behav…》 | 3 | 静态QA(临床分诊1667例)+开放生成(PatientSa… | 系统性、情境依赖且非单调:医疗人格在急诊分诊约+20pp准确率与校准改善(部分统计显著),初级保健反降约10pp、部分小模型一致性-20pp,聚合后相互抵消 |
| R007 | Wu 2026《Persona Matters: Effects of Activation Steerin…》 | 3 | 静态QA(教育短答生成与自动评分,ASAP-SAS 10个p… | 人格转向整体降低答案质量:Qwen3-4B平均∣Δ∣=0.172(humorous -0.420),gpt-oss-20b evil -0.443,Qwen… |
| R008 | Kim 2025《Persona is a Double-edged Sword: Mitigating th…》 | 3 | 静态推理QA(零样本) | persona提示在llama3上12个数据集中7个降低推理准确率 |
| R009 | Basil 2025《Prompting Science Report 4: Playing Pretend: E…》 | 3 | 静态QA(研究生级多选事实/推理题,零样本) | 同域专家persona普遍无显著增益(GPQA无一模型获益 |
| R010 | Duan 2025《The Power of Personality: A Human Simulation P…》 | 3 | 静态QA+开放创造生成+多agent辩论协作(三段式讨论) | 神经质得分与闭任务准确率跨任务跨模型普遍显著负相关(Qwen-14B五任务全显著) |
| R011 | Ruangtanusak 2025《Talk Less, Call Right: Enhancing Role-Play LLM…》 | 3 | agentic单步(多轮角色扮演对话,每轮至多一次函数调用) | 规则化角色提示RRP综合分0.571 vs zero-shot基线0.519(Task1 0.531 vs 0.442),优于APO(0.538)与人工改进… |
| R012 | Suresh 2025《Two-Faced Social Agents: Context Collapse in R…》 | 3 | 静态QA/推理(SAT数学28题,复制54题)+主观偏好问卷… | 认知负载下人格效应任务依赖性坍缩：GPT-5完全坍缩(SAT全对100%,PERMANOVA p=1.000,R²=0.0004)、Gemini部分坍缩(p… |
| R013 | Luz de Araujo et al. 2025《Persistent Personas? Role-Playing, Instruction…》 | 3 | 长程多轮对话(100+轮,长于99.99%的WildChat… | 人格保真随对话推进持续衰减(知识/风格/一致性三指标均降,目标导向对话更甚) |
| R014 | He et al. 2025《Impatient Users Confuse AI Agents: High-fideli…》 | 3 | agentic长程(多轮工具调用客服域：航空/零售/电信/远… | 用户trait向量注入使前沿agent成功率平均降4-20%(摘要口径) |
| R015 | Zheng et al. 2024《When "A Helpful Assistant" Is Not Really Helpf…》 | 3 | 静态QA(MMLU事实问答) | 162人格 vs 无角色对照均无统计显著提升，部分人格反而显著更差(如Mistral的ecologist) |
| R016 | Salewski et al. 2023《In-Context Impersonation Reveals Large Languag…》 | 3 | 序贯决策(两臂bandit,10试次×2k局/年龄)+静态Q… | 年龄人格系统性改变探索策略：扮演越年长探索越少(β=-0.03,p<.001)、利用越多(β=0.04,p<.001)、平均奖励随扮演年龄升至20岁(β=0… |
| R039 | Qian 2026《Nous: An Attempt to Extract and Inject the Cog…》 | 3 | agentic长程预测(ReAct式研究→预测,post-c… | 解离:提取部分有效(8/14参数split-half ICC≥0.5,contrarian ICC≈0.9 |
| R041 | Dabas 2026《Memory-Induced Tool-Drift in LLM Agents》 | 3 | agentic单步（每场景单次工具调用，7个专业域105场景… | 偏置记忆使deflection最高提升+3.6/5，7个前沿模型（含扩展推理）全部大幅漂移而中性对照分持续低 |
| R051 | Safder 2026《FinPersona-Bench: A Benchmark for Longitudinal…》 | 3 | agentic长程（200步序贯交易决策） | MSD（mandate显著性衰减）随时间复合且依模型而异 |
| R098 | Ding 2026《ContextEcho: A Benchmark for Persona Drift in …》 | 3 | agentic长程（数千轮编码会话）+下游无工具chat与S… | 17/23目标漂移差∣Δ∣≥0.30（范围−0.15~+1.00 |
| R099 | Handa 2025《Personality as a Probe for LLM Evaluation: Met…》 | 3 | 静态QA/推理（MMLU、BBQ）+agent基准（GAIA… | ICL对齐强且能力损失最小（Gemma ΔMMLU≈−0.06~−0.08，ΔGAIA还+0.06~+0.09） |
| R017 | Cho 2026《A Concise Agent is Less Expert: Revealing Side…》 | 2 | 对话生成单轮响应(任务型LMSYS-Chat-1M+日常Da… | 风格特征深度纠缠而非正交:提示Concise使感知Expert win率降至25.6%、Helpful 23.2% |
| R018 | Zhang et al. 2026《Guardrails Beat Guidance: A Large-Scale Study …》 | 2 | agentic长程(SWE-bench Verified真实… | 7种规则条件均优于无规则基线(50.0%)+6.9~13.8pp(方向符号检验p=0.008)但条件间无显著差异(Q=4.70,p=0.697)：随机规则=… |
| R019 | Jiang 2025《HARBOR: Exploring Persona Dynamics in Multi-Ag…》 | 2 | agentic多轮竞争（多agent拍卖，10-15件物品逐… | 人格注入使agent偏离利润最大化：无人格Master利润率34.56%为最高，Master带人格降至31.75%，全员同人格时平均利润率从29.23%降至… |
| R020 | Potertì 2025《Designing Role Vectors to Improve LLM Inferenc…》 | 2 | 静态QA（MMLU多选） | 较大模型上角色向量提升目标域及相关域准确率、无关域微降或不变（如mathematician向量提升Qwen-7B数学与EECS） |
| R021 | Wang 2025《Improving LLM Reasoning through Interpretable …》 | 2 | 静态QA/推理 | 转向在25/27设置优于vanilla、17/27优于role-play提示 |
| R022 | Hachalli Karanam 2025《Multi-Agent LLM Committees for Autonomous Soft…》 | 2 | agentic长程（多轮web应用测试，截图+浏览器操作） | 多agent委员会任务成功率91.7-100% vs 单agent 78.0%（+13.7-22.0pp，p<0.01） |
| R023 | Xiao 2026《When Does Persona Prompting Actually Help? A R…》 | 2 | 静态开放式QA(1140题, 38角色×6域, 咨询/概念两… | 聚合差异极小(全部d<0.12, baseline均分4.390 vs hybrid 4.382)但维度分解现系统tradeoff: 角色提示升专业深度(h… |
| R024 | Klang 2026《Personas Shift Clinical Action Thresholds in L…》 | 2 | 静态临床决策vignette(单步二元判断) | 基线肯定率42.8% |
| R025 | Luz de Araujo 2025《Principled Personas: Defining and Measuring th…》 | 2 | 静态QA/推理/数学(多选+开放式, 全部客观可判) | 专家人格多为正向或不显著(成功率78-100% |
| R057 | Luz de Araujo 2025《Persistent Personas? Role-Playing, Instruction…》 | 2 | 多轮对话条件化的静态QA/指令基准（100+轮对话前缀+五数… | 保真三指标（知识/风格/入戏）随轮次一致衰减且目标导向对话更陡 |
| R058 | Suresh 2025《Two-Faced Social Agents: Context Collapse in R…》 | 2 | 静态QA/推理(SAT数学28/54题)+问卷式偏好任务(单… | 任务依赖性语境塌缩:GPT-5在SAT上完全趋同(全persona 100%准确,PERMANOVA p=1.000,R²=0.0004),Gemini部分… |
| R062 | Slama et al. 2026《When Do LLM Preferences Predict Downstream Beh…》 | 2 | 静态QA（BoolQ）+agentic长程（GAIA L1、… | 偏好强预测建议(ρ=.94-.98)与拒答(ρ=.57-.83)且无需指令自发出现 |
| R063 | Han et al. 2025《The Personality Illusion: Revealing Dissociati…》 | 2 | 静态QA/行为探测任务（单步、非agentic） | 自评-行为方向对齐率45-62%，95%CI均与50%机会水平重叠 |
| R087 | Basil 2025《Prompting Science Report 4: Playing Pretend: E…》 | 2 | 静态QA（GPQA Diamond 198题；MMLU-Pr… | 6模型×2基准：专家人格总体无显著增益且显著变化更常为负 |
| R102 | Fitz 2025《Psychometric Personality Shaping Modulates Cap…》 | 2 | 静态QA | 低Conscientiousness灾难性：三模型安全任务−20~−40pp且MMLU大幅下降 |
| R026 | Le Truong 2025《Persona-Augmented Benchmarking: Evaluating LLM…》 | 1 | 静态QA/常识推理/代码生成 | 语义等同下风格改写显著改变测得成绩: 最好vs最差人格子集平均差20/11/28pp(CoQA/CosmosQA/DS-1000) |
| R088 | Sclar et al. 2023《Quantifying Language Models' Sensitivity to Sp…》 | 1 | 静态QA/分类few-shot | 格式微扰致最高76个准确点的性能差 |
| R089 | Mizrahi et al. 2023《State of What Art? A Call for Multi-Prompt LLM…》 | 1 | 静态QA/推理基准 | 不同指令模板导致非常不同的绝对与相对性能 |
| R090 | Messing 2026《Hidden Measurement Error in LLM Pipelines Dist…》 | 0 | 静态QA评测管线（MMLU、Chatbot Arena） | naive标准误比TEE校正SE小40-60% |
| R091 | Bjarnason 2026《On Randomness in Agentic Evals》 | 0 | agentic长程（SWE-Bench软件修复轨迹） | 单次运行pass@1随所选运行漂移2.2-6.0pp，temp=0下SD仍>1.5pp |
| R092 | Hua 2025《Flaw or Artifact? Rethinking Prompt Sensitivit…》 | 0 | 静态QA/推理（6基准，多选+开放式） | 大部分提示敏感性源于启发式评测方法（对数似然、刚性匹配漏判同义正确答案） |
| R093 | Sida Wang 2025《Measuring all the noises of LLM Evals》 | 0 | 静态QA/基准评测(元评测) | 每个eval表现出特征性、可预测的总噪声水平 |
| R094 | Mustahsan et al. 2025《Stochasticity in Agentic Evaluations: Quantify…》 | 0 | agentic长程(GAIA)+多跳检索推理QA(FRAME… | ICC=0.30–0.77随模型/任务变化 |
| R095 | Dubois et al. 2024《Length-Controlled AlpacaEval: A Simple Way to …》 | 0 | 静态指令跟随对话评测(元评测) | 长度控制后对冗长度操纵显著更稳健 |
| R096 | Miller 2024《Adding Error Bars to Evals: A Statistical Appr…》 | 0 | 评测方法学(跨任务通用) | 给出evals-as-experiments的统计公式集：成对分析降方差、聚类标准误处理题目非独立、功效分析定样本量 |

**邻近度分布（行级）**

```
3 │ █████████████████████ 21
2 │ ███████████████ 15
1 │ ███ 3
0 │ ███████ 7
```

**Gate0合并视图（⚠️警报1挂此主张）**

| 项 | 内容 |
|---|---|
| 警报1本体 | R003 = arXiv:2602.12285《From Biased Chatbots to Biased Agents》，Gate0宽口径C1:3（同问题+同类结果变量：persona指派→agentic多步成功率；5基准×3模型，最大−26.2%，自称first systematic case study）。定位表与Gate0**一致**（相邻主张=C1，行级3）——两级证据合并后此3为**确证3** |
| R003边界=C1活路（Gate0原文四条） | ①仅人口学persona非特质；②仅vanilla对照，无等长中性对照、无统计检验；③仅基准级聚合，无行为粒度；④偏见框架，无匹配-优化方向 |
| Gate0逐主张校正 | R001 C1:2、R002 C1:1、R007 C1:1——这三行在定位表的行级3由C4（R001/R002）与C2/C3（R007）驱动，读C1列时应按Gate0逐主张值降读 |
| 定位表新增的agentic域C1近邻（Gate0八邻居之外） | R014（用户侧trait向量→agent成功率−4~−20%）、R041（偏置记忆→工具漂移）、R005（人格构成×多agent长程）、R039、R051、R098、R011——宽口径C1现象层在agentic域已非R003一家 |
| 静态域prox3证据带 | R004/R006/R008/R009/R010/R012/R015/R016等：同问题不同任务域的密集先行证据，域差=agentic |
| 写作纪律脚注（Gate0） | PsySafe（黑暗人格注入→多agent危险率98–100%，经邻居#8编目）**未入定位表**——C1终稿仍须显式切割「任务成功率」vs「安全危险率」两类结果变量，此纪律须从Gate0杀伤报告直接带入（见§3.3缺口） |

**机械判决推导（§4.3规则）**：存在3（R003，Gate0确证+定位表一致）→ 规则输出「REPLICATE 或 强EXTEND，看域差」。域差核对：人格类型（人口学vs特质）、对照严格度（vanilla vs 等长中性+统计检验）、粒度（聚合分vs行为原语中介）三项域差均实在 → 机械落点 = **强EXTEND**（按Gate0重定位口径重述）。**最终判决权属楠，此为规则推导。**

---

### C2（触及12行）

> 主张锚：方向/激活干预→任务表现线（C2、C3均映射F2；两者的区分口径未在本次输入中给出，按Gate0脚注以「剂量-反应」「agentic任务成功率」为两大剩余要素）。

| ID | 引文短式 | 邻近度(行级) | 任务域 | 一句发现 |
|---|---|---|---|---|
| R027 | Lu 2026《The Assistant Axis: Situating and Stabilizing …》 | 3 | 多轮对话（15轮合成对话4域）+静态基准；非agentic | 治疗与AI哲学类对话稳定诱发漂移（编码/写作不漂） |
| R029 | Herrmann 2026《Do LLMs Experience an Internal Polylogue? Inve…》 | 3 | 静态QA/推理(MMLU-Pro, 非agentic) | polylogue(人格方向对齐时间序列)特征预测正确率匹配随机投影并接近激活基线(AUC 0.59-0.87) |
| R031 | Pinto 2026《Present but Rescaled: Chat-to-Agent Transfer o…》 | 3 | agentic多步(ReAct工具调用episode)vs单… | 转移真实但被重标定且解离: 注入方向在agent端近满强度存活(install-site比0.83-1.16), 行为耦合却按模型/语境重置, T从0.43… |
| R033 | Sui 2026《TACT: Mitigating Overthinking and Overacting i…》 | 3 | agentic长程(编码/终端agent, 数十至上百步轨迹… | OT/OA/CAL步隐状态沿两漂移轴线性可分(AUC≈0.9, OT-vs-CAL峰值0.91@层3, 信号集中于早中层) |
| R036 | Bas 2025《What Can We Actually Steer? A Multi-Behavior S…》 | 3 | 静态QA(单轮评测prompt,每行为1000条) | 特质表达随转向系数呈倒U(中低系数峰值后下降),连贯/相关单调崩塌(转向下相关性44.0、连贯49.3 vs prompting约79-88) |
| R041 | Dabas 2026《Memory-Induced Tool-Drift in LLM Agents》 | 3 | agentic单步（每场景单次工具调用，7个专业域105场景… | 偏置记忆使deflection最高提升+3.6/5，7个前沿模型（含扩展推理）全部大幅漂移而中性对照分持续低 |
| R097 | Yap 2026《Behavioral Steering in a 35B MoE Language Mode…》 | 3 | agentic单步~短程（ReAct式≤5轮，预缓存工具响应… | autonomy转向α=2达d(pro)=+1.01(p<0.0001,CI[+0.60,+1.43])，ask_user占比78%→5% |
| R020 | Potertì 2025《Designing Role Vectors to Improve LLM Inferenc…》 | 2 | 静态QA（MMLU多选） | 较大模型上角色向量提升目标域及相关域准确率、无关域微降或不变（如mathematician向量提升Qwen-7B数学与EECS） |
| R042 | Zeng 2026《What Models Express, Suppress, and Resist: Aud…》 | 2 | 静态单轮引出prompt(agentic特质亦以单轮评测) | 9个agentic特质在两模型均为natural(基线即高表达,域均值增益仅3.78/2.42,转向增益最小)——agentic行为是默认模式而非可拨动方向 |
| R044 | Yi 2026《Latent Agents: A Post-Training Procedure for I…》 | 2 | 静态推理QA(多步数学/多域知识/BBH;辩论仅内化不实际多… | IMAD以Debate 6.3-21.1%的token匹敌或超越显式辩论(Mistral GSM8K +18.97pp) |
| R049 | Courtis 2026《Mechanistic Personality Analysis of LLMs: Stee…》 | 2 | 静态文本生成（状态更新/日志体）+静态QA（MMLU） | 判别率分特质分化：尽责94%(LLM)/98%(人)、神经质92%/95%可靠检出，外向74%/65%、宜人78%/58%中等，开放性仅50%/30%难以转… |
| R050 | Shou 2026《Mechanistic Decoding of Cognitive Constructs i…》 | 1 | 静态判断任务(社会比较情境),非agentic;讨论指向多a… | 8个LLM将嫉妒原生编码为两前因的结构化线性组合,与人类心理构念一致:优越性为基础触发、相关性为最终强度乘数 |

**邻近度分布（行级）**

```
3 │ ███████ 7
2 │ ████ 4
1 │ █ 1
0 │ · 0
```

**Gate0合并视图**

| 项 | 内容 |
|---|---|
| Gate0八邻居内C2最高 | 2（R001 C2:2、R007 C2:2，均静态域）。注意：这两行的C2标注在定位表「相邻主张」列**缺失**（R001=C1/C3/C4，R007=C1/C3/C4/C5）——见§3.3补录建议 |
| 定位表抽取后 | 出现7个行级3，**全部是Gate0八邻居之外的新邻居**：R027（Assistant Axis：轴投影漂移监测+activation capping）、R029（polylogue段落条件化转向）、R031（chat→agent转移：方向近满强度存活但行为耦合被重标定）、R033（TACT：OT/OA步隐状态线性可分）、R036（可转向性审计：特质表达倒U+连贯单调崩塌）、R041（记忆诱导工具漂移）、R097（35B MoE autonomy转向，agentic+效应量CI） |
| Gate0脚注预警的兑现 | 脚注原文：C2/C3表述若不含「剂量-反应/agentic」二要素之一会滑向3——定位表证实**已滑向3**：R097（agentic域+统计检验）与R031（agentic转移标定）直接压在C2剩余空间上 |
| 残余域差 | R097为单步~短程ReAct、结果变量为行为占比(ask_user 78%→5%)非长程任务成功率；R031的结论「转移被重标定且解离」反而使剂量标定在agentic域成为必做题；R036连贯崩塌为静态单轮 |

**机械判决推导（§4.3规则）**：存在3（定位表行级，非Gate0确证）→「REPLICATE 或 强EXTEND，看域差」。域差=agentic**长程**×**任务成功率**×剂量-反应曲线的整链仍无行占据，但C2是抽取后邻近度上升最快的主张之一 → 机械落点 = **强EXTEND**，并建议楠优先复核R097/R031全文后再定REPLICATE与否。**最终判决权属楠，此为规则推导。**

---

### C3（触及29行）

> 主张锚：方向/激活干预→任务表现线（同C2注；C3侧重特质向量干预通道本身，Gate0脚注：表述若不含剂量-反应/agentic二要素之一会滑向3）。

| ID | 引文短式 | 邻近度(行级) | 任务域 | 一句发现 |
|---|---|---|---|---|
| R001 | Chen 2026《A Systematic Analysis of the Impact of Persona…》 | 3 | 静态QA/推理 | 效应强任务依赖且跨架构可复现:IFEval所有人格+10.9%~+15.1%(SA≈0.98),BBH所有人格下降(E_L最重-39.5%,SA=1.00) |
| R007 | Wu 2026《Persona Matters: Effects of Activation Steerin…》 | 3 | 静态QA(教育短答生成与自动评分,ASAP-SAS 10个p… | 人格转向整体降低答案质量:Qwen3-4B平均∣Δ∣=0.172(humorous -0.420),gpt-oss-20b evil -0.443,Qwen… |
| R014 | He et al. 2025《Impatient Users Confuse AI Agents: High-fideli…》 | 3 | agentic长程(多轮工具调用客服域：航空/零售/电信/远… | 用户trait向量注入使前沿agent成功率平均降4-20%(摘要口径) |
| R027 | Lu 2026《The Assistant Axis: Situating and Stabilizing …》 | 3 | 多轮对话（15轮合成对话4域）+静态基准；非agentic | 治疗与AI哲学类对话稳定诱发漂移（编码/写作不漂） |
| R028 | 匿名(OpenReview) 2026《Steering LLM Interactions Using Persona Vector…》 | 3 | 长上下文对话 | 据web核实梗概：提示法短期可产生人格一致回应但很少诱发持续行为改变、且常提高幻觉率 |
| R029 | Herrmann 2026《Do LLMs Experience an Internal Polylogue? Inve…》 | 3 | 静态QA/推理(MMLU-Pro, 非agentic) | polylogue(人格方向对齐时间序列)特征预测正确率匹配随机投影并接近激活基线(AUC 0.59-0.87) |
| R030 | Sun 2026《Persona Vectors in Games: Measuring and Steeri…》 | 3 | agentic单步(一次性/含历史vignette博弈决策,… | 正向利他转向系统性提高慷慨行为(Dictator给钱$15@β=0→$55@β=3)并改变言辞框架(utility/payoff/kind词频随β系统变化) |
| R031 | Pinto 2026《Present but Rescaled: Chat-to-Agent Transfer o…》 | 3 | agentic多步(ReAct工具调用episode)vs单… | 转移真实但被重标定且解离: 注入方向在agent端近满强度存活(install-site比0.83-1.16), 行为耦合却按模型/语境重置, T从0.43… |
| R032 | Zhao 2026《Neural Procedural Memory: Empowering LLM Agent…》 | 3 | agentic长程(具身家务/网购/科学实验/网格导航多步交… | NPM较无记忆平均提升(MiniCPM 22.60→28.87, Qwen3-8B 30.63→36.32), 明显超静态转向基线CAA/Mass-Mean… |
| R033 | Sui 2026《TACT: Mitigating Overthinking and Overacting i…》 | 3 | agentic长程(编码/终端agent, 数十至上百步轨迹… | OT/OA/CAL步隐状态沿两漂移轴线性可分(AUC≈0.9, OT-vs-CAL峰值0.91@层3, 信号集中于早中层) |
| R034 | Lin 2026《On Emotion-Sensitive Decision Making of Small …》 | 3 | agentic单步为主(博弈决策, 含多轮/多智能体/多模态… | 情绪转向系统性移动策略选择(Mean_Emotions NDM远超随机向量对照, 如Llama-1B 0.393 vs 0.006), 且随α单调放大 |
| R035 | Ong 2025《Identifying Cooperative Personalities in Multi…》 | 3 | agentic多轮博弈(10轮迭代囚徒困境,含通信与双ste… | 宜人/尽责/开放+转向使捣乱率中位数降至0.00 |
| R036 | Bas 2025《What Can We Actually Steer? A Multi-Behavior S…》 | 3 | 静态QA(单轮评测prompt,每行为1000条) | 特质表达随转向系数呈倒U(中低系数峰值后下降),连贯/相关单调崩塌(转向下相关性44.0、连贯49.3 vs prompting约79-88) |
| R037 | Rahn 2024《Controlling Large Language Model Agents with E…》 | 3 | agentic多轮(双臂高斯bandit,ReAct逐轮交互… | EAST随乘子增大显著提升动作熵、缓解agent过早收敛于单臂的过度自信(温度采样对动作熵几乎无效) |
| R038 | Herbster 2026《Activation Steering for Aligned Open-ended Gen…》 | 3 | 开放式单轮/多轮生成(5-10轮自弈)+多agent长程(A… | 全方法恢复trait(诚实62-77,共情71-78,coherence 87-95) |
| R040 | Wang 2026《ASA: Backbone-Training-Free Representation Eng…》 | 3 | agentic工具调用: NESTFUL嵌套多步依赖序列+B… | 意图-执行鸿沟实证: 中层线性探针可读工具必要性(AUC≈0.84)且高探针分桶边界进入率97-100%, 但严格可执行成功仅20-25% |
| R097 | Yap 2026《Behavioral Steering in a 35B MoE Language Mode…》 | 3 | agentic单步~短程（ReAct式≤5轮，预缓存工具响应… | autonomy转向α=2达d(pro)=+1.01(p<0.0001,CI[+0.60,+1.43])，ask_user占比78%→5% |
| R099 | Handa 2025《Personality as a Probe for LLM Evaluation: Met…》 | 3 | 静态QA/推理（MMLU、BBQ）+agent基准（GAIA… | ICL对齐强且能力损失最小（Gemma ΔMMLU≈−0.06~−0.08，ΔGAIA还+0.06~+0.09） |
| R020 | Potertì 2025《Designing Role Vectors to Improve LLM Inferenc…》 | 2 | 静态QA（MMLU多选） | 较大模型上角色向量提升目标域及相关域准确率、无关域微降或不变（如mathematician向量提升Qwen-7B数学与EECS） |
| R021 | Wang 2025《Improving LLM Reasoning through Interpretable …》 | 2 | 静态QA/推理 | 转向在25/27设置优于vanilla、17/27优于role-play提示 |
| R042 | Zeng 2026《What Models Express, Suppress, and Resist: Aud…》 | 2 | 静态单轮引出prompt(agentic特质亦以单轮评测) | 9个agentic特质在两模型均为natural(基线即高表达,域均值增益仅3.78/2.42,转向增益最小)——agentic行为是默认模式而非可拨动方向 |
| R044 | Yi 2026《Latent Agents: A Post-Training Procedure for I…》 | 2 | 静态推理QA(多步数学/多域知识/BBH;辩论仅内化不实际多… | IMAD以Debate 6.3-21.1%的token匹敌或超越显式辩论(Mistral GSM8K +18.97pp) |
| R045 | Xuan 2026《After Talking with 1,000 Personas: Learning Pr…》 | 2 | agentic主动助手交互(何时介入+如何响应,100次机会… | 设备端激活转向≈DPO:平均TAI 0.875 vs 0.900,IQA 0.936 vs 0.938 |
| R046 | Miao 2026《Contrastive Conceptor Activation Steering (COA…》 | 2 | 具身agentic:短程单物操纵到长程多步操纵(LIBERO… | 仿真平均绝对成功率+20.2pp(π0.5 MetaWorld 0.57→0.82、LIBERO 0.43→0.80,均p<.001 |
| R047 | Haon 2025《Mechanistic interpretability for steering visi…》 | 2 | 具身agentic:LIBERO 10个长程任务(每任务10… | fast簇较slow簇平均增大末端位移27.73%(最高148.54%),10/10配对比较p<0.001(d=-0.091~1.419) |
| R048 | Kumaran 2026《Causal Evidence that Language Models use Confi…》 | 2 | 静态多选事实QA(SimpleQA转4选, 1000题主实验… | 置信转向因果改变弃答: 最大低置信转向弃答66.5%→最大高置信7.0%(59.5pp摆幅, r=-0.99, p<0.001, 基线28.2%), 效应随… |
| R049 | Courtis 2026《Mechanistic Personality Analysis of LLMs: Stee…》 | 2 | 静态文本生成（状态更新/日志体）+静态QA（MMLU） | 判别率分特质分化：尽责94%(LLM)/98%(人)、神经质92%/95%可靠检出，外向74%/65%、宜人78%/58%中等，开放性仅50%/30%难以转… |
| R100 | Subbiah 2026《On the Limits of Steering Vectors for Preferen…》 | 2 | 静态NLG（摘要125题+邮件写作100题，写作个性化） | 转向效力随特质差异巨大：结构/风格整体性特质(bullets/formal tone等)最有效，非常规修辞(rhyming/tweet style等)最差且… |
| R102 | Fitz 2025《Psychometric Personality Shaping Modulates Cap…》 | 2 | 静态QA | 低Conscientiousness灾难性：三模型安全任务−20~−40pp且MMLU大幅下降 |

**邻近度分布（行级）**

```
3 │ ██████████████████ 18
2 │ ███████████ 11
1 │ · 0
0 │ · 0
```

**Gate0合并视图**

| 项 | 内容 |
|---|---|
| Gate0八邻居内C3最高 | 2（R001 C3:2、R007 C3:2；R028 C3:1） |
| 定位表抽取后 | 18个行级3，agentic域新邻居密集：R014（TraitBasis：对比激活差提取trait方向+剂量缩放+线性组合——C3式方法已在**用户模拟器侧**做完）、R030（利他转向剂量β=0→3，Dictator $15→$55）、R032（程序性记忆胜静态转向CAA）、R034（情绪转向×强度缩放）、R035（合作人格转向IPD捣乱率→0）、R037（EAST动作熵随乘子提升）、R038、R040（ASA意图-执行鸿沟）、R097 |
| 剂量-反应半边现状 | R014与R030已含剂量梯度、R034含强度缩放、R097含统计检验——「剂量」要素在agentic近域已被多点触及；未被占的是「特质向量×长程任务成功率×剂量曲线」的**整链** |
| 扰动论必答题（Gate0脚注） | R007「steering behaves like perturbation, not style control」+ R036倒U/连贯崩塌：ABCR若主张方向干预可**优化**任务表现，必须直面扰动论并给出正向利用条件 |

**机械判决推导（§4.3规则）**：存在3 →「REPLICATE 或 强EXTEND，看域差」。域差=整链组合而非任一环节 → 机械落点 = **强EXTEND**（每个环节都有近邻，主张必须以链为单位重述，单环节表述会撞车）。**最终判决权属楠，此为规则推导。**

---

### C4（触及33行）

> 主张锚：重定位后口径（Gate0材料）：长程agentic任务中的人格×任务(×阶段)交互结构 + 基于行为原语反馈的过程内(mid-trajectory)自适应人格调度。

| ID | 引文短式 | 邻近度(行级) | 任务域 | 一句发现 |
|---|---|---|---|---|
| R001 | Chen 2026《A Systematic Analysis of the Impact of Persona…》 | 3 | 静态QA/推理 | 效应强任务依赖且跨架构可复现:IFEval所有人格+10.9%~+15.1%(SA≈0.98),BBH所有人格下降(E_L最重-39.5%,SA=1.00) |
| R002 | Hu 2026《Expert Personas Improve LLM Alignment but Dama…》 | 3 | 静态QA/生成+安全 | 任务型二分:预训练依赖任务一致受损(MMLU 68.0%vs基线71.6%,长人格66.3%更重 |
| R004 | Kim 2026《Persona Switch: Mixing Distinct Perspectives i…》 | 3 | 静态推理QA | 单用role-play常逊于zero-shot(如LLaMA-3.1-8B平均67.6%vs贪心69.7%),但两策略实例级对错互补(Fig.1) |
| R005 | Keluskar 2026《When Does Personality Composition Matter for M…》 | 3 | agentic多agent长程(编码协作/研究协作/买卖谈判… | 低宜人性使沟通全域同向剧变(φ0.44→0.93,p<0.003,d最大-12.39)但结果效应依任务结构:编码milestone 3/4模型无显著变化(仅… |
| R006 | Abdullahi 2026《The Persona Paradox: Medical Personas as Behav…》 | 3 | 静态QA(临床分诊1667例)+开放生成(PatientSa… | 系统性、情境依赖且非单调:医疗人格在急诊分诊约+20pp准确率与校准改善(部分统计显著),初级保健反降约10pp、部分小模型一致性-20pp,聚合后相互抵消 |
| R007 | Wu 2026《Persona Matters: Effects of Activation Steerin…》 | 3 | 静态QA(教育短答生成与自动评分,ASAP-SAS 10个p… | 人格转向整体降低答案质量:Qwen3-4B平均∣Δ∣=0.172(humorous -0.420),gpt-oss-20b evil -0.443,Qwen… |
| R008 | Kim 2025《Persona is a Double-edged Sword: Mitigating th…》 | 3 | 静态推理QA(零样本) | persona提示在llama3上12个数据集中7个降低推理准确率 |
| R010 | Duan 2025《The Power of Personality: A Human Simulation P…》 | 3 | 静态QA+开放创造生成+多agent辩论协作(三段式讨论) | 神经质得分与闭任务准确率跨任务跨模型普遍显著负相关(Qwen-14B五任务全显著) |
| R012 | Suresh 2025《Two-Faced Social Agents: Context Collapse in R…》 | 3 | 静态QA/推理(SAT数学28题,复制54题)+主观偏好问卷… | 认知负载下人格效应任务依赖性坍缩：GPT-5完全坍缩(SAT全对100%,PERMANOVA p=1.000,R²=0.0004)、Gemini部分坍缩(p… |
| R013 | Luz de Araujo et al. 2025《Persistent Personas? Role-Playing, Instruction…》 | 3 | 长程多轮对话(100+轮,长于99.99%的WildChat… | 人格保真随对话推进持续衰减(知识/风格/一致性三指标均降,目标导向对话更甚) |
| R015 | Zheng et al. 2024《When "A Helpful Assistant" Is Not Really Helpf…》 | 3 | 静态QA(MMLU事实问答) | 162人格 vs 无角色对照均无统计显著提升，部分人格反而显著更差(如Mistral的ecologist) |
| R016 | Salewski et al. 2023《In-Context Impersonation Reveals Large Languag…》 | 3 | 序贯决策(两臂bandit,10试次×2k局/年龄)+静态Q… | 年龄人格系统性改变探索策略：扮演越年长探索越少(β=-0.03,p<.001)、利用越多(β=0.04,p<.001)、平均奖励随扮演年龄升至20岁(β=0… |
| R030 | Sun 2026《Persona Vectors in Games: Measuring and Steeri…》 | 3 | agentic单步(一次性/含历史vignette博弈决策,… | 正向利他转向系统性提高慷慨行为(Dictator给钱$15@β=0→$55@β=3)并改变言辞框架(utility/payoff/kind词频随β系统变化) |
| R034 | Lin 2026《On Emotion-Sensitive Decision Making of Small …》 | 3 | agentic单步为主(博弈决策, 含多轮/多智能体/多模态… | 情绪转向系统性移动策略选择(Mean_Emotions NDM远超随机向量对照, 如Llama-1B 0.393 vs 0.006), 且随α单调放大 |
| R035 | Ong 2025《Identifying Cooperative Personalities in Multi…》 | 3 | agentic多轮博弈(10轮迭代囚徒困境,含通信与双ste… | 宜人/尽责/开放+转向使捣乱率中位数降至0.00 |
| R051 | Safder 2026《FinPersona-Bench: A Benchmark for Longitudinal…》 | 3 | agentic长程（200步序贯交易决策） | MSD（mandate显著性衰减）随时间复合且依模型而异 |
| R098 | Ding 2026《ContextEcho: A Benchmark for Persona Drift in …》 | 3 | agentic长程（数千轮编码会话）+下游无工具chat与S… | 17/23目标漂移差∣Δ∣≥0.30（范围−0.15~+1.00 |
| R099 | Handa 2025《Personality as a Probe for LLM Evaluation: Met…》 | 3 | 静态QA/推理（MMLU、BBQ）+agent基准（GAIA… | ICL对齐强且能力损失最小（Gemma ΔMMLU≈−0.06~−0.08，ΔGAIA还+0.06~+0.09） |
| R017 | Cho 2026《A Concise Agent is Less Expert: Revealing Side…》 | 2 | 对话生成单轮响应(任务型LMSYS-Chat-1M+日常Da… | 风格特征深度纠缠而非正交:提示Concise使感知Expert win率降至25.6%、Helpful 23.2% |
| R019 | Jiang 2025《HARBOR: Exploring Persona Dynamics in Multi-Ag…》 | 2 | agentic多轮竞争（多agent拍卖，10-15件物品逐… | 人格注入使agent偏离利润最大化：无人格Master利润率34.56%为最高，Master带人格降至31.75%，全员同人格时平均利润率从29.23%降至… |
| R023 | Xiao 2026《When Does Persona Prompting Actually Help? A R…》 | 2 | 静态开放式QA(1140题, 38角色×6域, 咨询/概念两… | 聚合差异极小(全部d<0.12, baseline均分4.390 vs hybrid 4.382)但维度分解现系统tradeoff: 角色提示升专业深度(h… |
| R024 | Klang 2026《Personas Shift Clinical Action Thresholds in L…》 | 2 | 静态临床决策vignette(单步二元判断) | 基线肯定率42.8% |
| R025 | Luz de Araujo 2025《Principled Personas: Defining and Measuring th…》 | 2 | 静态QA/推理/数学(多选+开放式, 全部客观可判) | 专家人格多为正向或不显著(成功率78-100% |
| R057 | Luz de Araujo 2025《Persistent Personas? Role-Playing, Instruction…》 | 2 | 多轮对话条件化的静态QA/指令基准（100+轮对话前缀+五数… | 保真三指标（知识/风格/入戏）随轮次一致衰减且目标导向对话更陡 |
| R058 | Suresh 2025《Two-Faced Social Agents: Context Collapse in R…》 | 2 | 静态QA/推理(SAT数学28/54题)+问卷式偏好任务(单… | 任务依赖性语境塌缩:GPT-5在SAT上完全趋同(全persona 100%准确,PERMANOVA p=1.000,R²=0.0004),Gemini部分… |
| R059 | Shin 2025《Spotting Out-of-Character Behavior: Atomic-Lev…》 | 2 | 开放式单轮长文生成(100-300词,非agentic) | 原子级指标暴露response级平均分掩盖的句级OOC'glitch'(ACC高而ACC_atom低) |
| R100 | Subbiah 2026《On the Limits of Steering Vectors for Preferen…》 | 2 | 静态NLG（摘要125题+邮件写作100题，写作个性化） | 转向效力随特质差异巨大：结构/风格整体性特质(bullets/formal tone等)最有效，非常规修辞(rhyming/tweet style等)最差且… |
| R075 | Ding 2026《Calibrate-Then-Act: Cost-Aware Exploration in …》 | 1 | agentic单步~短程（检索决策；单测/代码执行多步交互） | Pandora's Box上CTA-Prompted最优策略匹配率94.0% vs Prompted 23.0%/NonThink 11.0%，奖励0.62… |
| R090 | Messing 2026《Hidden Measurement Error in LLM Pipelines Dist…》 | 0 | 静态QA评测管线（MMLU、Chatbot Arena） | naive标准误比TEE校正SE小40-60% |
| R091 | Bjarnason 2026《On Randomness in Agentic Evals》 | 0 | agentic长程（SWE-Bench软件修复轨迹） | 单次运行pass@1随所选运行漂移2.2-6.0pp，temp=0下SD仍>1.5pp |
| R093 | Sida Wang 2025《Measuring all the noises of LLM Evals》 | 0 | 静态QA/基准评测(元评测) | 每个eval表现出特征性、可预测的总噪声水平 |
| R094 | Mustahsan et al. 2025《Stochasticity in Agentic Evaluations: Quantify…》 | 0 | agentic长程(GAIA)+多跳检索推理QA(FRAME… | ICC=0.30–0.77随模型/任务变化 |
| R096 | Miller 2024《Adding Error Bars to Evals: A Statistical Appr…》 | 0 | 评测方法学(跨任务通用) | 给出evals-as-experiments的统计公式集：成对分析降方差、聚类标准误处理题目非独立、功效分析定样本量 |

**邻近度分布（行级）**

```
3 │ ██████████████████ 18
2 │ █████████ 9
1 │ █ 1
0 │ █████ 5
```

**Gate0合并视图（⚠️警报2挂此主张）**

| 项 | 内容 |
|---|---|
| 警报2本体 | R001 = arXiv:2604.11048《NPTI persona steering》，静态三件套确认=静态邻近度3：①系统交互矩阵（10极性×6基准×4架构×5尺度）；②73.68%人类方向一致性等全套量化；③DPR检索式自适应路由。定位表一致（行级3） |
| 补刀二文（Gate0） | R002（PRISM意图门控，Gate0 C4:2；但定位表行级3——升格，见§3.2）与R007（11×任务敏感度差，Gate0 C4:2） |
| Gate0活路清单 | (a) agentic长程域；(b) 行为过程解释层；(c) 过程内mid-trajectory人格调度；(d) 严格端到端成功率路由（DPR为oracle式hit口径） |
| 定位表对活路(a)的侵蚀（Gate0未见） | **R005**（Keluskar：多agent长程编码/研究/谈判×人格构成，带Cohen's d/p/CI与中性改写对照，混淆质量2）——「agentic域人格×任务结构交互」已有系统实证；另有R030/R034/R035（博弈决策域）、R051（200步纵向）、R098（数千轮编码）、R099（GAIA agent基准上的人格探针） |
| 仍空白 | 活路(b)(c)：以行为原语为中介的交互解释、过程内自适应调度——定位表102行中无行占据；(d)端到端成功率路由agentic域亦无行 |
| 外推性质疑弹药 | Gate0：可借邻居#8（2605.16282，未入定位表）的环境保真度偏置质疑静态→agentic外推 |

**机械判决推导（§4.3规则）**：存在3（R001静态确证+agentic域行级3多枚）→「REPLICATE 或 强EXTEND，看域差」。域差核对：交互存在性（静态已证、agentic粗粒度已有R005）vs 过程内调度+原语反馈（全空白）→ 机械落点 = **强EXTEND**（按Gate0重定位口径：(b)+(c)为主卖点；「agentic域首个交互矩阵」这一卖点已被R005削弱，须降级为「行为原语粒度首个」）。**最终判决权属楠，此为规则推导。**

---

### C5（触及38行）

> 主张锚：行为原语（核验/探索/坚持止损/校准）的测量与倾向刻度（F5仪器库+F4理据层）。

| ID | 引文短式 | 邻近度(行级) | 任务域 | 一句发现 |
|---|---|---|---|---|
| R004 | Kim 2026《Persona Switch: Mixing Distinct Perspectives i…》 | 3 | 静态推理QA | 单用role-play常逊于zero-shot(如LLaMA-3.1-8B平均67.6%vs贪心69.7%),但两策略实例级对错互补(Fig.1) |
| R006 | Abdullahi 2026《The Persona Paradox: Medical Personas as Behav…》 | 3 | 静态QA(临床分诊1667例)+开放生成(PatientSa… | 系统性、情境依赖且非单调:医疗人格在急诊分诊约+20pp准确率与校准改善(部分统计显著),初级保健反降约10pp、部分小模型一致性-20pp,聚合后相互抵消 |
| R007 | Wu 2026《Persona Matters: Effects of Activation Steerin…》 | 3 | 静态QA(教育短答生成与自动评分,ASAP-SAS 10个p… | 人格转向整体降低答案质量:Qwen3-4B平均∣Δ∣=0.172(humorous -0.420),gpt-oss-20b evil -0.443,Qwen… |
| R016 | Salewski et al. 2023《In-Context Impersonation Reveals Large Languag…》 | 3 | 序贯决策(两臂bandit,10试次×2k局/年龄)+静态Q… | 年龄人格系统性改变探索策略：扮演越年长探索越少(β=-0.03,p<.001)、利用越多(β=0.04,p<.001)、平均奖励随扮演年龄升至20岁(β=0… |
| R030 | Sun 2026《Persona Vectors in Games: Measuring and Steeri…》 | 3 | agentic单步(一次性/含历史vignette博弈决策,… | 正向利他转向系统性提高慷慨行为(Dictator给钱$15@β=0→$55@β=3)并改变言辞框架(utility/payoff/kind词频随β系统变化) |
| R033 | Sui 2026《TACT: Mitigating Overthinking and Overacting i…》 | 3 | agentic长程(编码/终端agent, 数十至上百步轨迹… | OT/OA/CAL步隐状态沿两漂移轴线性可分(AUC≈0.9, OT-vs-CAL峰值0.91@层3, 信号集中于早中层) |
| R037 | Rahn 2024《Controlling Large Language Model Agents with E…》 | 3 | agentic多轮(双臂高斯bandit,ReAct逐轮交互… | EAST随乘子增大显著提升动作熵、缓解agent过早收敛于单臂的过度自信(温度采样对动作熵几乎无效) |
| R097 | Yap 2026《Behavioral Steering in a 35B MoE Language Mode…》 | 3 | agentic单步~短程（ReAct式≤5轮，预缓存工具响应… | autonomy转向α=2达d(pro)=+1.01(p<0.0001,CI[+0.60,+1.43])，ask_user占比78%→5% |
| R098 | Ding 2026《ContextEcho: A Benchmark for Persona Drift in …》 | 3 | agentic长程（数千轮编码会话）+下游无工具chat与S… | 17/23目标漂移差∣Δ∣≥0.30（范围−0.15~+1.00 |
| R017 | Cho 2026《A Concise Agent is Less Expert: Revealing Side…》 | 2 | 对话生成单轮响应(任务型LMSYS-Chat-1M+日常Da… | 风格特征深度纠缠而非正交:提示Concise使感知Expert win率降至25.6%、Helpful 23.2% |
| R042 | Zeng 2026《What Models Express, Suppress, and Resist: Aud…》 | 2 | 静态单轮引出prompt(agentic特质亦以单轮评测) | 9个agentic特质在两模型均为natural(基线即高表达,域均值增益仅3.78/2.42,转向增益最小)——agentic行为是默认模式而非可拨动方向 |
| R048 | Kumaran 2026《Causal Evidence that Language Models use Confi…》 | 2 | 静态多选事实QA(SimpleQA转4选, 1000题主实验… | 置信转向因果改变弃答: 最大低置信转向弃答66.5%→最大高置信7.0%(59.5pp摆幅, r=-0.99, p<0.001, 基线28.2%), 效应随… |
| R061 | Taubenfeld et al. 2026《Evaluating Alignment of Behavioral Disposition…》 | 2 | 静态QA（单轮建议型社交情境） | 自评与行为显著脱节：所有模型自评低冲动(<4/7)但多数在SJT中冲动倾向>50% |
| R062 | Slama et al. 2026《When Do LLM Preferences Predict Downstream Beh…》 | 2 | 静态QA（BoolQ）+agentic长程（GAIA L1、… | 偏好强预测建议(ρ=.94-.98)与拒答(ρ=.57-.83)且无需指令自发出现 |
| R063 | Han et al. 2025《The Personality Illusion: Revealing Dissociati…》 | 2 | 静态QA/行为探测任务（单步、非agentic） | 自评-行为方向对齐率45-62%，95%CI均与50%机会水平重叠 |
| R064 | Song et al. 2025《Human Psychometric Questionnaires Mischaracter…》 | 2 | 静态QA（日常用户查询、单轮） | 跨方法一致性坍塌：生成概率↔问卷ρ均值0.31/0.28(价值)、0.26/0.11(人格)，同法内参照0.74/0.77(置换检验p<0.05~0.001… |
| R065 | Tosato et al. 2025《Persistent Instability in LLM's Personality Me…》 | 2 | 静态问卷施测（无任务行为） | 仅题序重排即致人格测量大幅漂移 |
| R066 | Huang et al. 2026《Knowing But Not Doing: Convergent Morality and…》 | 2 | 静态QA（多选建议情境） | LLM间情境决策近乎完全趋同(Pearson r=0.99-1.00)而人类高度异质(r∈[-0.79,0.98]) |
| R067 | Bo 2026《Language Models Exhibit Inconsistent Biases To…》 | 2 | 静态单轮决策委托（27任务评分/6任务下注），非agenti… | 方向相反的双重偏差：stated端8模型全部显著偏信人类专家（平均信任缺口+5.14~+30.68，p<0.001） |
| R068 | Meyer 2026《Apparent Psychological Profiles of Large Langu…》 | 2 | 静态问卷+静态单步行为任务（彩票选择类风险任务），非agen… | LLM正反向题均值相关全为正（+0.61~+0.81）而人类全为负（-0.69~-0.82）——LLM间变异走偏差轴 |
| R069 | Zierahn 2026《Personality Without Persons? A Psychometric Cr…》 | 2 | 静态问卷施测，非agentic | 人类原版量表对LLM内容效度不达标（IPIP-NEO-120 S-CVI=.29、BFI-44=.54<.80）而LLM改编版达标（BFI-LLM=.93、… |
| R070 | Zierahn 2026《LLMs Aren't Human: A Critical Perspective on L…》 | 2 | 元层批判（无任务施测） | 六大人格定义特征无一在LLM上完全满足：跨情境一致性被提示敏感性普遍否定 |
| R071 | Rezazadeh 2026《The Shape of Overthinking: Backtracking Bursts…》 | 2 | 静态QA/推理（AIME长推理trace，非agentic） | 早期孤立修复与正确兼容（正确轨迹首个合格backtrack反而更早，L2约2000 vs 3000词，§4.3） |
| R101 | Yang 2026《ActTraitBench: Quantifying the Knowledge-Decis…》 | 2 | 静态决策情景（两阶段0-99数值决策+归因，非agentic… | 知识-决策鸿沟普遍且随规模加剧：qwen3-235b-thinking G_KD=1.541、gemini-3.1-pro 1.834 vs 人类基线0.4… |
| R072 | Wang et al. 2026《A Survey for LLM Agent Trajectory Analysis: Fr…》 | 1 | agentic长程（LLM agent轨迹分析文献域） | 以五维度梳理领域（失败分类学/失败归因/增强优化/轨迹监控工具/数据集与基准） |
| R073 | Huang 2026《When Agents Fail to Act: A Diagnostic Framewor…》 | 1 | agentic单步（工具调用为主，多agent系统语境） | 小模型的首要瓶颈是工具初始化失败（程序性可靠性） |
| R074 | Shah et al. 2026《Characterizing Faults in Agentic AI: A Taxonom…》 | 1 | agentic长程（真实agentic AI系统的工程故障） | 34种故障类型组织进4个架构维度 |
| R075 | Ding 2026《Calibrate-Then-Act: Cost-Aware Exploration in …》 | 1 | agentic单步~短程（检索决策；单测/代码执行多步交互） | Pandora's Box上CTA-Prompted最优策略匹配率94.0% vs Prompted 23.0%/NonThink 11.0%，奖励0.62… |
| R076 | Kausik 2026《The Context Gathering Decision Process: A POMD…》 | 1 | agentic长程（迭代检索搜索：LoCoMo 1275对话… | 谓词信念状态使多跳推理最高+11.4%且从不降低性能 |
| R077 | Mazaheri 2026《AgentAtlas: Beyond Outcome Leaderboards for LL…》 | 0 | agentic评测元层（合成1,342条单步判别，非真实长程… | 两项测量风险获示证：去掉显式标签菜单后映射标签一致性发生substantial变化 |
| R078 | Zhang 2026《Agentic Confidence Calibration》 | 0 | agentic长程（多步轨迹、外部工具不确定性；含GAIA域… | +方向：HTC在8个基准、多LLM与多agent框架上校准与判别均一致超过强基线 |
| R079 | Liu et al. 2026《TrajAD: Trajectory Anomaly Detection for Trust…》 | 0 | agentic长程（轨迹级过程监督） | 通用LLM零样本难以识别与定位轨迹程序性异常（通用能力不自动转化为过程可靠性） |
| R080 | Yeh 2026《Tracing Agentic Failure from the Flow of Succe…》 | 0 | agentic长程（多步失败轨迹） | 仅用100条成功轨迹训练即可：比提示法基线快200–5000倍，且域内F1高出约20个百分点、分布外高出约7个百分点 |
| R081 | Liu et al. 2026《Who&When Pro: Can LLMs Really Attribute Failur…》 | 0 | agentic长程（3模态、26个基准的失败轨迹） | 建成12,326条带金标失败轨迹的大规模归因基准 |
| R083 | Zhu et al. 2026《A Unified Framework for the Evaluation of LLM …》 | 0 | agentic长程（7基准24域：单agent/多agent… | 脚手架选择与环境易变性双向实质性移动基准结果，框架可将模型内在能力与框架/环境诱导工件解缠 |
| R085 | Zhang et al. 2026《AgentForesight: Online Auditing for Early Fail…》 | 0 | agentic长程（Coding/Math/Agentic三… | 7B在线审计器超GPT-4.1与DeepSeek-V4-Pro，最高+19.9%性能增益、步定位误差低3倍 |
| R086 | Oh et al. 2026《Neglected Free Lunch from Post-training: Progr…》 | 0 | agentic长程（长时程交互、不可逆动作、随机环境反馈） | progress advantage在全部设置一致超置信度基线，且无需任务专门训练即超专门训练的过程奖励模型 |
| R090 | Messing 2026《Hidden Measurement Error in LLM Pipelines Dist…》 | 0 | 静态QA评测管线（MMLU、Chatbot Arena） | naive标准误比TEE校正SE小40-60% |

**邻近度分布（行级）**

```
3 │ █████████ 9
2 │ ███████████████ 15
1 │ █████ 5
0 │ █████████ 9
```

**Gate0合并视图（⚠️口径冲突需楠裁定）**

| 项 | 内容 |
|---|---|
| Gate0内C5特异最高 | 2 = AgentAtlas（礼物确认：六门词表+15基准审计+自认效度缺口；核验原语在六门无对应=ABCR可声明增量；测决策正确性非行为倾向强度） |
| ⚠️口径冲突 | 定位表将AgentAtlas（R077）记为邻近度**0**（礼物/工具口径），Gate0记C5:**2**（威胁口径）。合并读法建议：测量半边已有词表底座（按2防御），增量声明按礼物用（见§3.2） |
| 行级3的归属疑义 | 定位表9个行级3（R004/R006/R007/R016/R030/R033/R037/R097/R098）均为多主张行，其行级3主要由C1/C3/C4/C7驱动，**C5特异邻近度未单独标定** |
| 最接近C5本体的行 | R016（2023：人格→探索/利用probit原语分解——「人格→行为原语」单点链路11年前已有雏形）、R037（转向→动作熵）、R097（转向→ask_user行为占比+效应量）、R033（OT/OA行为状态隐层可分）、R048（置信转向→弃答59.5pp摆幅） |
| 未被占 | 四原语**成套**×人格特质×倾向强度刻度×效度检验；F4理据层10行全部prox2（自评-行为解离：R061-R070）为C5提供密集动机证据而非占位 |

**机械判决推导（§4.3规则）**：双口径——按定位表行级上界存在3→「看域差」；按主张特异读法（Gate0确证最高2+行级3归属他主张）→ 最高2 → **EXTEND**。机械落点 = **EXTEND（倾向）**，需楠对R016/R037/R097/R048做C5特异邻近度裁定后复核。**最终判决权属楠，此为规则推导。**

---

### C6（触及8行）

> 主张锚：人格→行为原语→任务结果的统计中介分析（Gate0材料：「行为原语中介」「C6中介分析的行为层定位」）。

| ID | 引文短式 | 邻近度(行级) | 任务域 | 一句发现 |
|---|---|---|---|---|
| R029 | Herrmann 2026《Do LLMs Experience an Internal Polylogue? Inve…》 | 3 | 静态QA/推理(MMLU-Pro, 非agentic) | polylogue(人格方向对齐时间序列)特征预测正确率匹配随机投影并接近激活基线(AUC 0.59-0.87) |
| R030 | Sun 2026《Persona Vectors in Games: Measuring and Steeri…》 | 3 | agentic单步(一次性/含历史vignette博弈决策,… | 正向利他转向系统性提高慷慨行为(Dictator给钱$15@β=0→$55@β=3)并改变言辞框架(utility/payoff/kind词频随β系统变化) |
| R072 | Wang et al. 2026《A Survey for LLM Agent Trajectory Analysis: Fr…》 | 1 | agentic长程（LLM agent轨迹分析文献域） | 以五维度梳理领域（失败分类学/失败归因/增强优化/轨迹监控工具/数据集与基准） |
| R080 | Yeh 2026《Tracing Agentic Failure from the Flow of Succe…》 | 0 | agentic长程（多步失败轨迹） | 仅用100条成功轨迹训练即可：比提示法基线快200–5000倍，且域内F1高出约20个百分点、分布外高出约7个百分点 |
| R082 | Rafi et al. 2026《FALAT: Tracing Failures in LLM Agent Trajector…》 | 0 | agentic长程（多agent失败轨迹） | 依赖感知归因区分错误起源与传播 |
| R084 | Qiao et al. 2026《VerifyMAS: Hypothesis Verification for Failure…》 | 0 | agentic长程（多agent长交互轨迹） | 假设验证式归因在两基准上对多底座一致提升并超先前方法，长轨迹上不牺牲推理效率，并能捕捉跨步不一致等全局失败 |
| R086 | Oh et al. 2026《Neglected Free Lunch from Post-training: Progr…》 | 0 | agentic长程（长时程交互、不可逆动作、随机环境反馈） | progress advantage在全部设置一致超置信度基线，且无需任务专门训练即超专门训练的过程奖励模型 |
| R096 | Miller 2024《Adding Error Bars to Evals: A Statistical Appr…》 | 0 | 评测方法学(跨任务通用) | 给出evals-as-experiments的统计公式集：成对分析降方差、聚类标准误处理题目非独立、功效分析定样本量 |

**邻近度分布（行级）**

```
3 │ ██ 2
2 │ · 0
1 │ █ 1
0 │ █████ 5
```

**Gate0合并视图（证据最薄的主张）**

| 项 | 内容 |
|---|---|
| Gate0内C6最高 | 1（R001 trait-process相关性框架、R002机制口头解释、R072失败归因工程线） |
| 定位表行级3两枚（均为八邻居之外新增） | R029（polylogue特征**预测**正确率——「人格方向→结果」的预测版，非中介检验；且预测力仅匹配随机投影基线）、R030（转向改变行为词汇框架+慷慨结果——具备「干预→行为→结果」三要素雏形，无统计中介） |
| 特异读法 | 两行按C6本体（统计中介）读实为1–2级；C6仅8行触及、其中5行为0级背景（F5失败归因工程线），是七主张中证据最薄者 |
| 组织素材 | R072（Wang survey，C6:1与Gate0一致）：42篇轨迹分析分类体系无人格维度=文献空位证明；failure attribution可为中介分析行为层定位 |

**机械判决推导（§4.3规则）**：按行级上界存在3→「看域差」；按特异读法最高≤2→**EXTEND**。**OPEN候选条件核对**（若楠将R029/R030特异值判为≤1，C6落入「最高≤1」档，须过三重前置）：①探针全中 ✅（17/17，含3条supplementary修补）；②饱和 ❌不满足——C6证据主要来自F2（未达饱和：两轮滚雪球新增25%/21%均>10%）与F5（仅方向性饱和，第二轮样本量不足）；③滚雪球空手 ❌不满足——F2雪球新增10条、F5新增33条，无一空手。→ **三重前置不满足，C6不能判OPEN**；机械落点 = **EXTEND**。**最终判决权属楠，此为规则推导。**

---

### C7（触及20行）

> 主张锚：长程人格/行为漂移的动力学测量×恢复行为交互（Gate0材料：「漂移的动力学测量×恢复」）。

| ID | 引文短式 | 邻近度(行级) | 任务域 | 一句发现 |
|---|---|---|---|---|
| R012 | Suresh 2025《Two-Faced Social Agents: Context Collapse in R…》 | 3 | 静态QA/推理(SAT数学28题,复制54题)+主观偏好问卷… | 认知负载下人格效应任务依赖性坍缩：GPT-5完全坍缩(SAT全对100%,PERMANOVA p=1.000,R²=0.0004)、Gemini部分坍缩(p… |
| R013 | Luz de Araujo et al. 2025《Persistent Personas? Role-Playing, Instruction…》 | 3 | 长程多轮对话(100+轮,长于99.99%的WildChat… | 人格保真随对话推进持续衰减(知识/风格/一致性三指标均降,目标导向对话更甚) |
| R027 | Lu 2026《The Assistant Axis: Situating and Stabilizing …》 | 3 | 多轮对话（15轮合成对话4域）+静态基准；非agentic | 治疗与AI哲学类对话稳定诱发漂移（编码/写作不漂） |
| R028 | 匿名(OpenReview) 2026《Steering LLM Interactions Using Persona Vector…》 | 3 | 长上下文对话 | 据web核实梗概：提示法短期可产生人格一致回应但很少诱发持续行为改变、且常提高幻觉率 |
| R033 | Sui 2026《TACT: Mitigating Overthinking and Overacting i…》 | 3 | agentic长程(编码/终端agent, 数十至上百步轨迹… | OT/OA/CAL步隐状态沿两漂移轴线性可分(AUC≈0.9, OT-vs-CAL峰值0.91@层3, 信号集中于早中层) |
| R051 | Safder 2026《FinPersona-Bench: A Benchmark for Longitudinal…》 | 3 | agentic长程（200步序贯交易决策） | MSD（mandate显著性衰减）随时间复合且依模型而异 |
| R052 | Dongre 2025《Drift No More? Context Equilibria in Multi-Tur…》 | 3 | 多轮长程:合成约束重写任务(8轮)+τ-Bench用户模拟(… | 漂移收敛于有界噪声均衡而非失控退化(ΔD_t对D_t负斜率,Spearman ρ<-0.7,恢复力存在) |
| R053 | Shekkizhar 2025《Echoing: Identity Failures when LLM Agents Tal…》 | 3 | agentic长程(多轮工具使用的顾客-卖家交易对话,每ag… | echoing率5-70%依模型/领域 |
| R054 | Li 2024《Measuring and Controlling Instruction (In)Stab…》 | 3 | 多轮对话self-chat(合成对话,非agentic)+M… | LLaMA2-70B与GPT-3.5在8轮内显著指令漂移,且agent LM逐渐采纳对方user LM的指令(安全隐患) |
| R098 | Ding 2026《ContextEcho: A Benchmark for Persona Drift in …》 | 3 | agentic长程（数千轮编码会话）+下游无工具chat与S… | 17/23目标漂移差∣Δ∣≥0.30（范围−0.15~+1.00 |
| R043 | Wang 2026《Nautilus Compass: Black-box Persona Drift Dete…》 | 2 | agentic长程(生产编码agent数百至数千轮会话;评测… | 合成100-prompt集AUC从0.51升至0.92,最大单步增益(+0.29)来自把格言式锚改写为task-shaped句 |
| R055 | Kim 2026《PICon: A Multi-Turn Interrogation Framework fo…》 | 2 | 多轮对话问答（50轮链式审讯，非agentic） | 无任何persona组综合一致性面积达到人类基线 |
| R056 | Abdulhai 2025《Consistently Simulating Human Personas with Mu…》 | 2 | 多轮对话模拟（患者/学生/闲聊三用户角色，10-300轮） | 未微调模型prompt-to-line与Q&A一致性随对话长度渐降（10→60/300轮） |
| R057 | Luz de Araujo 2025《Persistent Personas? Role-Playing, Instruction…》 | 2 | 多轮对话条件化的静态QA/指令基准（100+轮对话前缀+五数… | 保真三指标（知识/风格/入戏）随轮次一致衰减且目标导向对话更陡 |
| R058 | Suresh 2025《Two-Faced Social Agents: Context Collapse in R…》 | 2 | 静态QA/推理(SAT数学28/54题)+问卷式偏好任务(单… | 任务依赖性语境塌缩:GPT-5在SAT上完全趋同(全persona 100%准确,PERMANOVA p=1.000,R²=0.0004),Gemini部分… |
| R059 | Shin 2025《Spotting Out-of-Character Behavior: Atomic-Lev…》 | 2 | 开放式单轮长文生成(100-300词,非agentic) | 原子级指标暴露response级平均分掩盖的句级OOC'glitch'(ACC高而ACC_atom低) |
| R060 | Choi 2024《Examining Identity Drift in Conversations of L…》 | 2 | agent-agent多轮对话(36主题人际/价值观话题,非… | 更大模型身份漂移更大(小模型一致因子最多 |
| R065 | Tosato et al. 2025《Persistent Instability in LLM's Personality Me…》 | 2 | 静态问卷施测（无任务行为） | 仅题序重排即致人格测量大幅漂移 |
| R085 | Zhang et al. 2026《AgentForesight: Online Auditing for Early Fail…》 | 0 | agentic长程（Coding/Math/Agentic三… | 7B在线审计器超GPT-4.1与DeepSeek-V4-Pro，最高+19.9%性能增益、步定位误差低3倍 |
| R091 | Bjarnason 2026《On Randomness in Agentic Evals》 | 0 | agentic长程（SWE-Bench软件修复轨迹） | 单次运行pass@1随所选运行漂移2.2-6.0pp，temp=0下SD仍>1.5pp |

**邻近度分布（行级）**

```
3 │ ██████████ 10
2 │ ████████ 8
1 │ · 0
0 │ ██ 2
```

**Gate0合并视图（⚠️Gate0→定位表修正幅度最大的主张）**

| 项 | 内容 |
|---|---|
| Gate0原判 | 基于HpUDi5Pe8S（R028）全文定界：C7边缘、最高2——「漂移未定义未测量、恢复完全未触及」；并配两个礼物锚点（R007§5点名drift监测为future work、R028可作『连漂移都没定义』的靶子） |
| 定位表推翻此留白判断 | F3/F0抽取带来行级3×10：**R052**（Drift No More：漂移动力学ΔD_t负斜率+有界噪声均衡+**恢复力存在**——定义/测量/恢复三件都有了）、**R027**（Assistant Axis：轴投影在线漂移监测+activation capping稳定，有害响应−60%且能力不降）、R051（FinPersona-Bench 200步纵向mandate衰减）、R098（ContextEcho数千轮agentic编码漂移基准）、R053（Echoing身份失败5–70%）、R054（2024年即有指令漂移测控）、R013（100+轮人格保真衰减+回归基线机制）、R012/R033 |
| R028口径修正 | 定位表记行级3但抽取深度仅**摘要级**；Gate0为全文定界（经Exa读毕）給C7:2——建议以Gate0的2为准（见§3.2） |
| 残余域差 | 现有漂移工作的对象是persona表达/指令一致性/mandate显著性/身份echo，**无一以行为原语强度为漂移对象**；「人格干预×漂移×恢复」的交互设计（干预条件下的漂移-恢复动力学）仍无行占据——但域差比Gate0预估**窄得多**：R052已给恢复力、R027已给监测+干预式稳定 |

**机械判决推导（§4.3规则）**：存在3（多枚，非借Gate0八邻居）→「REPLICATE 或 强EXTEND，看域差」。机械落点 = **强EXTEND**（必须以「行为原语漂移×恢复交互」重述，并把R052/R027列为最近邻直接对话；原「漂移无人定义」的动机写法已不可用）。⚠️ 建议楠亲自复核R052/R027/R098全文后再判。**最终判决权属楠，此为规则推导。**

---

## 3 与Gate0杀伤报告的交叉印证

### 3.1 Gate0八邻居 ↔ 定位表逐行对照

| Gate0邻居 | Gate0逐主张邻近度 | 定位表行 | 定位表相邻主张（行级邻近度） | 修正方向 | 判读 |
|---|---|---|---|---|---|
| arXiv:2604.11048（NPTI/DPR） | C1:2, C2:2, C3:2, **C4:3(静态)**, C6:1 | R001（全文级，混淆2） | C1/C3/C4（3） | **确认**（C4静态3=警报2成立） | 定位表**漏记C2**；C1/C3列须按Gate0降读为2 |
| arXiv:2602.12285（Biased Agents） | **C1:3(宽口径)**, C4:1–2 | R003（全文级，混淆1） | C1（3） | **一致**（警报1成立） | 双源同判，C1的3为全场唯一双源确证3 |
| arXiv:2603.18507（PRISM） | C1:1, C4:2, C6:1 | R002（全文级，混淆1） | C1/C4（3） | **升格**（Gate0最高2→行级3） | 抽取后发现其对照为本组最严（随机persona+长度3档）；行级3是否成立需楠裁定，建议C4列按2–3读 |
| arXiv:2604.07102（Wu&Henriksson） | C1:1, C2:2, C3:2, C4:2, C7:0(点名未做) | R007（全文级，混淆1） | C1/C3/C4/C5（3） | **升格+主张集变化** | 定位表漏记C2、新增C5、未带C7动机锚点（其§5点名drift监测为future work——C7写作素材，勿丢） |
| OpenReview:HpUDi5Pe8S | C7:2, C2:1, C3:1, C1:0–1 | R028（**摘要级**，混淆1） | C3/C7（3） | **升格存疑** | Gate0系全文定界（Exa读毕：无漂移定义/无逐轮曲线/单题条件反例），定位表仅摘要级——**建议以Gate0的C7:2为准** |
| arXiv:2605.20530（AgentAtlas） | C5:2, C7:1, C4:1 | R077（摘要级，混淆1） | C5（0） | **降格（口径冲突）** | Gate0威胁口径2 vs 定位表礼物口径0。合并读法：C5测量半边按2防御、增量声明（核验原语无对应+效度缺口）按礼物用 |
| HF:Wang轨迹分析survey | C5:1, C6:1 | R072（摘要级，混淆0） | C5/C6（1） | **一致** | 文献空位证明（42篇分类体系无人格维度）双源同判 |
| arXiv:2605.16282（安全基准taxonomy） | C1:1(经PsySafe间接), C5:1 | **未入定位表** | — | **覆盖缺口** | 其两项可用件（agent-internal风险低测动机、PsySafe切割纪律）现仅存于Gate0报告，见§3.3 |

### 3.2 主张级：Gate0预判 vs 抽取后合并视图

| 主张 | Gate0预判最高（来源） | 定位表行级最高（3级行数） | 修正 | 合并视图要点 |
|---|---|---|---|---|
| C1 | 3（2602.12285宽口径） | 3（21行） | **确认+密度暴增** | 警报1成立；宽口径现象层在agentic域已多点扩散（R014/R041/R005等），静态prox3证据带密集；重定位（特质×严对照×中介）仍是唯一活路 |
| C2 | 2（静态） | 3（7行，全为新邻居） | **升**（滑向3已发生） | Gate0脚注预警兑现：R097/R031把agentic半场压掉一角；剩余=长程×成功率×剂量整链 |
| C3 | 2（静态） | 3（18行） | **升**（滑向3已发生） | 剂量梯度已被R014/R030/R034多点触及；整链无人但每环有近邻 |
| C4 | 3（静态三件套） | 3（18行，含agentic域R005等） | **确认+agentic侵蚀** | 警报2成立且活路(a)被R005削弱；(b)行为过程解释+(c)过程内调度仍全空白 |
| C5 | 2（AgentAtlas） | 3（9行，行级归属他主张） | **名义升/实质待定** | R077口径冲突（0 vs 2）；C5特异邻近度未标定，最接近者R016/R037/R097/R048需楠裁定 |
| C6 | 1 | 3（2行，特异读法1–2） | **名义升** | R029/R030为新增；按中介本体读实为1–2级；证据最薄（8行/5行为0级） |
| C7 | 2（名义占位，实质留白） | 3（10行） | **大幅升（Gate0留白判断被推翻）** | R052已给漂移动力学+恢复力、R027已给监测+干预稳定；「漂移无人定义」的动机写法作废；残余=行为原语漂移×人格干预×恢复交互 |

> 总判读：Gate0两条警报（C1←2602.12285、C4←2604.11048三件套）在定位表中**双双确证**且以更多邻居加固——本热图C1/C4两节的表格与条形图即警报与定位表证据的合并视图。Gate0八邻居之外，抽取新增了**33个行级3的行**（全场38行3级−八邻居对应的5行：R001/R002/R003/R007/R028），主要落在C3(F2 agentic转向线)与C7(F3漂移线)——这两条线是Gate0预检覆盖最薄、抽取后修正最大的区域。

### 3.3 覆盖缺口与建议补录项（供楠决断）

| # | 缺口 | 影响 | 建议 |
|---|---|---|---|
| 1 | 2605.16282（安全基准taxonomy）未入定位表，PsySafe（ACL'24）亦无行承载 | C1「任务成功率vs安全危险率」切割纪律与「agent-internal风险低测」动机引用悬空 | 补录2条0–1级行，或在终稿C1/动机节直接引Gate0报告 |
| 2 | R001/R007的相邻主张列缺C2（Gate0均判C2:2） | C2热图少2个2级锚，C2节的静态先行证据不完整 | 定位表补记；本热图§C2已以Gate0合并视图补显 |
| 3 | R007的C7动机锚点（§5点名drift监测未做）未入定位表任何列 | C7动机引用素材可能在终稿丢失 | 写作时从Gate0礼物清单带入 |
| 4 | R028行级3 vs Gate0全文定界C7:2（定位表抽取深度仅摘要级） | C7邻近度可能被高估1级 | 以Gate0为准；若楠要行级改判，据Gate0定界节 |
| 5 | R077邻近度0 vs Gate0 C5:2（威胁/礼物口径未统一） | C5防御面可能被低估 | 楠统一口径；建议威胁按2、增量按礼物双记 |

---

## 4 判决倾向汇总与OPEN三重前置核对

### 4.1 机械判决汇总（§4.3规则推导；最终判决权属楠）

| 主张 | 是否存在3 | 机械规则输出 | 域差核对结论 | 机械落点（倾向） |
|---|---|---|---|---|
| C1 | 是（R003双源确证） | REPLICATE或强EXTEND看域差 | 人口学vs特质／vanilla vs等长+检验／聚合vs原语中介，三项域差实在 | **强EXTEND**（Gate0重定位口径） |
| C2 | 是（行级，新邻居） | 同上 | R097单步短程非长程成功率；R031证明转移需重标定 | **强EXTEND**（先复核R097/R031） |
| C3 | 是（行级，新邻居） | 同上 | 剂量/agentic各环节有近邻，整链无人 | **强EXTEND**（以链为单位重述） |
| C4 | 是（R001静态确证+agentic行级） | 同上 | 交互存在性已被占（静态全占+agentic粗粒度R005）；过程内调度+原语中介全空白 | **强EXTEND**（(b)(c)为主卖点） |
| C5 | 行级是／特异待定（Gate0最高2） | 双口径：看域差／EXTEND | 行级3归属他主张；成套原语×倾向刻度×效度未被占 | **EXTEND**（待楠标定特异值） |
| C6 | 行级是（2行）／特异读法1–2 | 双口径：看域差／EXTEND | 预测≠中介、无统计中介；证据最薄 | **EXTEND**（OPEN不成立，见4.2） |
| C7 | 是（10行，非借八邻居） | REPLICATE或强EXTEND看域差 | 漂移定义/测量/恢复已被R052/R027占；行为原语漂移×干预×恢复交互未占 | **强EXTEND**（楠须复核R052/R027/R098） |

### 4.2 OPEN候选三重前置核对

按§4.3，OPEN候选仅当「最高≤1且饱和」。**本轮无任何主张满足「最高≤1」**（七主张行级最高均≥2，即便按Gate0特异口径校正后最低的C6也在1–2之间）→ **本轮无OPEN候选**。为完备起见，三重前置的全局状态如下（若楠改判某主张特异值≤1时直接取用）：

| 前置 | 状态 | 依据 |
|---|---|---|
| ①探针全中 | ✅ 满足 | 探针状态表：17/17检出，0未检出（14 natural + 3 supplementary；3个检索洞均已修补并留教训） |
| ②饱和 | ⚠️ 分前沿不齐 | 达/近饱和：F1（第二轮9%<10%）、F3（连续两轮≈10%）、F4（9%→15%但新增全为实时新预印本）、F0（r2≈5%）、F6（15.5%→12.5%达两轮上限）；**未达**：F2（25%→21%均>10%，仅到两轮上限）、F5（仅方向性饱和，第二轮样本量不足） |
| ③滚雪球空手 | ❌ 不满足 | 各前沿雪球新增：F1 20、F2 10、F3 21、F4 20、F5 33、F6 10、F0 7（合计121）——无一前沿空手 |

> 即：即便某主张被改判为「最高≤1」，三重前置中②（其证据来源前沿F2/F5未饱和）与③（雪球非空手）也不满足，**本轮任何主张都不具备判OPEN的资格**。

---

生成完毕。表格数据由定位表.csv机械抽取（行级邻近度、相邻主张、任务域、主要发现首句），分析块合并Gate0杀伤报告逐主张定界与结构化摘要。**所有判决倾向为§4.3规则机械推导，最终判决权属楠。**


---

## 补充轮增补（2026-07-17）

> 本节为文末追加增量，**原文任何行未改动**（§2 各热图表与 §4.1 判决倾向以本节为增量修订层）。来源：残余偏倚 2/3/4 侦察轮 + 补扫 S1–S4，36 新行 R105–R140 入定位表（prox3×6、prox2×30）。定界全文见 `deliverables/补充轮-偏倚234-报告.md`。

### C3 热图行增补（+16 行 → 触及 29+16=45 行）

| ID | 引文短式 | 邻近度(行级) | 任务域 | 一句发现 |
|---|---|---|---|---|
| R105 | Dong 2026《Steer Model beyond Assistant》(B2-01) | 3 | 单轮文本生成（五基准无工具调用；无agentic） | IFEval strict随α呈倒U：α≈0.5–1达峰、α=2回落；反能力人格GSM8K 91.0→11.0单调；剂量-冲突律+steering tax |
| R107 | Zhuravel 2026《AS for Tool-Poisoning Defense》 | 3 | agentic工具使用（MCP tool-calling，中毒工具描述） | HyperSteer剂量曲线f=0→1.0: AR 0.54→0.94（f=1.0系过转向伪影）；良性代价f=0.7仅−4pp vs f=1.0 −26pp |
| R108 | Huh & Mohapatra 2026《Steering LLMs for Multi-agent Decision-making》 | 3 | 多智能体博弈决策（γ-Bench） | （仅摘要）交互轨迹学得的转向表示注入后跨模型族一致提升社会与策略性能；剂量待全文核实 |
| R109 | ARR匿名《Big5-Scaler》(前身arXiv:2508.06149) | 3 | 社交对话agent+任务特定档案搜索；非长程 | 数值Big Five剂量接口（r>0.85比例缩放）+贝叶斯优化任务特定人格档案→任务依赖性能变化 |
| R111 | He 2024《Context Steering》(CoS) | 2 | 静态NLG（个性化摘要、BBQ、仇恨量化） | λ剂量单调调控context影响强度（人评Spearman ρ=.67, p<.001）——B2-01同机制先行者 |
| R112 | Veselovsky 2025《Localized Cultural Knowledge》 | 2 | 静态QA与开放生成 | 层19–28加文化向量大幅恢复显式提示的本地化率且保留implicit级多样性 |
| R113 | Heyman & Vandeputte 2026《Steer Like the LLM》 | 2 | 静态NLG（persona steering基准+IFEval） | 常数转向对prompt机制不忠实；Δ_PS蒸馏+token级系数3/3模型超prompt steering |
| R120 | Chen 2026《Controlling Tool Use with Heading-Specific AS》 | 2 | agentic工具调用（Math/Time/Intention三域） | 转向向量对工具调用双向因果控制（5模型×3域一致）；因果有效≠线性结构 |
| R122 | Sheta 2026《Behavioural Asymmetry Across Activation Interventions》 | 2 | 静态对话问答（BIG5-CHAT改造） | 同一几何方向下干预方式不可互换：ActAdd唯一高低双向可靠（judge分随α单调，p<0.0001） |
| R123 | McKenzie 2026《Endogenous Resistance to Activation Steering》 | 2 | 静态推理时生成（任务失配转向下） | steering持续生效时自发抵抗并中程恢复（ESR）；26个因果SAE latent，消融降25% |
| R124 | Wang 2025《The Geometry of Persona》 | 2 | 静态生成（角色/人格风格） | 层×强度网格现转向'甜点'（中层14-16×boost 6-8）；能力保持仅为声称（未报MMLU数据） |
| R125 | Baines 2026《Persona Cartography》 | 2 | 静态基准+多轮frustration对话 | 权重空间trait-LoRA随scale近单调、近可加；中等剂量能力保持、极端退化 |
| R126 | Fierro & Roger 2025《Steering LMs with Weight Arithmetic》 | 2 | 静态QA/数学 | 权重转向OOD行为控制常强于激活转向且先于能力退化 |
| R127 | Kelkar 2026《Playing Devil's Advocate》 | 2 | 静态强制选择+16事实探针 | 批判系人格向量免sycophancy标注达CAA效果68-98%；过度纠偏探针CAA反而更差 |
| R128 | Wei 2026《Situational Personality Steering》(IRIS) | 2 | 静态NLG（情境性人格问答） | 情境依赖人格实证+Identify–Retrieve–Steer情境自适应神经元转向 |
| R129 | Nie 2025《AdaPA-Agent》(NeurIPS 2025) | 2 | agent个性化多轮交互（推荐+web） | 免反馈动态估计偏好强度+强度加权next-token线性组合，较ReAct +18.9%/+14.2% |

**邻近度分布更新（行级）**：3级 18+4=**22**；2级 11+12=**23**；1级 0；0级 0。

**判决倾向修订（C3）**：机械落点**维持强EXTEND**，但理由收紧——①**解码层剂量已占位成族**（CoS 2024→B2-01 2026→AdaPA agent域），"强度连续剂量×任务指标"在logit空间无增量可言；②**残差流组合位仍空**：残差流方向×剂量曲线×agentic长程任务成功率×统计检验的整链无人占据（最近邻R107口径=防御率+无检验、R108仅摘要级）；③主张重述必须以整链为单位，且剂量设计须引B2-01剂量-冲突律+steering tax+R107过转向伪影检测为协议先验。**风险敞口**：R107/R108墙后全文若证实含统计检验+任务成功率主口径，C3滑向REPLICATE边缘（当前合成估计~10–15%）——楠判决前建议先定界此二条。

### C4 热图行增补（+10 行 → 触及 33+10=43 行）

| ID | 引文短式 | 邻近度(行级) | 任务域 | 一句发现 |
|---|---|---|---|---|
| R105 | Dong 2026《Steer Model beyond Assistant》(B2-01) | 3 | 单轮文本生成（无agentic） | 剂量-冲突律：任务与助手先验冲突越大最优α越高——任务×干预强度交互的解码层证据 |
| R106 | Lim 2025《Persona Dynamics》(PANDA, ACL 2025) | 3 | agentic多步交互（text-based games, POMDP） | 16人格×25游戏：高Openness显著占优（Friedman p<0.001）+轨迹机制（更广探索）；训练时策略塑形非推理时干预 |
| R109 | ARR匿名《Big5-Scaler》 | 3 | 社交对话agent+任务特定档案搜索 | 贝叶斯优化任务特定人格档案=交互+条件选择两要素直接跟进；但query级非过程内、无长程agentic |
| R110 | Yao 2025《Peacemaker or Troublemaker》 | 3 | 多智能体辩论（QA推理域） | 谄媚8档剂量×辩手组合网格→MMLU Pro准确率最大差5.9pp；NAR-SS r=0.902；无显著性检验 |
| R121 | Gilg 2026《Probing Persona-Dependent Preferences》 | 2 | 静态任务选择（成对偏好） | 线性probe预测persona依赖任务效用r≈0.87-0.94；steering使任务选择0.01→0.99 |
| R128 | Wei 2026《Situational Personality Steering》(IRIS) | 2 | 静态NLG | 情境-行为一致性实证+情境自适应人格转向——C4'条件选择'的干预侧实现（情境级） |
| R129 | Nie 2025《AdaPA-Agent》 | 2 | agent个性化多轮交互 | 交互中动态估计强度+线性组合=过程内调度最近机制同构体（对象=用户偏好非人格特质） |
| R132 | Liu 2025《Synthetic Socratic Debates》(EMNLP 2025) | 2 | AI-AI多轮道德辩论 | 意识形态与Big Five是道德立场与辩论结果最强预测维度；appeals策略随辩论演化 |
| R137 | Sakai 2026《personality steering→cooperative behavior》(Sci Rep) | 2 | 重复囚徒困境 | Agreeableness主导合作；'人格steering是行为偏置非确定性控制' |
| R140 | 李昌锦等 2026《大语言模型的人格化对齐》(心理学报) | 2 | 道德两难判断（静态） | HEXACO六维提示×模型×任务类型交互；宜人性/尽责性人机方向完全逆转 |

**邻近度分布更新（行级）**：3级 18+4=**22**；2级 9+6=**15**；1级 1；0级 5。

**判决倾向修订（C4）**：机械落点**维持强EXTEND**，修订三点——①"agentic域交互存在性"卖点彻底不可用（PANDA/Peacemaker/R137三路占位，Gate1的降级判定被本轮确认并加重）；②"条件选择"被三路逼近（R109贝叶斯优化=query级、R128 IRIS=情境级、R129 AdaPA=agent域动态强度），Gate0活路(c)表述必须收紧为"**以行为原语反馈为触发器的过程内特质剂量调度**"以显式区隔AdaPA（其对象=用户偏好、结果=个性化对齐、无原语中介）；③活路(b)行为过程解释层在36新行后仍全空。待核实：R109 ARR全文、R129 PDF。

### 其他主张增量一览（行级计数，详见补充轮报告§三）

| 主张 | 新增行 | 增量要点 | 判决倾向 |
|---|---|---|---|
| C1 | 3级×3（R105/R106/R110）+2级×11 | 现象先行层更厚（含心理学报×2严对照佐证，混淆2）；差异句三件套（特质/策略×严对照×原语中介）愈发唯一活路 | 强EXTEND不变 |
| C2 | 2级×13 | "prompt人格效应≈内部方向"机制忠实版成定论（R113/R117/R116）+产业级方向-中介对（R118/R119）→卖点重心必须迁移到"方向→行为原语→任务成功率"链上验证 | 强EXTEND，卖点迁移 |
| C5 | 3级×1（R106）+2级×2 | 均仪器件（轨迹探索分析/过度纠偏探针/失败预测探针） | EXTEND不变 |
| C6 | 2级×7 | OpenReview池定向确认**仍全场最空**；lab灰色文献给产业级中介证据对（R118/R119/R134/R135/R136）但均无统计中介检验、非任务成功率口径 | EXTEND不变 |
| C7 | 2级×8 | 漂移×恢复完整交互仍无人做（最近=分离的R130预测与R114/R115修复）；但"一致性修复机制"已在ICML主会级成型→恢复目标必须钉在任务结果/行为原语而非人格保真 | 强EXTEND，表述钉位 |

> 注：本节行级邻近度直接取自定位表 R105–R140（行构建 agent 已按 §4.3 严评）；R107/R108/R109/R114 为墙后条目（摘要级/网页级定界），引用作靶前须按补充轮报告 §四.2 的条件触发器先做全文定界。**最终判决权属楠。**
