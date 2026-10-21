# Tier-1 精读清单候选（供楠选定）

生成：2026-07-17 ｜ agent：Tier-1候选 ｜ 输入：定位表（R001–R102，102行）+ Gate0杀伤报告（8邻居全文定界）
用途：**D7 Gate1 楠的裁决输入。本清单只做候选与理由，不做最终选定。**
候选数：**15篇**（任务规定12–15），按杀伤力降序排列。结尾附「若只读8篇」最小集。

选择标准落点核对：
- ①邻近度3/2且agentic：2602.12285（R003）、2604.11048（R001）**必在**，已入；另入 R005/R014/R097/R031/R033/R098。
- ②Gate0八邻居威胁最高者：#1(R001)、#2(R003)、#3(R002)、#4(R007)、#6(R077) 已入；#5(OpenReview HpUDi5Pe8S)与#7/#8 落选理由见文末。
- ③方法学进口源：**Arditi投影消融与τ-bench pass^k在定位表中无独立行**——Arditi式方法由 R031 承载（同轴消融vs加法+等范数随机方向对照），pass^k由 R091 承载（pass@k/pass^k包络），τ-Bench配对协议由 R014 承载；length-controlled AlpacaEval = R095、Adding Error Bars = R096，直接入选。若楠要Arditi与τ-bench**原文**（Arditi et al. 2024 refusal direction；Yao et al. 2024 τ-bench），需另行入池——不在本定位表内，本agent不越界替选。
- ④C5礼物：AgentAtlas（R077）已入。
- ⑤C7漂移测量：ContextEcho（R098）、Assistant Axis（R027）已入。

---

## 候选清单（按杀伤力降序）

### 1. R003 ｜ Cao, Sun & Yue 2026《From Biased Chatbots to Biased Agents》(arXiv:2602.12285)
**为何必读**：C1警报源。宽口径现象占位（persona改变agentic成功率，自称first systematic），C1改写的直接对手。
**精读要答**：
1. 它的"systematic"止于哪里——无等长对照/无统计检验/仅人口学persona三缺口在正文与附录有无任何补救（重复运行？方差报告？），决定C1改写后的差异句能否写死为"现象已见、因果未立"。
2. 任务分层脆弱性（策略推理最脆弱、OS/DB仅±2–5%）可否直接借为ABCR任务选型依据，并预测特质干预的效应异质性方向？

### 2. R001 ｜ Chen et al. 2026《NPTI Persona Steering》(arXiv:2604.11048)
**为何必读**：C4警报源。静态域人格×任务交互矩阵+DPR自适应路由满占，C4收缩到agentic后的边界由它划定。
**精读要答**：
1. NPTI稀疏神经元集干预与ABCR单方向persona vector的方法学可比性——无剂量扫描、无安慰剂对照、hit式oracle口径，哪几条能写进"ABCR差异"列作方法学升级？
2. 73.68%人类方向一致性与O/E主导结论，在agentic长程域应预期保持还是失效？精读其理论对表（CB5T/ACT）找外推性断点。

### 3. R007 ｜ Wu & Henriksson 2026《Persona Matters: Activation Steering on Short Answer Generation and Scoring》(arXiv:2604.07102)
**为何必读**：C2/C3最近邻。方向干预→质量的显著性链路+"扰动非风格控制"结论必须直面；§5点名drift监测=C7动机锚。
**精读要答**：
1. "扰动论"的证据边界：双向皆降质是否可归因于固定α=2.0、单一中层、无剂量-反应？ABCR剂量曲线设计要怎样才能推翻或限定它？
2. 11×任务敏感度差（ELA vs science）给C4"人格×任务×阶段交互"什么先验？其15×15交互矩阵可否改造为ABCR的人格×任务矩阵模板？

### 4. R098 ｜ Ding et al. 2026《ContextEcho: Persona Drift in Long Agentic-Coding Sessions》(arXiv)
**为何必读**：C7直接对手。真实数千轮agentic会话的漂移基准，等长filler对照+预注册+负对照探针，漂移测量方法学最严。
**精读要答**：
1. 它测的漂移=assistant register偏移，与ABCR"特质人格漂移×行为原语"的差异还剩什么？~80 token锚已做恢复干预——ABCR的C7恢复主张要退到哪条线（原语级恢复？漂移×人格交互？）？
2. snapshot-then-probe分叉协议+等长filler对照可否原样进口为ABCR C7协议底座？

### 5. R027 ｜ Lu et al. 2026《The Assistant Axis》(Anthropic, arXiv)
**为何必读**：C7最强表示层邻居。漂移的轴投影在线测量+activation capping稳定化+漂移可预测性（R²=0.53–0.77）齐备。
**精读要答**：
1. 轴投影是表示层漂移，ABCR测行为层漂移——文中有无两层背离的证据？"表示不漂而行为漂"（或反之）能否立为ABCR增量？
2. capping仅在15轮对话+静态基准验证——agentic长程留白多大？ABCR恢复干预与capping的分界与组合空间怎么写？

