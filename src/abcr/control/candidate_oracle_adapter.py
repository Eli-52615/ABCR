"""Frozen candidate-side adapter for the controller's black-box protocol.

The adapter has no verdict authority.  It computes a small deterministic fact
from the candidate runtime; the trusted parent independently compares that fact
with the reviewed oracle profile and signs the resulting receipt.
"""
from __future__ import annotations

import importlib
import json
import sys
from typing import Any


MAX_REQUEST_BYTES = 64 * 1024
SERVICE_MODULES = (
    "abcr.control.human_gateway",
    "abcr.control.operator",
    "abcr.probe.service",
    "abcr.explore.itempool_service",
    "abcr.audit.service",
    "abcr.control.mission_worker",
    "abcr.control.test_controller",
    "abcr.control.verifier",
    "abcr.control.canary_controller",
    "abcr.control.release",
    "abcr.control.panel",
    "abcr.control.seal_broker",
)
STATUS_RESULT = {
    "fixture": "status-card", "runtime": "frozen-python-I",
    "service_count": len(SERVICE_MODULES), "all_main_callable": True,
}
DOCUMENT_RESULT = {"fixture": "marked-document", "marker": "ABCR-reviewed-v1"}


def _strict(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    if not isinstance(value, dict):
        raise ValueError("request is not an object")
    return value


def _status(request: dict[str, Any]) -> dict[str, Any]:
    if request != {"fixture": "status-card", "expected": STATUS_RESULT}:
        raise ValueError("status-card request is not the frozen profile")
    loaded = tuple(importlib.import_module(module) for module in SERVICE_MODULES)
    if not all(callable(getattr(module, "main", None)) for module in loaded):
        raise ValueError("candidate service main is unavailable")
    return STATUS_RESULT


def _document(request: dict[str, Any]) -> dict[str, Any]:
    if request != {"fixture": "marked-document", "expected": DOCUMENT_RESULT}:
        raise ValueError("document request is not the frozen profile")
    return DOCUMENT_RESULT


def main() -> int:
    raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
    if not raw or len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
        return 2
    if sys.stdin.buffer.read(1):
        return 2
    try:
        value = _strict(raw)
        if set(value) != {"protocol", "oracle_id", "version", "nonce", "request"}:
            return 2
        if (value["protocol"] != "abcr-oracle-v1" or value["version"] != "1"
                or not isinstance(value["nonce"], str) or len(value["nonce"]) != 64
                or not isinstance(value["request"], dict)):
            return 2
        if value["oracle_id"] == "status-card-v1":
            result = _status(value["request"])
        elif value["oracle_id"] == "doc-marker-v1":
            result = _document(value["request"])
        else:
            return 2
    except (ImportError, OSError, ValueError):
        return 2
    response = {"nonce": value["nonce"], "result": result}
    sys.stdout.buffer.write(json.dumps(
        response, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
