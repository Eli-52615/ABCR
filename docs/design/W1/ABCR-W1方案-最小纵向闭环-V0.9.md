# ABCR W1 方案：最小纵向闭环 V0.9（供否决 / 定稿）

> 日期：2026-07-10 ｜ 周期：启动周末（7/11–7/12）+ W1（7/13–7/18）
> 定位：设计层文档，Claude Code 据此出实际执行方案。上位文档：V1.3（W1 行：rig v0、step 原子 runner、schema 全字段、复现 Persona Vectors 配方、首批向量 + 表达检、steering 行为翻转 demo）。
> 与《自动化实验流程设计 V0.9》的关系：W1 只建其 Phase 0（账本 + rig + manifest + 复评），不建 Operator 常驻、Governor、控制台。

---

## 0. 一页结论

**对转发建议的判定**："最小纵向闭环"路线**采纳**——它与 V1.3 W1 行完全一致，也符合 2026 年文献"先建可验证 harness、后谈自主性"的共识。三处精化：① "固定输入与模型"必须落成明确的冻结清单（§2），否则"固定"只是愿望；② "自动评分"在 W1 = 确定性评分 + 单 judge 表达检，不是完整评价器栈；③ 闭环的**闭合点**必须定义为"独立复评一致"——可复现实验包只有被一个干净会话仅凭包内容重算出相同分数，才算闭合（§6）。排除清单（路由器、统计大屏、多轮 agent、LoRA、通用插件系统）全部采纳，另补五项同样诱人但不做的（§1）。

**W1 唯一目标**：一条真实实验链可重复运行——固定输入与模型 → baseline / 人格文本 / 残差干预三臂 → 逐步轨迹与激活摘要落盘 → 自动评分 → 独立复评一致 → 一键产出可复现实验包。

**四件交付**：① rig v0（含全字段 schema 与黄金测试）；② Persona Vectors 复现：1 个官方 trait 校准 + 3 个锚 trait 首批向量与表达检；③ steering 行为翻转 demo（周末即出）；④ 首个可复现实验包 = 本周对外证据对象。

---

## 1. 范围：做与不做

做（且只做）：step 原子 runner + 全字段日志；官方配方复现与首批向量；表达检（五检之②）；三臂 mini 环跑通（rig 验证性质）；复评脚本；复现包出包。

不做（转发建议五项 + 补五项）：路由器、统计大屏、多轮 agent、LoRA、通用插件系统；**另补**：B0 探针（W2）、剂量钳制协议（W2，依赖文本臂投影分布）、混合效应模型与正式统计（W2 功效模拟起）、③中性等 token 臂与 ③ᴸ 同长度臂（W2 探索期入场）、boss_console 改造与任何界面工作。

理由一句话：W1 的产出不是证据，是**产生证据的机器及其正确性证明**。任何看起来能提前出"结果"的诱惑，都会把 rig 验证的时间换成不可采信的数字。

---

## 2. 冻结清单（W1 固定什么）

"固定输入与模型"落成以下七项，全部哈希入 manifest、版本入 git：

1. **模型**：HF revision（commit hash）钉死——Qwen2.5-3B-Instruct（开发）、Qwen2.5-7B-Instruct（正式）；dtype 记录（正式 = bf16，Mac 开发 = 4bit 且标记 non-citable）。
2. **chat template**：模板文件哈希；渲染样例 3 条人工目检入库（模板错误是 harness 最常见静默杀手）。
3. **解码参数**：temp 0.7 × seed 集（W1 开发用 2–3 seed，正式规格 ≥5 留待 W2 起）+ temp 0 sanity 各一遍；max_new_tokens 定值。
4. **prompt 集**：trait 工件（正负 prompt、评测题、评分 rubric）与任务族题目全部版本化；抽取语料 ∩ 评测题 = ∅ 由构造保证 + 哈希检查。
5. **split**：W1 交付确定性 split 工具（按 item_id 哈希切 20/40/40），为首批 1–2 个任务族生成 split 并将 hash 入 git（满足"split hash 首轮前入 git"）；**W1 一切运行只碰 dev split**。
6. **引擎**：见 §3 单引擎决策（d1）。
7. **注入位置**：响应 token（对应官方 `--steering_type response`，V1.3 固定项）。

