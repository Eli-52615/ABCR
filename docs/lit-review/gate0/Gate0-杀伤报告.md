# Gate 0 定界·杀伤报告（D2核心）

生成：2026-07-16 ｜ agent：Gate0定界 ｜ 方法：8个预检邻居逐一全文精确定界（arXiv HTML全文 / OpenReview PDF经Exa / HF+二级源）。所有2026年论文均API拉取真身，未凭记忆。

**输出路径说明**：父工作流传入的输出目录为字面量 `undefined`（模板变量失效），故本报告落在会话scratchpad：`/private/tmp/claude-501/-Users-superagent/e3f47fcf-d357-4000-874b-2b7379738094/scratchpad/gate0/Gate0-杀伤报告.md`。

**阅读覆盖声明**（诚实性）：#1、#2、#4、#5、#6为100%全文；#3约81%（正文+实验+结论100%，余下为附录C后半persona提示词表格与附录D–F评测协议，未读部分不含新实验结论）；#7 PDF两渠道被拒（HF直连TLS重置、ResearchGate 403），定界基于HF数据卡（含官方引用信息与五维结构、42/1452篇统计）+第三方slides提要，真身确认充分、内容定界中等置信；#8按任务要求快速定界，读约25%（摘要+引言+风险框架R1–R6+六轴定义节4.1–4.5全文+全文persona/personality/steering关键词上下文抽查）。

C1–C7邻近度刻度：3=同问题+同类结果变量；2=同问题不同结果变量或任务域；1=同域不同问题；0=背景。

---

## 邻居1 ｜ arXiv:2604.11048 —— A Systematic Analysis of the Impact of Persona Steering on LLM Capabilities（NPTI×六认知基准+DPR）

Chen, Wang, Xie, Feng, Liu（东北大学/NEU + SMU），v2 2026-05-12。

**① 干预变量**：NPTI（Neuron-based Personality Trait Induction，引Deng et al. ICLR'25）神经元级大五诱导：识别阶段在PersonalityBench上按激活概率差δ>τ选出各维正/负神经元集𝒩⁺/𝒩⁻；转向阶段推理时确定性调制（Methodology·Personality Trait Induction节：“h′ᵢ=hᵢ+α·h_ref if i∈𝒩⁺, suppressed if i∈𝒩⁻”）。10个极性条件（大五×高/低）+ α=0基线。DPR：TF-IDF检索式query级persona自适应路由（Leveraging Persona-Task Regularities节）。

**“神经元级”与激活转向的关系（核实项）**：同属表示层推理时干预家族，但作用对象是**稀疏特质神经元集合**（FFN内逐神经元加/抑），不是persona vector那种**单一线性方向向量**——与ABCR若用Chen et al.式方向转向属近亲不同支。未做α剂量-反应扫描（全文只出现α=0与固定α两档）。

**② 结果变量**：六静态基准准确率变化ΔAcc（式1）；RQ3极性差Gap；DPR为hit式准确率（“hit”=推荐集内至少一个persona能解题——偏oracle宽松口径，Evaluation节）。

**③ 任务域**：**纯静态**（IFEval指令遵循、MMLU-Pro/GPQA知识、BBH/MuSR多步推理、GSM8K数值推理）。零agentic、零工具、零多轮。核实项确认：任务域纯静态。

**④ 对照条件质量：1（部分）**。有：within-item逐题配对设计（Experimental Procedure节：“for every evaluation instance, both baseline and persona-steered conditions processed identical inputs under identical generation parameters”）、温度0、α=0 vanilla基线、RQ2处配对t检验（Fig.3气泡=−log₁₀p）。无：随机神经元/中性方向的安慰剂对照，无多种子方差，主热图无显著性标注。

**⑤ 邻近度**：C1:2（同问题“人格改变任务表现”，但任务域静态）；C2:2 / C3:2（表示层干预→基准表现已链上，但无剂量-反应、非agentic任务成功率）；**C4:3（静态）**——系统性人格×任务交互矩阵（10条件×6基准×多架构多尺度）+自适应选择机制（DPR）双要素齐备，仅缺agentic/长程；C5:0；C6:1（trait-process映射是相关性框架非统计中介）；C7:0。

