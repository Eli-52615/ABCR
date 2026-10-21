from __future__ import annotations

from dataclasses import dataclass

from abcr.control.contracts import require_sha
from abcr.explore.item_pool import DevBundleRef


@dataclass(frozen=True)
class ProbeRequest:
    probe_id: str
    goal_hash: str
    dev_bundle: DevBundleRef
    persona_ref: str
    persona_text: str
    prediction: str
    seed: int
    model_profile: str
    max_output_tokens: int = 256

    def __post_init__(self) -> None:
        require_sha(self.goal_hash, "goal_hash")
        if not self.persona_text.strip() or not self.prediction.strip():
            raise ValueError("probe requires explicit persona and prediction")
        if self.max_output_tokens < 1 or self.max_output_tokens > 4096:
            raise ValueError("invalid max_output_tokens")


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