### 6. R005 ｜ Keluskar, Bhattacharjee & Liu 2026《When Does Personality Composition Matter for Multi-Agent LLM Teams?》(arXiv)
**为何必读**：已发表中最接近改写后C1：特质级（宜人性）×agentic成功率+中性改写对照+Cohen's d/p/CI全套。
**精读要答**：
1. 其中性改写对照（剥离贬义词保行为意图）算不算已过"等长中性对照"杀伤线？若算，C1差异只剩单agent/激活通道/行为原语三件，判决怎么下？
2. 其Bales IPA过程指标（沟通φ+四类行为）算不算C6"人格→行为→结果"中介的先行？到ABCR原语（核验/坚持/止损）的映射缺口在哪？

### 7. R014 ｜ He et al. 2025《Impatient Users Confuse AI Agents》(τ-Trait/TraitBasis, ACL 2026 Oral)
**为何必读**：C3式方法先行：对比激活差提取trait+剂量缩放+线性组合，且τ-Bench同任务配对协议可直接进口。
**精读要答**：
1. 干预对象在用户模拟器而非agent本身——这道差异防线是否牢固？文中有无对agent侧注入的实验、讨论或future work（若有，C3差异句要重写）？
2. trait稳定性三分类（consistent/escalate/fade）与强度可辨识度协议，可否直接搬为ABCR的C2剂量设计+C7漂移行为编码？

### 8. R031 ｜ Pinto 2026《Present but Rescaled: Chat-to-Agent Transfer of Additive Activation Steering》(arXiv)
**为何必读**：ABCR在agentic域用转向的设计前提由它定界（转移被重标定、无普适常数）；Arditi式消融+等范数随机对照的进口源。
**精读要答**：
1. 转移比T重标定定位于ReAct格式脚手架——对ABCR意味着每模型×每脚手架必须重标定剂量吗？子饱和剂量窗gate怎么搬？
2. 其Controls A–F（等范数随机方向带、能力匹配扰动、KV全量重编码、预注册）哪几件必须全套进口为C2/C3对照底线，哪些可减配？

### 9. R097 ｜ Yap 2026《Behavioral Steering in a 35B MoE: One Agency Axis, Not Five Traits》(arXiv)
**为何必读**：直接转向agentic行为特质（自主/坚持/风险校准/顺从）且五向量坍缩为单一agency轴——威胁ABCR特质×原语的维度结构。
**精读要答**：
1. 单轴坍缩是SAE探针法/单模型/代理指标（autonomy与deference构造上反相关）的工件，还是行为倾向空间本身低维？ABCR多维设计需要什么反证实验？
2. 探针R²=0.795而因果无效（risk-calibration）的解离，对ABCR"探针选向→转向"管线是什么级别的警告？

### 10. R002 ｜ Hu, Rostami & Thomason 2026《Expert Personas Improve Alignment but Damage Accuracy: PRISM》(arXiv:2603.18507)
**为何必读**：C4第二击。alignment vs pretraining任务二分解释+随机persona对照+长度混淆显式剥离，Gate0八邻居中对照最严。
**精读要答**：
1. "人格增益主要来自上下文长度"结论的适用范围——ABCR等长中性对照是否必须以此为设计红线？其随机persona对照可否直接进口？
2. alignment/pretraining二分映射到agentic任务（工具调用/规划属哪类）后，对特质×任务交互方向给出什么可检验预测？

### 11. R033 ｜ Sui et al. 2026《TACT: Mitigating Overthinking and Overacting in Coding Agents via Activation Steering》(arXiv)
**为何必读**：长程编码agent上沿漂移轴回拉转向治理overthinking/overacting（≈坚持失控/止损原语），C3/C5/C7三线压顶。
**精读要答**：
1. OT/OA与ABCR坚持/止损原语的分界能否写成"能力性漂移 vs 人格性倾向"？其步级三分类标注pipeline可否改造为原语测量仪？
2. 轨迹漂移比γ与resolve率负相关是否已抢占C6"行为→结果"半链？ABCR剩余增量是否只剩"人格前因"一段？

### 12. R077 ｜ Mazaheri & Mazaheri 2026《AgentAtlas》(arXiv:2605.20530)
**为何必读**：C5礼物（Gate0确认）。六门控词表+15基准0/1/2审计+自认效度缺口，ABCR原语操作化与选平台的现成底座。
**精读要答**：
1. 六门"决策正确性"改造为ABCR"行为倾向强度"刻度的最小路径（Stop门校准→止损倾向；anti-Looping→坚持）？核验原语无对应——增量声明的最稳写法？
2. τ-bench/ToolSandbox作为control轴仅有的2分基准，够不够承载全部原语测量？缺口用什么补？

