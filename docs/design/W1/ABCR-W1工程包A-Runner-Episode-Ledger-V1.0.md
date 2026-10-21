# ABCR W1 工程包 A：Runner + Episode + Ledger（V1.0，自足执行文档）

> 执行者：一个独立 Claude Code 窗口（建议 Opus 长上下文）。本文档自足：**执行全程不需要、也不要读取 shared-brain 下任何文件**。
> 上位：《ABCR-W1执行方案-V1.0.md》（同目录）。你只需本文档即可完工；若想核对接口冻结区权威版本可看上位文档 §4，除此以外不需要任何外部材料。
> 你的使命：把「一条实验链可重复运行」的**运行侧**建成——原子 step 写入与账本、config→run、preflight 冻结检查、幂等续跑、题库与 split、mini 环执行。**你不理解向量怎么生成**（那是包 B 的事，你只经冻结接口盲用）；**你不评分**（那是包 C 的事，你只产原始输出）。

---

## 0. 统一执行纪律（三包相同）

1. 文档没写的细节：独立决策，在 `/Users/superagent/abcr/DEVIATIONS.md` 追加一行（前缀 `[A]`），不回查任何外部文件。
2. 只写「所有权矩阵」（§3-F7）中属于 A 的文件；消费他包产物只认冻结路径，缺位走本文档后备；**不跨窗口沟通**。
3. **按阶段推进**：完成阶段 N 自验后更新 `/Users/superagent/abcr/STATUS-A.md`（含验收输出摘录），停在阶段门等统一回归。回归协议：三包 STATUS 均报完成后，由**最后完成的窗口**跑 `make stage<N>-regression`，全绿提交 `[REG] stage<N> PASS`（失败提交 FAIL+摘要，责任包修复重跑）；**你的放行信号 = git log 出现该 PASS 提交**。等待期只做本文「等待期可做」项。
4. 每完成一个 WBS 条目 git commit（前缀 `[A]`）；遇 `index.lock` 等 2s 重试 ≤5 次。
5. 验收断言必须真实跑过、输出留存；失败如实报告，**禁止降低断言换绿**。
6. 治理三条（背景见 §2）：本窗口不跑 `/boss`；本仓永不 `git push`；仓内路径规避子串 `"/persona/"`、`"v_core"`、`"judgment_engine"`。

## 1. 背景 primer（2 分钟读完，不需要更多背景）

ABCR 是楠的 12 周研究项目：在开源模型（Qwen2.5 家族）上研究「人格文本效应 × 内部人格向量」的因果关系。W1（本周）不产科学证据，只造**产生证据的机器及其正确性证明**：一条从「冻结配置」到「可复现实验包」的链。执行分五阶段（S0 契约冻结 → S1 全 fixture → S2 接真模型与一个官方 trait → S3 一个锚 trait + mini 环 → S4 闭合与扩展），阶段内三包并行、阶段间统一回归。三包知识边界（冻结）：**B 只输出标准化向量工件；A（你）不理解向量生成过程；C 只消费原始输出、不参与生成**。

Mac（本机）产物一律 `citable=false`（正式证据要 24GB 云卡 bf16，本周期不租卡）；一切只碰 dev split；对外数字必带 exploratory / rig-validation 标注。

## 2. 环境与治理事实（已实测，直接信任，不必复查）

- 本机：Mac mini M4，16GB 统一内存，macOS 26.4.1，磁盘余 122Gi。**7B 本机跑不动**；3B fp16 MPS 流畅；0.5B CPU 可跑。
- `/opt/homebrew/bin/python3.11`（=3.11.15）与 `uv`（0.11.3）可用；**系统默认 python3=3.14 不要用**。本机无 torch/transformers/HF 缓存，全部从零装。PyPI 与 huggingface.co 直连可达（HF `/api/` 路径不通但 `snapshot_download` 走 CDN 不受影响）；无代理无镜像。
- Qwen2.5-0.5B/3B-Instruct 模型**不 gated**，匿名下载，无需 HF token。
- 治理：`/Users/superagent/abcr` 不受任何沙箱/hook/监督系统拦截（已源码级核实）；SessionStart 会注入一段 AILH 工程史背景——无害，忽略；git 全局无 user 配置，bootstrap 会配本地级。
- git 纪律：本地仓、无远端、永不 push（楠既定决策）。

## 3. 接口冻结区 v1（等效副本；如有出入以上位文档 §4 为准；bootstrap 脚本权威全文在上位 §4-F13，本文 A0.1 为逐字副本）

