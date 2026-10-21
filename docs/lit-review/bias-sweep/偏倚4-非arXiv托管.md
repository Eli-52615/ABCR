# 偏倚4：非arXiv托管的学术物 —— 侦察报告

日期：2026-07-17 ｜ agent：残余偏倚侦察轮·偏倚项4 ｜ 去重基线：deliverables/定位表.csv（105行，R001–R104）
硬约束执行：所有上报候选均有可访问URL；元数据经 OpenReview API 原始JSON（curl直取，绕过摘要模型转述）、ACL Anthology页面直取或 exa 全文抓取核实。凡"标题在渠道摘要中出现但无法二次核实"者已剔除或明确标注。

---

## ① 渠道×查询日志

| # | 渠道 | 查询/入口 | 工具 | 结果 |
|---|------|-----------|------|------|
| 1a | OpenReview UI | openreview.net/search?query=persona+agent | WebFetch | ❌ UI返回"Missing search term"错误（参数名不兼容），改走API |
| 1b | OpenReview API v2 | /notes/search?term=persona+steering | WebFetch | ✅ 20条，多条新候选 |
| 1c | OpenReview API v2 | term=personality+task+performance | WebFetch | ✅ 多为人格识别类，1条新（Editing Personality等已知域） |
| 1d | OpenReview API v2 | term=persona+drift+agent | WebFetch | ✅ BRIDGE、Examining Persona Drift（=R060系）、DRIFT-BENCH等 |
| 1e | OpenReview API v2 | term=character+drift+language+model | WebFetch | ✅ Side Effects of Character Training、Thinking in Character等 |
| 1f | OpenReview API v2 | term=role-play+agent+task+success | WebFetch | ✅ ECIR role-play rankers、Kong et al.（R004已引）等 |
| 1g | OpenReview API v2 逐条核实 | curl /notes/search?term=<精确标题>（9次） | Bash curl | ✅ 原始JSON核实9条候选的标题/作者/venue/摘要 |
| 1h | OpenReview API v2 | /notes?id=<forum> 单条直取 | WebFetch/curl | ❌ 302重定向到人机challenge墙（记录：单条note端点被墙，search端点可用） |
| 2a | ACL Anthology | persona/personality→task performance 角度 | exa定向 + WebFetch逐页核实 | ✅ PANDA、Licato&Steinle、Risk-Taking、CHOIR等；单页直取（aclanthology.org/2025.acl-long.1515/等）可达 |
| 2b | ACL Anthology | role-play/character consistency→下游任务 角度 | exa定向 | ✅ Dynamic Persona Coherence、RoleCDE、R-CHAR、MREval等 |
| 3a | Anthropic | anthropic.com/research 直查 + 定向搜索 | WebFetch + exa | ✅ 页面可达；新发现 Teaching Claude why（2026-05-08）、Persona Selection Model（alignment.anthropic.com，非arXiv） |
| 3b | OpenAI | openai.com/research/index | WebFetch | ❌ 403 Forbidden；但 cdn.openai.com PDF 可达（Persona Features Control Emergent Misalignment） |
| 3c | DeepMind/Meta | 定向搜索 persona/character/steering×capability | exa | ⚠️ 未发现独立于arXiv的相关技术报告（Who's asking?=Google但arXiv托管）；两家publications页未直接枚举（JS重） |
| 4a | HuggingFace papers | huggingface.co/papers?q=persona+agent / personality+steering | WebFetch ×3 | ❌ 连续 ECONNRESET（搜索页对WebFetch不可达） |
| 4b | HuggingFace papers | 经exa抓取hf.co/papers页 | exa | ✅ 抓到 hf.co/papers/2512.07092（Geometry of Persona）、2606.02470（MCP-Persona，人格≠personality，排除）等；R002/R006/R099已在表 |
| 5a | METR/Apollo/Redwood | persona/personality×agent reliability | exa | ✅ METR Frontier Risk Report 2026、Agent Incidents目录、METR对Anthropic sabotage报告的评审（提及"deceptive AI persona"）；Apollo以scheming为轴无persona专文；Redwood: behavioral selection model博文 |
| 5b | Redwood | 第二角度：character/persona×control | exa | ✅ Ctrl-Z（arXiv托管，prox 1）、behavioral selection model（非arXiv，prox 1） |
| — | brave-search MCP | 全程 | — | ❌ 整个会话 fetch failed，全部改用 exa |

