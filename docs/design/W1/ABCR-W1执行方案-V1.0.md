# ABCR W1 执行方案 V1.0（Mac 全量 · 阶段化回归 · 三工程包并行制）

> 日期：2026-07-11 ｜ 作者：Claude（Fable 5，独立调研 + 设计）
> 定位：执行层文档。上位：《ABCR-W1方案-最小纵向闭环-V0.9》（设计层，本文逐项落地）；《ABCR-实验方案-V1.3》（研究轨唯一操作文档）。
> 范围：启动周末 + W1 的**全部**内容；需要租用 24GB 卡才能完成的部分**不执行、转为云日 Runbook**（可随时纯执行），其余在 Mac mini M4 16GB 上全量完成。
> 分工逻辑：采纳楠 2026-07-11 分工建议（阶段化测试回归 + A/B/C 新切分），五处精化见 §5-D15。执行模型：**Opus 长上下文窗口执行工程包，Fable 只审阶段产物与失败决策包**。
> 自足性：三个工程包文档（同目录）完全自足，执行期间**不需要**再调研 shared-brain 任何文件。
> 调研深度：五份项目文档全文 + shared-brain 四路全域调研（治理/模式/资产/环境）+ persona_vectors 官方仓库代码级核验（钉 commit b8e0f04）。核验状态见 §9。

---

## 0. 一页结论

**W1 唯一目标不变**：一条真实实验链可重复运行——固定输入与模型 → 多臂 → 逐步轨迹与激活摘要落盘 → 自动评分 → 独立复评一致 → 一键产出可复现实验包。

**执行骨架 = 五阶段，阶段内三包并行、阶段间统一回归**（楠建议，采纳）：

- **阶段 0（今日）**：冻结黄金路径与三包契约——config schema、step schema、工件路径、错误码、分阶段验收测试清单（本文 §4 接口冻结区即为冻结动作本身）+ bootstrap。
- **阶段 1（全 fixture/假模型）**：A 打通单步与合成两步轨迹；B 用已知小向量验证零注入等价、残差位移、投影消融、随机等范数方向机制；C 用人工黄金答案验证 parser、评分、manifest 核验、独立重评分。不碰云、不接 judge。**目标：全部工程错误在最低成本环境暴露。**
- **阶段 2（只接一个官方 trait）**：A 接真实 Qwen 推理（0.5B/3B）；B 在 3B 上经 pv_bridge 完整复现官方 optimistic 向量（dev 级，non-citable；7B citable 版 = 云日 Runbook）；C 接 DeepSeek judge 后端并保持盲评。闭环：**官方 trait → steering → 原始输出 → 重评分 → 首个复现包**。方向复现检与 hook 测试未过，不制作自定义人格。
- **阶段 3（一个锚 trait + mini 环）**：B 抽取尽责（conscientiousness）候选方向（dev）；A 跑 vanilla / 人格文本 / 向量注入 / **随机等范数方向** 四臂 × 30 题 × 2 seed；C 确定性评分 + dev 表达检。确认条件隔离、日志完整、复评一致。
- **阶段 4（闭合与扩展）**：全新会话仅凭复现包 verify + rescore（G5 闭合）；全部出口门过后才做扩展——第 2/3 锚 trait 工件与 dev 抽取、n=50 双 judge 一致性、（vLLM parity 仍属云日 Runbook）。

**三包契约的知识边界**（楠建议原文，冻结）：**B 只输出标准化向量工件；A 不理解向量生成过程**（干预对 A 是不透明的 context manager + 规格透传）；**C 只消费原始输出，不参与生成**。

**Mac 全量的含义**：W1 四件交付中 ①rig v0（全字段 schema + 黄金测试）与 ④可复现实验包**完整实过**；②PV 复现与 ③翻转 demo 拆成 Mac dev 部分（工件、judge 替换实测、3B dev 向量、3B 翻转预览，全部 non-citable）+ 云日 Runbook（7B bf16 正式版，纯执行）。出口门 G1/G2/G5/G6/G7 实过，G3/G4 转「就绪态」G3'/G4'（§7）。

**关键环境事实**（已实测）：本机无任何 HF 权重/torch 环境/abcr 仓——从零搭建；`uv`+`python3.11` 可用、PyPI 与 HF 直连；DeepSeek key 在 `~/oc-boss-state/deepseek.key`（0600）；`~/abcr` 不在 Syncthing 同步区、不被任何沙箱/治理机制拦截（前提：独立 code 窗口执行）。

---

## 1. 范围裁定：W1 全项 → Mac 实做 / 云日 Runbook 映射

「排除需要 24GB 卡的部分」的操作定义：凡必须在租用 CUDA 卡上运行才有效的**运行**，一律不跑；其**全部准备工作**（脚本、工件、配置、检查单）在 Mac 做完，使云日成为纯执行。

| W1 V0.9 条目 | 裁定 | 归属（包/阶段） |
|---|---|---|
| repo 骨架 + 全字段 schema + 原子 step 写入 + 幂等续跑 + 账本 | Mac 实做 | A / 阶段0-1 |
| 冻结清单七项（模型 revision/模板/解码/prompt 集/split/引擎/注入位置） | Mac 实做（7B revision 云日 provision 时按流程钉入） | A(1,2,3,6)/A(5 split)/B(7 注入)/B+C(4 工件与题) |
| 黄金测试：hook 检 / 模板检 / 双跑检 / 已知答案检 | Mac 实做（假模型+0.5B CPU float32 canonical；3B MPS fp16 次档） | B(hook)/A(模板/双跑)/C(已知答案) / 阶段1-2 |
| 合成 2-step 轨迹测试（schema 多步就绪证明） | Mac 实做 | A / 阶段1 |
| 评分器独立成 pass + 复评脚本 + manifest 校验器 | Mac 实做 | C / 阶段1-2 |
| split 工具 + 首批任务族 split hash 入 git（W1 只碰 dev） | Mac 实做 | A / 阶段2 |
| 任务族 #1（IFEval 式）题库 | Mac 实做 | A / 阶段2 |
| 官方仓 clone + Mac 干跑阶段 1–2 + DeepSeek judge 调通 | Mac 实做（B 经 pv_bridge；judge D0 实测归 C） | B+C / 阶段2 |
| 官方 trait 复现（W1 版 = 校准的 Mac 可做部分） | Mac 实做 3B dev 复现 + 方向复现检 | B / 阶段2 |
| 三/四臂 mini 环（rig 验证，非证据） | Mac 实做（3B fp16 MPS，30 题×2 seed×4 臂，non-citable） | A 执行 / 阶段3 |
| 激活抽样存储（分层均值 + 10% 投影标量） | Mac 实做 | B(采集库)+A(落盘) / 阶段2-3 |
| 3 锚 trait 工件（Claude 产、人工过目、版本化） | Mac 实做（#1 阶段3；#2/#3 阶段4） | B |
| judge 替换偏差 n=50 双 judge 一致性 | **Mac 实做**（官方仓自带 7B baseline CSV 作打分样本） | C / 阶段4 |
| 可复现实验包 + `make repro-pack` + 新会话闭合验收 | Mac 实做（阶段2 首包、阶段4 终包+闭合） | C 工具 / 阶段2、4 |
| 官方 trait 五阶段 7B bf16 完整复现 + 对表校准 | **排除 → 云日 #1 Runbook** | B / 阶段4 交付 Runbook |
| steering 翻转 demo（7B 正式版） | **排除 → 云日 #1 Runbook**；Mac 出 3B 预览（non-citable，家庭可见进展可用） | B / 阶段2 预览、Runbook |
| 3 锚 trait 正式抽取 + 表达检 + 系数扫描（bf16） | **排除 → 云日 #2 Runbook** | B / 阶段4 交付 Runbook |
| 20 题双引擎 parity 烟检 | **排除 → 云日 Runbook**（vLLM 需 CUDA；Mac CPU 版无外推价值） | B / 阶段4 交付 Runbook |
| 官方阶段 5 投影计算（eval.cal_projection 跑通） | **排除 → 云日 #1 Runbook 显式列项**（Mac 侧 capture.py 为自研投影，不替代官方工具链验证） | B / 阶段4 交付 Runbook |
| boss_console/界面/Operator 常驻/Governor | 本就不做（W1 = 自动化设计 Phase 0） | — |

