import json
import hashlib
import pathlib
import tempfile
import shutil
import pytest
from abcr.eval.deterministic.registry import run_checks
from abcr.review import review_run


def _canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _make_step(item_id: str, condition: str, seed: int, step_id: str,
               output_text: str, checks: list, prev_hash: str) -> tuple[dict, str]:
    step = {
        "item_id": item_id,
        "condition": condition,
        "random_seed": seed,
        "step_id": step_id,
        "trajectory_id": f"traj_{condition}_{seed}",
        "output_text": output_text,
        "checks": checks,
        "output_tokens": len(output_text.split()),
    }
    step["prev_hash"] = prev_hash
    # Match A's canonical_json: only exclude entry_hash, keep prev_hash
    entry_data = {k: v for k, v in step.items() if k != "entry_hash"}
    payload = _canonical_json(entry_data) + prev_hash
    entry_hash = hashlib.sha256(payload.encode()).hexdigest()
    step["entry_hash"] = entry_hash
    return step, entry_hash


def _write_steps(steps: list[dict], path: pathlib.Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for s in steps:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


def _write_scores(steps: list[dict], run_id: str, scores_dir: pathlib.Path):
    out = scores_dir / run_id
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "scores.jsonl", "w") as f:
        for step in steps:
            checks_spec = step.get("checks", [])
            output_text = step.get("output_text", "")
            check_results = run_checks(output_text, checks_spec)
            is_correct = all(r["pass"] for r in check_results) if check_results else True
            score_val = (sum(1 for r in check_results if r["pass"]) / len(check_results)) if check_results else 1.0
            entry = {
                "run_id": run_id,
                "trajectory_id": step.get("trajectory_id", ""),
                "step_id": step.get("step_id", ""),
                "item_id": step.get("item_id", ""),
                "condition": step.get("condition", ""),
                "random_seed": step.get("random_seed", 0),
                "scorer_version": "c1.0",
                "checks": check_results,
                "is_correct": is_correct,
                "score": score_val,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _write_items(steps: list[dict], items_file: pathlib.Path):
    """外部权威 items 源：review 复算判据的唯一信任根（不得由 steps 自述）。"""
    items_file.parent.mkdir(parents=True, exist_ok=True)
    seen = {}
    for s in steps:
        seen.setdefault(s["item_id"], s.get("checks", []))
    with open(items_file, "w") as f:
        for item_id, checks in seen.items():
            f.write(json.dumps({"item_id": item_id, "checks": checks},
                               ensure_ascii=False) + "\n")


def _write_manifest(run_id: str, steps: list, run_dir: pathlib.Path, split_path: str = "",
                    items_path: str = "", non_citable: bool = True):
    config = {"model": "tinyqwen", "run_id": run_id}
    config_hash = hashlib.sha256(_canonical_json(config).encode()).hexdigest()
    manifest = {
        "run_id": run_id,
        "config": config,
        "config_hash": config_hash,
        "n_items": len(set(s["item_id"] for s in steps)),
        "seeds": sorted(set(s["random_seed"] for s in steps)),
        "conditions": sorted(set(s["condition"] for s in steps)),
        "steps_per_item": 1,
        # 合成 Mac 数据一律 non_citable（呈现纪律）→ items 源缺锚走宽松路径。
        # citable 路径（non_citable=False）由 TestCitableItemsSealEnforced 专测覆盖。
        "non_citable": non_citable,
    }
    if items_path:
        manifest["items_path"] = items_path
    if split_path:
        manifest["split_path"] = split_path
        sp = pathlib.Path(split_path)
        if sp.exists():
            with open(sp, "rb") as f:
                manifest["split_hash"] = hashlib.sha256(f.read()).hexdigest()
        else:
            manifest["split_hash"] = "deadbeef"
    with open(run_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)


def _build_synthetic_run(tmp: pathlib.Path, run_id: str = "syn_test",
                         non_citable: bool = True):
    runs_dir = tmp / "runs"
    scores_dir = tmp / "scores"
    review_dir = tmp / "review"
    items_dir = tmp / "data" / "items"
    splits_dir = tmp / "data" / "splits"
    for d in [runs_dir, scores_dir, review_dir, items_dir, splits_dir]:
        d.mkdir(parents=True, exist_ok=True)

    split_file = splits_dir / "dev.jsonl"
    split_file.write_text('{"split": "dev"}\n')

    checks_list = [
        [{"name": "keywords_existence", "kwargs": {"keywords": ["hello"]}}],
        [{"name": "length_words", "kwargs": {"num_words": 3, "relation": "at least"}}],
    ]
    responses = [
        "hello world today",
        "short",
        "hello from the other side of the world",
        "just two",
        "hello hello hello hello hello words here",
        "one",
        "hello my friend how are you",
        "hello beautiful day ahead",
        "tiny",
        "hello final test run complete",
    ]

    steps = []
    prev_hash = "0" * 64
    for i in range(10):
        item_id = f"item_{i:03d}"
        condition = "vanilla" if i < 5 else "steered"
        seed = 42
        step_id = f"step_{i:03d}"
        checks = checks_list[i % 2]
        step, prev_hash = _make_step(item_id, condition, seed, step_id, responses[i], checks, prev_hash)
        steps.append(step)

    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    items_file = items_dir / "items.jsonl"
    _write_items(steps, items_file)
    _write_steps(steps, run_dir / "steps.jsonl")
    _write_scores(steps, run_id, scores_dir)
    _write_manifest(run_id, steps, run_dir, str(split_file), items_path=str(items_file),
                    non_citable=non_citable)

    return steps, runs_dir, scores_dir, review_dir


class TestNoFault:
    def test_clean_run_passes(self, tmp_path):
        steps, runs_dir, scores_dir, review_dir = _build_synthetic_run(tmp_path)
        report = review_run(
            "syn_test",
            runs_dir=str(runs_dir),
            scores_dir=str(scores_dir),
            review_dir=str(review_dir),
        )
        assert report["pass"] is True
        assert report["chain_ok"] is True
        assert len(report["error_codes"]) == 0
        assert len(report["score_mismatches"]) == 0


class TestFaultInjection:
    def test_tampered_field_breaks_chain(self, tmp_path):
        steps, runs_dir, scores_dir, review_dir = _build_synthetic_run(tmp_path)
        steps_file = runs_dir / "syn_test" / "steps.jsonl"
        lines = steps_file.read_text().strip().split("\n")
        tampered = json.loads(lines[3])
        tampered["output_text"] = "TAMPERED OUTPUT"
        lines[3] = json.dumps(tampered, ensure_ascii=False)
        steps_file.write_text("\n".join(lines) + "\n")

        report = review_run(
            "syn_test",
            runs_dir=str(runs_dir),
            scores_dir=str(scores_dir),
            review_dir=str(review_dir),
        )
        assert report["pass"] is False
        assert "E08" in report["error_codes"]

    def test_deleted_last_line_detected(self, tmp_path):
        steps, runs_dir, scores_dir, review_dir = _build_synthetic_run(tmp_path)
        steps_file = runs_dir / "syn_test" / "steps.jsonl"
        lines = steps_file.read_text().strip().split("\n")
        lines = lines[:-1]
        steps_file.write_text("\n".join(lines) + "\n")

        report = review_run(
            "syn_test",
            runs_dir=str(runs_dir),
            scores_dir=str(scores_dir),
            review_dir=str(review_dir),
        )
        assert report["pass"] is False
        assert any(code in report["error_codes"] for code in ["E10", "E08"])

    def test_forged_score_detected(self, tmp_path):
        steps, runs_dir, scores_dir, review_dir = _build_synthetic_run(tmp_path)
        scores_file = scores_dir / "syn_test" / "scores.jsonl"
        lines = scores_file.read_text().strip().split("\n")
        forged = json.loads(lines[2])
        forged["score"] = 0.999
        forged["is_correct"] = not forged["is_correct"]
        lines[2] = json.dumps(forged, ensure_ascii=False)
        scores_file.write_text("\n".join(lines) + "\n")

        report = review_run(
            "syn_test",
            runs_dir=str(runs_dir),
            scores_dir=str(scores_dir),
            review_dir=str(review_dir),
        )
        assert report["pass"] is False
        assert "E11" in report["error_codes"]
        assert len(report["score_mismatches"]) >= 1

    def test_missing_split_hash_detected(self, tmp_path):
        steps, runs_dir, scores_dir, review_dir = _build_synthetic_run(tmp_path)
        manifest_file = runs_dir / "syn_test" / "manifest.json"
        manifest = json.loads(manifest_file.read_text())
        del manifest["split_hash"]
        manifest_file.write_text(json.dumps(manifest, indent=2))

        report = review_run(
            "syn_test",
            runs_dir=str(runs_dir),
            scores_dir=str(scores_dir),
            review_dir=str(review_dir),
        )
        assert report["pass"] is False
        assert "E12" in report["error_codes"]


class TestSelfReportedChecksRejected:
    """V05 根因①③：权威 items 源缺失时不得回退到被审对象自述的 step['checks']。"""

    @staticmethod
    def _forge_all_full_marks(scores_dir: pathlib.Path, run_id: str = "syn_test"):
        scores_file = scores_dir / run_id / "scores.jsonl"
        lines = scores_file.read_text().strip().split("\n")
        out = []
        for ln in lines:
            s = json.loads(ln)
            s["score"] = 1.0
            s["is_correct"] = True
            out.append(json.dumps(s, ensure_ascii=False))
        scores_file.write_text("\n".join(out) + "\n")

    def _items_file(self, runs_dir: pathlib.Path) -> pathlib.Path:
        manifest = json.loads((runs_dir / "syn_test" / "manifest.json").read_text())
        return pathlib.Path(manifest["items_path"])

    def test_deleted_items_file_fails_closed_not_self_report(self, tmp_path):
        """删掉权威 items 文件 + 伪造全 1.0 分 + steps 自带永真 checks → 必须 FAIL。"""
        steps, runs_dir, scores_dir, review_dir = _build_synthetic_run(tmp_path)
        self._items_file(runs_dir).unlink()
        # 运动员在 steps 里自带的 checks 依然存在（原始 steps 就带 checks）
        self._forge_all_full_marks(scores_dir)

        report = review_run(
            "syn_test", runs_dir=str(runs_dir), scores_dir=str(scores_dir),
            review_dir=str(review_dir),
        )
        assert report["pass"] is False
        assert "E12" in report["error_codes"]
        assert "E11" in report["error_codes"]
        assert report["items_source_check"]["ok"] is False
        assert report["items_source_check"]["exists"] is False
        # 每一步都因"判据不可独立获得"记失配，而不是被自述 checks 判为满分
        assert len(report["score_mismatches"]) == len(steps)
        for m in report["score_mismatches"]:
            assert m["recomputed_score"] is None
            assert "not an accepted evidence root" in m["detail"]

    def test_empty_items_file_fails_closed(self, tmp_path):
        steps, runs_dir, scores_dir, review_dir = _build_synthetic_run(tmp_path)
        self._items_file(runs_dir).write_text("")
        self._forge_all_full_marks(scores_dir)

        report = review_run(
            "syn_test", runs_dir=str(runs_dir), scores_dir=str(scores_dir),
            review_dir=str(review_dir),
        )
        assert report["pass"] is False
        assert "E12" in report["error_codes"]
        assert "insufficient evidence" in report["items_source_check"]["detail"]

    def test_item_missing_from_items_source_is_unverifiable(self, tmp_path):
        """items 源存在但少了某个 item_id → 该步不可复算，绝不用 step['checks'] 顶上。"""
        steps, runs_dir, scores_dir, review_dir = _build_synthetic_run(tmp_path)
        items_file = self._items_file(runs_dir)
        kept = [ln for ln in items_file.read_text().strip().split("\n")
                if json.loads(ln)["item_id"] != "item_001"]
        items_file.write_text("\n".join(kept) + "\n")
        self._forge_all_full_marks(scores_dir)

        report = review_run(
            "syn_test", runs_dir=str(runs_dir), scores_dir=str(scores_dir),
            review_dir=str(review_dir),
        )
        assert report["pass"] is False
        assert "E11" in report["error_codes"]
        assert "item_001" in report["items_source_check"]["unresolved_item_ids"]
        unverifiable = [m for m in report["score_mismatches"]
                        if m["item_id"] == "item_001"]
        assert unverifiable and unverifiable[0]["recomputed_score"] is None

    def test_sealed_items_source_swap_detected(self, tmp_path, monkeypatch):
        """外部锚已封 items 源：换源/改判据（digest 变化）→ E12 fail-closed（接线 external_seal）。"""
        from abcr.common import external_seal

        monkeypatch.setenv(external_seal.ANCHOR_STORE_ENV,
                           str(tmp_path / "anchors" / "seals.jsonl"))
        steps, runs_dir, scores_dir, review_dir = _build_synthetic_run(tmp_path)
        items_file = self._items_file(runs_dir)
        entries = [json.loads(ln) for ln in items_file.read_text().strip().split("\n")]
        digest, length = external_seal.chain_digest_and_length(entries)
        external_seal.seal("items_source", items_file.name, digest, length)

        # 封锚后的干净运行仍通过
        ok_report = review_run(
            "syn_test", runs_dir=str(runs_dir), scores_dir=str(scores_dir),
            review_dir=str(review_dir),
        )
        assert ok_report["pass"] is True
        assert ok_report["items_source_check"]["seal_status"] == "ok"

        # 把 items 源换成"永真判据"版本（自证满分用），digest 变 → 锚不符
        items_file.write_text("\n".join(
            json.dumps({"item_id": e["item_id"], "checks": []}, ensure_ascii=False)
            for e in entries) + "\n")
        self._forge_all_full_marks(scores_dir)
        report = review_run(
            "syn_test", runs_dir=str(runs_dir), scores_dir=str(scores_dir),
            review_dir=str(review_dir),
        )
        assert report["pass"] is False
        assert "E12" in report["error_codes"]
        assert report["items_source_check"]["seal_status"] == "mismatch"


class TestCitableItemsSealEnforced:
    """V05 根因③深一层：未封印的 items 文件不得被 citable 批当权威源信任。

    攻击者不改 step['checks']（已闭合），而是往解析路径放一份伪造 items.jsonl。
    citable 批必须【强制要求 items 源有匹配封印】，缺锚 fail-closed。
    non_citable（Mac/fake）批走宽松路径以保冒烟贯通——由本文件其余测试覆盖。
    """

    def _items_file(self, runs_dir: pathlib.Path) -> pathlib.Path:
        manifest = json.loads((runs_dir / "syn_test" / "manifest.json").read_text())
        return pathlib.Path(manifest["items_path"])

    def test_citable_unsealed_items_fails_closed(self, tmp_path, monkeypatch):
        """citable 批 + 未封印 items 源（伪造放路径即可）→ E12 fail-closed。"""
        from abcr.common import external_seal
        monkeypatch.setenv(external_seal.ANCHOR_STORE_ENV,
                           str(tmp_path / "anchors" / "seals.jsonl"))
        # non_citable=False → citable 批；不封印任何 items 源
        steps, runs_dir, scores_dir, review_dir = _build_synthetic_run(
            tmp_path, non_citable=False)
        report = review_run(
            "syn_test", runs_dir=str(runs_dir), scores_dir=str(scores_dir),
            review_dir=str(review_dir),
        )
        assert report["pass"] is False
        assert "E12" in report["error_codes"]
        assert report["items_source_check"]["ok"] is False
        assert report["items_source_check"]["seal_status"] == "unsealed"
        assert report["items_source_check"]["citable"] is True
        assert "sealed items source" in report["items_source_check"]["detail"]

    def test_citable_forged_items_at_path_fails_closed(self, tmp_path, monkeypatch):
        """攻击复现：往解析到的 items 路径放一份伪造(永真判据)items.jsonl，
        citable 批因缺匹配封印而 FAIL（不再被当权威源信任）。"""
        from abcr.common import external_seal
        monkeypatch.setenv(external_seal.ANCHOR_STORE_ENV,
                           str(tmp_path / "anchors" / "seals.jsonl"))
        steps, runs_dir, scores_dir, review_dir = _build_synthetic_run(
            tmp_path, non_citable=False)
        items_file = self._items_file(runs_dir)
        # 伪造：把判据全部清空（永真）+ 全 1.0 分自证满分
        entries = [json.loads(ln) for ln in items_file.read_text().strip().split("\n")]
        items_file.write_text("\n".join(
            json.dumps({"item_id": e["item_id"], "checks": []}, ensure_ascii=False)
            for e in entries) + "\n")
        TestSelfReportedChecksRejected._forge_all_full_marks(scores_dir)
        report = review_run(
            "syn_test", runs_dir=str(runs_dir), scores_dir=str(scores_dir),
            review_dir=str(review_dir),
        )
        assert report["pass"] is False
        assert "E12" in report["error_codes"]
        assert report["items_source_check"]["seal_status"] == "unsealed"

    def test_citable_with_matching_seal_passes(self, tmp_path, monkeypatch):
        """citable 批 + 生产端已封印匹配 items 源 → 正常通过（封印是有锚可验的）。"""
        from abcr.common import external_seal
        monkeypatch.setenv(external_seal.ANCHOR_STORE_ENV,
                           str(tmp_path / "anchors" / "seals.jsonl"))
        steps, runs_dir, scores_dir, review_dir = _build_synthetic_run(
            tmp_path, non_citable=False)
        items_file = self._items_file(runs_dir)
        entries = [json.loads(ln) for ln in items_file.read_text().strip().split("\n")]
        digest, length = external_seal.chain_digest_and_length(entries)
        # 模拟生产端封印点（scripts/a_freeze.py::_seal_items_sources 同口径）
        external_seal.seal("items_source", items_file.name, digest, length)
        report = review_run(
            "syn_test", runs_dir=str(runs_dir), scores_dir=str(scores_dir),
            review_dir=str(review_dir),
        )
        assert report["pass"] is True
        assert report["items_source_check"]["ok"] is True
        assert report["items_source_check"]["seal_status"] == "ok"
        assert report["items_source_check"]["citable"] is True
