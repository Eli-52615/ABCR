# borderline 裁决队列（D3 楠裁边界输入）

生成: 2026-07-17 ｜ 共 **132** 条边界案例（来自7个收获文件`screen=borderline`全量grep）｜ 全部等楠裁决

说明：「为何边界」照录收获agent的screen_reason；已进定位表的条目标注行ID（借prox/交叉升级通道入表，不影响其borderline身份的裁决需求）。

## F1 人格/角色提示→任务表现（映射C1、C4）（16条）

| # | key | 标题 | 年份 | prox | 为何边界（screen_reason） | 定位表 | 裁决 |
|---|---|---|---|---|---|---|---|
| 1 | arxiv:2510.04491 | Impatient Users Confuse AI Agents: High-fidelity Simulations of Human Traits for Testing Agents | 2025 | 2 | trait方向向量(用户侧而非agent人格)→agent任务成功率降2-30%;C3式剂量可控+任务结果,但干预对象是用户模拟器 | R014 | 待楠裁决 |
| 2 | arxiv:2604.07102 | Persona Matters: Effects of Activation Steering on Short Answer Generation and Scoring | 2026 | 2 | 种子;干预=activation steering(非文本层,F2交叉),但结果=任务质量/评分且呈任务类型交互(C4-adjacent) | R007 | 待楠裁决 |
| 3 | arxiv:2604.11088 | Guardrails Beat Guidance: A Large-Scale Study of Rules, Skills, and Persistent Configuration for Coding Agents | 2026 | 2 | 干预=规则文件(含persona定义但非人格本身)→coding agent成功率;内容无关的context priming机制对C1对照设计是重要提醒 | R018 | 待楠裁决 |
| 4 | arxiv:2605.28037 | Personality, Role, and Expressive Style in Large Language Models: An Interactionist Analysis | 2026 | 1 | 人格×角色×风格的因子化交互设计(方法论参考,C4式设计),但结果=风格表达而非任务表现 | — | 待楠裁决 |
| 5 | arxiv:2605.06196 | The Granularity Axis: A Micro-to-Macro Latent Direction for Social Roles in Language Models | 2026 | 1 | 角色的线性潜在方向+因果转向证据(C2/C3同类方法),但结果变量=回应粒度/风格而非任务表现——更属F2版图 | — | 待楠裁决 |
| 6 | arxiv:2606.04057 | The Invisible Lottery: How Subtle Cues Steer Algorithm Choice in LLM Code Generation | 2026 | 2 | 非任务性提示线索→策略/算法选择(正确率恒定下的策略分布移动)——C6策略层结果变量的方法参考,非直接任务成功率 | — | 待楠裁决 |
| 7 | arxiv:2304.05335 | Toxicity in ChatGPT: Analyzing Persona-assigned Language Models | 2023 | 2 | 种子;人格→毒性(行为改变)证据强,但结果变量=毒性而非任务表现,处F1边界 | — | 待楠裁决 |
| 8 | arxiv:2506.07335 | Improving LLM Reasoning through Interpretable Role-Playing Steering | 2025 | 2 | 干预=SAE steering vector(非文本层,属F2/C3);但从role-play提示提取方向并测任务准确率,是C3剂量-行为的近旁证据 | R021 | 待楠裁决 |
| 9 | arxiv:2510.19331 | Algorithmic Fairness in NLP: Persona-Infused LLMs for Human-Centric Hate Speech Detection | 2025 | 2 | 人格→检测任务表现与公平;结果偏公平域但含检测性能测量 | — | 待楠裁决 |
| 10 | arxiv:2512.21352 | Multi-Agent LLM Committees for Autonomous Software Beta Testing | 2025 | 2 | 人格驱动行为变异是系统组件之一且测任务成功率,但人格效应未与模型多样性隔离 | R022 | 待楠裁决 |
| 11 | arxiv:2508.15835 | Alvorada-Bench: Can Language Models Solve Brazilian University Entrance Exams? | 2025 | 2 | role-playing为三提示条件之一×考试准确率+置信度校准(连C5);人格非核心研究对象 | — | 待楠裁决 |
| 12 | arxiv:2601.10809 | A Concise Agent is Less Expert: Revealing Side Effects of Using Style Features on Conversational Agents | 2026 | 2 | 风格特征提示的交叉副作用(简洁→专业度降),提示级与激活转向级干预对比;结果=感知风格而非客观任务成功率(C5风格/行为可区分性关键旁证) | R017 | 待楠裁决 |
| 13 | arxiv:2606.01755 | TriAlign: Towards Universal Truth Consistency in Personalized LLM Alignment | 2026 | 2 | 个性化/人格条件→客观任务准确率跨组不一致+缓解方法;重心在对齐方法而非人格效应本身 | — | 待楠裁决 |
| 14 | arxiv:2605.28187 | Whose Name Comes Up? III: Persona Prompting Effects in LLM-Based Scholar Recommendation | 2026 | 2 | 人格提示→推荐任务的事实性/覆盖度(任务质量维度存在但为审计域) | — | 待楠裁决 |
| 15 | arxiv:2601.15488 | Multi-Persona Thinking for Bias Mitigation in Large Language Models | 2026 | 1 | 多人格推理→bias降低为主,任务(推理)表现仅作维持性检查 | — | 待楠裁决 |
| 16 | arxiv:2601.18572 | One Persona, Many Cues, Different Results: How Sociodemographic Cues Impact LLM Personalization | 2026 | 1 | 人格线索构造方式的方法学敏感性(对C1实验设计的操纵有效性威胁),结果非任务表现 | — | 待楠裁决 |

