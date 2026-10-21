"""Loopback GET-only fallback panel; it cannot mutate the control plane."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from abcr.control.contracts import ControlSnapshot, canonical_json


def handler_factory(snapshot_provider: Callable[[], ControlSnapshot]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path not in {"/", "/api/v1/snapshot"}:
                self.send_error(404); return
            body = canonical_json(snapshot_provider().as_dict())
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def _readonly(self):
            body = json.dumps({"error": "read_only"}).encode()
            self.send_response(405); self.send_header("Allow", "GET")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        do_POST = do_PUT = do_PATCH = do_DELETE = _readonly
        def log_message(self, fmt, *args): return
    return Handler


def serve(snapshot_provider: Callable[[], ControlSnapshot], host: str = "127.0.0.1",
          port: int = 8765) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("panel must bind loopback")
    ThreadingHTTPServer((host, port), handler_factory(snapshot_provider)).serve_forever()


def main(argv: list[str] | None = None) -> int:
    """Fail closed until the public-snapshot source binding is frozen for launchd."""
    from abcr.control.service_runtime import blocked_runtime_main
    return blocked_runtime_main(argv, service="panel",
                                required_capability="serve",
                                capabilities={"serve": serve})


if __name__ == "__main__":
    raise SystemExit(main())
