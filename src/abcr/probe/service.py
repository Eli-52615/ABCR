"""Queue adapter for the on-demand probe service."""
from __future__ import annotations

from abcr.control.work_spool import WorkSpool


def process_once(spool: WorkSpool, work_id: str, handler) -> bool:
    claim = spool.claim("probe", work_id)
    if claim is None:
        return False
    try:
        result = handler(claim.payload)
        spool.submit_result(claim, {"ok": True, "result": result}, consumer="abcr-probe")
    except Exception as exc:
        spool.submit_result(claim, {"ok": False, "error_code": type(exc).__name__}, consumer="abcr-probe")
    spool.ack(claim)
    return True


def main(argv: list[str] | None = None) -> int:
    """Fail closed until the spool/engine wire binding is frozen for launchd."""
    from abcr.control.service_runtime import blocked_runtime_main
    return blocked_runtime_main(argv, service="probe-worker",
                                required_capability="process_once",
                                capabilities={"process_once": process_once})


if __name__ == "__main__":
    raise SystemExit(main())
