"""One-time script: build items.jsonl from IFEval dataset (or generate fallback)."""

import hashlib
import json
from pathlib import Path
from typing import Any

CT1_SUPPORTED = {
    "keywords:existence",
    "keywords:forbidden_words",
    "keywords:frequency",
    "length_constraints:number_words",
    "length_constraints:number_sentences",
    "length_constraints:number_paragraphs",
    "detectable_format:json_format",
    "detectable_format:title",
    "detectable_format:number_bullet_lists",
    "change_case:english_capital",
    "change_case:english_lowercase",
    "detectable_content:postscript",
    "startend:end_checker",
    "startend:quotation",
}

INSTRUCTION_MAP = {
    "keywords:existence": "keywords_existence",
    "keywords:forbidden_words": "keywords_forbidden",
    "keywords:frequency": "keyword_frequency",
    "length_constraints:number_words": "length_words",
    "length_constraints:number_sentences": "length_sentences",
    "length_constraints:number_paragraphs": "length_paragraphs",
    "detectable_format:json_format": "format_json",
    "detectable_format:title": "format_title",
    "detectable_format:number_bullet_lists": "format_bullets",
    "change_case:english_capital": "case_capital",
    "change_case:english_lowercase": "case_lowercase",
    "detectable_content:postscript": "postscript",
    "startend:end_checker": "end_phrase",
    "startend:quotation": "quotation",
}

KWARGS_MAP = {
    "keywords:existence": lambda kw: {"keywords": kw.get("keywords", [])},
    "keywords:forbidden_words": lambda kw: {"forbidden_words": kw.get("forbidden_words", [])},
    "keywords:frequency": lambda kw: {
        "keyword": kw.get("keyword", ""),
        "frequency": kw.get("frequency", 1),
        "relation": kw.get("relation", "at least"),
    },
    "length_constraints:number_words": lambda kw: {
        "num_words": kw.get("num_words", 1),
        "relation": kw.get("relation", "at least"),
    },
    "length_constraints:number_sentences": lambda kw: {
        "num_sentences": kw.get("num_sentences", 1),
        "relation": kw.get("relation", "at least"),
    },
    "length_constraints:number_paragraphs": lambda kw: {
        "num_paragraphs": kw.get("num_paragraphs", 1),
    },
    "detectable_format:json_format": lambda kw: {},
    "detectable_format:title": lambda kw: {},
    "detectable_format:number_bullet_lists": lambda kw: {
        "num_bullets": kw.get("num_bullets", 1),
    },
    "change_case:english_capital": lambda kw: {},
    "change_case:english_lowercase": lambda kw: {},
    "detectable_content:postscript": lambda kw: {
        "postscript_marker": kw.get("postscript_marker", "P.S."),
    },
    "startend:end_checker": lambda kw: {
        "end_phrase": kw.get("end_phrase", ""),
    },
    "startend:quotation": lambda kw: {},
}


def build_from_ifeval() -> list[dict[str, Any]]:
    from datasets import load_dataset
    ds = load_dataset("google/IFEval", split="train")
    items = []
    for row in ds:
        prompt = row["prompt"]
        instruction_ids = row.get("instruction_id_list", [])
        kwargs_list = row.get("kwargs", [])
        if isinstance(kwargs_list, str):
            kwargs_list = json.loads(kwargs_list)

        checks = []
        for inst_id, kw in zip(instruction_ids, kwargs_list):
            if isinstance(kw, str):
                kw = json.loads(kw)
            if inst_id in CT1_SUPPORTED:
                name = INSTRUCTION_MAP[inst_id]
                mapped_kw = KWARGS_MAP[inst_id](kw)
                checks.append({"name": name, "kwargs": mapped_kw})

        if not checks:
            continue

        item_id = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        items.append({
            "item_id": item_id,
            "family": "ifeval_style",
            "prompt": prompt,
            "checks": checks,
            "source": "google/IFEval",
            "source_key": item_id,
        })

    return items


def build_generated_fallback() -> list[dict[str, Any]]:
    import subprocess
    templates = [
        {"prompt": "Write a paragraph about technology. Include the keywords 'innovation', 'digital', and 'future'.", "checks": [{"name": "keywords_existence", "kwargs": {"keywords": ["innovation", "digital", "future"]}}]},
        {"prompt": "Describe a sunset without using the words 'beautiful', 'red', or 'orange'.", "checks": [{"name": "keywords_forbidden", "kwargs": {"forbidden_words": ["beautiful", "red", "orange"]}}]},
        {"prompt": "Write about your morning routine. Use the word 'coffee' at least 2 times.", "checks": [{"name": "keyword_frequency", "kwargs": {"keyword": "coffee", "frequency": 2, "relation": "at least"}}]},
        {"prompt": "Explain the concept of gravity in at least 30 words.", "checks": [{"name": "length_words", "kwargs": {"num_words": 30, "relation": "at least"}}]},
        {"prompt": "Describe a perfect vacation in exactly 5 sentences.", "checks": [{"name": "length_sentences", "kwargs": {"num_sentences": 5, "relation": "at least"}}]},
        {"prompt": "Write about the seasons. Use exactly 4 paragraphs.", "checks": [{"name": "length_paragraphs", "kwargs": {"num_paragraphs": 4}}]},
        {"prompt": "Create a JSON object with keys 'name', 'age', and 'city' describing a person.", "checks": [{"name": "format_json", "kwargs": {}}]},
        {"prompt": "Write a brief essay about space exploration. End with the phrase 'to infinity and beyond'.", "checks": [{"name": "end_phrase", "kwargs": {"end_phrase": "to infinity and beyond"}}]},
        {"prompt": "Write a recipe for scrambled eggs in ALL CAPITAL LETTERS.", "checks": [{"name": "case_capital", "kwargs": {}}]},
        {"prompt": "Write a thank you note. Add a postscript starting with 'P.S.'", "checks": [{"name": "postscript", "kwargs": {"postscript_marker": "P.S."}}]},
    ]
    items = []
    for i, t in enumerate(templates):
        item_id = hashlib.sha256(t["prompt"].encode()).hexdigest()[:16]
        items.append({
            "item_id": item_id,
            "family": "ifeval_style",
            "prompt": t["prompt"],
            "checks": t["checks"],
            "source": "generated-fallback",
            "source_key": f"gen_{i:03d}",
        })
    return items


def main():
    out_path = Path("data/items/ifeval_style/items.jsonl")
    try:
        items = build_from_ifeval()
        print(f"Built {len(items)} items from IFEval")
    except Exception as e:
        print(f"IFEval download failed: {e}")
        print("Using generated fallback")
        items = build_generated_fallback()
        Path("DEVIATIONS.md").open("a").write(
            f"[A] 2026-07-11 IFEval下载失败，使用生成式后备题库({len(items)}题)。原因: {type(e).__name__}\n"
        )

    if len(items) < 60:
        print(f"WARNING: only {len(items)} items (< 60 minimum)")

    with open(out_path, "w") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Written {len(items)} items to {out_path}")


if __name__ == "__main__":
    main()
