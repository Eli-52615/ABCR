# ABCR 项目交接文档（与《实验方案 V1.3》配套）

> 用途：新会话中上传《ABCR-实验方案-V1.3.md》+ 本文档后，Claude 应能完整掌握项目背景、楠的理念需求、V1.3 之外的全部共识，直接衔接执行任务。
> 阅读方式：V1.3 是研究轨唯一操作文档；本文补齐 V1.3 引用但未随附的 v1.0 条款（§6）、背景、共识与协作约定。二者冲突以 V1.3 为准。
> 日期：2026-07-10（12 周周期：2026-07-10 至 2026-10-04）

---

## 1. 人物、资源与约束

**楠（研究者本人）**：数据分析背景（约两年，国内大厂），哲学+心理学根基，统计本科，Python/SQL 基础，无 AI 行业正式经历。统计与实验设计是其相对主场，工程由 AI 助手高强度代劳。
**硬件**：Mac mini M4 16GB + MacBook Air M2 16GB；不新购单价 >¥5000 设备；GPU 按小时租用，预算硬上限 ¥4000。
**AI 协作工具**：Claude Opus 4.8 high 与 ChatGPT 5.6 Thinking 全天可用（分工见 §6.9）。
**时间**：每周 6 天 × 8 小时 = 48 小时（配置见 §6.8）。
**硬约束**：职业上只接受远程（可偶尔线下集中）；不以论文录用为唯一成败标准；每周必须产出显著、可对外汇报的进展；每周向爱人展示可见进展（一图/一 demo/一句外部认可/下周一步）。

## 2. AILH 既有系统与历史事实（实验的资产与教训来源）

AILH（AI Life Helper/Harness）：楠已建成的生产 agent 系统——Claude Opus API + 飞书集成，Drive→Dispatch→Capability→Tool 四层管线，mem0+pgvector 记忆，独立 auditor，benchmark 硬规则+灰区评判，自修改沙箱与回退，V_core/V_mutable 人格治理（三运行模式），结构化 task log。
**已确证的历史事实**（均有项目档案原文出处，可直接引用）：
- V_mutable 迭代使人格一致性五轮单调递增 2.65→3.15（证明人格表达可调，不证明能力来自人格）；
- 内生 vector 自评系统精度仅 11.5% 且方向错误（AI 自评不可作现实反馈）；
- 楠自己确立过三条原则：delta benchmark（测增量不测绝对分）、开发者污染防范、同底座审计盲区（judge 须异构）。
**AILH 在本项目中的角色**：真实任务与失败轨迹来源；W10 的 T1 集成场；对外展示的系统能力证据。**不作首轮因果实验体**（变量过多无法归因）。

## 3. 楠的理念与需求（最终版）

**研究母命题**：人格是可测量、可干预、任务依赖的策略控制结构；真正可能通用的不是一根静态高增益向量，而是"人格策略特征 × 任务需求"的连续调节规律与动态控制策略。"高能力人格吸引域/稳态"仅作理论叙事与对外表达，不进预注册。

**四条硬需求**：
1. 在开源模型上实现"直接调适人格向量、不经文本、验证行为能力增益/下降"（= V1.3 的 S1，不设单轮增益门槛，多轮价值由 T1 检验）。
2. 向量必须**可命名、非黑盒**：文本人格是向量的命名锚与剂量标尺（五检协议 + 剂量钳制），成果形态是人格向量卡。
3. 实验与对外接触**从第一周并行**，每周结合双轨进展调整方向；同一交付物三轨复用（研究证据=对外内容=家庭可见进展）。
4. 长程/多轮是原创命题的主场：单轮负责机制归因，多轮（T1）负责长期净价值——两级衔接，不二选一。

**认知立场（已定稿的保留/删除清单）**：
- 保留：文本人格可改变能力（任务依赖）；内部人格表征值得研究；"部分中介"是正确表述；LoRA 可作固化载体；现实反馈驱动局部更新；跨模型迁移是长期目标。
- 删除：不存在已知"完整内部人格"；人格向量不是文本作用唯一通道；内部干预不天然优于文本（须作为待检验假设，文献显示 prompt 常胜过激活 steering）；同一人格无唯一内部方向（多 elicitation 得不同侧面）；静态万能人格大概率不存在；AI 不能仅靠自述可靠抽象自身框架。
- 方法论三原则：状态 vs 特质之分（prompt 改激活态不改权重特质）；通道隔离先于归因；三层人格本体（文本形态→激活形态→行为形态）需三角汇聚。