### F1 仓库与身份
- 路径 `/Users/superagent/abcr`；本地 git（`git init -b main`；`git config user.name "Yinan Wang"`；`git config user.email worldofnan130@gmail.com`），无远端、永不 push。
- 提交前缀 `[A]`/`[B]`/`[C]`/`[REG]`；`index.lock` 冲突：等 2s 重试 ≤5 次，仍失败响亮报错。
- 三包文件所有权互斥（F7）；`mkdir -p` 不算冲突；`DEVIATIONS.md`、`STATUS-*.md` 为共用 append 文件。

### F2 环境
- 主 venv `/Users/superagent/abcr/.venv`（`uv venv --python /opt/homebrew/bin/python3.11`）。依赖：`torch==2.6.0, transformers==4.52.3, accelerate==1.7.0, datasets==3.6.0, pandas==2.3.1, pyarrow, duckdb, scipy, statsmodels, matplotlib, typer, pydantic==2.11.7, pyyaml==6.0.2, pytest, openai==1.70.0, backoff==2.2.1, tqdm, huggingface_hub`。torch==2.6.0 装不上则放宽 `torch>=2.6,<2.8` 并记 DEVIATIONS。
- 包 B 另有 `.venv-pv`（与你无关）。
- 模型 revision 钉死：`snapshot_download` 后读 `~/.cache/huggingface/hub/models--*/snapshots/<sha>` 目录名写入 `configs/models.yaml` 并 commit；此后一切加载显式 `revision=`。7B 占位 `revision: PIN-AT-CLOUD-PROVISION`。
- 阶段 1 假模型 tinyqwen：`Qwen2Config(hidden_size=64, num_hidden_layers=4, num_attention_heads=4, num_key_value_heads=2, intermediate_size=128, vocab_size=<0.5B tokenizer 的>, max_position_embeddings=512)` 随机初始化（seed 0）+ 0.5B 的 tokenizer/chat template，存 `tests/fixtures/tinyqwen/`（bootstrap 生成；CPU float32）。
- **tinyqwen 冻结钉死**（使 E02/E03 在 S1 可按文字执行）：bootstrap 在 models.yaml 写入条目 `tinyqwen: {model_id: tests/fixtures/tinyqwen, revision: "local-fixture-seed0"}`，并把 0.5B 的模板 hash 与样例复制为 `configs/templates/tinyqwen/`（tokenizer 同源）；tinyqwen 的 step 记 model_id="tinyqwen"、model_revision="local-fixture-seed0"。models.yaml 合法 key 集 = {tinyqwen, qwen2.5-0.5b-instruct, qwen2.5-3b-instruct, qwen2.5-7b-instruct}。

