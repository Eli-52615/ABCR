"""Expression check generation (Package B, B3.3).

Generates blinded expression check materials for C's evaluation.
For a given trait, produces:
  - exprcheck_pool.csv: sample_id, question, answer (NO condition labels)
  - exprcheck_key.csv: sample_id, condition (for post-scoring unblinding)

Usage:
  .venv-pv/bin/python pv_bridge/exprcheck_gen.py \
    --model-key qwen2.5-3b-instruct \
    --trait conscientiousness \
    --vector-dir vectors/qwen2.5-3b-instruct/conscientiousness-dev \
    --n-per-q 2 \
    --out-dir pv_bridge/out/conscientiousness
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys

import pandas as pd
import torch
import yaml
from tqdm import tqdm

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from abcr.resource_guard import set_mps_memory_limit, mps_cleanup  # noqa: E402


def load_model(model_key: str, device: str = "mps", dtype: str = "float16"):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    models = yaml.safe_load((ROOT / "configs" / "models.yaml").read_text())["models"]
    model_id = models[model_key]["model_id"]
    dtype_map = {"float32": torch.float32, "float16": torch.float16}
    torch_dtype = dtype_map.get(dtype, torch.float16)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch_dtype)
    if device == "mps":
        model = model.to("mps")
    model.eval()
    return model, tokenizer


def generate_one(model, tokenizer, question: str, vector=None, layer=None, coef=None, n_per_q=1):
    from abcr.interventions.residual_vector import ResidualVectorIntervention
    msgs = [{"role": "user", "content": question}]
    rendered = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(rendered, return_tensors="pt").to(model.device)

    do_sample = n_per_q > 1
    gen_kwargs = dict(
        max_new_tokens=500,
        do_sample=do_sample,
        pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
    )
    if do_sample:
        gen_kwargs["temperature"] = 1.0

    if vector is not None and coef is not None and coef != 0:
        card = {"trait": "exprcheck"}
        iv = ResidualVectorIntervention(
            vector=vector, card=card, layer=layer, coefficient=coef,
            positions="response", vector_dir="exprcheck",
        )
        with torch.inference_mode():
            with iv.context(model):
                out = model.generate(**inputs, **gen_kwargs)
    else:
        with torch.inference_mode():
            out = model.generate(**inputs, **gen_kwargs)
    return tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-key", required=True)
    parser.add_argument("--trait", required=True)
    parser.add_argument("--vector-dir", required=True)
    parser.add_argument("--n-per-q", type=int, default=2)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--dtype", default="float16")
    parser.add_argument("--shuffle-seed", type=int, default=42)
    args = parser.parse_args()

    vdir = pathlib.Path(args.vector_dir)
    card = json.loads((vdir / "card.json").read_text())
    layer = card["recommended"]["layer"]
    coef = card["recommended"]["coef"]
    vector = torch.load(vdir / "response_avg_diff.pt", map_location="cpu", weights_only=True)

    eval_path = ROOT / "artifacts" / "traits" / args.trait / "eval.json"
    eval_data = json.loads(eval_path.read_text())
    questions = eval_data["questions"]  # all 20 eval questions

    if args.device == "mps":
        fraction = set_mps_memory_limit()
        if fraction is not None:
            print(f"MPS memory fraction: {fraction:.3f}")

    model, tokenizer = load_model(args.model_key, args.device, args.dtype)

    conditions = [
        ("baseline", None, None),
        ("steered_pos", layer, coef),
        ("steered_neg", layer, -coef),
    ]

    records = []
    sample_id = 0
    for q in tqdm(questions, desc="Questions"):
        for cond_name, l, c in conditions:
            for _ in range(args.n_per_q):
                answer = generate_one(model, tokenizer, q, vector, l, c, n_per_q=args.n_per_q)
                records.append({
                    "sample_id": sample_id,
                    "question": q,
                    "answer": answer,
                    "condition": cond_name,
                })
                sample_id += 1

    # Shuffle with recorded seed for reproducibility
    rng = random.Random(args.shuffle_seed)
    rng.shuffle(records)

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pool: blind (no condition)
    pool_df = pd.DataFrame([{
        "sample_id": r["sample_id"],
        "question": r["question"],
        "answer": r["answer"],
    } for r in records])
    pool_df.to_csv(out_dir / "exprcheck_pool.csv", index=False)

    # Key: for C to unbind after scoring
    key_df = pd.DataFrame([{
        "sample_id": r["sample_id"],
        "condition": r["condition"],
    } for r in records])
    key_df.to_csv(out_dir / "exprcheck_key.csv", index=False)

    print(f"Pool: {out_dir / 'exprcheck_pool.csv'} ({len(pool_df)} rows)")
    print(f"Key:  {out_dir / 'exprcheck_key.csv'} ({len(key_df)} rows)")
    print(f"Shuffle seed: {args.shuffle_seed}")

    del model
    allocated = mps_cleanup()
    if allocated is not None:
        print(f"Post-cleanup MPS: {allocated/(1024**3):.2f}GB")


if __name__ == "__main__":
    main()