## 4. 版本谱系与效力

- **v1.0**（2026-07-10，1675 行，ChatGPT 产出，楠已采纳为骨架）：定义 ABCR（Adaptive Behavioral Control Runtime）、三轨道（R 研究/P 产品/M 市场）、三出口、治理条款。**不随附新会话**，其仍生效条款已压缩至本文 §6。
- **v1.1 决定书** → 补丁 M1–M3 → 补丁 M4–M7 → **V1.2** → 补丁 M8–M12 + 两条精化（同长度对照夹逼定位、T1 触发配对协议）→ **V1.3（冻结候选，现行唯一操作文档）**。
- 改动窗口：仅剩 W3 预注册前用探索数据定稿占位阈值（k=2、H2 资格门 5pp、绝对削减阈 2pp、T1 的 K 与冷却）。其余不再改。
- 外部评审记录：ChatGPT 侧对 V1.2 评 8.7/10；Claude 判定 V1.3 达博士早期开题水准以上。

## 5. 已锁定决策速查

¥4000 GPU 封顶（探索期 ≤30%）｜Qwen2.5 家族（3B 开发、7B 主研究、14B 规模轴 8bit/48GB、Llama-3.1-8B 跨架构、NPTI 仅旁证单点、Qwen3-8B 可选且 thinking 必须钉死）｜主假设 H1（连续式）/H2（绝对削减量版）｜残差流差分均值为主线配方（复用 Persona Vectors 官方流水线谱系）｜judge 异构规则：非 Qwen 非 Llama 家族（如 DeepSeek）双 judge 盲评随机顺序｜temp 0.7×≥5 seed + temp0 sanity｜出口排序 加盟/合作 ≥ 研究 > 融资（三合一门槛：两模型证据+设计伙伴+可信引荐，兴趣不改日历）。

## 6. v1.0 生效条款压缩替代（V1.3 引用、本节自足）

### 6.1 仓库结构（§5.1）
`abcr/`：configs（models/interventions/benchmarks/experiments）；src/abcr（models.py、hooks.py、interventions{npti,residual_vector,prompt_persona,controls}、eval{deterministic,judge,safety}、routing{nearest_neighbor,linear_router,contextual_bandit}、stats{paired_tests,mixed_effects,bootstrap}、logging{schema,writer}）；data/manifests+splits；scripts；tests；reports；demos。

### 6.2 日志 schema（§5.2 基底 + V1.3 §11 扩展）
基底字段：run_id、git_commit、model_id、model_revision、dtype、quantization、device、benchmark、split_hash、item_id、condition、trait、trait_pole、method、layer、coefficient、random_seed、prompt_hash、output_text、parsed_answer、is_correct、latency_ms、input_tokens、output_tokens、stop_reason、trait_score、fluency_score、safety_flags、activation_summary。
扩展字段（V1.3）：trajectory_id、step_id、parent_run、env_seed、action、obs_hash、intervention_strength、remaining_budget、stop_reason、state_snapshot_ref。
铁律：不得只存汇总分；每结果可追溯 revision/split hash/commit/条件。

### 6.3 云纪律（§4.2 五条）
本地只做开发与短实验；Mac 上第 3 个工作日仍无法稳定 hook 立即切云；正式结论至少一次 BF16/FP16 复现（不能只靠 4-bit）；云任务必须 checkpoint+自动上传+完成即关机；先 5% smoke test 再跑全批。

### 6.4 数据切分（§6.2）
每族 20% 开发 / 40% calibration / 40% held-out；holdout 冻结后楠不看单题、只看聚合与预定义错误类别；调参只在开发/calibration；路由只用 calibration；split hash 首轮前入 git；对外必分 exploratory/confirmatory。

### 6.5 评价器优先级（§7.4）
确定性答案 > 单元测试/规则 > 人类盲评 > 异构双 judge > 单 judge。开放题双家族 judge、隐藏条件、随机答案顺序，分歧保留不强行平均。

### 6.6 路由与反馈（§8，G1/G2 用）
阶梯：R0 oracle 上界（仅估上限）→ R1 任务族固定映射（最低基线）→ R2 最近邻 DPR 复现 → R3 线性/树（输入任务 embedding、长度、是否数学/开放式、约束数、检索验证度；输出 method/trait/pole/coefficient/layer）→ R4 contextual bandit（reward = task_score − λ1·流畅损失 − λ2·延迟 − λ3·安全回退；先离线 replay 再有限在线）。
只更新：task→config 概率、coefficient、method、layer 白名单、置信与回滚阈值。不更新：V_core、benchmark 答案、holdout、evaluator prompt、全部向量、底座权重、安全边界。每次更新记反事实八项（新旧策略选择、replay 预期、实际、偏差、原因、回滚条件）。

