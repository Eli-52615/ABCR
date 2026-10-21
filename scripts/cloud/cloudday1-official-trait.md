# Cloud Day 1: Official Trait Full-Scale (7B bf16, optimistic)

> **执行者**：租到 24GB GPU 卡的人。零思考照抄，不需要读其他文档。
> **前提**：Mac 开发全绿（S2 方向复现检通过）；DeepSeek key 在手。
> **预算**：¥150 上限（E16 熔断——超线立即关机，记账后提 STATUS-B 升级申请）。

---

## ① Provision 检查单

```bash
# 确认 GPU 规格
nvidia-smi
# 期望: ≥24GB VRAM (4090/A5000/L20/A100 均可), CUDA ≥12.1

# 记账（立即执行，不等跑完）
cat >> costs/ledger.jsonl << EOF
{"ts":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","provider":"<填>","instance":"<填>","rate_cny_h":<填>,"purpose":"cloudday1-official-optimistic-7b"}
EOF

# 预估总时长（7B 全量约 2-3h 推理 + judge），留 30min 余量
# 算成本：预估时长(h) × rate_cny_h ≤ 120（留 ¥30 给 day2）
```

## ② 环境

```bash
# 克隆仓库（Mac → 云的传输方式自定义，此处假设 scp/rsync）
cd /workspace/abcr

# 官方 PV 依赖（全量含 vLLM）
cd third_party/persona_vectors
pip install -r requirements.txt
# 验证 vLLM
python -c "from vllm import LLM; print('vLLM OK')"

# 主 venv 依赖（judge 需要）
pip install openai==1.70.0 backoff==2.2.1 pyyaml==6.0.2

# 模型下载（7B，HF 直连，Qwen 不 gated）
python -c "
from transformers import AutoModelForCausalLM, AutoTokenizer
m = AutoModelForCausalLM.from_pretrained('Qwen/Qwen2.5-7B-Instruct', torch_dtype='auto')
t = AutoTokenizer.from_pretrained('Qwen/Qwen2.5-7B-Instruct')
print(f'Loaded: {m.config.num_hidden_layers} layers, {m.config.hidden_size} hidden')
"
# 记录 revision（snapshot sha）→ 更新 configs/models.yaml
python -c "
from huggingface_hub import model_info
info = model_info('Qwen/Qwen2.5-7B-Instruct')
print(f'revision: {info.sha[:12]}')
# 手动更新 configs/models.yaml 的 PIN-AT-CLOUD-PROVISION 行
"

# 密钥注入（每个 shell 执行一次）
export OPENAI_API_KEY=$(cat /path/to/deepseek.key)
export OPENAI_BASE_URL=https://api.deepseek.com
# 验证
python -c "from openai import OpenAI; print(OpenAI().chat.completions.create(model='deepseek-chat', messages=[{'role':'user','content':'hi'}], max_tokens=3).choices[0].message.content)"
```

## ③ 5% Smoke（不过即关机排障）

```bash
cd /workspace/abcr/third_party/persona_vectors

# 单指令 × 2 题 × 1 响应 × 双极 = 4 生成 + 4 judge
python -m eval.eval_persona \
  --model Qwen/Qwen2.5-7B-Instruct \
  --trait optimistic \
  --version extract \
  --persona_instruction_type pos \
  --assistant_name optimistic \
  --judge_model deepseek-chat \
  --n_per_question 1 \
  --output_path /tmp/smoke_pos.csv \
  2>&1 | tee /tmp/smoke_pos.log

# 检查：CSV 非空、judge 分数列有数值
python -c "
import pandas as pd
df = pd.read_csv('/tmp/smoke_pos.csv')
print(f'Rows: {len(df)}, trait col non-null: {df[\"optimistic\"].notna().sum()}')
assert len(df) >= 2, 'Smoke FAIL: too few rows'
assert df['optimistic'].notna().sum() > 0, 'Smoke FAIL: judge returned all None'
print('SMOKE PASS')
"
# 如果 FAIL → 关机，不跑全量
```

## ④ 五阶段全量

