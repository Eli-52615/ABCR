"""Contract test: preflight checks E01–E06 trigger precisely."""

import hashlib
import json
import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from abcr.logging.errors import (
    AbcrError,
    E01_PREFLIGHT_GIT_DIRTY, E02_REVISION_MISMATCH, E03_TEMPLATE_HASH_MISMATCH,
    E04_SPLIT_HASH_MISMATCH, E05_CONFIG_INVALID, E06_ARM_PURITY_VIOLATION,
)
from abcr.run import _preflight, _validate_config, _check_arm_purity


def _base_config():
    return {
        "model_key": "tinyqwen",
        "condition": "vanilla",
        "intervention": {"method": "none"},
        "data": {
            "family": "fixture",
            "items": "tests/fixtures/items_fixture.jsonl",
            "split_file": "tests/fixtures/split_fixture.json",
            "split": "dev",
        },
        "decoding": {
            "temperature": 0.7,
            "seeds": [42],
            "max_new_tokens": 64,
        },
    }


def test_e05_missing_key():
    cfg = _base_config()
    del cfg["model_key"]
    with pytest.raises(AbcrError) as exc:
        _validate_config(cfg)
    assert E05_CONFIG_INVALID in str(exc.value)


def test_e05_invalid_condition():
    cfg = _base_config()
    cfg["condition"] = "invalid_cond"
    with pytest.raises(AbcrError) as exc:
        _validate_config(cfg)
    assert E05_CONFIG_INVALID in str(exc.value)


def test_e05_invalid_model_key():
    cfg = _base_config()
    cfg["model_key"] = "nonexistent_model"
    with pytest.raises(AbcrError) as exc:
        _validate_config(cfg)
    assert E05_CONFIG_INVALID in str(exc.value)


def test_e06_vector_keys_in_text_method():
    cfg = _base_config()
    cfg["intervention"] = {
        "method": "prompt_persona",
        "vector_dir": "/some/path",
        "artifact": "artifacts/test.json",
        "instruction_index": 0,
    }
    with pytest.raises(AbcrError) as exc:
        _check_arm_purity(cfg)
    assert E06_ARM_PURITY_VIOLATION in str(exc.value)


def test_e06_persona_keys_in_vector_method():
    cfg = _base_config()
    cfg["intervention"] = {
        "method": "residual_vector",
        "artifact": "artifacts/test.json",
        "vector_dir": "/some/path",
    }
    with pytest.raises(AbcrError) as exc:
        _check_arm_purity(cfg)
    assert E06_ARM_PURITY_VIOLATION in str(exc.value)


def test_e06_none_method_rejects_both():
    cfg = _base_config()
    cfg["intervention"] = {
        "method": "none",
        "vector_dir": "/some/path",
    }
    with pytest.raises(AbcrError) as exc:
        _check_arm_purity(cfg)
    assert E06_ARM_PURITY_VIOLATION in str(exc.value)

    cfg["intervention"] = {
        "method": "none",
        "artifact": "artifacts/test.json",
    }
    with pytest.raises(AbcrError) as exc:
        _check_arm_purity(cfg)
    assert E06_ARM_PURITY_VIOLATION in str(exc.value)


def test_e06_clean_configs_pass():
    cfg = _base_config()
    _check_arm_purity(cfg)

    cfg["intervention"] = {
        "method": "prompt_persona",
        "artifact": "artifacts/test.json",
        "instruction_index": 0,
    }
    _check_arm_purity(cfg)

    cfg["intervention"] = {
        "method": "residual_vector",
        "vector_dir": "/some/path",
    }
    _check_arm_purity(cfg)