---

## 3. rig v0 设计

**仓库结构**：按 v1.0 §5.1 建目录骨架，W1 实建子集：`configs/`、`src/abcr/{models, hooks, interventions/{prompt_persona, residual_vector}, eval/deterministic, logging}`、`data/manifests+splits`、`scripts/`、`tests/`。其余目录占位空建，防结构漂移。

**config → run**：一个 run = 一份声明式配置（模型、条件/臂、干预规格、数据切片、解码、seed）；`run_id = hash(config) + 时间戳`。启动前置检查：git 必须 clean（否则仅允许 `--dev` 启动并在 manifest 打 non-citable 标）；模型 revision、模板 hash、split hash 与冻结清单逐项核对，不符拒跑。

**step 原子写入**：schema = 交接文档 §6.2 基底 + V1.3 §11 扩展字段，单轮任务写成长度 1 的 trajectory（trajectory_id/step_id 从第一天就是主键）。W1 补充字段（提请并入 schema）：`engine, engine_version, torch_version, cuda_version, chat_template_hash, config_hash, protocol_ref, env_lock_ref`。写入方式：临时文件 + fsync + 追加，逐 step 落盘；崩溃后按 (item_id, seed, condition) 对账续跑，重复执行幂等。铁律沿用：不得只存汇总分。

**schema 的多步就绪证明**：W1 不建 agent，但用一条**合成 2-step 轨迹测试**（人造 action/obs_hash/state_snapshot_ref 序列走完写入-读取-重放解析）证明 W10 replay 所依赖的字段语义从第一天就是通的——这比"字段存在"强一档，成本半小时。

**黄金测试（rig 正确性层，W1 的核心工程交付）**：
- hook 注入检：注入已知向量 v、系数 c，断言该层残差位移 ≈ c·v（浮点容差内）；投影消融后断言该方向投影 ≈ 0；
- 已知答案检：10 道人工核定题过完整评分链，分数必须精确命中；
- 模板检：渲染结果与钉死样例逐字节一致；
- 双跑一致检：同 config、temp 0 连跑两遍，输出与分数一致（见下方诚实条款）。

**单引擎决策（d1）**：W1 三臂全部走 transformers + bf16 + forward hook。理由：vLLM 默认对批组成不满足确定性（同请求因并发批次不同可得不同 logprobs/输出，官方 FAQ 明示），而 W1 的价值就在"同链可重复"；且三臂同引擎才谈得上互相比较。vLLM 引入推迟到 W2 文本臂扩量时，W1 交付一项 **20 题 temp 0 双引擎 parity 烟检**（transformers vs vLLM，记录逐题一致率与分歧样例），为 W2 的分引擎设计提供事实依据；若分歧率高，W2 方案需响应（同引擎基线配对，或启用 `VLLM_BATCH_INVARIANT=1` 批不变模式并计入其约 1.6× 吞吐代价）。

**激活存储策略**：全量激活不落盘。W1 只存两类——抽取语料上的分层均值激活（生成向量所需）；评测运行中**抽样 10% 题目**的逐响应 token 在 v_p 上的投影标量序列 + 分层统计摘要（均值/P50/P90，直接为 W2 剂量标定铺路）。step 记录中 activation_summary 字段存路径 + 统计值。

**可复现性诚实条款**：本项目承诺的复现 = ① 工件级（原始输出永久保存，任何再分析不依赖重新生成）+ ② 统计级（同 config 重跑，聚合指标在自身抽样波动内一致）+ ③ 单机确定级（同机同环境 temp 0 双跑一致）。**不承诺跨硬件 bit 级一致**——浮点归约序差异是行业已知事实，声称 bit 级可复现反而不诚实。此条写入复现包 README。

---

## 4. Persona Vectors 复现设计

官方流水线（safety-research/persona_vectors，本次页面级核验）五阶段与 W1 动作映射：