```bash
cd /workspace/abcr/third_party/persona_vectors
TRAIT=optimistic
MODEL=Qwen/Qwen2.5-7B-Instruct
JUDGE=deepseek-chat
OUT=/workspace/abcr/runs/cloud-day1

mkdir -p $OUT

# --- Stage 1: pos 抽取 ---
python -m eval.eval_persona \
  --model $MODEL --trait $TRAIT --version extract \
  --persona_instruction_type pos --assistant_name $TRAIT \
  --judge_model $JUDGE --n_per_question 10 \
  --output_path $OUT/${TRAIT}_pos_extract.csv \
  2>&1 | tee $OUT/log_pos_extract.txt
echo "[$(date)] Stage 1 pos DONE"

# --- Stage 2: neg 抽取 ---
python -m eval.eval_persona \
  --model $MODEL --trait $TRAIT --version extract \
  --persona_instruction_type neg --assistant_name helpful \
  --judge_model $JUDGE --n_per_question 10 \
  --output_path $OUT/${TRAIT}_neg_extract.csv \
  2>&1 | tee $OUT/log_neg_extract.txt
echo "[$(date)] Stage 2 neg DONE"

# --- Stage 3: generate_vec ---
python generate_vec.py \
  --model_name $MODEL \
  --pos_path $OUT/${TRAIT}_pos_extract.csv \
  --neg_path $OUT/${TRAIT}_neg_extract.csv \
  --trait $TRAIT \
  --save_dir $OUT/vectors/ \
  --threshold 50 \
  --dtype bfloat16 \
  2>&1 | tee $OUT/log_generate_vec.txt
echo "[$(date)] Stage 3 vec DONE"
# 验证产物
python -c "
import torch, os
for f in os.listdir('$OUT/vectors/'):
    if f.endswith('.pt'):
        t = torch.load(f'$OUT/vectors/{f}')
        print(f'{f}: shape={t.shape}, finite={t.isfinite().all()}')
"

# --- Stage 4: baseline eval ---
python -m eval.eval_persona \
  --model $MODEL --trait $TRAIT --version eval \
  --steering_type response --coef 0 \
  --judge_model $JUDGE \
  --output_path $OUT/${TRAIT}_baseline_eval.csv \
  2>&1 | tee $OUT/log_baseline_eval.txt
echo "[$(date)] Stage 4 baseline DONE"

# --- Stage 5: steering eval (扫 coef) ---
# 从 generate_vec 输出确定层号（Mac dev 推荐层或取中间层）
LAYER=20  # 先用 Mac dev recommended; 实际按 card.json 调
for COEF in 2.0 3.5 -2.0 -3.5; do
  python -m eval.eval_persona \
    --model $MODEL --trait $TRAIT --version eval \
    --steering_type response --coef $COEF \
    --vector_path "$OUT/vectors/${TRAIT}_response_avg_diff.pt" \
    --layer $LAYER \
    --judge_model $JUDGE \
    --output_path "$OUT/${TRAIT}_steer_L${LAYER}_c${COEF}_eval.csv" \
    2>&1 | tee "$OUT/log_steer_L${LAYER}_c${COEF}.txt"
  echo "[$(date)] Stage 5 coef=$COEF DONE"
done

# --- Stage 5b: cal_projection (W2 前置验证) ---
python -m eval.cal_projection \
  --model $MODEL \
  --vector_path "$OUT/vectors/${TRAIT}_response_avg_diff.pt" \
  --layer $LAYER \
  --output_path "$OUT/${TRAIT}_projection.csv" \
  2>&1 | tee $OUT/log_cal_projection.txt || echo "cal_projection not available (non-blocking)"
echo "[$(date)] Projection DONE (or skipped)"
```

## ⑤ 对表校准检查单

逐条手动检查并填入结论：

| # | 检查项 | 通过标准 | 结果 |
|---|--------|----------|------|
| 1 | trait 分随 coef>0 上升 | mean(coef=3.5) > mean(baseline) + 10 | ☐ |
| 2 | trait 分随 coef<0 下降 | mean(coef=-3.5) < mean(baseline) - 10 | ☐ |
| 3 | 方向单调 | coef=3.5 > coef=2.0 > baseline > coef=-2.0 > coef=-3.5 | ☐ |
| 4 | coherence 未崩 | 所有条件 coherence 均值 ≥50 | ☐ |
| 5 | 与论文方向一致 | optimistic: pos=乐观/neg=悲观 | ☐ |
| 6 | 无全零/全百 | 无条件的 trait 分中位数 ∈ [5, 95] | ☐ |

如有未通过项 → 记录数据 + 假设写入 STATUS-B，不继续下一步。

## ⑥ 翻转 Demo 录制

```bash
# 选 eval.json 前 3 题，用推荐 coef 的 ± 值
# 并排展示 baseline / +coef / -coef 生成文本 + trait 分
# 录屏 60-120 秒（用 asciinema 或 screen record）

# 简易文本 demo（备选）：
python -c "
import pandas as pd
bl = pd.read_csv('$OUT/${TRAIT}_baseline_eval.csv')
pos = pd.read_csv('$OUT/${TRAIT}_steer_L${LAYER}_c3.5_eval.csv')
neg = pd.read_csv('$OUT/${TRAIT}_steer_L${LAYER}_c-3.5_eval.csv')
for i in range(min(3, len(bl))):
    print(f'=== Q{i+1}: {bl.iloc[i][\"question\"][:80]} ===')
    print(f'  Baseline ({bl.iloc[i][\"optimistic\"]:.0f}): {bl.iloc[i][\"answer\"][:200]}')
    print(f'  +coef   ({pos.iloc[i][\"optimistic\"]:.0f}): {pos.iloc[i][\"answer\"][:200]}')
    print(f'  -coef   ({neg.iloc[i][\"optimistic\"]:.0f}): {neg.iloc[i][\"answer\"][:200]}')
    print()
" | tee $OUT/flip_demo.txt
```

## ⑦ Parity 烟检（vLLM vs transformers）

