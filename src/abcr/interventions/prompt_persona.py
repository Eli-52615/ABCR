"""Prompt-based persona intervention (Package B).

Pure text-level intervention: reads an instruction from a trait
artifact and returns it as system_text. No hooks, no torch.
"""
from __future__ import annotations

import json
import pathlib
from contextlib import nullcontext
from typing import Any


class PromptPersonaIntervention:
    def __init__(
        self,
        system_text: str,
        trait: str,
        trait_pole: str,
        instruction_index: int,
        artifact_path: str,
    ):
        self.system_text = system_text
        self.capture_path: str | None = None
        self.spec = {
            "method": "prompt_persona",
            "artifact": artifact_path,
            "instruction_index": instruction_index,
            "trait": trait,
            "trait_pole": trait_pole,
        }

    def context(self, model):
        return nullcontext(self)

    def describe(self) -> dict:
        return {
            "condition": f"prompt_persona_{self.spec['trait_pole']}",
            "trait": self.spec["trait"],
            "trait_pole": self.spec["trait_pole"],
            "method": "prompt_persona",
            "layer": None,
            "coefficient": None,
            "intervention_strength": None,
        }

    def activation_summary(self) -> dict | None:
        return None


def build(spec: dict, model_key: str) -> PromptPersonaIntervention:
    artifact_path = pathlib.Path(spec["artifact"])
    if not artifact_path.exists():
        raise FileNotFoundError(f"Trait artifact not found: {artifact_path}")

    artifact = json.loads(artifact_path.read_text())
    idx = spec["instruction_index"]
    trait = spec["trait"]
    pole = spec["trait_pole"]

    instructions = artifact.get("instruction", [])
    if idx >= len(instructions):
        raise IndexError(
            f"instruction_index {idx} out of range (have {len(instructions)})"
        )

    text = instructions[idx][pole]

    return PromptPersonaIntervention(
        system_text=text,
        trait=trait,
        trait_pole=pole,
        instruction_index=idx,
        artifact_path=str(artifact_path),
    )
