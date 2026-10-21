# BRIDGE-FIDELITY: 官方 persona_vectors extract 语义 → pv_bridge 保真度记录

> 钉版 commit: b8e0f044fe2410a6fad579f38324f03f13b4e917
> 本文逐条记录官方 extract 流程的精确语义，桥的每一处实现必须能指回本文件的一条记录。

## 1. System Prompt 组装（eval/eval_persona.py:137-155）

- `load_persona_questions(trait, version="extract", persona_instructions_type=pos|neg, assistant_name=<name>)` 
- trait_data = `data_generation/trait_data_extract/{trait}.json`
- 每个 question × 每个 instruction（5个）生成一个 Question 对象
- system prompt 模板（L154）：`"You are {a_or_an(assistant_name)} {assistant_name} assistant. {instruction}"`
  - `a_or_an(word)` (L134): 首字母 aeiou 用 "an"，否则 "a"
  - `assistant_name` 默认逻辑（L150-153）：pos 极 → `assistant_name=trait`（如 "optimistic"），neg 极 → `assistant_name="helpful"`
- conversation = `[{"role":"system","content":system}, {"role":"user","content":question}]`

## 2. 生成参数（eval/eval_persona.py:240,252-255）

- `n_per_question=10` (main 默认值 L240)
- `temperature`: n_per_question==1 时 temperature=0.0，否则 1.0 (L252-255)
- `max_tokens=1000` (L240 默认)
- `min_tokens=1` (sample 默认 L58)
- `top_p=1` (sample 默认 L58)
- extract 版本使用 vLLM `sample()` (L262, coef=0 路径)

## 3. 模板渲染（eval/eval_persona.py:69-70,41）

- `tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)`
- **CSV `prompt` 列 = 渲染后全文**（L69-70：`texts.append(tokenizer.apply_chat_template(...))`），generate_vec.py 依赖此语义
- 这也是 sample_steering (L41) 中的渲染方式

## 4. Judge 评分（eval/eval_persona.py:106,125-130）

- 每个 question 有两个 judge (L106)：
  - `trait` judge: 使用 trait_data["eval_prompt"] 模板
  - `coherence` judge: 使用 `eval.prompts.Prompts["coherence_0_100"]`
- judge 模型: `gpt-4.1-mini-2025-04-14` (默认 L240; 本项目替换为 `deepseek-chat`)
- eval_type: `0_100` (默认 L240)

## 5. Judge 内部机制（judge.py:17-70）

- `OpenAiJudge.__init__`: model, prompt_template, eval_type
- `judge()` (L39-47):
  - 非 binary_text: `logprob_probs()` → `_aggregate_0_100_score()`
  - binary_text: `query_full_text()` → `_aggregate_binary_text_score()`
- `logprob_probs()` (L49-70):
  - `max_tokens=1, temperature=0, logprobs=True, top_logprobs=20, seed=0`
  - 返回 {token: exp(logprob)} 字典
- `_aggregate_0_100_score()` (L85-103):
  - 遍历 logprobs，过滤 int key ∈ [0,100]
  - 加权平均 = sum(key * prob) / sum(prob)
  - total < 0.25 → None (视为 refusal)

## 6. CSV 输出格式（eval/eval_persona.py:121-131）

- 列：`question, prompt, answer, question_id, {trait}, coherence`
- `question_id` = `{trait}_{i}_{persona_instructions_type}_{k}` (extract 版)
- `prompt` = 渲染后全文（与 generate_vec.py 输入语义一致）

## 7. config.py 执行时机（judge.py:9-13）

- `from config import setup_credentials` → `config = setup_credentials()` → `openai = AsyncOpenAI()`
- **import judge 时即执行** setup_credentials() 和 AsyncOpenAI()
- 因此 import judge 前必须先设 OPENAI_API_KEY 和 OPENAI_BASE_URL

## 8. generate_vec.py 输入契约（generate_vec.py:40-54,57-58）

- `get_persona_effective()`: 读 pos/neg CSV
  - 过滤: `pos[trait] >= threshold & neg[trait] < 100-threshold & pos.coherence >= 50 & neg.coherence >= 50`
  - threshold 默认 50
- `save_persona_vector()` (L57-58):
  - `AutoModelForCausalLM.from_pretrained(model_name, device_map="auto")`
  - **未传 torch_dtype → 默认 fp32**（补丁目的）
  - 输出三文件：`{trait}_{prompt_avg|response_avg|prompt_last}_diff.pt`

## 9. 桥与官方的偏差声明

| 偏差点 | 官方 | 桥 | 理由 |
|---|---|---|---|
| 生成引擎 | vLLM sample() | transformers generate() | Mac 无 vLLM |
| judge 模型 | gpt-4.1-mini | deepseek-chat | 项目级替换 F8 |
| HF_TOKEN | 强制 | 可选 | patch: pv-config-hftoken-optional |
| dtype | 未指定(fp32) | 显式 --dtype | patch: pv-generate-vec-dtype |
| temperature | 1.0 (n>1) | 同 | 保真 |
| n_per_question | 10 | 2 (Mac 止损) | 资源限制 |

> 每一处桥实现必须能指回本文件的一条记录编号。
