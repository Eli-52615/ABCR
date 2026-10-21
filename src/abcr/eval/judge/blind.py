import csv
import json
import os
import pathlib
import random
import sys
from typing import Optional
from abcr.eval.judge.client import TraitJudge

FORBIDDEN_COLUMNS = {"condition", "trait", "trait_pole", "arm", "method"}


def blind_score(pool_csv: str, eval_prompt_template: str, out_jsonl: str,
                coherence_prompt_template: Optional[str] = None,
                mode: str = "text_parse", seed: int = 42,
                prompt_source: Optional[dict] = None) -> dict:
    pool_path = pathlib.Path(pool_csv)
    if not pool_path.exists():
        print(f"Error: pool CSV not found: {pool_csv}", file=sys.stderr)
        sys.exit(1)

    with open(pool_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        columns = set(reader.fieldnames or [])
        violations = columns & FORBIDDEN_COLUMNS
        if violations:
            raise ValueError(
                f"Blind protocol violation: pool CSV contains forbidden columns {violations}. "
                "Only sample_id/question/answer are permitted."
            )
        rows = list(reader)

    rng = random.Random(seed)
    rng.shuffle(rows)

    judge = TraitJudge(mode=mode)
    out_path = pathlib.Path(out_jsonl)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    raw_dir = out_path.parent / "judge_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_name = out_path.stem
    raw_path = raw_dir / f"{raw_name}.jsonl"

    results = []
    n_trait_refusal = 0
    n_coherence_refusal = 0
    with open(out_path, "w") as f, open(raw_path, "w") as raw_f:
        for row in rows:
            sample_id = row.get("sample_id", row.get("id", ""))
            question = row.get("question", row.get("prompt", ""))
            answer = row.get("answer", row.get("response", ""))

            filled_prompt = eval_prompt_template.replace("{question}", question).replace("{answer}", answer)
            trait_result = judge.score(filled_prompt)

            raw_entry = {"sample_id": sample_id, "type": "trait", "raw": trait_result}

            entry = {
                "sample_id": sample_id,
                "trait_score": trait_result.get("score"),
                "judge_raw_ref": f"trait:{sample_id}",
            }
            if trait_result.get("score") is None:
                n_trait_refusal += 1
                entry["E14_parse_fail"] = trait_result.get("reason", "unknown")

            if coherence_prompt_template:
                coherence_prompt = coherence_prompt_template.replace("{question}", question).replace("{answer}", answer)
                coherence_result = judge.score(coherence_prompt)
                entry["coherence_score"] = coherence_result.get("score")
                entry["coherence_raw_ref"] = f"coherence:{sample_id}"
                raw_entry["coherence_raw"] = coherence_result
                if coherence_result.get("score") is None:
                    n_coherence_refusal += 1

            results.append(entry)
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            raw_f.write(json.dumps(raw_entry, ensure_ascii=False) + "\n")

    result = {
        "n": len(results),
        "shuffle_seed": seed,
        "judge_model": judge.model,
        "judge_lineage": "replaced(official gpt-4.1-mini-2025-04-14)",
        "cost": judge.cost_summary(),
        "judge_raw_path": str(raw_path),
        "n_trait_refusal": n_trait_refusal,
        "n_coherence_refusal": n_coherence_refusal,
    }
    if prompt_source:
        result["prompt_source"] = prompt_source
    return result


if __name__ == "__main__":
    import typer
    app = typer.Typer()

    @app.command()
    def run(pool: str, prompt: str, out: str, mode: str = "text_parse", seed: int = 42):
        result = blind_score(pool, prompt, out, mode=mode, seed=seed)
        print(json.dumps(result, indent=2))

    app()
