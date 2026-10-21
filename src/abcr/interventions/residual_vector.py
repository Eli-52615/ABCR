"""Residual vector steering intervention (Package B).

Loads a standardized vector artifact and applies additive steering
to the residual stream at a specified layer via a forward hook.
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


def _load_models_yaml() -> dict:
    p = pathlib.Path("configs/models.yaml")
    if p.exists():
        return yaml.safe_load(p.read_text())
    return {}


def _model_config(model_key: str):
    from transformers import AutoConfig
    models = _load_models_yaml().get("models", {})
    entry = models.get(model_key, {})
    model_id = entry.get("model_id", model_key)
    revision = entry.get("revision", None)
    if revision and revision != "PIN-AT-CLOUD-PROVISION":
        return AutoConfig.from_pretrained(model_id, revision=revision)
    return AutoConfig.from_pretrained(model_id)


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


class ResidualVectorIntervention:
    def __init__(
        self,
        vector: torch.Tensor,
        card: dict,
        layer: int,
        coefficient: float,
        positions: str,
        vector_dir: str,
    ):
        self.vector = vector
        self.card = card
        self.layer = layer
        self.coefficient = coefficient
        self.positions = positions
        self._hook_handle = None
        self._model_ref = None
        self.capture_path: str | None = None
        self._capture_projections: list[float] = []
        self._capture_direction: torch.Tensor | None = None

        v_layer = vector[layer]
        norm = torch.linalg.norm(v_layer).item()
        self.spec = {
            "method": "residual_vector",
            "vector_dir": vector_dir,
            "layer": layer,
            "coefficient": coefficient,
            "trait": card.get("trait"),
            "positions": positions,
        }
        self.system_text = None
        self._intervention_strength = abs(coefficient) * norm
        self._v_layer = v_layer
        self._direction_unit = v_layer / (torch.linalg.norm(v_layer) + 1e-30)

    @contextmanager
    def context(self, model):
        v = self._v_layer.to(dtype=model.dtype, device=model.device)
        d_unit = self._direction_unit.to(dtype=model.dtype, device=model.device)
        coef = self.coefficient
        positions = self.positions
        capture_path = self.capture_path
        projections = self._capture_projections
        projections.clear()

        target_layer = model.model.layers[self.layer - 1]

        def hook_fn(module, input, output):
            if isinstance(output, tuple):
                h = output[0]
            else:
                h = output

            if positions == "response":
                is_prefill = h.shape[1] > 1 and not hasattr(module, "_past_seen")
                if is_prefill:
                    module._past_seen = True
                    if capture_path:
                        pass
                    return output
                module._past_seen = True
            # positions == "all" or response-mode decode step
            h_new = h + coef * v

            if capture_path:
                with torch.no_grad():
                    proj = (h_new[0, -1] * d_unit).sum().item()
                    projections.append(proj)

            if isinstance(output, tuple):
                return (h_new,) + output[1:]
            return h_new

        handle = target_layer.register_forward_hook(hook_fn)
        try:
            yield self
        finally:
            handle.remove()
            if hasattr(target_layer, "_past_seen"):
                del target_layer._past_seen
            if capture_path and projections:
                self._save_capture(capture_path, projections)

    def _save_capture(self, path: str, projections: list[float]):
        import numpy as np
        arr = np.array(projections, dtype=np.float32)
        meta = {
            "layer": self.layer,
            "coefficient": self.coefficient,
            "direction_source": "residual_vector",
            "trait": self.card.get("trait"),
            "n_tokens": len(projections),
        }
        np.savez(
            path,
            proj=arr,
            meta=np.array([json.dumps(meta)]),
        )

    def describe(self) -> dict:
        return {
            "condition": "residual_vector",
            "trait": self.card.get("trait"),
            "trait_pole": None,
            "method": "residual_vector",
            "layer": self.layer,
            "coefficient": self.coefficient,
            "intervention_strength": self._intervention_strength,
        }

    def activation_summary(self) -> dict | None:
        if not self.capture_path or not self._capture_projections:
            return None
        import numpy as np
        arr = np.array(self._capture_projections, dtype=np.float32)
        return {
            "path": self.capture_path,
            "layer": self.layer,
            "proj_mean": float(np.mean(arr)),
            "proj_p50": float(np.median(arr)),
            "proj_p90": float(np.percentile(arr, 90)),
        }


def build(spec: dict, model_key: str) -> ResidualVectorIntervention:
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
        raise AbcrError(E15_VECTOR_ARTIFACT_INVALID,
            f"pt_sha256 mismatch (card={card['pt_sha256']}, actual={actual_sha})"
        )

    vector = torch.load(pt_path, map_location="cpu", weights_only=True)
    cfg = _model_config(model_key)
    expected_layers = cfg.num_hidden_layers + 1
    expected_hidden = cfg.hidden_size
    if vector.shape != (expected_layers, expected_hidden):
        raise AbcrError(E15_VECTOR_ARTIFACT_INVALID,
            f"shape {vector.shape} != expected ({expected_layers}, {expected_hidden})"
        )

    layer = spec.get("layer") or card.get("recommended", {}).get("layer")
    coefficient = spec.get("coefficient")
    if coefficient is None:
        coefficient = card.get("recommended", {}).get("coef")
    positions = spec.get("positions", "response")

    if layer is None or coefficient is None:
        raise AbcrError(E15_VECTOR_ARTIFACT_INVALID,
            "layer/coefficient not in spec or card.recommended"
        )

    return ResidualVectorIntervention(
        vector=vector,
        card=card,
        layer=int(layer),
        coefficient=float(coefficient),
        positions=positions,
        vector_dir=str(vector_dir),
    )
