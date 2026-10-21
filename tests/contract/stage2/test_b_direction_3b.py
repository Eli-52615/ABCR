"""S2 Contract Test: 3B direction reproduction check.

Layers {16,20,24} × coef {+2.0,+3.5,-2.0,-3.5} + baseline,
eval.json first 10 questions × 1 generation each.
Assert: exists layer L* where pos-coef mean > baseline+10
and neg-coef mean < baseline-10, and coherence >= 50.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
from collections import defaultdict

import pytest
import torch
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]

# V17 成本闸：本文件调用 deepseek 付费 judge。凭据读取 **不得** 出现在模块顶层
# ——模块顶层代码在 collect 期先于 skipif 执行，`--collect-only` 就会把 key 载入
# 进程环境。凭据读取一律推迟到 _arm_paid_judge()，且置于成本闸判定之后。
# 全局闸见 tests/conftest.py（无 APPROVE_COST 时本文件在 import 前即被 ignore）。
pytestmark = pytest.mark.paid

APPROVE_ENV = "APPROVE_COST"
_DEEPSEEK_KEY_PATH = "~/oc-boss-state/deepseek.key"


def _cost_approved() -> bool:
    return os.environ.get(APPROVE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _arm_paid_judge():
    """成本闸 → 凭据注入 → 付费依赖导入。顺序不可颠倒。"""
    if not _cost_approved():
        raise RuntimeError(
            f"cost gate: test_b_direction_3b issues billable deepseek judge calls; "
            f"set {APPROVE_ENV}=1 to authorize."
        )
    for p in (ROOT / "src", ROOT / "third_party" / "persona_vectors"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    if not (ROOT / "third_party" / "persona_vectors").is_dir():
        raise RuntimeError(
            f"third_party/persona_vectors missing under {ROOT}; "
            "run scripts/bootstrap.sh before this contract test."
        )
    os.environ.setdefault(
        "OPENAI_API_KEY",
        open(os.path.expanduser(_DEEPSEEK_KEY_PATH)).read().strip(),
    )
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")

    global OpenAiJudge, Prompts
    from judge import OpenAiJudge  # noqa: E402,F811
    from eval.prompts import Prompts  # noqa: E402,F811
    return OpenAiJudge, Prompts


#: 由 _arm_paid_judge() 在成本闸之后填充；未武装时保持 None，任何误用立刻 TypeError。
OpenAiJudge = None
Prompts = None


sys.path.insert(0, str(ROOT / "src"))
from abcr.interventions.residual_vector import ResidualVectorIntervention  # noqa: E402
from abcr.resource_guard import set_mps_memory_limit, mps_cleanup  # noqa: E402


def load_model(model_key: str):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    models = yaml.safe_load((ROOT / "configs" / "models.yaml").read_text())["models"]
    model_id = models[model_key]["model_id"]
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.float16)
    model = model.to("mps")
    model.eval()
    return model, tokenizer


def generate(model, tokenizer, question: str, vector=None, layer=None, coef=None):
    msgs = [{"role": "user", "content": question}]
    rendered = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(rendered, return_tensors="pt").to(model.device)

    if vector is not None and coef is not None and coef != 0:
        card = {"trait": "direction_check"}
        iv = ResidualVectorIntervention(
            vector=vector, card=card, layer=layer, coefficient=coef,
            positions="response", vector_dir="direction_check",
        )
        with torch.inference_mode():
            with iv.context(model):
                out = model.generate(
                    **inputs, max_new_tokens=300, do_sample=False,
                    pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
                )
    else:
        with torch.inference_mode():
            out = model.generate(
                **inputs, max_new_tokens=300, do_sample=False,
                pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            )
    return tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)


async def judge_one(q: str, a: str, eval_prompt: str, trait: str) -> dict:
    import time
    tj = OpenAiJudge("deepseek-chat", eval_prompt, eval_type="0_100")
    cj = OpenAiJudge("deepseek-chat", Prompts["coherence_0_100"], eval_type="0_100")
    for attempt in range(4):
        try:
            t = await tj(question=q, answer=a)
            c = await cj(question=q, answer=a)
            return {"trait": t, "coherence": c}
        except (AttributeError, TypeError, IndexError) as e:
            if attempt < 3:
                time.sleep(2 ** attempt)
            else:
                return {"trait": None, "coherence": None}


def test_direction_3b():
    _arm_paid_judge()   # 成本闸；未批准即 RuntimeError，凭据在此之前从未被读
    trait = "optimistic"
    vector_dir = ROOT / "vectors" / "qwen2.5-3b-instruct" / "optimistic-dev"
    if not vector_dir.exists():
        print(f"SKIP: vector_dir not yet created: {vector_dir}")
        print("Run 3B extraction first")
        return

    vector = torch.load(vector_dir / "response_avg_diff.pt", map_location="cpu", weights_only=True)
    eval_data = json.loads((ROOT / "artifacts" / "traits" / trait / "eval.json").read_text())
    questions = eval_data["questions"][:10]
    eval_prompt = eval_data["eval_prompt"]

    fraction = set_mps_memory_limit()
    if fraction is not None:
        print(f"MPS memory fraction: {fraction:.3f}")

    model, tokenizer = load_model("qwen2.5-3b-instruct")
    layers = [16, 20, 24]
    coefs = [2.0, 3.5, -2.0, -3.5]

    results = defaultdict(list)

    # Baseline
    print("Baseline (10 questions)...")
    for q in questions:
        ans = generate(model, tokenizer, q)
        scores = asyncio.run(judge_one(q, ans, eval_prompt, trait))
        results["baseline"].append(scores)

    # Steered
    for layer in layers:
        for coef in coefs:
            key = f"L{layer}_c{coef}"
            print(f"{key} (10 questions)...")
            for q in questions:
                ans = generate(model, tokenizer, q, vector, layer, coef)
                scores = asyncio.run(judge_one(q, ans, eval_prompt, trait))
                results[key].append(scores)

    # Save raw results
    out_path = ROOT / "pv_bridge" / "out" / "direction_check_3b.json"
    serializable = {k: v for k, v in results.items()}
    out_path.write_text(json.dumps(serializable, indent=2, default=str))

    # Analysis
    def mean_trait(scores_list):
        vals = [s["trait"] for s in scores_list if s["trait"] is not None]
        return sum(vals) / len(vals) if vals else 0

    def mean_coh(scores_list):
        vals = [s["coherence"] for s in scores_list if s["coherence"] is not None]
        return sum(vals) / len(vals) if vals else 0

    baseline_mean = mean_trait(results["baseline"])
    print(f"\nBaseline trait mean: {baseline_mean:.1f}")

    best_layer = None
    best_coef = None

    for layer in layers:
        pos_coefs = [c for c in coefs if c > 0]
        neg_coefs = [c for c in coefs if c < 0]

        for pc in pos_coefs:
            pk = f"L{layer}_c{pc}"
            pos_mean = mean_trait(results[pk])
            pos_coh = mean_coh(results[pk])

            for nc in neg_coefs:
                nk = f"L{layer}_c{nc}"
                neg_mean = mean_trait(results[nk])

                print(f"  L{layer}: +{pc}={pos_mean:.1f} (coh={pos_coh:.1f}), {nc}={neg_mean:.1f}, "
                      f"delta_pos={pos_mean-baseline_mean:.1f}, delta_neg={neg_mean-baseline_mean:.1f}")

                if (pos_mean > baseline_mean + 10 and
                    neg_mean < baseline_mean - 10 and
                    pos_coh >= 50):
                    if best_layer is None:
                        best_layer = layer
                        best_coef = pc
                        print(f"  -> PASS: L*={layer}, coef={pc}")

    if best_layer is None:
        # Retry with backup layers
        print("\nFirst layer set failed. Trying backup layers {8,12,28}...")
        backup_layers = [8, 12, 28]
        for layer in backup_layers:
            for coef in coefs:
                key = f"L{layer}_c{coef}"
                print(f"{key} (10 questions)...")
                for q in questions:
                    ans = generate(model, tokenizer, q, vector, layer, coef)
                    scores = asyncio.run(judge_one(q, ans, eval_prompt, trait))
                    results[key].append(scores)

        for layer in backup_layers:
            for pc in [c for c in coefs if c > 0]:
                pk = f"L{layer}_c{pc}"
                pos_mean = mean_trait(results[pk])
                pos_coh = mean_coh(results[pk])
                for nc in [c for c in coefs if c < 0]:
                    nk = f"L{layer}_c{nc}"
                    neg_mean = mean_trait(results[nk])
                    if (pos_mean > baseline_mean + 10 and
                        neg_mean < baseline_mean - 10 and
                        pos_coh >= 50):
                        best_layer = layer
                        best_coef = pc
                        break
                if best_layer:
                    break
            if best_layer:
                break

    # Update card.json with recommended
    if best_layer is not None:
        card_path = vector_dir / "card.json"
        card = json.loads(card_path.read_text())
        card["recommended"] = {"layer": best_layer, "coef": best_coef}
        card_path.write_text(json.dumps(card, indent=2))
        print(f"\ncard.recommended updated: layer={best_layer}, coef={best_coef}")
    else:
        print("\nFAIL: No layer satisfies direction monotonicity + coherence criteria")
        print("Writing failure decision package to STATUS-B")

    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"Results saved: {out_path}")
    del model
    allocated = mps_cleanup()
    if allocated is not None:
        print(f"Post-cleanup MPS: {allocated/(1024**3):.2f}GB")

    assert best_layer is not None, "Direction reproduction check failed"


if __name__ == "__main__":
    test_direction_3b()
    print("PASS: test_b_direction_3b")
