"""Runtime roots for the ABCR control plane.

The code never snapshots environment variables at import time.  Tests and fixture
journeys can therefore point every root at an isolated temporary directory while
production keeps hot state outside the Syncthing/Git tree.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeRoots:
    control: Path
    evidence: Path
    research: Path
    lab: Path
    dev_bundles: Path
    datasets: Path
    work: Path
    bridge: Path
    attest: Path
    releases: Path

    @classmethod
    def from_env(cls) -> "RuntimeRoots":
        home = Path.home()
        app = home / "Library" / "Application Support"
        system_app = Path("/Library/Application Support")
        return cls(
            control=Path(os.environ.get("ABCR_CONTROL_ROOT", app / "ABCR-Control")),
            evidence=Path(os.environ.get("ABCR_EVIDENCE_ROOT", app / "ABCR-Evidence")),
            research=Path(os.environ.get("ABCR_RESEARCH_ROOT", app / "ABCR-Research")),
            lab=Path(os.environ.get("ABCR_LAB_ROOT", app / "ABCR-Lab")),
            dev_bundles=Path(os.environ.get("ABCR_DEVBUNDLE_ROOT", system_app / "ABCR-DevBundles")),
            datasets=Path(os.environ.get("ABCR_DATASET_ROOT", system_app / "ABCR-Datasets")),
            work=Path(os.environ.get("ABCR_WORK_ROOT", system_app / "ABCR-Work")),
            bridge=Path(os.environ.get("ABCR_BRIDGE_ROOT", system_app / "ABCR-Bridge")),
            attest=Path(os.environ.get("ABCR_ATTEST_ROOT", system_app / "ABCR-Attest")),
            releases=Path(os.environ.get("ABCR_RELEASE_ROOT", home / ".abcr" / "releases")),
        )

    @classmethod
    def under(cls, root: Path) -> "RuntimeRoots":
        """Construct a complete fixture topology below one disposable root."""
        root = Path(root).resolve()
        return cls(**{name: root / name.replace("_", "-") for name in cls.__annotations__})

    def create_fixture_dirs(self) -> None:
        for path in self.__dict__.values():
            path.mkdir(parents=True, exist_ok=True)
