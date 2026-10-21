import json
import hashlib
import pathlib
import tempfile
import pytest
from abcr.review import review_pack


def _canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _build_test_pack(pack_dir: pathlib.Path):
    pack_dir.mkdir(parents=True, exist_ok=True)

    test_files = {
        "data/sample.csv": "id,value\n1,hello\n2,world\n",
        "configs/models.yaml": "models:\n  tinyqwen:\n    model_id: tests/fixtures/tinyqwen\n",
        "scores/test_run/scores.jsonl": '{"run_id":"test_run","score":0.8}\n',
    }

    manifest_entries = []
    for rel_path, content in test_files.items():
        fp = pack_dir / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        sha = hashlib.sha256(content.encode()).hexdigest()
        manifest_entries.append({
            "path": rel_path,
            "sha256": sha,
            "source": f"/Users/superagent/abcr/{rel_path}",
        })

    manifest = {
        "preset": "test",
        "files": manifest_entries,
        "n_files": len(manifest_entries),
        "packed_at": "2026-07-11T00:00:00+00:00",
        "git_commit": "test123",
    }
    (pack_dir / "pack_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


class TestFirstPack:
    def test_clean_pack_passes(self, tmp_path):
        pack_dir = tmp_path / "test_pack"
        _build_test_pack(pack_dir)
        report = review_pack(str(pack_dir))
        assert report["pass"] is True
        assert len(report["sha_mismatches"]) == 0
        assert len(report["missing_files"]) == 0

    def test_tampered_file_detected(self, tmp_path):
        pack_dir = tmp_path / "test_pack"
        _build_test_pack(pack_dir)

        tampered_file = pack_dir / "data" / "sample.csv"
        original = tampered_file.read_text()
        tampered_file.write_text(original + "TAMPERED")

        report = review_pack(str(pack_dir))
        assert report["pass"] is False
        assert len(report["sha_mismatches"]) == 1
        assert report["sha_mismatches"][0]["path"] == "data/sample.csv"

    def test_missing_file_detected(self, tmp_path):
        pack_dir = tmp_path / "test_pack"
        _build_test_pack(pack_dir)

        (pack_dir / "configs" / "models.yaml").unlink()

        report = review_pack(str(pack_dir))
        assert report["pass"] is False
        assert "configs/models.yaml" in report["missing_files"]