### 13. R091 ｜ Bjarnason, Silva & Monperrus 2026《On Randomness in Agentic Evals》(arXiv)
**为何必读**：方法学进口（pass^k承载行）。agentic噪声地板：pass@1漂移2.2–6.0pp、temp=0仍SD>1.5pp——ABCR效应量必须压过此地板。
**精读要答**：
1. 按其功效分析，ABCR预期人格效应量（参照R003的−26.2%与R014的−4~−20%）每条件最少要几次独立运行？
2. pass@k（乐观）/pass^k（悲观）包络哪个应作ABCR主指标？人格干预下"稳定性"本身是不是该用pass^k作结果变量？

### 14. R096 ｜ Miller 2024《Adding Error Bars to Evals》(Anthropic, arXiv)
**为何必读**：方法学进口（任务点名）。成对分析/聚类标准误/功效分析——ABCR全部效应量报告的统计底线规范。
**精读要答**：
1. ABCR同任务±人格的配对设计下，聚类单位取任务、轨迹还是模型×任务？与R091的重复运行方差如何合成一个误差预算？

### 15. R095 ｜ Dubois et al. 2024《Length-Controlled AlpacaEval》(arXiv)
**为何必读**：方法学进口（任务点名）。GLM长度中介的统计等长对照——C1等长中性对照的统计补丁+judge长度偏差防线。
**精读要答**：
1. 设计层等长对照（提示级）与统计层长度校正（GLM mediator）在C1中如何组合？该法能否推广到校正agentic轨迹长度差异（人格干预常改变轨迹长度）？

---

## 落选但供楠替换的近邻（4篇）

| 行ID | 论文 | 落选理由 | 若楠想加强 |
|---|---|---|---|
| R099 | Handa et al.《Personality as a Probe》(ICL/PEFT/MS×GAIA) | 邻近度3但within-run Δ框架无显著性检验，威胁弱于已入选者 | C1"prompt+激活双通道"论证 → 可替换R095 |
| R051 | FinPersona-Bench（200步mandate衰减+安慰剂） | C7 agentic漂移已由R098+R033+R027覆盖 | C7再接地/恢复干预一节 → 可替换R091 |
| R039 | Qian《Nous》（四组等长安慰剂+注入阴性） | null结果威胁低；但其等长安慰剂设计是全表最严 | C1对照设计模板 → 可替换R096 |
| R028 | OpenReview:HpUDi5Pe8S | Gate0已定界为名义占位（无漂移定义无恢复），全文不可稳定获取——引用作靶即可，不值精读位 | 不建议入选 |

---

## 若只读8篇（最小集）

覆盖原则：每条受威胁主张至少一篇最近邻+C5礼物；方法学三篇（R091/R096/R095）降级为摘要级速读进口，不占精读位；R002的C4杀伤细节已被Gate0全文定界覆盖（读R001即可锚定C4边界）。

1. **R003**（2602.12285）— C1警报源
2. **R001**（2604.11048）— C4警报源
3. **R007**（2604.07102）— C2/C3扰动论+C7动机锚
4. **R005**（多agent人格构成）— C1严格对照最近邻
5. **R031**（chat→agent转移）— C2/C3设计前提+Arditi式对照进口
6. **R027**（Assistant Axis）— C7表示层漂移+稳定化
7. **R098**（ContextEcho）— C7 agentic漂移基准
8. **R077**（AgentAtlas）— C5礼物/原语操作化底座

主张覆盖自查：C1←1/4；C2/C3←3/5；C4←2（+Gate0对R002的定界）；C5←8；C6←4的过程指标+11（11不在8篇内，C6中介威胁暂由R033的γ相关记录在案，Gate1若判C6为重点应将R033升入）；C7←5/6/7。

---

## 补充轮增补建议（2026-07-17；最终选定权属楠）

补充轮 36 新行（R105–R140）中有 4 篇被点名评估是否入 Tier-1，另有 5 条墙后/新警报条目给出去向建议。原 15 篇候选与"只读8篇"最小集**未改动**，以下为增量修订建议。

### 建议入 Tier-1（2篇，附替换方案）