| 官方阶段 | 内容 | W1 动作 |
|---|---|---|
| 1 trait 工件 | 仓库自带 7 个 trait 的正负 prompt / 40 题（20 抽取 + 20 评测）/ rubric；新 trait 用 `data_generation/prompts.py` 的生成 prompt（原文用 Claude 3.7 Sonnet thinking） | 官方 trait 直接用现成工件；3 个锚 trait（尽责 / 开放 / 神经质）用官方生成 prompt 经 Claude 产工件，人工过目后版本化，provenance 记录生成模型 |
| 2 正负系统提示生成 | `eval.eval_persona --version extract`，pos/neg 各 20 题 × 多响应，judge 打 trait 分并按 >50 / <50 过滤 | 照跑；judge 见下方替换决策 |
| 3 差分均值向量 | `generate_vec.py`：逐层响应 token 平均激活之差，产出 `response_avg_diff.pt`（论文所用），shape = 层 × 隐维 | 照跑；向量与层扫描结果入库 |
| 4 steering 评测 | `eval.eval_persona --version eval --steering_type response --coef --layer` | 官方 trait：对表校准；锚 trait：小系数集扫描（2–3 个系数 × 1–2 层），全部标 exploratory |
| 5 投影计算 | `eval.cal_projection` | 跑通即可，为 W2 剂量钳制的投影统计验证工具链 |

**复现顺序（d2）**：先用**一个官方已发布 trait**（建议 optimistic 或 sycophancy——后者与谄媚抗性任务族叙事相连；不选 evil，对外与家庭展示不友好）完整走五阶段，与官方公开行为对表（steering 使 trait 分沿预期方向移动、连贯性在文档化系数区间内维持），确认"管线在我手里是对的"；然后才抽 3 个锚 trait。这是把"复现锚定"原则用到向量配方上：先复现已知，再产自己的。PERSONA（ICLR 2026，已核）已在同族模型上验证过此流水线可复用，管线级风险低；风险集中在环境与 judge 替换。

**judge 替换（d3，谱系偏差点，必须明示）**：官方评测为 OpenAI 系 judge（默认 gpt-4.1-mini，改自 Emergent Misalignment 代码库——本次核验确认）。按锁定的异构 judge 规则（非 Qwen 非 Llama），W1 将 judge 端点替换为 DeepSeek（OpenAI 兼容接口，配置级改动）。两项配套：① 向量卡谱系字段记录"judge 已替换，非官方原件"；② n=50 双 judge 一致性抽样（官方 judge 若可低成本获取则实测，否则以第二异构家族替代），量化替换引入的评分漂移。**过滤用 judge（阶段 2 的 >50/<50 筛选）与表达检 judge 允许同为 DeepSeek**——前者是数据清洗，后者是结果度量；但表达检必须盲评：judge 输入不含条件标签、样本随机顺序。

**表达检（五检之②）W1 判定**：盲评下 steered-pos 的 trait 分明显高于 baseline 与 steered-neg（方向清晰 + 效应量记录 + 逐题分布图），n = 20 评测题 × 每题 ≥2 响应 × 正负两向。W1 不做正式显著性检验（W2 补）；同时轻量记录副作用初筛（评测响应的流畅度分或小样 PPL），不设门槛只留数。五检覆盖度声明：W1 完成 ①谱系（复现包本身即谱系证明）与 ②表达，⑤副作用轻量记录；③词表（logit-lens）与 ④孪生留 W2+。未过五检前一律称 direction-k，不称人格向量——沿 V1.3 §4。

**算力安排**：官方流水线按 CUDA 假设编写，Mac 只用于代码干跑（3B、极小样，验证脚本能走通与 judge 端点通）；正式抽取与评测在租用 24GB 卡上进行（两个云日，见 §7），云纪律五条全部生效。粗量级：单 trait 抽取 ≈ 5 对 prompt × 20 题 × 10 响应 × 2 极 ≈ 2000 条生成 + 激活前向，24GB 卡上单 trait 小时级；4 个 trait（1 官方 + 3 锚）+ steering 评测 + mini 环，两个云日充裕。W1 云预算上限 **¥150**（d4；预计实耗 ¥40–100，租价当日核定，不预写死数）。

---

## 5. 三臂 mini 环（rig 验证，非证据）

