# ABCR W1 工程包 C：Scorer + Audit + Repro Pack（V1.0，自足执行文档）

> 执行者：一个独立 Claude Code 窗口（建议 Opus 长上下文）。本文档自足：**执行全程不需要、也不要读取 shared-brain 下任何文件**，唯一豁免 = 同目录上位文档《ABCR-W1执行方案-V1.0.md》的 §4（接口冻结区权威版本 + F13 bootstrap 脚本权威全文），除此以外一律不读。允许读取的仓外内容仅两处：包 B 克隆的 `third_party/persona_vectors`（vendored 依赖，只读）与 DeepSeek key 文件（只读、只入环境变量）。
> 你的使命：**裁判与验船师**——确定性评分器（独立 pass）、复评与 manifest/哈希链审计、judge 后端与盲评协议、复现包与闭合验收、全部图表。**你只消费原始输出、绝不参与生成**；评分绝不回写 runs/。你是「运动员/裁判/验船师」三分中后两者的化身，你的独立性是整个 W1 正确性证明的支点。

---

## 0. 统一执行纪律（三包相同）

1. 文档没写的细节：独立决策，在 `/Users/superagent/abcr/DEVIATIONS.md` 追加一行（前缀 `[C]`），不回查任何外部文件。
2. 只写「所有权矩阵」（§3-F7）中属于 C 的文件；消费他包产物只认冻结路径，缺位走本文档后备；**不跨窗口沟通**。
3. **按阶段推进**：完成阶段 N 自验后更新 `/Users/superagent/abcr/STATUS-C.md`（含验收输出摘录），停在阶段门等统一回归。回归协议：三包 STATUS 均报完成后，由**最后完成的窗口**跑 `make stage<N>-regression`，全绿提交 `[REG] stage<N> PASS`（失败提交 FAIL+摘要，责任包修复重跑）；**你的放行信号 = git log 出现该 PASS 提交**。等待期只做本文「等待期可做」项。
4. 每完成一个 WBS 条目 git commit（前缀 `[C]`）；遇 `index.lock` 等 2s 重试 ≤5 次。
5. 验收断言必须真实跑过、输出留存；失败如实报告，**禁止降低断言换绿**。
6. 治理三条：本窗口不跑 `/boss`；本仓永不 `git push`；仓内路径规避子串 `"/persona/"`、`"v_core"`、`"judgment_engine"`。

## 1. 背景 primer（2 分钟读完，不需要更多背景）

ABCR 是楠的 12 周研究项目：在 Qwen2.5 家族上研究「人格文本效应 × 内部人格向量」的因果关系。W1 不产科学证据，只造**产生证据的机器及其正确性证明**——你负责「正确性证明」的一半：评分链正确（已知答案黄金检）、账本可审（哈希链/manifest/复评一致）、复现包能闭合（全新会话仅凭包复算出同样分数）。五阶段执行（S0 契约 → S1 全 fixture → S2 一个官方 trait + judge → S3 锚 trait + mini 环 → S4 闭合与扩展），阶段内三包并行、阶段间统一回归。知识边界（冻结）：B 只输出标准化向量工件；A 不理解向量生成；**C（你）只消费原始输出、不参与生成**。

judge 谱系要点：官方 Persona Vectors 用 OpenAI gpt-4.1-mini 打 trait 分（logprobs top-20 概率加权）；本项目按「judge 异构（非 Qwen 非 Llama）」规则替换为 **DeepSeek**——替换的兼容性实测（D0 探针）与偏差量化（n=50 双 judge）都归你。Mac 产物一律 non-citable；一切对外数字带 exploratory / rig-validation 标注。

## 2. 环境与治理事实（已实测，直接信任，不必复查）

