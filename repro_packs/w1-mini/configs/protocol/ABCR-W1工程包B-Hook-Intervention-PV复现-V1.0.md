# ABCR W1 工程包 B：Hook + Intervention + Persona Vectors 复现（V1.0，自足执行文档）

> 执行者：一个独立 Claude Code 窗口（建议 Opus 长上下文）。本文档自足：**执行全程不需要、也不要读取 shared-brain 下任何文件**，唯一豁免 = 同目录上位文档《ABCR-W1执行方案-V1.0.md》的 §4（接口冻结区权威版本 + F13 bootstrap 脚本权威全文），除此以外一律不读。允许且必须读取的外部代码只有一处：你自己克隆到 `third_party/persona_vectors` 的官方仓库（vendored 依赖，不属于 shared-brain）。
> 你的使命：把「干预」做成**对 A 不透明、对 C 只是原始输出**的库与工件——residual hook 与其三重正确性验证、Persona Vectors 官方配方的 Mac 复现线（0.5B/3B dev 级）、trait 工件生产、标准化向量工件、翻转预览、云日 Runbook。**你只输出标准化向量工件与原始生成物**；评分判定归 C，运行编排归 A。

---

## 0. 统一执行纪律（三包相同）

1. 文档没写的细节：独立决策，在 `/Users/superagent/abcr/DEVIATIONS.md` 追加一行（前缀 `[B]`），不回查任何外部文件。
2. 只写「所有权矩阵」（§3-F7）中属于 B 的文件；消费他包产物只认冻结路径，缺位走本文档后备；**不跨窗口沟通**。
3. **按阶段推进**：完成阶段 N 自验后更新 `/Users/superagent/abcr/STATUS-B.md`（含验收输出摘录），停在阶段门等统一回归。回归协议：三包 STATUS 均报完成后，由**最后完成的窗口**跑 `make stage<N>-regression`，全绿提交 `[REG] stage<N> PASS`（失败提交 FAIL+摘要，责任包修复重跑）；**你的放行信号 = git log 出现该 PASS 提交**。等待期只做本文「等待期可做」项。
4. 每完成一个 WBS 条目 git commit（前缀 `[B]`）；遇 `index.lock` 等 2s 重试 ≤5 次。
5. 验收断言必须真实跑过、输出留存；失败如实报告，**禁止降低断言换绿**。
6. 治理三条：本窗口不跑 `/boss`；本仓永不 `git push`；仓内路径规避子串 `"/persona/"`、`"v_core"`、`"judgment_engine"`（注意：`third_party/persona_vectors`、`pv_bridge` 均不含 `"/persona/"` 精确子串，合规；新建路径沿用 `traits/`、`pv_` 词根）。

## 1. 背景 primer（2 分钟读完，不需要更多背景）

ABCR 是楠的 12 周研究项目：在 Qwen2.5 家族上研究「人格文本效应 × 内部人格向量」的因果关系。主线抽取配方 = Persona Vectors 式残差流差分均值（官方仓 safety-research/persona_vectors，正负人格 prompt 下响应 token 的逐层平均激活之差）。W1 不产科学证据，只造**产生证据的机器及其正确性证明**。五阶段执行（S0 契约 → S1 全 fixture → S2 一个官方 trait → S3 一个锚 trait + mini 环 → S4 闭合与扩展），阶段内三包并行、阶段间统一回归。知识边界（冻结）：**B（你）只输出标准化向量工件；A 不理解向量生成过程；C 只消费原始输出、不参与生成**。

Mac 产物一律 non-citable（正式证据需 24GB 云卡 bf16，本周期不租卡；你负责把云日写成 Runbook）；judge 已由官方的 gpt-4.1-mini 替换为 DeepSeek（谱系必须记录此替换）。**方向复现检（S2）未过之前，不制作自定义锚 trait**（楠阶段律）。

## 2. 环境与治理事实（已实测，直接信任，不必复查）