规格：1 个任务族（可验证指令遵循，IFEval 式——确定性判分、先验高、且直接对应对外话术句式）× 50 dev 题 × 3 臂（① Vanilla；② 全人格文本，用首个通过表达检的锚 trait；④ 残差注入，系数取该 trait 扫描中"表达检显著且连贯性未垮"的一档）× 2–3 seed，全部 transformers 引擎。

**定位声明（d6）**：此环的目的（按序）是——评分链在真实负载下无 parse 灾难、三臂配置切换无泄漏（②臂无向量 hook、④臂无人格文本，由 manifest 断言）、激活抽样存储与投影统计跑通、复评一致。**产出的分数差异不构成任何假设的证据**：dev split、样本小、无对照配对、阈值未定。周报与对外材料必须如此标注；违者即触犯"exploratory 当结论"禁令。

产出一张图：三臂逐 seed 得分点图 + 每臂输出长度分布（后者为 W2 长度三段分解预热），标注"rig 验证运行，非证据"。

---

## 6. 可复现实验包（闭环的闭合点）

内容清单：`manifest.json`（全部哈希：protocol_ref / config / commit / model revision / template / split / env lock）、configs 原件、原始输出 JSONL（steps 级）、scores、激活摘要文件、环境 lockfile（pip freeze + Python/torch/CUDA 版本）、复跑与复评命令 README、一张主图、诚实条款（§3）与 exploratory 标注。

一键语义：`make repro-pack RUNSET=...` 从账本聚合出包。

**闭合验收**：开一个全新 Claude Code 会话，只给包，要求其不接触原仓库、仅按 README 从原始输出重算全部确定性分数——与包内 scores 一致，闭环才算闭合。这一步同时就是《自动化设计》§7 审计器"重评分"项的第一次人工执行，为 W2 审计器自动化提供参照实现。

三轨复用：本包 + 表达检图 + 翻转 demo 录屏（60–120 秒）即本周对外证据对象与家庭可见进展，不另做材料。

---

## 7. 七天日程

| 日 | 主题 | 交付 / 止损点 |
|---|---|---|
| 7/10 五（今） | 方案定稿；repo 骨架 + schema 初版；官方仓库 clone，Mac 3B 干跑阶段 1–2 脚本，DeepSeek judge 端点调通 | 干跑通 = 明日云日风险已排掉大半 |
| 7/11 六（云日 #1） | 租 24GB 卡：官方 trait 五阶段完整复现（bf16）→ 对表校准 → **steering 行为翻转 demo**（同题 ±系数并排 + trait 分）；晚间向爱人展示；发出首批 2–3 个联系（附 demo 截图 + 一句话问题） | 启动周末三件事全部落账；卡完成即关机 |
| 7/12 日 | 休 / 缓冲（周 6 天制，休息日可与楠习惯对调） | — |
| 7/13 一 | runner 正式化：config→run_id、step 原子写、幂等续跑；黄金测试四件（hook 检 / 已知答案检 / 模板检 / 双跑检）；合成 2-step 轨迹测试 | 黄金测试全绿为当日门 |
| 7/14 二 | 评分器独立成 pass（从工件评分，非在线附带）；复评脚本；split 工具 + 首批任务族 split hash 入 git；manifest 校验器 | **止损点：若 runner 至今不稳，砍 3B 开发路径与 parity 烟检，直取主链** |
| 7/15 三（云日 #2） | 3 锚 trait 工件生成（已于本地预生成、人工过目）→ 抽取 → 向量 → 表达检 → 小系数扫描；激活抽样存储实测 | 至少 1 个锚 trait 表达检方向清晰；**止损：云日失败顺延一天，砍 mini 环题量 50→30** |
| 7/16 四 | 三臂 mini 环 ×2–3 seed；20 题双引擎 parity 烟检；复评全量跑 | 复评一致为当日门 |
| 7/17 五 | 复现包出包 + 新会话闭合验收；主图与表达检图；周报（exploratory 标注）；demo 精修 | 四件交付齐 |
| 7/18 六 | 对外日：周证据对象发出（教授/博士优先，附复现包链接与表达检图） | 周最低配额起算 |

