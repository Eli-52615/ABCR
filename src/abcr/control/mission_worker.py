"""Codex builder adapter.  Fake is default; real argv must be frozen by preflight."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from abcr.control.contracts import ContractError
from abcr.control.worktree import reconstruct_diff


class BuilderAdapter(Protocol):
    def run(self, tree: Path, objective: str) -> int: ...


class FakeBuilder:
    def __init__(self, mutation): self.mutation = mutation
    def run(self, tree: Path, objective: str) -> int:
        self.mutation(tree, objective); return 0


@dataclass(frozen=True)
class CodexExecAdapter:
    argv_prefix: tuple[str, ...]

    def run(self, tree: Path, objective: str) -> int:
        if not self.argv_prefix or any("\x00" in x for x in self.argv_prefix):
            raise ContractError("codex_argv_invalid", "Codex argv 未冻结")
        proc = subprocess.run([*self.argv_prefix, objective], cwd=tree, shell=False,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=1800,
                              env={"PATH": "/usr/bin:/bin:/usr/local/bin"})
        return proc.returncode


def build_candidate(adapter: BuilderAdapter, *, base_tree: Path, candidate_tree: Path,
                    objective: str, allowed_paths: tuple[str, ...]) -> dict:
    code = adapter.run(candidate_tree, objective)
    if code != 0: raise ContractError("builder_failed", f"builder exited {code}")
    return reconstruct_diff(base_tree, candidate_tree, allowed_globs=allowed_paths)


def main(argv: list[str] | None = None) -> int:
    """Fail closed until builder argv, worktree and queue bindings are frozen."""
    from abcr.control.service_runtime import blocked_runtime_main
    return blocked_runtime_main(argv, service="mission-builder",
                                required_capability="build_candidate",
                                capabilities={"build_candidate": build_candidate})


if __name__ == "__main__":
    raise SystemExit(main())