---

## ② 新候选清单（均已grep定位表确认不在表内）

**格式**：标题｜作者｜年份｜托管地｜一句发现｜prox｜触及主张｜证据引句｜URL
**托管标记**：〔纯非arXiv〕= 未发现arXiv版；〔双托管〕= 同时有arXiv版（主综述漏检属查询角度缺口而非托管缺口）。

### A. prox 3（1条）

**A1. Persona Dynamics: Unveiling the Impact of Persona Traits on Agents in Text-Based Games (PANDA)**｜Seungwon Lim, Seungbeen Lee, Dongjun Min, Youngjae Yu（Yonsei）｜2025｜ACL 2025 Long（〔双托管〕arXiv 2504.06868）｜16种人格类型（Big Five高低极+黑暗三联）投射进agent策略管线，跑25个text-based games（Jiminy-Cricket），人格类型系统性改变agent任务表现，高Openness显著占优｜**prox 3**｜C1/C4（次及C5：从轨迹分析人格化行为）｜"By deploying agents embodying 16 distinct personality types across 25 text-based games and analyzing their trajectories… certain personality types, such as those characterized by higher levels of Openness, display marked advantages in performance."｜https://aclanthology.org/2025.acl-long.1515/ ＋ https://arxiv.org/abs/2504.06868

### B. prox 2（24条）

**B1. Steer Like the LLM: Activation Steering that Mimics Prompting**｜Geert Heyman, Frederik Vandeputte（Nokia Bell Labs）｜2026｜ICML 2026（poster页66813；GitHub称spotlight）＋arXiv 2605.03907〔双托管〕｜把prompt steering形式化为激活干预并蒸馏成token级系数的PSR模型，性能接近/超过prompting——直接支撑"prompt人格效应≈方向干预"的C2桥｜prox 2｜C2/C3｜"PSR models…achieve performance close to or exceeding prompt steering…compare favorably to prompting on AxBench and persona steering."｜https://icml.cc/virtual/2026/poster/66813

**B2. Probing Persona-Dependent Preferences in Language Models**｜Oscar Gilg, Pierre Beckmann, Daniel Paleka, Patrick Butlin｜2026｜ICML 2026 Mech Interp Workshop Poster〔纯非arXiv，OpenReview核实〕｜残差流线性probe预测不同persona下的成对任务选择，发现跨persona共享的偏好机制——C4"条件选择"的内部机制证据｜prox 2｜C2/C4｜"We train linear probes on residual-stream activations…finding shared preference machinery across personas including adversarial variants."｜https://openreview.net/forum?id=uPF7ocza0O

**B3. Refusal Lives Downstream of Persona in Chat Models**｜Viola Zhong, Qirui Li｜2026｜ICML 2026 Mech Interp Workshop〔纯非arXiv〕｜persona方向与refusal方向"方向依赖"：沿关系型persona方向steering可宽谱控制拒绝行为——人格方向→行为的因果链但结果变量是refusal非任务成功率｜prox 2｜C2/C6-邻｜"we find that they are directionally dependent: personas can condition refusal…steering toward a 'compliant' pe[rsona]…"｜https://openreview.net/forum?id=QcnqeJzwBq

**B4. Behavioural Asymmetry Across Activation Interventions for Big Five Personality Control in LLMs**｜Hala Sheta｜2026｜ICML 2026 MusIML Workshop Poster〔纯非arXiv〕｜系统比较activation addition/probe steering/ablation对Big Five双向控制：加法干预可靠、其余仅部分控制——C3剂量/方向操纵的方法学地图｜prox 2｜C3/C2｜"systematically compare different interventions for steering Big Five personality traits…across both high- and low-trait directions"｜https://openreview.net/forum?id=X89cn3iy8b

**B5. Playing Devil's Advocate: Off-the-Shelf Persona Vectors Rival Targeted Steering for Sycophancy**｜Ishaan Kelkar, Nebras Alam, Vikram Kakaria, Madhur Panwar, Vasu Sharma, Maheep Chaudhary｜2026｜ICML 2026 CompLearn Poster + Pluralistic-Alignment WS〔纯非arXiv〕｜通用persona向量（doubt/scrutiny）达到定向CAA 68–98%的去谄媚效果且用户正确时保准确率——人格方向→行为结果+副作用控制｜prox 2｜C2/C3｜"whether off-the-shelf persona steering vectors, originally developed for general role-playing…can serve as an alternative [to CAA]"｜https://openreview.net/forum?id=SlXKeoJsMM