### F3 目录布局（bootstrap 一次建全；未用目录空建占位防漂移）
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
├── runs/<run_id>/{config.yaml, manifest.json, steps.jsonl, activations/, judge_raw.jsonl?}
├── scores/<run_id>/{scores.jsonl, summary.json}      ├── review/<run_id>/review_report.json
├── repro_packs/<runset>/       ├── figures/
├── third_party/persona_vectors/   ├── patches/   ├── pv_bridge/{extract_mac.py, flip_preview.py, exprcheck_gen.py, out/}
├── scripts/{bootstrap.sh, cloud/}  ├── costs/ledger.jsonl
└── tests/{fixtures/, unit/, contract/stage1/, contract/stage2/, contract/stage3/, contract/stage4/}
```
`.gitignore`：`.venv*/ third_party/ __pycache__/ .bootstrap.lock .pytest_cache/ *.pyc tests/fixtures/tinyqwen/ pv_bridge/out/`。runs/scores/vectors/figures 入 git。

### F4 steps.jsonl schema（w1.1，冻结）
一行 = 一 step（单轮 = 长度 1 的 trajectory）。

| 组 | 字段 |
|---|---|
| 元 | schema_version="w1.1", run_id, trajectory_id, step_id(int), parent_run(null 允许；-t0 派生 run 记原 run_id，其余 null) |
| 溯源 | git_commit, config_hash, protocol_ref, env_lock_ref |
| 模型 | model_id, model_revision, dtype, quantization(null), device, device_backend(mps/cuda/cpu), engine="transformers", engine_version, torch_version, cuda_version(Mac=null), chat_template_hash |
| 数据 | benchmark(=任务族), split_hash, item_id |
| 条件 | condition(vanilla/prompt_persona/residual_vector/random_direction), trait(null), trait_pole(pos/neg/null), method(none/prompt_persona/residual_vector/projection_ablation/random_direction), layer(null), coefficient(null), intervention_strength(null) |
| 轨迹 | env_seed(null), action(null), obs_hash(null), remaining_budget(null), stop_reason(枚举: eos/max_new_tokens/error), state_snapshot_ref(null) |
| 解码 | random_seed(int)（temperature/max_new_tokens 在 run config，经 config_hash 溯源） |
| IO | prompt_hash, output_text, parsed_answer(生成时 null), is_correct(生成时 null，评分永不回写本文件), latency_ms, input_tokens, output_tokens |
| 评 | trait_score(null), fluency_score(null), safety_flags([]) |
| 激活 | activation_summary(null 或 {path, layer, proj_mean, proj_p50, proj_p90}) |
| 标记 | citable(bool；Mac 恒 false) |
| 链 | prev_hash, entry_hash |

### F5 写入语义
- append-only JSONL；每行：组装 → `prev_hash`=链尾（首条 "0"×64）→ `entry_hash`=sha256(canonical_json(含 prev_hash、不含 entry_hash；sort_keys；ensure_ascii=False) + prev_hash) → open('a') 写 → flush + os.fsync。
- 幂等续跑：启动读 steps.jsonl 构建完成集 {(item_id, random_seed, condition, step_id)} 跳过；尾部半行 → 拒跑（E07）并指路 `--repair`：原文件改名 `steps.jsonl.crashed-<ts>` 永久归档、有效前缀重写新文件、manifest 记 repair 事件。
- 铁律：不得只存汇总分；评分产物独立于 runs/。

### F6 scores / review / 向量工件 / 判定工件
- `scores/<run_id>/scores.jsonl` 行：{run_id, trajectory_id, step_id, item_id, condition, random_seed, scorer_version, checks:[{name,pass,detail}], is_correct(bool), score(float 0-1)}；join 键 (run_id, trajectory_id, step_id)。`summary.json` 逐臂×seed 聚合 + 长度统计。
- `review/<run_id>/review_report.json`：{n_steps, n_expected, missing[], duplicated[], chain_ok, score_mismatches[], manifest_checks{}, error_codes[], pass}。
- 向量工件（B 产，你视 .pt 为不透明二进制）：`vectors/<model-slug>/<trait>-<grade>/` 三件套 `response_avg_diff.pt`（float32，shape=(层数+1,hidden)）、`card.json`{trait, model_id, model_revision, source_commit, extraction_date, grade, judge_model, judge_lineage, recommended{layer,coef}, n_pos_effective, n_neg_effective, pt_sha256, notes}、`extraction_meta.json`。
- judge 判定工件：`runs/<run_id>/judge_raw.jsonl`（逐样本原始返回 + 解析分），聚合可重算。

### F7 所有权矩阵
| 路径 | 所有者 |
|---|---|
| scripts/bootstrap.sh、pyproject.toml、CLAUDE.md、README.md、Makefile、configs/、src/abcr/{models,run,splits,build_items}.py、logging/ 全部、interventions/api.py（仅接口文件）、src/abcr/ 及其子包全部 __init__.py、data/、runs/（数据）、costs/、tests/fixtures/（golden_answers、vector_tiny 除外）、tests/contract/*/test_a_*.py、tests/unit/test_a_*.py | **A（你）** |
| src/abcr/interventions/{prompt_persona,residual_vector,projection_ablation,random_direction,capture}.py、third_party/、patches/、pv_bridge/、artifacts/traits/、vectors/、scripts/cloud/、tests/fixtures/vector_tiny/、tests/*/test_b_*.py | B |
| src/abcr/{score,review,repro_pack}.py、eval/ 全部、scores/ review/ repro_packs/ figures/、tests/*/test_c_*.py、tests/fixtures/golden_answers/ | C |

### F8 密钥与 judge 纪律（你在 A 基本不触 judge，仅须知禁令）
- DeepSeek key 只经进程环境注入（`OPENAI_API_KEY=$(cat /Users/superagent/oc-boss-state/deepseek.key)`、`OPENAI_BASE_URL=https://api.deepseek.com`）；key 不写入任何文件/git/日志；禁止创建 .env。

