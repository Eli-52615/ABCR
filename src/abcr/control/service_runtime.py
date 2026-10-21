"""Fail-closed runtime gate for domain modules without a frozen wire adapter.

These modules already contain useful domain operations, but a callable function is
not itself a safe launchd service.  Until a queue/socket contract and its trusted
configuration are frozen, this gate makes that distinction executable: ``doctor``
is read-only and ``once`` cannot accidentally invent a transport or authority.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Callable, Mapping


EX_CONFIG = 78
DEFAULT_CONFIG_ROOT = Path("/Library/Application Support/ABCR-Bootstrap/config")
CONFIG_ROOT_ENV = "ABCR_ENTRYPOINT_CONFIG_ROOT"


class ServiceRuntimeBlocked(RuntimeError):
    """A deployment contract is absent or unsafe (message is never emitted)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _read_secure_json(path: Path, *, owner_uid: int) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ServiceRuntimeBlocked("trusted_runtime_contract_missing") from exc
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != owner_uid
                or stat.S_IMODE(before.st_mode) not in {0o440, 0o600}
                or before.st_size > 16 * 1024):
            raise ServiceRuntimeBlocked("trusted_runtime_contract_unsafe")
        chunks: list[bytes] = []
        remaining = before.st_size + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                                  value.st_nlink, value.st_uid,
                                  stat.S_IMODE(value.st_mode))
        if len(raw) != before.st_size or identity(before) != identity(after):
            raise ServiceRuntimeBlocked("trusted_runtime_contract_changed")
    finally:
        os.close(fd)

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ServiceRuntimeBlocked("trusted_runtime_contract_invalid")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ServiceRuntimeBlocked("trusted_runtime_contract_invalid") from exc
    if not isinstance(value, dict):
        raise ServiceRuntimeBlocked("trusted_runtime_contract_invalid")
    return value


def _contract_path(service: str, env: Mapping[str, str]) -> tuple[Path, int]:
    override = env.get(CONFIG_ROOT_ENV)
    if env.get("ABCR_SERVICE_LABEL"):
        if override:
            raise ServiceRuntimeBlocked("runtime_contract_override_forbidden")
        root, owner_uid = DEFAULT_CONFIG_ROOT, 0
    elif override:
        root, owner_uid = Path(override), os.getuid()
    else:
        root, owner_uid = DEFAULT_CONFIG_ROOT, 0
    try:
        info = root.lstat()
    except OSError as exc:
        raise ServiceRuntimeBlocked("trusted_runtime_root_missing") from exc
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != owner_uid or stat.S_IMODE(info.st_mode) & 0o022):
        raise ServiceRuntimeBlocked("trusted_runtime_root_unsafe")
    return root / f"{service}.json", owner_uid


def runtime_status(*, service: str, required_capability: str,
                   capabilities: Mapping[str, Callable[..., Any]],
                   env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Validate the domain surface and a root-owned explicit blocked contract.

    V1 intentionally accepts only ``state=blocked``.  Treating a hand-edited
    ``ready`` flag as authority would recreate the exact static-import false
    positive this gate closes.  A future runnable adapter must replace this gate
    with its own semantic doctor and queue/socket tests.
    """
    source = os.environ if env is None else env
    operation = capabilities.get(required_capability)
    if not callable(operation):
        raise ServiceRuntimeBlocked("domain_capability_missing")
    path, owner_uid = _contract_path(service, source)
    contract = _read_secure_json(path, owner_uid=owner_uid)
    required = {"schema_version", "service", "state", "reason_code"}
    if set(contract) != required:
        raise ServiceRuntimeBlocked("trusted_runtime_contract_invalid")
    if (contract["schema_version"] != 1 or contract["service"] != service
            or contract["state"] != "blocked"
            or not isinstance(contract["reason_code"], str)
            or not contract["reason_code"].startswith("adapter_")):
        raise ServiceRuntimeBlocked("trusted_runtime_contract_invalid")
    return {"ok": False, "service": service, "state": "BLOCKED",
            "error_code": contract["reason_code"]}


def blocked_runtime_main(argv: list[str] | None, *, service: str,
                         required_capability: str,
                         capabilities: Mapping[str, Callable[..., Any]]) -> int:
    parser = argparse.ArgumentParser(prog=service)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--doctor", action="store_true")
    modes.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    try:
        status = runtime_status(service=service,
                                required_capability=required_capability,
                                capabilities=capabilities)
    except ServiceRuntimeBlocked as exc:
        status = {"ok": False, "service": service, "state": "BLOCKED",
                  "error_code": exc.code}
    # Both paths are deliberately read-only.  --once is accepted so launchd and
    # an operator get a bounded response, but no domain mutation is authorized
    # before the missing adapter is implemented.
    stream = sys.stdout if args.doctor else sys.stderr
    print(json.dumps(status, ensure_ascii=False, sort_keys=True), file=stream)
    return EX_CONFIG
