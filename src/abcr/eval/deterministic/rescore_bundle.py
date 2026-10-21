"""Generate the rescore/ self-contained bundle for repro packs.
Copies checkers, registry, and chain verification into a single-file rescore.py
that uses only stdlib (no third-party imports).
"""
import pathlib
import textwrap


def generate_rescore(out_dir: pathlib.Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    checkers_src = pathlib.Path(__file__).parent / "checkers.py"
    registry_src = pathlib.Path(__file__).parent / "registry.py"

    checkers_code = checkers_src.read_text()
    registry_code = registry_src.read_text()

    registry_code = registry_code.replace(
        "from abcr.eval.deterministic.checkers import (",
        "from checkers import ("
    )

    rescore_code = textwrap.dedent('''\
        #!/usr/bin/env python3
        """Self-contained rescore: verify chain + recompute all deterministic scores.
        Usage: python3 rescore.py <pack_dir>
        Requires only Python 3.10+ stdlib. No third-party imports.
        """
        import json
        import hashlib
        import pathlib
        import sys
        import os

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from registry import run_checks


        def canonical_json(obj):
            return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


        def verify_chain(steps):
            if not steps:
                return True, []
            prev_hash = "0" * 64
            errors = []
            for i, step in enumerate(steps):
                expected_prev = step.get("prev_hash", "")
                if expected_prev and expected_prev != prev_hash:
                    errors.append(f"step {i}: prev_hash mismatch")
                entry_data = {k: v for k, v in step.items() if k != "entry_hash"}
                payload = canonical_json(entry_data) + prev_hash
                computed = hashlib.sha256(payload.encode()).hexdigest()
                entry_hash = step.get("entry_hash", "")
                if entry_hash and entry_hash != computed:
                    errors.append(f"step {i}: entry_hash mismatch")
                prev_hash = entry_hash or computed
            return len(errors) == 0, errors


        def verify_sha256(pack_dir):
            manifest_path = pack_dir / "pack_manifest.json"
            if not manifest_path.exists():
                return False, ["pack_manifest.json not found"]
            with open(manifest_path) as f:
                manifest = json.load(f)
            errors = []
            for entry in manifest.get("files", []):
                fp = pack_dir / entry["path"]
                if not fp.exists():
                    errors.append(f"missing: {entry['path']}")
                    continue
                with open(fp, "rb") as f:
                    actual = hashlib.sha256(f.read()).hexdigest()
                if actual != entry["sha256"]:
                    errors.append(f"sha mismatch: {entry['path']}")
            return len(errors) == 0, errors


        def rescore_run(run_dir, items_by_id, scores_dir):
            steps_file = run_dir / "steps.jsonl"
            if not steps_file.exists():
                return {"run": run_dir.name, "error": "steps.jsonl not found"}
            steps = []
            with open(steps_file) as f:
                for line in f:
                    if line.strip():
                        steps.append(json.loads(line.strip()))

            chain_ok, chain_errors = verify_chain(steps)

            scores_file = scores_dir / run_dir.name / "scores.jsonl"
            mismatches = []
            if scores_file.exists():
                saved = {}
                with open(scores_file) as f:
                    for line in f:
                        if line.strip():
                            s = json.loads(line.strip())
                            key = (s.get("trajectory_id", ""), s.get("step_id", ""))
                            saved[key] = s

                for step in steps:
                    item_id = step.get("item_id", "")
                    output = step.get("output_text", "")
                    checks_spec = None
                    if item_id in items_by_id:
                        checks_spec = items_by_id[item_id].get("checks", [])
                    elif "checks" in step:
                        checks_spec = step["checks"]
                    if checks_spec is None:
                        checks_spec = []

                    results = run_checks(output, checks_spec)
                    n_checks = len(results)
                    matches = sum(1 for r in results if r["pass"])
                    # 根因②闭合:无 checks 可复算 → 复算分未定义(None),绝不默认 1.0/True。
                    # 旧实现 `else True`/`else 1.0` 让"checks 被丢空"的伪造分与复算值自洽 → 永不失配。
                    score_val = (matches / n_checks) if n_checks else None
                    is_correct = (matches == n_checks) if n_checks else None

                    key = (step.get("trajectory_id", ""), step.get("step_id", ""))
                    if key in saved:
                        s = saved[key]
                        if score_val is None:
                            mismatches.append({
                                "step_id": step.get("step_id", ""),
                                "saved": s.get("score"),
                                "recomputed": None,
                                "detail": "no checks to recompute; saved score unverifiable",
                            })
                        elif s["is_correct"] != is_correct or abs(s["score"] - score_val) > 1e-9:
                            mismatches.append({
                                "step_id": step.get("step_id", ""),
                                "saved": s["score"],
                                "recomputed": score_val,
                            })

            return {
                "run": run_dir.name,
                "n_steps": len(steps),
                "chain_ok": chain_ok,
                "chain_errors": chain_errors,
                "n_mismatches": len(mismatches),
                "mismatches": mismatches,
                "pass": chain_ok and len(mismatches) == 0,
            }


        def main():
            if len(sys.argv) < 2:
                print("Usage: python3 rescore.py <pack_dir>")
                sys.exit(1)

            pack_dir = pathlib.Path(sys.argv[1]).resolve()
            print(f"Rescore: {pack_dir}")

            sha_ok, sha_errors = verify_sha256(pack_dir)
            print(f"SHA256 verification: {'PASS' if sha_ok else 'FAIL'}")
            for e in sha_errors:
                print(f"  {e}")

            items_by_id = {}
            items_dir = pack_dir / "data" / "items"
            if items_dir.exists():
                for items_path in items_dir.rglob("items.jsonl"):
                    with open(items_path) as f:
                        for line in f:
                            if line.strip():
                                item = json.loads(line.strip())
                                items_by_id[item["item_id"]] = item

            runs_dir = pack_dir / "runs"
            scores_dir = pack_dir / "scores"
            all_pass = sha_ok

            if runs_dir.exists():
                for run_dir in sorted(runs_dir.iterdir()):
                    if run_dir.is_dir() and (run_dir / "steps.jsonl").exists():
                        result = rescore_run(run_dir, items_by_id, scores_dir)
                        status = "PASS" if result["pass"] else "FAIL"
                        print(f"Run {result['run']}: {status} (steps={result['n_steps']}, mismatches={result['n_mismatches']})")
                        if not result["pass"]:
                            all_pass = False
                            for e in result.get("chain_errors", []):
                                print(f"  chain: {e}")
                            for m in result.get("mismatches", []):
                                print(f"  mismatch: {m}")

            print(f"\\nOverall: {'PASS' if all_pass else 'FAIL'}")
            sys.exit(0 if all_pass else 1)


        if __name__ == "__main__":
            main()
    ''')

    (out_dir / "checkers.py").write_text(checkers_code)
    (out_dir / "registry.py").write_text(registry_code)
    (out_dir / "rescore.py").write_text(rescore_code)
    (out_dir / "__init__.py").write_text("")

    _verify_no_third_party(out_dir)


def _verify_no_third_party(out_dir: pathlib.Path):
    import ast
    stdlib_modules = {
        "json", "re", "hashlib", "pathlib", "sys", "os", "math",
        "statistics", "typing", "ast", "textwrap", "collections",
        "functools", "itertools", "abc", "io", "csv", "datetime",
    }
    internal_modules = {"checkers", "registry"}

    for py in out_dir.glob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    assert mod in stdlib_modules or mod in internal_modules, (
                        f"Third-party import '{alias.name}' in {py.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    mod = node.module.split(".")[0]
                    assert mod in stdlib_modules or mod in internal_modules, (
                        f"Third-party import 'from {node.module}' in {py.name}"
                    )