### 6.7 LoRA 门槛（§9.1，G3 用）
同时满足五条：held-out 稳定有效；过随机方向与长度控制；跨两模型或两任务子集方向一致；steering tax 可接受；路由净收益为正。固化目标是行为原语小 LoRA / 可组合 adapter，比较 Prompt/Activation/LoRA/Router 组合的准确性-成本-兼容-可审计性，不证"更深"。

### 6.8 AILH 集成与防污染（§10）
接口：BehaviorControlRequest(task_features, model_id, allowed_traits, risk_level) → BehaviorControlDecision(method, trait, coefficient, layer, confidence, rollback_rule)；AILH 只消费决策，ABCR 独立维护实验/hook/路由。
防污染六条：confirmatory 期关自修改；auditor 盲条件标签；memory 用冻结快照；禁逐题修 prompt；只允许预注册的 router 更新；批后汇总不中途挑条件。

### 6.9 时间配置与双模型分工（§12–13）
周 48h：实验工程 26 / 分析写作 8 / 对外 6 / 定向学习 4（只学本周阻塞）/ 管理复盘 2 / 缓冲 2。每日：晨读昨日结果定唯一关键问题→深度实验→分析→写日志图结论→对外或学习。第六天后半天固定：结果冻结、一张主图、一段 demo、本周失败、下周假设、爱人可见说明、方向调整记录。
Opus 4.8：实现调试、读 repo、单测、跑实验、工程史、patch、自动化；约束——不独立改研究假设、不按 held-out 单题修代码、不兼运动员与裁判、修改由测试与 commit 固化。
ChatGPT 5.6：文献追踪、因果识别、统计设计、替代解释攻击、周报叙事、市场研究、材料；约束——语言完整感不代实验、建议须落可验证条件、最新事实须联网核验、不看 held-out 单题给针对性修复。
楠不可替代：定问题、定行为构念、分哲学解释与实验证据、定更新哪个节点、与真人建信任、判产品与方向、模型意见相左时终裁。

### 6.10 对外接触系统（§14）
周最低配额：3 个个性化异步联系、1 次远程通话、1 个公开进展物、1 个明确问题、1 条影响方向的反馈记录。
四类对象：研究者（persona vectors/RepE/interp/agent learning）、创业者工程师（eval/observability/agent infra/开源部署）、潜在设计伙伴（有 agent 失败日志、需私有部署）、投资人招聘方（有证据后才重点接触）。
冷联系只发证据对象：一句话问题+一张图+60–120 秒 demo+一个请教点+低成本下一步；示例句式："在无人格 prompt 下，Qwen2.5-7B 的某内部干预对 IFEval +X pp、GSM8K −Y pp，随机等范数控制无此现象……你最担心的替代解释/部署障碍是什么？"
每周公开七件套：问题/方法/一图/结果/最大失败/下一步/repo。禁令：只发愿景、exploratory 当结论、judge 单分造突破、只晒代码量、藏负结果。

### 6.11 定位与不做（§15–16、§19 摘要）
一句话定位：ABCR 是开放权重 agent 的自适应行为控制层——从生产反馈学习何时激活验证/探索/坚持/校准等原语，用因果对照证明改进。产品楔子优先级：agent regression optimizer > 私有/开源模型行为控制 > 长程 coding/research agent 校准 > 高风险策略校准 > companion（最后）。与 eval/observability 公司的差异必须落在：原语识别、任务条件化干预、剂量、反馈更新、反事实比较、steering tax、局部回滚、三载体统一实验——若只做到 trace+judge 则转作品集不融资。
职业定位关键词：AI Evaluation / Agent Reliability / Applied Research / Research Engineer—Model Behavior / Agent Infra & Observability 等；作品集四证明：会实验、会工程、懂 agent 生产问题、能独立推进。远程话术：不把"远程"放第一句，先证独立交付。
不做（摘）：不训基础模型、不大规模 SAE、不 70B、不全自动递归自改、不让 agent 改 evaluator、不先写论文再实验、不做漂亮 UI、不同时研究全部人格概念、不自建全部 steering 算法、不重写 AILH、不押 workshop、不等实验完再社交、不用哲学直觉豁免对照、不用"更深"代替因果。

