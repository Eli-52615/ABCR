"""C2-2 repro_pack 测试（§C2-2 / §8.2 C-R2-2/3）：出包 → 逐文件 sha256 齐 →
仓库外空 PYTHONPATH 独立复算两组一致率 == 1.0；污染检测；自检 fail-closed。

用真实 B scorer（deterministic_v1）+ 真实 A rescore（rescore_v1）产分数——双实现在 golden
上必然一致，故独立复算 agreement 应为 1.0（正是本包要证明的东西）。K9：全程在 tmp。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from abcr.audit import rescore
from abcr.common.ledger_ref import RunLedger, append_record
from abcr.report import repro_pack
from abcr.rig import scorer

BATCH = "B-20260716T020000Z-0001"
# golden 混合样本：g01/g02 正确，g03 已知错（fail_sample）
_SAMPLES = {
    "g01": "- 红\n- 黄\n- 蓝",
    "g02": "391",
    "g03": "hello, hello, hello, hello, hello",   # 有空格 → 判 0
}


def _step(rid: str, item_id: str, cond: str, seed: int) -> dict:
    txt = _SAMPLES[item_id]
    return {"schema_version": "1.0", "run_id": rid, "trajectory_id": f"{rid}-{item_id}",
            "step_id": 0, "condition": cond, "random_seed": seed, "item_id": item_id,
            "output_text": txt, "output_tokens": max(1, len(txt))}


def _build_batch(repo_root: Path) -> None:
    (repo_root / "configs" / "envelopes").mkdir(parents=True)
    env = {
        "envelope_version": "1.0", "batch_id": BATCH, "protocol_ref": "W1-V0.9",
        "scope": {"benchmark_families": ["golden10"], "conditions": ["vanilla", "persona_text"],
                  "splits": ["dev"], "item_limit_per_run": 3, "seeds": [1, 2],
                  "trait_whitelist": []},
        "budget": {"gpu_hours_max": 1.0, "cost_cap_cny": 0.0},
        "deadline_utc": "2027-01-01T00:00:00+00:00",
        "run_configs": [{"config_version": "1.0", "condition": "vanilla"}],
        "drafted_by": "test",
    }
    (repo_root / "configs" / "envelopes" / f"{BATCH}.json").write_text(
        json.dumps(env, ensure_ascii=False), encoding="utf-8")

    led = RunLedger(repo_root / "ledger", "runs_index")
    for rid, cond, seed in (("run-vanilla-1", "vanilla", 1), ("run-persona-2", "persona_text", 2)):
        rd = repo_root / "data" / "runs" / rid
        rd.mkdir(parents=True)
        steps = [_step(rid, it, cond, seed) for it in _SAMPLES]
        for st in steps:
            append_record(rd / "steps.jsonl", dict(st))
        # B deterministic_v1（真实 scorer）
        det = scorer.score_steps(steps)
        (rd / "scores.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in det) + "\n", encoding="utf-8")
        # A rescore_v1（真实 rescore，追加）
        rescore.rescore_run(rd)
        # manifest（含 non_citable + config）
        (rd / "manifest.json").write_text(json.dumps({
            "run_id": rid, "config": {"condition": cond, "random_seed": seed, "split": "dev"},
            "non_citable": True, "batch_id": BATCH, "status": "COMPLETED",
        }, ensure_ascii=False), encoding="utf-8")
        led.append("run_registered", subject_id=rid, batch_id=BATCH)
        led.append("run_started", subject_id=rid)
        led.append("run_completed", subject_id=rid)
        led.append("run_scored", subject_id=rid)


@pytest.fixture
def packed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_batch(repo)
    pack_dir = repro_pack.pack(BATCH, out_root=tmp_path / "demos", repo_root=repo)
    return pack_dir


def test_manifest_files_sha256_all_match(packed):
    """C-R2-2：pack_manifest 逐文件 sha256 全符。"""
    man = json.loads((packed / "pack_manifest.json").read_text(encoding="utf-8"))
    assert man["labels"] == ["exploratory", "rig-validation"]
    assert man["commitments"]["cross_hardware_bit_level"] is False
    assert man["commitments"]["artifact_level"] is True
    assert len(man["run_ids"]) == 2
    for f in man["files"]:
        fp = packed / f["path"]
        assert fp.exists(), f["path"]
        assert hashlib.sha256(fp.read_bytes()).hexdigest() == f["sha256"], f["path"]
        assert fp.stat().st_size == f["bytes"]
    # manifest 不含自身
    assert all(f["path"] != "pack_manifest.json" for f in man["files"])


def test_pack_contents_present(packed):
    for rel in ("README.md", "ACCEPTANCE.md", "pack_manifest.json",
                "tools/rescore_copy.py", "tools/scorer_copy.py", "tools/rescore_standalone.py",
                "env/requirements.lock.txt", "env/versions.json", "figures/main.png"):
        assert (packed / rel).exists(), rel
    # 诚实条款逐字在 README
    assert "不承诺跨硬件 bit 级一致" in (packed / "README.md").read_text(encoding="utf-8")
    # ACCEPTANCE 文件数占位已回填为数字
    acc = (packed / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert "__FILE_COUNT__" not in acc
    # 密钥政策：包内无任何 .key
    assert not list(packed.rglob("*.key"))


def _run_standalone(pack_dir: Path, tmp_path: Path) -> dict:
    """仓库外（/tmp 副本）空 PYTHONPATH 跑 rescore_standalone，返回报告。"""
    import shutil
    ext = tmp_path / "pack-ext"
    shutil.copytree(pack_dir, ext)
    r = subprocess.run([sys.executable, "tools/rescore_standalone.py", "--pack", ".",
                        "--report", "rescore_report.json"],
                       cwd=str(ext), env={"PYTHONPATH": "", "PATH": ""},
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads((ext / "rescore_report.json").read_text(encoding="utf-8"))


def test_out_of_repo_agreement_10(packed, tmp_path):
    """C-R2-3：仓库外独立复算，两组一致率均 == 1.0。"""
    rep = _run_standalone(packed, tmp_path)
    assert rep["integrity_ok"] is True
    assert rep["agreement_deterministic_v1"] == 1.0
    assert rep["agreement_rescore_v1"] == 1.0
    assert rep["recompute_triples"] > 0
    assert rep["mismatches"] == []


def test_contamination_exit_2(packed, tmp_path):
    """篡改任一受清单文件 → 完整性核验失败、退出码 2。"""
    import shutil
    ext = tmp_path / "pack-tamper"
    shutil.copytree(packed, ext)
    steps = next(ext.glob("runs/*/steps.jsonl"))
    with steps.open("a", encoding="utf-8") as f:
        f.write('{"tampered": true}\n')
    r = subprocess.run([sys.executable, "tools/rescore_standalone.py", "--pack", ".",
                        "--report", "r.json"],
                       cwd=str(ext), env={"PYTHONPATH": "", "PATH": ""},
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, r.stdout + r.stderr
    rep = json.loads((ext / "r.json").read_text(encoding="utf-8"))
    assert rep["integrity_ok"] is False and rep["contamination"]


def _plant_aligned_shadow_pyc(pack: Path) -> str:
    """种一个"mtime/size 与合法 rescore_copy.py 对齐"的影子 pyc（攻击 V04 的载荷）。"""
    import importlib.util
    import marshal
    import struct
    mal = ("import sys\n"
           "sys.stderr.write('### SHADOW PYC LOADED ###\\n')\n"
           "def rescore_step(step):\n"
           "    return []\n")
    legit = pack / "tools" / "rescore_copy.py"
    st = legit.stat()
    data = marshal.dumps(compile(mal, str(legit), "exec"))
    header = (importlib.util.MAGIC_NUMBER + struct.pack("<I", 0)
              + struct.pack("<I", int(st.st_mtime) & 0xFFFFFFFF)
              + struct.pack("<I", st.st_size & 0xFFFFFFFF))
    rel = f"tools/__pycache__/rescore_copy.{sys.implementation.cache_tag}.pyc"
    (pack / rel).parent.mkdir(parents=True, exist_ok=True)
    (pack / rel).write_bytes(header + data)
    return rel


def _redeclare_manifest(pack: Path, extra: list[str]) -> None:
    """攻击者重生成清单（全部 sha256 一致重算）并把影子 pyc 申报进去。"""
    import hashlib
    man = json.loads((pack / "pack_manifest.json").read_text(encoding="utf-8"))
    for f in man["files"]:
        b = (pack / f["path"]).read_bytes()
        f["sha256"] = hashlib.sha256(b).hexdigest()
        f["bytes"] = len(b)
    for rel in extra:
        b = (pack / rel).read_bytes()
        man["files"].append({"path": rel, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)})
    (pack / "pack_manifest.json").write_text(
        json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("declare", [False, True])
def test_shadow_pyc_rejected_declared_or_not(packed, tmp_path, declare):
    """V04：mtime/size 对齐的影子 .pyc —— 无论是否申报进(重生成的)清单，都判污染、退出码 2，
    且影子字节码永不被执行（副本改走 compile+exec 已核验源码，不经 import 机制）。"""
    import shutil
    ext = tmp_path / f"pack-pyc-{int(declare)}"
    shutil.copytree(packed, ext)
    rel = _plant_aligned_shadow_pyc(ext)
    _redeclare_manifest(ext, [rel] if declare else [])
    r = subprocess.run([sys.executable, "tools/rescore_standalone.py", "--pack", ".",
                        "--report", "r.json"],
                       cwd=str(ext), env={"PYTHONPATH": "", "PATH": ""},
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "SHADOW PYC LOADED" not in r.stderr, "影子字节码被执行了"
    rep = json.loads((ext / "r.json").read_text(encoding="utf-8"))
    assert rep["integrity_ok"] is False
    assert any("字节码" in c["reason"] for c in rep["contamination"]), rep["contamination"]


def test_pack_has_no_bytecode_and_external_seal_verifies(packed, tmp_path):
    """阴性对照 + 接线：干净包不含任何字节码，且外部锚校验（出包强制门同一函数）通过。"""
    assert not list(packed.rglob("*.pyc"))
    assert not [p for p in packed.rglob("*") if p.name == "__pycache__"]
    ok, why = repro_pack.verify_pack_external_seal(packed, repo_root=packed.parents[1] / "repo")
    assert ok, why


def test_selfcheck_refuses_non_selfcontained(tmp_path, monkeypatch):
    """出包末步自检 fail-closed：若某副本非 stdlib 自包含（import abcr），拒绝出包并删半成品。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_batch(repo)
    monkeypatch.setattr(repro_pack, "_gen_scorer_copy",
                        lambda: "import abcr.common.constants  # 故意破坏自包含\n")
    with pytest.raises(RuntimeError, match="BLOCKER"):
        repro_pack.pack(BATCH, out_root=tmp_path / "demos2", repo_root=repo)
    # 半成品包已删
    assert not (tmp_path / "demos2" / f"repro-{BATCH}").exists()