## F2 激活转向与人格向量（映射C2、C3）（18条）

| # | key | 标题 | 年份 | prox | 为何边界（screen_reason） | 定位表 | 裁决 |
|---|---|---|---|---|---|---|---|
| 1 | arxiv:2605.09863 | Nautilus Compass: Black-box Persona Drift Detection for Production LLM Agents | 2026 | 1 | 黑盒(非激活层)人格漂移检测→F2边界外但C7(长程漂移)相关; 保留供裁决; 升级:规则命中(persona drift+agents) | R043 | 待楠裁决 |
| 2 | arxiv:2606.00545 | The Assistant as a Privileged Persona: A canonical reference in cross-persona self-recognition | 2026 | 1 | 人格向量几何×自我识别; C2几何背景, 与任务结果距离较远 | — | 待楠裁决 |
| 3 | arxiv:2607.00006 | Persona Without Substrate: Regime-Dependence and the LLM Individuation Problem | 2026 | 2 | 质疑'同一方向跨机制同指'——对C2/C3的跨机制外推(提示vs注入)是重要警示; 哲学框架+实验混合 | — | 待楠裁决 |
| 4 | arxiv:2604.17031 | Where is the Mind? Persona Vectors and LLM Individuation | 2026 | 1 | 人格向量文献的哲学整理(三种内部结构假说); 背景价值 | — | 待楠裁决 |
| 5 | arxiv:2602.04000 | After Talking with 1,000 Personas: Learning Preference-Aligned Proactive Assistants From Large-Scale Persona Interactions | 2026 | 2 | 激活转向做助手个性化适配(结果变量=时机决策/交互质量); C3应用域证据; 升级:规则命中(persona+generative agents) | R045 | 待楠裁决 |
| 6 | arxiv:2506.18887 | Steering Conceptual Bias via Transformer Latent-Subspace Activation | 2025 | 1 | 代码生成域的概念转向(结果=语言选择而非任务成败); C3外围; 升级:规则命中(steering+agentic systems) | — | 待楠裁决 |
| 7 | arxiv:2509.00328 | Mechanistic interpretability for steering vision-language-action models | 2025 | 2 | 具身域(VLA)方向→动作选择; C3跨域旁证; 升级:规则命中(steering+embodied agents) | R047 | 待楠裁决 |
| 8 | arxiv:2606.13038 | Nous: An Attempt to Extract and Inject the Cognition Behind Prediction-Market Behavior | 2026 | 2 | 提示层人格/认知注入→agent预测任务的null结果(C1阴性证据), 指向激活层注入的动机; 升级:规则命中(persona/profile+agents) | R039 | 待楠裁决 |
| 9 | arxiv:2511.07772 | SALT: Steering Activations towards Leakage-free Thinking in Chain of Thought | 2025 | 1 | CoT行为转向+任务性能保持; C3外围(隐私域); 升级:规则命中(steering+personal agents) | — | 待楠裁决 |
| 10 | arxiv:2510.22256 | SteerX: Disentangled Steering for LLM Personalization | 2025 | 1 | 个性化转向的数据去噪方法; C3方法外围 | — | 待楠裁决 |
| 11 | arxiv:2504.15133 | EasyEdit2: An Easy-to-use Steering Framework for Editing Large Language Models | 2025 | 0 | 转向实验基础设施(含人格模块); 工具价值 | — | 待楠裁决 |
| 12 | arxiv:2604.14593 | Mechanistic Decoding of Cognitive Constructs in Large Language Models | 2026 | 1 | 情绪构念的方向分解+双向因果转向; C2方法旁证, 域偏(情绪非人格特质); 升级:规则命中(steering+multi-agent) | R050 | 待楠裁决 |
| 13 | arxiv:2606.11399 | Scenario-based Probing and Steering Cultural Values in Large Language Models | 2026 | 2 | 价值观方向纠缠(轴间转移)+任务性能保持; C4类交互旁证(价值观域) | — | 待楠裁决 |
| 14 | arxiv:2511.05408 | Steering Language Models with Weight Arithmetic | 2025 | 1 | 权重空间方向转向(F2边界外)但与激活转向直接对比且涉sycophancy人格方向+任务性能保持; 供裁决 | — | 待楠裁决 |
| 15 | arxiv:2511.01689 | Open Character Training: Shaping the Persona of AI Assistants through Constitutional AI | 2025 | 2 | 人格塑造三方法对照(训练vs提示vs激活转向)+能力保持; C1/C3对照背景(训练层主线, F2边界侧) | — | 待楠裁决 |
| 16 | arxiv:2605.17144 | Contrastive Conceptor Activation Steering (COAST): Unlocking Vision-Language-Action Models through Hidden States | 2026 | 2 | 成功子空间转向→任务成功率大幅提升(具身域); C3×任务成功的跨域同构证据; 升级:规则命中(steer+task success rate) | R046 | 待楠裁决 |
| 17 | arxiv:2603.27518 | Over-Refusal and Representation Subspaces: A Mechanistic Analysis of Task-Conditioned Refusal in Aligned LLMs | 2026 | 2 | 行为方向的任务条件性(全局vs任务依赖子空间)——C4(任务×干预交互)的几何版本 | — | 待楠裁决 |
| 18 | arxiv:2507.11878 | LLMs Encode Harmfulness and Refusal Separately | 2025 | 2 | '判断方向'与'行为方向'可分——为C5(内部原语与表面行为可区分)提供几何先例 | — | 待楠裁决 |

