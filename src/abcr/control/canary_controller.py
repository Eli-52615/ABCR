"""External semantic canary; service self-reported health is insufficient."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from abcr.control.contracts import ContractError, canonical_json, require_id, sha256, strict_object, utc_now
from abcr.control.mission_pipeline import (artifact_object_id, resolve_sealed_tree, seal_json_artifact,
                                           validate_broker_ref)
from abcr.control.queue_runtime import WorkBrokerClient


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
    """Consume canary requests using a frozen external black-box probe argv."""
    from abcr.control.queue_runtime import queue_main

    def preflight(config: dict) -> None:
        settings = strict_object(config["settings"], required={
            "probe_argv", "trusted_release_root", "canary_staging_root"})
        argv = settings["probe_argv"]
        if (not isinstance(argv, list) or not argv
                or any(not isinstance(item, str) or not item or "\x00" in item for item in argv)
                or not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file()):
            raise ContractError("canary_probe_invalid", "external probe argv 不合法")
        for key in ("trusted_release_root", "canary_staging_root"):
            path = Path(settings[key])
            if path.is_symlink() or not path.is_dir():
                raise ContractError("canary_artifact_root_invalid", f"{key} 不可用")

    def make_handler(config: dict):
        argv = tuple(config["settings"]["probe_argv"])
        settings = config["settings"]
        client = WorkBrokerClient(Path(config["broker_socket"]))

        def handle(payload, work_id: str, fencing_token: int) -> dict:
            obj = strict_object(payload, required={
                "mission_id", "release_ref", "verification_ref", "expected_version",
                "old_release"})
            if obj["mission_id"] != work_id:
                raise ContractError("mission_work_identity_mismatch", "canary work identity 漂移")
            release_ref = validate_broker_ref(obj["release_ref"],
                                              expected_operation="seal_release")
            resolve_sealed_tree(release_ref, expected_operation="seal_release",
                                trusted_root=Path(settings["trusted_release_root"]))
            release_id = release_ref["object_id"]
            require_id(release_id, "release_id")
            if not isinstance(obj["expected_version"], str) or not obj["expected_version"]:
                raise ContractError("version_invalid", "expected_version 不合法")

            def external_probe() -> tuple[str | None, bool, str]:
                request = canonical_json({"release_id": release_id,
                                          "expected_version": obj["expected_version"]}) + b"\n"
                proc = subprocess.run(argv, input=request, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, timeout=30, check=False,
                                      shell=False, env={"PATH": "/usr/bin:/bin"})
                if proc.returncode != 0 or len(proc.stdout) > 65536:
                    return None, False, "probe_process_failed"
                response = json.loads(proc.stdout)
                exact = strict_object(response,
                                      required={"observed_version", "semantic_ok", "reason"})
                if (exact["observed_version"] is not None
                        and not isinstance(exact["observed_version"], str)):
                    raise ContractError("probe_response_invalid", "observed_version 不合法")
                if type(exact["semantic_ok"]) is not bool or not isinstance(exact["reason"], str):
                    raise ContractError("probe_response_invalid", "probe response 不合法")
                return exact["observed_version"], exact["semantic_ok"], exact["reason"][:256]

            result = run_canary(release_id, obj["expected_version"], external_probe)
            document = {"schema_version": 1, "kind": "canary", "mission_id": work_id,
                        "canary": result.__dict__, "release_ref": release_ref,
                        "verification_ref": obj["verification_ref"],
                        "old_release": obj["old_release"]}
            object_id = artifact_object_id("CNY", document)
            reference = seal_json_artifact(
                client, operation="seal_canary",
                staging_root=Path(settings["canary_staging_root"]),
                object_id=object_id, filename="canary.json", document=document,
                nonce=f"canary:{work_id}:{fencing_token}")
            return {"mission_id": work_id,
                    "verdict": "PASS" if result.semantic_ok else "FAIL",
                    "broker_ref": reference}
        return handle

    return queue_main(argv, service="canary-controller", stage="canary",
                      consumer="abcr-canary", preflight=preflight,
                      make_handler=make_handler)


if __name__ == "__main__":
    raise SystemExit(main())
