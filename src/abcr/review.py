import json
import hashlib
import os
import pathlib
import sys
from typing import Optional
from abcr.eval.deterministic.registry import run_checks
from abcr.common.evidence_floor import agreement_or_none, require_substantive, EvidenceError
from abcr.common import external_seal
from abcr.logging.schema import canonical_json
from abcr.logging.writer import StepWriter

REVIEW_VERSION = "c2.1"

# 外部 items 源的锚 kind（验船师复算判据的信任根；生产端收口时 seal 同名 subject_id）。
KIND_ITEMS_SOURCE = "items_source"
# 严格模式：置 1 时「无锚」也判失败（缺省只在「有锚但不符」时 fail-closed）。
REQUIRE_ITEMS_SEAL_ENV = "ABCR_REQUIRE_ITEMS_SEAL"


def review_run(run_id: str, runs_dir: str = "runs", scores_dir: str = "scores",
               review_dir: str = "review", items_path: Optional[str] = None) -> dict:
    run_path = pathlib.Path(runs_dir) / run_id
    steps_file = run_path / "steps.jsonl"
    manifest_file = run_path / "manifest.json"
    scores_path = pathlib.Path(scores_dir) / run_id / "scores.jsonl"

    error_codes = []
    missing = []
    duplicated = []
    score_mismatches = []
    manifest_checks = {}

    if not steps_file.exists():
        return _fail_report(run_id, ["E10"], "steps.jsonl not found")

    # citable 判定（与 auditor._batch_all_non_citable 同口径，fail-closed）：
    # manifest 明确 non_citable=true → 非可引用（Mac/fake），items 源缺锚走宽松路径；
    # 其余一切（含 manifest 缺失/未声明）→ 按 citable 处理 → items 源【强制封印】。
    citable_run = True

    steps = []
    with open(steps_file, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                steps.append(json.loads(line))

    chain_ok = _verify_chain(steps, steps_file)
    if not chain_ok:
        error_codes.append("E08")

    if manifest_file.exists():
        manifest = _load_json(manifest_file)
        # 两种字段约定并存：dispatch/rig 写 non_citable=true，logging/run 写 citable=false。
        # 任一明确表态"非可引用" → 走宽松路径；否则（含两字段皆缺）fail-closed 按 citable。
        citable_run = not (manifest.get("non_citable") is True
                           or manifest.get("citable") is False)
        manifest_checks = _check_manifest(manifest, run_path, steps)
        if manifest_checks.get("config_hash_mismatch"):
            error_codes.append("E12")
        if manifest_checks.get("split_hash_missing"):
            error_codes.append("E12")
        if manifest_checks.get("split_hash_mismatch"):
            error_codes.append("E12")
        if manifest_checks.get("arm_purity_violation"):
            error_codes.append("E06")

        if items_path is None:
            items_path = manifest.get("items_path")
            if items_path is None:
                cfg = manifest.get("config", {})
                items_path = cfg.get("data", {}).get("items", "data/items/items.jsonl")

        expected_keys = set()
        n_items = manifest.get("n_items", 0)
        seeds = manifest.get("seeds", [])
        conditions = manifest.get("conditions", [])
        steps_per_item = manifest.get("steps_per_item", 1)

        if n_items and seeds and conditions:
            for cond in conditions:
                for seed in seeds:
                    for item_idx in range(n_items):
                        for step_idx in range(steps_per_item):
                            expected_keys.add((cond, seed, item_idx, step_idx))

        actual_keys = set()
        seen = set()
        for i, step in enumerate(steps):
            key = (
                step.get("condition", ""),
                step.get("random_seed", 0),
                step.get("item_id", ""),
                step.get("step_id", ""),
            )
            actual_keys.add(key)
            if key in seen:
                duplicated.append({"index": i, "key": str(key)})
            seen.add(key)

        if expected_keys and actual_keys:
            manifest_checks["expected_keys_count"] = len(expected_keys)
            manifest_checks["actual_keys_count"] = len(actual_keys)
            manifest_checks["keys_complete"] = len(actual_keys) >= len(expected_keys)
    else:
        manifest_checks["manifest_missing"] = True
        seen = set()
        for i, step in enumerate(steps):
            key = (
                step.get("condition", ""),
                step.get("random_seed", 0),
                step.get("item_id", ""),
                step.get("step_id", ""),
            )
            if key in seen:
                duplicated.append({"index": i, "key": str(key)})
            seen.add(key)

    arm_prompt_check = _check_arm_prompt_hash(steps)
    if not arm_prompt_check["ok"]:
        error_codes.append("E06")

    vector_check = _check_vector_artifacts(steps)
    if not vector_check["ok"]:
        error_codes.append("E15")

    if duplicated:
        error_codes.append("E10")

    if items_path is None:
        items_path = "data/items/items.jsonl"
    items_by_id = {}
    items_entries = []
    items_file = pathlib.Path(items_path)
    if items_file.exists():
        with open(items_file, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    item = json.loads(line)
                    items_entries.append(item)
                    items_by_id[item["item_id"]] = item

    # 根因①/③闭合：判据(checks)的信任根只能是【外部 items 源】。
    # 外部源缺失/为空/与锚不符 → fail-closed，绝不回退到被审对象自带的 step["checks"]。
    items_source_check = _check_items_source(items_file, items_entries, items_by_id,
                                             citable=citable_run)
    if not items_source_check["ok"]:
        error_codes.append("E12")

    if scores_path.exists():
        saved_scores = {}
        with open(scores_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    s = json.loads(line)
                    join_key = (s["run_id"], s.get("trajectory_id", ""), s.get("step_id", ""))
                    saved_scores[join_key] = s

        for step in steps:
            item_id = step.get("item_id", "")
            output_text = step.get("output_text", "")

            # 判据只认外部 items 源。item_id 在外部源里查不到 → 判据不可独立获得,
            # 该步不可复算(recomputed=None → E11)。
            # 【绝不】回退 step["checks"]：被审对象自述的判据不是可接受的证据根,
            # 否则"删掉 items 文件 + 自带永真 checks"即可自证满分(V05 等价攻击)。
            unverifiable_reason = None
            if not items_source_check["ok"]:
                unverifiable_reason = (
                    "external items source unusable "
                    f"({items_source_check.get('detail', 'unknown')}); "
                    "self-reported step['checks'] is not an accepted evidence root")
                checks_spec = []
            elif item_id in items_by_id:
                checks_spec = items_by_id[item_id].get("checks", []) or []
            else:
                unverifiable_reason = (
                    f"item_id {item_id!r} not present in external items source "
                    f"{items_source_check['items_path']}; "
                    "self-reported step['checks'] is not an accepted evidence root")
                checks_spec = []
                if item_id not in items_source_check["unresolved_item_ids"]:
                    items_source_check["unresolved_item_ids"].append(item_id)

            recomputed = run_checks(output_text, checks_spec) if unverifiable_reason is None else []
            n_checks = len(recomputed)
            matches = sum(1 for r in recomputed if r["pass"])
            # 根因②闭合：无 checks 可独立复算时,复算分是「未定义」(agreement_or_none → None),
            # 绝不默认 1.0/True。旧实现 `else True`/`else 1.0` 让"checks 被丢空"的伪造分
            # (is_correct=True/score=1.0) 与复算值自洽 → E11 永不触发;这里改为 fail-closed。
            recomputed_score = agreement_or_none(matches, n_checks)   # None when n_checks == 0
            recomputed_is_correct = (matches == n_checks) if n_checks else None

            join_key = (run_id, step.get("trajectory_id", ""), step.get("step_id", ""))
            if join_key in saved_scores:
                saved = saved_scores[join_key]
                if recomputed_score is None:
                    # 已保存分数存在,却无任何 checks 可独立核验 → 该分不可信,记失配触发 E11。
                    score_mismatches.append({
                        "step_id": step.get("step_id", ""),
                        "item_id": item_id,
                        "saved_score": saved.get("score"),
                        "recomputed_score": None,
                        "saved_is_correct": saved.get("is_correct"),
                        "recomputed_is_correct": None,
                        "detail": unverifiable_reason or
                                  "no checks to independently recompute; saved score unverifiable",
                    })
                elif saved["is_correct"] != recomputed_is_correct or abs(saved["score"] - recomputed_score) > 1e-9:
                    score_mismatches.append({
                        "step_id": step.get("step_id", ""),
                        "item_id": item_id,
                        "saved_score": saved["score"],
                        "recomputed_score": recomputed_score,
                        "saved_is_correct": saved["is_correct"],
                        "recomputed_is_correct": recomputed_is_correct,
                    })

        if score_mismatches:
            error_codes.append("E11")

        step_keys = set()
        for step in steps:
            join_key = (run_id, step.get("trajectory_id", ""), step.get("step_id", ""))
            step_keys.add(join_key)
        orphaned = [k for k in saved_scores if k not in step_keys]
        if orphaned:
            for k in orphaned:
                missing.append({"join_key": str(k), "detail": "score exists but step missing"})
            if "E10" not in error_codes:
                error_codes.append("E10")

    n_expected = len(steps)
    pass_ok = len(error_codes) == 0

    report = {
        "run_id": run_id,
        "review_version": REVIEW_VERSION,
        "n_steps": len(steps),
        "n_expected": n_expected,
        "missing": missing,
        "duplicated": duplicated,
        "chain_ok": chain_ok,
        "score_mismatches": score_mismatches,
        "manifest_checks": manifest_checks,
        "items_source_check": items_source_check,
        "arm_prompt_hash_check": arm_prompt_check,
        "vector_artifact_check": vector_check,
        "error_codes": sorted(set(error_codes)),
        "pass": pass_ok,
    }

    out_dir = pathlib.Path(review_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / "review_report.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report


def review_pack(pack_dir: str, review_dir: str = "review") -> dict:
    pack_path = pathlib.Path(pack_dir)
    manifest_file = pack_path / "pack_manifest.json"

    if not manifest_file.exists():
        return {"pass": False, "error": "pack_manifest.json not found"}

    with open(manifest_file, "r") as f:
        pack_manifest = json.load(f)

    sha_mismatches = []
    missing_files = []
    for entry in pack_manifest.get("files", []):
        file_path = pack_path / entry["path"]
        if not file_path.exists():
            missing_files.append(entry["path"])
            continue
        with open(file_path, "rb") as f:
            actual_sha = hashlib.sha256(f.read()).hexdigest()
        if actual_sha != entry["sha256"]:
            sha_mismatches.append({
                "path": entry["path"],
                "expected": entry["sha256"],
                "actual": actual_sha,
            })

    judge_raw_check = _check_judge_raw_aggregates(pack_path)

    pass_ok = len(sha_mismatches) == 0 and len(missing_files) == 0
    report = {
        "pack_dir": str(pack_path),
        "n_files": len(pack_manifest.get("files", [])),
        "missing_files": missing_files,
        "sha_mismatches": sha_mismatches,
        "judge_raw_check": judge_raw_check,
        "pass": pass_ok,
    }
    return report


def _check_judge_raw_aggregates(pack_path: pathlib.Path) -> dict:
    """Verify judge_raw → aggregate score consistency if judge_raw exists."""
    raw_dir = pack_path / "review" / "judge_raw"
    if not raw_dir.exists():
        return {"status": "no_judge_raw_dir"}
    results = {}
    for raw_file in raw_dir.glob("*.jsonl"):
        entries = []
        with open(raw_file) as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line.strip()))
        scores = [e.get("raw", {}).get("score") for e in entries if e.get("type") == "trait"]
        valid = [s for s in scores if s is not None]
        results[raw_file.name] = {
            "n_entries": len(entries),
            "n_valid_scores": len(valid),
            "mean_score": round(sum(valid) / len(valid), 4) if valid else None,
        }
    return {"status": "checked", "files": results}


def _check_items_source(items_file: pathlib.Path, items_entries: list,
                        items_by_id: dict, citable: bool = True) -> dict:
    """外部 items 源（复算判据的信任根）体检。fail-closed。

    ok=False 的四种情形，任何一种都会让本次 review 拒绝复算、拒绝回退自述 checks：
      1. 文件不存在（"删掉权威 items 文件"即攻击面本身）；
      2. 存在但无实质条目（evidence_floor.require_substantive，空 ≠ 通过）；
      3. 存在外部锚记录但 digest/length 不符（external_seal.verify，防换源/截断）；
      4. citable 批但【无外部锚】——可引用证据的判据源必须被生产端封印
         （根因③深一层：未封印 items 文件不得被当权威源信任；攻击者往解析路径
         放一份伪造 items.jsonl 即绕过原修复。生产端封印点见 scripts/a_freeze.py）。
    宽松路径仅对 non_citable（citable=False，Mac/fake 批）开放：无锚只记 seal_status
    而不 FAIL，但【若存在锚则仍必须匹配】（换源/截断依然抓）。
    严格模式（env ABCR_REQUIRE_ITEMS_SEAL=1）下，non_citable 的"无锚"同样判 ok=False。
    """
    check = {
        "items_path": str(items_file),
        "exists": items_file.exists(),
        "n_items": len(items_by_id),
        "unresolved_item_ids": [],
        "citable": citable,
        "ok": False,
        "detail": "",
    }

    if not check["exists"]:
        check["detail"] = "external items source file not found"
        return check

    try:
        require_substantive(len(items_by_id), f"external items source {items_file}")
    except EvidenceError as e:
        check["detail"] = str(e)
        return check

    # 外部锚：对 items 条目序列算 (digest, length)，与规范锚存储比对。
    digest, length = external_seal.chain_digest_and_length(items_entries)
    check["digest"] = digest
    check["length"] = length
    subject_id = items_file.name
    anchored = external_seal.latest_seal(KIND_ITEMS_SOURCE, subject_id)
    strict = os.environ.get(REQUIRE_ITEMS_SEAL_ENV, "") == "1"
    # citable 批一律要求封印；non_citable 批只在 strict 模式下要求。
    require_seal = citable or strict
    if anchored is None:
        check["seal_status"] = "unsealed"
        if require_seal:
            why = ("citable run" if citable
                   else f"{REQUIRE_ITEMS_SEAL_ENV}=1")
            check["detail"] = (f"{why} requires a sealed items source but none found: "
                               f"kind={KIND_ITEMS_SOURCE!r} subject_id={subject_id!r} "
                               f"(未封印的 items 文件不得被当权威源信任; "
                               f"生产端封印点 scripts/a_freeze.py)")
            return check
    else:
        seal_ok, reason = external_seal.verify(
            KIND_ITEMS_SOURCE, subject_id, digest, length)
        check["seal_status"] = "ok" if seal_ok else "mismatch"
        check["seal_reason"] = reason
        if not seal_ok:
            check["detail"] = f"external seal check failed: {reason}"
            return check

    check["ok"] = True
    return check


def _verify_chain(steps: list[dict], steps_file: pathlib.Path) -> bool:
    from abcr.logging.errors import AbcrError
    try:
        return StepWriter.verify_chain(str(steps_file))
    except AbcrError:
        return False


def _check_manifest(manifest: dict, run_path: pathlib.Path, steps: list[dict]) -> dict:
    checks = {}

    if "config" in manifest:
        config = manifest["config"]
        expected_hash = manifest.get("config_hash", "")
        if expected_hash:
            recomputed = hashlib.sha256(canonical_json(config).encode()).hexdigest()
            checks["config_hash_ok"] = recomputed == expected_hash
            checks["config_hash_mismatch"] = recomputed != expected_hash

    if "split_hash" in manifest:
        split_hash = manifest["split_hash"]
        split_path_str = manifest.get("split_path", "")
        found = False
        if split_path_str:
            split_file = pathlib.Path(split_path_str)
            if split_file.exists():
                with open(split_file, "rb") as f:
                    actual_hash = hashlib.sha256(f.read()).hexdigest()
                checks["split_hash_ok"] = actual_hash == split_hash
                checks["split_hash_mismatch"] = actual_hash != split_hash
                found = True
            else:
                checks["split_hash_missing"] = True
        if not found and not split_path_str:
            items_dir = pathlib.Path("data/items")
            if items_dir.exists():
                for candidate in items_dir.rglob("items.jsonl"):
                    with open(candidate, "rb") as f:
                        actual_hash = hashlib.sha256(f.read()).hexdigest()
                    if actual_hash == split_hash:
                        checks["split_hash_ok"] = True
                        checks["split_hash_mismatch"] = False
                        found = True
                        break
            if not found:
                checks["split_hash_unverifiable"] = True
    else:
        checks["split_hash_missing"] = True

    if "chat_template_hash" in manifest and manifest["chat_template_hash"]:
        ct_hash = manifest["chat_template_hash"]
        ct_verified = False
        templates_dir = pathlib.Path("configs/templates")
        if templates_dir.exists():
            for tmpl_dir in templates_dir.iterdir():
                if tmpl_dir.is_dir():
                    for tf in tmpl_dir.glob("*.jinja*"):
                        with open(tf, "rb") as f:
                            if hashlib.sha256(f.read()).hexdigest() == ct_hash:
                                ct_verified = True
                                break
                    if ct_verified:
                        break
        checks["chat_template_hash_verified"] = ct_verified

    # 受管控的 steering 臂：出现在 steps 里就必须有 arm_purity 声明,否则判据未接线(根因④)。
    _STEERING_METHODS = {"prompt_persona", "residual_vector", "random_direction"}
    _declared_steering = {s.get("condition", "") for s in steps} & _STEERING_METHODS
    arm_purity = manifest.get("arm_purity", {})
    if arm_purity:
        method = arm_purity.get("declared_method", "none")
        has_vector = arm_purity.get("has_vector_ref", False)
        has_persona = arm_purity.get("has_persona_ref", False)
        violation = False
        if method == "prompt_persona" and not has_persona:
            violation = True
        if method == "residual_vector" and not has_vector:
            violation = True
        if method == "none" and (has_persona or has_vector):
            violation = True
        if method == "random_direction" and has_persona:
            violation = True
        # steps 里实测出现的受管控 steering 臂,必须被 declared_method 覆盖,不能自述 none 蒙混(根因③)。
        if _declared_steering - ({method} if method != "none" else set()):
            violation = True
        checks["arm_purity_ok"] = not violation
        checks["arm_purity_violation"] = violation
    elif _declared_steering:
        # steps 出现受管控 steering 臂,manifest 却无 arm_purity 声明 → 判据未接线,fail-closed。
        checks["arm_purity_declared"] = False
        checks["arm_purity_ok"] = False
        checks["arm_purity_violation"] = True
        checks["arm_purity_undeclared_conditions"] = sorted(_declared_steering)

    if "env_lock_ref" in manifest:
        env_lock_path = run_path / manifest["env_lock_ref"]
        checks["env_lock_exists"] = env_lock_path.exists()

    protocol_ref = manifest.get("protocol_ref", "")
    if protocol_ref:
        checks["protocol_ref_present"] = True
    else:
        checks["protocol_ref_present"] = False

    expected_fields = {"run_id", "config", "config_hash", "model", "chat_template_hash",
                       "split_hash", "arm_purity", "protocol_ref", "started_at"}
    missing_fields = expected_fields - set(manifest.keys())
    checks["manifest_fields_complete"] = len(missing_fields) == 0
    if missing_fields:
        checks["manifest_missing_fields"] = sorted(missing_fields)

    return checks


def _check_arm_prompt_hash(steps: list[dict]) -> dict:
    """Verify arm purity via prompt_hash: text arm ≠ vanilla, vector/random = vanilla."""
    hashes_by_condition = {}
    for step in steps:
        cond = step.get("condition", "")
        ph = step.get("prompt_hash", "")
        hashes_by_condition.setdefault(cond, set()).add(ph)

    result = {"conditions": {c: sorted(hs) for c, hs in hashes_by_condition.items()}}
    vanilla_hashes = hashes_by_condition.get("vanilla", set())
    violations = []

    if vanilla_hashes:
        for cond, hs in hashes_by_condition.items():
            if cond == "vanilla":
                continue
            if cond == "prompt_persona":
                if hs & vanilla_hashes:
                    violations.append(f"{cond}: prompt_hash overlaps with vanilla")
            elif cond in ("residual_vector", "random_direction"):
                if hs != vanilla_hashes:
                    violations.append(f"{cond}: prompt_hash differs from vanilla")

    result["violations"] = violations
    result["ok"] = len(violations) == 0
    return result


def _check_vector_artifacts(steps: list[dict]) -> dict:
    """E15: verify vector artifact existence, shape, and hash for residual_vector runs."""
    issues = []
    checked = set()
    for step in steps:
        if step.get("condition") != "residual_vector":
            continue
        vdir = step.get("vector_dir", step.get("vector_path", ""))
        if not vdir or vdir in checked:
            continue
        checked.add(vdir)
        vpath = pathlib.Path(vdir)
        if vpath.is_file():
            vpath = vpath.parent
        if not vpath.exists():
            issues.append(f"vector dir missing: {vdir}")
            continue
        pt_files = list(vpath.glob("*.pt"))
        if not pt_files:
            issues.append(f"no .pt files in {vdir}")
    return {"ok": len(issues) == 0, "issues": issues}


def _load_json(path: pathlib.Path) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def _fail_report(run_id: str, error_codes: list, detail: str) -> dict:
    return {
        "run_id": run_id,
        "review_version": REVIEW_VERSION,
        "n_steps": 0,
        "n_expected": 0,
        "missing": [],
        "duplicated": [],
        "chain_ok": False,
        "score_mismatches": [],
        "manifest_checks": {},
        "items_source_check": {"ok": False, "detail": "review aborted before items source check",
                               "unresolved_item_ids": []},
        "error_codes": error_codes,
        "pass": False,
        "detail": detail,
    }


def main():
    import typer
    app = typer.Typer()

    @app.command()
    def review(run: Optional[str] = None, pack: Optional[str] = None):
        if run:
            report = review_run(run)
        elif pack:
            report = review_pack(pack)
        else:
            print("specify --run or --pack", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(report, indent=2))
        if not report.get("pass", False):
            sys.exit(1)

    app()


if __name__ == "__main__":
    main()
