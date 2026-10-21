from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from abcr.control.contracts import ContractError, sha256
from abcr.explore.compiler import build_run_configs
from abcr.explore.goal import Goal, Prediction
from abcr.explore.item_pool import DevBundleRef
from abcr.explore.length_control import (generate_task_expansion_control,
                                         generate_paired_prompt_plans,
                                         load_task_expansion_library,
                                         validate_task_expansion_plan_receipt,
                                         verify_task_expansion_control)
from abcr.explore.personas import PersonaRegistry
from abcr.rig import runner
from abcr.rig.models import TOKENIZER_FINGERPRINT_SCHEMA


ROOT = Path(__file__).resolve().parents[2]
LIBRARY_PATH = (ROOT / "configs" / "research" / "length-control" /
                "task_expansion_zh_v1.json")
TOKENIZER_HASH = sha256(b"fixture-tokenizer")
TEMPLATE_HASH = sha256(b"fixture-template")


def _encode(text: str) -> list[int]:
    return [ord(char) for char in text]


def _render(system: str, item: str) -> str:
    return f"{system}\n\n任务：\n{item}"


def _pair():
    library = load_task_expansion_library(LIBRARY_PATH)
    base = library.fragments[0]["text"]
    persona = "甲" * len(base)
    items = {"d1": "第一题", "d2": "第二题更长"}
    plan = generate_task_expansion_control(
        persona, items, encode=_encode, render_chat=_render,
        tokenizer_sha256=TOKENIZER_HASH, chat_template_sha256=TEMPLATE_HASH,
        library=library)
    return library, persona, items, plan


def test_frozen_library_generates_and_reverifies_exact_final_chat_per_item():
    packaged = (ROOT / "src" / "abcr" / "explore" / "resources" /
                "task_expansion_zh_v1.json")
    assert packaged.read_bytes() == LIBRARY_PATH.read_bytes()
    library, persona, items, plan = _pair()
    verified = verify_task_expansion_control(
        plan, persona, items, encode=_encode, render_chat=_render,
        tokenizer_sha256=TOKENIZER_HASH, chat_template_sha256=TEMPLATE_HASH,
        library=library)
    assert verified == plan
    assert plan["rendered_prompt_token_counts"] == \
        plan["target_rendered_prompt_token_counts"]
    assert plan["manipulation_checks"]["forbidden_hits"] == []
    assert plan["manipulation_checks"]["required_slots_observed"] >= ["task_expansion"]

    long_persona = "甲" * 80
    long_plan = generate_task_expansion_control(
        long_persona, items, encode=_encode, render_chat=_render,
        tokenizer_sha256=TOKENIZER_HASH, chat_template_sha256=TEMPLATE_HASH,
        library=library)
    assert long_plan["prompt_token_count"] == 80
    assert long_plan["search"]["states_examined"] < \
        long_plan["search"]["max_states"]
    paired = generate_paired_prompt_plans(
        "persona-p", "length-p", persona, items, encode=_encode,
        render_chat=_render, tokenizer_sha256=TOKENIZER_HASH,
        chat_template_sha256=TEMPLATE_HASH, library=library)
    assert set(paired) == {"persona-p", "length-p"}
    assert (paired["persona-p"]["rendered_prompt_token_counts"]
            == paired["length-p"]["target_rendered_prompt_token_counts"])


@pytest.mark.parametrize("attack,code", [
    ("tokenizer_drift", "length_plan_binding_mismatch"),
    ("outside_bytes", "length_bytes_outside_library"),
    ("outside_source", "length_source_outside_library"),
    ("final_count", "length_exact_match_failed"),
])
def test_plan_rejects_drift_library_escape_and_false_exact_claim(attack, code):
    library, persona, items, plan = _pair()
    attacked = copy.deepcopy(plan)
    tokenizer_hash = TOKENIZER_HASH
    if attack == "tokenizer_drift":
        tokenizer_hash = "f" * 64
    elif attack == "outside_bytes":
        attacked["prompt_text"] += "库外"
        attacked["prompt_sha256"] = sha256(attacked["prompt_text"].encode())
    elif attack == "outside_source":
        attacked["source_ids"].append("attacker")
    else:
        attacked["rendered_prompt_token_counts"]["d1"] += 1
    with pytest.raises(ContractError) as exc:
        validate_task_expansion_plan_receipt(
            attacked, persona, tuple(items), tokenizer_sha256=tokenizer_hash,
            chat_template_sha256=TEMPLATE_HASH, library=library)
    assert exc.value.code == code


