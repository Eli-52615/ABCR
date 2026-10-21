# Cloud Day 2: Anchor Traits Full-Scale (7B bf16, conscientiousness/openness/neuroticism)

> **前提**：Cloud Day 1 全绿 + 工件 review_status=approved（楠确认 REVIEW-REQUEST）。
> **预算**：¥150 总额减去 Day 1 消耗 = 剩余额度（查 costs/ledger.jsonl 最后一行 remaining_cny）。
> **产物**：3 trait 的 citable 级向量 + 表达检生成素材（供 C 正式盲评）。

---

## ① Provision + 环境复用

```bash
# 同 Day 1 provision 检查单（GPU ≥24GB, CUDA ≥12.1）
nvidia-smi

# 如果复用同一台机器，环境已就绪；否则重复 Day 1 ② 步骤
# 确认 vLLM + judge 可用
python -c "from vllm import LLM; print('OK')"

# 密钥注入
export OPENAI_API_KEY=$(cat /path/to/deepseek.key)
export OPENAI_BASE_URL=https://api.deepseek.com

# 记账开始
cat >> costs/ledger.jsonl << EOF
{"ts":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","provider":"<填>","instance":"<填>","rate_cny_h":<填>,"purpose":"cloudday2-anchor-traits-7b"}
EOF
```

## ② 三 Trait 全量抽取（官方规格 n_per_question=10）

```bash
MODEL=Qwen/Qwen2.5-7B-Instruct
JUDGE=deepseek-chat
OUT=/workspace/abcr/runs/cloud-day2

mkdir -p $OUT

for TRAIT in conscientiousness openness neuroticism; do
  echo "=== $TRAIT extraction ==="
  
  # pos 抽取
  python -m eval.eval_persona \
    --model $MODEL --trait $TRAIT --version extract \
    --persona_instruction_type pos --assistant_name $TRAIT \
    --judge_model $JUDGE --n_per_question 10 \
    --output_path $OUT/${TRAIT}_pos_extract.csv \
    2>&1 | tee $OUT/log_${TRAIT}_pos.txt
  
  # neg 抽取
  python -m eval.eval_persona \
    --model $MODEL --trait $TRAIT --version extract \
    --persona_instruction_type neg --assistant_name helpful \
    --judge_model $JUDGE --n_per_question 10 \
    --output_path $OUT/${TRAIT}_neg_extract.csv \
    2>&1 | tee $OUT/log_${TRAIT}_neg.txt
  
  echo "[$(date)] $TRAIT extraction DONE"
done
```

## ③ 向量生成

```bash
for TRAIT in conscientiousness openness neuroticism; do
  python generate_vec.py \
    --model_name $MODEL \
    --pos_path $OUT/${TRAIT}_pos_extract.csv \
    --neg_path $OUT/${TRAIT}_neg_extract.csv \
    --trait $TRAIT \
    --save_dir $OUT/vectors/${TRAIT}/ \
    --threshold 50 \
    --dtype bfloat16 \
    2>&1 | tee $OUT/log_${TRAIT}_vec.txt
  
  # 验证
  python -c "
import torch, os
d = '$OUT/vectors/$TRAIT'
for f in os.listdir(d):
    if f.endswith('.pt'):
        t = torch.load(f'{d}/{f}')
        print(f'  {f}: shape={t.shape}, finite={t.isfinite().all()}')
"
  echo "[$(date)] $TRAIT vector DONE"
done
```

## ④ 表达检生成素材（供 C 正式盲评）

```bash
# 每 trait: eval.json 20 题 × {baseline, +coef, -coef} × 2 响应 = 120 生成
# 用 Day 1 确定的推荐层和系数（或 Mac dev card.recommended）

for TRAIT in conscientiousness openness neuroticism; do
  # 读 recommended 层/系数（从 Mac dev card.json 或 Day 1 结果）
  # LAYER=<填>  COEF=<填>
  # 如果 Mac dev 不可用，取 layer=中间层(14), coef=3.0 作为保守值
  LAYER=${LAYER:-14}
  COEF=${COEF:-3.0}
  
  VEC_PATH="$OUT/vectors/${TRAIT}/${TRAIT}_response_avg_diff.pt"
  
  # baseline (coef=0)
  python -m eval.eval_persona \
    --model $MODEL --trait $TRAIT --version eval \
    --steering_type response --coef 0 \
    --judge_model $JUDGE --n_per_question 2 \
    --output_path $OUT/${TRAIT}_exprcheck_baseline.csv
  
  # +coef
  python -m eval.eval_persona \
    --model $MODEL --trait $TRAIT --version eval \
    --steering_type response --coef $COEF \
    --vector_path $VEC_PATH --layer $LAYER \
    --judge_model $JUDGE --n_per_question 2 \
    --output_path $OUT/${TRAIT}_exprcheck_pos.csv
  
  # -coef
  python -m eval.eval_persona \
    --model $MODEL --trait $TRAIT --version eval \
    --steering_type response --coef -$COEF \
    --vector_path $VEC_PATH --layer $LAYER \
    --judge_model $JUDGE --n_per_question 2 \
    --output_path $OUT/${TRAIT}_exprcheck_neg.csv
  
  echo "[$(date)] $TRAIT exprcheck素材 DONE"
done

# 混池乱序 + 盲化（去条件标签）
python << 'BLINDEOF'
import pandas as pd, hashlib, random, json, pathlib

OUT = pathlib.Path("/workspace/abcr/runs/cloud-day2")
SEED = 42

for trait in ["conscientiousness", "openness", "neuroticism"]:
    pool = []
    for cond, suffix in [("baseline", "baseline"), ("steered_pos", "pos"), ("steered_neg", "neg")]:
        df = pd.read_csv(OUT / f"{trait}_exprcheck_{suffix}.csv")
        for _, row in df.iterrows():
            pool.append({"question": row["question"], "answer": row["answer"], "condition": cond})
    
    random.seed(SEED)
    random.shuffle(pool)
    
    # Blind pool (no condition labels)
    blind = pd.DataFrame([{"sample_id": f"{trait}_{i:04d}", "question": r["question"], "answer": r["answer"]} for i, r in enumerate(pool)])
    key = pd.DataFrame([{"sample_id": f"{trait}_{i:04d}", "condition": r["condition"]} for i, r in enumerate(pool)])
    
    out_dir = OUT / "exprcheck" / trait
    out_dir.mkdir(parents=True, exist_ok=True)
    blind.to_csv(out_dir / "exprcheck_pool.csv", index=False)
    key.to_csv(out_dir / "exprcheck_key.csv", index=False)
    print(f"{trait}: pool={len(blind)} samples, key written")

BLINDEOF
```

