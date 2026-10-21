import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Optional

HONESTY_CLAUSE = """本包承诺的复现 = ①工件级（原始输出永久保存，再分析不依赖重新生成）+ ②统计级（同 config 重跑，聚合指标在自身抽样波动内一致）+ ③单机确定级（同机同环境 temp 0 双跑一致）。不承诺跨硬件 bit 级一致——浮点归约序差异是行业已知事实。本包全部产物为 Mac dev 档（fp16/MPS 或 fp32/CPU），non-citable，仅证明管线正确性，不构成任何科学结论。"""

PRESETS = {
    "stage2": {
        "description": "S2 验收包：向量工件 + bridge 数据 + patches + configs",
        "globs": [
            "vectors/qwen2.5-3b-instruct/optimistic-dev/**/*",
            "pv_bridge/out/**/*.csv",
            "pv_bridge/out/**/*.judge_raw.jsonl",
            "patches/*",
            "configs/models.yaml",
            "configs/templates/**/*",
        ],
    },
    "mini-loop": {
        "description": "W1 终包：mini loop 四 run + t0 + 全评分审计 + 图表",
        "globs": [],
    },
}


def build_pack(preset: str, out_dir: str, repo_root: str = ".") -> dict:
    root = pathlib.Path(repo_root).resolve()
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    git_commit = _get_git_commit(root)

    files = []
    if preset in PRESETS:
        for pattern in PRESETS[preset]["globs"]:
            for f in root.glob(pattern):
                if f.is_file():
                    rel = f.relative_to(root)
                    files.append((str(rel), f))

    if preset == "mini-loop":
        files.extend(_collect_mini_loop_files(root))

    seen_paths = set()
    manifest_entries = []
    for rel_path, src_path in files:
        if rel_path in seen_paths:
            continue
        seen_paths.add(rel_path)
        dst = out / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst)
        sha = _sha256_file(dst)
        manifest_entries.append({
            "path": rel_path,
            "sha256": sha,
            "source": str(src_path),
        })

    if preset == "mini-loop":
        _generate_env_lock(root, out)
        env_lock_path = out / "env.lock"
        if env_lock_path.exists():
            sha = _sha256_file(env_lock_path)
            manifest_entries.append({
                "path": "env.lock",
                "sha256": sha,
                "source": "uv pip freeze (generated at pack time)",
            })

        from abcr.eval.deterministic.rescore_bundle import generate_rescore
        rescore_dir = out / "rescore"
        generate_rescore(rescore_dir)
        for pycache in rescore_dir.rglob("__pycache__"):
            shutil.rmtree(pycache)
        for fp in sorted(rescore_dir.rglob("*")):
            if fp.is_file():
                sha = _sha256_file(fp)
                manifest_entries.append({
                    "path": str(fp.relative_to(out)),
                    "sha256": sha,
                    "source": "generate_rescore (stdlib-only bundle)",
                })

    for pycache in out.rglob("__pycache__"):
        shutil.rmtree(pycache)

    protocol_refs = {}
    for entry in manifest_entries:
        if entry["path"].startswith("configs/protocol/") and entry["path"].endswith(".md"):
            protocol_refs[pathlib.Path(entry["path"]).name] = entry["sha256"]

    pack_manifest = {
        "preset": preset,
        "files": manifest_entries,
        "n_files": len(manifest_entries),
        "packed_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
    }
    if protocol_refs:
        pack_manifest["protocol_refs"] = protocol_refs

    readme = _generate_readme(preset, pack_manifest)
    readme_path = out / "README.md"
    readme_path.write_text(readme)
    readme_sha = _sha256_file(readme_path)
    manifest_entries.append({
        "path": "README.md",
        "sha256": readme_sha,
        "source": "generated",
    })
    pack_manifest["n_files"] = len(manifest_entries)

    manifest_path = out / "pack_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(pack_manifest, f, indent=2, ensure_ascii=False)

    return pack_manifest


