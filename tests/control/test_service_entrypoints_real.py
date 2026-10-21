from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _topology_services() -> list[dict[str, object]]:
    value = json.loads(
        (ROOT / "configs/control/service-topology-v1.json").read_text(encoding="utf-8"))
    assert value["schema_version"] == 1
    services = value["services"]
    assert isinstance(services, list) and len(services) == 12
    return services


def test_all_topology_entrypoints_are_real_runtime_mains() -> None:
    """Prevent callable-but-permanently-BLOCKED stubs from satisfying deployment."""
    for service in _topology_services():
        module_name = service["module"]
        assert isinstance(module_name, str)
        module = importlib.import_module(module_name)
        assert callable(module.main), module_name
        source = inspect.getsource(module.main)
        assert "blocked_runtime_main" not in source, module_name
        assert "required_capability" not in source, module_name


def test_retired_blocked_runtime_adapter_is_absent() -> None:
    assert not (ROOT / "src/abcr/control/service_runtime.py").exists()