**不做清单照单全收**（W1 V0.9 §1），另加两条本执行方案的不做：不为三包并行搭任何编排/监控设施（三窗人工开，包文档即全部指令）；阶段 4 之前不做任何扩展项（第 2/3 trait、双 judge、parity——楠阶段律）。

---

## 2. 环境与治理事实（调研结论，包执行者不必再查证）

### 2.1 硬件与系统
- Mac mini M4（Mac16,10），16GB 统一内存，macOS 26.4.1，根盘可用 122Gi。
- 档位约束：3B fp16 ≈ 6.2GB 权重，MPS 流畅；**7B fp16 ≈ 15GB 本机不可跑**（7B 全归云日）；0.5B 供快速集成检（CPU float32 可跑）；阶段 1 用本地随机权重微型模型（无网络依赖、秒级前向）。

### 2.2 软件与网络（2026-07-11 实测）
- `/opt/homebrew/bin/python3.11` = 3.11.15；`uv` 0.11.3；Xcode CLT 已装；git/make/brew 可用。**系统默认 python3=3.14，不要用**。
- 本机**无** torch/transformers/HF 缓存/HF token/safetensors 权重；ollama 的 qwen3:8b GGUF 对 hook 实验无用，忽略。
- PyPI 直连 200；huggingface.co 主站 200（`/api/` 路径被网络中间层挡，但 `snapshot_download` 走 CDN 不受影响；revision 钉死流程已按「下载后读 snapshots 目录名」设计，不依赖 API）；api.deepseek.com 存活（匿名 401 属预期）。无代理、无镜像配置。
- **DeepSeek key**：`/Users/superagent/oc-boss-state/deepseek.key`（0600、35 字节、非空）。用法纪律见 §4-F8。
- **claude CLI**：zsh 的 `claude` 是函数（经 AILH 画像 launcher）；无头调用一律 **`CLAUDE_RAW=1 ~/.local/bin/claude -p ...`**（真 binary v2.1.207，订阅通道）。ANTHROPIC_API_KEY 未设且按治理**不得**设置。
- git 全局无 user.name/email——abcr 仓需本地级 `git config`。

### 2.3 治理约束（已逐条核对沙箱/hook/监督系统源码）
1. **~/abcr 不被拦截**：Seatbelt 只包 AILH tool 子进程（写白名单仅 shared-brain）；红线 hook 仅武装过 `/boss` 的会话生效；SessionEnd 自动 commit 仅作用 V2 仓；BOSS/监工/watchdog 事实源不覆盖 ~/abcr。**前提：三包必须走独立 Claude Code 窗口（code 任务），绝不可作为 AILH 任务派发**（AILH tool 层对 ~/abcr 写必 EPERM）。
2. abcr 窗口内**不跑 `/boss`**；仓内路径**规避子串** `"/persona/"`、`"v_core"`、`"judgment_engine"`（红线词表，误伤保险）——用 `traits/`、`pv_bridge/` 命名。
3. git 纪律：本地 `git init`、不设远端、**永不 push**（楠 2026-06-10 决策 + N5 先例）。
4. SessionStart hook 会向每个新会话注入工程进展史当前阶段——纯上下文开销，无害，忽略。
5. ~/abcr 不在 Syncthing 四个同步文件夹内，无同步冲突风险。

### 2.4 persona_vectors 官方仓库（代码级核验，钉 commit `b8e0f044fe2410a6fad579f38324f03f13b4e917`，2026-04-22）
- **依赖边界**：requirements 含 `vllm==0.8.5.post1`、`bitsandbytes`、`unsloth`（CUDA 系，Mac 不可装）；`torch==2.6.0`、`transformers==4.52.3`、`openai==1.70.0`（Mac 可装）。
- **`eval/eval_persona.py` 顶层 `from vllm import LLM`** → Mac 不可 import；其 steering 路径 `sample_steering()` 是纯 transformers + `ActivationSteerer`（**层约定：用户层号 L → `model.layers[L-1]`，等价 `hidden_states[L]`**；positions="response"）。
- **`generate_vec.py` 纯 transformers**（Mac 可跑）：输入 pos/neg 两个 CSV（列 `prompt`=已渲染模板全文、`answer`、`<trait>` 分、`coherence`），过滤 `pos[trait]>=50 & neg[trait]<100-50 & coherence>=50（双侧）`；输出 `{trait}_{prompt_avg|response_avg|prompt_last}_diff.pt`，shape=(层数+1, hidden)。其 `from_pretrained` **未传 dtype（默认 fp32）**——3B fp32=12GB、7B fp32=28GB，Mac 与 24GB 卡都需 dtype 补丁。
- **`judge.py`**：`AsyncOpenAI()`（读 `OPENAI_API_KEY`/`OPENAI_BASE_URL` 环境变量），0-100 打分 = max_tokens 1 + `logprobs=True, top_logprobs=20` 概率加权；另有 `binary_text` 全文解析档。`config.py` 强制 `OPENAI_API_KEY` **和** `HF_TOKEN` 双双非空否则 raise（HF_TOKEN 需「可选化」补丁）。
- **trait 工件格式**：`data_generation/trait_data_extract|eval/<trait>.json` = `{"instruction":[5×{pos,neg}], "questions":[20], "eval_prompt":"...REFUSAL 或 0-100 数字..."}`；新 trait 生成 prompt = `data_generation/prompts.py::PROMPTS["generate_trait"]`（一次产 40 题，拆 20 抽取+20 评测）。
- **官方 CLI 权威用法**（云日 Runbook 逐字采用）：`python -m eval.eval_persona --model <M> --trait <t> --version extract|eval [--persona_instruction_type pos|neg --assistant_name <n>] [--steering_type response --coef <c> --vector_path <p> --layer <L>] --judge_model <j> --output_path <csv>`；`python generate_vec.py --model_name <M> --pos_path <csv> --neg_path <csv> --trait <t> --save_dir <d> --threshold 50`。
- 官方自带 `output/qwen2.5-7b-instruct_baseline.csv`（7B 基线响应）——**n=50 双 judge 一致性抽样的现成样本，Mac 即可完成**。

### 2.5 既有资产裁定
- shared-brain 全域搜索确认：**无任何激活工程/steering/hook 既有实现、无 HF 权重落盘**——机制层从零，符合预期。
- 谱系资产（不进工程包，登记于 §9）：L0-raw 两份前身设计对话（0706/0707）、V2 标定套件、v_core/v_mutable spec、「2.65→3.15 / 11.5%」先验证据指针。
- trace_writer 哈希链、原子写、fail 方向纪律等 V2 工程模式**已提炼成规格内嵌包文档**，执行者无须回看 V2 源码。

