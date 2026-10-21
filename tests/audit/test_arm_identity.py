from __future__ import annotations

import copy

import pytest

from abcr.audit.evidence import _production_expected_keys
from abcr.control.contracts import ContractError


def _envelope() -> dict:
    configs = []
    for arm_id, condition in (("vanilla", "vanilla"),
                              ("persona-a", "persona_text"),
                              ("persona-b", "persona_text"),
                              ("length-a", "length_instruct"),
                              ("length-b", "length_instruct")):
        for seed in (7, 11):
            configs.append({"arm_id": arm_id, "condition": condition,
                            "item_ids": ["d1", "d2"],
                            "decoding": {"seeds": [seed]}})
    return {"batch_id": "EXP-0123456789abcdef0123",
            "item_ids": ["d1", "d2"], "seeds": [7, 11],
            "arms": [{"id": arm_id} for arm_id in
                     ("vanilla", "persona-a", "persona-b", "length-a", "length-b")],
            "run_configs": configs}


def test_same_condition_persona_arms_have_distinct_expected_keys() -> None:
    expected = _production_expected_keys(_envelope())
    persona = [key for key in expected if key[-1] == "persona_text"]
    assert len(persona) == 8
    assert {key[2] for key in persona} == {"persona-a", "persona-b"}
    assert len({(key[0], key[1]) for key in persona}) == 4


def test_missing_one_arm_seed_fails_closed() -> None:
    envelope = copy.deepcopy(_envelope())
    envelope["run_configs"] = [cfg for cfg in envelope["run_configs"]
                               if not (cfg["arm_id"] == "persona-b"
                                       and cfg["decoding"]["seeds"] == [11])]
    with pytest.raises(ContractError, match="arm×seed"):
        _production_expected_keys(envelope)
