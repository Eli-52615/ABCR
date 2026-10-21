"""Loopback GET-only fallback panel; it cannot mutate the control plane."""
from __future__ import annotations

import argparse
import json
import os
import stat
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from abcr.control.contracts import ControlSnapshot, Severity, canonical_json, require_sha

DEFAULT_SNAPSHOT_PATH = Path(
    "/Library/Application Support/ABCR-Bridge/operator-status/public-snapshot.json")
_SNAPSHOT_FIELDS = frozenset({
    "snapshot_id", "generated_at", "source_hash", "stale_after", "sections", "severity"})


def load_snapshot(path: Path) -> ControlSnapshot:
    """Load one read-only materialized snapshot without following links."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_mode & 0o022 or info.st_size > 2 * 1024 * 1024):
            raise RuntimeError("public snapshot file is unsafe")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            value = json.load(stream)
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(value, dict) or set(value) != _SNAPSHOT_FIELDS:
        raise RuntimeError("public snapshot shape is invalid")
    if not isinstance(value["sections"], dict):
        raise RuntimeError("public snapshot sections must be an object")
    require_sha(value["source_hash"], "source_hash")
    try:
        severity = Severity(value["severity"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("public snapshot severity is invalid") from exc
    try:
        generated_at = datetime.fromisoformat(value["generated_at"])
        stale_after = datetime.fromisoformat(value["stale_after"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("public snapshot timestamps are invalid") from exc
    if (generated_at.tzinfo is None or stale_after.tzinfo is None
            or stale_after <= generated_at):
        raise RuntimeError("public snapshot freshness window is invalid")
    sections = value["sections"]
    if datetime.now(timezone.utc) > stale_after.astimezone(timezone.utc):
        # Staleness is derived at read time.  It never rewrites the signed/source
        # snapshot and never lets an old green state masquerade as current.
        severity = Severity.UNKNOWN
        sections = dict(sections)
        sections["状态说明"] = "快照已过期；运行状态未知，请以飞书驾驶舱刷新结果为准。"
    return ControlSnapshot(
        snapshot_id=value["snapshot_id"], generated_at=value["generated_at"],
        source_hash=value["source_hash"], stale_after=value["stale_after"],
        sections=sections, severity=severity)


def handler_factory(snapshot_provider: Callable[[], ControlSnapshot]):
    class Handler(BaseHTTPRequestHandler):
        def _local_request(self) -> bool:
            host = self.headers.get("Host", "").lower()
            allowed_hosts = {"127.0.0.1", "localhost", "[::1]"}
            hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]", 1)[0] + "]"
            origin = self.headers.get("Origin")
            if hostname not in allowed_hosts:
                return False
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme != "http" or parsed.hostname not in {
                        "127.0.0.1", "localhost", "::1"}:
                    return False
            return True

        def do_GET(self):  # noqa: N802
            if not self._local_request():
                self.send_error(403); return
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
    parser = argparse.ArgumentParser(description="ABCR loopback read-only panel")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    snapshot = load_snapshot(args.snapshot)
    if args.doctor:
        print(json.dumps({"ok": True, "snapshot_id": snapshot.snapshot_id,
                          "source_hash": snapshot.source_hash, "read_only": True},
                         sort_keys=True))
        return 0
    serve(lambda: load_snapshot(args.snapshot), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