---

## 3. 总体架构：三包契约 + 五阶段回归

```
包 A：Runner + Episode + Ledger          包 B：Hook + Intervention + PV 复现        包 C：Scorer + Audit + Repro Pack
  bootstrap（三包同脚本，互斥锁）           interventions 库（冻结 API，A 盲用）        checker registry + 单测
  schema/writer（哈希链+fsync+幂等）        hook 三验证:零注入等价/位移/随机等范数        已知答案黄金检（人工核定 10 题）
  preflight/config→run_id/repair          third_party 钉 commit + 补丁 + .venv-pv    score 独立 pass（只读 runs/）
  runner（干预=不透明 context manager）     pv_bridge（transformers 生成桥）           review 复评 + manifest/链校验
  合成 2-step + 模板钉死 + 双跑检           optimistic 3B dev 复现 + 方向复现检         judge 后端（DeepSeek 盲评）+ D0 实测
  IFEval 题库 + split 工具 + hash 入 git    锚 trait 工件（claude CLI + 过目单）        repro_pack + 闭合验收协议
  mini 环执行（阶段3）                      3B 翻转预览 + dev 表达检素材                n=50 双 judge 一致性（阶段4）
  costs/ledger.jsonl                       激活采集库 + 云日 Runbook×3                主图脚本
        └───────────────┬───────────────────────┴────────────────┬─────────────────┘
                        ▼                                        ▼
        知识边界（冻结）：B 只输出标准化向量工件；A 不理解向量生成过程；C 只消费原始输出、不参与生成
                        ▼
   阶段门（统一回归）：S1 全 fixture 契约回归 → S2 官方 trait 闭环（首包）→ S3 mini 环复评一致 → S4 全新会话闭合 + 扩展
```

**阶段间回归协议**：每包完成阶段 N 后在 `STATUS-<包>.md` 记录终态；三包齐后任一窗口执行 `make stage<N>-regression`（跑 `tests/contract/stage<N>/` 全部三包契约测试）；**回归输出与各包 STATUS 交 Fable 审**（楠执行模型），绿灯才进阶段 N+1。失败 → 责任包修复 → 重跑回归。阶段内三包完全并行、互不等待；跨包消费只认冻结路径落位文件，缺位走各包文档内的后备（fixture/stub），**不跨窗口沟通**。

---

## 4. 接口冻结区 v1（权威副本；三包文档内各有逐字副本，冲突以本文为准）

### F1 仓库与身份
- 路径 `/Users/superagent/abcr`；本地 git（`git init -b main`；`git config user.name "Yinan Wang"`；`git config user.email worldofnan130@gmail.com`），无远端、永不 push。
- 提交前缀 `[A]`/`[B]`/`[C]`/`[REG]`（回归）。并行提交遇 `index.lock`：等 2s 重试 ≤5 次，仍失败响亮报错。
- 三包文件所有权互斥（F7）；`mkdir -p` 不算冲突；`DEVIATIONS.md` 与 `STATUS-*.md` 为共用 append 文件（各写各段，带包名前缀）。

### F2 环境
- 实验主 venv `/Users/superagent/abcr/.venv`（`uv venv --python /opt/homebrew/bin/python3.11`）。依赖（对齐官方仓可对齐项）：`torch==2.6.0, transformers==4.52.3, accelerate==1.7.0, datasets==3.6.0, pandas==2.3.1, pyarrow, duckdb, scipy, statsmodels, matplotlib, typer, pydantic==2.11.7, pyyaml==6.0.2, pytest, openai==1.70.0, backoff==2.2.1, tqdm, huggingface_hub`。若 torch==2.6.0 在 macOS arm64 装不上：放宽 `torch>=2.6,<2.8`，实际版本入 env lock + DEVIATIONS。
- 包 B 另建 `.venv-pv`（third_party 专用 Mac 子集：官方 requirements 去掉 `vllm/bitsandbytes/unsloth/trl`，加装说明见包 B）。
- 模型匿名 `snapshot_download`（Qwen2.5 系不 gated）：`Qwen/Qwen2.5-0.5B-Instruct`、`Qwen/Qwen2.5-3B-Instruct`。**revision 钉死**：下载后读 `~/.cache/huggingface/hub/models--*/snapshots/<sha>` 目录名写入 `configs/models.yaml` 并 commit；此后一切加载显式传 `revision=`。7B 条目占位 `revision: PIN-AT-CLOUD-PROVISION`。
- 阶段 1 假模型：本地构造 `Qwen2Config(hidden_size=64, num_hidden_layers=4, num_attention_heads=4, num_key_value_heads=2, intermediate_size=128, vocab_size=从 0.5B tokenizer, max_position_embeddings=512)` 随机初始化（seed 0）+ 0.5B 的 tokenizer/chat template，存 `tests/fixtures/tinyqwen/`（bootstrap 生成，CPU float32，秒级前向、确定性最强）。
- **tinyqwen 的冻结钉死**（使 E02/E03 在 S1 可按文字执行）：bootstrap 在 configs/models.yaml 追加条目 `tinyqwen: {model_id: tests/fixtures/tinyqwen, revision: "local-fixture-seed0"}`，并把 0.5B 的模板 hash 与 3 样例复制为 `configs/templates/tinyqwen/`（tokenizer 同源）；tinyqwen 的 step 记 model_id="tinyqwen"、model_revision="local-fixture-seed0"。models.yaml 合法 key 集 = {tinyqwen, qwen2.5-0.5b-instruct, qwen2.5-3b-instruct, qwen2.5-7b-instruct}。

### F3 目录布局（骨架 bootstrap 一次建全，未用目录空建占位防漂移）
```
abcr/
├── CLAUDE.md  README.md  Makefile  pyproject.toml  .gitignore  DEVIATIONS.md  STATUS-A/B/C.md
├── configs/{models.yaml, templates/, runs/}
├── src/abcr/{__init__.py, models.py, run.py, splits.py, score.py, review.py, repro_pack.py,
│            interventions/{__init__.py, api.py, prompt_persona.py, residual_vector.py, projection_ablation.py, random_direction.py, capture.py},
│            eval/{__init__.py, deterministic/{__init__.py, checkers.py, registry.py}, judge/{__init__.py, client.py, blind.py, probe.py}},
│            logging/{__init__.py, schema.py, writer.py, manifest.py, errors.py}}
├── data/{items/ifeval_style/items.jsonl, splits/}
├── artifacts/traits/<trait>/{extract.json, eval.json, provenance.json}
├── vectors/<model-slug>/<trait>-dev/{response_avg_diff.pt, card.json, extraction_meta.json}
├── runs/<run_id>/{config.yaml, manifest.json, steps.jsonl, activations/}
├── scores/<run_id>/{scores.jsonl, summary.json}      ├── review/<run_id>/review_report.json
├── repro_packs/<runset>/                              ├── figures/
├── third_party/persona_vectors/     # 钉 commit 克隆；.gitignore 排除；改动只经 patches/
├── patches/{pv-config-hftoken-optional.patch, pv-generate-vec-dtype.patch}
├── pv_bridge/{extract_mac.py, flip_preview.py, exprcheck_gen.py, BRIDGE-FIDELITY.md, out/}
├── scripts/{bootstrap.sh, cloud/{cloudday1-official-trait.md, cloudday2-anchor-traits.md, parity-smoke.md}}
├── costs/ledger.jsonl
└── tests/{fixtures/, unit/, contract/stage1/, contract/stage2/, contract/stage3/, contract/stage4/}
```
`.gitignore`：`.venv*/ third_party/ __pycache__/ .bootstrap.lock .pytest_cache/ *.pyc tests/fixtures/tinyqwen/ pv_bridge/out/`（tinyqwen 由 bootstrap 确定性再生；pv_bridge/out 的应留证子集由 C 出包时按清单复制）。runs/scores/vectors/figures **入 git**（W1 体量小，工件级可追溯优先）。