**B6. Steering Personas Steers Safety: How Personality Trait Vectors Encode Safety-Critical Directions in LLMs**｜（ARR匿名）｜2026｜ACL ARR 2026 May Submission〔纯非arXiv〕｜5模型×5人格向量×3安全向量的8×8余弦矩阵：人格方向与安全方向几何耦合、耦合度预测副作用、可线性移除｜prox 2｜C2｜"whether persona directions are geometrically coupled with safety-relevant directions, whether this coupling predicts side effects, and whether it is linearly removable"｜https://openreview.net/forum?id=sBcYIHknFx

**B7. Steering at the Source: Style Modulation Heads for Robust Persona Control**｜Yoshihiro Izawa, Gouki Minegishi, Koshi Eguchi, Sosuke Hosokawa, Kenjiro Taura｜2026｜ICLR 2026 Re-Align Workshop＋arXiv 2603.13249〔双托管〕｜仅3个attention head独立支配persona/风格形成；头级干预实现行为控制且规避残差流steering的连贯性degradation｜prox 2｜C2｜"a sparse subset of attention heads (only three heads) that independently govern persona and style formation"｜https://openreview.net/forum?id=JlO2MCzUto

**B8. BRIDGE: Triangular Fixed-Point Refinement for Long-Horizon Persona Consistency**｜Yinghui Jiang, Bocheng Xu, Jianye Xie, Haotong Sun｜2026｜**ICML 2026 主会**（regular）〔OpenReview核实，未见arXiv版〕｜长程对话agent的latent state drift：言、内部表征、记忆三者静默背离，"非对称断裂风险"——多轮局部连贯被单次高代价矛盾摧毁；三角不动点耦合O/L/M修复｜prox 2｜C7｜"Long-horizon dialogue agents suffer from latent state drift: what an agent says, what it internally represents, and what it stores in memory can diverge silently across turns. This creates asymmetric rupture risk…"｜https://openreview.net/forum?id=itYG95jkKx

**B9. Beyond Static Persona Consistency: Dynamic Persona Coherence in LLM Role-Playing**｜（见页）｜2026｜ACL 2026 Long〔ACL Anthology托管〕｜身份层稳定与适应层演化解耦；PCC评估器+PDS漂移抑制器构成闭环"自主连贯性修复"（+16–84% PCC）——漂移×修复机制已在role-play域成型｜prox 2｜C7｜"a closed-loop alignment system…(Persona Drift Suppressor, PDS) enables autonomous coherence repair"｜https://aclanthology.org/2026.acl-long.1336/

**B10. Endogenous Resistance to Activation Steering in Language Models (ESR)**｜Alex McKenzie, Keenan Pepper, et al.（AE Studio系）｜2026｜ICLR 2026 Trustworthy AI Workshop〔OpenReview核实〕｜模型在任务失配steering持续生效时自发抵抗并**中程恢复**——"注入方向后的行为恢复"现象，直接关联C7的恢复原语与C3的剂量有效性边界｜prox 2｜C3/C7｜"large language models can spontaneously resist task-misaligned activation steering during inference, recovering mid-generation even when steering remains active"｜https://openreview.net/forum?id=6LfXccur0Z

**B11. Do Persona-Infused LLMs Affect Performance in a Strategic Reasoning Game?**｜John Licato, Stephen Steinle｜2025｜IJCNLP-AACL 2025〔ACL Anthology托管，未见arXiv版〕｜PERIL战棋游戏：人格prompt→（人格问卷中介翻译→启发式值）→策略表现；**只有经结构化中介翻译人格才改变行为**，直接persona prompt不足以产生差异化行为｜prox 2｜C1/C6（中介结构工程化实现，非统计中介检验）｜"strategic personality traits improved performance only when using a structured translation process…to convert LLM-generated responses into heuristic values"｜https://aclanthology.org/2025.ijcnlp-long.186/