## F3 角色扮演一致性与漂移（映射C7、C1边界）（15条）

| # | key | 标题 | 年份 | prox | 为何边界（screen_reason） | 定位表 | 裁决 |
|---|---|---|---|---|---|---|---|
| 1 | arxiv:2406.20094 | Scaling Synthetic Data Creation with 1,000,000,000 Personas | 2024 | 0 | 种子保留待裁：persona数据集/合成论文，边界规则排除'不含测量方法学的数据集论文'；作为persona资源背景保留。注：S2作者解析漏掉一作Tao Ge，arXiv元数据为准 | — | 待楠裁决 |
| 2 | arxiv:2606.14695 | Persona-Pruner: Sculpting Lightweight Models for Role-Playing | 2026 | 1 | 效率/剪枝方法论文，非漂移测量；作为滚雪球起点使用（其related work引出Persona Vectors与RPLA survey）。persona子网络隔离对C2(线性方向/子空间)有间接参考价值 | — | 待楠裁决 |
| 3 | arxiv:2605.14802 | A Heterogeneous Temporal Memory Governance Framework for Long-Term LLM Persona Consistency (ARPM) | 2026 | 2 | 长程persona一致性的外部记忆治理框架(漂移缓解)；无venue、工程日志式实验，质量存疑但主题在界内 | — | 待楠裁决 |
| 4 | arxiv:2604.14717 | Layered Mutability: Continuity and Governance in Persistent Self-Modifying Agents | 2026 | 2 | C7恢复/止损相关：身份滞回(hysteresis)与'回滚失败'初步实验；单作者概念框架，证据薄 | — | 待楠裁决 |
| 5 | arxiv:2601.08892 | Evaluating Role-Consistency in LLMs for Counselor Training | 2026 | 2 | 角色保持在对抗攻击下的领域特化评估（咨询训练）；界内但域窄 | — | 待楠裁决 |
| 6 | arxiv:2607.10428 | Enjoy Your Talk (EYT-Bench): A Human-Centered Benchmark for Multi-Turn Dialogue with Decoupled User Simulation, Target Modeling, and Judging | 2026 | 2 | 轨迹级drift度量(intent drift)+persona一致性+目标完成率同框；主结果偏intent非persona漂移 | — | 待楠裁决 |
| 7 | s2:616ef6e6751b37631cc2ffe4960170ac1590b221 | Multi-Turn Neural Transparency: Surfacing Neural Activations Improves User Calibration to LLM Behavioral Drift | 2026 | 2 | C2/C7交叉：激活空间trait方向的实时漂移监控界面（HCI取向，非任务结果） | — | 待楠裁决 |
| 8 | s2:39eed83033ab35a8e6fc320a0e6721e87c0ac672 | Measuring What Persists: Conditioning Mechanisms and a Geometric Framework for AI Agent Identity | 2026 | 2 | 漂移测量的几何框架+诚实负结果（150K token未测得真实漂移，此前信号系padding伪影）；单作者未发表 | — | 待楠裁决 |
| 9 | s2:2fd39530f526ae767845f306605b635dec270703 | I Know, but I Don't Know! How Persona Conflict Undermines Instruction Adherence in Large Language Models | 2026 | 2 | 题名指向persona冲突×指令遵循(C4/C1邻接)；S2摘要缺失、arXiv未收录，元数据(题目/作者/年份/venue=EACL)已核实但摘要不可得，待人工补查 | — | 待楠裁决 |
| 10 | s2:90f4ace4b5d9889183252eb3b3edcb9b76de14f5 | The Narrative Continuity Test: A Conceptual Framework for Evaluating Identity Persistence in AI Systems | 2025 | 2 | 身份持续性的纯概念评估框架(五轴含Persona/Role Continuity与自我纠错)；无实证测量 | — | 待楠裁决 |
| 11 | s2:7f575e1a8e4c465b31f8928ffd13ad48aa961789 | From Persona to Personalization: A Survey on Role-Playing Language Agents | 2024 | 0 | 背景survey(RPLA分类+评估taxonomy)，prox=0背景件 | — | 待楠裁决 |
| 12 | s2:ba1b0fbc0c3ae7ec12f08074de10856ebd6cb0c8 | Are Economists Always More Introverted? Analyzing Consistency in Persona-Assigned LLMs | 2025 | 2 | persona一致性跨任务/跨run的标准化分析框架；一致性×任务结构交互，非时序漂移 | — | 待楠裁决 |
| 13 | s2:02bd233262065611a89439e036ec42220e5739bb | Do Role-Playing Agents Practice What They Preach? Belief-Behavior Consistency in LLM-Based Simulations of Human Trust | 2025 | 2 | C6邻接：陈述信念→角色扮演行为→结果的一致性链测量(经济博弈)；非漂移但对中介链方法学有参考 | — | 待楠裁决 |
| 14 | s2:3d99d2277c04529a738724f6cb842ec12b5a5eee | The Autocorrelation Blind Spot: Why 42% of Turn-Level Findings in LLM Conversation Analysis May Be Spurious | 2026 | 2 | C7测量方法学警示：turn级漂移/一致性统计推断的自相关校正框架——凡做多轮漂移测量都需面对；单作者 | — | 待楠裁决 |
| 15 | arxiv:2604.28048 | Stable Behavior, Limited Variation: Persona Validity in LLM Agents for Urban Sentiment Perception | 2026 | 2 | C1设计参照：within-persona一致性+cross-persona变异+无persona对照三件套；域窄(城市感知标注)且非时序漂移 | — | 待楠裁决 |