**⑥ 杀伤评估：C4重创（静态半场被占满），C1重创**。按杀伤条件，C4致命需“覆盖长程agentic”——此文没有，故C4收缩到agentic域后仍活，但**“人格×任务交互存在系统规律+可用检索路由吃掉规律”这两句话在静态域已被此文说完**（含73.68%人类方向一致性、O/E主导、BBH全persona降−39.5%等硬数）。ABCR的C4必须以agentic长程+行为原语粒度重述，否则与此文只差换基准。

**对预判的修正**：C4静态≈3确认；C1≈2确认；补充：DPR的存在使“自适应人格选择”不能再作为ABCR的首创卖点，只能作“agentic域首个”。

---

## 邻居2 ｜ arXiv:2602.12285 —— From Biased Chatbots to Biased Agents: Examining Role Assignment Effects on LLM Agent Robustness

Cao, Sun, Yue，2026-01-21 v1。

**① 干预变量**：**人口学persona**（非特质/策略persona，核实项确认）：23个角色，4类（性别3、种族/来源6、宗教7、职业8，Table 1），以固定两轮对话前缀注入（Persona Prompting Setup节：“From now on, you are a [ROLE]…”，引Zhao et al. 2025），persona间措辞结构一致仅人口学内容不同。

**② 结果变量**：agentic任务成功率/奖励（ALFWorld成功率、WebShop reward、Card Game胜率、OS命令准确率、DB查询正确率）。**粒度=基准级聚合分**，无步骤级、无行为分解、无机制分析（Limitations自认“developing interpretability techniques…”为future work）。核实项确认：结果变量粒度粗。

**③ 任务域**：**agentic多步**（具身规划、电商决策、策略博弈、OS、DB；AgentBench家族+ALFWorld+WebShop）。

**④ 对照条件质量：1（部分）**。基线=“omits this prefix entirely”（纯vanilla）。**无等长中性对照**（如同模板的“you are a person/assistant”，核实项确认：没有），无显著性检验、无重复运行方差报告（deterministic decoding单次），效应表中大量±1–2%波动与−26.2%极值同表并列，噪声地板未标定。

**⑤ 框架（核实项）**：偏见/稳健性框架（robustness/bias/volatility），非匹配-优化框架；结论方向为“persona是脆弱性”，不含“选对persona提升agent”。

**⑤′ 邻近度**：**C1:3**（同问题：persona指派改变agentic任务成功率；同类结果变量：多步任务成功率/胜率）——注意持3的前提是ABCR的C1以宽口径表述（“persona/角色改变agentic任务成功率”）；若C1锁定“**特质**人格（大五/特质向量）+严格对照”则降至2–3之间。C4:1–2（有“推理型任务比技术型敏感”的任务依赖观察，无系统交互设计与自适应机制）；C2/C3:0（prompt级、无方向干预）；C5:0；C6:0；C7:0。

**⑥ 杀伤评估：C1重创非致命**。它自称“the first systematic case study showing that demographic-based persona assignments can alter LLM agents’ behavior and degrade performance”（Abstract/Intro）——**“persona改变agentic任务成功率”这个现象的占位权没了**。但按杀伤条件，C1致命需“等长/中性严格对照”：此文仅vanilla、无统计检验、人格类型是人口学身份而非特质维度、无剂量、无行为机制。致命线未过。

**对预判的修正**：C1 agentic=3（宽口径下），触发警报（见文末）；persona类型=人口学确认；无等长中性对照确认；结果变量粒度=聚合级确认。

---

## 邻居3 ｜ arXiv:2603.18507 —— Expert Personas Improve LLM Alignment but Damage Accuracy: Bootstrapping Intent-Based Persona Routing with PRISM

Hu, Rostami, Thomason（USC），2026-03-19 v1。

**① 干预变量**：专家persona**提示**（12个：8个MT-Bench任务匹配专家+4个行为persona；ExpertPrompting生成；三粒度full~150tok/short~75tok/min~5tok；system vs user placement操纵）；PRISM=意图门控LoRA自蒸馏（五阶段自举管线，无外部数据）。注意：**专家persona≠人格特质**，干预在prompt层非激活层。

