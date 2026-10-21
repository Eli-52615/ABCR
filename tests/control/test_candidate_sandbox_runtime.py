"""Real macOS frozen-Python sandbox startup and escape-denial contract."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SANDBOX = Path("/usr/bin/sandbox-exec")
PROFILE = ROOT / "ops/sandbox/abcr-candidate.sb"


pytestmark = pytest.mark.skipif(
    not SANDBOX.is_file() or not os.access(SANDBOX, os.X_OK),
    reason="real sandbox-exec is macOS-only")


@pytest.fixture(scope="module")
def frozen_python(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Materialize a regular, relocatable CPython home like the release builder.

    The active venv's interpreter is an absolute uv symlink and is intentionally
    not used.  This fixture proves the exact release shape: regular
    ``candidate/env/bin/python`` plus its own stdlib/dylib tree.
    """
    root = tmp_path_factory.mktemp("frozen-candidate")
    candidate = root / "candidate"
    runtime = candidate / "env"
    (runtime / "bin").mkdir(parents=True)
    base_executable = Path(sys._base_executable).resolve(strict=True)
    base_home = Path(sys.base_prefix).resolve(strict=True)
    shutil.copyfile(base_executable, runtime / "bin/python")
    (runtime / "bin/python").chmod(0o555)
    shutil.copytree(base_home / "lib", runtime / "lib", symlinks=False)
    assert not (runtime / "bin/python").is_symlink()
    assert stat.S_ISREG((runtime / "bin/python").lstat().st_mode)
    return candidate, runtime / "bin/python"


def _run(candidate: Path, python: Path, scratch: Path, code: str,
         *arguments: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SANDBOX), "-f", str(PROFILE),
         "-D", f"CANDIDATE_ROOT={candidate}",
         "-D", f"RUNTIME_ROOT={candidate / 'env'}",
         "-D", f"TMPDIR={scratch}",
         str(python), "-I", "-c", code, *(str(path) for path in arguments)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, check=False, timeout=30,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C",
             "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/Users/superagent"})


def test_deny_default_profile_starts_regular_frozen_python(
        tmp_path: Path, frozen_python: tuple[Path, Path]) -> None:
    candidate, python = frozen_python
    scratch = tmp_path / "scratch"; scratch.mkdir()
    outcome = _run(
        candidate, python, scratch,
        "import json,pathlib,sys; assert pathlib.Path(sys.executable).is_file(); "
        "print(json.dumps({'ok':True,'prefix':sys.prefix}),flush=True)")
    assert outcome.returncode == 0, outcome.stderr
    report = json.loads(outcome.stdout)
    assert report["ok"] is True
    assert Path(report["prefix"]).resolve() == (candidate / "env").resolve()


def test_profile_denies_sensitive_read_write_list_rename_links_and_network(
        tmp_path: Path, frozen_python: tuple[Path, Path]) -> None:
    candidate, python = frozen_python
    scratch = tmp_path / "scratch"; scratch.mkdir()
    # The integration test tree is under /Users/superagent/.abcr-build on the
    # deployment host: it stands in for HOME, canonical Git, ledger, key and
    # spool bytes without exposing any content to the child.  Fixed production
    # ABCR roots are additionally pinned by static assertions below.
    sensitive = ROOT
    sentinel = sensitive / "CLAUDE.md"
    assert sentinel.is_file()
    code = r'''import json, os, pathlib, socket, sys
root = pathlib.Path(sys.argv[1]); sentinel = pathlib.Path(sys.argv[2]); scratch = pathlib.Path(sys.argv[3])
denied = []
checks = [
    ("read", lambda: sentinel.read_bytes()),
    ("list", lambda: list(root.iterdir())),
    ("write", lambda: (root / ".candidate-write").write_text("x")),
    ("rename", lambda: sentinel.rename(scratch / "stolen")),
    ("symlink-follow", lambda: ((scratch / "leak-link").symlink_to(sentinel),
                                (scratch / "leak-link").read_bytes())),
    ("hardlink", lambda: os.link(sentinel, scratch / "leak-hardlink")),
]
for name, operation in checks:
    try:
        operation()
    except (PermissionError, OSError):
        denied.append(name)
s = socket.socket(); s.settimeout(0.1)
try:
    s.connect(("127.0.0.1", 9))
except PermissionError:
    denied.append("network")
except OSError:
    pass
allowed = scratch / "allowed"
allowed.write_text("ok")
allowed.rename(scratch / "allowed-renamed")
print(json.dumps(sorted(denied)))
'''
    outcome = _run(candidate, python, scratch, code, sensitive, sentinel, scratch)
    assert outcome.returncode == 0, outcome.stderr
    assert json.loads(outcome.stdout) == sorted([
        "read", "list", "write", "rename", "symlink-follow", "hardlink", "network"])
    assert not (sensitive / ".candidate-write").exists()
    assert sentinel.is_file()
    assert not (scratch / "stolen").exists()
    assert (scratch / "leak-link").is_symlink()
    assert not (scratch / "leak-hardlink").exists()
    assert (scratch / "allowed-renamed").read_text() == "ok"


def test_profile_pins_all_production_sensitive_roots_after_system_baseline() -> None:
    text = PROFILE.read_text()
    assert '(import "system.sb")' in text
    assert text.index('(import "system.sb")') < text.index('(deny file-write*)')
    for path in (
        "/Library/Application Support/ABCR-Work",
        "/Library/Application Support/ABCR-Trust",
        "/Library/Application Support/ABCR-Bootstrap",
        "/Library/Application Support/ABCR-Attest",
        "/Library/Application Support/ABCR-Datasets",
        "/Library/Application Support/ABCR-DevBundles",
        "/Users/superagent/shared-brain",
        "/Users/superagent/.abcr/releases",
        "/Users/superagent/Library/Application Support/ABCR-Human",
    ):
        assert f'(subpath "{path}")' in text
    assert text.rstrip().endswith("; No result spool, canonical Git metadata, evidence, key or network mount is provided.")