## F4 LLM心理测量与效度批判（映射C5的理据层）（17条）

| # | key | 标题 | 年份 | prox | 为何边界（screen_reason） | 定位表 | 裁决 |
|---|---|---|---|---|---|---|---|
| 1 | arxiv:2311.04076 | Do LLMs exhibit human-like response biases? A case study in survey design | 2024 | 1 | 调查问卷响应偏差的系统检验（LLM作人类代理的效度），非人格构念本身——边界内侧。 | — | 待楠裁决 |
| 2 | arxiv:2408.07377 | Do GPT Language Models Suffer From Split Personality Disorder? The Advent Of Substrate-Free Psychometrics | 2024 | 1 | 跨语言人格测量不稳定+substrate-free心理测量学构想；方法较初步，作为跨语言不稳定证据保留。 | — | 待楠裁决 |
| 3 | arxiv:2605.16996 | Evaluation Drift in LLM Personality Induction: Are We Moving the Goalpost? | 2026 | 2 | 人格诱导评测的目标漂移批判：微调提升问卷稳定性但全维准确率近随机——测量与诱导交互的证据。 | — | 待楠裁决 |
| 4 | arxiv:2602.15669 | PERSONA: Dynamic and Compositional Inference-Time Personality Control via Activation Vector Algebra | 2026 | 2 | 激活空间人格方向的代数操纵（近正交、剂量可调）——C2/C3强相关但属转向频道而非测量效度，供跨前沿归并。 | — | 待楠裁决 |
| 5 | arxiv:2512.17639 | Linear Personality Probing and Steering in LLMs: A Big Five Study | 2025 | 2 | 线性人格方向探针有效但转向效应情境依赖（强迫选择可靠、开放生成受限）——C2/C3剂量-情境边界证据，属转向频道。 | — | 待楠裁决 |
| 6 | arxiv:2502.12109 | Generative Personality Simulation via Theory-Informed Structured Interview | 2025 | 2 | 测量理论驱动的结构化访谈替代量表施测，外部效度含行为结果预测——替代测量方法线。 | — | 待楠裁决 |
| 7 | arxiv:2605.30036 | Teaching Values to Machines: Simulating Human-Like Behavior in LLMs | 2026 | 1 | 价值-行为关系结构在价值诱导下与人类吻合（正面结果）；价值域而非人格域——边界内侧对照证据。 | — | 待楠裁决 |
| 8 | arxiv:2602.04033 | On the Credibility of Evaluating LLMs using Survey Questions | 2026 | 1 | 调查式评测方法论批判（解码/提示策略主导结果+结构一致性度量）；价值观域。 | — | 待楠裁决 |
| 9 | s2:364467630532a195296d31798aec49d43442c659 | Evaluating LLM Alignment under Big Five Personality Prompting | 2026 | 2 | Big Five人格提示对对齐行为的影响——C1相关。注：仅题录级核实（S2引文记录），摘要未获取。 | — | 待楠裁决 |
| 10 | s2:d42cfed8d6b68a4a7a1606142d171b9c3bbd474f | Quantifying and Mitigating Socially Desirable Responding in LLMs: A Desirability-Matched Graded Forced-Choice Psychometric Study | 2026 | 2 | 社会赞许作答的量化与强迫选择缓解方案——测量修正线。注：仅题录级核实，摘要未获取。 | — | 待楠裁决 |
| 11 | s2:dab723953ccfc6fef3807a9915cdb69e2c2cb916 | A validity-guided workflow for robust large language model research in psychology | 2025 | 1 | 心理学LLM研究的效度工作流（方法论指南，C5理据层背景）。注：仅题录级核实，摘要未获取；同作者另有姊妹篇From Prompts to Constructs(s2:f8dbbe1285250e3bbc1a77b983131391baced8f4)。 | — | 待楠裁决 |
| 12 | s2:1a17737e51c1fd4ecba8ff952f73fd4c9fb53914 | Vibe Check: Understanding the Effects of LLM-Based Conversational Agents' Personality and Alignment on User Perceptions in Goal-Oriented Tasks | 2025 | 1 | 人格×目标导向任务中的用户感知（外部效标视角）。注：仅题录级核实，摘要未获取；escalation按标题机械规则触发(personality+agents)。 | — | 待楠裁决 |
| 13 | arxiv:2512.00461 | Whose Personae? Synthetic Persona Experiments in LLM Research and Pathways to Transparency | 2025 | 1 | persona实验方法论综述（生态效度/透明度清单），C1实验设计的背景理据。 | — | 待楠裁决 |
| 14 | arxiv:2410.17632 | LMLPA: Language Model Linguistic Personality Assessment | 2024 | 1 | 从语言输出而非选项作答测人格的适配方案（开放式+AI评分）——测量改造线。 | — | 待楠裁决 |
| 15 | arxiv:2512.09149 | MindShift: Analyzing Language Models' Reactions to Psychological Prompts | 2025 | 1 | MMPI改造+人格强度分级的角色跟随测量——范式应用，效度批判性较弱。 | — | 待楠裁决 |
| 16 | arxiv:2605.05080 | The Pinocchio Dimension: Phenomenality of Experience as the Primary Axis of LLM Psychometric Differences | 2026 | 1 | 跨45问卷的模型间方差主轴不是人格特质而是自我表征立场——问卷测到的'是什么'的结构性证据。 | — | 待楠裁决 |
| 17 | arxiv:2603.00048 | MOSAIC: Unveiling the Moral, Social and Individual Dimensions of Large Language Models | 2026 | 1 | 问卷+行为游戏双通道基准（潜在的问卷-行为对照数据源）；道德/社会域为主。 | — | 待楠裁决 |