### F9 呈现与运行纪律（由你在 A0.2 写入 abcr/CLAUDE.md，内容清单见 A0.2 的 CLAUDE.md 条目）
### F10 错误码（`src/abcr/logging/errors.py`，A 实现，全仓共用）
E01_PREFLIGHT_GIT_DIRTY（--dev 放行并打 non-citable）/ E02_REVISION_MISMATCH / E03_TEMPLATE_HASH_MISMATCH / E04_SPLIT_HASH_MISMATCH / E05_CONFIG_INVALID / E06_ARM_PURITY_VIOLATION / E07_STEPS_TAIL_CORRUPT / E08_CHAIN_BROKEN / E09_RESUME_CONFLICT / E10_SCORE_JOIN_INCOMPLETE / E11_SCORE_MISMATCH / E12_MANIFEST_INCOMPLETE / E13_JUDGE_UNAVAILABLE / E14_JUDGE_PARSE_FAIL / E15_VECTOR_ARTIFACT_INVALID / E16_BUDGET_EXCEEDED / E17_DISJOINTNESS_VIOLATION / E18_GOLDEN_FAIL。全部 fail-closed（E14 按样本记、率>10% 整批 fail）。CLI 非零退出并打印码。
**E06 禁键集合（冻结）**：method∈{prompt_persona, none} 的 spec 禁含 {vector_dir, vector_path, match_to, direction_seed, target_norm}；method∈{residual_vector, random_direction, none} 的 spec 禁含 {artifact, instruction_index}。manifest 相应字段 has_vector_ref / has_persona_ref（按上述键集判定）。

### F11 你参与的分阶段契约测试（全清单见上位 §4-F11）
- S1：test_a_writer_chain / test_a_traj2step / test_a_preflight
- S2：test_a_qwen_smoke / test_a_template_pin / test_a_doublerun
- S3：test_a_mini_loop_coverage / test_a_arm_purity

### F12 checker 契约 CT-1（你按此过滤题库；C 按此实现 checker；两份文档表格逐字一致）
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
多约束题：is_correct = 全部 checks pass；score = 通过比例。数据集 kwargs 键名与上表不一致处：以语义映射为准，映射决定记 DEVIATIONS。

---

## 4. WBS（按阶段执行）

### 阶段 0（S0）：bootstrap + 契约文件（目标 7/11 内完成）

**A0.1 bootstrap**。把下述脚本写入 `scripts/bootstrap.sh`（若已存在则直接执行，不改写）并运行。脚本与上位 §4-F13 权威全文逐字一致（B/C 首启时也会按 F13 写入并执行——先到先跑、互斥锁防双跑）：

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
# 模板钉死：hash + 3 渲染样例
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
# tinyqwen（阶段1 假模型；确定性 seed 0）
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

**A0.2 契约代码文件**（bootstrap 后立即写，B/C 依赖）：
- `src/abcr/logging/errors.py`：`class AbcrError(Exception)` 带 `code`；F10 全部码为常量；`def die(code, msg)`（打印码并 `sys.exit(1)`）。
- `src/abcr/logging/schema.py`：`STEP_FIELDS`（F4 全字段：名 → (类型, 可空)）；`validate_step(d: dict)`（缺字段/类型错/非法枚举 → AbcrError(E05)）；`SCHEMA_VERSION="w1.1"`；`canonical_json(d)`（sort_keys、ensure_ascii=False、不含 entry_hash）。
- `src/abcr/interventions/api.py`（**冻结接口，S0 后不再改**）：
```python
class Intervention(Protocol):
    spec: dict                      # 原样写入 step 条件组字段
    system_text: str | None        # 文本干预注入的 system 内容；无则 None
    def context(self, model): ...   # 返回 contextmanager；生成期间生效（hook 类干预在此挂/摘）
    def describe(self) -> dict: ... # {condition, trait, trait_pole, method, layer, coefficient, intervention_strength}
    def activation_summary(self) -> dict | None: ...  # 生成后可选返回 {path, layer, proj_mean, proj_p50, proj_p90}
# runner 侧补充语义（与包 B 文档一致）：runner 在需要激活抽样时于 generate 前设 iv.capture_path=<npz 路径>；
# 实现若见 capture_path 非空则采集并在 activation_summary() 返回摘要，否则返回 None。

def get_intervention(spec: dict, model_key: str) -> Intervention:
    """按 spec['method'] 经 importlib 动态加载 abcr.interventions.<method> 模块的 build(spec, model_key)。
    method=none 时返回内置空干预（system_text=None、context=空 contextmanager）。
    模块缺失 → AbcrError(E05)。A 对各实现内容保持无知。"""
```
- `Makefile`：`bootstrap`、`stage1-regression: .venv/bin/pytest tests/contract/stage1 -x -q`（2/3/4 同构）、`mini-loop`（S3 填充）、`repro-pack: .venv/bin/python -m abcr.repro_pack --preset $(PRESET) --out repro_packs/$(PRESET)`（上位 V0.9 的 RUNSET 语义由 preset 承接；C 实现后生效）。
- `CLAUDE.md`（abcr 仓，供所有窗口）：内容 = §0 六条纪律 + F9 呈现纪律（non-citable、dev-only、exploratory 标注、fail 方向、¥150 预算常量）+「本仓三包并行，所有权矩阵见各包文档」。
- `README.md`：一段话（项目名、W1 目标、目录导览、`make` 入口）。
- 提交：`[A] S0 contracts: errors/schema/api/Makefile/CLAUDE.md`。