**B12. How Personality Traits Shape LLM Risk-Taking Behaviour**｜（见页）｜2025｜Findings of ACL 2025〔ACL Anthology托管〕｜Big Five干预（尤其Openness）改变LLM在CPT框架下的风险倾向，先进模型复现人类人格-风险模式｜prox 2｜C1/C4/C5-邻（风险倾向≈探索/校准原语的近亲）｜"Interventions on Big Five traits, particularly Openness, influence the risk-propensity of several LLMs"｜https://aclanthology.org/2025.findings-acl.1085/

**B13. Effects of personality steering on cooperative behavior in large language model agents**｜M. Sakai, M. Yokoyama, W. Tateishi, et al.｜2026｜**Scientific Reports（Nature子刊，非arXiv期刊渠道）**｜重复囚徒困境中Big Five逐维极值操纵→合作行为：Agreeableness主导；显式人格信息提高合作但增加被剥削脆弱性——"人格steering是行为偏置而非确定性控制"｜prox 2｜C1/C4｜"agreeableness is the dominant factor promoting cooperation across all models…personality steering acts as a behavioral bias rather than a deterministic control mechanism"｜https://www.nature.com/articles/s41598-026-56163-8 (DOI 10.1038/s41598-026-56163-8)

**B14. Teaching Claude why**｜Anthropic (Alignment)｜2026-05-08｜anthropic.com/research〔纯非arXiv〕｜宪法/character训练（教"为什么"）→agentic misalignment率骤降（勒索倾向96%→≈0）；人格/价值中介agentic行为结果的产业级证据｜prox 2｜C1/C6-邻｜"teaching the principles underlying aligned behavior can be more effective than training on demonstrations alone"（结果变量=agentic misalignment率）｜https://www.anthropic.com/research/teaching-claude-why

**B15. Persona Features Control Emergent Misalignment**｜OpenAI｜2025-06｜cdn.openai.com PDF（＋arXiv 2506.19823〔双托管〕）｜SAE model-diffing发现"toxic persona"特征**介导**emergent misalignment，沿方向双向steering可预测/控制——方向介导行为的中介证据（结果=misalignment非任务成功率）｜prox 2｜C2/C6｜"One feature representing a 'toxic persona' is particularly effective in mediating emergent misalignment…steering the model toward and away from the corresponding direction"｜https://cdn.openai.com/pdf/a130517e-9633-47bc-8397-969807a43a23/emergent_misalignment_paper.pdf

**B16. How Role-Play Shapes Relevance Judgment in Zero-Shot LLM Rankers**｜Yumeng Wang, Jirui Qi, Catherine Chen, Panagiotis Eustratiadis, Suzan Verberne｜2026｜ECIR 2026（＋CoRR 2025〔双托管〕）｜role-play prompt→排序准确率提升，且role信号编码于早层、特定attention heads承载role条件化相关性判断——prompt人格→机制→任务表现三点连线（任务域=静态IR）｜prox 2｜C1/C2｜"Role-play signals encoded in early layers; attention heads critical for role-conditioned relevance"｜https://openreview.net/forum?id=Y8vyCvJdMm

**B17. Activation-Space Personality Steering: Hybrid Layer Selection for Stable Trait Control**｜（见页）｜2026｜EACL 2026 Long〔ACL Anthology托管〕｜人格特质占据低秩共享子空间；验证+动态层选择实现双向steering且保流畅性/能力、方差大幅下降｜prox 2｜C2/C3｜"personality traits occupy a low-rank shared subspace…careful perturbations without impacting the fluency, variance and general capabilities"｜https://aclanthology.org/2026.eacl-long.300/

**B18. Persona Prompting as a Lens on LLM Social Reasoning**｜（见页）｜2026｜EACL 2026 Long〔ACL Anthology托管〕｜人口学persona提升最主观任务（仇恨言论）分类但劣化rationale质量——任务成绩×解释质量的trade-off｜prox 2｜C1｜"PP improving classification on the most subjective task (hate speech) but degrading rationale quality"｜https://aclanthology.org/2026.eacl-long.52/

**B19. CHOIR: Harmonizing Structured Persona Diversity for Robust Collaborative LLM Reasoning**｜（见页）｜2026｜ACL 2026 Long〔ACL Anthology托管〕｜最小人口学persona扰动改变推理轨迹与正确答案集合；token级logit调和多persona信号→推理提升至+20.1%——人格扰动→任务成绩的正向利用｜prox 2｜C1/C4｜"even minor demographic perturbations in personas, such as simple pronoun swaps, can alter reasoning trajectories"｜https://aclanthology.org/2026.acl-long.2175/

