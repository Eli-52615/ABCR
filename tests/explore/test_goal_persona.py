from __future__ import annotations

import json

import pytest

from abcr.control.contracts import ContractError
from abcr.explore.goal import validate_goal
from abcr.explore.length_control import build_3l
from abcr.explore.personas import PersonaRegistry


def valid_goal() -> bytes:
    return b"""goal_id: G-1
title: test
design_origin: human_claude_manual
hypothesis: persona changes behavior
template_id: persona_control
split: dev
personas: [p@v1]
arms:
  - {id: control, kind: vanilla}
  - {id: persona, kind: persona}
predictions:
  - {task_family: ifeval, direction: increase, rationale: explicit prediction}
falsifier: no directional difference
metrics: [is_correct]
item_count: 2
seeds: [1, 2]
max_cost_usd: 0
decision_rules: {if_support: retain, if_refute: revise}
"""


def test_goal_strict_happy_and_hash_stable():
    first = validate_goal(valid_goal())
    second = validate_goal(valid_goal())
    assert first.ok and first.goal is not None
    assert first.goal.goal_hash == second.goal.goal_hash
    assert first.goal.design_origin == "human_claude_manual"


@pytest.mark.parametrize("raw,code", [
    (valid_goal() + b"---\n{}\n", "multi_document"),
    (valid_goal().replace(b"title: test", b"title: test\ntitle: second"), "duplicate_key"),
    (valid_goal().replace(b"title: test", b"title: &x test\nhypothesis: *x"), "yaml_indirection_forbidden"),
])
def test_goal_parser_attacks_reject(raw, code):
    report = validate_goal(raw)
    assert not report.ok
    assert report.defects[0]["code"] == code


def test_goal_never_invents_bad_fields():
    raw = valid_goal().replace(b"split: dev", b"split: holdout").replace(
        b"human_claude_manual", b"automatic_llm")
    report = validate_goal(raw)
    assert not report.ok and report.goal is None
    assert {x["code"] for x in report.defects} >= {"bad_origin", "non_dev_split"}


@pytest.mark.parametrize("old,new", [
    (b"template_id: persona_control", b"template_id: [persona_control]"),
    (b"seeds: [1, 2]", b"seeds: [[1]]"),
    (b"metrics: [is_correct]", b"metrics: [is_correct, is_correct]"),
    (b"  - {id: control, kind: vanilla}", b"  - {id: duplicate, kind: persona}"),
])
def test_untrusted_goal_types_return_defects_not_exceptions(old, new):
    report = validate_goal(valid_goal().replace(old, new))
    assert not report.ok and report.defects


def test_persona_one_component_lineage_and_3l():
    registry = PersonaRegistry()
    parent = registry.add({"persona_id": "p", "version": 1, "parent_ref": None,
                           "components": {"stance": "MARKER careful", "tone": "neutral"},
                           "changed_component": None, "manipulation_checks": ["MARKER"]})
    child = registry.add({"persona_id": "p", "version": 2, "parent_ref": "p@v1",
                          "components": {"stance": "MARKER very careful", "tone": "neutral"},
                          "changed_component": "stance", "manipulation_checks": ["MARKER"]})
    assert child.parent_ref == parent.ref
    variants = build_3l("MARKER", {"short": 2, "medium": 3, "long": 4},
                        encode=lambda x: x.split(), padding_units=(" pad",),
                        required_markers=("MARKER",))
    assert [x.token_count for x in variants] == [2, 3, 4]


def test_persona_multi_component_change_rejects():
    registry = PersonaRegistry()
    registry.add({"persona_id": "p", "version": 1, "parent_ref": None,
                  "components": {"a": "1", "b": "2"}, "changed_component": None,
                  "manipulation_checks": ["1"]})
    with pytest.raises(ContractError) as exc:
        registry.add({"persona_id": "p", "version": 2, "parent_ref": "p@v1",
                      "components": {"a": "x", "b": "y"}, "changed_component": "a",
                      "manipulation_checks": ["x"]})
    assert exc.value.code == "persona_multi_component_diff"