**② 结果变量（核实项）**：三轴——MT-Bench生成质量（Qwen3-32B judge）、MMLU判别准确率、安全拒绝率（HarmBench/JailbreakBench/PKU-SafeRLHF），加15子类宏平均Overall。非agentic任务成功率。

**③ 任务域**：纯静态（生成/判别/安全）。零agentic。

**④ 对照设计质量（核实项）：2（本组最严）**。六策略对照：Base Model、**No-Sys（空系统提示）**、**Random Prompting（12 persona均值——随机persona对照）**、Expert Prompting、SFT无门控消融、PRISM（§5 Experimental Setup）；再加粒度（长度）三档与placement二档操纵（§3.1c/§3.3b），等于做了**提示长度混淆的显式剥离**：“the major performance gain from persona prompting is from the added context length”（§3.4，针对推理蒸馏模型）。弱点：主表仅±std无显著性检验。

**⑤ 邻近度**：C4:2（任务类型依赖的系统解释——“persona帮alignment依赖任务、伤pretraining依赖任务”——加**意图门控自适应机制**，但域为静态、维度为专家域非人格特质）；C1:1；C2/C3:0–1；C5:0；C6:1（机制解释：“persona prefixes activate the model’s instruction-following mode that would otherwise be devoted to factual recall”§3.1a，非统计中介）；C7:0。

**⑥ 杀伤评估：C4重创（第二击）**。与#1合看：静态域里“人格/角色×任务交互有规律+规律可被自适应机制利用”已被从两个不同干预层（神经元级、prompt级）各做一遍，且#3给了**为什么**的训练阶段解释（alignment vs pretraining能力分层）。ABCR C4剩余的活空间=（a）agentic长程域、（b）特质维度而非专家域、（c）以行为原语为中介的交互解释。对C1/C2/C3边缘。

**对预判的修正**：预检只说“核实对照与结果变量”——对照比预期严（含随机persona对照），结果变量三轴静态。威胁级别从待定确定为“C4重创、其余边缘”。

---

## 邻居4 ｜ arXiv:2604.07102 —— Persona Matters: Effects of Activation Steering on Short Answer Generation and Scoring

Wu & Henriksson（Stockholm University），v2 2026-07-08。

**① 干预变量**：Chen et al.（arXiv:2507.21509）persona vectors流程复刻：对比prompt生成→均值差向量（式1）→单一中层注入 h̃=h+α·v（式2）。7特质（evil/apathetic/hallucinating/humorous/impolite/optimistic/sycophantic）×正负向。**剂量-反应（核实项）：没有做**——“fix |α|=2.0 across models for comparability”（§2.3），仅方向±两档，层也固定（各模型中点层，§2.2）。

**② 结果变量（核实项）**：**非任务成功率**——(A) 生成侧：GPT-5.2 judge按ASAP-SAS人类量规打的归一化质量分效应Δt（式3）；(B) 评分侧：评分者校准偏移δ(j,s)（式4），15×15 scorer-learner交互矩阵，约20.25万判分。

**③ 任务域**：静态教育任务（短答生成+自动评分，ASAP-SAS，10个prompt，science vs ELA）。零agentic。

**④ 对照条件质量：1（部分）**。unsteered基线（α=0）+ **Mann-Whitney U显著性检验**（生成侧13/14、7/14、0/14条件显著；评分侧9/14、11/13、4/14），且做了长度-质量相关排查（r=−0.47）排除纯冗长解释（§4）。无随机方向/正交向量安慰剂对照，无等长概念（激活层干预）。

**⑤ 邻近度**：C2:2 / C3:2（**方向干预→任务表现质量**链路已立且带显著性，但无剂量-反应、结果变量是质量分非agentic成功率）；C4:2（**11×任务敏感度差**=Qwen3-32B上ELA mean|Δ|0.105 vs science 0.010，§3.2 RQ2——人格×任务交互的又一静态实锤，无自适应机制）；C1:1；C6:0；C7:0——但注意其结论列了未来方向：“investigate whether persona vectors can be used to monitor and control behavioral drift in deployed systems”（§5）——**C7空间被公开点名但未做**。

