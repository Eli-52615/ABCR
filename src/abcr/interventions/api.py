"""Frozen intervention interface — not modified after S0."""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from typing import Any, Protocol, runtime_checkable

from abcr.logging.errors import AbcrError, E05_CONFIG_INVALID


@runtime_checkable
class Intervention(Protocol):
    spec: dict
    system_text: str | None

    def context(self, model: Any) -> Any:
        ...

    def describe(self) -> dict:
        ...

    def activation_summary(self) -> dict | None:
        ...


class _NullIntervention:
    def __init__(self, spec: dict) -> None:
        self.spec = spec
        self.system_text = None
        self.capture_path: str | None = None

    @contextmanager
    def context(self, model: Any):
        yield

    def describe(self) -> dict:
        return {
            "condition": "vanilla",
            "trait": None,
            "trait_pole": None,
            "method": "none",
            "layer": None,
            "coefficient": None,
            "intervention_strength": None,
        }

    def activation_summary(self) -> dict | None:
        return None


def get_intervention(spec: dict, model_key: str) -> Intervention:
    method = spec.get("method", "none")
    if method == "none":
        return _NullIntervention(spec)  # type: ignore[return-value]
    module_name = f"abcr.interventions.{method}"
    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError:
        raise AbcrError(E05_CONFIG_INVALID, f"intervention module not found: {module_name}")
    return mod.build(spec, model_key)  # type: ignore[return-value]