**A0 验收**：bootstrap 重跑第二遍输出 "bootstrap done"（幂等）；`configs/models.yaml` 有两个真实 revision sha；`configs/templates/*/sample_*.txt` 存在；tinyqwen 可 `from_pretrained`；契约文件全部落位并 commit。

**等待期可做**：预写 S1 各测试骨架。

### 阶段 1（S1）：全 fixture（目标 7/12–7/13；tinyqwen，CPU float32，不接网、不接 judge）

**A1.1 `logging/writer.py`**。`class StepWriter(run_dir)`：
- `append(step_dict)`：validate → 链字段（F5）→ 'a' 写行 → flush + `os.fsync(fd)`。
- `load_done() -> set[(item_id, random_seed, condition, step_id)]`；尾部半行检测（最后一行 json.loads 失败 → AbcrError(E07)）。
- `verify_chain(path)`（逐条 prev/entry 重算；**语义定死：链完整返回 True，断链 raise AbcrError(E08)**，调用方自行 catch）——此函数 C 的 review 也会调用，放 writer.py 内保持单实现。
- `repair(run_dir)`：`steps.jsonl` → `steps.jsonl.crashed-<ts>`（保留），有效前缀重写新文件（链重算），返回 repair 事件 dict 供 manifest 记录。

**A1.2 `logging/manifest.py`**。`write_manifest(run_dir, config, extra)`：{run_id, config 全文嵌入, **config_hash=sha256(canonical_json(config dict))（canonical_json 用 schema.py 单实现）**, git_commit, model{key,id,revision,dtype,device_backend}, chat_template_hash, split_hash, arm_purity{declared_method, has_vector_ref(bool), has_persona_ref(bool)——按 F10 的 E06 禁键集合判定}, env_lock_ref(=`pip freeze` 落 `runs/<id>/env.lock` 的相对路径), protocol_ref="docs/1Personality-Experiment-Final/ABCR-W1执行方案-V1.0.md@sha256:<hash>"（bootstrap 后计算一次存 configs/protocol_ref.txt——若该文档不可达则写 "UNAVAILABLE-see-DEVIATIONS"，不去读 shared-brain）, started_at/finished_at, n_steps_expected/written, repair_events[], citable}。
> protocol_ref 特例：唯一允许触碰 shared-brain 的动作是 bootstrap 时对上位文档算一次 sha256（只读单文件）；失败不阻塞。

**A1.3 `run.py`（runner 核心，先在 tinyqwen 上通）**。CLI：`python -m abcr.run --config <yaml> [--dev] [--resume <run_id>] [--repair <run_id>]`。
- run config schema（示例落 `configs/runs/example_fixture.yaml`）：
```yaml
model_key: tinyqwen | qwen2.5-0.5b-instruct | qwen2.5-3b-instruct
condition: vanilla            # vanilla|prompt_persona|residual_vector|random_direction
intervention: {method: none}  # 或 B 的 spec（A 不解释内容，原样透传 get_intervention）
data: {family: ifeval_style, items: data/items/ifeval_style/items.jsonl, split_file: data/splits/<f>.json, split: dev}
# S1 的 example_fixture.yaml 用 fixture 三件：family: fixture, items: tests/fixtures/items_fixture.jsonl,
#   split_file: tests/fixtures/split_fixture.json（A1.6 一并产出，10 题全 dev，格式同 A2.6；E04 照常校验其 sha256）
decoding: {temperature: 0.7, seeds: [17, 42], max_new_tokens: 512, temp0_sanity: true}
activation_sampling_rate: 0.1
run_name: <slug>
```
- `run_id = <UTCyyyymmdd-HHMMSS>-<config_hash[:12]>`；resume 时沿用原 run_id。
- preflight（fail-closed，逐项对应错误码）：git clean（E01；--dev 放行并 citable=false+non-citable 标进 manifest。**注：三包并行期 B/C 持续提交，git 几乎不会 clean，Mac 上例行加 --dev 属预期，勿在 E01 上排查**）、model revision 对 configs/models.yaml（E02；tinyqwen 按 "local-fixture-seed0" 判定）、tokenizer 模板 hash 对钉死值（E03；tinyqwen 用 configs/templates/tinyqwen/）、split 文件 sha256 对 config 声明（E04）、config schema（E05）、臂纯度（E06 按 F10 冻结禁键集合双向判定）。
- 启动即复制 config 至 `runs/<run_id>/config.yaml`（F3 布局要求；manifest 另嵌全文）。
- 主循环：for item ∈ split 选中集 × seed ∈ seeds（temp0 sanity 作为**独立派生 run**：runner 在 temp0_sanity=true 时自动派生 `<run_id>-t0`，其 config temperature=0、seeds=[0]、parent_run=原 run_id；避免同 run 混温度）：跳过完成集 → 组消息（intervention.system_text 若非 None 则作 system）→ 渲染模板 → `torch.manual_seed(seed)` → `with intervention.context(model): generate` → 记 latency/token 数 → 组 step dict（intervention.describe() 展开进条件组；激活抽样：按 activation_sampling_rate 对 item 确定性抽样（sha256(item_id) 取模），命中则生成前设 `iv.capture_path=runs/<id>/activations/<item_id>_<seed>.npz`、生成后取 `iv.activation_summary()` 填入，未命中或返回 None 则字段为 null）→ writer.append。
- 结束：manifest 收尾（finished_at、计数）；打印 run 摘要。
- 生成参数：`do_sample=(temperature>0), temperature, top_p=1.0, max_new_tokens`；`pad_token=eos`。

