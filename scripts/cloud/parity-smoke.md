# Parity Smoke: vLLM vs Transformers (独立版)

> 独立执行版——当 Cloud Day 1 时间不够时，单独租卡跑此检查。
> 目的：验证 Mac bridge（transformers）与官方推理路径（vLLM）的生成一致性。
> 预计用时：30-60 分钟（含环境准备）。

---

## 前提

- 24GB GPU + CUDA ≥12.1
- `third_party/persona_vectors` 已就位（pip install -r requirements.txt 完成）
- 模型已下载（Qwen/Qwen2.5-7B-Instruct）

## 执行

```bash
cd /workspace/abcr/third_party/persona_vectors
export OPENAI_API_KEY=$(cat /path/to/deepseek.key)
export OPENAI_BASE_URL=https://api.deepseek.com

MODEL=Qwen/Qwen2.5-7B-Instruct
TRAIT=optimistic
OUT=/workspace/abcr/runs/parity-smoke
mkdir -p $OUT

python << 'EOF'
import sys, torch, pandas as pd
sys.path.insert(0, ".")
from eval.eval_persona import load_persona_questions
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "Qwen/Qwen2.5-7B-Instruct"
TRAIT = "optimistic"
N_QUESTIONS = 20

# --- Transformers path (Mac bridge equivalent) ---
print("=== Transformers generation (temp=0, greedy) ===")
tokenizer = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.bfloat16, device_map="auto")
model.eval()

questions = load_persona_questions(TRAIT, version="eval", persona_instruction_type="pos", assistant_name=TRAIT)[:N_QUESTIONS]

tf_answers = []
for q in questions:
    conv = q.conversation
    rendered = tokenizer.apply_chat_template(conv, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(rendered, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=100, do_sample=False, use_cache=True)
    answer = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    tf_answers.append(answer)
print(f"Transformers: {len(tf_answers)} answers generated")

del model
torch.cuda.empty_cache()

# --- vLLM path (official) ---
print("\n=== vLLM generation (temp=0, greedy) ===")
from vllm import LLM, SamplingParams

llm = LLM(model=MODEL, dtype="bfloat16")
params = SamplingParams(temperature=0, max_tokens=100)

prompts = []
for q in questions:
    rendered = tokenizer.apply_chat_template(q.conversation, tokenize=False, add_generation_prompt=True)
    prompts.append(rendered)

outputs = llm.generate(prompts, params)
vllm_answers = [o.outputs[0].text for o in outputs]
print(f"vLLM: {len(vllm_answers)} answers generated")

# --- Compare ---
print("\n=== Parity Results ===")
results = []
for i, (q, tf_a, vl_a) in enumerate(zip(questions, tf_answers, vllm_answers)):
    exact_match = tf_a.strip() == vl_a.strip()
    # Token-level comparison (first 50 tokens)
    tf_toks = tokenizer.encode(tf_a)[:50]
    vl_toks = tokenizer.encode(vl_a)[:50]
    min_len = min(len(tf_toks), len(vl_toks))
    token_match = sum(1 for a, b in zip(tf_toks[:min_len], vl_toks[:min_len]) if a == b) / max(min_len, 1)
    
    results.append({
        "question": q.question[:100],
        "exact_match": exact_match,
        "token_match_rate": round(token_match, 3),
        "answer_transformers": tf_a[:300],
        "answer_vllm": vl_a[:300],
    })

df = pd.DataFrame(results)
exact_rate = df["exact_match"].mean()
token_rate = df["token_match_rate"].mean()

print(f"Exact match: {exact_rate*100:.1f}% ({df['exact_match'].sum()}/{len(df)})")
print(f"Token match (first 50): {token_rate*100:.1f}%")
print(f"\nDivergences:")
for _, row in df[~df["exact_match"]].head(5).iterrows():
    print(f"  Q: {row['question'][:60]}")
    print(f"    TF:   {row['answer_transformers'][:100]}")
    print(f"    vLLM: {row['answer_vllm'][:100]}")

df.to_csv("/workspace/abcr/runs/parity-smoke/parity_results.csv", index=False)
print(f"\nSaved: /workspace/abcr/runs/parity-smoke/parity_results.csv")

# Verdict
if exact_rate >= 0.8:
    print("\n✓ PARITY PASS (≥80% exact match)")
elif token_rate >= 0.95:
    print("\n~ PARITY MARGINAL (token-level ≥95%, some rounding divergence expected)")
else:
    print("\n✗ PARITY CONCERN — investigate bf16 vs fp32 or sampling differences")
EOF
```

## 可选：VLLM_BATCH_INVARIANT 对照

```bash
# 验证 vLLM batch size 不影响输出（确定性 greedy 应一致）
python << 'EOF'
from vllm import LLM, SamplingParams

MODEL = "Qwen/Qwen2.5-7B-Instruct"
llm = LLM(model=MODEL, dtype="bfloat16")
params = SamplingParams(temperature=0, max_tokens=50)

# 准备 10 条相同 prompt
prompt = "<|im_start|>system\nYou are helpful.<|im_end|>\n<|im_start|>user\nWhat is 2+2?<|im_end|>\n<|im_start|>assistant\n"
prompts = [prompt] * 10

# batch=10
out_batch = llm.generate(prompts, params)
answers_batch = [o.outputs[0].text for o in out_batch]

# single
answers_single = []
for p in prompts[:3]:
    out = llm.generate([p], params)
    answers_single.append(out[0].outputs[0].text)

# Compare
print(f"All batch answers identical: {len(set(answers_batch)) == 1}")
print(f"Batch vs single match: {answers_batch[0] == answers_single[0]}")
if answers_batch[0] == answers_single[0]:
    print("✓ BATCH INVARIANT CONFIRMED")
else:
    print("⚠ BATCH DIVERGENCE — flag for investigation")
    print(f"  Batch: {answers_batch[0][:100]}")
    print(f"  Single: {answers_single[0][:100]}")
EOF
```

## 回传

```bash
tar czf /tmp/parity-smoke.tar.gz -C /workspace/abcr runs/parity-smoke/
sha256sum /tmp/parity-smoke.tar.gz
scp /tmp/parity-smoke.tar.gz user@mac-ip:~/abcr/
```