## F5 Agent行为原语与长程基准（核验/探索/坚持止损/校准四原语 + 轨迹失败分类学 + 长程可靠性基准；映射C5/C6/C7，ABCR结果变量仪器库）（37条）

| # | key | 标题 | 年份 | prox | 为何边界（screen_reason） | 定位表 | 裁决 |
|---|---|---|---|---|---|---|---|
| 1 | arxiv:2605.12894 | Beyond Cooperative Simulators: Generating Realistic User Personas for Robust Evaluation of LLM Agents (PPol) | 2026 | 1 | 用户侧persona多样性→agent任务成功（C1对偶方向）→升级 | — | 待楠裁决 |
| 2 | arxiv:2606.03467 | StepFinder: A Temporal Semantic Framework for Failure Attribution in Multi-Agent Systems | 2026 | 1 | 失败归因方法变体（效率向）；同类已收多篇 | — | 待楠裁决 |
| 3 | arxiv:2607.02882 | Diagnosis-Driven Automatic Repair for Agentic Workflow via Symbolic Inference (FlowFixer) | 2026 | 1 | 诊断→修复闭环（enhancement侧），归因部分可参考 | — | 待楠裁决 |
| 4 | arxiv:2606.31478 | One Reflection Is Not Enough: Self-Correcting Autonomous Research via Multi-Hypothesis Failure Attribution (SAGE) | 2026 | 1 | 核验原语的结构化升级（多假设归因），但绑定autonomous research域 | — | 待楠裁决 |
| 5 | arxiv:2605.27957 | DisasterBench: Benchmarking LLM Planning under Typed Tool Interface Constraints | 2026 | 1 | 可偷=FPoF指标；域特定(灾害响应) | — | 待楠裁决 |
| 6 | arxiv:2605.17439 | DiagEval: Trajectory-Conditioned Diagnosis for Reliable Software Evaluation with GUI Agents | 2026 | 1 | 测量效度问题（评测者误差vs被测缺陷）与ABCR结果测量相关 | — | 待楠裁决 |
| 7 | arxiv:2601.15625 | Robust Tool Use via Fission-GRPO: Learning to Recover from Execution Errors | 2026 | 1 | 训练方法，但error recovery rate指标可偷（恢复原语） | — | 待楠裁决 |
| 8 | arxiv:2604.10261 | The Amazing Agent Race: Strong Tool Users, Weak Navigators | 2026 | 1 | 可偷=互补诊断指标分解设计 | — | 待楠裁决 |
| 9 | web:uw-ast2025-tallm | A Taxonomy of Failures in Tool-Augmented LLMs | 2025 | 1 | 工具增强LLM失败分类学（web核实：UW官网PDF）；作者名单未完整核实 | — | 待楠裁决 |
| 10 | arxiv:2504.13367 | THOUGHTTERMINATOR: Benchmarking, Calibrating, and Mitigating Overthinking in Reasoning Models | 2025 | 1 | 难度校准×token预算（推理域非agent域） | — | 待楠裁决 |
| 11 | arxiv:2603.04751 | Evaluating the Search Agent in a Parallel World (Mind-ParaWorld) | 2026 | 1 | 止损瓶颈证据+去记忆混淆的评测设计 | — | 待楠裁决 |
| 12 | arxiv:2605.12947 | When Should an AI Workflow Release? Always-Valid Inference for Black-Box Generate-Verify Systems | 2026 | 1 | 统计学止损判据（optional stopping合法推断） | — | 待楠裁决 |
| 13 | arxiv:2606.27009 | Semantic Early-Stopping for Iterative LLM Agent Loops | 2026 | 1 | 止损策略+可复用的策略重放评测法 | — | 待楠裁决 |
| 14 | arxiv:2603.30031 | Cognitive Friction: A Decision-Theoretic Framework for Bounded Deliberation in Tool-Using Agents | 2026 | 1 | 止损的最优停止理论框架（单作者理论文） | — | 待楠裁决 |
| 15 | arxiv:2412.14737 | On Verbalized Confidence Scores for LLMs | 2024 | 1 | 言语化置信度方法学基线（非agent域） | — | 待楠裁决 |
| 16 | arxiv:2510.04265 | Don't Pass@k: A Bayesian Framework for Large Language Model Evaluation | 2025 | 1 | 可偷=贝叶斯不确定性评测协议 | — | 待楠裁决 |
| 17 | arxiv:2605.13841 | EVA-Bench: A New End-to-end Framework for Evaluating Voice Agents | 2026 | 1 | 可偷=峰值vs可靠能力gap分析（语音域） | — | 待楠裁决 |
| 18 | arxiv:2604.06132 | Claw-Eval: Towards Trustworthy Evaluation of Autonomous Agents | 2026 | 1 | 可偷=轨迹感知打分+pass^k鲁棒性协议 | — | 待楠裁决 |
| 19 | arxiv:2602.10525 | LHAW: Controllable Underspecification for Long-Horizon Tasks | 2026 | 1 | 可控歧义注入→澄清行为测量（提问原语） | — | 待楠裁决 |
| 20 | arxiv:2604.02022 | ATBench: A Diverse and Realistic Agent Trajectory Benchmark for Safety Evaluation and Diagnosis | 2026 | 1 | 轨迹失败诊断（安全域）；分层分类法可参照 | — | 待楠裁决 |
| 21 | arxiv:2511.20766 | OpenApps: Simulating Environment Variations to Measure UI-Agent Reliability | 2025 | 1 | 可偷=环境变体×可靠性协议（C4环境×行为交互近邻） | — | 待楠裁决 |
| 22 | arxiv:2511.07338 | DeepPersona: A Generative Engine for Scaling Deep Synthetic Personas | 2025 | 1 | persona生成工具（C1处理构造可用）；机械升级规则命中（personas+agentic behavioral simulation+task success） | — | 待楠裁决 |
| 23 | arxiv:2506.09902 | PersonaLens: A Benchmark for Personalization Evaluation in Conversational AI Assistants | 2025 | 1 | persona×task success评测框架→升级 | — | 待楠裁决 |
| 24 | arxiv:2509.11656 | MALLM: Multi-Agent Large Language Models Framework | 2025 | 1 | C4实验基础设施（persona×策略×协议可交叉配置）→升级 | — | 待楠裁决 |
| 25 | s2:b407d4c092cb273b55e403efb244742f603157e2 | How Many Tasks Are Enough for Agent Benchmark Decisions? A Replay Analysis of Public LLM Agent Benchmarks | 2026 | 1 | 可偷=部分运行决策协议（实验预算设计） | — | 待楠裁决 |
| 26 | s2:7003da639ae8634502956a9800796cd1fcbc6a64 | Beyond Static Leaderboards: Predictive Validity for the Evaluation of LLM Agents | 2026 | 1 | 评测预测效度立场（测量效度背景） | — | 待楠裁决 |
| 27 | s2:a847ab0537e30010588fd086e9d56c5fc99819d9 | From Agent Traces to Trust: A Survey of Evidence Tracing and Execution Provenance in LLM Agents | 2026 | 1 | 轨迹证据链survey（可追责性视角，与F5测量视角部分重叠） | — | 待楠裁决 |
| 28 | s2:2c88e19c8f21b8f9876c57e643ad3d5b492add27 | When Errors Become Narratives: A Longitudinal Taxonomy of Silent Failures in a Production LLM Agent Runtime | 2026 | 1 | 生产环境静默失败分类（运维视角） | — | 待楠裁决 |
| 29 | s2:740d99af1124a0b6d9e06b3aaf85e556f78e8cfa | EARS: Explanatory Abstention for Reliable Sub-Agent Modeling in Large-scale Multi-Agent Systems | 2026 | 1 | 弃权原语在MAS路由中的工程化 | — | 待楠裁决 |
| 30 | s2:255c9b4f091756d01d201857d3a11596a2f78678 | Beyond Prompt Engineering: Robust Behavior Control in LLMs via Steering Target Atoms | 2025 | 1 | C3方法背景（非agent任务域；机械升级规则未触发） | — | 待楠裁决 |
| 31 | s2:bdde8c8a3d1b6f9f89ad0a1c4b3175ddfa160fb8 | R-Horizon: How Far Can Your Large Reasoning Model Really Go in Breadth and Depth? | 2025 | 1 | 可偷=组合式长程压力测试构造法（推理域） | — | 待楠裁决 |
| 32 | s2:dce29a364185781a73fc16f186375b711a75b015 | Stop When Enough: Adaptive Early-Stopping for Chain-of-Thought Reasoning (REFRAIN) | 2025 | 1 | 止损判别器（推理域非agent） | — | 待楠裁决 |
| 33 | s2:5cc514aa3991704514015539a61547f7838e039e | Position: Agent Should Invoke External Tools ONLY When Epistemically Necessary | 2025 | 1 | 工具调用的认知必要性判据（校准×工具使用立场文） | — | 待楠裁决 |
| 34 | s2:99259d51eadfe2473fe8eb643625a6bd1c3c0a41 | WebCoT: Enhancing Web Agent Reasoning by Reconstructing Chain-of-Thought in Reflection, Branching, and Rollback | 2025 | 1 | 把核验/探索/回滚原语作为可蒸馏技能（原语操作化参照） | — | 待楠裁决 |
| 35 | s2:9ecfd344fad1ec75dcc18bae2770b94c3913a112 | Thinking Past the Answer: Evaluating Harmful Overthinking in Large Reasoning Models | 2026 | 1 | 可偷=reasoning sufficiency前缀协议（推理域） | — | 待楠裁决 |
| 36 | s2:1ac6b0d31ad221a6fb6b505585ccdb107d8b92cb | Survey on Evaluation of LLM-based Agents | 2025 | 1 | 评测survey（与Mohammadi survey重叠） | — | 待楠裁决 |
| 37 | arxiv:2602.23701 | From Flat Logs to Causal Graphs: Hierarchical Failure Attribution for LLM-based Multi-Agent Systems (CHIEF) | 2026 | 1 | 因果图归因方法变体（同类已收多篇；C6相关） | — | 待楠裁决 |