def test_polluted_frozen_library_and_unreachable_pair_fail_closed(tmp_path):
    raw = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    raw["fragments"][0]["text"] += "人格"
    polluted = tmp_path / "polluted.json"
    polluted.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError) as exc:
        load_task_expansion_library(polluted)
    assert exc.value.code == "length_library_polluted"

    library = load_task_expansion_library(LIBRARY_PATH)
    with pytest.raises(ContractError) as exc:
        generate_task_expansion_control(
            "短", {"d1": "题"}, encode=_encode, render_chat=_render,
            tokenizer_sha256=TOKENIZER_HASH, chat_template_sha256=TEMPLATE_HASH,
            library=library)
    assert exc.value.code == "exact_token_unreachable"


def _compiler_inputs():
    library, persona, items, plan = _pair()
    registry = PersonaRegistry()
    registry.add({"persona_id": "p", "version": 1, "parent_ref": None,
                  "components": {"rule": persona}, "changed_component": None,
                  "manipulation_checks": ["甲"]})
    goal = Goal(
        goal_id="G-3L", title="exact", design_origin="human_claude_manual",
        hypothesis="length bracket", template_id="persona_control", split="dev",
        personas=("p@v1",), arms=(
            {"id": "vanilla", "kind": "vanilla"},
            {"id": "persona-p", "kind": "persona", "persona_ref": "p@v1"},
            {"id": "length-p", "kind": "length", "persona_ref": "p@v1"},
        ), predictions=(Prediction("ifeval_zh_v1", "increase", "test"),),
        falsifier="none", metrics=("is_correct",), item_count=2, seeds=(7,),
        max_cost_usd=0.0)
    persona_rendered = {item_id: _render(persona, prompt)
                        for item_id, prompt in items.items()}
    persona_plan = {
        "prompt_text": persona, "prompt_sha256": sha256(persona.encode()),
        "prompt_token_count": len(_encode(persona)),
        "rendered_prompt_token_counts": {
            item_id: len(_encode(text)) for item_id, text in persona_rendered.items()},
        "rendered_prompt_sha256s": {
            item_id: sha256(text.encode()) for item_id, text in persona_rendered.items()},
    }
    profile = {
        "benchmark_family": "ifeval_zh_v1",
        "model": {"engine": "fixture", "model_id": "m", "revision": "r",
                  "dtype": "none", "device": "cpu"},
        "decoding": {"temperature": 0.0},
        "tokenizer_sha256": TOKENIZER_HASH,
        "tokenizer_fingerprint_schema": TOKENIZER_FINGERPRINT_SCHEMA,
        "chat_template_sha256": TEMPLATE_HASH,
        "scorer": {"id": "s", "version": "1"},
        "release_pin": {"release_id": "r", "release_tree_hash": "a" * 64,
                        "release_lock_hash": "b" * 64},
        "prompt_plans": {"persona-p": persona_plan, "length-p": plan},
    }
    bundle = DevBundleRef("c" * 64, ROOT, "d" * 64, tuple(items), "e" * 64)
    receipt = {"selected_bytes_hash": "f" * 64}
    evidence = {"goal_hash": goal.goal_hash, "goal_receipt_id": "receipt",
                "research_commit": "1" * 40, "deployment_id": "prod",
                "protocol_ref": "test"}
    return goal, registry, bundle, receipt, profile, evidence


def test_compiler_emits_exactly_one_owned_3l_and_preserves_full_receipt():
    goal, registry, bundle, receipt, profile, evidence = _compiler_inputs()
    configs = build_run_configs(
        goal=goal, bundle=bundle, personas=registry, selection_receipt=receipt,
        execution_profile=profile, evidence_base=evidence,
        length_library_path=LIBRARY_PATH)
    assert [cfg["condition"] for cfg in configs] == [
        "vanilla", "persona_text", "length_instruct"]
    length = configs[-1]
    assert length["control_role"] == "task_expansion_bracket"
    assert length["length_control_receipt"] == profile["prompt_plans"]["length-p"]

    class FrozenTokenizer:
        def encode(self, text, add_special_tokens=False):
            return _encode(text)

        def apply_chat_template(self, messages, tokenize=False,
                                add_generation_prompt=True):
            assert [message["role"] for message in messages] == ["system", "user"]
            return _render(messages[0]["content"], messages[1]["content"])

    tokenizer = FrozenTokenizer()
    persona_cfg, length_cfg = configs[1], configs[2]
    for item_id, item_prompt in {"d1": "第一题", "d2": "第二题更长"}.items():
        counts = []
        for cfg in (persona_cfg, length_cfg):
            system = runner.build_system_prompt(cfg, None)
            runner._verify_inline_prompt(cfg, tokenizer, system)
            rendered = runner.render_prompt(tokenizer, item_prompt, system)
            counts.append(runner._verify_final_rendered_prompt(
                cfg, tokenizer, item_id, rendered))
        assert counts[0] == counts[1]