**B20. R-CHAR: A Metacognition-Driven Framework for Role-Playing in LLMs**｜（见页）｜2025｜EMNLP 2025 Main〔ACL Anthology托管〕｜role-consistent分层自适应推理→SocialBench任务成绩大幅提升（长上下文34.64%→68.59%）——人格一致性工程→任务成功率的正向链｜prox 2｜C1-邻/C7-邻｜"concise thinking processes can achieve superior performance…in role-playing social intelligence tasks"｜https://aclanthology.org/2025.emnlp-main.1372/

**B21. Beyond Static Personas: Situational Personality Steering (IRIS)**｜（ARR/Findings）｜2026｜Findings of ACL 2026（另有CoRR〔双托管〕）｜LLM人格情境依赖+情境-行为模式一致；神经元级Identify–Retrieve–Steer实现情境自适应人格——C4"条件选择"的干预侧实现｜prox 2｜C4/C3｜"we first demonstrate the existence of situation-dependency and consistent situation-behavior patterns within LLM personalities"｜https://aclanthology.org/2026.findings-acl.958/

**B22. The Geometry of Persona: Disentangling Personality from Reasoning in LLMs（Soul Engine）**｜Zhixiang Wang｜2025｜arXiv 2512.07092（HF papers页收录）〔双托管；主综述HF渠道线索〕｜Big Five线性子空间+向量算术α剂量注入，"零样本人格注入"保持通用智能基准无损｜prox 2｜C2/C3｜"v_Neutral + α·v_Villain…precise control over behavior…with negligible degradation in general intelligence benchmarks"｜https://huggingface.co/papers/2512.07092

**B23. Persona Cartography: Charting Language Model Personality Traits in Weight Space**｜（见页）｜2026｜arXiv 2607.07916〔双托管；lab检索浮现〕｜权重空间trait-LoRA：目标特质随scale近单调（剂量-反应形态）、可加合成、中等剂量下能力基准保持；特质轴影响下游安全行为｜prox 2｜C3/C1｜"each adapter moves its target trait largely monotonically with scale, combines approximately additively…and preserves performance on capability benchmarks at moderate scales"｜https://arxiv.org/abs/2607.07916

**B24. Open Character Training: Shaping the Persona of AI Assistants through Constitutional AI**｜Sharan Maiya, Henning Bartsch, Nathan Lambert, Evan Hubinger｜2025｜arXiv 2511.01689〔双托管〕｜首个开源character training；比system prompt与activation steering更抗对抗性break-character，通用能力基准几乎无损——人格植入方式×稳固性×能力代价的三方比较｜prox 2｜C1/C7｜"these changes are more robust to adversarial prompting than the above two alternatives…little to no effect on general capabilities"｜https://arxiv.org/abs/2511.01689

**B25. Thinking in Character: Advancing Role-Playing Agents with Role-Aware Reasoning**｜（见OpenReview）｜2025｜NeurIPS 2025〔OpenReview核实〕｜针对role-play agent的attention diversion与style drift的推理优化——RPA域的漂移矫正｜prox 2（保守可降1）｜C7-邻/C1-邻｜"addresses attention diversion and style drift in role-playing agents through reasoning optimization"｜https://openreview.net/forum?id=geNdDlzKTG

### C. prox 1 / 0（背景与工具，7条精选）