- Mac mini M4，16GB，macOS 26.4.1，磁盘余 122Gi。**7B 本机跑不动**；3B fp16 MPS 流畅（≈15–25 tok/s 量级预期）；0.5B CPU 可跑。
- `/opt/homebrew/bin/python3.11`（3.11.15）与 `uv`（0.11.3）可用；系统 python3=3.14 不要用。PyPI/HF 直连；Qwen2.5 模型不 gated 匿名下载。
- **DeepSeek key**：`/Users/superagent/oc-boss-state/deepseek.key`（0600，非空）。注入方式见 F8；key 值绝不入文件/git/日志。api.deepseek.com 存活（匿名 401 属预期）。
- **claude CLI**：无头调用一律 `CLAUDE_RAW=1 ~/.local/bin/claude -p ...`（v2.1.207，订阅通道；zsh 的 `claude` 是 AILH launcher 函数，勿直接用）。ANTHROPIC_API_KEY 按治理不得设置。
- **persona_vectors 官方仓**（已代码级核验，你可直接信任）：钉 commit `b8e0f044fe2410a6fad579f38324f03f13b4e917`（2026-04-22）。要点：
  - requirements 含 `vllm==0.8.5.post1 / bitsandbytes / unsloth / trl`（Mac 不可装，剔除）；`torch==2.6.0 / transformers==4.52.3 / openai==1.70.0 / peft==0.15.1 / accelerate==1.7.0 / datasets==3.6.0 / pandas==2.3.1 / fire / backoff / pyyaml / tqdm`（Mac 可装）。
  - `eval/eval_persona.py` **顶层 `from vllm import LLM`** → Mac 不可 import（这就是需要你写 pv_bridge 的原因）；其内 `sample_steering()` 为纯 transformers。
  - `activation_steer.py::ActivationSteerer`：**层约定 = 用户层号 L 挂 `model.layers[L-1]`（等价 hidden_states[L]）**；`positions ∈ {all, prompt, response}`；对 block 输出 tuple 的 `[0]` 加 `coeff*vector`。
  - `generate_vec.py` 纯 transformers；输入 pos/neg CSV（列 `prompt`=已渲染模板全文、`answer`、`<trait>`、`coherence`），过滤 `pos[trait]>=50 & neg[trait]<100-50 & 双方 coherence>=50`；对 `prompt+answer` 拼接文本前向、按 prompt_len 切分，输出 `{trait}_{prompt_avg|response_avg|prompt_last}_diff.pt`，shape=(层数+1, hidden)；**其 from_pretrained 未传 dtype（默认 fp32）——必须打 --dtype 补丁**。
  - `judge.py::OpenAiJudge`：`AsyncOpenAI()`（读 `OPENAI_API_KEY`/`OPENAI_BASE_URL` 环境变量）；0_100 打分 = max_tokens 1 + logprobs top-20 概率加权；另有 binary_text 全文解析档。**`judge.py` 在 import 时即执行 `setup_credentials()`——import 前必须先注入 key**。
  - `config.py` 强制 `OPENAI_API_KEY` 与 `HF_TOKEN` 双双非空否则 raise → HF_TOKEN 需可选化补丁。
  - trait 工件：`data_generation/trait_data_extract|eval/<trait>.json` = `{"instruction":[5×{pos,neg}], "questions":[20], "eval_prompt":"...REFUSAL 或 0-100..."}`；自带 7 个 trait（optimistic/sycophantic/evil/apathetic/hallucinating/humorous/impolite）。新 trait 生成 prompt = `data_generation/prompts.py::PROMPTS["generate_trait"]`（产 5 指令对 + 40 题 + eval_prompt，JSON 输出）。
  - 官方 CLI（云日 Runbook 逐字基准）：
    ```
    python -m eval.eval_persona --model <M> --trait <t> --version extract --persona_instruction_type pos|neg --assistant_name <n> --judge_model <j> --output_path <csv>
    python generate_vec.py --model_name <M> --pos_path <csv> --neg_path <csv> --trait <t> --save_dir <d> --threshold 50
    python -m eval.eval_persona --model <M> --trait <t> --version eval --steering_type response --coef <c> --vector_path <p> --layer <L> --judge_model <j> --output_path <csv>
    ```
  - 官方自带 `output/qwen2.5-7b-instruct_baseline.csv`（C 的双 judge 一致性会用，你无须处理）。
- 治理：`/Users/superagent/abcr` 不受任何沙箱/hook 拦截（源码级已核）；SessionStart 注入的 AILH 背景无害忽略；git 本地仓、无远端、永不 push。

## 3. 接口冻结区 v1（等效副本；如有出入以上位 §4 为准；本节「见上位」指针均指上位文档 §4 的对应条目）

### F1 仓库与身份
- 路径 `/Users/superagent/abcr`；本地 git（`git init -b main`；`git config user.name "Yinan Wang"`；`git config user.email worldofnan130@gmail.com`），无远端、永不 push。
- 提交前缀 `[A]`/`[B]`/`[C]`/`[REG]`；`index.lock` 冲突：等 2s 重试 ≤5 次。
- 三包文件所有权互斥（F7）；`mkdir -p` 不算冲突；`DEVIATIONS.md`、`STATUS-*.md` 为共用 append 文件。

### F2 环境
- 主 venv `.venv`（uv，python3.11）：`torch==2.6.0, transformers==4.52.3, accelerate==1.7.0, datasets==3.6.0, pandas==2.3.1, pyarrow, duckdb, scipy, statsmodels, matplotlib, typer, pydantic==2.11.7, pyyaml==6.0.2, pytest, openai==1.70.0, backoff==2.2.1, tqdm, huggingface_hub`；torch 装不上放宽 `>=2.6,<2.8` 记 DEVIATIONS。
- **`.venv-pv`（你建，third_party 专用）**：官方 requirements 的 Mac 子集（见 B2.3）。
- 模型 revision 钉死：snapshot 目录名 → `configs/models.yaml`（bootstrap 完成）；加载必显式 `revision=`。合法 model_key 集 = {tinyqwen, qwen2.5-0.5b-instruct, qwen2.5-3b-instruct, qwen2.5-7b-instruct}（条目格式 {model_id, revision}）；7B 占位 `PIN-AT-CLOUD-PROVISION`。你做向量 shape 校验（层数/hidden）时用 `AutoConfig.from_pretrained`（免载权重）。
- tinyqwen（S1 假模型）：hidden 64 / 4 层 / float32 / 0.5B tokenizer，`tests/fixtures/tinyqwen/`（bootstrap 生成）。