**A1.4 合成 2-step 轨迹测试** `tests/contract/stage1/test_a_traj2step.py`：手工构造 trajectory_id=T1 的 step 0/1（人造 action="tool_call:search"、obs_hash=sha256("obs")、state_snapshot_ref="fixtures/snap0.json"、remaining_budget 递减、step1.parent 关系由 (trajectory_id, step_id) 表达）→ writer 写入 → 读回 → 「重放解析」：按 (trajectory_id, step_id) 排序重建时间线，断言字段语义完整（action/obs/state 逐一还原、链校验通过）。

**A1.5 契约测试**：
- `test_a_writer_chain.py`：写 5 行 → verify_chain 过；篡改第 3 行任一字段 → E08；删 1 行 → E08（prev 断）；模拟崩溃尾（追加半行）→ load 报 E07 → repair() 后旧文件存在、新链完整、完成集正确；重复 append 相同键 → E09。
- `test_a_preflight.py`：逐一制造 E01–E06 触发（临时脏文件、伪 revision、伪模板 hash、伪 split hash、坏 config、脏 spec），断言错误码精确。
- 用 tinyqwen 跑 `example_fixture.yaml`（fixtures 10 题，见 A1.6）×2 seed，端到端产出 runs/<id>/{steps.jsonl, manifest.json, env.lock}，validate_step 全过。
- **kill -9 演练**：脚本启动 run、在半程 kill -9、`--resume` 续跑，断言无重复无缺漏（这是幂等续跑的真实验收，不是单测模拟）。

**A1.6 fixture 题库与 split** `tests/fixtures/items_fixture.jsonl`：10 题，覆盖 CT-1 至少 6 种 check 类型（题目自拟英文指令题，checks 按 CT-1 kwargs 写死，行 schema 按 F6 冻结格式）。同时产出 `tests/fixtures/split_fixture.json`（10 题全 dev，格式同 A2.6）及其 `.sha256`。此两文件是 S1 端到端 run 与 C 评分链的共同输入。

**S1 验收（写 STATUS-A 后停阶段门）**：pytest stage1 中 test_a_* 全绿输出摘录；kill 演练记录；tinyqwen e2e run 目录树。

**等待期可做**：A2.1/A2.2 代码骨架、IFEval 下载脚本预写（不运行）。

### 阶段 2（S2）：真模型 + 题库 + split（目标 7/14–7/15）