## 7. 文献核验台账与设计依据地图

**已由 Claude 亲自核验（arXiv 页面/摘要级），及其在方案中的角色**：
- 2604.11048（NPTI 系统分析）：人格诱导产生稳定、任务依赖的能力变化；DPR 路由胜最佳静态；RQ2 规模轴即 Qwen2.5 0.5B–14B——推理族效应 7B 峰值、14B 近噪声，IFEval 跨尺度稳定（→S2 是复现+扩展）；与人类人格-认知关系 73.68% 方向一致（楠的心理学直觉可作先验）。
- 2507.21509（Persona Vectors，Anthropic）：主线抽取配方与可对表基线（Qwen2.5-7B/Llama-3.1-8B 同款模型）。
- 2602.15669（PERSONA，ICLR 2026）：复用 Persona Vectors 流水线，Big Five 向量近正交可代数运算，多轮人格一致胜 prompting——证明流水线可复用、多轮"持续性"有据（但持续≠能力提升）。
- 2605.03907（PSR）：逐 token 系数模仿 prompt 干预 → 剂量钳制协议依据。
- 2605.10664（Prompt–Activation Duality）：prompt 下投影稀疏、均匀注入绕过受训通路且长程累积失真 → 钳制须匹配分布而非只匹配范数；消融比注入更贴流形。
- 2606.11172（预测特征）：检测特征是未来行为的糟糕预测器；预测探针 64–91%；FPCG 文本级 steering 几乎无质量损失 → B0 双门槛设计与 G4。
- 2605.05980（TACT，ICML 2026）：过思/过动两条漂移轴线性可分（AUC≈0.9），逐步拉回校准区，SWE-bench Verified 等 +4.8–5.8pp、步骤 −26% → T1 动态臂配方与"吸引域"操作化先例。
- 2504.04635（Steering off Course）：跨模型可靠性差异大；几何可分性差时 30–50% 样本反向 → 0.70 可分性门。
- 2603.02578（可控性统一评测）：prompt 式控制常压过激活式 → "内部优于文本"只能作待检假设。
- 2605.13329（预训练追踪）：人格方向极早形成；不同 elicitation 得同一人格不同侧面 → "无唯一方向"。
- 2603.18507（PRISM）：专家人格助对齐损判别准确率 → 解验证族"正反都有信息"。
- 2605.29420：专家人格增益小且依赖问题类型。
- 2509.03730（Personality Illusion）：自报≠行为 → 表达/行为分层依据。
- 2503.07513：模型对自身知识无可靠特权访问 → AI 自述不作框架依据（与 AILH 11.5% 教训互证）。
- Assistant Axis（Lu et al. 2026，经 2605.21006 引用确认）：已有人发布命名角色向量（Skeptic/Judge/Peacekeeper）→ 对外必须主动引用并声明差异（因果对照+副作用面板）。
- 旁证：2604.07102（Qwen3-4B 位移 0.172 vs 32B 0.021 不显著）、2507.11771（越大越难 steer）——规模衰减的独立旁证；Zheng et al. 2024 角色 prompt 负结果系列（H1 必须测"方向可预测"而非"存在效应"的依据）；2604.02113（行为稳定边界过滤提升向量质量、同家族可迁移，抽取工艺可参考）；2511.00617（belief dynamics 把 ICL 与 steering 放同一标尺，剂量换算理论参照，选读）。
**未核验（用前必查）**：v1.0 之 R3（Steer2Adapt 2602.07276）、R5（2602.15847）、R7（2602.01716）、R8（2604.14463）、R9–R18（市场与价格类）。楠明确不参考：RESGA/SAEGA（2601.02896）。

**2026H1 中国市场共识（已核验，2026-06/07 澎湃/虎嗅/投中/定焦等）**：AI 融资超三千亿、占一级市场约 48.6%；头部三家（DeepSeek/阶跃/月之暗面）占 30%，DeepSeek 6 月 510 亿 A 轮；纯大模型早期窗口关闭，资金转向下游；早期钱高度偏向大厂/顶校背景团队；估值逻辑转向复购/运行数据。→ 这是出口排序（加盟/合作优先）与三合一融资门槛的依据。

## 8. 工程与算力结论（已达成，不再重议）

