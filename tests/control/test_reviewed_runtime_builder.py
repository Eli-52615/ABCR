"""Offline reviewed-runtime builder and authority-bound finalization checks."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from abcr.control.worktree import scan_tree, tree_hash


ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "scripts/build_reviewed_runtime.py"
    loader = importlib.machinery.SourceFileLoader("abcr_reviewed_runtime_builder_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _load_genesis():
    path = ROOT / "scripts/bootstrap_abcr_genesis.py"
    loader = importlib.machinery.SourceFileLoader(
        "abcr_genesis_reviewed_commit_binding_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _git(repo: Path, *argv: str) -> str:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *argv], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C",
             "GIT_AUTHOR_NAME": "ABCR Test", "GIT_AUTHOR_EMAIL": "abcr@example.invalid",
             "GIT_COMMITTER_NAME": "ABCR Test", "GIT_COMMITTER_EMAIL": "abcr@example.invalid"})
    return result.stdout.strip()


def _reviewed_repo(tmp_path: Path) -> tuple[Path, str]:
    builder = _load()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    paths = set(builder.GIT_EXACT) | {
        runtime for _, runtime in builder.RESOURCE_MIRRORS
    } | {
        "src/abcr/control/panel.py",
        "src/abcr/control/seal_broker.py",
        "configs/control/service-topology-v1.json",
        "ops/acl/fixture.json", "ops/install/fixture.json",
        "ops/install/bootstrap-v1.json",
        "ops/install/genesis-authority-v1.json",
        "ops/launchd/fixture.plist", "ops/sandbox/fixture.sb",
    }
    production_bytes = {
        "ops/install/genesis-authority-v1.json",
        "ops/install/bootstrap-v1.json",
        "scripts/abcr-bootstrap-selector",
    }
    for relative in sorted(paths):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative in production_bytes:
            shutil.copyfile(ROOT / relative, path)
        elif relative == "configs/control/service-topology-v1.json":
            path.write_text(json.dumps({"schema_version": 1, "services": []}) + "\n")
        elif relative.endswith(".py"):
            path.write_text("def main():\n    return 0\n")
        elif relative.endswith(".json"):
            path.write_text("{}\n")
        else:
            path.write_text(f"reviewed:{relative}\n")
        if relative.startswith("scripts/"):
            path.chmod(0o755)
    # Scientific data exists in the commit but is outside the finite export.
    secret = repo / "data/benchmarks/items.json"
    secret.parent.mkdir(parents=True)
    secret.write_text('[{"secret":true}]\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "reviewed fixture")
    return repo, _git(repo, "rev-parse", "HEAD")


def _runtime(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "python-home"
    python = home / "bin/python3.12"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 0\n")
    python.chmod(0o755)
    stdlib = home / "lib/python3.12/os.py"
    stdlib.parent.mkdir(parents=True)
    stdlib.write_text("name = 'posix'\n")
    site = tmp_path / "source-venv/lib/python3.12/site-packages"
    metadata = site / "fixture_pkg-1.0.dist-info/METADATA"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("Metadata-Version: 2.1\nName: fixture-pkg\nVersion: 1.0\n\n")
    package = site / "fixture_pkg/__init__.py"
    package.parent.mkdir(parents=True)
    package.write_text("VALUE = 1\n")
    # Exact uv virtualenv bootstrap files are intentionally not promoted.
    (site / "_virtualenv.pth").write_text("import _virtualenv\n")
    (site / "_virtualenv.py").write_text("raise AssertionError('must not ship')\n")
    return home, site


def _review_key(tmp_path: Path) -> Path:
    path = tmp_path / "review-verifier.pub"
    path.write_text("-----BEGIN PUBLIC KEY-----\nfixture\n-----END PUBLIC KEY-----\n")
    path.chmod(0o444)
    return path


def _make_writable(root: Path) -> None:
    for directory, names, files in os.walk(root, topdown=False):
        for name in files:
            (Path(directory) / name).chmod(0o600)
        for name in names:
            (Path(directory) / name).chmod(0o700)
    root.chmod(0o700)


def test_build_is_exact_commit_deterministic_plain_tree(tmp_path: Path) -> None:
    builder = _load()
    repo, commit = _reviewed_repo(tmp_path)
    home, site = _runtime(tmp_path)
    review_key = _review_key(tmp_path)
    first = tmp_path / "candidate-a"
    second = tmp_path / "candidate-b"

    one = builder.build_candidate(repo=repo, reviewed_commit=commit,
                                  python_home=home, site_packages=site,
                                  review_verifier_public_key=review_key, output=first)
    two = builder.build_candidate(repo=repo, reviewed_commit=commit,
                                  python_home=home, site_packages=site,
                                  review_verifier_public_key=review_key, output=second)

    assert one["candidate_tree_hash"] == two["candidate_tree_hash"]
    assert tree_hash(scan_tree(first)) == tree_hash(scan_tree(second))
    assert (first / "env/bin/python").is_file()
    assert not (first / "env/bin/python").is_symlink()
    assert (first / "env/lib/python3.12/site-packages/abcr/control/panel.py").is_file()
    assert (first / "configs/research/length-control/task_expansion_zh_v1.json").is_file()
    manifest = json.loads((first / "reviewed-source.json").read_text())
    assert len(manifest["resource_mirrors"]) == 2
    for mirror in manifest["resource_mirrors"]:
        assert (first / mirror["authority_path"]).read_bytes() == (
            first / mirror["runtime_path"]).read_bytes()
        assert mirror["sha256"] == builder.sha256(
            (first / mirror["authority_path"]).read_bytes())
    assert not (first / "src").exists()
    assert not (first / "data").exists()
    assert not (first / "env/lib/python3.12/site-packages/_virtualenv.pth").exists()
    assert not any(path.is_symlink() for path in first.rglob("*"))
    assert json.loads((first / "reviewed-source.json").read_text())["reviewed_commit"] == commit

    second_manifest = json.loads((second / "reviewed-source.json").read_text())
    runtime_mirror = second / second_manifest["resource_mirrors"][0]["runtime_path"]
    runtime_mirror.chmod(0o600)
    runtime_mirror.write_text('{"drift":true}\n')
    with pytest.raises(builder.BuildBlocked,
                       match="candidate bytes|drifted from reviewed config"):
        builder.doctor_candidate(second, repo=repo, reviewed_commit=commit)

    _make_writable(first); _make_writable(second)


def test_build_rejects_symbolic_commit_name(tmp_path: Path) -> None:
    builder = _load()
    repo, _ = _reviewed_repo(tmp_path)
    home, site = _runtime(tmp_path)
    review_key = _review_key(tmp_path)
    with pytest.raises(builder.BuildBlocked, match="exact 40-character"):
        builder.build_candidate(repo=repo, reviewed_commit="HEAD",
                                python_home=home, site_packages=site,
                                review_verifier_public_key=review_key,
                                output=tmp_path / "candidate")


def test_build_rejects_runtime_resource_different_from_reviewed_config(
        tmp_path: Path) -> None:
    builder = _load()
    repo, _ = _reviewed_repo(tmp_path)
    _, runtime_path = builder.RESOURCE_MIRRORS[0]
    (repo / runtime_path).write_text('{"different":true}\n')
    _git(repo, "add", runtime_path)
    _git(repo, "commit", "-qm", "drift packaged resource")
    commit = _git(repo, "rev-parse", "HEAD")
    home, site = _runtime(tmp_path)
    with pytest.raises(builder.BuildBlocked, match="differs from reviewed config"):
        builder.build_candidate(
            repo=repo, reviewed_commit=commit, python_home=home,
            site_packages=site, review_verifier_public_key=_review_key(tmp_path),
            output=tmp_path / "candidate")


def test_build_rejects_site_packages_symlink(tmp_path: Path) -> None:
    builder = _load()
    repo, commit = _reviewed_repo(tmp_path)
    home, site = _runtime(tmp_path)
    review_key = _review_key(tmp_path)
    external = tmp_path / "external.py"
    external.write_text("SECRET = True\n")
    (site / "injected.py").symlink_to(external)

    with pytest.raises(builder.BuildBlocked, match="site-packages symlink"):
        builder.build_candidate(repo=repo, reviewed_commit=commit,
                                python_home=home, site_packages=site,
                                review_verifier_public_key=review_key,
                                output=tmp_path / "candidate")


def test_candidate_doctor_is_honest_about_unsigned_gate(tmp_path: Path) -> None:
    builder = _load()
    # This assertion is about status semantics: structural readiness must never
    # be represented as a verifier PASS.  Avoid executing candidate code.
    source = (ROOT / "scripts/build_reviewed_runtime.py").read_text()
    assert '"status": "BLOCKED"' in source
    assert '"blocking_gate": "SIGNED_VERIFICATION_REQUIRED"' in source
    assert "sign_attestation" not in source
    assert "generate_keypair" not in source


def test_cli_requires_verifier_evidence_and_exact_reviewed_commit() -> None:
    builder = _load()
    parser_source = (ROOT / "scripts/build_reviewed_runtime.py").read_text()
    assert 'finalize.add_argument("--attestation"' in parser_source
    assert 'finalize.add_argument("--verifier-public-key"' in parser_source
    assert 'finalize.add_argument("--repo"' in parser_source
    assert 'finalize.add_argument("--reviewed-commit"' in parser_source
    assert 'build.add_argument("--review-verifier-public-key"' in parser_source
    assert builder._selected_git_path("src/abcr/control/release.py")
    assert builder._selected_git_path(
        "configs/research/length-control/task_expansion_zh_v1.json")
    assert builder._selected_git_path("configs/research/templates/registry.json")
    assert not builder._selected_git_path("data/benchmarks/ifeval_zh_v1.json")


def _reviewed_release_and_draft(tmp_path: Path, builder, monkeypatch
                                ) -> tuple[Path, dict, str]:
    repo, commit = _reviewed_repo(tmp_path)
    home, site = _runtime(tmp_path)
    candidate = tmp_path / "candidate-for-authority"
    builder.build_candidate(
        repo=repo, reviewed_commit=commit, python_home=home, site_packages=site,
        review_verifier_public_key=_review_key(tmp_path), output=candidate)
    candidate_entries = tuple(sorted(scan_tree(candidate), key=lambda item: item.path))
    core = {
        "tree_hash": tree_hash(candidate_entries), "runtime_digest": "a" * 64,
        "lock_hash": "b" * 64, "service_config_hash": "c" * 64,
        "verification_hash": "d" * 64,
    }
    release_id = "REL-" + builder.sha256(core)
    module_path = (
        "env/lib/python3.12/site-packages/abcr/control/seal_broker.py")
    declared = {item.path: asdict(item) for item in candidate_entries}
    payload_files = [module_path]
    manifest = {
        **core, "release_id": release_id,
        "tree_entries": [asdict(item) for item in candidate_entries],
        "runtime_relpath": "env", "lock_relpath": "requirements.lock",
        "service_config_relpath": "configs/control/service-topology-v1.json",
        "service_payloads": {"abcr.control.seal_broker": {
            "module": "abcr.control.seal_broker", "module_relpath": module_path,
            "payload_files": payload_files,
            "payload_tree_hash": builder.sha256(
                [declared[path] for path in payload_files]),
        }},
    }
    review_root = tmp_path / "reviewed"
    review_root.mkdir()
    release = review_root / release_id
    candidate.chmod(0o755)
    candidate.rename(release)
    release.chmod(0o755)
    manifest_path = release / "release-manifest.json"
    manifest_path.write_bytes(builder._canonical(manifest)); manifest_path.chmod(0o444)
    release.chmod(0o555)
    monkeypatch.setattr(builder, "GENESIS_REVIEW_ROOT", review_root)
    draft_core = {
        "schema_version": 1, "ceremony": "abcr-human-root-genesis-v1",
        "authority_sha256": "a" * 64, "policy_sha256": "b" * 64,
        "human_approved": False, "reviewed_commit": commit,
        "reviewed_release_path": str(release), "release_id": release_id,
        "release_manifest_sha256": builder.sha256(manifest_path.read_bytes()),
        "source_tree_hash": tree_hash(scan_tree(release)),
        "broker_seal_nonce": "genesis:fixture", "expected_receipt_id": "1" * 64,
        "tcb": {"finite": True},
    }
    return release, {**draft_core, "authority_id": builder.sha256(draft_core)}, commit


def test_authority_approval_is_explicit_canonical_and_rehashes(
        tmp_path: Path, monkeypatch) -> None:
    builder = _load()
    _, draft, _ = _reviewed_release_and_draft(tmp_path, builder, monkeypatch)
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(draft))
    draft_path.chmod(0o444)

    with pytest.raises(builder.BuildBlocked, match="--human-reviewed"):
        builder.approve_authority_draft(
            draft_path, tmp_path / "approved.json", human_reviewed=False)

    result = builder.approve_authority_draft(
        draft_path, tmp_path / "approved.json", human_reviewed=True)
    raw = (tmp_path / "approved.json").read_bytes()
    approved = json.loads(raw)
    assert raw == builder._canonical(approved)
    assert approved["human_approved"] is True
    assert approved["authority_id"] == builder.sha256(
        {key: value for key, value in approved.items() if key != "authority_id"})
    assert result["status"] == "READY_FOR_ROOT_AUTHORITY_INSTALL"


def test_authority_approval_rejects_self_consistent_commit_claim_not_in_release(
        tmp_path: Path, monkeypatch) -> None:
    """Adversary cannot relabel commit-A release as commit B and rehash draft."""
    builder = _load()
    _, draft, commit = _reviewed_release_and_draft(tmp_path, builder, monkeypatch)
    claimed = "f" * 40 if commit != "f" * 40 else "e" * 40
    forged_core = {**{key: value for key, value in draft.items()
                      if key != "authority_id"}, "reviewed_commit": claimed}
    forged = {**forged_core, "authority_id": builder.sha256(forged_core)}
    draft_path = tmp_path / "forged-draft.json"
    draft_path.write_text(json.dumps(forged)); draft_path.chmod(0o444)

    with pytest.raises(builder.BuildBlocked, match="reviewed source/release/tree"):
        builder.approve_authority_draft(
            draft_path, tmp_path / "must-not-exist.json", human_reviewed=True)


def test_genesis_derives_commit_from_release_and_rejects_caller_relabel(
        tmp_path: Path, monkeypatch) -> None:
    builder = _load()
    genesis = _load_genesis()
    release, _, commit = _reviewed_release_and_draft(tmp_path, builder, monkeypatch)
    monkeypatch.setattr(genesis, "REVIEW_ROOT", release.parent)

    derived = genesis.build_authority_statement(release, human_approved=False)
    assert derived["reviewed_commit"] == commit
    claimed = "f" * 40 if commit != "f" * 40 else "e" * 40
    with pytest.raises(genesis.GenesisBlocked, match="reviewed-source.json"):
        genesis.build_authority_statement(
            release, claimed, human_approved=False)
