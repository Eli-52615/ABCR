from __future__ import annotations

import json
from pathlib import Path

import pytest

from abcr.control.contracts import ContractError
from abcr.explore.goal import READY_TEMPLATES, validate_goal
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
  - {id: persona, kind: persona, persona_ref: p@v1}
  - {id: length, kind: length, persona_ref: p@v1}
predictions:
  - {task_family: ifeval, direction: increase, rationale: explicit prediction}
falsifier: no directional difference
metrics: [is_correct]
item_count: 2
seeds: [1, 2]
max_cost_usd: 0
decision_rules: {if_support: retain, if_refute: revise}
"""


def behavior_probe_goal() -> bytes:
    return valid_goal().replace(
        b"template_id: persona_control", b"template_id: behavior_probe"
    ).replace(
        b"  - {id: length, kind: length, persona_ref: p@v1}\n", b""
    )


def test_goal_strict_happy_and_hash_stable():
    first = validate_goal(valid_goal())
    second = validate_goal(valid_goal())
    assert first.ok and first.goal is not None
    assert first.goal.goal_hash == second.goal.goal_hash
    assert first.goal.design_origin == "human_claude_manual"


def test_behavior_probe_may_omit_optional_length_control():
    report = validate_goal(behavior_probe_goal())
    assert report.ok and report.goal is not None
    assert [arm["kind"] for arm in report.goal.arms] == ["vanilla", "persona"]


def test_packaged_template_registry_matches_review_source_and_blocks_unbuilt_templates():
    root = Path(__file__).resolve().parents[2]
    reviewed = root / "configs" / "research" / "templates" / "registry.json"
    packaged = root / "src" / "abcr" / "explore" / "resources" / "template_registry_v1.json"
    assert reviewed.read_bytes() == packaged.read_bytes()
    assert {"light_agentic", "internal_mediation", "confirmation"}.isdisjoint(
        READY_TEMPLATES)
    for template_id in ("light_agentic", "internal_mediation", "confirmation"):
        report = validate_goal(valid_goal().replace(
            b"template_id: persona_control", f"template_id: {template_id}".encode()))
        assert not report.ok
        assert any(defect["code"] == "template_unavailable" for defect in report.defects)


@pytest.mark.parametrize("template_id", ["component_ablation", "dose_response"])
def test_template_registry_min_arms_is_enforced(template_id):
    report = validate_goal(behavior_probe_goal().replace(
        b"template_id: behavior_probe", f"template_id: {template_id}".encode()))
    assert not report.ok
    assert any(defect["code"] == "bad_arms" and "3" in defect["message"]
               for defect in report.defects)


@pytest.mark.parametrize("attack", ["missing_length", "duplicate_length", "outside_persona"])
def test_required_length_policy_rejects_incomplete_duplicate_or_foreign_pair(attack):
    raw = valid_goal()
    if attack == "missing_length":
        raw = raw.replace(
            b"  - {id: length, kind: length, persona_ref: p@v1}\n", b"")
    elif attack == "duplicate_length":
        raw = raw.replace(
            b"predictions:\n",
            b"  - {id: length-2, kind: length, persona_ref: p@v1}\npredictions:\n",
        )
    else:
        raw = raw.replace(b"persona_ref: p@v1}\npredictions:",
                          b"persona_ref: foreign@v1}\npredictions:")
    report = validate_goal(raw)
    assert not report.ok
    assert any(defect["code"] == "persona_length_pair_invalid"
               for defect in report.defects)


def test_optional_length_policy_rejects_partial_multi_persona_pairing():
    raw = behavior_probe_goal().replace(
        b"personas: [p@v1]", b"personas: [p@v1, q@v1]"
    ).replace(
        b"predictions:\n",
        b"  - {id: persona-q, kind: persona, persona_ref: q@v1}\n"
        b"  - {id: length-p, kind: length, persona_ref: p@v1}\n"
        b"predictions:\n",
    )
    report = validate_goal(raw)
    assert not report.ok
    assert any(defect["code"] == "persona_length_pair_invalid"
               for defect in report.defects)


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