### F3 目录布局
（完整目录树见上位 §4-F3；此处列你常用子集）
```
third_party/persona_vectors/   # 你克隆，.gitignore 排除，改动只经 patches/
patches/{pv-config-hftoken-optional.patch, pv-generate-vec-dtype.patch, PV-PIN.txt}
pv_bridge/{extract_mac.py, flip_preview.py, exprcheck_gen.py, BRIDGE-FIDELITY.md, out/}
artifacts/traits/<trait>/{extract.json, eval.json, provenance.json}
vectors/<model-slug>/<trait>-dev/{response_avg_diff.pt, card.json, extraction_meta.json, flip_preview.md?}
src/abcr/interventions/{api.py(A 所有,勿改), prompt_persona.py, residual_vector.py, projection_ablation.py, random_direction.py, capture.py}
scripts/cloud/{cloudday1-official-trait.md, cloudday2-anchor-traits.md, parity-smoke.md}
tests/{fixtures/vector_tiny/, contract/*/test_b_*.py, unit/test_b_*.py}
```

### F4 steps.jsonl schema（w1.1）
（全字段表见上位 §4-F4——你的 describe()/spec 透传字段必须恰好落进「条件」组：condition, trait, trait_pole, method(none/prompt_persona/residual_vector/projection_ablation/random_direction), layer, coefficient, intervention_strength。**projection_ablation 特例**：W1 仅用于黄金测试、不写入任何 steps.jsonl；其 describe().condition 固定 "projection_ablation"，不受 F4 condition 枚举约束。）

### F5 写入语义 / F6 scores·review·工件
（全文见上位 §4-F5/F6。你最关心的是 F6 的**标准化向量工件**定义——你的唯一输出形态：）
- `vectors/<model-slug>/<trait>-<grade>/`（grade=dev|citable）三件套：
  - `response_avg_diff.pt`：torch float32，shape=(层数+1, hidden)（官方 generate_vec 原生产物，逐字节保留）；
  - `card.json`：{trait, model_id, model_revision, source_commit（pv 仓 commit）, extraction_date, grade, judge_model, judge_lineage, recommended:{layer:int, coef:float}, n_pos_effective:int, n_neg_effective:int, pt_sha256, notes}；
  - `extraction_meta.json`：{n_instructions, n_questions, n_responses_per_q, filter_threshold, pos_csv_sha256, neg_csv_sha256, questions_sha256, bridge_version, device, dtype}。
- judge 判定工件：judge 原始返回必须逐样本落盘可重算（bridge 的 CSV 落 `pv_bridge/out/`；正式 runs 的落 `runs/<id>/judge_raw.jsonl`）。

