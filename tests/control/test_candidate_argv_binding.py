"""Adversarial binding tests for the production candidate command."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from abcr.control.contracts import ContractError
from abcr.control.test_controller import (
    CANDIDATE_ADAPTER_RELPATH,
    FROZEN_CANDIDATE_ARGV_TEMPLATE,
    resolve_candidate_argv,
    validate_candidate_argv_template,
)
from abcr.control.worktree import export_plain_tree, scan_tree, tree_hash


def _write_tree(root: Path) -> None:
    python = root / "env/bin/python"
    adapter = root / CANDIDATE_ADAPTER_RELPATH
    python.parent.mkdir(parents=True)
    adapter.parent.mkdir(parents=True)
    python.write_bytes(b"frozen-python")
    adapter.write_bytes(b"adapter")
    (root / "reviewed-source.json").write_bytes(b"{}\n")
    for directory, names, files in os.walk(root, topdown=False):
        for name in files:
            path = Path(directory) / name
            path.chmod(0o550 if path == python else 0o440)
        for name in names:
            (Path(directory) / name).chmod(0o500)
    root.chmod(0o500)


@pytest.fixture
def run_tree(tmp_path: Path) -> Path:
    root = tmp_path / "candidate-run"
    _write_tree(root)
    return root


def _resolve(root: Path, *, expected: str | None = None,
             uid: int | None = None, gid: int | None = None,
             template: object | None = None) -> tuple[str, ...]:
    return resolve_candidate_argv(
        list(FROZEN_CANDIDATE_ARGV_TEMPLATE) if template is None else template,
        root, expected_tree_hash=expected or tree_hash(scan_tree(root)),
        candidate_uid=os.getuid() if uid is None else uid,
        candidate_gid=os.getgid() if gid is None else gid)


def test_only_exact_frozen_template_resolves_inside_committed_tree(run_tree: Path) -> None:
    argv = _resolve(run_tree)
    assert argv == (
        str((run_tree / "env/bin/python").absolute()), "-I", "-m",
        "abcr.control.candidate_oracle_adapter")
    assert argv[0] != "/usr/bin/python3"
    assert "{candidate_root}" not in "\0".join(argv)


@pytest.mark.parametrize("template", [
    ["/usr/bin/python3", "-I", "-m", "abcr.control.candidate_oracle_adapter"],
    ["{candidate_root}/env/bin/python", "{candidate_root}/env/bin/python", "-I",
     "-m", "abcr.control.candidate_oracle_adapter"],
    ["{candidate_root}/../env/bin/python", "-I", "-m",
     "abcr.control.candidate_oracle_adapter"],
    ["{candidate_root}/env/bin/python", "-I", "-m",
     "abcr.control.candidate_oracle_adapter", "--caller-argument"],
    ("{candidate_root}/env/bin/python", "-I", "-m",
     "abcr.control.candidate_oracle_adapter"),
])
def test_path_injection_duplicate_placeholder_and_system_python_are_rejected(
        template: object) -> None:
    with pytest.raises(ContractError) as caught:
        validate_candidate_argv_template(template)
    assert caught.value.code == "candidate_argv_template_invalid"


def test_python_or_adapter_byte_replacement_is_hash_drift(run_tree: Path) -> None:
    expected = tree_hash(scan_tree(run_tree))
    run_tree.chmod(0o700)
    python = run_tree / "env/bin/python"
    python.chmod(0o750)
    python.write_bytes(b"substituted-system-wrapper")
    python.chmod(0o550)
    run_tree.chmod(0o500)
    with pytest.raises(ContractError) as caught:
        _resolve(run_tree, expected=expected)
    assert caught.value.code == "candidate_run_copy_drift"


def test_adapter_deletion_is_hash_drift(run_tree: Path) -> None:
    expected = tree_hash(scan_tree(run_tree))
    run_tree.chmod(0o700)
    adapter = run_tree / CANDIDATE_ADAPTER_RELPATH
    adapter.parent.chmod(0o700)
    adapter.unlink()
    run_tree.chmod(0o500)
    with pytest.raises(ContractError) as caught:
        _resolve(run_tree, expected=expected)
    assert caught.value.code == "candidate_run_copy_drift"


@pytest.mark.parametrize("relative", ["env/bin/python", CANDIDATE_ADAPTER_RELPATH])
def test_symlinked_interpreter_or_adapter_is_rejected(run_tree: Path, relative: str) -> None:
    target = run_tree / relative
    run_tree.chmod(0o700)
    target.parent.chmod(0o700)
    target.unlink()
    target.symlink_to("/usr/bin/python3")
    run_tree.chmod(0o500)
    with pytest.raises(ContractError) as caught:
        _resolve(run_tree, expected="0" * 64)
    assert caught.value.code == "unsafe_tree_entry"


def test_file_and_directory_mode_changes_cannot_hide_from_binding(run_tree: Path) -> None:
    expected = tree_hash(scan_tree(run_tree))
    adapter = run_tree / CANDIDATE_ADAPTER_RELPATH
    adapter.chmod(0o550)
    with pytest.raises(ContractError) as caught:
        _resolve(run_tree, expected=expected)
    assert caught.value.code == "candidate_run_copy_drift"

    # Directory modes are not part of TreeEntry, so the explicit metadata walk
    # must reject this even when the expected file-tree hash is recomputed.
    adapter.chmod(0o440)
    (run_tree / "env/lib").chmod(0o550)
    with pytest.raises(ContractError) as caught:
        _resolve(run_tree)
    assert caught.value.code == "candidate_run_tree_unsafe"


def test_wrong_run_identity_is_rejected_even_though_uid_is_not_hashed(run_tree: Path) -> None:
    with pytest.raises(ContractError) as caught:
        _resolve(run_tree, uid=os.getuid() + 1)
    assert caught.value.code == "candidate_run_root_unsafe"
    with pytest.raises(ContractError) as caught:
        _resolve(run_tree, gid=os.getgid() + 1)
    assert caught.value.code == "candidate_run_root_unsafe"


def test_seal_to_run_mode_normalization_preserves_hash_only_for_exact_policy(
        tmp_path: Path) -> None:
    sealed = tmp_path / "sealed"
    _write_tree(sealed)
    sealed_hash = tree_hash(scan_tree(sealed))
    exported = tmp_path / "exported"
    assert export_plain_tree(sealed, exported) == sealed_hash
    for directory, names, files in os.walk(exported, topdown=False):
        for name in files:
            path = Path(directory) / name
            mode = path.stat().st_mode & 0o777
            os.chown(path, os.getuid(), os.getgid())
            path.chmod(0o550 if mode & 0o111 else 0o440)
        for name in names:
            path = Path(directory) / name
            os.chown(path, os.getuid(), os.getgid())
            path.chmod(0o500)
    os.chown(exported, os.getuid(), os.getgid())
    exported.chmod(0o500)
    assert tree_hash(scan_tree(exported)) == sealed_hash
    _resolve(exported, expected=sealed_hash)

    exported.chmod(0o700)
    (exported / "reviewed-source.json").chmod(0o550)
    exported.chmod(0o500)
    assert tree_hash(scan_tree(exported)) != sealed_hash
    with pytest.raises(ContractError) as caught:
        _resolve(exported, expected=sealed_hash)
    assert caught.value.code == "candidate_run_copy_drift"