**⑥ 杀伤评估：C2/C3重创预警、C4追加重创、C7获赠一个引用锚点**。“steering behaves like perturbation, not style control”（§4）+双向皆降质的下左象限图（Fig.5）意味着ABCR若主张“方向干预可用于优化任务表现”，必须直面此文的“扰动论”；剩余空间=剂量-反应曲线+agentic任务成功率+特质-任务匹配的正向利用。

**对预判的修正**：预判问“是否做了剂量-反应、结果变量是否任务成功率”——答案双否。11×为任务间敏感度比值（交互强度），非剂量效应。

---

## 邻居5 ｜ OpenReview HpUDi5Pe8S —— Steering LLM Interactions Using Persona Vectors

匿名投稿（AAAI格式；预检标注AAAI'26 Bridge，PDF本身无venue栏，forum页被反爬墙挡、无法直接核对决议状态——以预检venue标注为准，置信中）。全文经 openreview.net/pdf?id=HpUDi5Pe8S（Exa抓取）读毕。

**① 干预变量**：Chen et al. 2025式persona vectors：Claude生成5对对立系统提示×20题→采激活→均值差 v=h̄⁺−h̄⁻→余弦对齐选层→单位归一→h̃=h+αv，**α=2固定**。名义大五，**实测只有外向性+尽责性两特质**（“Every mention of Big 5 traits refers to two target traits we chose: extraversion and conscientiousness”，Methods·Preliminaries）；神经质因“very low means and very high variances”被放弃（Limitations）。模型：Qwen2.5-7B-it、Llama3.1-8B-it。

**② 结果变量**：特质表达分0–100（GPT-4o judge，逐响应）。无任务成功率、无能力/质量指标、无幻觉率实测（引言声称prompt法“frequently increase hallucination rates”但未测）。

**③ 任务域**：长上下文多轮对话（“long conversations”条件）+单题条件。非agentic。

**④ 对照条件质量：1（部分）**。两基线：native（无任何干预）+ text prompting（系统提示同特质）。仅mean±std无检验；尽责性native缺失（表1“—”）；单题与长对话两设置结果方向相反。

**⑤ 漂移测量方法（C7核实项，重点）**：**没有真正的漂移测量**。所谓长上下文人格维持=在长对话条件下对响应打特质分后取均值方差，与text/native横比（Table 1：外向性 steering 98.57±2.50 vs text 95.42±2.67 vs native 26.67±16.27；尽责性 38.67±18.91 vs 36.25±22.42）。**无逐轮漂移曲线、无漂移的操作化定义、无漂移事件检测、无恢复行为、无漂移×任何东西的交互**。且自曝反例：单题设置下steering反而低于text prompt（85.08±21.51 vs 95.99±8.17，Table 2），结论口径也只敢说“a possible advantage”（Abstract）。

**⑥ 邻近度**：C7:2（同问题域——长程人格维持——但结果变量为汇总特质分、无漂移动力学与恢复）；C2/C3:1（方向干预→特质表达非任务结果）；C1:0–1；C4:0；C5:0；C6:0。

**⑦ 杀伤评估：C7边缘（名义占位，实质留白）**。它占掉的是一句话：“有人试过用persona vector替代文本提示做长上下文人格维持”。ABCR C7的核心（漂移的动力学测量×恢复行为交互）完全无人触碰；此文反而可作为“现有维持类工作连漂移都没定义”的靶子引用。

**对预判的修正**：预判为“C7相关、核实漂移测量方法”——核实结果：无漂移测量方法可言，威胁级从待定降为边缘。

---

## 邻居6 ｜ arXiv:2605.20530 —— AgentAtlas: Beyond Outcome Leaderboards for LLM Agents

Mazaheri & Mazaheri（UCSC/MIT），v2 2026-05-26。全文100%读毕（含附录A–G）。

