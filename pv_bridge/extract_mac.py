"""Mac-side extract bridge for persona_vectors (Package B).

Replaces the official eval_persona.py extract path (which requires vLLM)
with transformers-based generation while maintaining semantic fidelity.
See BRIDGE-FIDELITY.md for line-by-line correspondence.

Run with .venv-pv:
  export OPENAI_API_KEY=$(cat ~/oc-boss-state/deepseek.key)
  export OPENAI_BASE_URL=https://api.deepseek.com
  .venv-pv/bin/python pv_bridge/extract_mac.py \
    --model-key qwen2.5-0.5b-instruct \
    --trait optimistic --artifact artifacts/traits/optimistic/extract.json \
    --pole pos --n-per-q 2 --out-csv pv_bridge/out/optimistic_pos.csv
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import json
import os
import pathlib
import sys

import pandas as pd
import torch
import yaml
from tqdm import tqdm

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Inject PV clone path for judge import (BRIDGE-FIDELITY §7: import order matters)
PV_PATH = ROOT / "third_party" / "persona_vectors"
sys.path.insert(0, str(PV_PATH))
sys.path.insert(0, str(ROOT / "src"))

from judge import OpenAiJudge  # noqa: E402
from eval.prompts import Prompts  # noqa: E402
from abcr.resource_guard import check_pressure_fuse, set_mps_memory_limit, mps_cleanup  # noqa: E402


def load_models_yaml() -> dict:
    p = ROOT / "configs" / "models.yaml"
    return yaml.safe_load(p.read_text()).get("models", {})


def a_or_an(word: str) -> str:
    """BRIDGE-FIDELITY §1: official a_or_an at eval_persona.py:134"""
    return "an" if word[0].lower() in "aeiou" else "a"


def build_system_prompt(instruction: str, assistant_name: str) -> str:
    """BRIDGE-FIDELITY §1: official template at eval_persona.py:154"""
    return f"You are {a_or_an(assistant_name)} {assistant_name} assistant. {instruction}"


def load_model(model_key: str, device: str, dtype: str):
    from transformers import AutoModelForCausalLM, AutoTokenizer

    models = load_models_yaml()
    entry = models[model_key]
    model_id = entry["model_id"]

    dtype_map = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}
    torch_dtype = dtype_map.get(dtype, torch.float32)

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if device == "mps":
        model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch_dtype)
        model = model.to("mps")
    else:
        model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch_dtype)
    model.eval()
    return model, tokenizer


def generate_responses(
    model,
    tokenizer,
    conversations: list[list[dict]],
    n_per_q: int,
    temperature: float,
    max_tokens: int = 1000,
    seed_offset: int = 0,
) -> tuple[list[str], list[str]]:
    """BRIDGE-FIDELITY §2-3: replicate official generation semantics."""
    tokenizer.padding_side = "left"
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        tokenizer.pad_token_id = tokenizer.eos_token_id

    all_prompts = []
    all_answers = []
    seed_counter = seed_offset
    _init_ppid = os.getppid()
    _consecutive_warnings = 0

    for conv in tqdm(conversations, desc="Generating"):
        rendered = tokenizer.apply_chat_template(conv, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(rendered, return_tensors="pt").to(model.device)

        for _ in range(n_per_q):
            torch.manual_seed(seed_counter)
            seed_counter += 1

            with torch.inference_mode():
                output = model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    min_new_tokens=1,
                    do_sample=(temperature > 0),
                    temperature=temperature if temperature > 0 else None,
                    top_p=1.0 if temperature > 0 else None,
                    use_cache=True,
                    pad_token_id=tokenizer.pad_token_id,
                )
            prompt_len = inputs["input_ids"].shape[1]
            answer = tokenizer.decode(output[0][prompt_len:], skip_special_tokens=True)
            all_prompts.append(rendered)
            all_answers.append(answer)

            action, _consecutive_warnings = check_pressure_fuse(_consecutive_warnings)
            if action:
                print(f"\n[E19] Pressure fuse: {action}. Exiting.")
                sys.exit(19)
            if os.getppid() != _init_ppid:
                print(f"\n[E19] Parent gone (orphaned). Exiting.")
                sys.exit(19)

    return all_prompts, all_answers


async def judge_batch(
    questions: list[str],
    answers: list[str],
    trait: str,
    eval_prompt: str,
    judge_model: str = "deepseek-chat",
) -> tuple[list[float | None], list[float | None], list[dict]]:
    """BRIDGE-FIDELITY §4-5: dual judge (trait + coherence), logprob_weighted."""
    trait_judge = OpenAiJudge(judge_model, eval_prompt, eval_type="0_100")
    coherence_judge = OpenAiJudge(judge_model, Prompts["coherence_0_100"], eval_type="0_100")

    raw_records = []

    async def score_one(q: str, a: str):
        import time
        for attempt in range(4):
            try:
                t_score = await trait_judge(question=q, answer=a)
                c_score = await coherence_judge(question=q, answer=a)
                raw_records.append({"question": q, "answer": a[:200], "trait_score": t_score, "coherence_score": c_score})
                return t_score, c_score
            except (AttributeError, TypeError, IndexError) as e:
                if attempt < 3:
                    wait = 2 ** attempt
                    print(f"\n  [judge retry {attempt+1}/3] {type(e).__name__}: {e}; wait {wait}s")
                    time.sleep(wait)
                else:
                    print(f"\n  [judge FAIL] {type(e).__name__}: {e}; returning None scores")
                    raw_records.append({"question": q, "answer": a[:200], "trait_score": None, "coherence_score": None, "error": str(e)})
                    return None, None

    results = []
    for q, a in tqdm(zip(questions, answers), total=len(questions), desc="Judging"):
        results.append(await score_one(q, a))

    trait_scores = [r[0] for r in results]
    coherence_scores = [r[1] for r in results]
    return trait_scores, coherence_scores, raw_records


def main():
    parser = argparse.ArgumentParser(description="Mac-side PV extract bridge")
    parser.add_argument("--model-key", required=True)
    parser.add_argument("--trait", required=True)
    parser.add_argument("--artifact", required=True, help="Path to extract.json")
    parser.add_argument("--pole", required=True, choices=["pos", "neg"])
    parser.add_argument("--n-per-q", type=int, default=2)
    parser.add_argument("--out-csv", required=True)
    parser.add_argument("--device", default="cpu", choices=["cpu", "mps"])
    parser.add_argument("--dtype", default="float32", choices=["float32", "float16"])
    parser.add_argument("--limit-questions", type=int, default=None)
    parser.add_argument("--limit-instructions", type=int, default=None)
    parser.add_argument("--question-start", type=int, default=0, help="Question slice start (0-indexed inclusive)")
    parser.add_argument("--question-end", type=int, default=None, help="Question slice end (exclusive)")
    parser.add_argument("--seed-offset", type=int, default=0, help="Base seed for deterministic chunked runs")
    args = parser.parse_args()

    artifact = json.loads(pathlib.Path(args.artifact).read_text())
    instructions = artifact["instruction"]
    questions = artifact["questions"]

    if args.limit_instructions:
        instructions = instructions[: args.limit_instructions]
    if args.limit_questions:
        questions = questions[: args.limit_questions]
    if args.question_start or args.question_end:
        questions = questions[args.question_start : args.question_end]

    # BRIDGE-FIDELITY §1: assistant_name defaults
    assistant_name = args.trait if args.pole == "pos" else "helpful"

    # Build conversations: each question × each instruction
    conversations = []
    question_texts = []
    for q in questions:
        for instr in instructions:
            system = build_system_prompt(instr[args.pole], assistant_name)
            conv = [{"role": "system", "content": system}, {"role": "user", "content": q}]
            conversations.append(conv)
            question_texts.append(q)

    # BRIDGE-FIDELITY §2: temperature
    temperature = 0.0 if args.n_per_q == 1 else 1.0

    print(f"Extract: {len(conversations)} conversations × {args.n_per_q} responses = {len(conversations) * args.n_per_q} total")

    if args.device == "mps":
        fraction = set_mps_memory_limit()
        if fraction is not None:
            print(f"MPS memory fraction: {fraction:.3f}")

    model, tokenizer = load_model(args.model_key, args.device, args.dtype)
    prompts, answers = generate_responses(model, tokenizer, conversations, args.n_per_q, temperature, seed_offset=args.seed_offset)

    # Expand question_texts to match n_per_q
    expanded_questions = []
    for q in question_texts:
        expanded_questions.extend([q] * args.n_per_q)

    # Judge
    eval_prompt = artifact["eval_prompt"]
    trait_scores, coherence_scores, raw_records = asyncio.run(
        judge_batch(expanded_questions, answers, args.trait, eval_prompt)
    )

    # BRIDGE-FIDELITY §6: CSV output format
    df = pd.DataFrame({
        "prompt": prompts,
        "answer": answers,
        "question": expanded_questions,
        args.trait: trait_scores,
        "coherence": coherence_scores,
    })

    out_path = pathlib.Path(args.out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".csv.tmp")
    df.to_csv(tmp_path, index=False)
    os.rename(tmp_path, out_path)
    print(f"CSV written: {out_path} ({len(df)} rows)")

    raw_path = pathlib.Path(f"{args.out_csv}.judge_raw.jsonl")
    tmp_raw = raw_path.with_suffix(".jsonl.tmp")
    with open(tmp_raw, "w") as f:
        for rec in raw_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.rename(tmp_raw, raw_path)
    print(f"Judge raw: {raw_path}")

    # Summary stats
    valid_trait = [s for s in trait_scores if s is not None]
    valid_coh = [s for s in coherence_scores if s is not None]
    if valid_trait:
        print(f"{args.trait}: mean={sum(valid_trait)/len(valid_trait):.1f} (n={len(valid_trait)}/{len(trait_scores)})")
    if valid_coh:
        print(f"coherence: mean={sum(valid_coh)/len(valid_coh):.1f} (n={len(valid_coh)}/{len(coherence_scores)})")

    del model
    allocated = mps_cleanup()
    if allocated is not None:
        print(f"Post-cleanup MPS: {allocated/(1024**3):.2f}GB")


if __name__ == "__main__":
    main()