- Mac mini M4，16GB，macOS 26.4.1，磁盘余 122Gi。你的工作基本不吃算力（评分/审计为 CPU 轻载；图表 matplotlib）。
- `/opt/homebrew/bin/python3.11`（3.11.15）与 `uv`（0.11.3）可用；系统 python3=3.14 不要用。PyPI 直连。
- **DeepSeek key**：`/Users/superagent/oc-boss-state/deepseek.key`（0600，非空）。注入：`export OPENAI_API_KEY=$(cat /Users/superagent/oc-boss-state/deepseek.key); export OPENAI_BASE_URL=https://api.deepseek.com`；模型 `deepseek-chat`；api.deepseek.com 存活（匿名 401 属预期）。**key 值绝不入文件/git/日志/报错回显；禁止创建 .env**。
- **claude CLI**（n=50 双 judge 的第二家族）：无头调用一律 `CLAUDE_RAW=1 ~/.local/bin/claude -p ...`（v2.1.207，订阅通道，零 API 费；zsh 的 `claude` 是 AILH launcher 函数勿用）。ANTHROPIC_API_KEY 按治理不得设置。
- **官方 judge 的实现语义**（已代码级核验 persona_vectors@b8e0f04 的 judge.py，你的 client 照此对齐）：`AsyncOpenAI()` 读环境变量；0_100 档 = messages 单轮、max_tokens=1、temperature=0、seed=0、logprobs=True、top_logprobs=20 → 对返回的 top-20 token 中**能 int() 且 0≤x≤100** 的 token 按 exp(logprob) 加权平均；数字概率质量 <0.25 判无效（记 None/REFUSAL）。另有 binary_text 档 = 全文生成 + 文本解析。eval_prompt 末尾要求「只回一个 0-100 数字或 REFUSAL」。
- 官方仓自带 `output/qwen2.5-7b-instruct_baseline.csv`（7B 基线响应集）——你 n=50 双 judge 的现成打分样本（在包 B 克隆的 `third_party/persona_vectors/output/` 下，只读；若 B 尚未克隆，你可自行 `git clone https://github.com/safety-research/persona_vectors` 到临时目录取该 CSV，但**不写 third_party**——那是 B 的所有权）。
- 治理：`/Users/superagent/abcr` 不受任何沙箱/hook 拦截（源码级已核）；SessionStart 注入的 AILH 背景无害忽略；git 本地仓、无远端、永不 push。

## 3. 接口冻结区 v1（等效副本；如有出入以上位 §4 为准）

### F1 仓库与身份
- 路径 `/Users/superagent/abcr`；本地 git（`git init -b main`；user.name "Yinan Wang"；user.email worldofnan130@gmail.com），无远端、永不 push。
- 提交前缀 `[A]`/`[B]`/`[C]`/`[REG]`；`index.lock` 冲突等 2s 重试 ≤5 次。
- 所有权互斥（F7）；`mkdir -p` 不算冲突；DEVIATIONS.md、STATUS-*.md 共用 append。

### F2 环境
- 主 venv `.venv`（uv，python3.11）：`torch==2.6.0, transformers==4.52.3, accelerate==1.7.0, datasets==3.6.0, pandas==2.3.1, pyarrow, duckdb, scipy, statsmodels, matplotlib, typer, pydantic==2.11.7, pyyaml==6.0.2, pytest, openai==1.70.0, backoff==2.2.1, tqdm, huggingface_hub`。
- 模型 revision 钉死于 `configs/models.yaml`（bootstrap 完成；你只在审计时核对，不加载大模型）。
- tinyqwen（S1 假模型）：`tests/fixtures/tinyqwen/`（bootstrap 生成）——你的审计 fixture 生成会用到 A 的 writer 模块（代码 import 不算所有权冲突；所有权只管文件写入）。

### F3 目录布局
（与包 A 文档 §3-F3 完全一致；你常用子集：）
```
src/abcr/{score.py, review.py, repro_pack.py, eval/{deterministic/{checkers.py, registry.py}, judge/{client.py, blind.py, probe.py}}}
scores/<run_id>/{scores.jsonl, summary.json}    review/<run_id>/review_report.json
review/{judge_probe_report.json, judge_consistency_n50.json, exprcheck_<trait>_report.json}
repro_packs/{<runset>/, CLOSURE-PROTOCOL.md}    figures/
tests/{fixtures/golden_answers/, contract/*/test_c_*.py, unit/test_c_*.py}
```

### F4 steps.jsonl schema（w1.1）
（与包 A 文档 §3-F4 逐字一致。你审计时校验的就是这套字段；评分时消费 output_text/item_id/condition/random_seed 等，**永不回写**。）