**① 干预变量**：无（分类学+测量协议论文，无行为干预）。**全文0次出现persona/personality/trait字样**——与人格研究完全正交。

**② 结果变量**：协议输出——控制决策标签准确率、轨迹标签一致度、tool-context utility retention等（合成集上的评估者协议，非agent能力主张）。

**③ 任务域**：agentic评估方法学。四件套：六态控制决策分类（Act/Ask/Refuse/Stop/Confirm/Recover）；轨迹失败词表=AgentRx九类+两个正交层（primary_error_source×impact，§4.2）；15基准0/1/2覆盖审计（§6）；合成1342项×8模型×taxonomy-aware/blind协议研究（§7）。

**④ 对照质量**：n/a（对基准的审计量规0/1/2；协议研究内部为aware vs blind提示对照）。

**⑤ 与核验/坚持/止损原语的重叠度（核实项）**：**中度、互补型**。映射关系——止损/恢复 ↔ Stop门+Recover门+轨迹类“Recovery failure”；坚持失控 ↔ 轨迹类“Looping or over-action”（“continues past a reasonable stopping point”）+Stop门失败模式“Looping or making redundant edits”（Table 1）；核验 ↔ Confirm门（但语义是“用户签核”而非agent自我核验——ABCR的核验原语在六门里**没有**对应物，最近的是Ask门的不确定性澄清）。关键差异：AgentAtlas测的是**决策正确性标注**（该不该Stop），不是**行为倾向强度**（多久才肯止损）——ABCR原语作为人格的行为表型需要后者。

**⑥ 测量效度检验（核实项）：没有**。§8.1明列四类效度威胁并自认：“The synthetic labels may not measure real agent competence”（construct validity）；无human-validated校准子集（caveat ii）；blind-mapper未独立审计（≈3–5%误映射自估，附录B）；gold labels单模型族（Opus 4.7）生成。附录D数据反而展示测量脆弱性：去掉标签菜单后轨迹标签一致度掉14–40pp。

**⑦ 邻近度**：C5:2（原语测量问题的“测量半边”——词表+每门评估钩子+哪些基准能测哪个轴的地图——但无人格干预、无效度验证、无倾向刻度）；C7:1（Recover门相关，无漂移概念）；C1:0；C4:1（其审计可用于选ABCR的agentic基准）；C6:0。

**⑧ 杀伤评估：C5礼物（确认）**。三重可用性：(a) 六门词表直接做ABCR原语的操作化底座（止损=Stop/Recover门校准，坚持=anti-Looping，核验需自行补一门）；(b) 15基准审计表（Table A.1）现成告诉你τ-bench/ToolSandbox是control轴仅有的2分基准——ABCR选平台的捷径；(c) 其自认的效度缺口=ABCR做“人格干预下的原语测量+效度检验”时的引用靶。按杀伤条件“仅有效度检验的原语框架=礼物”——此文连效度检验都没有，礼物成色更足、威胁更低。

**对预判的修正**：C5礼物候选确认升级为确认礼物；补充：核验原语在其六门中无对应，是ABCR可声明的增量。

---

## 邻居7 ｜ Wang et al. 2026 —— A Survey for LLM Agent Trajectory Analysis: From Failure Attribution to Enhancement

**真身确认**：Junjie Wang, Yawen Wang, Mengzhuo Chen, Xiaofei Xie, Chunyang Chen, Fangwen Mu, Zhe Liu, Qing Wang（ISCAS中科院软件所为主，联系人junjie@iscas.ac.cn），2026年2月。**不在arXiv**——PDF托管于HF数据集 `RobinChen2001/A-Survey-for-LLM-Agent-Trajectory-Analysis`（LLMAgentTraceAnalysisSurvey.pdf），伴随GitHub榜单 `IcyFeather233/Awesome-LLM-Agent-Trajectory-Analysis`，ResearchGate页401193207。检索1452篇留42篇（结构化记录54条）。

**定界置信声明**：PDF直连两渠道失败（HF resolve被连接重置、RG 403），以下基于HF官方数据卡+codgician slides提要，未逐节读原文。

**① 干预/②结果变量**：n/a（survey，无实验）。

