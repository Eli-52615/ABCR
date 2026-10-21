"""Projection ablation intervention (Package B).

Removes the component of the hidden state along the persona vector
direction: h <- h - (h . v_hat) * v_hat
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from contextlib import contextmanager
from typing import Any

import torch
import yaml

from abcr.logging.errors import AbcrError, E15_VECTOR_ARTIFACT_INVALID


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _model_config(model_key: str):
    from transformers import AutoConfig
    p = pathlib.Path("configs/models.yaml")
    models = yaml.safe_load(p.read_text()).get("models", {}) if p.exists() else {}
    entry = models.get(model_key, {})
    model_id = entry.get("model_id", model_key)
    revision = entry.get("revision", None)
    if revision and revision != "PIN-AT-CLOUD-PROVISION":
        return AutoConfig.from_pretrained(model_id, revision=revision)
    return AutoConfig.from_pretrained(model_id)


class ProjectionAblationIntervention:
    def __init__(
        self,
        vector: torch.Tensor,
        card: dict,
        layer: int,
        positions: str,
        vector_dir: str,
    ):
        self.vector = vector
        self.card = card
        self.layer = layer
        self.positions = positions
        self.capture_path: str | None = None
        self._capture_projections: list[float] = []

        v_layer = vector[layer]
        v_unit = v_layer / (torch.linalg.norm(v_layer) + 1e-30)
        self._v_unit = v_unit

        self.spec = {
            "method": "projection_ablation",
            "vector_dir": vector_dir,
            "layer": layer,
            "trait": card.get("trait"),
            "positions": positions,
        }
        self.system_text = None

    @contextmanager
    def context(self, model):
        v_unit = self._v_unit.to(dtype=model.dtype, device=model.device)
        positions = self.positions
        target_layer = model.model.layers[self.layer - 1]

        def hook_fn(module, input, output):
            if isinstance(output, tuple):
                h = output[0]
            else:
                h = output

            if positions == "response":
                is_prefill = h.shape[1] > 1 and not hasattr(module, "_past_seen_abl")
                if is_prefill:
                    module._past_seen_abl = True
                    return output
                module._past_seen_abl = True

            proj = (h * v_unit).sum(dim=-1, keepdim=True)
            h_new = h - proj * v_unit

            if isinstance(output, tuple):
                return (h_new,) + output[1:]
            return h_new

        handle = target_layer.register_forward_hook(hook_fn)
        try:
            yield self
        finally:
            handle.remove()
            if hasattr(target_layer, "_past_seen_abl"):
                del target_layer._past_seen_abl

    def describe(self) -> dict:
        return {
            "condition": "projection_ablation",
            "trait": self.card.get("trait"),
            "trait_pole": None,
            "method": "projection_ablation",
            "layer": self.layer,
            "coefficient": None,
            "intervention_strength": None,
        }

    def activation_summary(self) -> dict | None:
        return None


def build(spec: dict, model_key: str) -> ProjectionAblationIntervention:
    vector_dir = pathlib.Path(spec["vector_dir"])
    pt_path = vector_dir / "response_avg_diff.pt"
    card_path = vector_dir / "card.json"
    meta_path = vector_dir / "extraction_meta.json"

    for p in [pt_path, card_path, meta_path]:
        if not p.exists():
            raise AbcrError(E15_VECTOR_ARTIFACT_INVALID, f"missing {p}")

    card = json.loads(card_path.read_text())
    actual_sha = _sha256_file(pt_path)
    if card.get("pt_sha256") and card["pt_sha256"] != actual_sha:
        raise AbcrError(E15_VECTOR_ARTIFACT_INVALID, "pt_sha256 mismatch")

    vector = torch.load(pt_path, map_location="cpu", weights_only=True)
    cfg = _model_config(model_key)
    expected_shape = (cfg.num_hidden_layers + 1, cfg.hidden_size)
    if vector.shape != expected_shape:
        raise AbcrError(E15_VECTOR_ARTIFACT_INVALID,
            f"shape {vector.shape} != {expected_shape}")

    layer = spec.get("layer") or card.get("recommended", {}).get("layer")
    positions = spec.get("positions", "response")
    if layer is None:
        raise AbcrError(E15_VECTOR_ARTIFACT_INVALID,
            "layer not specified in spec or card.recommended")

    return ProjectionAblationIntervention(
        vector=vector,
        card=card,
        layer=int(layer),
        positions=positions,
        vector_dir=str(vector_dir),
    )