def _collect_mini_loop_files(root: pathlib.Path) -> list[tuple[str, pathlib.Path]]:
    files = []
    runset_path = root / "runs" / "MINILOOP-RUNSET.json"
    if runset_path.exists():
        files.append((str(runset_path.relative_to(root)), runset_path))
        with open(runset_path) as f:
            runset = json.load(f)

        for run_id in runset.get("main_runs", []):
            run_dir = root / "runs" / run_id
            if run_dir.exists():
                for fp in run_dir.rglob("*"):
                    if fp.is_file() and ".crashed" not in fp.name:
                        files.append((str(fp.relative_to(root)), fp))
            score_dir = root / "scores" / run_id
            if score_dir.exists():
                for fp in score_dir.rglob("*"):
                    if fp.is_file():
                        files.append((str(fp.relative_to(root)), fp))
            review_file = root / "review" / run_id / "review_report.json"
            if review_file.exists():
                files.append((str(review_file.relative_to(root)), review_file))

        for run_id in runset.get("t0_runs", []):
            run_dir = root / "runs" / run_id
            if run_dir.exists():
                for fp in run_dir.rglob("*"):
                    if fp.is_file() and ".crashed" not in fp.name:
                        files.append((str(fp.relative_to(root)), fp))
            score_dir = root / "scores" / run_id
            if score_dir.exists():
                for fp in score_dir.rglob("*"):
                    if fp.is_file():
                        files.append((str(fp.relative_to(root)), fp))
            review_file = root / "review" / run_id / "review_report.json"
            if review_file.exists():
                files.append((str(review_file.relative_to(root)), review_file))

    for ip in (root / "data" / "items").rglob("items.jsonl"):
        if ip.is_file():
            files.append((str(ip.relative_to(root)), ip))

    splits_dir = root / "data" / "splits"
    if splits_dir.exists():
        for fp in splits_dir.iterdir():
            if fp.is_file():
                files.append((str(fp.relative_to(root)), fp))

    for fp in (root / "figures").glob("*.png"):
        files.append((str(fp.relative_to(root)), fp))

    for fp in (root / "review").glob("*.json"):
        files.append((str(fp.relative_to(root)), fp))

    exprcheck_dir = root / "pv_bridge" / "out"
    if exprcheck_dir.exists():
        for fp in exprcheck_dir.rglob("*"):
            if fp.is_file() and "__pycache__" not in str(fp):
                files.append((str(fp.relative_to(root)), fp))

    for fp in (root / "configs").rglob("*"):
        if fp.is_file():
            files.append((str(fp.relative_to(root)), fp))

    patches_dir = root / "patches"
    if patches_dir.exists():
        for fp in patches_dir.iterdir():
            if fp.is_file():
                files.append((str(fp.relative_to(root)), fp))

    vectors_dir = root / "vectors"
    if vectors_dir.exists():
        for fp in vectors_dir.rglob("*"):
            if fp.is_file():
                files.append((str(fp.relative_to(root)), fp))

    return files


def _generate_env_lock(root: pathlib.Path, out: pathlib.Path):
    sections = []
    for venv_name in [".venv", ".venv-pv"]:
        venv_python = root / venv_name / "bin" / "python"
        if not venv_python.exists():
            sections.append(f"# {venv_name}: not found\n")
            continue
        try:
            result = subprocess.run(
                ["uv", "pip", "freeze", "--python", str(venv_python)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                sections.append(f"# {venv_name}\n{result.stdout.strip()}\n")
            else:
                sections.append(f"# {venv_name}: uv pip freeze failed (rc={result.returncode})\n")
        except FileNotFoundError:
            sections.append(f"# {venv_name}: uv not available\n")
    (out / "env.lock").write_text("\n".join(sections))


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_git_commit(root: pathlib.Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=root,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _generate_readme(preset: str, manifest: dict) -> str:
    return f"""# Repro Pack: {preset}

## 内容
本包含 {manifest['n_files']} 个文件，打包时间 {manifest['packed_at']}。
Git commit: {manifest['git_commit']}

## 复算命令
```
python3 rescore/rescore.py .
```
（系统 python3 即可，rescore/ 目录自含全部代码，无第三方依赖）

对 pack 内所有文件的 SHA256 校验：
```
python -m abcr.review --pack <本目录路径>
```

## 诚实条款
{HONESTY_CLAUSE}

## 标注
- rig-validation run — NOT evidence
- non-citable
- dev split
- exploratory
- Mac dev 档（fp16/MPS 或 fp32/CPU）

## Judge 谱系
- judge_model: deepseek-chat
- judge_lineage: replaced(official gpt-4.1-mini-2025-04-14)
"""


def main():
    import typer
    app = typer.Typer()

    @app.command()
    def pack(preset: str, out: str):
        result = build_pack(preset, out)
        print(json.dumps({"n_files": result["n_files"], "packed_at": result["packed_at"]}, indent=2))

    app()


if __name__ == "__main__":
    main()