**③ 任务域/内容结构**：agentic轨迹分析方法学，五维：Failure Taxonomy（四镜头：阶段边界/能力模块/多智能体组织/环境交互模式）→ Failure Attribution（定位“failure becomes inevitable”的最早步）→ Monitoring（轨迹证据采集）→ Enhancement（修复面：prompt/工作流拓扑/verifier/监督者/工具接口）→ Datasets & Benchmarks。类目计数：归因方法18条、增强修复9条、失败分类8条、工具7条、基准8条、实证4条。

**④ 对照质量**：n/a。

**⑤ 邻近度**：C5:1（同域——agentic行为/轨迹测量——不同问题：42篇保留文献的分类体系中**无人格/特质/内因倾向维度**，全部以外因或能力性failure为对象）；C6:1（failure attribution是“行为→结果”归因的工程版，缺“人格→行为”前半段与统计中介框架）；C1/C2/C3/C4/C7:0。

**⑥ 杀伤评估：边缘（组织素材）**。价值在反向：它以1452→42的系统检索为ABCR提供了“轨迹分析文献里不存在人格前因这一维”的**文献空位证明**；其五维框架也可用来给ABCR的C6中介分析定位（人格→[归因框架的步级行为]→结果）。无任何主张被其占位。

**对预判的修正**：预判要求“先确认真身再定界”——真身与预判一致（trajectory analysis survey, failure attribution to enhancement），但注意它不在arXiv，引用时用HF/RG来源。

---

## 邻居8 ｜ arXiv:2605.16282 —— Taxonomy and Consistency Analysis of Safety Benchmarks for AI Agents

Li, Fung, Li, Ismail, Iqbal（McGill/Kean/Zayed），2026-04-11 v1。快速定界（读约25%：摘要、引言、R1–R6风险框架、§4.1–4.5六轴全文、关键词上下文抽查）。

**① 干预/②结果**：n/a（40+5个agent安全基准的方法学编目+12模型×4基准一致性实证：Kendall’s W=0.10, p=0.94——各评估维度间**排名无一致性**）。

**③ 任务域**：agent安全评估方法学。六轴（§4）：对抗压力源（user-directed/environmental/structural/agent-internal/multi-agent）、环境保真度、能力包络、评分方法、评估粒度、安全-效用耦合。

**④ 对照质量**：n/a。

**⑤ 邻近度**：C5:1（评估方法学同域，无原语无人格）；C1:1（间接：其编目的**PsySafe（ACL'24）**是“向多智能体注入黑暗人格特质→危险行为传播，HI-Traits攻击下Process Danger Rate 98–100%”——即“人格干预改变agentic行为”在**安全结果变量**上早有先例，§5.9）；其余0。

**⑥ 杀伤评估：边缘**。两点可用：(a) “the field disproportionately tests externally imposed rather than agent-internal risks”（Abstract）——agent内因倾向被系统性低测，与ABCR人格内因视角同向，可引作动机；(b) PsySafe条目提醒C1相关工作检索必须覆盖安全文献线（危险率≠任务成功率，故不改C1邻近度判定，但写作时须显式切割）。

**对预判的修正**：预判“边缘、快速定界即可”成立；增量发现=PsySafe线索。

---

# 邻近度3警报与重定位建议材料（供楠决断，本报告不做判决）

## 警报1：C1 ← arXiv:2602.12285《From Biased Chatbots to Biased Agents》

**现状**：该文已于2026-01占位“persona指派改变agentic多步任务成功率”这一现象（5个agentic基准、3模型、23 persona、最大−26.2%），且自称first systematic case study。若ABCR的C1表述为宽口径（“人格/角色设定影响agent任务成功率”），则同问题+同类结果变量=邻近度3。