---

## 8. W1 出口门

- **G1 可重复**：同 config 重跑 → 题目覆盖一致、temp 0 分数一致、聚合指标一致；manifest 校验通过。
- **G2 schema 就绪**：全部 run 过字段校验；合成 2-step 轨迹测试通过（W10 replay 字段语义证明）。
- **G3 配方校准**：官方 trait 复现行为与公开结果方向一致、连贯性在文档化系数区间内维持。
- **G4 首批向量**：≥1 个锚 trait 通过 W1 版表达检（方向清晰 + 效应量与分布图在案）；judge 替换偏差已记录（n=50 抽样在案）。
- **G5 闭环闭合**：新会话仅凭复现包复算，分数一致。
- **G6 预算**：GPU 实耗 ≤¥150 且逐实例登记在案。
- **G7 呈现纪律**：周报与对外物中，全部 W1 数字带 exploratory / rig-validation 标注，无一处越线表述。

任一门未过 → W2 首日先补门，不带病推进（探索期 ≤30% 算力的表内本就含此缓冲）。

---

## 9. 风险与止损

| 风险 | 概率 | 应对 |
|---|---|---|
| hook 正确性错误（最危险：错得安静） | 中 | 黄金测试 hook 检为 D1 硬门；错必现于断言而非分数 |
| chat template / 分词静默错配 | 中 | 模板 hash + 逐字节样例检 + 渲染人工目检 |
| judge 替换引入评分漂移 | 中 | n=50 一致性抽样定量；谱系卡明示；表达检以方向与分布为准而非绝对分 |
| 官方脚本环境坑（CUDA/依赖） | 中 | 周五 Mac 干跑前置排雷；云日 5% smoke 后才全跑 |
| 云日失败 / 卡被回收 | 低中 | checkpoint + 幂等续跑；日程留 7/12 与顺延一档 |
| 工时超支拖垮闭环 | 中 | §7 两处止损点写死；砍的永远是外围（3B 路径、parity、题量），主链（复现 + 闭环闭合）不砍 |

---

## 10. 嵌入决策清单（可否决，未否决即按此执行）

- **d1** W1 三臂全走 transformers + bf16 + hook 单引擎；vLLM 推迟 W2，本周只交 20 题 parity 烟检。
- **d2** 复现顺序：先 1 个官方 trait 对表校准，后 3 锚 trait；官方 trait 选 optimistic 或 sycophancy（弃 evil，展示友好性）。
- **d3** judge 替换为 DeepSeek（OpenAI 兼容端点）；谱系卡记录偏差 + n=50 双 judge 一致性抽样；表达检盲评（隐藏条件、随机顺序）。
- **d4** W1 云预算上限 ¥150，两个云日制，完成即关机。
- **d5** W1 只碰 dev split；split 工具与首批任务族 hash 本周入 git。
- **d6** 三臂 mini 环定位为 rig 验证，产出不作证据、周报明确标注。
- **d7** 行为翻转 demo 用复现的官方 trait（效果确定、周六即出）；锚 trait 表达检作为研究性交付随后。
- **d8** 止损规则按 §7 表内两处执行，砍外围保主链。

---

## 附：核验状态

已核（本次实时，页面级）：persona_vectors 官方仓库——目录结构、五阶段命令、自带 trait 工件位置（`data_generation/trait_data_extract|eval/`）、新 trait 生成方式（`data_generation/prompts.py`，原文用 Claude 3.7 Sonnet thinking）、judge 为 OpenAI 系（默认 gpt-4.1-mini，改自 Emergent Misalignment 代码库）、向量产物 `response_avg_diff.pt`（论文所用，层 × 隐维）、steering 类型含 response；vLLM 官方 FAQ 确认默认非确定性、批不变模式 `VLLM_BATCH_INVARIANT=1` 存在（性能代价约 1.6×，第三方实测口径）。已核（此前台账）：2507.21509 配方细节、2602.15669（PERSONA）流水线可复用性。未核：DeepSeek 端点与官方 judge.py 的具体兼容细节（周五干跑时实测，属执行层验证）。