**A2.1 `models.py`**：`load(model_key, device_backend=auto)`——读 configs/models.yaml 强制 revision；0.5B 默认 CPU float32、3B 默认 MPS float16（`mps` 不可用→CPU 并记 DEVIATIONS）；返回 (model, tokenizer, meta{dtype,device,engine_version,torch_version})。
**A2.2 真模型烟检** `test_a_qwen_smoke.py`：0.5B 与 3B 各 2 题 × 1 seed 生成落盘，全字段校验过、latency/token 数合理（>0）。
**A2.3 模板钉死检** `test_a_template_pin.py`：对两模型逐一渲染 bootstrap 的 3 组样例消息，与 `configs/templates/*/sample_*.txt` **逐字节**一致；tokenizer.chat_template 的 sha256 与 `.hash` 文件一致。渲染样例人工目检一次（你自己读一遍确认 im_start/system 位置正常）并在 STATUS-A 记「已目检」。
**A2.4 双跑检** `test_a_doublerun.py`：3B temp0 同 config 连跑两遍（2 题），输出文本逐字节一致。若 MPS 不定 → 改 0.5B CPU 作 canonical 判定、3B MPS 结果记 DEVIATIONS（诚实条款允许：只承诺单机同环境确定级）。
**A2.5 IFEval 题库**：脚本 `src/abcr/build_items.py`（一次性）：`datasets.load_dataset("google/IFEval")`（split=train，541 条）→ 逐条检查 instruction_id_list ⊆ CT-1 支持集 → 映射 kwargs → 写 `data/items/ifeval_style/items.jsonl` 行 {item_id: sha256(prompt)[:16], family:"ifeval_style", prompt, checks:[{name, kwargs}], source:"google/IFEval", source_key}。预期可保留百余条；若 <60 条：放宽到「多约束题中不支持的约束丢弃、保留支持子集且 ≥1 check」并记 DEVIATIONS。**下载失败后备**：用 claude CLI（`CLAUDE_RAW=1 ~/.local/bin/claude -p`）按 CT-1 逐类型生成英文指令题共 80 题（prompt 模板：给定 check 类型与 kwargs，产出自然任务指令），人工抽查 10 题合理性，source 记 "generated-claude"。
**A2.6 split**：`splits.py`——`make(family, items_path)`：bucket = int(sha256(f"{family}:{item_id}").hexdigest()[:8], 16) % 100；<20 dev、<60 calibration、其余 heldout；写 `data/splits/ifeval_style-<filehash8>.json`（**<filehash8> = items_source_sha256[:8]**）{family, items_source_sha256, assignment{item_id: split}, counts, tool_version:"1.0"}；**文件 sha256 即 split_hash**，写入文件旁 `.sha256` 并 git commit（「split hash 首轮前入 git」在此闭合）。`verify(split_file)` 供 preflight。W1 一切 run 只取 dev 子集（预期 ~20-30 题）。
**A2.7 mini 环 run 配置预置** `configs/runs/mini_{vanilla,text,vector,random}.yaml`（S3 用）：共同 {model_key: qwen2.5-3b-instruct, data: ifeval_style dev, decoding: {temperature:0.7, seeds:[17,42], max_new_tokens:512, temp0_sanity:true}, activation_sampling_rate:0.1}；差异 —— vanilla: {method:none}；text: {method:prompt_persona, trait:conscientiousness, trait_pole:pos, artifact:artifacts/traits/conscientiousness/extract.json, instruction_index:0}；vector: {method:residual_vector, trait:conscientiousness, vector_dir:vectors/qwen2.5-3b-instruct/conscientiousness-dev, layer:null, coefficient:null}（layer/coef 留空 = 从 card.json.recommended 读取）；random: {method:random_direction, match_to:vectors/qwen2.5-3b-instruct/conscientiousness-dev, layer:null, coefficient:null, direction_seed:1234}（等范数随机，B 的实现自会解释）。**dev 题量截取 30**（config 加 `data.limit: 30`，按 item_id 排序取前 30 保证跨臂同题）。

**S2 验收**：test_a_* (S2) 全绿；items.jsonl 与 split 及 .sha256 已 commit；mini 配置四件落位；STATUS-A 更新。
**等待期可做**：mini 环执行脚本排练（用 fixture items + method:none 走一遍四 run 编排）。

### 阶段 3（S3）：mini 环执行（目标 7/16，生成可过夜）

**A3.1 依赖检查**：`vectors/qwen2.5-3b-instruct/conscientiousness-dev/` 三件套（B 产）与 `artifacts/traits/conscientiousness/extract.json`（B 产）。**后备链**（B 迟到不等待，逐级降）：①文本臂改用 `artifacts/traits/optimistic/extract.json`（B 在 S2 从官方工件标准化落位——B 的 S2 明确承诺此产物）+ trait 改 optimistic；向量臂改用 `vectors/qwen2.5-3b-instruct/optimistic-dev/`；②向量工件全缺位 → 向量臂降级为第二个 random_direction，用**无参照字面量 spec**（B1.3 的 literal 模式）`{method: random_direction, layer: 20, coefficient: 8.0, target_norm: 1.0, direction_seed: 5678}`（单位范数向量 × 系数 8 为 rig 演练值，无科学含义，condition 备注 synthetic-rig-test）——mini 环仍完整验证 rig（其定位本就是 rig 验证非证据）。采用任何后备均改 config + 记 DEVIATIONS。
**A3.2 执行**：**7/16 晚过夜起跑**（stage3 依赖就绪或后备生效后）；四主 run + 四 -t0 派生 run 顺序执行（3B×MPS 单进程防内存超载）：30 题 × 2 seed × 4 臂 = 240 生成 + temp0 各 30×4=120，共 360 条 × ≤512 token，预估 3–6 小时；中途人为 kill 一次并续跑（把幂等演练做在真负载上）。止损（若晨起未完）：30→20 题（config limit 改 20，已完成部分因幂等保留）。
**A3.3 契约测试**：`test_a_mini_loop_coverage.py`——四主 run 的 steps 完成集恰为 {30 题}×{17,42}×{4 臂}（或止损后 20）无缺无重；**且向量/随机臂中 activation_summary 非空的 step 集合 = 确定性抽样（sha256(item_id) 取模 10%）命中集合**（10% 抽样率覆盖断言归 A，B 只管被选中 step 的采集质量）；`test_a_arm_purity.py`——逐 run manifest 的 arm_purity 断言 + steps 抽样反查（文本臂 step 无 layer/coefficient；向量臂 step 无 system_text 痕迹——prompt_hash 对 vanilla 同题同值）。
**A3.4** 通知性落位：`runs/MINILOOP-RUNSET.json`——**两组清单**：main_runs（4 个主 run_id，C 评分+复评+主图对象）与 t0_runs（4 个 -t0 派生 run_id，C 仅做链/完备性审计，不进主图），附参数摘要。