**A. R105 ｜ Dong et al. 2026《Steer Model beyond Assistant》(B2-01, arXiv:2601.06403) —— 建议入，替换 R095**
- **为何入**：C3 三级重创·边缘型占位（本轮唯一经 Gate0 式全文定界确认的新 ≥3 级）。剂量-冲突律与 steering tax 是 ABCR 剂量曲线设计必须直面的两条先验；其 +Prompting vs CD α=0 分解对照同时是等长/措辞混淆的另一条防线。
- **为何替换 R095**：R095（Length-Controlled AlpacaEval）为方法学进口件，其 GLM 长度校正已完整收录于方法进口清单，可降级为摘要级速读；B2-01 则直接决定 C3 判决书的写法。
- **精读负担低**：`bias-sweep/B2-01-全文定界.md` 已做 100% 精读定界，楠可只读该报告 + 原文 Table 1/Figure 2/§5.1。
- **精读要答**：①剂量-冲突律在残差流干预下应预期保持还是失效（ABCR 的 α 扫描范围怎么定）？②"steering tax"与 R007 扰动论是同一现象的两个口径吗——C3 的正向利用条件句如何同时回应两者？

**B. R106 ｜ Lim et al. 2025《Persona Dynamics》(PANDA, ACL 2025, arXiv:2504.06868) —— 建议入，替换 R002**
- **为何入**：C4/C1 agentic 交互面最强先行（16人格×25游戏×Wilcoxon/Friedman 全套统计），且是 ACL 主会正式发表——C1"现象已见"的引用锚与 C4 差异句的直接对手。其轨迹机制分析（高 Openness=更广探索）是"人格→行为原语→结果"叙事的既有半链。
- **为何替换 R002**：Gate0 已对 R002 做过全文定界，其 C4 杀伤细节已被杀伤报告覆盖（"只读8篇"最小集本就不含 R002）；PANDA 的统计规范与轨迹分析对 ABCR 更可偷。
- **精读要答**：①训练时策略塑形（γ·C 项）与推理时人格文本/方向注入的差异防线是否牢固——文中有无 prompt 注入对照或 future work？②其"10/25 游戏因零分剔除"的任务筛选口径对 ABCR 任务选型是什么警示？

### 不建议入 Tier-1（2篇，理由与替代用法）

**C. R113 ｜ Heyman & Vandeputte 2026《Steer Like the LLM》(ICML 2026, arXiv:2605.03907) —— 不入正位，列为 R031 的配套速读**
- 理由：C2 桥最强机制证据（prompt 人格效应≈方向干预的忠实版），但评估停在 steering 基准、无任务成功率直链，威胁级 prox2——不构成判决级对手。其 Δ_PS 蒸馏、TA@coherence 协议、相对 RMSE 忠实度度量已录入可偷方法。**建议与 R031（chat→agent 转移）捆绑速读**（同为"方向干预的设计前提"层），不占独立精读位。若楠认为 C2 桥须原文核实，可替换 R096（统计规范可由方法进口清单承载）。

**D. R114 ｜ Sun et al. 2026《BRIDGE》(ICML 2026 主会) —— 不入，引用作靶即可**
- 理由：修复目标=人格一致性/保真（PersonaGym/CoSER），非任务结果恢复，prox2；且 OpenReview 被人机墙、无 arXiv 版，**全文当前物理不可稳定获取**（现有定界仅 icml.cc 摘要+GitHub README 级）——精读位无法兑现。C7 写作时以其 latent state drift 三分与"非对称断裂风险"概念为靶/为引即可；若后续墙解除且楠要深挖 C7 理论层，再按条件触发器定界（补充轮报告§四.2）。

### 新警报条目去向（不占 Tier-1 位，入"待全文定界队列"）

| 条目 | 去向 | 理由 |
|---|---|---|
| R107 duDmnRyJh5（C3 致命位最近邻） | **待全文定界队列首位**：C3 判决落笔前必须定界 | 现仅摘要级+repo日志；墙后 PDF 取回是前提，谈不上精读位 |
| R108 WVVSObO4oT（C3） | 待全文定界队列次位 | 仅摘要级，剂量存在性未知，混淆质量0 |
| R109 GcpNaqxp0z（C4） | 待全文定界队列（C4 判决前）；前身 arXiv:2508.06149 可先速读 | ARR 匿名稿被墙；贝叶斯优化任务性能部分是关键缺口 |
| R110 Peacemaker（C1/C4） | **Tier-1 替补第一顺位**（全文已可达且已全文级抽取） | 若楠要加强 C1 多agent线，可替换 R091（其 pass^k 结论可由方法进口清单承载）；否则弹药包引用即可 |
| R129 AdaPA（C4 机制同构体） | 弹药包引用+差异句点名；PDF 被 Cloudflare 阻，暂不定界 | prox2 且对象=偏好非人格；C4 差异句必须点名它，但不值精读位 |

### 若采纳 A/B 替换后的"只读8篇"最小集（不变）

最小集 8 篇不受影响（R095/R002 本就不在内）；15 篇正位变为：R003/R001/R007/R098/R027/R005/R014/R031/R097/**R106(PANDA)**/R033/R077/R091/R096/**R105(B2-01)**。主张覆盖自查增量：C3←+R105（解码层剂量族系定界）；C4←+R106（agentic 交互面对手）；C1←+R106。