```bash
# 20 题 temperature=0：官方 vLLM sample() vs transformers sample_steering(coef=0)
# 逐题比较 token 序列一致率

python << 'PARITY_EOF'
import pandas as pd
from eval.eval_persona import load_persona_questions
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

MODEL = "Qwen/Qwen2.5-7B-Instruct"
TRAIT = "optimistic"

# Load questions (eval set, first 20)
questions = load_persona_questions(TRAIT, version="eval", persona_instruction_type="pos", assistant_name=TRAIT)[:20]

tokenizer = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.bfloat16, device_map="auto")
model.eval()

results = []
for q in questions:
    conv = q.conversation
    rendered = tokenizer.apply_chat_template(conv, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(rendered, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=100, do_sample=False, temperature=None, use_cache=True)
    answer_tf = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    results.append({"question": q.question[:100], "answer_transformers": answer_tf[:200]})

df_tf = pd.DataFrame(results)

# Compare with vLLM output (if already generated in stage 4 baseline with temp=0)
# Note: official eval uses temp=1 n=10, so parity must be separate run
from vllm import LLM, SamplingParams
llm = LLM(model=MODEL, dtype="bfloat16")
params = SamplingParams(temperature=0, max_tokens=100)

convs = [tokenizer.apply_chat_template(q.conversation, tokenize=False, add_generation_prompt=True) for q in questions]
outputs = llm.generate(convs, params)
df_tf["answer_vllm"] = [o.outputs[0].text[:200] for o in outputs]
df_tf["match"] = df_tf["answer_transformers"] == df_tf["answer_vllm"]

match_rate = df_tf["match"].mean()
print(f"Parity: {match_rate*100:.1f}% exact match ({df_tf['match'].sum()}/{len(df_tf)})")
df_tf.to_csv("/workspace/abcr/runs/cloud-day1/parity_smoke.csv", index=False)

# 分歧样例
diverge = df_tf[~df_tf["match"]]
if len(diverge) > 0:
    print(f"\nDivergences ({len(diverge)}):")
    for _, row in diverge.head(5).iterrows():
        print(f"  Q: {row['question'][:60]}")
        print(f"    TF:   {row['answer_transformers'][:80]}")
        print(f"    vLLM: {row['answer_vllm'][:80]}")
PARITY_EOF
```

## ⑧ 产物回传

```bash
OUT=/workspace/abcr/runs/cloud-day1

# 打包
cd /workspace/abcr
tar czf /tmp/cloud-day1-results.tar.gz runs/cloud-day1/
sha256sum /tmp/cloud-day1-results.tar.gz | tee /tmp/cloud-day1-sha256.txt

# 回传 Mac（替换为实际 IP/路径）
scp /tmp/cloud-day1-results.tar.gz user@mac-ip:~/abcr/
scp /tmp/cloud-day1-sha256.txt user@mac-ip:~/abcr/

# Mac 端验证
# sha256sum -c cloud-day1-sha256.txt
# tar xzf cloud-day1-results.tar.gz
```

## ⑨ 关机断言 + 记账

```bash
# 确认所有产物存在
ls $OUT/${TRAIT}_pos_extract.csv \
   $OUT/${TRAIT}_neg_extract.csv \
   $OUT/vectors/${TRAIT}_response_avg_diff.pt \
   $OUT/${TRAIT}_baseline_eval.csv \
   $OUT/${TRAIT}_steer_L*_c*_eval.csv \
   $OUT/parity_smoke.csv

# 记账收笔
HOURS_USED=$(echo "scale=2; ($(date +%s) - $START_TS) / 3600" | bc)
COST=$(echo "scale=2; $HOURS_USED * $RATE" | bc)
echo "Total: ${HOURS_USED}h × ¥${RATE}/h = ¥${COST}"

# E16 检查
python -c "
cost = $COST
budget = 150
assert cost <= budget, f'E16 BUDGET EXCEEDED: ¥{cost} > ¥{budget}. STOP.'
print(f'Budget OK: ¥{cost}/{budget} ({cost/budget*100:.0f}%)')
"

# 追加 ledger
cat >> costs/ledger.jsonl << EOF
{"ts":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","event":"cloudday1-complete","hours":$HOURS_USED,"cost_cny":$COST,"remaining_cny":$(echo "150-$COST"|bc)}
EOF

# 关机
echo "All done. Shutting down."
sudo shutdown -h now
```

---

## 故障处理

| 症状 | 动作 |
|------|------|
| vLLM 安装失败 | `pip install vllm==0.8.5.post1`；CUDA 版本不匹配换 `pip install vllm --no-build-isolation` |
| Judge 返回全 None | 检查 OPENAI_BASE_URL 是否含尾 `/`（不应有）；检查 key 有效性 |
| OOM (7B bf16) | 确认未开其他 GPU 进程；vLLM 加 `--gpu-memory-utilization 0.95` |
| 生成速度极慢 | 确认 `nvidia-smi` 显示 GPU 利用率 >80%；否则 CPU offload 检查 |
| generate_vec 过滤后空集 | threshold 从 50 降至 30 并记 DEVIATIONS |
| 预算超 ¥120 还没跑完 | 立即停止，已有产物打包回传，STATUS-B 标 PARTIAL |
