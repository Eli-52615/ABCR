from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from abcr.control.contracts import require_sha
from abcr.explore.item_pool import DevBundleRef
from abcr.explore.length_control import (load_task_expansion_library,
                                         validate_task_expansion_plan_receipt)


_DEFAULT_LENGTH_LIBRARY = (Path(__file__).resolve().parents[1] / "explore" / "resources" /
                           "task_expansion_zh_v1.json")


@dataclass(frozen=True)
class ProbePersona:
    """One explicitly versioned persona arm in a fast-lane probe.

    ``arm_id`` is derived from the registry reference instead of being supplied by
    the queue producer.  That keeps the cell identity stable and prevents two
    differently rendered personas from being hidden behind the same arm label.
    """

    persona_ref: str
    persona_text: str

    def __post_init__(self) -> None:
        if (not isinstance(self.persona_ref, str) or not self.persona_ref.strip()
                or len(self.persona_ref) > 512):
            raise ValueError("probe persona_ref must be a non-empty bounded string")
        if (not isinstance(self.persona_text, str) or not self.persona_text.strip()
                or len(self.persona_text) > 65536):
            raise ValueError("probe persona_text must be a non-empty bounded string")

    @property
    def arm_id(self) -> str:
        return f"persona:{self.persona_ref}"


@dataclass(frozen=True)
class ProbeRequest:
    probe_id: str
    goal_hash: str
    dev_bundle: DevBundleRef
    personas: tuple[ProbePersona, ...]
    prediction: str
    seed: int
    model_profile: str
    max_output_tokens: int = 256
    with_length_control: bool = False
    length_controls: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        require_sha(self.goal_hash, "goal_hash")
        if (not isinstance(self.probe_id, str) or not self.probe_id.strip()
                or len(self.probe_id) > 128):
            raise ValueError("invalid probe_id")
        if (not isinstance(self.personas, tuple) or not 1 <= len(self.personas) <= 3
                or any(not isinstance(persona, ProbePersona) for persona in self.personas)):
            raise ValueError("probe requires 1-3 explicit personas")
        refs = [persona.persona_ref for persona in self.personas]
        if len(refs) != len(set(refs)):
            raise ValueError("probe persona refs must be unique")
        if (not isinstance(self.prediction, str) or not self.prediction.strip()
                or "\n" in self.prediction or "\r" in self.prediction
                or len(self.prediction.encode("utf-8")) > 8192):
            raise ValueError("probe requires one explicit prediction line")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("probe seed must be an integer")
        if not isinstance(self.model_profile, str) or not self.model_profile.strip():
            raise ValueError("invalid model_profile")
        if (isinstance(self.max_output_tokens, bool)
                or not isinstance(self.max_output_tokens, int)
                or self.max_output_tokens < 1 or self.max_output_tokens > 4096):
            raise ValueError("invalid max_output_tokens")
        if not isinstance(self.with_length_control, bool):
            raise ValueError("with_length_control must be boolean")
        if not isinstance(self.length_controls, tuple):
            raise ValueError("length_controls must be a tuple")
        if not self.with_length_control:
            if self.length_controls:
                raise ValueError("unrequested length_controls are forbidden")
            return
        if len(self.length_controls) != len(self.personas):
            raise ValueError("probe ③L requires one precompiled control per persona")
        library = load_task_expansion_library(_DEFAULT_LENGTH_LIBRARY)
        by_ref = {persona.persona_ref: persona for persona in self.personas}
        seen: set[str] = set()
        for value in self.length_controls:
            if (not isinstance(value, dict) or set(value) != {"persona_ref", "plan"}
                    or value["persona_ref"] not in by_ref
                    or value["persona_ref"] in seen):
                raise ValueError("probe ③L persona binding is missing or duplicated")
            seen.add(value["persona_ref"])
            plan = value["plan"]
            try:
                validate_task_expansion_plan_receipt(
                    plan, by_ref[value["persona_ref"]].persona_text,
                    self.dev_bundle.item_ids,
                    tokenizer_sha256=plan.get("tokenizer_sha256", "")
                    if isinstance(plan, dict) else "",
                    chat_template_sha256=plan.get("chat_template_sha256", "")
                    if isinstance(plan, dict) else "",
                    library=library,
                )
            except Exception as exc:
                raise ValueError("probe ③L precompiled plan failed verification") from exc
        if seen != set(by_ref):
            raise ValueError("probe ③L must cover every persona")

    @property
    def arm_ids(self) -> tuple[str, ...]:
        """Vanilla is structural and therefore cannot be omitted by a caller."""
        persona_arms = tuple(persona.arm_id for persona in self.personas)
        length_arms = (() if not self.with_length_control else
                       tuple(f"length:{persona.persona_ref}" for persona in self.personas))
        return ("vanilla", *persona_arms, *length_arms)


@dataclass(frozen=True)
class ProbeRoots:
    lab_root: str
    snippets_root: str | None = None
    model_root: str | None = None


@dataclass(frozen=True)
class EngineOutput:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    engine_version: str