### F4 steps.jsonl schema（w1.1，冻结）
一行 = 一 step（单轮 = 长度 1 的 trajectory）。字段 = 交接文档 §6.2 基底 + V1.3 §11 扩展 + W1 V0.9 §3 补充 + 本方案四新增（schema_version / device_backend / citable / 链字段，理由 D3/D10）。

| 组 | 字段（类型；null 约定） |
|---|---|
| 元 | schema_version="w1.1", run_id, trajectory_id, step_id(int), parent_run(null 允许) |
| 溯源 | git_commit, config_hash, protocol_ref, env_lock_ref |
| 模型 | model_id, model_revision, dtype, quantization(null), device, device_backend(mps/cuda/cpu), engine="transformers", engine_version, torch_version, cuda_version(Mac=null), chat_template_hash |
| 数据 | benchmark(=任务族), split_hash, item_id |
| 条件 | condition(vanilla/prompt_persona/residual_vector/random_direction), trait(null), trait_pole(pos/neg/null), method(none/prompt_persona/residual_vector/projection_ablation/random_direction), layer(null), coefficient(null), intervention_strength(null) |
| 轨迹 | env_seed(null), action(null), obs_hash(null), remaining_budget(null), stop_reason, state_snapshot_ref(null) |
| 解码 | random_seed(int)（temperature/max_new_tokens 在 run config，经 config_hash 溯源） |
| IO | prompt_hash, output_text, parsed_answer(生成时 null), is_correct(生成时 null，**评分永不回写本文件**), latency_ms, input_tokens, output_tokens |
| 评 | trait_score(null), fluency_score(null), safety_flags([]) |
| 激活 | activation_summary(null 或 {path, layer, proj_mean, proj_p50, proj_p90}) |
| 标记 | citable(bool；Mac 恒 false) |
| 链 | prev_hash, entry_hash（F5） |

### F5 写入语义（trace_writer 模式 + fsync 强化）与单实现裁定
- append-only JSONL；每行：组装 → `prev_hash`=链尾（首条 "0"×64）→ `entry_hash`=sha256(canonical_json(含 prev_hash、不含 entry_hash；sort_keys；ensure_ascii=False) + prev_hash) → open('a') 写行 → flush + os.fsync。
- 幂等续跑：启动读已有 steps.jsonl 构建完成集 {(item_id, random_seed, condition, step_id)} 跳过；尾部半行（崩溃残留）→ **拒跑**（E07）并提示 `python -m abcr.run --repair <run_id>`：原文件改名 `steps.jsonl.crashed-<ts>` 永久归档，有效前缀重写新文件，manifest 记 repair 事件。
- **单实现裁定**（防三包各写一份算法互相打架）：①`verify_chain`（链完整返回 True，断链 raise AbcrError(E08)）单实现于 `abcr.logging.writer`，C 的 review import 调用（catch 转 chain_ok=false）；②`canonical_json` 单实现于 `abcr.logging.schema`；③**config_hash = sha256(canonical_json(config dict))**，与 manifest 必填字段集/生成/校验算法一并单实现于 `abcr.logging.manifest`（A 所有），C 的 review import 调用重算，不自写第二份。同源 bug 风险由 C 的已知答案黄金检对冲（checker 双实现推迟 W2）。
- 铁律：不得只存汇总分；评分产物独立于 runs/（F6）。

### F6 scores / review / 向量工件 / 判定工件
- `scores/<run_id>/scores.jsonl` 行：{run_id, trajectory_id, step_id, item_id, condition, random_seed, scorer_version, checks:[{name, pass, detail}], is_correct(bool), score(float 0-1)}；join 键 (run_id, trajectory_id, step_id)。`summary.json`：逐臂×seed 聚合 + 输出长度统计。
- `review/<run_id>/review_report.json`：{n_steps, n_expected, missing[], duplicated[], chain_ok, score_mismatches[], manifest_checks{}, error_codes[], pass(bool)}。复评 = 独立进程从 steps.jsonl 重算全部确定性分逐条 diff；judge 类分数复评 = 从**已落盘的 judge 原始输出**重算聚合（不重调 API）。
- **标准化向量工件**（B 的唯一输出形态，A/C 视 .pt 为不透明二进制）：`vectors/<model-slug>/<trait>-<grade>/`（grade=dev|citable）三件套——`response_avg_diff.pt`（torch float32，shape=(层数+1, hidden)）；`card.json`{trait, model_id, model_revision, source_commit(pv 仓), extraction_date, grade, judge_model, judge_lineage, recommended{layer, coef}, n_pos_effective, n_neg_effective, pt_sha256, notes}；`extraction_meta.json`（过滤阈值、语料 hash、逐文件 sha256）。
- judge 判定工件（逐样本原始返回：logprob 字典或全文 + 解析分，聚合必须可重算）三个落位：B 的 bridge 侧 → `pv_bridge/out/**/*.judge_raw.jsonl`；C 的盲评/双 judge 侧 → `review/judge_raw/<name>.jsonl`；`runs/<run_id>/judge_raw.jsonl` 保留给 W2+ 的 run 内 judge（W1 不产生，C 对 runs/ 恒零写入）。
- **items.jsonl 行 schema（冻结，A 产 C 消费）**：`{item_id: sha256(prompt)[:16], family, prompt, checks: [{name: <CT-1 内部名>, kwargs: {...}}], source, source_key}`；is_correct = 全部 checks pass，score = 通过比例。
- **向量工件文件名规则**：官方 generate_vec 产 `{trait}_{prompt_avg|response_avg|prompt_last}_diff.pt` 三份；标准化工件只取 response_avg 一份、内容逐字节不动、重命名为 `response_avg_diff.pt`；另两份留 `pv_bridge/out/`。

