"""Flip preview generator (Package B).

For each of the first 3 eval questions, generate baseline / +coef / -coef
responses, with judge scores, and produce a side-by-side markdown preview.

Usage:
  export OPENAI_API_KEY=$(cat ~/oc-boss-state/deepseek.key)
  export OPENAI_BASE_URL=https://api.deepseek.com
  .venv-pv/bin/python pv_bridge/flip_preview.py \
    --model-key qwen2.5-3b-instruct \
    --vector-dir vectors/qwen2.5-3b-instruct/optimistic-dev \
    --trait optimistic \
    --out-md vectors/qwen2.5-3b-instruct/optimistic-dev/flip_preview.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
from datetime import datetime

import torch
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "third_party" / "persona_vectors"))
sys.path.insert(0, str(ROOT / "src"))

from judge import OpenAiJudge  # noqa: E402
from eval.prompts import Prompts  # noqa: E402


def load_model(model_key: str, device: str = "mps", dtype: str = "float16"):
    from transformers import AutoModelForCausalLM, AutoTokenizer

    models = yaml.safe_load((ROOT / "configs" / "models.yaml").read_text()).get("models", {})
    model_id = models[model_key]["model_id"]
    dtype_map = {"float32": torch.float32, "float16": torch.float16}
    torch_dtype = dtype_map.get(dtype, torch.float16)

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch_dtype)
    if device == "mps":
        model = model.to("mps")
    model.eval()
    return model, tokenizer


def generate_one(model, tokenizer, question: str, system: str | None = None) -> str:
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": question})
    rendered = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(rendered, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(
            **inputs, max_new_tokens=300, do_sample=False,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
        )
    return tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)


def generate_steered(model, tokenizer, question: str, vector: torch.Tensor,
                     layer: int, coef: float) -> str:
    from abcr.interventions.residual_vector import ResidualVectorIntervention
    msgs = [{"role": "user", "content": question}]
    rendered = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(rendered, return_tensors="pt").to(model.device)

    card = {"trait": "preview"}
    iv = ResidualVectorIntervention(
        vector=vector, card=card, layer=layer, coefficient=coef,
        positions="response", vector_dir="preview",
    )
    with torch.no_grad():
        with iv.context(model):
            out = model.generate(
                **inputs, max_new_tokens=300, do_sample=False,
                pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            )
    return tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)


async def judge_one(question: str, answer: str, eval_prompt: str, trait: str) -> dict:
    import time
    trait_judge = OpenAiJudge("deepseek-chat", eval_prompt, eval_type="0_100")
    coh_judge = OpenAiJudge("deepseek-chat", Prompts["coherence_0_100"], eval_type="0_100")
    for attempt in range(4):
        try:
            t = await trait_judge(question=question, answer=answer)
            c = await coh_judge(question=question, answer=answer)
            return {trait: t, "coherence": c}
        except (AttributeError, TypeError, IndexError) as e:
            if attempt < 3:
                time.sleep(2 ** attempt)
            else:
                print(f"\n  [judge FAIL-CLOSED] {trait}: exhausted 4 retries ({type(e).__name__}), marking None")
    return {trait: None, "coherence": None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-key", required=True)
    parser.add_argument("--vector-dir", required=True)
    parser.add_argument("--trait", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--dtype", default="float16")
    args = parser.parse_args()

    vdir = pathlib.Path(args.vector_dir)
    card = json.loads((vdir / "card.json").read_text())
    layer = card["recommended"]["layer"]
    coef = card["recommended"]["coef"]

    vector = torch.load(vdir / "response_avg_diff.pt", map_location="cpu", weights_only=True)

    # Load eval questions (first 3)
    eval_path = ROOT / "artifacts" / "traits" / args.trait / "eval.json"
    eval_data = json.loads(eval_path.read_text())
    questions = eval_data["questions"][:3]
    eval_prompt = eval_data["eval_prompt"]

    model, tokenizer = load_model(args.model_key, args.device, args.dtype)

    lines = [
        f"# Flip Preview: {args.trait} (3B dev)",
        "",
        f"> **⚠ dev preview · 3B · non-citable**",
        f"> model: {args.model_key} | layer: {layer} | coef: ±{coef}",
        f"> generated: {datetime.now().isoformat()[:19]}",
        "",
    ]

    for i, q in enumerate(questions):
        print(f"Question {i+1}/3: {q[:60]}...")
        baseline = generate_one(model, tokenizer, q)
        pos = generate_steered(model, tokenizer, q, vector, layer, coef)
        neg = generate_steered(model, tokenizer, q, vector, layer, -coef)

        scores_b = asyncio.run(judge_one(q, baseline, eval_prompt, args.trait))
        scores_p = asyncio.run(judge_one(q, pos, eval_prompt, args.trait))
        scores_n = asyncio.run(judge_one(q, neg, eval_prompt, args.trait))

        lines.extend([
            f"## Q{i+1}: {q}",
            "",
            f"### Baseline ({args.trait}={scores_b[args.trait]:.0f}, coh={scores_b['coherence']:.0f})" if scores_b[args.trait] else f"### Baseline",
            f"```\n{baseline[:500]}\n```",
            "",
            f"### +coef ({args.trait}={scores_p[args.trait]:.0f}, coh={scores_p['coherence']:.0f})" if scores_p[args.trait] else f"### +coef",
            f"```\n{pos[:500]}\n```",
            "",
            f"### −coef ({args.trait}={scores_n[args.trait]:.0f}, coh={scores_n['coherence']:.0f})" if scores_n[args.trait] else f"### −coef",
            f"```\n{neg[:500]}\n```",
            "",
            "---",
            "",
        ])

    out_path = pathlib.Path(args.out_md)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    print(f"Flip preview written: {out_path}")
    del model


if __name__ == "__main__":
    main()
