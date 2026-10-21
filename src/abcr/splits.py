"""Split management: deterministic hash-based assignment + verification."""

import hashlib
import json
from pathlib import Path
from typing import Any


def make(family: str, items_path: str | Path) -> Path:
    items_path = Path(items_path)
    items_content = items_path.read_bytes()
    items_sha = hashlib.sha256(items_content).hexdigest()
    filehash8 = items_sha[:8]

    items = []
    for line in items_path.read_text().splitlines():
        if line.strip():
            items.append(json.loads(line))

    assignment: dict[str, str] = {}
    for item in items:
        item_id = item["item_id"]
        bucket = int(hashlib.sha256(f"{family}:{item_id}".encode()).hexdigest()[:8], 16) % 100
        if bucket < 20:
            assignment[item_id] = "dev"
        elif bucket < 60:
            assignment[item_id] = "calibration"
        else:
            assignment[item_id] = "heldout"

    counts: dict[str, int] = {}
    for split in assignment.values():
        counts[split] = counts.get(split, 0) + 1

    split_data = {
        "family": family,
        "items_source_sha256": items_sha,
        "assignment": assignment,
        "counts": counts,
        "tool_version": "1.0",
    }

    split_path = Path(f"data/splits/{family}-{filehash8}.json")
    split_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(split_data, indent=2, ensure_ascii=False)
    split_path.write_text(content)

    split_hash = hashlib.sha256(split_path.read_bytes()).hexdigest()
    sha_path = split_path.with_suffix(split_path.suffix + ".sha256")
    sha_path.write_text(split_hash)

    print(f"Split created: {split_path}")
    print(f"  Items: {len(items)}, Counts: {counts}")
    print(f"  Split hash: {split_hash[:16]}...")

    return split_path


def verify(split_file: str | Path) -> bool:
    split_file = Path(split_file)
    sha_file = split_file.with_suffix(split_file.suffix + ".sha256")
    if not sha_file.exists():
        return False
    expected = sha_file.read_text().strip()
    actual = hashlib.sha256(split_file.read_bytes()).hexdigest()
    return actual == expected


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        make(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python -m abcr.splits <family> <items_path>")