### F7 所有权矩阵
| 路径 | 所有者 |
|---|---|
| scripts/bootstrap.sh、pyproject.toml、CLAUDE.md、README.md、Makefile、configs/、src/abcr/{models,run,splits}.py、logging/、interventions/api.py（仅接口定义文件）、data/、runs/（数据）、costs/、tests/fixtures/（golden_answers、vector_tiny 除外）、tests/contract/*/test_a_*.py、tests/unit/test_a_*.py、src/abcr/ 及其子包全部 __init__.py、src/abcr/build_items.py | A |
| src/abcr/interventions/{prompt_persona,residual_vector,projection_ablation,random_direction,capture}.py、third_party/、patches/、pv_bridge/、artifacts/traits/、vectors/、scripts/cloud/、tests/fixtures/vector_tiny/、tests/contract/*/test_b_*.py、tests/unit/test_b_*.py | B |
| src/abcr/{score,review,repro_pack}.py、eval/、scores/ review/ repro_packs/ figures/（数据与脚本）、tests/contract/*/test_c_*.py、tests/unit/test_c_*.py、tests/fixtures/golden_answers/ | C |
- bootstrap.sh 三包文档逐字相同：谁先启动谁执行（`mkdir /Users/superagent/abcr/.bootstrap.lock` 原子互斥；后到者轮询 `.bootstrap.done`，上限 30 分钟）；写文件一律「不存在才写」。
- `interventions/api.py`（A 所有，阶段 0 冻结后不改）：`get_intervention(spec, model_key) -> Intervention`（协议含 spec/system_text/context()/describe()/activation_summary()；spec 直通入 step 条件组字段）。补充语义：runner 需激活抽样时于生成前设 `iv.capture_path=<npz 路径>`，生成后取 `iv.activation_summary()`；实现细节 B 负责，A 对内容保持无知（协议全文以包 A/B 文档一致副本为准）。

### F8 密钥与 judge 纪律
- DeepSeek key 只在进程环境注入：`export OPENAI_API_KEY=$(cat /Users/superagent/oc-boss-state/deepseek.key)`、`export OPENAI_BASE_URL=https://api.deepseek.com`、模型名 `deepseek-chat`。**key 不写入任何文件/git/日志/报错回显；禁止创建 .env**。
- trait 表达类打分 judge 必须盲评：输入只含 {sample_id, question, answer}（sample_id 为非语义 join 键、不属泄盲字段；官方 eval_prompt 模板本身无条件标签）；样本顺序随机且记录置换 seed。**豁免**：抽取过滤（数据清洗）与 B 的方向检/预览/recommended 标定（向量生产内部 QA）允许非盲，产物仍记 judge 谱系、不作科学证据。
- 谱系：一切 judge 产物记 `judge_model=deepseek-chat, judge_lineage=replaced(official gpt-4.1-mini-2025-04-14)`。

### F9 呈现与运行纪律（写入 abcr/CLAUDE.md）
- Mac 一切运行 `citable=false`；只碰 dev split；对外数字必带 exploratory / rig-validation / non-citable 标注。
- 不跑 `/boss`；不 push；路径避 `"/persona/"`、`"v_core"`、`"judgment_engine"` 子串。
- fail 方向纪律：安全/校验组件 fail-closed（preflight 不符拒跑、校验失败即不过）；旁路信号（图/通知）best-effort 不阻塞主链。
- 云预算常量 ¥150（W1）；costs/ledger.jsonl 从阶段 0 建账（本周应恒 ¥0 支出）。

### F10 错误码（冻结；`src/abcr/logging/errors.py`，CLI 非零退出并打印码）
| 码 | 含义 | fail 方向 |
|---|---|---|
| E01_PREFLIGHT_GIT_DIRTY | git 不 clean 且未带 --dev | closed（拒跑；--dev 放行并打 non-citable） |
| E02_REVISION_MISMATCH | 模型 revision 与 configs/models.yaml 不符 | closed |
| E03_TEMPLATE_HASH_MISMATCH | chat template hash 与钉死值不符 | closed |
| E04_SPLIT_HASH_MISMATCH | split 文件 hash 与 config 声明不符 | closed |
| E05_CONFIG_INVALID | run config 未过 schema 校验 | closed |
| E06_ARM_PURITY_VIOLATION | 臂纯度断言失败。**禁键集合（冻结）**：method∈{prompt_persona, none} 的 spec 禁含 {vector_dir, vector_path, match_to, direction_seed, target_norm}；method∈{residual_vector, random_direction, none} 的 spec 禁含 {artifact, instruction_index}。manifest 相应字段名 has_vector_ref / has_persona_ref | closed |
| E07_STEPS_TAIL_CORRUPT | steps.jsonl 尾部半行 | closed（指路 --repair） |
| E08_CHAIN_BROKEN | 哈希链校验失败 | closed（review 判 fail） |
| E09_RESUME_CONFLICT | 续跑发现 (item,seed,condition,step) 重复 | closed |
| E10_SCORE_JOIN_INCOMPLETE | scores 与 steps join 有缺漏 | closed |
| E11_SCORE_MISMATCH | 复评与 scores 不一致 | closed |
| E12_MANIFEST_INCOMPLETE | manifest 必填项缺失/哈希对不上 | closed |
| E13_JUDGE_UNAVAILABLE | judge 端点不可用 | closed（该批标 blocked，不静默跳过） |
| E14_JUDGE_PARSE_FAIL | judge 返回不可解析 | 按样本记 REFUSAL/parse_fail，率超 10% 整批 fail |
| E15_VECTOR_ARTIFACT_INVALID | 向量工件三件套不齐/shape 或 sha 不符 | closed |
| E16_BUDGET_EXCEEDED | ledger 超 ¥150 | closed（冻结新云动作） |
| E17_DISJOINTNESS_VIOLATION | 抽取语料 ∩ 评测题 ≠ ∅ | closed |
| E18_GOLDEN_FAIL | 任一黄金/契约测试失败 | closed（阶段门不放行） |

### F11 分阶段验收测试清单（冻结；`tests/contract/stage<N>/`，`make stage<N>-regression` 全绿为阶段门）
**阶段门操作协议**：三包 STATUS 均报阶段 N 完成后，由**最后完成的窗口**执行 `make stage<N>-regression`；全绿则提交 `[REG] stage<N> PASS`（失败则 `[REG] stage<N> FAIL <摘要>`，责任包修复后重跑）。各包放行信号 = git log 出现该 PASS 提交；回归输出与 STATUS 交 Fable 审后进入阶段 N+1。
- **S1**（全 fixture，tinyqwen，CPU float32，不接网/不接 judge）：test_a_writer_chain（写入-链校验-幂等续跑-崩溃尾修复）；test_a_traj2step（合成 2-step 写读重放）；test_a_preflight（E01-E06 逐码触发）；test_b_zero_injection（coef=0 与无 hook 输出逐字节等价）；test_b_displacement（残差位移 ≈ c·v，float32 容差 1e-5）；test_b_ablation（投影后 ≈ 0）；test_b_random_norm（随机方向等范数断言 + 与 v 正交性统计）；test_c_parser_scorer（黄金答案 ≥12 例精确命中）；test_c_manifest_review（E08+E10-E12 逐码触发 + 复评零差异）。
- **S2**（真模型 + judge）：test_a_qwen_smoke（0.5B 与 3B 各 2 题生成落盘全字段）；test_a_template_pin（渲染与钉死样例逐字节一致）；test_a_doublerun（3B temp0 双跑逐字节一致；MPS 失败则 CPU 档判定并记 DEVIATIONS）；test_b_pv_e2e_05b（bridge 0.5B 端到端：生成→judge→CSV→generate_vec 出 .pt）；test_b_direction_3b（optimistic 3B dev 向量 steering ±coef 使 judge trait 分单调移动——方向复现检）；test_c_judge_blind（D0 实测结论 + 盲评协议断言：输入无条件字段、顺序已置换）；test_c_first_pack（阶段 2 闭环包 verify+rescore 通过）。
- **S3**：test_a_mini_loop_coverage（4 臂×30 题×2 seed 覆盖无缺重 + 向量/随机臂中 activation_summary 非空 step 数与确定性抽样命中集精确一致——10% 抽样率的覆盖断言归 A）；test_a_arm_purity（E06 双向断言）；test_b_capture（capture_path 设定时产出合法 npz 与摘要字段——抽样率由 A 的 runner 决定，B 只管被选中 step 的逐 token 全记）；test_c_review_full（mini 环复评一致 + 链校验 + manifest 全绿）。
- **S4**：闭合验收（全新会话仅凭包 verify+rescore，人工执行按 C 的协议文档）；test_c_dual_judge_n50（一致性数据在案）；扩展项各自验收（见各包阶段 4 节）。

### F12 checker 契约 CT-1（权威版；包 A/C 文档各有逐字副本；A 按此过滤题库、C 按此实现 checker）
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
多约束题：is_correct = 全部 checks pass；score = 通过比例。词/句切分规则由 C 在 checkers.py 顶部注释写死（词=`\S+`；句=按 [.!?] 含引号右括号收尾切分），A 不依赖该细节。

### F13 bootstrap 脚本（权威全文；包 A §4-A0.1 有逐字副本；B/C 首启时按本文全文写入 `scripts/bootstrap.sh` 并执行——先到先跑、互斥锁防双跑）
```bash
#!/bin/bash
set -euo pipefail
ROOT=/Users/superagent/abcr
mkdir -p "$ROOT"; cd "$ROOT"
[ -f .bootstrap.done ] && { echo "bootstrap done"; exit 0; }
if ! mkdir .bootstrap.lock 2>/dev/null; then
  echo "另一窗口正在 bootstrap，等待（上限30分钟）..."
  for i in $(seq 1 360); do [ -f .bootstrap.done ] && exit 0; sleep 5; done
  echo "E: bootstrap 等待超时"; exit 1
fi
trap 'rmdir "$ROOT/.bootstrap.lock" 2>/dev/null || true' EXIT
[ -d .git ] || git init -b main
git config user.name "Yinan Wang"; git config user.email worldofnan130@gmail.com
mkdir -p configs/templates configs/runs data/items/ifeval_style data/splits artifacts/traits \
  vectors runs scores review repro_packs third_party patches pv_bridge/out scripts/cloud costs figures \
  src/abcr/interventions src/abcr/eval/deterministic src/abcr/eval/judge src/abcr/logging \
  tests/fixtures/golden_answers tests/unit tests/contract/stage1 tests/contract/stage2 tests/contract/stage3 tests/contract/stage4
for f in src/abcr/__init__.py src/abcr/interventions/__init__.py src/abcr/eval/__init__.py \
  src/abcr/eval/deterministic/__init__.py src/abcr/eval/judge/__init__.py src/abcr/logging/__init__.py; do
  [ -f "$f" ] || touch "$f"; done
for f in DEVIATIONS.md STATUS-A.md STATUS-B.md STATUS-C.md costs/ledger.jsonl; do [ -f "$f" ] || touch "$f"; done
[ -f .gitignore ] || cat > .gitignore <<'EOF'
.venv*/
third_party/
__pycache__/
.bootstrap.lock
.pytest_cache/
*.pyc
tests/fixtures/tinyqwen/
pv_bridge/out/
EOF
[ -d .venv ] || uv venv --python /opt/homebrew/bin/python3.11 .venv
uv pip install -p .venv/bin/python torch==2.6.0 transformers==4.52.3 accelerate==1.7.0 datasets==3.6.0 \
  pandas==2.3.1 pyarrow duckdb scipy statsmodels matplotlib typer pydantic==2.11.7 pyyaml==6.0.2 \
  pytest openai==1.70.0 backoff==2.2.1 tqdm huggingface_hub \
  || { echo "torch==2.6.0 失败则手动放宽 torch>=2.6,<2.8 重装并记 DEVIATIONS.md"; exit 1; }