## F6 提示干预实验方法学与评测统计（横切全部主张；喂设计v2）（15条）

| # | key | 标题 | 年份 | prox | 为何边界（screen_reason） | 定位表 | 裁决 |
|---|---|---|---|---|---|---|---|
| 1 | arxiv:2605.17480 | The Capability Paradox: How Smarter Auditors Make Multi-Agent Systems Less Secure | 2026 | 2 | K5命中:agent系统中行为风格变量(语言确定性)的统计中介分析(74%中介占比,bootstrap CI)——C6轨迹中介链的实证范例 | — | 待楠裁决 |
| 2 | arxiv:2510.18170 | AgentChangeBench: A Multi-Dimensional Evaluation Framework for Goal-Shift Robustness in Conversational AI | 2025 | 2 | 机械升级规则命中(persona∧task success);恢复时间/冗余率指标与C7恢复止损测量相关 | — | 待楠裁决 |
| 3 | arxiv:2510.04265 | Don't Pass@k: A Bayesian Framework for Large Language Model Evaluation | 2025 | 2 | pass@k的贝叶斯替代——任务结果变量的可选统计方案 | — | 待楠裁决 |
| 4 | arxiv:2601.05420 | Efficient Inference for Noisy LLM-as-a-Judge Evaluation | 2026 | 2 | judge噪声下的半参数有效估计——统计工具进阶,可选进口 | — | 待楠裁决 |
| 5 | arxiv:2503.04474 | Know Thy Judge: On the Robustness Meta-Evaluation of LLM Safety Judges | 2025 | 2 | judge对风格/提示扰动的敏感性——风格与实质分离(C5)的反例证据;安全域特化 | — | 待楠裁决 |
| 6 | arxiv:2603.05399 | Judge Reliability Harness: Stress Testing the Reliability of LLM Judges | 2026 | 2 | judge可靠性压力测试工具(含格式/冗长扰动)——设计v2评分管线的验收工具候选 | — | 待楠裁决 |
| 7 | s2:f35e8cc662b5f50d5585c456fe5f302da682f8d1 | Validity Threats for Foundation Model Research | 2026 | 2 | 四类效度框架应用于FM研究设计——设计v2威胁清单的组织框架 | — | 待楠裁决 |
| 8 | arxiv:2603.14417 | Questionnaire Responses Do not Capture the Safety of AI Agents | 2026 | 2 | 问卷式测量对agent行为缺乏构念效度——人格自报告vs agent行为分离的论证(C1/C5背景) | — | 待楠裁决 |
| 9 | arxiv:2410.03492 | Towards Reproducible LLM Evaluation: Quantifying Uncertainty in LLM Benchmark Scores | 2024 | 2 | 重复实验不确定性量化的轻量方案 | — | 待楠裁决 |
| 10 | arxiv:2502.05150 | CodeSCM: Causal Analysis for Multi-Modal Code Generation | 2025 | 2 | K5命中:提示模态→(中介)→代码任务结果的SCM中介量化——C6可借用的形式化 | — | 待楠裁决 |
| 11 | arxiv:2603.16475 | Breaking the Chain: A Causal Analysis of LLM Faithfulness to Intermediate Structures | 2026 | 2 | 中介干预协议(对中间结构做受控编辑检验因果中介地位)——C6'人格→策略→动作'链的检验模板与反例警示 | — | 待楠裁决 |
| 12 | arxiv:2509.13680 | Prompt Stability in Code LLMs: Measuring Sensitivity across Emotion- and Personality-Driven Variations | 2025 | 2 | 人格/情绪模板化提示变体→代码任务通过率的稳定性评测——C1在代码域的等语义人格扰动方法 | — | 待楠裁决 |
| 13 | arxiv:2604.10733 | Too Nice to Tell the Truth: Quantifying Agreeableness-Driven Sycophancy in Role-Playing Language Models | 2026 | 2 | 人格特质维度→行为(阿谀)的量化统计关联(r/d效应量)——C1/C6人格→行为环节的测量范例;结果变量非任务成功故prox2 | — | 待楠裁决 |
| 14 | arxiv:2604.08362 | Towards Real-world Human Behavior Simulation: Benchmarking Large Language Models on Long-horizon, Cross-scenario, Heterogeneous Behavior Traces | 2026 | 1 | 机械升级规则命中(persona homogenization∧long-horizon);对F6仅背景(行为模拟基准效度),prox1 | — | 待楠裁决 |
| 15 | s2:48cc3f94879df191c6e6cbcd1a2fe9bdd5a4b6b7 | Prompt Robustness Is Task-Dependent: Comparing Objective and Belief-Style Questions in LLM Evaluation | 2026 | 2 | GEE统计建模提示鲁棒性的任务×扰动交互——C4交互效应检验的统计模板 | — | 待楠裁决 |

