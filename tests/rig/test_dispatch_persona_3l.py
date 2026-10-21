from __future__ import annotations

import hashlib
import json

import pytest

from abcr.control.contracts import ContractError
from abcr.ops import dispatch
from abcr.rig import runner


class WordTokenizer:
    chat_template_hash = "a" * 64

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        return " <turn> ".join(message["content"] for message in messages) + " <assistant>"

    def encode(self, text, add_special_tokens=False):
        return list(range(len(text.split())))


def _prompt_cfg(condition: str, system: str, item_ids=("d1",)) -> dict:
    tok = WordTokenizer()
    rendered = tok.apply_chat_template([
        {"role": "system", "content": system}, {"role": "user", "content": "question"}],
        tokenize=False, add_generation_prompt=True)
    return {
        "condition": condition, "item_ids": list(item_ids),
        "dev_bundle_ref": {"strict": True}, "prompt_text": system,
        "prompt_sha256": hashlib.sha256(system.encode()).hexdigest(),
        "prompt_token_count": len(tok.encode(system)),
        "rendered_prompt_token_counts": {"d1": len(tok.encode(rendered))},
    }


def test_persona_and_3l_use_approved_inline_prompt():
    tok = WordTokenizer()
    for condition in ("persona_text", "length_instruct"):
        cfg = _prompt_cfg(condition, "careful concise persona")
        system = runner.build_system_prompt(cfg, None)
        runner._verify_inline_prompt(cfg, tok, system)
        rendered = runner.render_prompt(tok, "question", system)
        assert runner._verify_final_rendered_prompt(cfg, tok, "d1", rendered) == len(tok.encode(rendered))
    assert runner.build_system_prompt({"condition": "vanilla"}, None) is None


def test_3l_rechecks_tokens_after_final_chat_serialization():
    tok = WordTokenizer()
    cfg = _prompt_cfg("length_instruct", "one two three")
    cfg["rendered_prompt_token_counts"]["d1"] += 1
    rendered = runner.render_prompt(tok, "question", cfg["prompt_text"])
    with pytest.raises(ContractError, match="最终序列化"):
        runner._verify_final_rendered_prompt(cfg, tok, "d1", rendered)


def test_fake_dispatch_arms_share_item_prompt_and_persona_is_explicit():
    item_prompts = {"d1": "question"}
    vanilla = {"condition": "vanilla", "dev_bundle_ref": {"strict": True}}
    persona = _prompt_cfg("persona_text", "careful concise persona")
    length = _prompt_cfg("length_instruct", "length matched instruction")
    assert dispatch._fake_render_prompts(vanilla, item_prompts) == item_prompts
    assert dispatch._fake_render_prompts(persona, item_prompts)["d1"].endswith("question")
    assert dispatch._fake_render_prompts(length, item_prompts)["d1"].endswith("question")
    bad = dict(persona, prompt_sha256="0" * 64)
    with pytest.raises(ContractError, match="prompt_sha256"):
        dispatch._fake_render_prompts(bad, item_prompts)


def test_rendered_prompt_sidecar_is_idempotent_and_conflict_fails(tmp_path):
    row = {"run_id": "r1", "item_id": "d1", "random_seed": 7,
           "condition": "persona_text", "prompt_text": "raw", "prompt_hash": "h",
           "system_prompt_hash": "s", "template_hash": "t"}
    dispatch._append_prompt_sidecar_once(tmp_path, row)
    dispatch._append_prompt_sidecar_once(tmp_path, row)
    path = tmp_path / "logs" / "rendered_prompts.jsonl"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    changed = dict(row, prompt_text="mutated")
    with pytest.raises(ContractError, match="内容冲突"):
        dispatch._append_prompt_sidecar_once(tmp_path, changed)