## ⑤ 小系数扫描 + 激活抽样

```bash
# 2-3 系数 × 1-2 层 → 快速标定推荐区间
for TRAIT in conscientiousness openness neuroticism; do
  VEC_PATH="$OUT/vectors/${TRAIT}/${TRAIT}_response_avg_diff.pt"
  
  for L in $LAYER $((LAYER+4)); do
    for C in 1.5 3.0 5.0; do
      python -m eval.eval_persona \
        --model $MODEL --trait $TRAIT --version eval \
        --steering_type response --coef $C \
        --vector_path $VEC_PATH --layer $L \
        --judge_model $JUDGE --n_per_question 2 \
        --output_path "$OUT/${TRAIT}_scan_L${L}_c${C}.csv"
    done
  done
  echo "[$(date)] $TRAIT scan DONE"
done

# 激活抽样存储实测（W2 前置验证）
python << 'ACTEOF'
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "Qwen/Qwen2.5-7B-Instruct"
model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.bfloat16, device_map="auto")
tokenizer = AutoTokenizer.from_pretrained(MODEL)

# 单条生成 + 逐 token hidden state 采集（10 tokens）
conv = [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "What is 2+2?"}]
rendered = tokenizer.apply_chat_template(conv, tokenize=False, add_generation_prompt=True)
inputs = tokenizer(rendered, return_tensors="pt").to(model.device)

with torch.no_grad():
    out = model.generate(**inputs, max_new_tokens=10, output_hidden_states=True, return_dict_in_generate=True)

# 验证 hidden_states 结构可用于 W2 剂量采集
hs = out.hidden_states  # tuple of tuples
print(f"Generated tokens: {len(hs)}")
print(f"Layers per token: {len(hs[0])}")
print(f"Shape: {hs[0][0].shape}")
print("Activation sampling structure verified for W2")
ACTEOF
```

## ⑥ 回传 + 关机记账

```bash
# 标准化向量工件（按 F6 schema 整理）
python << 'STDEOF'
import torch, json, hashlib, pathlib, os
from datetime import date

OUT = pathlib.Path("/workspace/abcr/runs/cloud-day2")

for trait in ["conscientiousness", "openness", "neuroticism"]:
    vec_dir = OUT / "vectors" / trait
    pt_file = vec_dir / f"{trait}_response_avg_diff.pt"
    if not pt_file.exists():
        print(f"WARN: {pt_file} missing")
        continue
    
    # Rename to standard
    std_dir = pathlib.Path(f"/workspace/abcr/vectors/qwen2.5-7b-instruct/{trait}-citable")
    std_dir.mkdir(parents=True, exist_ok=True)
    
    t = torch.load(pt_file)
    std_pt = std_dir / "response_avg_diff.pt"
    torch.save(t, std_pt)
    
    sha = hashlib.sha256(std_pt.read_bytes()).hexdigest()
    
    card = {
        "trait": trait, "model_id": "Qwen/Qwen2.5-7B-Instruct",
        "model_revision": "<填revision>",
        "source_commit": "b8e0f044fe2410a6fad579f38324f03f13b4e917",
        "extraction_date": str(date.today()), "grade": "citable",
        "judge_model": "deepseek-chat",
        "judge_lineage": "replaced(official gpt-4.1-mini-2025-04-14)",
        "recommended": {"layer": 0, "coef": 0.0},  # 填入扫描结果
        "n_pos_effective": 0, "n_neg_effective": 0,  # 从 generate_vec 日志读取
        "pt_sha256": sha, "notes": "cloud-day2 7B bf16 full-scale"
    }
    (std_dir / "card.json").write_text(json.dumps(card, indent=2))
    print(f"{trait}: standardized to {std_dir}")

STDEOF

# 打包
tar czf /tmp/cloud-day2-results.tar.gz runs/cloud-day2/ vectors/
sha256sum /tmp/cloud-day2-results.tar.gz | tee /tmp/cloud-day2-sha256.txt
scp /tmp/cloud-day2-results.tar.gz user@mac-ip:~/abcr/
scp /tmp/cloud-day2-sha256.txt user@mac-ip:~/abcr/

# 记账 + 关机
COST=<计算>
python -c "assert $COST <= $(python -c 'import json; print(json.loads(open(\"costs/ledger.jsonl\").readlines()[-1])[\"remaining_cny\"])'),'E16'"
cat >> costs/ledger.jsonl << EOF
{"ts":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","event":"cloudday2-complete","hours":<填>,"cost_cny":$COST}
EOF
sudo shutdown -h now
```

---

## 标注

- 所有产物标 `exploratory`（citable 需楠确认对表通过后手动升级 grade）
- judge_lineage: `replaced(official gpt-4.1-mini-2025-04-14)` 写入全部 card.json
- 三 trait 的 exprcheck_pool.csv 回传 Mac 后供 C 包正式盲评