### F5 写入语义
（与包 A 一致。要点：append-only + 哈希链（prev_hash/entry_hash，sha256(canonical_json+prev)）+ 每行 fsync；链校验单实现在 `abcr.logging.writer.verify_chain`——你 review 时调用它，不自写第二份链算法（W1 裁定：同源风险由已知答案黄金检对冲，checker 双实现推迟 W2）。）

### F6 scores / review / 向量工件 / 判定工件
- `scores/<run_id>/scores.jsonl` 行：{run_id, trajectory_id, step_id, item_id, condition, random_seed, scorer_version, checks:[{name,pass,detail}], is_correct(bool), score(float 0-1)}；join 键 (run_id, trajectory_id, step_id)。`summary.json`：逐臂×seed 聚合 + 输出长度统计。
- `review/<run_id>/review_report.json`：{n_steps, n_expected, missing[], duplicated[], chain_ok, score_mismatches[], manifest_checks{}, error_codes[], pass(bool)}。复评 = 独立进程从 steps.jsonl 重算全部确定性分逐条 diff；judge 类分数复评 = 从**已落盘 judge 原始输出**重算聚合（不重调 API）。
- 向量工件（B 产，你只审元数据与 sha）：`vectors/<model-slug>/<trait>-<grade>/{response_avg_diff.pt, card.json, extraction_meta.json}`；E15 = 三件套不齐/shape 或 pt_sha256 不符。
- judge 判定工件（逐样本原始返回 + 解析分，聚合必须可重算——你的重算基座）三个落位：B 的 bridge 侧 `pv_bridge/out/**/*.judge_raw.jsonl`；**你（C）的盲评/双 judge 侧 → `review/judge_raw/<name>.jsonl`**；`runs/<run_id>/judge_raw.jsonl` 保留给 W2+ 的 run 内 judge（W1 不产生，你对 runs/ 恒零写入）。
- **items.jsonl 行 schema（冻结，A 产你消费）**：`{item_id: sha256(prompt)[:16], family, prompt, checks: [{name: <CT-1 内部名>, kwargs: {...}}], source, source_key}`；is_correct = 全部 checks pass，score = 通过比例。你的 score.py 与 S1 自测 fixture 都按此格式。