def test_behavior_probe_may_omit_3l_but_requested_3l_must_be_complete():
    goal, registry, bundle, receipt, profile, evidence = _compiler_inputs()
    optional_with = Goal(**{**goal.__dict__, "template_id": "behavior_probe"})
    with_configs = build_run_configs(
        goal=optional_with, bundle=bundle, personas=registry,
        selection_receipt=receipt, execution_profile=profile,
        evidence_base=evidence, length_library_path=LIBRARY_PATH)
    assert [cfg["condition"] for cfg in with_configs] == [
        "vanilla", "persona_text", "length_instruct"]

    optional_without = Goal(**{**optional_with.__dict__, "arms": optional_with.arms[:-1]})
    no_length_profile = copy.deepcopy(profile)
    no_length_profile["prompt_plans"].pop("length-p")
    without_configs = build_run_configs(
        goal=optional_without, bundle=bundle, personas=registry,
        selection_receipt=receipt, execution_profile=no_length_profile,
        evidence_base=evidence, length_library_path=LIBRARY_PATH)
    assert [cfg["condition"] for cfg in without_configs] == [
        "vanilla", "persona_text"]


@pytest.mark.parametrize("attack", ["missing_pair", "duplicate_pair", "final_mismatch"])
def test_compiler_rejects_missing_duplicate_or_wrongly_paired_3l(attack):
    goal, registry, bundle, receipt, profile, evidence = _compiler_inputs()
    if attack == "missing_pair":
        goal = Goal(**{**goal.__dict__, "arms": goal.arms[:-1]})
    elif attack == "duplicate_pair":
        goal = Goal(**{**goal.__dict__, "arms": (*goal.arms,
                    {"id": "length-p-2", "kind": "length", "persona_ref": "p@v1"})})
        profile["prompt_plans"]["length-p-2"] = copy.deepcopy(
            profile["prompt_plans"]["length-p"])
    else:
        profile["prompt_plans"]["persona-p"]["rendered_prompt_token_counts"]["d1"] += 1
    with pytest.raises(ContractError):
        build_run_configs(
            goal=goal, bundle=bundle, personas=registry, selection_receipt=receipt,
            execution_profile=profile, evidence_base=evidence,
            length_library_path=LIBRARY_PATH)


def _attack_generator_grammar(plan, library, attack):
    attacked = copy.deepcopy(plan)
    if attack == "over_sequence_limit":
        repeatable = next(fragment for fragment in library.fragments
                          if fragment["repeatable"])
        attacked["source_ids"] = [repeatable["source_id"]] * (
            library.value["max_sequence_units"] + 1)
    elif attack == "reuse_nonrepeatable":
        nonrepeatable = next(fragment for fragment in library.fragments
                             if not fragment["repeatable"])
        attacked["source_ids"] = [nonrepeatable["source_id"]] * 2
    else:
        self_check = next(
            fragment for fragment in library.fragments
            if fragment["kind"] == "self_check"
            and fragment["slot"] in library.value["required_slots"]
        )
        attacked["source_ids"] = [self_check["source_id"]]
        attacked["prompt_text"] = self_check["text"]
        attacked["prompt_sha256"] = sha256(self_check["text"].encode("utf-8"))
    return attacked


@pytest.mark.parametrize("attack,code", [
    ("over_sequence_limit", "length_sequence_limit"),
    ("reuse_nonrepeatable", "length_nonrepeatable_reused"),
    ("self_check_claims_required_slot", "length_required_slot_missing"),
])
def test_receipt_full_verifier_and_compiler_share_generator_grammar(attack, code):
    library, persona, items, plan = _pair()
    attacked = _attack_generator_grammar(plan, library, attack)

    with pytest.raises(ContractError) as receipt_error:
        validate_task_expansion_plan_receipt(
            attacked, persona, tuple(items), tokenizer_sha256=TOKENIZER_HASH,
            chat_template_sha256=TEMPLATE_HASH, library=library)
    assert receipt_error.value.code == code

    with pytest.raises(ContractError) as full_error:
        verify_task_expansion_control(
            attacked, persona, items, encode=_encode, render_chat=_render,
            tokenizer_sha256=TOKENIZER_HASH, chat_template_sha256=TEMPLATE_HASH,
            library=library)
    assert full_error.value.code == code

    goal, registry, bundle, receipt, profile, evidence = _compiler_inputs()
    profile["prompt_plans"]["length-p"] = _attack_generator_grammar(
        profile["prompt_plans"]["length-p"], library, attack)
    with pytest.raises(ContractError) as compiler_error:
        build_run_configs(
            goal=goal, bundle=bundle, personas=registry,
            selection_receipt=receipt, execution_profile=profile,
            evidence_base=evidence, length_library_path=LIBRARY_PATH)
    assert compiler_error.value.code == code