**C1. Side Effects of Character Training: Quantifying Cross-Constitution Drift**｜Bhagyesh Kumar et al.｜2026｜ICML 2026 Pluralistic-Alignment WS〔纯非arXiv〕｜character训练的跨宪法价值漂移（EigenBench度量）｜prox 1｜C7-邻｜https://openreview.net/forum?id=oh9CqCyxSc
**C2. Orthogonalizing Personality Vectors for Interference-Free Multi-Trait Modulation**｜（ARR匿名）｜2026｜ACL ARR 2026 May〔纯非arXiv〕｜参数空间人格向量多特质合并的串扰（ρ0.9→0.58）与正交化修复｜prox 1｜C2/C3方法｜https://openreview.net/forum?id=qm7hpeKPqV
**C3. The Persona Selection Model (PSM)**｜Anthropic Alignment｜2026-02-23｜alignment.anthropic.com〔纯非arXiv〕｜"预训练学人格模拟、后训练选定Assistant人格"的理论框架——ABCR的C1/C2理论背景件｜prox 1（0-1）｜https://alignment.anthropic.com/2026/psm/
**C4. METR Frontier Risk Report (Feb–Mar 2026)**｜METR｜2026-05-19｜metr.org〔纯非arXiv〕｜agent判断力/可靠性系统性弱于人类专家（含Redwood"自主赚钱"4天$0案例：单次拒付即停止排查=止损/坚持失败实例）｜prox 1｜C5/C7背景｜https://metr.org/blog/2026-05-19-frontier-risk-report/
**C5. METR Review of Anthropic Sabotage Risk Report (Opus 4.6, 2026-03)**｜METR｜2026｜metr.org PDF〔纯非arXiv〕｜披露生产模型早期快照出现"deceptive AI persona"及其缓解措施——人格漂移×训练缓解在产业界已是实操问题｜prox 1｜C7背景｜https://metr.org/assets/sabotage-risk-report-opus-4-6-review-mar-2026.pdf
**C6. Documented AI Agent Incidents（44例目录）**｜METR｜持续更新｜metr.org〔纯非arXiv〕｜真实agent越权/欺瞒事件的overreach×deception双轴评分——C5原语测量的野外语料源｜prox 1｜https://metr.org/agent-incidents/
**C7. The behavioral selection model for predicting AI motivations**｜Alex Mallen（Redwood）｜2025-12｜blog.redwoodresearch.org〔纯非arXiv〕｜行为选择框架解释persona类现象（含Grok MechaHitler persona案例）｜prox 1｜C7理论背景｜https://blog.redwoodresearch.org/p/the-behavioral-selection-model-for

**记录但未上报**（低相关或重复）：MCP-Persona（HF 2606.02470，"persona"=个性化应用非人格）；PersonaGym（CoRR 2024，评估框架prox 1，arXiv托管主综述应能覆盖）；Examining Persona Drift（ARR版，=R060同系）；Measuring and Controlling Persona Drift（aArgTyz5aC，=R054早期标题）；Stay Focused: Problem Drift（EACL Findings 2026，问题漂移非人格漂移，prox 1）；RoleCDE（Findings ACL 2026，role-value decoupling，prox 1）；Better Zero-Shot Reasoning with Role-Play Prompting（NAACL 2024，R004已引为Kong et al.）；Serapio-García et al. Personality Traits in LLMs（NMI 2025/arXiv 2307.00184，R102行文已涉其作者系）；Apollo scheming系列（无persona操纵变量，prox 0-1）；Ctrl-Z（Redwood，控制协议prox 1）。

---

## ③ ≥3级判定（对照致命条件逐条）

**唯一新prox 3：PANDA（A1，ACL 2025）**

- **对C1致命条件（agentic任务＋等长中性严格对照＋改变任务成功率）**：**不致命**。(i) 任务域合格——Jiminy-Cricket 25个text-based games是多步交互式agentic环境，且结果变量是游戏得分/表现（任务结果类）；(ii) 但干预方式是**训练时策略管线整合**（人格分类器引导的policy learning），不是推理时人格文本注入，**完全没有等长中性文本对照**；(iii) 因此它证明"人格→agentic任务表现"效应存在（Openness优势），但未触碰ABCR C1的核心设计（persona text vs 等长中性对照的推理时因果隔离）。**定位**：C1的强先行证据+动机件，非杀伤件。
- **对C4致命条件（系统交互＋自适应选择＋长程agentic）**：**不致命但构成挤压**。16人格×25游戏是系统性交叉部署，提供了agentic域"任务×人格"交互面的实证（与R001的DPR静态QA路由互补）；但无按任务条件的自适应人格选择、无策略交互分析。C4剩余新颖性收窄为：**长程agentic域的自适应条件选择+人格×策略交互**。
- **对C5/C6/C7**：轨迹分析用于人格分类（触C5边缘），无原语测量、无统计中介链、无漂移×恢复设计。均不致命。

