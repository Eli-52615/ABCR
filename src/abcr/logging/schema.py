"""steps.jsonl schema w1.1 — field definitions, validation, canonical JSON."""

import json
from typing import Any

from .errors import AbcrError, E05_CONFIG_INVALID

SCHEMA_VERSION = "w1.1"

STEP_FIELDS: dict[str, tuple[type | tuple[type, ...], bool]] = {
    # meta
    "schema_version": (str, False),
    "run_id": (str, False),
    "trajectory_id": (str, False),
    "step_id": (int, False),
    "parent_run": ((str, type(None)), True),
    # provenance
    "git_commit": (str, False),
    "config_hash": (str, False),
    "protocol_ref": (str, False),
    "env_lock_ref": (str, False),
    # model
    "model_id": (str, False),
    "model_revision": (str, False),
    "dtype": (str, False),
    "quantization": ((str, type(None)), True),
    "device": (str, False),
    "device_backend": (str, False),
    "engine": (str, False),
    "engine_version": (str, False),
    "torch_version": (str, False),
    "cuda_version": ((str, type(None)), True),
    "chat_template_hash": (str, False),
    # data
    "benchmark": (str, False),
    "split_hash": (str, False),
    "item_id": (str, False),
    # condition
    "condition": (str, False),
    "trait": ((str, type(None)), True),
    "trait_pole": ((str, type(None)), True),
    "method": (str, False),
    "layer": ((int, type(None)), True),
    "coefficient": ((float, int, type(None)), True),
    "intervention_strength": ((float, int, type(None)), True),
    # trajectory
    "env_seed": ((int, type(None)), True),
    "action": ((str, type(None)), True),
    "obs_hash": ((str, type(None)), True),
    "remaining_budget": ((int, float, type(None)), True),
    "stop_reason": (str, False),
    "state_snapshot_ref": ((str, type(None)), True),
    # decoding
    "random_seed": (int, False),
    # IO
    "prompt_hash": (str, False),
    "output_text": (str, False),
    "parsed_answer": ((str, type(None)), True),
    "is_correct": ((bool, type(None)), True),
    "latency_ms": ((int, float), False),
    "input_tokens": (int, False),
    "output_tokens": (int, False),
    # eval
    "trait_score": ((float, int, type(None)), True),
    "fluency_score": ((float, int, type(None)), True),
    "safety_flags": (list, False),
    # activation
    "activation_summary": ((dict, type(None)), True),
    # marker
    "citable": (bool, False),
    # chain
    "prev_hash": (str, False),
    "entry_hash": (str, False),
}

VALID_CONDITIONS = {"vanilla", "prompt_persona", "residual_vector", "random_direction"}
VALID_STOP_REASONS = {"eos", "max_new_tokens", "error"}
VALID_METHODS = {"none", "prompt_persona", "residual_vector", "projection_ablation", "random_direction"}
VALID_TRAIT_POLES = {"pos", "neg", None}
VALID_DEVICE_BACKENDS = {"mps", "cuda", "cpu"}


def validate_step(d: dict[str, Any]) -> None:
    for field, (typ, nullable) in STEP_FIELDS.items():
        if field not in d:
            raise AbcrError(E05_CONFIG_INVALID, f"missing field: {field}")
        val = d[field]
        if val is None:
            if not nullable:
                raise AbcrError(E05_CONFIG_INVALID, f"field {field} cannot be null")
        else:
            if not isinstance(val, typ if isinstance(typ, tuple) else (typ,)):
                raise AbcrError(E05_CONFIG_INVALID, f"field {field}: expected {typ}, got {type(val)}")
    if d["schema_version"] != SCHEMA_VERSION:
        raise AbcrError(E05_CONFIG_INVALID, f"schema_version must be {SCHEMA_VERSION}")
    if d["condition"] not in VALID_CONDITIONS:
        raise AbcrError(E05_CONFIG_INVALID, f"invalid condition: {d['condition']}")
    if d["stop_reason"] not in VALID_STOP_REASONS:
        raise AbcrError(E05_CONFIG_INVALID, f"invalid stop_reason: {d['stop_reason']}")
    if d["method"] not in VALID_METHODS:
        raise AbcrError(E05_CONFIG_INVALID, f"invalid method: {d['method']}")
    if d.get("trait_pole") not in VALID_TRAIT_POLES:
        raise AbcrError(E05_CONFIG_INVALID, f"invalid trait_pole: {d.get('trait_pole')}")
    if d["device_backend"] not in VALID_DEVICE_BACKENDS:
        raise AbcrError(E05_CONFIG_INVALID, f"invalid device_backend: {d['device_backend']}")


def canonical_json(d: dict[str, Any]) -> str:
    filtered = {k: v for k, v in d.items() if k != "entry_hash"}
    return json.dumps(filtered, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