**S3 验收**：coverage/purity 测试绿；RUNSET 文件落位；STATUS-A 更新（C 随后评分复评，阶段门看 stage3 全绿）。

### 阶段 4（S4）：收尾（目标 7/17）

- 配合闭合验收（C 主导）：无 A 侧动作，待命修 bug。
- `costs/ledger.jsonl` 周结行：`{"ts":"<now>","provider":"none","cny":0,"note":"W1 Mac-only, no GPU rental"}`。
- README 补全（运行手册：从 bootstrap 到 repro-pack 的命令序列）。
- STATUS-A 终态。

---

## 5. 验收总清单（A 完工定义）

1. bootstrap 幂等（两遍运行证据）；models.yaml 两 revision 真实；模板 hash+3 样例入 git。
2. S1：writer 链/幂等/E07 修复/E09、preflight E01–E06、合成 2-step、tinyqwen e2e、kill -9 演练——全部有真实输出留存。
3. S2：0.5B/3B 烟检、模板逐字节检（含人工目检记录）、temp0 双跑逐字节一致（或 CPU canonical + DEVIATIONS）、items+split 入 git、四 mini 配置就位。
4. S3：mini 环 4 臂×30(20) 题×2 seed + temp0，coverage 无缺重、purity 双向断言过、RUNSET 落位、途中 kill+续跑记录。
5. 全程：每 WBS 一 commit；STATUS-A 各阶段更新；DEVIATIONS 如实。

## 6. 不做清单（A 范围外，勿做）

评分/复评/出包（C）；一切 hook/向量/judge 内容（B/C）；vLLM/云操作；界面；多轮 agent；第二任务族（除非 S4 全部完成后仍有余裕，作 stretch：解验证/找错族 exact-match 题 20 道 + split，同规格）。

## 7. 缺口处置

本文档未覆盖的决策：按「最小实现、fail-closed、可追溯」三原则就地决定，记 DEVIATIONS.md（格式：`[A] <日期> <决策> <理由一句>`）。禁止为缺口去读 shared-brain 或询问其他窗口。若缺口属于接口冻结区级别（改 schema/路径/错误码）：停下，在 STATUS-A 标 `BLOCKED-CONTRACT`，等阶段回归时由 Fable 裁决。

## 8. V1.1 补丁接入注记（2026-07-12 append；本文档其余内容不变）

《ABCR-W1执行方案-V1.1补丁-资源治理门与节奏修订》（同目录）已发布：D16/F14 资源契约、错误码 E19/E20/E21、S1.5 资源治理门对本包生效，冲突以补丁为准。A 包最低必守与必交：
1. **重负载全机串行**：任何 ≥0.5B 真模型加载、真模型 pytest（含 stage≥2 回归）、claude CLI 批量（>5 次）必须持有 `/Users/superagent/abcr/.resource/heavy.lock`——取锁 → 锁内 preflight → 执行 → 释放（协议见补丁 F14.2/§3.2）；tinyqwen 一切用途豁免。
2. **软熔断与分片**：runner 样本间探测内存压力（warning×2 / critical 单次 → E19 优雅退出后按补丁 F14.6 续跑）；增加 `--max-items-per-chunk`（3B 默认 20），复用既有 --resume。
3. **S1.5 交付归 A**：`src/abcr/resource_guard.py`（stdlib-only）、`make resource-smoke`、runner 接入、`tests/contract/stage2/test_a_resource_guard.py`（F7 增行归 A，验收判据见补丁 §3.3）。批2 回填 run 需把 `iv.activation_summary()` 写回 step（补丁 §6-P4）。
