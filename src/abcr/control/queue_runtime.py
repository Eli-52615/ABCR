"""Peer-credential broker client shared by finite WorkSpool services.

Consumers never receive spool paths and never rename or create cross-UID files.
The root broker is the sole filesystem mutator; stage authority is checked from
the kernel-reported peer UID on every request.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import stat
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Mapping

from abcr.control.contracts import ContractError, canonical_json, strict_object
CONFIG_ROOT = Path("/Library/Application Support/ABCR-Bootstrap/config")
CONFIG_ROOT_ENV = "ABCR_QUEUE_CONFIG_ROOT"
EX_CONFIG = 78


class ServiceRuntimeBlocked(RuntimeError):
    def __init__(self, code: str): super().__init__(code); self.code = code


def _read_secure_json(path: Path, *, owner_uid: int) -> dict[str, Any]:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
                     | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ServiceRuntimeBlocked("trusted_queue_config_missing") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != owner_uid
                or stat.S_IMODE(info.st_mode) not in {0o440, 0o600}
                or info.st_size > 64 * 1024):
            raise ServiceRuntimeBlocked("trusted_queue_config_unsafe")
        raw = b""
        while len(raw) <= info.st_size:
            chunk = os.read(fd, info.st_size + 1 - len(raw))
            if not chunk: break
            raw += chunk
    finally: os.close(fd)
    if len(raw) != info.st_size:
        raise ServiceRuntimeBlocked("trusted_queue_config_changed")
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out: raise ServiceRuntimeBlocked("trusted_queue_config_invalid")
            out[key] = value
        return out
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ServiceRuntimeBlocked("trusted_queue_config_invalid")
    return value


def load_queue_config(service: str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    source = os.environ if env is None else env
    override = source.get(CONFIG_ROOT_ENV)
    if source.get("ABCR_SERVICE_LABEL") and override:
        raise ServiceRuntimeBlocked("queue_config_override_forbidden")
    root = Path(override) if override and not source.get("ABCR_SERVICE_LABEL") else CONFIG_ROOT
    owner = os.getuid() if override and not source.get("ABCR_SERVICE_LABEL") else 0
    try: info = root.lstat()
    except OSError as exc: raise ServiceRuntimeBlocked("trusted_queue_config_root_missing") from exc
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != owner or stat.S_IMODE(info.st_mode) & 0o022):
        raise ServiceRuntimeBlocked("trusted_queue_config_root_unsafe")
    value = _read_secure_json(root / f"{service}.json", owner_uid=owner)
    strict_object(value, required={"schema_version", "service", "broker_socket", "settings"})
    if (value["schema_version"] != 1 or value["service"] != service
            or not isinstance(value["broker_socket"], str)
            or not Path(value["broker_socket"]).is_absolute()
            or not isinstance(value["settings"], dict)):
        raise ServiceRuntimeBlocked("trusted_queue_config_invalid")
    return value


class WorkBrokerClient:
    def __init__(self, socket_path: Path): self.socket_path = Path(socket_path)

    def request(self, operation: str, arguments: dict[str, Any]) -> Any:
        request = {"schema_version": 1, "operation": operation, "arguments": arguments}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
            channel.settimeout(10); channel.connect(str(self.socket_path))
            channel.sendall(canonical_json(request) + b"\n")
            raw = b""
            while b"\n" not in raw and len(raw) <= 1024 * 1024:
                chunk = channel.recv(65536)
                if not chunk: break
                raw += chunk
        if len(raw) > 1024 * 1024 or raw.count(b"\n") != 1:
            raise ContractError("broker_response_invalid", "broker response framing 不合法")
        response = json.loads(raw)
        exact = strict_object(response, required={"ok"}, optional={"result", "error_code"})
        if exact.get("ok") is not True:
            raise ContractError(str(exact.get("error_code", "broker_rejected")), "broker 拒绝")
        return exact.get("result")

    def ready(self, stage: str) -> list[str]:
        result = self.request("work_list", {"stage": stage})
        if not isinstance(result, list) or any(not isinstance(item, str) for item in result):
            raise ContractError("broker_response_invalid", "work list 不合法")
        return result

    def completed(self, stage: str) -> list[str]:
        result = self.request("work_result_list", {"stage": stage})
        if not isinstance(result, list) or any(not isinstance(item, str) for item in result):
            raise ContractError("broker_response_invalid", "result list 不合法")
        return result

    def completed_fenced(self, stage: str) -> list[dict[str, Any]]:
        result = self.request("work_result_list", {"stage": stage, "include_fence": True})
        if not isinstance(result, list):
            raise ContractError("broker_response_invalid", "fenced result list 不合法")
        out = []
        for item in result:
            exact = strict_object(item, required={"work_id", "attempt", "fencing_token"})
            if (not isinstance(exact["work_id"], str) or type(exact["attempt"]) is not int
                    or type(exact["fencing_token"]) is not int or exact["attempt"] < 1
                    or exact["fencing_token"] < 1):
                raise ContractError("broker_response_invalid", "fenced result identity 不合法")
            out.append(exact)
        return out

    def read_result(self, stage: str, work_id: str, *, attempt: int = 1,
                    fencing_token: int = 1) -> dict[str, Any]:
        value = self.request("work_result_read", {"stage": stage, "work_id": work_id,
                                                   "attempt": attempt,
                                                   "fencing_token": fencing_token})
        return strict_object(value, required={"schema_version", "stage", "work_id",
                                              "attempt", "fencing_token", "consumer",
                                              "result", "result_hash", "completed_at"})

    def acknowledge(self, stage: str, work_id: str, *, result_hash: str,
                    attempt: int = 1, fencing_token: int = 1) -> dict[str, Any]:
        value = self.request("work_ack", {"stage": stage, "work_id": work_id,
                                          "attempt": attempt,
                                          "fencing_token": fencing_token,
                                          "result_hash": result_hash})
        return strict_object(value, required={"acked"})


def doctor(config: dict[str, Any], stage: str,
           preflight: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    preflight(config)
    client = WorkBrokerClient(Path(config["broker_socket"]))
    count = len(client.ready(stage))
    return {"ok": True, "stage": stage, "ready_items": count,
            "transport": "unix-peer-credentials"}


def run(config: dict[str, Any], stage: str, consumer: str,
        handler: Callable[[Any, str, int], dict[str, Any]], *, once: bool) -> int:
    client = WorkBrokerClient(Path(config["broker_socket"]))
    work_ids = client.ready(stage)
    count = 0
    for work_id in work_ids[:1] if once else work_ids:
        claim = client.request("work_claim", {"stage": stage, "work_id": work_id})
        if claim is None:
            continue
        exact = strict_object(claim, required={"work_id", "attempt", "fencing_token", "payload"})
        identity = {"stage": stage, "work_id": work_id, "attempt": exact["attempt"],
                    "fencing_token": exact["fencing_token"]}
        stop = threading.Event()

        def heartbeat() -> None:
            while not stop.wait(10):
                try: client.request("work_heartbeat", identity)
                except Exception: return

        ticker = threading.Thread(target=heartbeat, name=f"abcr-heartbeat-{stage}", daemon=True)
        ticker.start()
        try:
            result = {"ok": True, "result": handler(exact["payload"], work_id,
                                                       exact["fencing_token"])}
        except Exception as exc:
            code = exc.code if isinstance(exc, ContractError) else type(exc).__name__
            result = {"ok": False, "error_code": code}
        finally:
            stop.set(); ticker.join(timeout=1)
        client.request("work_result", {**identity, "consumer": consumer, "result": result})
        count += 1
    return count


def queue_main(argv: list[str] | None, *, service: str, stage: str, consumer: str,
               preflight: Callable[[dict[str, Any]], None],
               make_handler: Callable[[dict[str, Any]], Callable[[Any, str, int], dict[str, Any]]],
               ) -> int:
    parser = argparse.ArgumentParser(prog=service)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--doctor", action="store_true")
    modes.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_queue_config(service); preflight(config)
        if args.doctor:
            print(json.dumps(doctor(config, stage, preflight), sort_keys=True)); return 0
        run(config, stage, consumer, make_handler(config), once=args.once); return 0
    except Exception as exc:
        code = exc.code if isinstance(exc, (ContractError, ServiceRuntimeBlocked)) else type(exc).__name__
        print(json.dumps({"ok": False, "service": service, "stage": stage,
                          "error_code": code}, sort_keys=True), file=sys.stderr)
        return EX_CONFIG