## F0 跨前沿杀伤查询扫描（kill-first）+ 中文平台线索扫描（14条）

| # | key | 标题 | 年份 | prox | 为何边界（screen_reason） | 定位表 | 裁决 |
|---|---|---|---|---|---|---|---|
| 1 | arxiv:2605.28037 | Personality, Role, and Expressive Style in Large Language Models: An Interactionist Analysis | 2026 | 2 | 触C5可分性：表达风格与角色即可诱导『人格印象』——风格/特质混淆是C5『原语与语言风格可区分』的直接威胁；但为对话域非agent任务。 | — | 待楠裁决 |
| 2 | arxiv:2605.06196 | The Granularity Axis: A Micro-to-Macro Latent Direction for Social Roles in Language Models | 2026 | 2 | 触C2/C3：角色空间主轴+因果转向（单调剂量方向）——C2/C3的角色域邻近证据；但结果变量是回应粒度非任务成功。 | — | 待楠裁决 |
| 3 | arxiv:2602.17881 | Understanding Unreliability of Steering Vectors in Language Models: Geometric Predictors and the Limits of Linear Approximations | 2026 | 2 | 杀伤C2线性假设的边界条件：行为表征非线性时方向法失效——为C2『线性方向介导』提供先验诊断与反例机制。 | — | 待楠裁决 |
| 4 | arxiv:2607.01802 | On the Limits of Steering Vectors for Preference-Aligned Generation | 2026 | 2 | 杀伤C3：特质方向的任务迁移与组合上限——writing域证据，需外推。 | R100 | 待楠裁决 |
| 5 | arxiv:2605.03907 | Steer Like the LLM: Activation Steering that Mimics Prompting | 2026 | 2 | 杀伤C2-C3衔接：prompt人格效应≠恒定方向加法（token特异干预）——若C2以恒定方向近似prompt效应会遇到此系统偏差。 | — | 待楠裁决 |
| 6 | arxiv:2602.00016 | PTCBENCH: Benchmarking Contextual Stability of Personality Traits in LLM Systems | 2026 | 2 | 触C7/C1交叉：情境→人格漂移→推理能力变化的反向链路（环境诱导人格再影响能力）；非agent域。 | — | 待楠裁决 |
| 7 | arxiv:2604.08401 | Verify Before You Commit: Towards Faithful Reasoning in LLM Agents via Self-Auditing | 2026 | 2 | Rule4升级（persona+long-horizon agentic）：persona用作核验多样性来源且联到端任务表现——C5核验原语×人格的交叉信号，但persona非自变量。 | — | 待楠裁决 |
| 8 | arxiv:2604.11259 | Mobile GUI Agent Privacy Personalization with Trajectory Induced Preference Optimization | 2026 | 2 | Rule4升级（persona+task success+agent）：人格→轨迹结构异质性（探索/防护动作差异）→与任务成功率的权衡——C5/C1在GUI agent域的邻近证据。 | — | 待楠裁决 |
| 9 | arxiv:2605.12894 | Beyond Cooperative Simulators: Generating Realistic User Personas for Robust Evaluation of LLM Agents | 2026 | 2 | Rule4升级（persona+agent+task success）：用户侧persona多样性→agent任务成功率——非agent自身人格但同一因果结构的对偶（用户人格→agent结果）。 | — | 待楠裁决 |
| 10 | arxiv:2605.29791 | ActTraitBench: Quantifying the Knowledge-Decision Gap in Large Language Models via Human-Grounded Behavioral Validation | 2026 | 2 | 触C5：自陈人格与行为决策系统性解离——支持『人格要用行为/轨迹测不能用问卷』，是C5测量学的关键背景；非agent任务域。 | R101 | 待楠裁决 |
| 11 | arxiv:2510.18170 | AgentChangeBench: A Multi-Dimensional Evaluation Framework for Goal-Shift Robustness in Conversational AI | 2025 | 2 | 触C7/C5：恢复时间(GSRT)与冗余率等轨迹级恢复/止损指标已被定义——C7交互项的度量先行；persona为情境变量非干预。 | — | 待楠裁决 |
| 12 | arxiv:2604.09682 | Decision-Theoretic Safety Assessment of Persona-Driven Multi-Agent Systems in O-RAN | 2026 | 2 | 触C1/C4：应用域(电信MAS)中persona配置→任务性能与级联效应——跨前沿盲区（非NLP venue），效应量已量化。 | — | 待楠裁决 |
| 13 | arxiv:2606.04057 | The Invisible Lottery: How Subtle Cues Steer Algorithm Choice in LLM Code Generation | 2026 | 2 | 触C4/C6：提示线索→策略(算法)选择分布的因果移动（固定正确性下）——『人格→策略→结果』链中『线索→策略』环节的强先行。 | — | 待楠裁决 |
| 14 | arxiv:2407.02099 | Helpful assistant or fruitful facilitator? Investigating how personas affect language model behavior | 2024 | 2 | C1方法学关键：等长/等语用中性对照（30个paraphrase对照组）设计先行——C1的『等长中性对照』设计必须引用并超越。 | — | 待楠裁决 |

