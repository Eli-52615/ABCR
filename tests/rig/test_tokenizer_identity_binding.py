from __future__ import annotations

from types import SimpleNamespace

import pytest

from abcr.control import dispatch_supervisor
from abcr.control.contracts import ContractError
from abcr.rig import models, runner


class _Backend:
    def __init__(self, identity: str):
        self.identity = identity

    def to_str(self) -> str:
        # Both tokenizers below intentionally count every input identically.  Only
        # the serialized backend identity differs.
        return '{"model":{"type":"fixture","identity":"' + self.identity + '"}}'


class SameCountTokenizer:
    special_tokens_map = {"bos_token": "<s>", "eos_token": "</s>"}

    def __init__(self, identity: str):
        self.backend_tokenizer = _Backend(identity)

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        assert add_special_tokens is False
        return list(range(len(text)))

    def apply_chat_template(self, messages, tokenize=False,
                            add_generation_prompt=True):
        return "\n".join(message["content"] for message in messages)


def _binding(tokenizer: SameCountTokenizer) -> tuple[dict, SimpleNamespace]:
    digest = models.tokenizer_identity_sha256(tokenizer)
    assert digest is not None
    schema = models.TOKENIZER_FINGERPRINT_SCHEMA
    release = {"release_id": "REL-1", "release_tree_hash": "a" * 64,
               "release_lock_hash": "b" * 64}
    receipt = {"tokenizer_sha256": digest}
    cfg = {
        "condition": "length_instruct", "dev_bundle_ref": {"strict": True},
        "tokenizer_sha256": digest, "tokenizer_fingerprint_schema": schema,
        "length_control_receipt": receipt, "release_pin": release,
        "evidence_inputs": {
            "tokenizer_sha256": digest, "tokenizer_fingerprint_schema": schema,
            "model_id": "fixture/model", "model_revision": "rev",
            "chat_template_sha256": "c" * 64,
            "scorer_id": runner.scorer.SCORER_ID,
            "scorer_version": runner.scorer.SCORER_VERSION,
            **release,
        },
    }
    info = SimpleNamespace(
        model_id="fixture/model", revision="rev", chat_template_hash="c" * 64,
        tokenizer_sha256=digest, tokenizer_fingerprint_schema=schema,
    )
    return cfg, info


def test_fingerprint_distinguishes_same_count_tokenizers_and_opaque_is_unqualified():
    first = SameCountTokenizer("first")
    second = SameCountTokenizer("second")
    assert len(first.encode("碰巧等长")) == len(second.encode("碰巧等长"))
    assert models.tokenizer_identity_sha256(first) != models.tokenizer_identity_sha256(second)

    class OpaqueTokenizer:
        def encode(self, text, add_special_tokens=False):
            return list(range(len(text)))

    assert models.tokenizer_identity_sha256(OpaqueTokenizer()) is None


def test_runner_accepts_exact_actual_identity_and_rejects_same_count_substitution():
    approved = SameCountTokenizer("approved")
    cfg, info = _binding(approved)
    runner._verify_runtime_evidence_binding(cfg, approved, info)

    substituted = SameCountTokenizer("substituted")
    with pytest.raises(ContractError) as exc:
        runner._verify_runtime_evidence_binding(cfg, substituted, info)
    assert exc.value.code == "runtime_tokenizer_binding_mismatch"


def test_runner_rejects_forged_modelinfo_even_when_actual_and_profile_match():
    approved = SameCountTokenizer("approved")
    cfg, info = _binding(approved)
    info.tokenizer_sha256 = "f" * 64
    with pytest.raises(ContractError) as exc:
        runner._verify_runtime_evidence_binding(cfg, approved, info)
    assert exc.value.code == "runtime_tokenizer_binding_mismatch"
    assert "ModelInfo.tokenizer_sha256" in exc.value.details["mismatched_fields"]


def test_root_profile_rejects_config_tokenizer_drift_before_model_access():
    tokenizer = SameCountTokenizer("approved")
    cfg, _ = _binding(tokenizer)
    cfg.update({
        "model": {"engine": "transformers", "model_id": "/fixed/model",
                  "revision": "rev", "dtype": "bfloat16", "device": "cuda:0"},
        "benchmark": {"family": "ifeval_zh_v1"},
        "decoding": {"temperature": 0.0, "seeds": [7]},
    })
    profile = {
        "model": cfg["model"], "benchmark_family": "ifeval_zh_v1",
        "decoding": {"temperature": 0.0}, "release_pin": cfg["release_pin"],
        "tokenizer_sha256": cfg["tokenizer_sha256"],
        "tokenizer_fingerprint_schema": models.TOKENIZER_FINGERPRINT_SCHEMA,
    }
    dispatch_supervisor._validate_execution_profile_binding(cfg, profile)
    cfg["evidence_inputs"]["tokenizer_sha256"] = "0" * 64
    with pytest.raises(ContractError) as exc:
        dispatch_supervisor._validate_execution_profile_binding(cfg, profile)
    assert exc.value.code == "dispatch_execution_profile_drift"
