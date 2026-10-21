"""Read-only production probes for the Operator health cycle.

No probe installs, starts, stops, or signals a service.  launchd is queried in
read-only mode, broker stages use the producer-side result-list operation, and
the active release is bound by the root-owned service config plus launcher env.
Unprovable observations are emitted as failed facts and are therefore BLOCKED,
never optimistic PASS.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from abcr.control.contracts import ContractError, sha256
from abcr.control.health_runtime import (HealthFact, ServiceHealthSpec,
                                         ServiceObservation)
from abcr.control.queue_runtime import WorkBrokerClient
from abcr.control.store import ControlStore


@dataclass(frozen=True)
class LaunchdStatus:
    loaded: bool
    running: bool
    last_exit_ok: bool | None
    detail: dict[str, Any]


@dataclass(frozen=True)
class _ServiceProbe:
    label: str
    mode: str
    stage: str | None = None
    fault_domain: str = "engineering"


# Frozen to the reviewed service-topology-v1 contract.  A topology drift test
# prevents this collector from silently omitting a newly privileged service.
PRODUCTION_PROBES = (
    _ServiceProbe("com.abcr.human-gateway", "keepalive", fault_domain="tcb"),
    _ServiceProbe("com.abcr.operator-reconciler", "keepalive", fault_domain="tcb"),
    _ServiceProbe("com.abcr.probe-worker", "on_demand", "probe"),
    _ServiceProbe("com.abcr.itempool", "on_demand", "itempool"),
    _ServiceProbe("com.abcr.auditor", "on_demand", "audit"),
    _ServiceProbe("com.abcr.mission-builder", "on_demand", "mission-build"),
    _ServiceProbe("com.abcr.test-controller", "on_demand", "test", "tcb"),
    _ServiceProbe("com.abcr.verifier", "on_demand", "verify"),
    _ServiceProbe("com.abcr.canary-controller", "on_demand", "canary"),
    _ServiceProbe("com.abcr.release-activator", "on_demand", "release-prepare", "tcb"),
    _ServiceProbe("com.abcr.panel", "keepalive"),
    _ServiceProbe("com.abcr.seal-broker", "socket", "activate", "tcb"),
)
DISPATCH_SUPERVISOR_LABEL = "com.abcr.dispatch-supervisor"


def probe_launchd(label: str) -> LaunchdStatus:
    """Return launchd's protected process state without mutating it."""
    try:
        completed = subprocess.run(
            ["/bin/launchctl", "print", f"system/{label}"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=3, check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError) as exc:
        return LaunchdStatus(False, False, None,
                             {"error_class": type(exc).__name__})
    output = completed.stdout or ""
    state = re.search(r"(?m)^\s*state\s*=\s*([^\s]+)\s*$", output)
    exit_code = re.search(r"(?m)^\s*last exit code\s*=\s*(-?\d+)\s*$", output)
    parsed_exit = int(exit_code.group(1)) if exit_code else None
    return LaunchdStatus(
        loaded=completed.returncode == 0,
        running=bool(state and state.group(1) == "running"),
        last_exit_ok=None if parsed_exit is None else parsed_exit == 0,
        detail={"returncode": completed.returncode,
                "state": state.group(1) if state else "unknown",
                "last_exit_code": parsed_exit,
                "output_sha256": sha256(output.encode("utf-8"))})


def production_service_specs() -> dict[str, ServiceHealthSpec]:
    specs: dict[str, ServiceHealthSpec] = {}
    for probe in PRODUCTION_PROBES:
        if probe.fault_domain == "tcb":
            specs[probe.label] = ServiceHealthSpec(probe.label, tcb=True)
        elif probe.label == "com.abcr.panel":
            specs[probe.label] = ServiceHealthSpec(
                probe.label, reversible_codes=frozenset({"process_dead"}),
                mission_allowed_paths=("src/abcr/control/cards.py",),
                acceptance_profile="status-card-v1")
        else:
            specs[probe.label] = ServiceHealthSpec(probe.label)
    specs[DISPATCH_SUPERVISOR_LABEL] = ServiceHealthSpec(
        DISPATCH_SUPERVISOR_LABEL, tcb=True)
    return specs


def _broker_fact(client: WorkBrokerClient, probe: _ServiceProbe,
                 stamp: str) -> HealthFact | None:
    if probe.stage is None:
        return None
    try:
        pending_results = client.completed(probe.stage)
    except Exception as exc:
        code = exc.code if isinstance(exc, ContractError) else "network_timeout"
        return HealthFact("broker", f"work-stage-{probe.stage}", "semantic",
                          False, stamp, code=str(code),
                          fault_domain=probe.fault_domain,
                          detail={"operation": "work_result_list",
                                  "error_class": type(exc).__name__})
    return HealthFact("broker", f"work-stage-{probe.stage}", "semantic",
                      True, stamp,
                      detail={"operation": "work_result_list",
                              "pending_result_count": len(pending_results)})


def collect_production_observations(
        store: ControlStore, broker: WorkBrokerClient, *, active_release_id: str,
        launcher_release_id: str | None, supervisor_qualified: bool,
        supervisor_alive: bool, now: datetime | None = None,
        launchd_probe: Callable[[str], LaunchdStatus] = probe_launchd,
        ) -> tuple[ServiceObservation, ...]:
    """Collect all 12 reviewed services plus the dispatch supervisor child."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = current.isoformat(timespec="microseconds")
    release_ok = launcher_release_id == active_release_id
    release_detail = {"release_id": active_release_id if release_ok
                      else launcher_release_id,
                      "configured_release_id": active_release_id,
                      "launcher_release_id": launcher_release_id}
    observations: list[ServiceObservation] = []

    try:
        store.quick_check(); control_state_ok = True; control_state_code = None
    except Exception as exc:
        control_state_ok = False
        control_state_code = (exc.code if isinstance(exc, ContractError)
                              else "control_state_invalid")

    for probe in PRODUCTION_PROBES:
        facts = [HealthFact(
            "fixed_state", "sealed-active-release", "release", release_ok, stamp,
            code=None if release_ok else "release_identity_mismatch",
            fault_domain="integrity", detail=release_detail)]
        launchd = launchd_probe(probe.label)
        idle = probe.mode == "on_demand" and launchd.loaded and not launchd.running
        process_ok = (launchd.running if probe.mode in {"keepalive", "socket"}
                      else launchd.loaded and
                      (launchd.running or launchd.last_exit_ok is not False))
        liveness_code = (None if process_ok else "process_dead" if launchd.loaded
                         else "untrusted_health_evidence")
        liveness_domain = (probe.fault_domain if launchd.loaded
                           else "tcb")
        facts.append(HealthFact(
            "fixed_state", f"launchd-{probe.label}", "semantic", process_ok,
            stamp, code=liveness_code, fault_domain=liveness_domain,
            detail={**launchd.detail, "loaded": launchd.loaded,
                    "running": launchd.running, "idle": idle}))
        broker_fact = _broker_fact(broker, probe, stamp)
        if broker_fact is not None:
            facts.append(broker_fact)
        if probe.label in {"com.abcr.operator-reconciler", "com.abcr.panel"}:
            facts.append(HealthFact(
                "fixed_state", "control-store-quick-check", "semantic",
                control_state_ok, stamp, code=control_state_code,
                fault_domain="integrity" if not control_state_ok else "engineering",
                detail={"database": "quick_check", "fresh": True}))
        observations.append(ServiceObservation(
            probe.label, active_release_id, stamp, tuple(facts)))

    supervisor_ok = supervisor_qualified and supervisor_alive and release_ok
    supervisor_code = (None if supervisor_ok else
                       "dispatch_supervisor_unqualified" if not supervisor_qualified
                       else "process_dead")
    observations.append(ServiceObservation(
        DISPATCH_SUPERVISOR_LABEL, active_release_id, stamp,
        (HealthFact("fixed_state", "sealed-active-release", "release",
                    release_ok, stamp,
                    code=None if release_ok else "release_identity_mismatch",
                    fault_domain="integrity", detail=release_detail),
         HealthFact("fixed_state", "operator-child-handle", "semantic",
                    supervisor_ok, stamp, code=supervisor_code, fault_domain="tcb",
                    detail={"qualified": supervisor_qualified,
                            "alive": supervisor_alive}))))
    return tuple(observations)
