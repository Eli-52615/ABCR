"""External semantic canary; service self-reported health is insufficient."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from abcr.control.contracts import sha256, utc_now


@dataclass(frozen=True)
class CanaryResult:
    release_id: str
    expected_version: str
    observed_version: str | None
    semantic_ok: bool
    reason: str
    checked_at: str
    result_hash: str


def run_canary(release_id: str, expected_version: str,
               external_probe: Callable[[], tuple[str | None, bool, str]]) -> CanaryResult:
    try: observed, semantic, reason = external_probe()
    except Exception as exc: observed, semantic, reason = None, False, f"probe_error:{type(exc).__name__}"
    ok = bool(semantic) and observed == expected_version
    core = {"release_id": release_id, "expected_version": expected_version,
            "observed_version": observed, "semantic_ok": ok, "reason": reason,
            "checked_at": utc_now()}
    return CanaryResult(**core, result_hash=sha256(core))


def main(argv: list[str] | None = None) -> int:
    """Fail closed until the external semantic probe binding is frozen."""
    from abcr.control.service_runtime import blocked_runtime_main
    return blocked_runtime_main(argv, service="canary-controller",
                                required_capability="run_canary",
                                capabilities={"run_canary": run_canary})


if __name__ == "__main__":
    raise SystemExit(main())
