"""Production-shaped immutable bootstrap bytes for release unit fixtures."""
from __future__ import annotations

import shutil
import stat
from pathlib import Path

from abcr.control.release import BOOTSTRAP_REQUIRED_PATHS


REPO = Path(__file__).resolve().parents[2]
_PLISTS = tuple(
    f"ops/launchd/com.abcr.{name}.plist" for name in (
        "human-gateway", "operator-reconciler", "probe-worker", "itempool",
        "auditor", "mission-builder", "test-controller", "verifier",
        "canary-controller", "release-activator", "panel", "seal-broker"))


def add_bootstrap_payload(root: Path) -> None:
    """Copy the reviewed finite bootstrap contract into a synthetic candidate.

    The helper deliberately follows the production requirement registry instead
    of weakening ``prepare_release`` for tests.  Files are copied as immutable
    bytes with their executable bits preserved and no writable group/other bits.
    """
    for relative in (*BOOTSTRAP_REQUIRED_PATHS, *_PLISTS):
        source = REPO / relative
        if not source.is_file() or source.is_symlink():
            raise AssertionError(f"reviewed bootstrap fixture is missing: {relative}")
        destination = Path(root) / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        source_mode = stat.S_IMODE(source.stat().st_mode)
        destination.chmod(0o555 if source_mode & 0o111 else 0o444)