.venv/bin/python - <<'PY'
import pathlib, hashlib, shutil, yaml, torch
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer, Qwen2Config, Qwen2ForCausalLM
pins = {}
for mid in ["Qwen/Qwen2.5-0.5B-Instruct", "Qwen/Qwen2.5-3B-Instruct"]:
    p = snapshot_download(mid); pins[mid] = pathlib.Path(p).name; print(mid, "->", pins[mid])
my = pathlib.Path("configs/models.yaml")
if not my.exists():
    my.write_text(yaml.safe_dump({"models": {
        "tinyqwen":              {"model_id": "tests/fixtures/tinyqwen",      "revision": "local-fixture-seed0"},
        "qwen2.5-0.5b-instruct": {"model_id": "Qwen/Qwen2.5-0.5B-Instruct", "revision": pins["Qwen/Qwen2.5-0.5B-Instruct"]},
        "qwen2.5-3b-instruct":   {"model_id": "Qwen/Qwen2.5-3B-Instruct",   "revision": pins["Qwen/Qwen2.5-3B-Instruct"]},
        "qwen2.5-7b-instruct":   {"model_id": "Qwen/Qwen2.5-7B-Instruct",   "revision": "PIN-AT-CLOUD-PROVISION"},
    }}, allow_unicode=True, sort_keys=False))
for key, mid in [("qwen2.5-0.5b-instruct","Qwen/Qwen2.5-0.5B-Instruct"),("qwen2.5-3b-instruct","Qwen/Qwen2.5-3B-Instruct")]:
    tok = AutoTokenizer.from_pretrained(mid, revision=pins[mid])
    tpl = tok.chat_template or ""
    h = hashlib.sha256(tpl.encode()).hexdigest()
    d = pathlib.Path(f"configs/templates/{key}"); d.mkdir(parents=True, exist_ok=True)
    (d/"chat_template.hash").exists() or (d/"chat_template.hash").write_text(h)
    samples = [
        [{"role":"user","content":"Hello, what is 2+2?"}],
        [{"role":"system","content":"You are a careful assistant."},{"role":"user","content":"List three fruits."}],
        [{"role":"system","content":"Respond optimistically."},{"role":"user","content":"How is the weather?"}],
    ]
    for i, msgs in enumerate(samples):
        f = d/f"sample_{i}.txt"
        f.exists() or f.write_text(tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True))
dst_t = pathlib.Path("configs/templates/tinyqwen")
if not dst_t.exists(): shutil.copytree("configs/templates/qwen2.5-0.5b-instruct", dst_t)
tq = pathlib.Path("tests/fixtures/tinyqwen")
if not (tq/"config.json").exists():
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-0.5B-Instruct", revision=pins["Qwen/Qwen2.5-0.5B-Instruct"])
    torch.manual_seed(0)
    cfg = Qwen2Config(hidden_size=64, num_hidden_layers=4, num_attention_heads=4, num_key_value_heads=2,
                      intermediate_size=128, vocab_size=len(tok), max_position_embeddings=512)
    m = Qwen2ForCausalLM(cfg); m = m.to(torch.float32)
    m.save_pretrained(tq); tok.save_pretrained(tq)