### F7 所有权矩阵
| 路径 | 所有者 |
|---|---|
| scripts/bootstrap.sh、pyproject.toml、CLAUDE.md、README.md、Makefile、configs/、src/abcr/{models,run,splits}.py、logging/、interventions/api.py、data/、runs/（数据）、costs/、tests/fixtures/（golden_answers、vector_tiny 除外）、tests/*/test_a_*.py | A |
| src/abcr/interventions/{prompt_persona,residual_vector,projection_ablation,random_direction,capture}.py、third_party/、patches/、pv_bridge/、artifacts/traits/、vectors/、scripts/cloud/、tests/fixtures/vector_tiny/、tests/*/test_b_*.py | B |
| src/abcr/{score,review,repro_pack}.py、eval/ 全部、scores/ review/ repro_packs/ figures/、tests/fixtures/golden_answers/、tests/*/test_c_*.py | **C（你）** |

### F8 密钥与 judge 纪律
- 注入方式见 §2；模型 `deepseek-chat`；谱系字段 `judge_model=deepseek-chat, judge_lineage=replaced(official gpt-4.1-mini-2025-04-14)`。
- **盲评协议（你实现并自证）**：trait 表达类打分的输入行只含 {sample_id, question, answer}——代码断言禁含 {condition, trait, trait_pole, arm, method} 键；样本顺序随机且置换 seed 落盘。抽取过滤用 judge（B 的 bridge 内）允许非盲——数据清洗与结果度量之分是上位既定裁定。

### F9 呈现与运行纪律
Mac 产物恒 non-citable；only-dev-split；对外数字必带 exploratory / rig-validation 标注（**你产的每张图必须带此角标**）；fail 方向：校验类 fail-closed，旁路 best-effort；¥150 云预算常量（本周应恒 0）。

### F10 错误码（logging/errors.py，A 实现）
E01–E18 全表见包 A §3-F10；你是 E08/E10/E11/E12/E13/E14/E15 的主要触发者与报告者。全部 fail-closed；CLI 非零退出打印码。

### F11 你参与的分阶段契约测试
- S1：test_c_parser_scorer / test_c_manifest_review
- S2：test_c_judge_blind / test_c_first_pack
- S3：test_c_review_full
- S4：闭合验收（人工协议）/ test_c_dual_judge_n50

### F12 checker 契约 CT-1（你按此实现 checker；A 按此过滤题库；两份文档表格逐字一致）
| 内部名 | IFEval instruction_id | kwargs | pass 判定 |
|---|---|---|---|
| keywords_existence | keywords:existence | {keywords:[str]} | 全部关键词出现（不区分大小写、词边界匹配） |
| keywords_forbidden | keywords:forbidden_words | {forbidden_words:[str]} | 全部禁词不出现（同上匹配规则） |
| keyword_frequency | keywords:frequency | {keyword, frequency:int, relation} | 出现次数满足 relation（at least/at most/exactly） |
| length_words | length_constraints:number_words | {num_words:int, relation} | 词数满足 relation（at least/less than） |
| length_sentences | length_constraints:number_sentences | {num_sentences:int, relation} | 句数满足 relation |
| length_paragraphs | length_constraints:number_paragraphs | {num_paragraphs:int} | 以空行分隔的段落数恰好 N |
| format_json | detectable_format:json_format | {} | strip 后整体可 json.loads |
| format_title | detectable_format:title | {} | 含 `<<标题>>` 形式标题 |
| format_bullets | detectable_format:number_bullet_lists | {num_bullets:int} | markdown `* ` 起始行数恰好 N |
| case_capital | change_case:english_capital | {} | 全大写（含字母的字符全为大写） |
| case_lowercase | change_case:english_lowercase | {} | 全小写 |
| postscript | detectable_content:postscript | {postscript_marker:str} | 含标记（如 "P.S."） |
| end_phrase | startend:end_checker | {end_phrase:str} | 以该短语结尾（允许尾随空白/引号） |
| quotation | startend:quotation | {} | 整体被英文双引号包裹 |
多约束题：is_correct = 全部 checks pass；score = 通过比例。词数/句数的切分规则由你实现并在 checkers.py 顶部注释写死（词 = `\S+`；句 = 按 [.!?] 加引号右括号收尾切分），A 不依赖该细节。

---

## 4. WBS（按阶段执行）

### 阶段 0（S0）：bootstrap + 骨架（目标 7/11 内）

**C0.1** 执行 bootstrap（脚本权威全文在**上位 §4-F13**——你被明示允许读取的唯一外部文档章节；`scripts/bootstrap.sh` 已存在则直接执行，不存在则按 F13 全文写入后执行。先到先跑、互斥锁保护，你若后到会等到 `.bootstrap.done` 再返回）。
**C0.2** 等 A 落位 `logging/{schema,errors,writer}.py`（S0–S1 初）。等待期：先写 checkers.py/registry.py（不依赖 A）、golden_answers fixtures、score/review 骨架。

### 阶段 1（S1）：确定性评分链 + 审计器（目标 7/12–7/13；全 fixture，不接网不接 judge）

**C1.1 `eval/deterministic/checkers.py` + `registry.py`**：按 CT-1 实现全部 14 个 checker（纯函数 `check_<name>(text, **kwargs) -> (pass: bool, detail: str)`）；registry：`get_checker(name)`、`run_checks(text, checks: list) -> [{name, pass, detail}]`。**每个 checker ≥3 个单测**（正/负/边界；`tests/unit/test_c_checkers.py`）。
**C1.2 已知答案黄金检**（W1 四大黄金测试之一，anti-同源-bug 的支点）：`tests/fixtures/golden_answers/golden.jsonl`——**你亲手核定** ≥12 个用例，覆盖 ≥10 种 CT-1 类型，含 ≥4 个应判 fail 的用例与 ≥2 个多约束用例（is_correct 语义）；每行 {case_id, checks, response, expected:[{name, pass}], expected_is_correct}。核定方法：逐例人工数词数/查关键词后把期望写死（这是「人工核定」的实义——期望值不来自被测代码）。`tests/contract/stage1/test_c_parser_scorer.py`：评分链跑 golden.jsonl **逐例精确命中**（E18 未过则修 checker 不改期望）。
**C1.3 `score.py`（评分独立成 pass）**：CLI `python -m abcr.score --run <run_id> [--items <items.jsonl>]`——只读 `runs/<id>/steps.jsonl` 与 manifest（取 items 路径与 split）；逐 step 跑 checks → 写 `scores/<id>/scores.jsonl` + `summary.json`（逐臂×seed 的 is_correct 率与 score 均值、output_tokens 分布分位数）。scorer_version="c1.0" 起。对 steps 目录**零写入**（用只读打开自证）。
**C1.4 `review.py`（复评 + manifest 校验 + 链审计）**：CLI `python -m abcr.review --run <run_id>` / `--pack <dir>`：
1. 链：调 `abcr.logging.writer.verify_chain`（断→E08）；
2. 完备性：steps 完成集 vs manifest 期望（(item×seed×condition×step) 缺→E10 missing；重→duplicated）；
3. 复评：独立重算全部确定性分 vs scores.jsonl 逐条 diff（不一致→E11，列样本）；judge 类分（若 run 含 judge_raw）从原始返回重算聚合比对（不重调 API）；
4. manifest：config_hash 重算一致、split_hash 对文件、chat_template_hash 对 configs/templates、env.lock 存在、arm_purity 字段自洽（违→E12/E06）。**单实现裁定（同 verify_chain）**：manifest 必填字段集与 config_hash 算法（sha256(canonical_json(config))）以 A 的 `abcr.logging.manifest`/`abcr.logging.schema` 为单一实现，你 import 调用重算、不自写第二份；
5. 产出 `review/<id>/review_report.json`（F6 结构），pass=全绿。
**C1.5 故障注入自检** `tests/contract/stage1/test_c_manifest_review.py`：用 A 的 writer 在 tmpdir 造合成 run（10 步）→ 注入四类故障各一：篡改一行字段（→error_codes 含 E08）、**删除末尾一行**（→error_codes 含 E10；删中间行会先断链报 E08，故断言口径为「error_codes 包含期望码，允许伴随 E08」）、伪造 scores 中一行分数（→含 E11）、manifest 挖掉 split_hash（→含 E12）——**全部被 review 发现且期望码在案**；再跑无故障对照（pass=true）。这是《自动化设计》故障演练制在 W1 的最小实现。

**S1 验收**：checker 单测 + 黄金检 + 故障注入全绿，输出留存；STATUS-C 更新，停阶段门。
**等待期可做**：C2 judge client/probe 代码（不发真实请求）；repro_pack 骨架。

### 阶段 2（S2）：judge 后端 + 实链评分 + 首个复现包（目标 7/14–7/15）

**C2.1 D0 探针（S2 第一件事，7/14 上午做完——B 在等你的结论）**。`eval/judge/probe.py`：注入 key 后向 `deepseek-chat` 发 10 次官方式打分请求（用官方 optimistic eval_prompt 格式自拟 2 组 question/answer）：记录 ①响应是否含 `logprobs.content[0].top_logprobs`（个数）；②top 候选是否为 0-100 整数**单 token**；③数字概率质量是否 ≥0.25；④text 模式对照（temp0 全文，解析数字成功率）。结论写 `review/judge_probe_report.json`：{logprobs_supported, numeric_single_token, numeric_mass_ok, recommended_mode: "logprob_weighted"|"text_parse", evidence:[逐次原始摘要], probed_at}。**两种结论都合法**——探针的任务是定案，不是保证兼容。
**C2.2 `eval/judge/client.py`**：`TraitJudge(model="deepseek-chat", mode=<probe 结论>)`——logprob_weighted 档（对齐官方语义：max_tokens=1/temp0/seed0/top_logprobs=20/加权平均/质量<0.25→REFUSAL）与 text_parse 档（temp0 全文→严格数字或 REFUSAL 解析，解析失败→E14 按样本记）。backoff 重试；端点不可用→E13；**每次调用的原始返回逐样本落 `review/judge_raw/<name>.jsonl`**（聚合可重算是复评的前提）。成本记录（token 计数）落点：**凡由 TraitJudge 产出的每份 `review/*.json` 报告均带 `cost` 尾注字段**（调用数、输入/输出 token 合计）。
**C2.3 `eval/judge/blind.py`**：`blind_score(pool_csv, eval_prompt, out_jsonl)`——输入行 schema 断言（只许 sample_id/question/answer，见 F8）；洗牌（seed 落盘）；逐样本 TraitJudge 打分（trait + coherence 两项；coherence eval prompt 从 `third_party/persona_vectors/eval/prompts.py` 只读取用，取用行号记入报告）；输出 {sample_id, trait_score, coherence_score, judge_raw_ref}。`tests/contract/stage2/test_c_judge_blind.py`：对含违禁列的输入拒绝（断言 raise）；洗牌可复现；对 6 条真实样本（自拟 2 组×3 答）端到端打分成功且 judge_raw 可重算出相同聚合。
**C2.4 实链评分与复评**：对 A 已落盘的真实 run（S1 tinyqwen e2e 与 S2 0.5B/3B 烟检 run）跑 score + review 全链，pass=true。
**C2.5 `repro_pack.py` + 首个复现包**：CLI `python -m abcr.repro_pack --preset stage2|mini-loop --out repro_packs/<name>`。打包逻辑：复制清单内工件 → `pack_manifest.json`（逐文件 sha256、来源路径、打包时间、git_commit）→ `README.md`（模板内嵌：包内容说明、**复算命令**、**诚实条款全文**——见下、non-citable/exploratory 声明、judge 谱系）→ 自验 `python -m abcr.review --pack <dir>`。
- **stage2 preset 清单**：`vectors/qwen2.5-3b-instruct/optimistic-dev/` 三件套 + flip_preview.md；B 的抽取/方向检 CSV 与 judge_raw（`pv_bridge/out/` 相关子集）；patches/ 两枚 + PV-PIN.txt + BRIDGE-FIDELITY.md；configs/models.yaml + templates；两 venv 的 `pip freeze` 输出。复算语义分两档：**`review --pack` 自动做** = ②judge_raw→聚合分重算比对 + ③全部 sha256 对 pack_manifest；**README 记载的手工命令** = ①CSV→generate_vec 重算 .pt 比对 sha（依赖仓内 third_party 与 .venv-pv，README 注明「需 torch 环境，非 G5 闭合门要求」）。
- **诚实条款（README 模板逐字内嵌）**：「本包承诺的复现 = ①工件级（原始输出永久保存，再分析不依赖重新生成）+ ②统计级（同 config 重跑，聚合指标在自身抽样波动内一致）+ ③单机确定级（同机同环境 temp 0 双跑一致）。不承诺跨硬件 bit 级一致——浮点归约序差异是行业已知事实。本包全部产物为 Mac dev 档（fp16/MPS 或 fp32/CPU），non-citable，仅证明管线正确性，不构成任何科学结论。」
- `test_c_first_pack.py`：出包 → `review --pack` 全绿 → 手工改包内任一文件一字节 → review 报 sha 不符（fail-closed 自证）。

**S2 验收**：probe 报告（7/14 上午即出）；judge client/blind 测试绿；实链 score+review pass；首包出包并通过自验+篡改检测。STATUS-C 更新，停阶段门。
**等待期可做**：主图脚本、exprcheck 报告模板、CLOSURE-PROTOCOL 草稿。

### 阶段 3（S3）：dev 表达检先行 + mini 环评分复评 + 主图（表达检与准备 7/16；mini 环评分复评在 A 过夜跑完后 = 7/17 上午）

**C3.1 mini 环全量评分复评**：读 `runs/MINILOOP-RUNSET.json`（A 产，含 main_runs 与 t0_runs 两组）→ **main_runs 四 run 逐一 score + review；t0_runs 仅 review（链/完备性审计），不评分不进主图**；`tests/contract/stage3/test_c_review_full.py` = main_runs 四 review 全 pass 且跨 run 交叉核对（四臂同 split 同题集、同 seed 集；vanilla 与各干预臂 prompt_hash 的一致性规则：文本臂 ≠ vanilla、向量/随机臂 = vanilla——臂纯度的评分侧证据）。
**C3.2 dev 表达检**（消费 B 的 exprcheck 素材；缺位后备：改用 optimistic 的方向检数据出简化报告并记 DEVIATIONS）：`blind_score(pv_bridge/out/conscientiousness/exprcheck_pool.csv, <eval_prompt>)`——**eval_prompt 取 `artifacts/traits/conscientiousness/eval.json` 的 `eval_prompt` 字段**（B 产工件，你只读）→ 盲评完成后用 `pv_bridge/out/conscientiousness/exprcheck_key.csv` 解盲 → `review/exprcheck_conscientiousness_report.json`：{n, 各条件 trait 分均值/中位数, 方向判定(steered_pos > baseline > steered_neg?), 效应量(Cohen's d, pos vs baseline), coherence 均值（副作用轻量初筛,只记录不设门槛）, 置换 seed, judge 谱系}；配图 `figures/exprcheck_conscientiousness.png`（逐题分布 + 条件均值，角标 `dev · non-citable · exploratory`）。**W1 判定口径（dev 级）**：方向清晰 + 效应量记录在案即可，不做显著性检验（W2 补）。
**C3.3 主图**：`figures/fig_mini_loop.py` → `figures/mini_loop.png`——面板1：四臂逐 seed 得分点图（is_correct 率）；面板2：四臂输出长度（output_tokens）分布（W2 长度三段分解预热）；大角标：`rig-validation run — NOT evidence · non-citable · dev split`。

**S3 验收**：四 review pass；exprcheck 报告与图；主图。STATUS-C 更新，停阶段门。

### 阶段 4（S4）：闭合验收 + 双 judge + 终包（目标 7/17 下午）

**C4.1 终包**：`repro_pack --preset mini-loop --out repro_packs/w1-mini`——清单：main_runs 四 run 目录（steps/manifest/env.lock/activations；env.lock 位置按 manifest/steps 的 env_lock_ref 引用解析后复制入包）+ t0_runs 的 steps/manifest + scores + review 报告 + items.jsonl + split 及 .sha256 + 用到的 configs + exprcheck 报告与图 + 主图 + **`rescore/` 自包含复算捆绑**（stdlib-only：checkers.py/registry.py 副本 + verify_chain/canonical_json/manifest 校验的必要函数副本 + 薄入口 `rescore.py`——打包时由 repro_pack 从 src/abcr 复制生成并断言零第三方 import，使闭合验收无须任何 venv）+ README（**复算命令 = `python3 rescore/rescore.py .`**，系统 python 即可；诚实条款；标注）。自验（`review --pack` 与 rescore 双跑一致）+ 篡改检测同 S2。
**C4.2 闭合验收协议**：写 `repro_packs/CLOSURE-PROTOCOL.md`，内含给楠（或任何人）的逐字操作卡：
> 开一个**全新** Claude Code 会话（空目录启动，勿在 abcr 仓内），把下面这段话原样发给它：
> 「你收到一个实验复现包：/Users/superagent/abcr/repro_packs/w1-mini。**除该目录外不要读取任何项目文件、不要使用任何项目 venv**。按包内 README 的复算命令（`python3 rescore/rescore.py .`，包内自含全部代码，系统 python3 即可），从原始 steps.jsonl 独立重算全部确定性分数，与包内 scores 逐条比对，输出：逐 run 一致/不一致结论、任何哈希或链校验异常、你无法仅凭包内信息完成复算的每一处缺口。」
> 验收标准：分数逐条一致、链与哈希零异常、缺口清单为空。任何缺口 = G5 未过，修包重验。
执行本协议（你可以自己开该新会话执行，或在 STATUS-C 中请楠执行——两者都算数，前者更快）。结果记 `repro_packs/w1-mini/CLOSURE-RESULT.md`。
**C4.3 n=50 双 judge 一致性**：从 `third_party/persona_vectors/output/qwen2.5-7b-instruct_baseline.csv` 只读取样 50 行（列名运行时自查，取 question/answer 语义列；结构不符则改用 B 的 3B 抽取 CSV 并记 DEVIATIONS）→ 用官方 optimistic eval_prompt：judge①=DeepSeek（client 模式）、judge②=Claude CLI（`CLAUDE_RAW=1 ~/.local/bin/claude -p "<填充后 eval_prompt>" --output-format json`，从返回 JSON 的 result 字段解析数字、model/usage 字段记录模型名与消耗；若 JSON 无 model 字段则另记 `claude --version` 与会话默认模型名）→ `review/judge_consistency_n50.json`：{n, pearson, spearman, MAE, 均值差, REFUSAL/解析失败率, 样本 ref, 同源提示:"第二 judge（Claude）与锚 trait 工件生成模型同源，此一致性数据用于量化 DeepSeek 替换漂移，不作独立效度证明"}+ 散点图 `figures/judge_consistency.png`。`test_c_dual_judge_n50.py` = 报告存在且字段完备、n=50、两列分数非常数。
**C4.4** 图表终检（每张图有角标）；STATUS-C 终态。

---

## 5. 验收总清单（C 完工定义）

1. S1：14 checker 全实现全单测；黄金检 ≥12 例逐例命中（期望值人工核定）；故障注入四类全被抓且码精确。
2. S2：probe 报告（B 可消费）；judge client 双模式 + judge_raw 可重算；blind 违禁列拒绝自证；实链 score+review pass；首包 + 篡改检测。
3. S3：mini 环四 run 复评全 pass + 臂纯度评分侧证据；dev 表达检报告与图；主图（角标齐全）。
4. S4：终包 + **闭合验收执行且 CLOSURE-RESULT 在案**；n=50 双 judge 报告与图；STATUS-C 终态。
5. 全程：runs/ 零写入（自证）；key 零泄露（`rg -i "sk-" --glob '!*.md'` 无真值命中）；每 WBS 一 commit；DEVIATIONS 如实。

## 6. 不做清单（C 范围外，勿做）

一切生成（模型推理/向量/trait 工件——B 的领域，你连 3B 都不需要加载）；runner/题库构建/split（A）；对 runs/steps 的任何写入或"修复"（发现坏账只报错误码，修复权在 A 的 --repair）；显著性检验与混合模型（W2）；界面；checker 第二实现（W2，黄金检已对冲）。

## 7. 缺口处置

未覆盖决策按「审计独立性优先、fail-closed、一切可重算」三原则就地决定，记 DEVIATIONS.md（`[C] <日期> <决策> <理由>`）。接口冻结区级缺口：STATUS-C 标 `BLOCKED-CONTRACT` 等阶段回归裁决。你与 A/B 产物冲突时（如 schema 字段不符）：**以冻结区文本为准报 E 码**，不迁就实现。

## 8. V1.1 补丁接入注记（2026-07-12 append；本文档其余内容不变）

《ABCR-W1执行方案-V1.1补丁-资源治理门与节奏修订》（同目录）已发布：D16/F14 资源契约、错误码 E19/E20/E21、S1.5 资源治理门对本包生效，冲突以补丁为准。C 包最低必守：
1. **claude CLI 批量属重负载**：预计调用数 >5 或上界不可预估的批量任务（如 n=50 双 judge 类）必须经 `python -m abcr.resource_guard run -- <cmd>` 包装执行（持 heavy.lock）；单次 `-p` 调用与 DeepSeek API、确定性评分/复评/打包照旧为轻活。已按轻活启动的任务要发第 6 次 CLI 调用时必须先取锁。
2. **终包质量修正**（补丁 §6，w1-full 起生效）：P1 env.lock = 真实 `uv pip freeze`（两 venv 各一份，禁 UNAVAILABLE 字面量）；P2 t0 子 run 出 scores 或 manifest 显式 `scored:false`+原因；P3 协议文档（V1.0 全文 + V1.1 补丁全文）随包并记 sha256。
3. 新 run 的 `protocol_ref` 自批2 起为双指针（V1.0 + V1.1 补丁，见补丁 §8-2），review/manifest 校验时按双指针核对。