- Mac 16GB：7B/8B 4bit 推理流畅、14B 4bit 紧且慢，只作开发试点；机制实验主战在租用卡。
- 24GB 卡（4090 级）：7B bf16 推理+hook 舒适；8B bf16 LoRA 可行（grad ckpt+小 batch）；14B QLoRA 舒适；14B bf16 推理超 24GB → 8bit（hook 照常，残差仍 fp16）或短租 48GB。
- 吞吐分工：文本臂批量 vLLM；注入/消融 transformers+bf16+forward hook（静态向量加法不拖速，慢的是激活存盘——只在抽取/探针/投影统计的抽样子集存）。
- 成本量级：全程预计 ≤¥2000（¥4000 上限的一半留缓冲）；租价波动大，下单当日核价。
- 软件栈（v1.0 §4.3）：PyTorch/Transformers/Accelerate/Datasets、自写薄 runner（优先）或 lm-eval adapter、原生 hook/NNSight/Pyvene 三选一且优先复用论文代码、Pandas/DuckDB/Parquet、SciPy/Statsmodels、Typer、Pydantic、pytest；不引必须付费平台。
- 若用 Qwen3：thinking 开关必须钉死为受控变量。

## 9. M 轨道联系人映射（楠的真实清单 → 周程）

| 联系人 | 激活周 | 给什么 | 要什么 |
|---|---|---|---|
| AI 教授/博士（2–3 人） | W3、W6 | 预注册、首批结果 | 方法拍砖、替代解释挑战 |
| 大厂研究员 | W5、W8 | 效应图、中介结果 | 技术讨论、内推 |
| 智谱产品 & HR | W8–W10 | 向量卡+报告 | 远程岗位/产品交流；话术锚"开源模型行为可控性与评测"，不谈"AI 人格哲学" |
| 初创创始人 | W6 起 | demo+向量卡 | 合作/兼职顾问/设计伙伴（要真实失败日志） |
| 量子位等社媒运营 | W9–W11 | 一篇成果稿（负结果亦可） | 发布曝光 |
| 数据资产入表公司商务 | G 门后 | — | 仅商业化时激活，低优先 |
| 知识产权代理人 | 一次性 | — | 咨询专利 vs 开源；默认全开源 |
| 大厂老同事 | 月度 | 周报摘要 | 弱连接维护 |

每周六=对外日，周中不切换。

## 10. 当前状态与下一步

**状态**：V1.3 冻结候选已交付；预注册尚未上 OSF（W3 冻结）；rig 未动工；对外接触未启动。
**启动周末三件事**：① 建 `abcr` repo 并跑通 Persona Vectors 官方流水线（Qwen2.5-7B，抽首批向量+表达检）；② 周六发第一批 2–3 个联系（教授/博士优先，附预注册草案求拍砖）；③ 向爱人展示首个 steering 行为翻转 demo。
**新会话可能被要求的任务**（按概率）：W1 rig 代码与 hook 实现支持；抽取/钳制/探针脚本；预注册文档（OSF 版）起草与 E1/E2/E3 矩阵计价；W2 功效模拟代码；周报与冷联系文案；对楠转发的 ChatGPT 建议做核验评审；结果分析与图。

## 11. 与 Claude 的协作约定（对下一实例的工作指令，楠已明确）

1. **独立思考、整体推进**：楠已明确撤销"一步一步讨论"模式——给完整方案与判断，附可否决的嵌入决策清单，不逐项征询。
2. **审视一切非自产内容**：楠会转发 ChatGPT/其他来源的建议文档要求评审；惯例输出格式为"判定＋逐条采纳/精化/驳回＋M 编号补丁"；每条承重引用（尤其 2026 年 arXiv 与市场数据）必须实时联网核验后再表态，已核/未核状态明示。楠对此高度重视且已多次因核验获得实质增量。
3. **平实语气**，技术诚实（不奉承开头、结论先行带证据、直言缺陷——此亦 AILH 项目 CLAUDE.md §6.4 之约）。
4. **限长指令严格执行**（如"总结 500 字/1000 字"）。
5. **每周节奏意识**：任何产出尽量落成"可对外的证据对象"（一图/一 demo/一段可复现说明），服务三轨复用。
6. 记住占位阈值（k=2、5pp、2pp、K/冷却）只能用 W2 探索数据定稿、W3 冻结、其后任何人（包括楠）要求修改都应援引 V1.3 §14 拒绝。
7. 楠的身份叙事统一用 ABCR 一句话定位；对外材料禁令见 §6.10。