print("bootstrap python 段完成")
PY
touch .bootstrap.done
git add -A && git commit -m "[bootstrap] repo skeleton + env + model pins + template pins + tinyqwen" || true
echo "bootstrap 完成"
```

---

## 5. 嵌入决策清单（可否决，未否决即按此执行）

- **D1 执行形态**：三独立 Claude Code 窗口并行执行包 A/B/C（建议 Opus 长上下文执行——楠执行模型）；**禁止**作为 AILH 任务派发（Seatbelt 白名单不含 ~/abcr）。阶段产物与失败决策包交 Fable 审。
- **D2 仓库**：`/Users/superagent/abcr` 本地 git、无远端、永不 push；不在 Syncthing 同步区（已核实）。
- **D3 Mac 引擎档位**：transformers + MPS + float16（3B）为 Mac 主档；tinyqwen（CPU float32）为阶段 1 契约档；0.5B CPU/MPS 为集成档。上位文档「Mac 4bit」在 transformers+hook 路线不可实现（bitsandbytes 仅 CUDA），以本条代之；Mac 产物本就 non-citable，档位替换不改变证据性质。schema 增 `device_backend`、`cuda_version` 可 null。
- **D4 parity 烟检移云日**：vLLM 无实用 macOS 支持；W1 交付 Runbook + 20 题固定清单（云日随行，约 10 分钟）。
- **D5 官方管线 Mac 干跑经 pv_bridge**：`eval_persona.py` 顶层 import vllm 不可用；桥 = abcr 仓内自研 transformers 生成脚本，**语义逐项复刻**官方 extract 流程（模板渲染→生成→官方 judge 过滤→官方 CSV schema），官方文件零改动；仅有的两个补丁（config.py HF_TOKEN 可选化、generate_vec.py 增 --dtype）以 patch 文件管理并记谱系。云日一律用官方原版脚本（vLLM 在场）。
- **D6 judge 替换**：主 judge = DeepSeek（F8 注入）。阶段 2 入口由 C 做 D0 实测（logprobs/top_logprobs 可用性 + 0-100 数字单 token 性），结论落 `review/judge_probe_report.json` 供 B 消费（B 侧后备：该文件迟到则自跑最小探针并记 DEVIATIONS）；不兼容 → 降级 temp0 全文数字解析（官方 binary_text 同构），偏差记谱系。n=50 双 judge：第二家族 = Claude（`CLAUDE_RAW=1 claude -p` 订阅通道），明记「锚 trait 工件亦 Claude 生成」同源提示；样本用官方 7B baseline CSV；**阶段 4 才做**（楠阶段律）。
- **D7 官方校准 trait = optimistic**（d2 范围内择定：判分直观、翻转 demo 与家庭展示最友好）；sycophancy 备选不并行。
- **D8 锚 trait 工件**用官方 `generate_trait` prompt 经 claude CLI 生成，40 题拆 20+20，`抽取∩评测=∅` 构造保证 + 哈希断言（E17）；provenance 记生成模型与日期；楠过目为唯一人肉动作，不阻塞工程链（阶段 3 用 #1 尽责；#2 开放 #3 神经质在阶段 4）。
- **D9 任务族 #1 = IFEval 式**：主路径 HF `google/IFEval`，过滤到 checker registry 冻结支持的约束类型，item_id=sha256(prompt)[:16]；下载失败后备 = claude CLI 按 registry 生成同构题 + 人工抽查 10 题。split 20/40/40 按 item_id 哈希、split 文件哈希入 git；W1 只碰 dev。题库与 split 归 A（runner 输入侧），checker 归 C（评分侧），经 item schema 解耦（item 行内嵌 checks 规格）。第二任务族列 stretch 不占关键路径。
- **D10 steps.jsonl 带哈希链**（trace_writer 模式 + 每行 fsync）：复现包防篡改从第一天结构化；评分永不回写 steps。
- **D11 mini 环参数**（楠阶段 3 精化后）：臂 = vanilla / prompt_persona / residual_vector / **random_direction（等范数随机方向，与向量臂同 |coef|·|v|）** 四臂 × **30 题** × 2 seed（{17,42}）+ temp0 sanity；trait = 尽责（锚 #1，dev 向量与文本臂同源同 trait——楠「B 抽取候选方向」语义）；层/系数取 B 方向复现检中「trait 分动、输出未崩」一档（dev 性质）。预计 3B MPS 过夜跑完（7/16 晚起跑，B 向量落位后；仍缺位则按后备）；止损：30→20 题。三条附注：①**W1 激活采集只覆盖向量/随机臂的注入侧投影**（无向量臂 capture_path 恒 None）——文本臂投影分布采集移 W2（W2 剂量钳制依赖它，W2 方案勿误以为 W1 已有此数据）；②相对 W1 V0.9 §5 的顺序偏移：dev 表达检后置到与 mini 环同阶段、向量臂系数取方向检档而非表达检档——rig 验证定位下可接受，正式口径云日 #2 回填；③向量臂后备的无参照 random_direction 用字面量 spec（见 D12）。
- **D12 汇合协议**：跨包消费只认冻结路径（F6/F7），缺位走后备——文本臂后备 = `artifacts/traits/optimistic/`（B 在 S2 从官方工件标准化落位）；向量臂后备 = optimistic-dev；终极后备 = 无参照 random_direction 字面量 spec `{method: random_direction, layer: 20, coefficient: 8.0, target_norm: 1.0, direction_seed: 5678}`（单位范数向量，rig 演练值，标 synthetic-rig-test）；A 缺 items→fixtures 10 题。不跨窗口沟通；阶段门见 §3/F11。
- **D13 路径避讳**：见 §2.3-2。
- **D14 云账本**：costs/ledger.jsonl 阶段 0 建账即 G6 证据（W1 实耗 ¥0 + Runbook 五步纪律）。
- **D15 对楠分工建议的采纳与五处精化**：①（假模型）tinyqwen 用真 tokenizer + 钉死模板（模板检需真渲染），bootstrap 生成、离线确定；②（知识边界）A 与 B 经 `interventions/api.py` 冻结接口解耦——B 交付库、A 盲用 context manager，「A 不理解向量生成」落为代码边界而非口头约定；③（题库归属）items/split 归 A、checkers 归 C，item schema 内嵌 checks 规格实现「C 不参与生成」；④（两次出包）阶段 2 首包（官方 trait steering 链）+ 阶段 4 终包（mini 环），复现工具链被完整演练两遍；⑤（表达检分级）阶段 3 的表达检为 dev 级（3B、non-citable、方向+分布记录），W1 正式表达检判定仍属云日 #2——G4' 口径不变。

---

## 6. 日程（阶段制；今天 2026-07-11 五）

| 阶段 | 目标时点 | 内容 | 门 / 止损 |
|---|---|---|---|
| S0 | 7/11 下午 | 三窗启动；bootstrap（repo/venv/0.5B+3B 下载/revision 与模板钉死/tinyqwen 生成）；契约文件落位（api.py、errors.py、schema.py 骨架） | bootstrap 幂等可重入 |
| S1 | 7/12–7/13 | 全 fixture：A writer/链/幂等/2-step/preflight；B hook 三验证；C parser/评分/manifest/复评 | `make stage1-regression` 全绿（对应 W1 方案 7/13 黄金测试门） |
| S2 | 7/14–7/15 | A 真模型烟检+模板检+双跑检+IFEval 题库+split 入 git；B pv 干跑 0.5B e2e → optimistic 3B dev 向量 + 方向复现检 + 翻转预览；C judge D0 + 盲评 + score/review 实链 + **首个复现包** | `make stage2-regression` 全绿；**止损**（7/14 晚，沿 W1 方案）：runner 不稳→砍 3B 契约档保 0.5B/tinyqwen 直取主链 |
| S3 | 7/16 | B 尽责锚 trait 工件+3B dev 抽取（stage2 回归绿灯当晚即可作 S3 首项启动，目标 7/16 日间落位）；A mini 环 4 臂×30 题×2 seed（**7/16 晚过夜起跑**，B 向量落位后；仍缺则按 D12 后备）；C 先行完成 exprcheck 盲评与图表准备 | `make stage3-regression`（生成完成后）；止损 30→20 题 |
| S4 | 7/17 | C 上午完成 mini 环评分+复评全量+主图（复评一致为门，沿 W1 方案原 7/16 门顺延半日）→ 终包出包 → **全新会话闭合验收**；扩展：锚 #2/#3 工件+dev 抽取、n=50 双 judge、云日 Runbook×3 终检；周报素材（G7 措辞） | 四件 Mac 交付齐；出口门全过 |
| — | 7/18 六 | 对外日：复现包 + 3B 翻转预览（明标 non-citable dev preview）+ 云日计划书；措辞按 G7 | 周配额起算 |

云日 #1/#2 不在本表内：Runbook 就绪后由楠择日租卡纯执行（内含 5% smoke、checkpoint、产物回传、完成即关机、逐实例记账）。

---

## 7. W1 出口门（Mac 版映射）

| 门 | 本周判定 | 验收动作 |
|---|---|---|
| G1 可重复 | **实过** | 同 config 重跑覆盖一致；temp0 双跑逐字节一致；manifest 校验通过 |
| G2 schema 就绪 | **实过** | 全部 run 过字段校验；合成 2-step 写读重放通过 |
| G3 配方校准 | **转 G3'-就绪** | pv_bridge 0.5B/3B 全链通 + 3B 方向复现检过 + 云日#1 Runbook 检查单全绿；7B 对表校准待云日 |
| G4 首批向量 | **转 G4'-就绪** | 3 锚 trait 工件版本化 + judge 替换 D0 与 n=50 在案 + 尽责 3B dev 向量（direction-k、non-citable）；正式表达检待云日 |
| G5 闭环闭合 | **实过** | 全新会话仅凭复现包 verify+rescore，分数一致（阶段 2、4 各一次） |
| G6 预算 | **实过** | ledger 在案且 W1 GPU 实耗 ¥0 ≤ ¥150 |
| G7 呈现纪律 | **实过** | 周报/对外物全部数字带 exploratory / rig-validation / non-citable 标注 |

任一实过门未过 → 沿 W1 方案：W2 首日先补门，不带病推进。G3'/G4' 云日本体完成后回填原判据。

---

## 8. 风险登记（执行层新增；W1 V0.9 §9 全保留）

| 风险 | 概率 | 应对 |
|---|---|---|
| torch/transformers 在 macOS arm64 安装或 MPS 不顺 | 低中 | F2 放宽条款；契约档在 tinyqwen CPU float32——主链不被 MPS 绑架 |
| MPS temp0 双跑不确定 | 低 | 双跑检 MPS 失败→canonical 判定转 CPU 档并记录（诚实条款只承诺单机同环境确定级） |
| DeepSeek logprobs 与官方加权法不兼容 | 中 | D6 双档预案；阶段 2 入口 D0 定案，全链不等待 |
| google/IFEval 下载失败 | 低 | D9 后备生成路径，registry 不变 |
| 三窗 git 冲突 | 低 | F1 所有权互斥 + index.lock 重试；仍冲突响亮失败人工看 |
| mini 环过夜中断 | 中 | 幂等续跑本就是被测能力；kill 后续跑属演练剧本 |
| 楠过目锚 trait 工件延迟 | 中 | 过目只阻塞「工件转正」；阶段 3 可先以 draft 态跑 dev 抽取（工件文件带 review_status 字段），云日 #2 前转正即可 |
| 阶段门等待造成空转 | 中 | 各包每阶段末有「等待期可做」清单（文档内），如提前写下阶段代码骨架、补单测——不越阶段门跑实验 |
| 包文档自足性缺口 | 低 | 已做对抗审查（§9）；仍遇缺口→按包文档「缺口处置」独立决策记 DEVIATIONS.md，不回查 shared-brain |

---

## 9. lineage 与核验状态

**直接依据（全文已读）**：ABCR-W1方案-最小纵向闭环-V0.9；ABCR-实验方案-V1.3；ABCR-自动化实验流程设计-V0.9；ABCR-fable5聊天交接文档1；ABCR-12周方案-v1.1修订决定书；AILH_人格向量实验与创业并行12周方案（短版 v1.0）；楠 2026-07-11 分工建议（本会话内收到，全文采纳+D15 精化）。

**shared-brain 调研（2026-07-11 四路并行，只读）**：
- 治理与历史：工程进展史+理念演进档案全文核验——「ABCR/12周/steering」两文档零记载（全新事物）；~/abcr 不受拦截结论的源码级依据（sandbox.py:47-147、boss_redline_guard.py、v2_session_commit.py、~/.claude/settings.json）；七条历史教训逐条钉行号（V_mutable 2.65→3.15 = 工程史 L133；11.5% = L145+理念档 L219；G19/G51 = 理念档 L599-605；双 beat = 工程史 L641；误 HALT = L203+理念档 L296；Worker6 = L137；start 无 done 715/1519min = L510）。
- V2 模式提炼：trace_writer（selfiter/trace_writer.py）、Seatbelt（tools/sandbox.py）、resumable 原子写（tools/resumable.py）、部署一致性校验、告警冷却、fail 方向纪律——规格已内嵌各包。
- 资产全域：无既有激活工程/HF 权重；谱系资产 = L0-raw/chat-mac 0706/0707 两份前身对话、V2/scripts/calibration、v_core/v_mutable spec、L1-active/audit/evaluations。
- 环境：§2 全部条目实测。

**外部核验（本次实时，代码级）**：persona_vectors@b8e0f04 之 requirements.txt / eval/model_utils.py / eval/eval_persona.py / judge.py / config.py / activation_steer.py / generate_vec.py / scripts/*.sh / data_generation/prompts.py / trait_data_extract/optimistic.json——§2.4 全部有原文依据。HF 模型 revision 未预取（本机 HF `/api/` 不通），改为 bootstrap 从 snapshot 目录名钉死（F2），不构成缺口。

**独立决策声明**：楠指令「有疑问现在确认，没有则独立决策完成全套」+ 分工建议「自行决策」。无阻塞性疑问；全部裁量点入 D1–D15 可否决清单，未否决即按此执行。

---

## 10. 对包执行者的统一指令（每包文档开头也有）

你是三个并行 Claude Code 窗口之一（建议 Opus 长上下文），任务 = 完整执行你那份工程包文档。纪律：
1. 文档自足，**不需要也不要**读 shared-brain 下任何文件；文档没写的细节按「缺口处置」节独立决策并记 `DEVIATIONS.md`（append-only，带包名前缀）。
2. 只写所有权矩阵内属于你的文件；消费他包产物只认冻结路径，缺位走后备；不跨窗口沟通。
3. **按阶段推进**：完成阶段 N 自验后更新 `STATUS-<包>.md`（含验收输出摘录），**停在阶段门等统一回归**；等待期只做文档列出的「等待期可做」项。
4. 每完成一个 WBS 条目即 git commit（前缀 [A]/[B]/[C]）。
5. 验收断言必须真实跑过、输出留存；失败如实报告，禁止降低断言换绿。
6. 全部完成后 STATUS 写终态：完成清单、验收摘录、偏差、遗留。
