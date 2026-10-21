"""Random direction intervention (Package B).

Two modes:
1. Reference mode: match norm/layer/coef from an existing vector artifact
2. Literal mode: explicit layer/coefficient/target_norm
Both produce a deterministic random direction from direction_seed.
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


def _generate_random_vector(dim: int, seed: int, target_norm: float) -> torch.Tensor:
    gen = torch.Generator()
    gen.manual_seed(seed)
    r = torch.randn(dim, generator=gen)
    r = r / torch.linalg.norm(r)
    r = r * target_norm
    return r


class RandomDirectionIntervention:
    def __init__(
        self,
        random_vector: torch.Tensor,
        layer: int,
        coefficient: float,
        direction_seed: int,
        positions: str,
        spec_full: dict,
        reference_trait: str | None,
    ):
        self._random_vector = random_vector
        self.layer = layer
        self.coefficient = coefficient
        self.direction_seed = direction_seed
        self.positions = positions
        self.capture_path: str | None = None
        self._capture_projections: list[float] = []
        self._direction_unit = random_vector / (torch.linalg.norm(random_vector) + 1e-30)

        norm = torch.linalg.norm(random_vector).item()
        self._intervention_strength = abs(coefficient) * norm

        self.spec = spec_full
        self.system_text = None

    @contextmanager
    def context(self, model):
        v = self._random_vector.to(dtype=model.dtype, device=model.device)
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
                is_prefill = h.shape[1] > 1 and not hasattr(module, "_past_seen_rnd")
                if is_prefill:
                    module._past_seen_rnd = True
                    return output
                module._past_seen_rnd = True

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
            if hasattr(target_layer, "_past_seen_rnd"):
                del target_layer._past_seen_rnd
            if capture_path and projections:
                self._save_capture(capture_path, projections)

    def _save_capture(self, path: str, projections: list[float]):
        import numpy as np
        arr = np.array(projections, dtype=np.float32)
        meta = {
            "layer": self.layer,
            "coefficient": self.coefficient,
            "direction_source": "random_direction",
            "direction_seed": self.direction_seed,
            "n_tokens": len(projections),
        }
        np.savez(path, proj=arr, meta=np.array([json.dumps(meta)]))

    def describe(self) -> dict:
        return {
            "condition": "random_direction",
            "trait": None,
            "trait_pole": None,
            "method": "random_direction",
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


def build(spec: dict, model_key: str) -> RandomDirectionIntervention:
    direction_seed = spec["direction_seed"]

    if "match_to" in spec:
        # Reference mode
        vector_dir = pathlib.Path(spec["match_to"])
        pt_path = vector_dir / "response_avg_diff.pt"
        card_path = vector_dir / "card.json"
        if not pt_path.exists() or not card_path.exists():
            raise AbcrError(E15_VECTOR_ARTIFACT_INVALID, f"missing in {vector_dir}")
        card = json.loads(card_path.read_text())
        vector = torch.load(pt_path, map_location="cpu", weights_only=True)
        layer = spec.get("layer") or card.get("recommended", {}).get("layer")
        coefficient = spec.get("coefficient")
        if coefficient is None:
            coefficient = card.get("recommended", {}).get("coef")
        if layer is None or coefficient is None:
            raise AbcrError(E15_VECTOR_ARTIFACT_INVALID,
                "layer/coefficient not in spec or card.recommended")
        layer = int(layer)
        v_ref = vector[layer]
        target_norm = torch.linalg.norm(v_ref).item()
        hidden_dim = v_ref.shape[0]
        reference_trait = card.get("trait")
    else:
        # Literal mode
        layer = int(spec["layer"])
        coefficient = float(spec["coefficient"])
        target_norm = float(spec["target_norm"])
        cfg = _model_config(model_key)
        hidden_dim = cfg.hidden_size
        reference_trait = None

    random_vec = _generate_random_vector(hidden_dim, direction_seed, target_norm)

    return RandomDirectionIntervention(
        random_vector=random_vec,
        layer=layer,
        coefficient=float(coefficient),
        direction_seed=direction_seed,
        positions=spec.get("positions", "response"),
        spec_full=spec,
        reference_trait=reference_trait,
    )
