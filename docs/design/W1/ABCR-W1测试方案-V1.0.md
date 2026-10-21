# ABCR W1 基础设施对抗性测试方案 V1.0

> **目的**: W1 是整个 ABCR 人格向量实验的工程骨架。本文档为新 agent 提供完整上下文，执行对抗性审查——找出隐藏 bug，尤其是"看起来正常但数据已被静默污染"的情况。
> **范围**: 仅审查 W1 云端执行中修改/自定义的代码，不审查 PV 原始代码的正确性。
> **产物位置**: Mac 端 `/Users/superagent/abcr/`

---

## 一、执行环境

| 项目 | 值 |
|------|---|
| GPU | AutoDL RTX 4090 24GB |
| torch | 2.8.0+cu128 |
| transformers | 4.52.3 |
| 模型 | Qwen2.5-7B-Instruct (28 layers, hidden=3584, bf16) |
| 模型来源 | ModelScope, revision a09a35458c70 |
| Judge | deepseek-chat via OpenAI SDK (OPENAI_BASE_URL=https://api.deepseek.com) |
| vLLM | **未使用**（ABI 不兼容，改为 transformers-only） |
| PV commit | b8e0f044fe2410a6fad579f38324f03f13b4e917 |
| 云端工作目录 | `/root/autodl-tmp/abcr-work/` |
| Mac 产物目录 | `/Users/superagent/abcr/cloud-results/` |

---

## 二、代码修改清单（共 3 个文件被修改）

### 2.1 eval_persona.py — vLLM 替换为 transformers

**文件**: `third_party/persona_vectors/eval/eval_persona.py`

**修改 1: import 替换**
```python
# 原始
from vllm.lora.request import LoRARequest
from vllm import LLM, SamplingParams

# 修改后（注释掉 vLLM，保留 transformers）
# from vllm.lora.request import LoRARequest
# from vllm import LLM, SamplingParams
```

**修改 2: `sample()` 函数完全重写**
```python
# 原始: 使用 vLLM 的 LLM.generate() + SamplingParams
def sample(model, tokenizer, conversations, top_p=1, max_tokens=1000, temperature=1, min_tokens=1, lora_path=None):
    sampling_params = SamplingParams(temperature=temperature, top_p=top_p, max_tokens=max_tokens, ...)
    ...
    completions = model.generate(texts, sampling_params=sampling_params)
    answers = [completion.outputs[0].text for completion in completions]

# 修改后: 使用 transformers 的 model.generate()
def sample(model, tokenizer, conversations, top_p=1, max_tokens=1000, temperature=1, min_tokens=1, lora_path=None, bs=20):
    tokenizer.padding_side = "left"
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        tokenizer.pad_token_id = tokenizer.eos_token_id
    prompts = [tokenizer.apply_chat_template(m, tokenize=False, add_generation_prompt=True) for m in conversations]
    outputs = []
    for i in trange(0, len(prompts), bs):
        batch = prompts[i:i+bs]
        tokenized_batch = tokenizer(batch, return_tensors="pt", padding=True)
        tokenized_batch = {k: v.to(model.device) for k, v in tokenized_batch.items()}
        with torch.no_grad():
            output = model.generate(**tokenized_batch, do_sample=(temperature > 0),
                temperature=temperature if temperature > 0 else None,
                top_p=top_p, max_new_tokens=max_tokens, use_cache=True, min_new_tokens=min_tokens)
        prompt_len = tokenized_batch["input_ids"].shape[1]
        output = [tokenizer.decode(o[prompt_len:], skip_special_tokens=True) for o in output]
        outputs.extend(output)
    return prompts, outputs
```

**⚠ 审查点 S1**: `temperature` 传参——当 `temperature=0` 时，原始 vLLM 使用 greedy decoding。修改后代码传 `do_sample=False, temperature=None`。`temperature=None` 在 transformers 中是否等价于 greedy？如果 transformers 默认 temperature=1.0 而非 None→greedy，所有 n_per_question=1 的运行（smoke test）都可能用了错误的采样策略。

**⚠ 审查点 S2**: `prompt_len` 截取逻辑——使用 `tokenized_batch["input_ids"].shape[1]`（padded batch 的最大长度）作为所有样本的 prompt 长度。但 left-padding 下，较短的 prompt 前面有 pad tokens。解码时用同一个 `prompt_len` 截取，短 prompt 的输出会包含部分 pad token 解码。**这可能导致生成文本前面出现垃圾字符。**

**⚠ 审查点 S3**: `min_new_tokens` vs `min_tokens`——vLLM 的 `SamplingParams(min_tokens=1)` 和 transformers 的 `min_new_tokens=1` 语义是否一致？

**修改 3: `main()` 函数中 coef==0 的模型加载路径**
```python
# 原始: coef==0 时使用 vLLM 模型
else:
    llm, tokenizer, lora_path = load_vllm_model(model)

# 修改后: coef==0 也使用 transformers 模型
else:
    llm, tokenizer = load_model(model)
    lora_path = None
```

**⚠ 审查点 S4**: `load_model()` 加载行为——`model_utils.py:load_model()` 的具体实现。它是否使用 `device_map="auto"`？如果是，coef==0 的 baseline/extraction 运行使用了 device_map（部分 CPU offload），而 coef!=0 的 steering 运行也是同一个 `load_model()`。这会导致 Stage 1/2 和 Stage 4/5 使用不同的推理路径吗？

**修改 4: `max_concurrent_judges` 默认值**
```python
# 原始: 100
# 修改后: 30
```

**修改 5: 移除 `load_vllm_model` import**
```python
# 原始
from eval.model_utils import load_model, load_vllm_model
# 修改后
from eval.model_utils import load_model
```

---

### 2.2 judge.py — 重试 + 空值处理

**文件**: `third_party/persona_vectors/judge.py`

**修改 1: 添加 import**
```python
import backoff
import openai as openai_module
```

**修改 2: `logprob_probs()` 完全重写**
```python
# 原始
async def logprob_probs(self, messages) -> dict:
    completion = await openai.chat.completions.create(model=self.model, messages=messages,
        max_tokens=1, temperature=0, logprobs=True, top_logprobs=20, seed=0)
    try:
        logprobs = completion.choices[0].logprobs.content[0].top_logprobs
    except IndexError:
        return {}
    result = {}
    for el in logprobs:
        result[el.token] = float(math.exp(el.logprob))
    return result

# 修改后
@backoff.on_exception(backoff.expo, (openai_module.APITimeoutError, openai_module.APIConnectionError), max_tries=5, max_time=120)
async def logprob_probs(self, messages) -> dict:
    try:
        completion = await openai.chat.completions.create(model=self.model, messages=messages,
            max_tokens=1, temperature=0, logprobs=True, top_logprobs=20, seed=0)
    except Exception as e:
        print(f"Judge API error: {e}")
        return {}
    try:
        if not completion.choices:
            return {}
        lp = completion.choices[0].logprobs
        if lp is None or not hasattr(lp, "content") or lp.content is None or len(lp.content) == 0:
            return {}
        logprobs = lp.content[0].top_logprobs
    except (IndexError, AttributeError, TypeError):
        return {}
    result = {}
    for el in logprobs:
        result[el.token] = float(math.exp(el.logprob))
    return result
```

**⚠ 审查点 J1**: **空 dict `{}` 的评分结果**——当 `logprob_probs` 返回 `{}` 时，`self.aggregate_score({})` 被调用。需要检查 `_aggregate_0_100_score({})` 的返回值。如果返回 `None`、`NaN`、或固定值（如 0 或 50），那么 DeepSeek API 偶发的空 logprobs 会在 CSV 中产生对应的异常值，静默污染统计结果。

**⚠ 审查点 J2**: **DeepSeek logprobs 兼容性**——PV 原始代码假设 judge 是 OpenAI GPT 系列（`gpt-4.1-mini-2025-04-14`），它们对 0-100 的每个整数 tokenize 为单 token。DeepSeek 的 tokenizer 是否有相同特性？如果 DeepSeek 把 "78" tokenize 为两个 token ("7" + "8")，那么 `max_tokens=1` 只会返回第一个 digit，`top_logprobs` 分布会完全错误。

**⚠ 审查点 J3**: **`seed=0` 在 DeepSeek 上的行为**——DeepSeek 可能不支持 `seed` 参数，会忽略或报错。需确认 judge 评分的可复现性。

---

### 2.3 generate_vec — 自定义脚本替代 CLI

**未修改 `generate_vec.py` 本身**，但 Stage 3 的实际执行未使用 `python generate_vec.py --model_name ... --pos_path ... --neg_path ...` CLI，而是使用了内联 Python 脚本（`/tmp/genvec_v5.py`）。

**差异**:

| 方面 | 原始 CLI | 自定义脚本 |
|------|---------|-----------|
| 模型加载 | `device_map="auto"` | `.to("cuda")` 直接加载 |
| hidden states | `output_hidden_states=True` 全模型 | 同上（v5 恢复使用 `output_hidden_states=True`） |
| 层范围 | 全部 29 层 (0-28) | 仅 14-24（11 层） |
| 保存的向量 | `prompt_avg_diff`, `response_avg_diff`, `prompt_last_diff` | 同上 |
| dict key | 层号 0-28 | 层号 14-24 |

**⚠ 审查点 V1**: **层号对齐**——原始 `generate_vec.py` 保存 dict key 为 `range(0, num_layers+1)` = 0-28。自定义脚本保存 key 为 14-24。Stage 5 steering 代码使用 `vector = torch.load(vector_path)[layer]`，其中 `layer=20`。如果 vector dict 的 key 是 14-24，`vector[20]` 可以正常取值。**但如果 key 类型不同（int vs str）或 off-by-one，会 KeyError 或取到错误层的向量。** 需验证。

**⚠ 审查点 V2**: **`output_hidden_states=True` 返回值的层号含义**——`model(**inputs, output_hidden_states=True).hidden_states` 返回 `(num_layers + 1)` 个 tensor：index 0 = embedding layer output，index 1 = layer 0 output，...，index 28 = layer 27 output。**如果自定义脚本用 `hidden_states[14]` 表示 "layer 14"，但实际是 layer 13 的输出（因为 index 0 是 embedding），那么提取和 steering 使用了不同的层。** 这是一个 off-by-one 风险。

**⚠ 审查点 V3**: **`get_persona_effective()` 的有效样本筛选逻辑**——原始 CLI 调用 `get_persona_effective(pos_path, neg_path, trait, threshold=50)`，筛选条件为：
```python
mask = (pos[trait] >= threshold) & (neg[trait] < 100-threshold) & (pos["coherence"] >= 50) & (neg["coherence"] >= 50)
```
注意：这是对**同位置**的 pos/neg 样本配对筛选。如果 pos CSV 和 neg CSV 的行顺序不同（不同问题/不同指令），配对可能是错误的。需确认 pos/neg CSV 的行对齐语义。

---

## 三、已知结果异常

### 3.1 Day 1 monotonic FAIL

| 条件 | optimistic 均值 |
|------|----------------|
| baseline | 82.9 |
| coef=2.0 | 100.0 |
| coef=3.5 | 100.0 |
| coef=-2.0 | 21.1 |
| coef=-3.5 | 4.5 |

coef=2.0 和 3.5 均达天花板 100.0。**需确认这不是 bug 导致的虚假满分**（例如 judge 总是返回 {} → aggregate 返回 100）。

### 3.2 Day 2 极性异常

| Trait | pos 均值 | neg 均值 |
|-------|---------|---------|
| openness | 100.0 | 100.0 |
| neuroticism | 0.8 | 0.1 |

**需确认**: 这是 eval_prompt 质量问题，还是 judge/scoring 管道 bug？如果 aggregate_score({}) 返回 100，那么 openness 的 100/100 可能是大量空 logprobs 导致的虚假结果。

---

## 四、需要审查的文件路径

| 文件 | Mac 路径 | 审查重点 |
|------|---------|---------|
| eval_persona.py (modified) | 云端已修改，Mac 端原始版在 `abcr/third_party/persona_vectors/eval/eval_persona.py`（如果有的话） | S1-S4 |
| judge.py (modified) | 同上 | J1-J3 |
| model_utils.py | `abcr/third_party/persona_vectors/eval/model_utils.py`（未修改，但 load_model 行为影响全局） | S4 |
| generate_vec.py | `abcr/third_party/persona_vectors/generate_vec.py`（未修改，但 hidden_states 索引逻辑影响 V1-V2） | V1-V3 |
| prompts.py | `abcr/third_party/persona_vectors/eval/prompts.py`（coherence 评估 prompt） | — |
| activation_steer.py | `abcr/third_party/persona_vectors/activation_steer.py`（steering hook 逻辑，layer_idx=layer-1） | V1-V2 |
| 产物 CSV | `abcr/cloud-results/cloud-day1/*.csv` | 抽样检查异常值 |
| 产物向量 | `abcr/cloud-results/cloud-day1/vectors/*.pt` | V1 key 验证 |
| ABCR trait data | `abcr/artifacts/traits/{conscientiousness,openness,neuroticism}/extract.json` | eval_prompt 质量 |

---

## 五、建议审查方法

### 优先级 P0（数据可能已被静默污染）

1. **J1 + 3.1/3.2 联合验证**: 读取 `judge.py` 的 `_aggregate_0_100_score` 方法，确定 `aggregate_score({})` 的返回值。然后在 Day 1 CSV 中搜索该值的出现频率。如果高频出现，说明大量 judge 评分是无效的。

2. **V2 off-by-one**: 读取 `generate_vec.py` 的 `get_hidden_p_and_r` 函数和 `activation_steer.py` 的 `ActivationSteerer.__init__`，确认 hidden_states 索引和 steering hook 的 `layer_idx` 是否使用相同的层号语义。

3. **S2 padding 截取**: 在修改后的 `sample()` 中，验证 left-padding 下的 `prompt_len` 截取是否正确。构造一个 2 样本 batch，一短一长，检查短样本的输出是否包含 pad token 解码残留。

### 优先级 P1（可能影响结果质量但不一定致命）

4. **J2 DeepSeek tokenizer**: 验证 DeepSeek 是否将 0-100 的整数 tokenize 为单 token。可通过调 API 检查 `top_logprobs` 返回的 token 格式。

5. **S1 temperature=0 行为**: 确认 transformers 在 `do_sample=False, temperature=None` 时的行为与 vLLM 的 greedy decoding 一致。

6. **V3 pos/neg 行对齐**: 确认 extraction 时 pos CSV 和 neg CSV 的行是否按 (question_id, instruction_id) 一一对应。

### 优先级 P2（记录但可接受）

7. **S4 load_model 实现**: 确认 `load_model()` 的 dtype 和 device 行为。
8. **J3 seed 参数**: 确认 DeepSeek 是否支持 seed。
9. **向量 .pt 文件的 key 类型**: `torch.load` 后检查 key 是 int 还是其他类型。

---

## 六、快速验证命令（Mac 端可执行）

```bash
# 检查产物向量的 key
python -c "
import torch
t = torch.load('abcr/cloud-results/cloud-day1/vectors/optimistic_response_avg_diff.pt', weights_only=False)
print('Keys:', sorted(t.keys()))
print('Key types:', type(list(t.keys())[0]))
print('Layer 20 shape:', t[20].shape if 20 in t else 'MISSING')
"

# 检查 Day1 CSV 中 optimistic 列的异常值分布
python -c "
import pandas as pd
for f in ['optimistic_pos_extract', 'optimistic_neg_extract', 'optimistic_baseline_eval']:
    df = pd.read_csv(f'abcr/cloud-results/cloud-day1/{f}.csv')
    col = 'optimistic'
    null_count = df[col].isna().sum()
    zero_count = (df[col] == 0).sum()
    hundred_count = (df[col] == 100).sum()
    print(f'{f}: rows={len(df)}, null={null_count}, ==0: {zero_count}, ==100: {hundred_count}')
"

# 检查 aggregate_score({}) 的返回值
python -c "
import sys; sys.path.insert(0, 'abcr/third_party/persona_vectors')
from judge import OpenAiJudge
j = OpenAiJudge.__new__(OpenAiJudge)
j.eval_type = '0_100'
j.aggregate_score = j._aggregate_0_100_score
print('aggregate_score({}) =', j._aggregate_0_100_score({}))
"
```

---

## 七、判定标准

- **P0 任一确认为 bug** → 对应阶段产物作废，需重跑。
- **P0 全部排除** → W1 基础设施可信，产物可用于后续实验。
- **P1 发现问题** → 记入 DEVIATIONS，评估影响范围，决定是否需要补跑。