### F7 所有权矩阵
| 路径 | 所有者 |
|---|---|
| scripts/bootstrap.sh、pyproject.toml、CLAUDE.md、README.md、Makefile、configs/、src/abcr/{models,run,splits}.py、logging/、interventions/api.py、data/、runs/（数据）、costs/、tests/fixtures/（golden_answers、vector_tiny 除外）、tests/*/test_a_*.py | A |
| src/abcr/interventions/{prompt_persona,residual_vector,projection_ablation,random_direction,capture}.py、third_party/、patches/、pv_bridge/、artifacts/traits/、vectors/、scripts/cloud/、tests/fixtures/vector_tiny/、tests/*/test_b_*.py | **B（你）** |
| src/abcr/{score,review,repro_pack}.py、eval/ 全部、scores/ review/ repro_packs/ figures/、tests/*/test_c_*.py、tests/fixtures/golden_answers/ | C |

### F8 密钥与 judge 纪律
- 注入（每个需要 judge 的 shell/进程）：`export OPENAI_API_KEY=$(cat /Users/superagent/oc-boss-state/deepseek.key); export OPENAI_BASE_URL=https://api.deepseek.com`；judge 模型名 `deepseek-chat`。**key 不写入任何文件/git/日志/报错回显；禁止创建 .env**（官方 config.py 支持 .env，但本项目禁用——环境注入足够）。
- 谱系：一切 judge 产物记 `judge_model=deepseek-chat, judge_lineage=replaced(official gpt-4.1-mini-2025-04-14)`。
- trait 表达类打分盲评归 C；你的 bridge 内 judge 允许非盲的场景（上位 F8 豁免条款）：**抽取过滤**（数据清洗）与**方向复现检 / 翻转预览 / recommended 标定**（向量生产内部 QA）——产物仍记 judge 谱系、不作科学证据。

### F9 呈现与运行纪律
Mac 产物恒 `citable=false`/grade=dev；对外数字必带 exploratory / non-citable 标注；fail 方向：校验类 fail-closed，旁路信号 best-effort；云预算 ¥150 常量，costs/ledger.jsonl 记账。

### F10 错误码（logging/errors.py，A 实现）
E01–E18 全表见上位 §4-F10；你最常触的：E13_JUDGE_UNAVAILABLE（端点不可用→整批 blocked 不静默跳）、E14_JUDGE_PARSE_FAIL（按样本记，率>10% 整批 fail）、E15_VECTOR_ARTIFACT_INVALID（三件套不齐/shape 或 sha 不符）、E17_DISJOINTNESS_VIOLATION（抽取∩评测≠∅）、E18_GOLDEN_FAIL。

### F11 你参与的分阶段契约测试
- S1：test_b_zero_injection / test_b_displacement / test_b_ablation / test_b_random_norm
- S2：test_b_pv_e2e_05b / test_b_direction_3b
- S3：test_b_capture
- S4：扩展项验收（锚 #2/#3、Runbook 终检）

### F12 checker 契约 CT-1
（A/C 之间的题库-评分契约，与你无关；权威版在上位 §4-F12。）

---

## 4. WBS（按阶段执行）

### 阶段 0（S0）：bootstrap + 接口对齐（目标 7/11 内）

**B0.1** 执行 bootstrap：脚本权威全文在**上位 §4-F13**（你被明示允许读取的唯一外部文档章节）。若 `scripts/bootstrap.sh` 已存在则直接执行；不存在则按 F13 全文写入后执行。A 窗口已跑完会立即返回 "bootstrap done"；若你先启动就由你执行（互斥锁保证不双跑）。
**B0.2** 等 A 落位 `src/abcr/interventions/api.py` 与 `logging/{schema,errors}.py`（S0 内应出现）。**等待期不空转**：先写你的实现文件（协议规格本文档已完整给出，见下），api.py 落位后跑通 import。api.py 协议（与 A 文档一致，你按此实现）：
```python
class Intervention(Protocol):
    spec: dict                      # 原样写入 step 条件组
    system_text: str | None
    def context(self, model): ...   # contextmanager；hook 挂/摘在此
    def describe(self) -> dict: ... # {condition, trait, trait_pole, method, layer, coefficient, intervention_strength}
    def activation_summary(self) -> dict | None: ...
# runner 侧补充语义：runner 在需要激活抽样时于 generate 前设 iv.capture_path=<npz路径>；
# 你的实现若见 capture_path 非空则采集并在 activation_summary() 返回摘要，否则返回 None。
# get_intervention(spec, model_key) 按 spec['method'] importlib 加载 abcr.interventions.<method>.build(spec, model_key)
```

### 阶段 1（S1）：hook 库与三重验证（目标 7/12–7/13；tinyqwen CPU float32，不接网不接 judge）

**B1.1 `interventions/residual_vector.py`**。`build(spec, model_key) -> Intervention`：
- spec：{method:"residual_vector", vector_dir, layer?, coefficient?, trait?, positions?="response"}。加载 `vector_dir` 三件套：三文件齐全、`pt_sha256` 与 card 一致、shape=(L+1,H) 与目标模型 config 一致，否则 AbcrError(E15)。layer/coef 缺省从 card.recommended 取。
- hook：`model.model.layers[layer-1].register_forward_hook`（**官方层约定：用户层号 L → index L-1**）；block 输出为 tuple → `out[0] = out[0] + coef * v`（v 取 `pt[layer]`，cast 到模型 dtype/device）。positions 语义（对齐官方 ActivationSteerer）：`response` = 仅对生成 token 生效——prefill 前向（seq_len>1 且无 past）跳过、decode 前向（seq_len==1）生效；`all` = 一律生效（供测试断言用）。
- `describe()`：{condition:"residual_vector", trait:card.trait, trait_pole:null, method:"residual_vector", layer, coefficient, intervention_strength: |coef|·‖v[layer]‖₂（float）}。
- capture 集成：见 B1.4。

**B1.2 `interventions/projection_ablation.py`**：同构；hook 改 `h ← h − (h·v̂)v̂`（v̂=单位化 v[layer]）；method="projection_ablation"。W1 只用于黄金测试与 W2 铺路，不进 mini 环。

**B1.3 `interventions/random_direction.py`**：两种模式。**参照模式** spec {method:"random_direction", match_to:<vector_dir>, direction_seed:int, layer?, coefficient?}——从 match_to 的 card/pt 取参照 layer/coef 与 ‖v[layer]‖，`torch.Generator(seed=direction_seed)` 抽高斯向量（dim H）归一后放缩到同范数。**无参照字面量模式** spec {method:"random_direction", layer:int, coefficient:float, target_norm:float, direction_seed:int}——向量归一后放缩到 target_norm（供 A 的向量工件全缺位后备，如 {layer:20, coefficient:8.0, target_norm:1.0, direction_seed:5678}）。hook 同 B1.1。describe：method="random_direction", trait:null, coefficient/intervention_strength 按所用模式实值；spec 全量随 step 透传。同 seed 必复现同向量。

**B1.4 `interventions/capture.py`**：投影采集器——在目标层挂只读 hook，逐生成 token 记 `(h·d̂)` 标量（**d̂ = 该臂自己注入的方向**：向量臂用 v̂、随机臂用 r̂；方向来源写入 npz 元数据）；`finalize(path)` 存 npz{proj:[...], meta} 并返回 {path, layer, proj_mean, proj_p50, proj_p90}。residual_vector/random_direction 在 capture_path 非空时启用（对被注入后的 h 采集）。**抽样率归属**：是否采集（约 10% 的 step）由 A 的 runner 经 capture_path 决定，你只负责被选中 step 的逐 token 全记与摘要质量；10% 覆盖断言在 A 的 test_a_mini_loop_coverage，你的 test_b_capture 只断言 npz 合法性与摘要字段。vanilla/prompt_persona 臂 W1 裁定 capture_path 恒 None（文本臂投影分布采集移 W2 剂量标定）；此裁定记入 card.notes。

**B1.5 `interventions/prompt_persona.py`**：spec {method:"prompt_persona", artifact:<extract.json 路径>, instruction_index:int, trait, trait_pole:"pos"|"neg"}。读 artifact 的 `instruction[instruction_index][trait_pole]` 为 system_text；context=nullcontext；describe：method="prompt_persona"，layer/coefficient=null。**臂纯度**：本模块不 import torch hook 相关任何东西。

**B1.6 fixture 向量工件** `tests/fixtures/vector_tiny/`：对 tinyqwen（pt shape=(5,64)）造已知向量三件套——**layer 2 行 = v（seed 0 单位向量 ×√H 缩放），其余 4 行全零**；card.json 占位字段统一：{trait:"tinyqwen-fixture", model_id:"tinyqwen", model_revision:"local-fixture-seed0", source_commit:"n/a", grade:"dev", judge_model:"n/a", judge_lineage:"n/a", recommended:{layer:2, coef:3.0}, n_pos_effective:0, n_neg_effective:0, pt_sha256:<真算>, notes:"S1 契约测试专用"}；extraction_meta.json 各计数字段填 0、hash 字段真算——契约测试与 A 的 fixture 运行共用。

**B1.7 S1 契约测试**（tinyqwen，float32，greedy）：
- `test_b_zero_injection.py`：coef=0 挂 hook vs 不挂：同 prompt greedy 生成 20 token，token id 序列**完全一致**。
- `test_b_displacement.py`：`positions="all"`、coef=3.0、layer=2：带 hook 与不带 hook 各做一次 `output_hidden_states=True` 前向，断言 `hs_hooked[2] − hs_plain[2] ≈ 3.0·v`（atol 1e-5）。同时断言 layer≠2 的**下游层已变化**（hook 真的在传播）而上游层（index<2）不变。
- `test_b_ablation.py`：消融 hook 后该层输出与 v̂ 的投影绝对值 ≤ 1e-5（逐位置）。
- `test_b_random_norm.py`：100 个 direction_seed：每个 ‖r‖ 与参照范数差 ≤1e-6；|cos(r, v)| 均值 <0.2 且最大 <0.6（dim=64 的统计界）；同 seed 复现同向量。

**S1 验收**：四测试全绿输出留存；STATUS-B 更新，停阶段门。
**等待期可做**：B2 的 clone/补丁/venv-pv（不跑 judge）；BRIDGE-FIDELITY 研读。

### 阶段 2（S2）：官方 optimistic 复现线（目标 7/14–7/15）

**B2.1 克隆钉版 + 官方工件标准化落位**：`git clone https://github.com/safety-research/persona_vectors /Users/superagent/abcr/third_party/persona_vectors && cd $_ && git checkout b8e0f044fe2410a6fad579f38324f03f13b4e917`；写 `patches/PV-PIN.txt`（commit、日期、clone 命令）。随后立即把官方 optimistic 工件按 F6 schema 落 `artifacts/traits/optimistic/`：extract.json/eval.json = 克隆内 `data_generation/trait_data_extract|eval/optimistic.json` 原样复制，provenance.json = {generator:"official", source:"persona_vectors@b8e0f04", review_status:"official"}——这是 A 的 mini 环文本臂后备所依赖的承诺产物。
**B2.2 两个补丁**（先改文件、验证、再 `git diff > patches/<名>.patch`，patch 文件入 abcr git；BRIDGE-FIDELITY.md 记偏差声明）：
- `pv-config-hftoken-optional.patch`：config.py——hf_token 属性改为 `os.environ.get('HF_TOKEN','')` 不 raise；setup_environment 仅在非空时设置；validate_credentials 只验 openai key。（Qwen2.5 不 gated，无需真 token；此补丁不触科学内容。）
- `pv-generate-vec-dtype.patch`：generate_vec.py——`save_persona_vector` 增 `dtype` 参数（"float32"/"float16"/"bfloat16"），传入 `from_pretrained(..., torch_dtype=...)`；argparse 增 `--dtype`，默认 float32（保官方原语义）。
**B2.3 `.venv-pv`**：`uv venv --python /opt/homebrew/bin/python3.11 .venv-pv && uv pip install -p .venv-pv/bin/python torch==2.6.0 transformers==4.52.3 accelerate==1.7.0 datasets==3.6.0 pandas==2.3.1 openai==1.70.0 backoff==2.2.1 fire==0.7.0 pyyaml==6.0.2 tqdm==4.67.1 peft==0.15.1`。验证（key 先注入）：`cd third_party/persona_vectors && ../../.venv-pv/bin/python -c "import judge; print('judge importable')"`。
**B2.4 保真度研读**：通读克隆内 `eval/eval_persona.py` 的 extract 路径与 `eval/prompts.py`，把**官方 extract 的精确语义**记入 `pv_bridge/BRIDGE-FIDELITY.md`（逐条带文件行号）：system prompt 如何由 instruction pos/neg 与 assistant_name 组装、每题响应数、解码参数、trait 与 coherence 两个 judge 的 prompt 来源与调用形态、CSV 确切列名。**桥的每一处实现都必须能指回此文件的一条记录**；官方语义不明处保守复刻并记 DEVIATIONS。
**B2.5 judge 探针结论消费**：读 `review/judge_probe_report.json`（C 产，D0 实测 DeepSeek logprobs 可用性）。**后备**：若你到达此步时该文件缺位，自跑最小探针（10 次 judge 调用、记录 top_logprobs 是否返回、0-100 数字是否单 token），结论写 `pv_bridge/out/judge_probe_fallback.json` 并记 DEVIATIONS；若 logprob 加权不可行 → 官方 judge 改用 `eval_type="binary_text"` 同构的全文数字解析路径（judge.py 已内置该模式的解析骨架），偏差入谱系。
**B2.6 `pv_bridge/extract_mac.py`**（.venv-pv 运行；`sys.path` 注入克隆目录以复用其 `judge.OpenAiJudge` 与 prompts；生成侧自实现 transformers）：
- CLI：`--model-key --trait --artifact <extract.json> --pole pos|neg --n-per-q 2 --out-csv <path> [--device mps|cpu] [--dtype float16|float32] [--limit-questions N] [--limit-instructions N]`。
- 流程：读 artifact → 按 BRIDGE-FIDELITY 记录的官方语义组装消息 → `apply_chat_template` 渲染（**CSV `prompt` 列 = 渲染后全文**，generate_vec 依赖此语义）→ 逐条生成（temperature 与官方 extract 一致，见 BRIDGE-FIDELITY；`torch.manual_seed` 逐样本递增记录）→ 官方 judge 打 trait 分 + coherence 分（异步批量 + backoff）→ 写 CSV（列：prompt, answer, question, `<trait>`, coherence——前四列语义与官方逐一对齐）。judge 原始返回逐样本落 `<out-csv>.judge_raw.jsonl`。
**B2.7 0.5B 端到端烟检** `test_b_pv_e2e_05b.py`：optimistic（工件用 `artifacts/traits/optimistic/` 标准化副本），`--limit-instructions 2 --limit-questions 5 --n-per-q 1` × 双极（20 生成，CPU float32 可跑）→ 两 CSV → 补丁版 `generate_vec.py --dtype float32 --threshold 50`（如过滤后空集：阈值降至 30 重试一次并记 DEVIATIONS——0.5B 表达力弱属预期，烟检只验管线）→ 断言 `.pt` 存在、shape=(25, 896)、全 finite、非零。
**B2.8 3B dev 抽取**：optimistic 全量 dev 规格 `5 指令 × 20 题 × 2 响应 × 双极`（400 生成，MPS fp16，预估 3–5h，可与 B2.9 拆日跑；止损 `--n-per-q 1`）→ `generate_vec --dtype float16`（MPS；失败转 CPU float32 + `--limit` 减量）→ 产物按 F6 标准化落 `vectors/qwen2.5-3b-instruct/optimistic-dev/`：**取官方输出三份中的 `optimistic_response_avg_diff.pt` 一份、内容逐字节不动、重命名为 `response_avg_diff.pt`**（另两份 prompt_avg/prompt_last 留 `pv_bridge/out/`）+ card + meta；grade=dev。
**B2.9 方向复现检**（S2 门；`test_b_direction_3b.py`）：3B（36 层）取层 {16,20,24} × coef {±2.0, ±3.5}，每条件用官方 eval.json questions 的**前 10 道**（确定性选题）× 1 生成（+baseline 10）≈130 生成；官方 judge 打 trait 分。**断言**：存在层 L*，coef>0 均值 > baseline 均值 + 10 分 且 coef<0 均值 < baseline − 10 分（方向单调）且该条件 coherence 均值 ≥50。把 (L*, 最稳系数) 写入 card.recommended。**未过**：换层集 {8,12,28} 重试一次；仍未过 → 停下写失败决策包（现象、数据、两个假设、建议）入 STATUS-B，阶段门交 Fable 裁——**不得进入 S3 自定义 trait**（楠阶段律）。
**B2.10 翻转预览**（demo 素材，家庭可见进展）：`pv_bridge/flip_preview.py`——官方 eval.json questions 的**前 3 道** × {baseline, +coef, −coef}（用 card.recommended），并排文本 + judge 分 → `vectors/qwen2.5-3b-instruct/optimistic-dev/flip_preview.md`，头部大字标注 `⚠ dev preview · 3B · non-citable`。

**S2 验收**：e2e 烟检绿；3B 向量工件三件套齐且 E15 自检过；方向复现检数据与结论留存；flip_preview.md 落位。STATUS-B 更新，停阶段门。
**等待期可做**：B3.1 锚 trait 工件生成（工件生成不依赖阶段门——它是数据准备非实验），Runbook 初稿。

### 阶段 3（S3）：锚 trait #1 + exprcheck 素材（目标 7/16）

**B3.1 尽责（conscientiousness）工件生成**：
- **trait 命名统一（三 trait 通用规则）**：{TRAIT} 填值 = artifacts/vectors 目录名 = CSV 列名 = `--trait` 参数 = **同一个字符串**，三个锚 trait 分别为 `conscientiousness` / `openness` / `neuroticism`（官方 .pt 文件名前缀随之，如 `conscientiousness_response_avg_diff.pt`）。
- 从克隆读 `data_generation/prompts.py::PROMPTS["generate_trait"]`，填 `{TRAIT}="conscientiousness"`、`{trait_instruction}`（用本段英文描述，逐字）："Conscientiousness: careful, disciplined, and duty-bound behavior — systematically verifying claims and steps, following instructions and constraints precisely, attending to details, double-checking work before finalizing, and completing commitments rather than cutting corners."、`{question_instruction}` 留空字符串。
- `CLAUDE_RAW=1 ~/.local/bin/claude -p "<填充后 prompt>" --output-format text` → 解析 JSON（失败重试一次，再失败手工修剪围栏）→ 结构校验（5 指令对 / 40 题 / eval_prompt 含 "REFUSAL" 与 "0 to 100" 语义）。
- 40 题**确定性拆分**：前 20 → `artifacts/traits/conscientiousness/extract.json`，后 20 → `eval.json`（两文件均按官方 schema 含同一 eval_prompt）；断言两题集交集为空（E17）。
- `provenance.json`：{generator:"claude-cli-subscription", cli_version:"2.1.207", date, source_prompt:"persona_vectors@b8e0f04::data_generation/prompts.py::generate_trait", trait_description:"<上文>", review_status:"draft"}。
- 追加 `artifacts/traits/REVIEW-REQUEST.md`：给楠的过目清单（指令对是否双极干净、题目是否自然多样、eval_prompt 是否与 trait 一致；通过则把 review_status 改 approved）。**draft 态即可继续 dev 工序，云日 #2 前需 approved**。
**B3.2 尽责 3B dev 抽取**：**stage2 回归绿灯当晚即可作 S3 首项启动**（阶段律满足：方向复现检已过门）。同 B2.8 规格（400 生成或止损 200）→ `vectors/qwen2.5-3b-instruct/conscientiousness-dev/`（同 B2.8 的重命名规则）；mini 方向检定 card.recommended，矩阵明确为：**2 层（optimistic 的 L* 与 L*+4）× {+c, −c}（c = optimistic 的 recommended coef）× 尽责 eval.json 前 15 题 = 60 生成**。**这是 A 的 mini 环向量臂输入，目标 7/16 日间落位**（A 于 7/16 晚起跑；迟到则 A 走后备）。
**B3.3 exprcheck 生成素材**（C 的盲评表达检输入；「C 只消费原始输出」在此落地）：`pv_bridge/exprcheck_gen.py`——尽责 trait 的 20 道 eval 题 × {baseline, steered_pos(+coef), steered_neg(−coef)} × 2 响应（120 生成，recommended 层/系数）→ 混池乱序（记录置换 seed）写 `pv_bridge/out/conscientiousness/exprcheck_pool.csv`（列仅 sample_id, question, answer——**无任何条件标签**）+ `exprcheck_key.csv`（sample_id, condition；供 C 评分后解盲）。
**B3.4 `test_b_capture.py`**：向量臂在 capture_path 设定时产出合法 npz 与摘要统计（用 mini 环实跑数据或 3B 单题实测）。

**S3 验收**：尽责工件三件套 + REVIEW-REQUEST；尽责 dev 向量工件落位（时点早于 A3.2 启动，最迟 7/15 晚——若 A 已按后备起跑，落位仍有效供重跑/云日）；exprcheck 池与钥匙落位；capture 测试绿。
**等待期可做**：B4 Runbook 正稿。

### 阶段 4（S4）：扩展 + 云日 Runbook（目标 7/17）

**B4.1 锚 #2/#3 工件**：openness（"Openness: intellectually curious and exploratory behavior — willingly considering novel ideas, generating alternatives, questioning assumptions, and engaging with ambiguity rather than defaulting to familiar answers."）与 neuroticism（"Neuroticism: anxious, threat-sensitive behavior — worrying about risks and failure modes, expressing self-doubt and hedging, anticipating negative outcomes, and reacting strongly to setbacks."）——流程同 B3.1。**3B dev 抽取为 stretch**（时间富余才做，各 200 生成）。
**B4.2 云日 Runbook 三份**（`scripts/cloud/`，可执行文档标准：租到卡的人零思考照抄）：
- `cloudday1-official-trait.md`：①provision 检查单（24GB 4090 级、CUDA≥12.1、当日核价并写 costs/ledger.jsonl 行 {ts,provider,instance,rate_cny_h}）；②环境（官方 requirements **全量**含 vllm；`pip install -r requirements.txt`；HF_TOKEN 可留空——已有补丁；7B revision 钉死：下载后读 snapshot sha 更新 configs/models.yaml 的 PIN-AT-CLOUD-PROVISION 并记录）；③**5% smoke**（extract 单指令×2 题跑通 + judge 连通，不过即关机排障）；④五阶段全量（官方命令逐字，optimistic，7B bf16，--judge_model deepseek-chat + OPENAI_BASE_URL 注入；**五阶段 = pos 抽取 / neg 抽取 / generate_vec / baseline eval / steering eval**，以克隆内 scripts/*.sh 顺序为准；另加一步 `python -m eval.cal_projection` 跑通留痕——W2 剂量钳制的官方工具链验证，V0.9 §4 表阶段 5）；⑤对表校准检查单（trait 分随 coef 方向移动、文档化系数区间内 coherence≥50、与官方 README/论文描述的行为方向一致——逐条打勾留数）；⑥翻转 demo 录制（同题 ±coef 并排 + trait 分，60–120 秒屏录）；⑦**parity 烟检**（20 题 temp0：vLLM `sample()` vs transformers `sample_steering(coef=0)` 逐题一致率与分歧样例落 CSV）；⑧产物回传（tar + sha256 → scp 回 Mac `runs/cloud-day1/`）；⑨**完成即关机**断言 + ledger 收笔（实耗 ≤¥150 预算余量检查，超线 = E16 停止）。
- `cloudday2-anchor-traits.md`：前提 = 工件 approved + 云日1 全绿；3 锚 trait 7B bf16 抽取（官方规格 10 响应/题）→ 向量 → 表达检生成素材（同 B3.3 结构，供 C 正式盲评）→ 小系数扫描（2–3 系数 × 1–2 层）→ 激活抽样存储实测 → 回传关机记账，全部标 exploratory。
- `parity-smoke.md`：独立版（若云日 1 时间不够单独执行用），含 `VLLM_BATCH_INVARIANT=1` 对照可选项。
**B4.3** STATUS-B 终态。

---

## 5. 验收总清单（B 完工定义）

1. S1 四重 hook 验证（零注入等价/位移/消融/随机等范数）真实输出留存；fixture 向量工件在案。
2. S2：补丁两枚 + PV-PIN + BRIDGE-FIDELITY（带行号引用）；0.5B e2e 绿；optimistic-dev 三件套（E15 自检过）；方向复现检结论与数据；flip_preview.md。
3. S3：尽责工件（E17 过）+ provenance + REVIEW-REQUEST；conscientiousness-dev 三件套；exprcheck 池/钥匙；capture 测试绿。
4. S4：openness/neuroticism 工件；Runbook×3（含预算五步与 E16 熔断）；STATUS-B 终态。
5. 全程：judge key 零泄露（自查 `grep -RniE "sk-[a-z0-9]" --include="*.py" --include="*.json" --include="*.yaml" /Users/superagent/abcr` 无真值命中；rg 未预装，用 grep）；每 WBS 一 commit；DEVIATIONS 如实。

## 6. 不做清单（B 范围外，勿做）

vLLM 在 Mac 上的任何安装尝试；7B 在 Mac 上的任何加载尝试；LoRA/训练（官方仓 sft/training 部分完全不碰）；评分/复评/出包（C）；runner/题库/split（A）；剂量钳制与 B0 探针（W2）；表达检的**判定**（你只产素材，判定归 C）。

## 7. 缺口处置

未覆盖决策按「官方语义优先、保守复刻、记录一切偏差」三原则就地决定，记 DEVIATIONS.md（`[B] <日期> <决策> <理由>`）。桥与官方语义有歧义处：以克隆内源码为准（BRIDGE-FIDELITY 记录），不猜测。接口冻结区级缺口：STATUS-B 标 `BLOCKED-CONTRACT` 等阶段回归裁决。

## 8. V1.1 补丁接入注记（2026-07-12 append；本文档其余内容不变）

《ABCR-W1执行方案-V1.1补丁-资源治理门与节奏修订》（同目录）已发布：D16/F14 资源契约、错误码 E19/E20/E21、S1.5 资源治理门对本包生效，冲突以补丁为准。B 包最低必守：
1. **重负载全机串行**：`.venv` 与 `.venv-pv` 下任何真模型加载（含 generate_vec 前向、真模型 pytest）必须持有 `/Users/superagent/abcr/.resource/heavy.lock`；`.venv-pv` 命令统一经 `.venv/bin/python -m abcr.resource_guard run -- <cmd>` 包装（协议见补丁 F14.2/§3.2）。
2. **既有实现追认**：你在 B2.6 自建的「分块检查点 + 内存压力门控」被追认为 F14.5 合规实现，**不要求重构**；只对齐三点——锁路径、压力探测源（`sysctl kern.memorystatus_vm_pressure_level`）、阈值语义（warning×2 停 / critical 急停，走 E19 路径）。
3. **加载纪律**（补丁 F14.4）：`from_pretrained` 显式 `torch_dtype`；3B 前设 MPS 上限（min(8GiB, recommended_max)）；每片后 del→gc→`torch.mps.empty_cache()`；low_cpu_mem_usage 在 transformers 4.52.3 为 no-op，不设工作项。