**为何其余候选停在prox 2（代表性说明）**：
- B13 Sakai（Sci Rep）：逐维极值操纵接近剂量设计+交互域，但结果变量是合作倾向非任务成功率（域=社会困境）→2。
- B1 Steer Like the LLM：C2"prompt效应可被方向干预复现"的最强机制证据，但评估停留在steering基准（概念得分/连贯性/IF），无任务成功率直链、无任务域剂量-反应→2，不触C2/C3致命条件。
- B16 ECIR rankers：人格prompt→任务准确率+机制定位三点连线，但任务域为静态IR非agentic→2。
- B9/B8/B10（漂移×修复类）：修复/恢复机制均在role-play连贯性或生成中程恢复层面，无"人格漂移×任务恢复/止损"的交互设计→C7不致命。
- B14 Teaching Claude why：character训练→agentic misalignment率是产业级"人格→agentic行为结果"证据，但无对照化人格文本操纵、结果变量为misalignment非任务成功率→2。

**结论：本轮未发现任何触发七条主张致命条件的非arXiv托管证据。** 唯一prox 3（PANDA）实际同时有arXiv版，其漏检根因是**查询角度缺口**（"personality traits + text-based games"词面不含persona steering/agent success常用词）而非托管渠道缺口。

---

## ④ 覆盖注记

**搜到的**：OpenReview API v2 search端点（5个查询角度+9次精确标题核实，含ICLR 2026被拒公开稿、ICML 2026主会/6个workshop、AAAI 2026 Bridge/workshop、NeurIPS 2025、ACL ARR 2025-2026公开投稿池）；ACL Anthology（2个角度，经exa定向+单页WebFetch核实，2024–2026）；Anthropic research页（直查可达）+alignment.anthropic.com；OpenAI cdn PDF；METR（blog+assets+incidents目录）；Apollo（scheming系列扫描）；Redwood（blog两角度）；HF papers（经exa间接）。

**被墙/不可达**：① OpenReview UI搜索页（参数错误）与单条`/notes?id=`端点（302→人机challenge）——但search端点可用，等效覆盖；② openai.com/research 403；③ huggingface.co/papers搜索页对WebFetch连续ECONNRESET（3次）——paper单页经exa可达，等效部分覆盖；④ brave-search MCP整场故障，改用exa全程替代。

**没搜/欠搜**：① DeepMind与Meta AI的publications列表页未逐页枚举（JS重、未走浏览器工具），仅exa定向查询——两家若有未上arXiv的persona×agent技术报告存在残余漏检可能（估计低：两家此域产出习惯性上arXiv）；② ACL ARR 2026 May匿名投稿池仅经关键词面扫描（该池体量大、标题匿名期不可全览）；③ COLM 2025/2026与EMNLP 2026在审池未单独定向；④ NeurIPS 2026投稿（尚未公开评审期）无法直查；⑤ 非英语渠道归偏倚3不在本轮范围。

---

## ⑤ 主观概率估计："非arXiv托管物里还藏着≥3级证据"

**估计：约30%**（另：藏着触发致命条件证据的概率 <8%）

**理由**：
1. **压低因素**：本轮系统扫过最可能藏匿处（OpenReview全venue搜索、ACL Anthology、四大lab、三家评测机构），24条prox 2里**没有一条**在向"方向干预直链agentic任务成功率+剂量反应"或"漂移×恢复交互"收敛；且本轮唯一prox 3（PANDA）实为双托管——经验上，达到prox 3质量的完整工作几乎总会上arXiv（本轮双托管率：核实过托管状态的候选中约半数有arXiv版，且质量越高比例越高）。
2. **抬高因素**：(i) ACL ARR 2026 May匿名池是已证实的活跃藏匿地（本轮从中挖出3条纯非arXiv候选，均为2026年5月新货，说明该池正以月为周期产出persona×steering新工作，其中出现agentic任务成功率结果变量只是时间问题）；(ii) ICML 2026主会已出现无arXiv版的长程persona一致性正式论文（BRIDGE），证明"主会级+纯OpenReview托管"组合真实存在；(iii) 产业界非arXiv渠道（anthropic.com、cdn.openai.com、metr.org）证实在持续发布人格×agentic行为的定量结果（Teaching Claude why的96%→0%），这类工作若下一篇把结果变量换成任务成功率即成prox 3——而它们不受arXiv发布纪律约束。
3. **最可能的藏匿位置排序**：ACL ARR 2026 May/July匿名池 ＞ ICML/ICLR 2026 workshop纯OpenReview稿 ＞ lab博客技术报告 ＞ 期刊直投（Sci Rep式）。