**它的边界（= C1的活路清单）**：
1. **人格类型**：它只做人口学身份persona（性别/种族/宗教/职业），未碰特质persona（大五/性格维度）与激活层干预——“**特质**人格× agentic任务成功率”仍空白；
2. **对照**：仅vanilla省略前缀，无等长中性对照、无显著性检验、无重复运行——它自己够不到自设杀伤线，谁先做严格对照谁拿因果占位；
3. **粒度**：只有基准级聚合分，无步骤级行为分解——“人格通过**哪些行为**（核验/坚持/止损）影响成功率”完全没人做（正好接C5/C6）；
4. **框架**：偏见-脆弱性框架，无匹配-优化方向（“给任务选对人格提升agent”在agentic域无人做——注意静态域已被#1的DPR和#3的PRISM占）。

**可能的改写方向（材料）**：C1从“人格影响agentic成功率”（已被占）改写为——「特质级人格干预（prompt与激活双通道）在等长中性对照与统计检验下对agentic多步任务成功率的**因果**效应，及其**行为原语中介**」。即把C1的卖点从现象移到：特质维度×严格对照×机制粒度三件套。引用位置：该文作为动机（“现象已被粗粒度观察到，但无因果对照、无特质维度、无机制”）。

## 警报2：C4（静态半场） ← arXiv:2604.11048《NPTI persona steering》

**现状**：系统性人格×任务交互（10个大五极性条件×6认知域×4架构×5尺度，含方向一致性/极性差/人类一致性73.68%全套量化）+ 自适应人格选择机制（DPR检索路由，训练免费，MuSR +24.57%）——C4致命条件的前两个要素在**静态域**齐备，邻近度3（静态）。且#3 PRISM在prompt层用意图门控又做了一遍“何时该用persona”的自适应机制，#4给了任务敏感度11×的第三方交互证据。

**它的边界（= C4的活路清单）**：
1. **域**：三文全部静态基准，无一步工具调用——C4按杀伤条件自动收缩为“agentic/长程域的人格×任务交互+自适应选择”，此处仍无人；
2. **交互的解释层**：#1用认知科学理论（CB5T/ACT）对表、#3用训练阶段（alignment vs pretraining）解释，都不含**行为过程**解释——长程任务里人格通过核验/坚持/止损等原语与任务结构交互，这一层无人碰；
3. **选择机制的粒度**：DPR是query级TF-IDF检索、PRISM是query级意图门控，均为**单步路由**；长程任务的**过程内**（mid-trajectory）人格调度无人做；
4. **DPR口径弱点**：hit式评估偏oracle（推荐集命中即算对），agentic域做严格的端到端成功率路由即形成方法学升级。

**可能的改写方向（材料）**：C4改写为——「长程agentic任务中的人格×任务（×阶段）交互结构，及基于行为原语反馈的过程内自适应人格调度」；将#1/#3/#4定位为静态域先行证据（引为“交互规律在静态域成立，但静态规律不能外推到含工具反馈回路的长程任务”——可借#8的环境保真度偏置发现做外推性质疑的引证）。

## 非3级但需写作纪律的两条脚注

- **C2/C3 ←（#4）**：方向干预→任务质量链路+显著性已在静态教育域建立且结论是“扰动非风格控制”；ABCR做剂量-反应时必须把#4列为最近邻并以agentic任务成功率+剂量曲线划界。当前判2，不触发警报，但若ABCR的C2/C3表述不含“剂量-反应/agentic”二要素之一，会滑向3。
- **C1安全线脚注 ← PsySafe（经#8）**：黑暗人格注入→多智能体危险行为（2024）已存在；C1写作需显式切割“任务成功率”与“安全危险率”两类结果变量。

## 礼物清单（正向可用）

| 来源 | 礼物 | 用法 |
|---|---|---|
| #6 AgentAtlas | 六门控词表+15基准审计+自认效度缺口 | C5原语操作化底座；选τ-bench/ToolSandbox做control轴；引其效度缺口立ABCR增量 |
| #7 Wang survey | 1452→42的文献空位证明（无人格维度） | C5/C6定位陈述 |
| #4 §5结论 | 点名“persona vectors监测行为漂移”为未来方向 | C7动机引用 |
| #5 | 长上下文维持类工作连漂移都未定义 | C7的靶子引用 |
| #8 | agent-internal风险被系统性低测；W=0.10排名不一致 | 动机+基准选择方法学警示 |
