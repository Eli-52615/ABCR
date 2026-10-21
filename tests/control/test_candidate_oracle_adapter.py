"""Candidate adapter speaks one finite protocol and has no verdict output."""
from __future__ import annotations

import json
import subprocess
import sys

from abcr.control.candidate_oracle_adapter import DOCUMENT_RESULT, STATUS_RESULT


NONCE = "a" * 64


def _invoke(raw: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "abcr.control.candidate_oracle_adapter"],
        input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=20)


def _request(oracle_id: str, request: dict) -> bytes:
    return (json.dumps({
        "protocol": "abcr-oracle-v1", "oracle_id": oracle_id,
        "version": "1", "nonce": NONCE, "request": request,
    }, sort_keys=True, separators=(",", ":")) + "\n").encode()


def test_frozen_status_adapter_imports_exact_twelve_services() -> None:
    outcome = _invoke(_request(
        "status-card-v1", {"fixture": "status-card", "expected": STATUS_RESULT}))
    assert outcome.returncode == 0, outcome.stderr.decode()
    assert json.loads(outcome.stdout) == {"nonce": NONCE, "result": STATUS_RESULT}
    assert b"verdict" not in outcome.stdout and b"PASS" not in outcome.stdout


def test_frozen_document_adapter_returns_only_reviewed_marker() -> None:
    outcome = _invoke(_request(
        "doc-marker-v1", {"fixture": "marked-document", "expected": DOCUMENT_RESULT}))
    assert outcome.returncode == 0
    assert json.loads(outcome.stdout) == {"nonce": NONCE, "result": DOCUMENT_RESULT}


def test_caller_cannot_change_expected_result_or_add_input() -> None:
    changed = _invoke(_request(
        "status-card-v1", {"fixture": "status-card", "expected": {"ok": True}}))
    trailing = _invoke(_request(
        "doc-marker-v1", {"fixture": "marked-document", "expected": DOCUMENT_RESULT}) + b"x")
    duplicate = _invoke(
        (f'{{"protocol":"abcr-oracle-v1","protocol":"other",'
         f'"oracle_id":"doc-marker-v1","version":"1","nonce":"{NONCE}",'
         '"request":{}}\n').encode())
    assert [(item.returncode, item.stdout) for item in (changed, trailing, duplicate)] == [
        (2, b""), (2, b""), (2, b"")]
