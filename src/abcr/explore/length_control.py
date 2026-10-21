"""Deterministic exact-token ③L task-expansion controls.

The scientific contract is deliberately narrower than "make some text about the
same length".  A control is assembled only from a reviewed finite library, and it
must match its paired persona after the frozen chat template has serialized every
selected item.  The tokenizer and renderer are runtime objects supplied by the
already-frozen execution-profile generation step; this module never guesses either.
"""
from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from heapq import heappop, heappush
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from abcr.control.contracts import ContractError, canonical_json, require_sha, sha256


Encode = Callable[[str], Sequence[int]]
ChatRenderer = Callable[[str, str], str]


@dataclass(frozen=True)
class TaskExpansionLibrary:
    value: dict[str, Any]
    digest: str

    @property
    def fragments(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.value["fragments"])


@dataclass(frozen=True)
class LengthVariant:
    label: str
    text: str
    token_count: int
    text_hash: str
    checks: tuple[str, ...]


def load_task_expansion_library(path: Path) -> TaskExpansionLibrary:
    """Load an exact-shape, finite, regular-file task-expansion library."""
    path = Path(path)
    try:
        info = path.lstat()
    except OSError as exc:
        raise ContractError("length_library_unavailable", "③L 冻结短句库不可达") from exc
    if (path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_size > 256 * 1024):
        raise ContractError("length_library_unsafe", "③L 短句库必须是有限普通文件")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("length_library_invalid", "③L 短句库不是合法 UTF-8 JSON") from exc
    required = {
        "schema_version", "template_id", "template_version", "control_role",
        "manipulation_profile_id", "required_slots", "max_sequence_units",
        "max_search_states", "max_hedging_hits", "max_self_check_hits",
        "forbidden_terms", "fragments",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ContractError("length_library_invalid", "③L 短句库字段不匹配")
    if (value["schema_version"] != 1
            or value["template_id"] != "task_expansion_zh_v1"
            or value["control_role"] != "task_expansion_bracket"
            or value["manipulation_profile_id"] != "manipulation-check-3l-v1"):
        raise ContractError("length_library_invalid", "③L 短句库身份不匹配")
    if (type(value["max_sequence_units"]) is not int
            or not 1 <= value["max_sequence_units"] <= 256
            or type(value["max_search_states"]) is not int
            or not 1 <= value["max_search_states"] <= 1_000_000
            or type(value["max_hedging_hits"]) is not int
            or value["max_hedging_hits"] < 0
            or type(value["max_self_check_hits"]) is not int
            or value["max_self_check_hits"] < 0):
        raise ContractError("length_library_invalid", "③L 短句库搜索/行为上限不合法")
    required_slots = value["required_slots"]
    forbidden = value["forbidden_terms"]
    fragments = value["fragments"]
    if (not isinstance(required_slots, list) or not required_slots
            or len(required_slots) != len(set(required_slots))
            or any(not isinstance(slot, str) or not slot for slot in required_slots)
            or not isinstance(forbidden, list)
            or len(forbidden) != len(set(forbidden))
            or any(not isinstance(term, str) or not term for term in forbidden)
            or not isinstance(fragments, list) or not fragments
            or len(fragments) > 256):
        raise ContractError("length_library_invalid", "③L 短句库列表不合法")
    ids: set[str] = set()
    covered_slots: set[str] = set()
    for fragment in fragments:
        if (not isinstance(fragment, dict)
                or set(fragment) != {"source_id", "slot", "kind", "text", "repeatable"}):
            raise ContractError("length_library_invalid", "③L 片段字段不匹配")
        source_id, slot, kind, text, repeatable = (
            fragment["source_id"], fragment["slot"], fragment["kind"],
            fragment["text"], fragment["repeatable"])
        if (not isinstance(source_id, str) or not source_id or source_id in ids
                or not isinstance(slot, str) or not slot
                or kind not in {"task_expansion", "filler", "hedging", "self_check"}
                or not isinstance(text, str) or not text
                or type(repeatable) is not bool):
            raise ContractError("length_library_invalid", "③L 片段内容不合法")
        ids.add(source_id)
        covered_slots.add(slot)
        folded = text.casefold()
        if any(term.casefold() in folded for term in forbidden):
            raise ContractError("length_library_polluted", "③L 冻结片段命中禁词")
    if not set(required_slots).issubset(covered_slots):
        raise ContractError("length_library_invalid", "③L 库没有覆盖必需 task-expansion slot")
    return TaskExpansionLibrary(value=value, digest=sha256(canonical_json(value)))


def _ids(encode: Encode, text: str) -> tuple[int, ...]:
    try:
        first = encode(text)
        second = encode(text)
    except Exception as exc:
        raise ContractError("tokenizer_encode_failed", "冻结 tokenizer 无法编码 ③L 文本") from exc
    if (not isinstance(first, Sequence) or isinstance(first, (str, bytes))
            or not isinstance(second, Sequence) or isinstance(second, (str, bytes))):
        raise ContractError("tokenizer_encode_invalid", "冻结 tokenizer encode 返回类型不合法")
    a, b = tuple(first), tuple(second)
    if a != b or any(type(token) is not int or token < 0 for token in a):
        raise ContractError("tokenizer_encode_drift", "冻结 tokenizer 编码不确定或含非法 token")
    return a


def _render(renderer: ChatRenderer, system_prompt: str, item_prompt: str) -> str:
    try:
        first = renderer(system_prompt, item_prompt)
        second = renderer(system_prompt, item_prompt)
    except Exception as exc:
        raise ContractError("chat_renderer_failed", "冻结 chat renderer 无法序列化 ③L") from exc
    if not isinstance(first, str) or not first or first != second:
        raise ContractError("chat_renderer_drift", "冻结 chat renderer 输出不确定或为空")
    return first


def _behavior_checks(text: str, source_ids: tuple[str, ...], *,
                     library: TaskExpansionLibrary) -> dict[str, Any]:
    by_id = {item["source_id"]: item for item in library.fragments}
    if any(source_id not in by_id for source_id in source_ids):
        raise ContractError("length_source_outside_library", "③L 引用了库外 source id")
    if len(source_ids) > library.value["max_sequence_units"]:
        raise ContractError(
            "length_sequence_limit",
            "③L source sequence 超过冻结生成器的单位上限",
            {"observed": len(source_ids),
             "maximum": library.value["max_sequence_units"]},
        )
    source_counts = {source_id: source_ids.count(source_id)
                     for source_id in set(source_ids)}
    reused = sorted(source_id for source_id, count in source_counts.items()
                    if count > 1 and not by_id[source_id]["repeatable"])
    if reused:
        raise ContractError(
            "length_nonrepeatable_reused",
            "③L 重复使用了冻结生成器标记为 non-repeatable 的片段",
            {"source_ids": reused},
        )
    reconstructed = "".join(by_id[source_id]["text"] for source_id in source_ids)
    if reconstructed != text:
        raise ContractError("length_bytes_outside_library", "③L 含有冻结片段库外字节")
    slots = sorted({by_id[source_id]["slot"] for source_id in source_ids})
    task_expansion_slots = {
        by_id[source_id]["slot"] for source_id in source_ids
        if by_id[source_id]["kind"] == "task_expansion"
    }
    if not set(library.value["required_slots"]).issubset(task_expansion_slots):
        raise ContractError("length_required_slot_missing", "③L 未覆盖必需 task-expansion slot")
    folded = text.casefold()
    forbidden_hits = sorted(term for term in library.value["forbidden_terms"]
                            if term.casefold() in folded)
    hedging_hits = sum(by_id[source_id]["kind"] == "hedging" for source_id in source_ids)
    self_check_hits = sum(by_id[source_id]["kind"] == "self_check" for source_id in source_ids)
    if forbidden_hits:
        raise ContractError("length_forbidden_term", "③L 命中 persona/theory/affect 禁词",
                            {"hits": forbidden_hits})
    if hedging_hits > library.value["max_hedging_hits"]:
        raise ContractError("length_hedging_limit", "③L hedging 超过冻结上限")
    if self_check_hits > library.value["max_self_check_hits"]:
        raise ContractError("length_self_check_limit", "③L self-check 超过冻结上限")
    return {
        "profile_id": library.value["manipulation_profile_id"],
        "allowed_sources_only": True,
        "exact_library_reconstruction": True,
        "required_slots_observed": slots,
        "forbidden_hits": forbidden_hits,
        "hedging_hits": hedging_hits,
        "self_check_hits": self_check_hits,
        "status": "PASS",
    }


def generate_task_expansion_control(
    persona_text: str,
    item_prompts: Mapping[str, str],
    *,
    encode: Encode,
    render_chat: ChatRenderer,
    tokenizer_sha256: str,
    chat_template_sha256: str,
    library: TaskExpansionLibrary,
) -> dict[str, Any]:
    """Generate one finite-library control exactly matching a persona on all items.

    Search is deterministic and bounded by the reviewed library.  If no candidate
    reaches the full vector of target counts, the *whole persona/control pair* is
    rejected; there is no approximate fallback.
    """
    require_sha(tokenizer_sha256, "tokenizer_sha256")
    require_sha(chat_template_sha256, "chat_template_sha256")
    if not isinstance(persona_text, str) or not persona_text:
        raise ContractError("persona_prompt_invalid", "③L 配对人格文本为空")
    if (not isinstance(item_prompts, Mapping) or not item_prompts
            or any(not isinstance(item_id, str) or not item_id
                   or not isinstance(prompt, str) or not prompt
                   for item_id, prompt in item_prompts.items())):
        raise ContractError("length_items_invalid", "③L 必须绑定有限非空 item prompt")
    ordered_items = tuple(sorted(item_prompts.items()))
    target_prompt_count = len(_ids(encode, persona_text))
    target_rendered = {
        item_id: len(_ids(encode, _render(render_chat, persona_text, item_prompt)))
        for item_id, item_prompt in ordered_items
    }
    target_rendered_hashes = {
        item_id: sha256(_render(render_chat, persona_text, item_prompt).encode("utf-8"))
        for item_id, item_prompt in ordered_items
    }
    fragments = library.fragments
    required_indices = tuple(
        index for index, fragment in enumerate(fragments)
        if fragment["slot"] in set(library.value["required_slots"])
        and fragment["kind"] == "task_expansion"
    )
    if not required_indices:
        raise ContractError("length_library_invalid", "③L 库无必需任务展开起始片段")
    queue: list[tuple[int, int, tuple[str, ...], tuple[int, ...], str,
                      int, dict[str, str], dict[str, int]]] = []

    def enqueue(sequence: tuple[int, ...]) -> None:
        source_ids = tuple(fragments[index]["source_id"] for index in sequence)
        text = "".join(fragments[index]["text"] for index in sequence)
        prompt_count = len(_ids(encode, text))
        rendered_texts = {
            item_id: _render(render_chat, text, item_prompt)
            for item_id, item_prompt in ordered_items
        }
        rendered_counts = {
            item_id: len(_ids(encode, rendered_texts[item_id]))
            for item_id, _ in ordered_items
        }
        # Best-first distance is only scheduling, never acceptance.  It avoids a
        # breadth-first combinatorial wall for realistic long personas while the
        # exact equality below remains the sole success criterion.
        distance = abs(target_prompt_count - prompt_count) + sum(
            abs(target_rendered[item_id] - rendered_counts[item_id])
            for item_id, _ in ordered_items)
        heappush(queue, (distance, len(sequence), source_ids, sequence, text,
                         prompt_count, rendered_texts, rendered_counts))

    for index in required_indices:
        enqueue((index,))
    seen_text: set[str] = set()
    searched = 0
    max_units = library.value["max_sequence_units"]
    max_states = library.value["max_search_states"]
    while queue and searched < max_states:
        (_distance, _length, source_ids, sequence, text, prompt_count,
         rendered_texts, rendered_counts) = heappop(queue)
        if text in seen_text:
            continue
        seen_text.add(text)
        searched += 1
        if prompt_count == target_prompt_count and rendered_counts == target_rendered:
            checks = _behavior_checks(text, source_ids, library=library)
            return {
                "schema_version": 1,
                "plan_type": "length_control_3l",
                "template_id": library.value["template_id"],
                "template_version": library.value["template_version"],
                "template_sha256": library.digest,
                "control_role": library.value["control_role"],
                "prompt_text": text,
                "prompt_sha256": sha256(text.encode("utf-8")),
                "prompt_token_count": prompt_count,
                "source_ids": list(source_ids),
                "tokenizer_sha256": tokenizer_sha256,
                "chat_template_sha256": chat_template_sha256,
                "paired_persona_sha256": sha256(persona_text.encode("utf-8")),
                "target_prompt_token_count": target_prompt_count,
                "rendered_prompt_token_counts": rendered_counts,
                "target_rendered_prompt_token_counts": target_rendered,
                "rendered_prompt_sha256s": {
                    item_id: sha256(rendered_texts[item_id].encode("utf-8"))
                    for item_id, _ in ordered_items
                },
                "target_rendered_prompt_sha256s": target_rendered_hashes,
                "manipulation_checks": checks,
                "search": {"states_examined": searched, "max_states": max_states,
                           "max_sequence_units": max_units},
            }
        if len(sequence) >= max_units:
            continue
        # Exact-token counts for ordinary tokenizers are monotone enough to prune
        # obviously oversized states.  The final equality is still checked without
        # approximation, and an unusual tokenizer simply gets a closed rejection.
        if (prompt_count > target_prompt_count
                or any(rendered_counts[item_id] > target_rendered[item_id]
                       for item_id, _ in ordered_items)):
            continue
        used = set(sequence)
        for index, fragment in enumerate(fragments):
            if fragment["repeatable"] or index not in used:
                enqueue((*sequence, index))
    raise ContractError(
        "exact_token_unreachable",
        "冻结 task_expansion_zh_v1 无法对所有 item 达到 persona 的最终 chat token 数；整对拒绝",
        {"states_examined": searched, "max_states": max_states},
    )


def generate_paired_prompt_plans(
    persona_arm_id: str,
    length_arm_id: str,
    persona_text: str,
    item_prompts: Mapping[str, str],
    *,
    encode: Encode,
    render_chat: ChatRenderer,
    tokenizer_sha256: str,
    chat_template_sha256: str,
    library: TaskExpansionLibrary,
) -> dict[str, dict[str, Any]]:
    """Generate both execution-profile plans from the same frozen callbacks."""
    if (not isinstance(persona_arm_id, str) or not persona_arm_id
            or not isinstance(length_arm_id, str) or not length_arm_id
            or persona_arm_id == length_arm_id):
        raise ContractError("length_arm_ids_invalid", "persona/③L arm id 必须非空且不同")
    control = generate_task_expansion_control(
        persona_text, item_prompts, encode=encode, render_chat=render_chat,
        tokenizer_sha256=tokenizer_sha256,
        chat_template_sha256=chat_template_sha256, library=library)
    rendered = {
        item_id: _render(render_chat, persona_text, item_prompt)
        for item_id, item_prompt in sorted(item_prompts.items())
    }
    persona = {
        "prompt_text": persona_text,
        "prompt_sha256": sha256(persona_text.encode("utf-8")),
        "prompt_token_count": len(_ids(encode, persona_text)),
        "rendered_prompt_token_counts": {
            item_id: len(_ids(encode, text)) for item_id, text in rendered.items()},
        "rendered_prompt_sha256s": {
            item_id: sha256(text.encode("utf-8")) for item_id, text in rendered.items()},
    }
    # A final full verifier here catches callback drift between the control search
    # and persona-plan materialization before either plan can enter a root profile.
    verify_task_expansion_control(
        control, persona_text, item_prompts, encode=encode, render_chat=render_chat,
        tokenizer_sha256=tokenizer_sha256,
        chat_template_sha256=chat_template_sha256, library=library)
    return {persona_arm_id: persona, length_arm_id: control}


def verify_task_expansion_control(
    plan: Mapping[str, Any],
    persona_text: str,
    item_prompts: Mapping[str, str],
    *,
    encode: Encode,
    render_chat: ChatRenderer,
    tokenizer_sha256: str,
    chat_template_sha256: str,
    library: TaskExpansionLibrary,
) -> dict[str, Any]:
    """Recompute every byte/hash/token/behavior claim in a precompiled ③L plan."""
    if not isinstance(plan, Mapping):
        raise ContractError("length_plan_invalid", "③L 计划必须是对象")
    required = {
        "schema_version", "plan_type", "template_id", "template_version",
        "template_sha256", "control_role", "prompt_text", "prompt_sha256",
        "prompt_token_count", "source_ids", "tokenizer_sha256",
        "chat_template_sha256", "paired_persona_sha256",
        "target_prompt_token_count", "rendered_prompt_token_counts",
        "target_rendered_prompt_token_counts", "rendered_prompt_sha256s",
        "target_rendered_prompt_sha256s", "manipulation_checks", "search",
    }
    if set(plan) != required:
        raise ContractError("length_plan_invalid", "③L 计划字段不匹配")
    if (plan["schema_version"] != 1 or plan["plan_type"] != "length_control_3l"
            or plan["template_id"] != library.value["template_id"]
            or plan["template_version"] != library.value["template_version"]
            or plan["template_sha256"] != library.digest
            or plan["control_role"] != "task_expansion_bracket"
            or plan["tokenizer_sha256"] != tokenizer_sha256
            or plan["chat_template_sha256"] != chat_template_sha256
            or plan["paired_persona_sha256"] != sha256(persona_text.encode("utf-8"))):
        raise ContractError("length_plan_binding_mismatch", "③L 计划与冻结配对/profile 不一致")
    text = plan["prompt_text"]
    source_ids = plan["source_ids"]
    if (not isinstance(text, str) or not text
            or plan["prompt_sha256"] != sha256(text.encode("utf-8"))
            or not isinstance(source_ids, list)
            or any(not isinstance(source_id, str) for source_id in source_ids)):
        raise ContractError("length_plan_invalid", "③L prompt/source/hash 不合法")
    checks = _behavior_checks(text, tuple(source_ids), library=library)
    if plan["manipulation_checks"] != checks:
        raise ContractError("length_checks_drift", "③L manipulation-check 回执漂移")
    ordered_items = tuple(sorted(item_prompts.items()))
    expected_keys = {item_id for item_id, _ in ordered_items}
    persona_prompt_count = len(_ids(encode, persona_text))
    actual_prompt_count = len(_ids(encode, text))
    target_rendered: dict[str, int] = {}
    target_hashes: dict[str, str] = {}
    actual_rendered: dict[str, int] = {}
    actual_hashes: dict[str, str] = {}
    for item_id, item_prompt in ordered_items:
        persona_rendered = _render(render_chat, persona_text, item_prompt)
        control_rendered = _render(render_chat, text, item_prompt)
        target_rendered[item_id] = len(_ids(encode, persona_rendered))
        actual_rendered[item_id] = len(_ids(encode, control_rendered))
        target_hashes[item_id] = sha256(persona_rendered.encode("utf-8"))
        actual_hashes[item_id] = sha256(control_rendered.encode("utf-8"))
    maps = (plan["rendered_prompt_token_counts"],
            plan["target_rendered_prompt_token_counts"],
            plan["rendered_prompt_sha256s"], plan["target_rendered_prompt_sha256s"])
    if any(not isinstance(value, Mapping) or set(value) != expected_keys for value in maps):
        raise ContractError("length_plan_items_mismatch", "③L 计划未精确覆盖 item 集")
    if (plan["prompt_token_count"] != actual_prompt_count
            or plan["target_prompt_token_count"] != persona_prompt_count
            or actual_prompt_count != persona_prompt_count
            or dict(plan["rendered_prompt_token_counts"]) != actual_rendered
            or dict(plan["target_rendered_prompt_token_counts"]) != target_rendered
            or dict(plan["rendered_prompt_sha256s"]) != actual_hashes
            or dict(plan["target_rendered_prompt_sha256s"]) != target_hashes
            or actual_rendered != target_rendered):
        raise ContractError("length_exact_match_failed", "persona/③L 最终 chat 序列化未逐 item 精确等长")
    return dict(plan)


def validate_task_expansion_plan_receipt(
    plan: Mapping[str, Any],
    persona_text: str,
    item_ids: Sequence[str],
    *,
    tokenizer_sha256: str,
    chat_template_sha256: str,
    library: TaskExpansionLibrary,
) -> dict[str, Any]:
    """Compiler-side validation of a frozen generation receipt.

    The generation stage has the actual tokenizer/renderer and can call
    :func:`verify_task_expansion_control`.  The compiler intentionally receives no
    mutable model object.  It nevertheless rechecks the finite-library bytes, all
    bindings and hashes, full item coverage, and the claimed target/actual equality;
    the runner repeats the observable token count after real chat serialization.
    """
    if not isinstance(plan, Mapping):
        raise ContractError("length_plan_invalid", "③L 计划必须是对象")
    required = {
        "schema_version", "plan_type", "template_id", "template_version",
        "template_sha256", "control_role", "prompt_text", "prompt_sha256",
        "prompt_token_count", "source_ids", "tokenizer_sha256",
        "chat_template_sha256", "paired_persona_sha256",
        "target_prompt_token_count", "rendered_prompt_token_counts",
        "target_rendered_prompt_token_counts", "rendered_prompt_sha256s",
        "target_rendered_prompt_sha256s", "manipulation_checks", "search",
    }
    if set(plan) != required:
        raise ContractError("length_plan_invalid", "③L 计划字段不匹配")
    require_sha(tokenizer_sha256, "tokenizer_sha256")
    require_sha(chat_template_sha256, "chat_template_sha256")
    if (plan["schema_version"] != 1 or plan["plan_type"] != "length_control_3l"
            or plan["template_id"] != library.value["template_id"]
            or plan["template_version"] != library.value["template_version"]
            or plan["template_sha256"] != library.digest
            or plan["control_role"] != "task_expansion_bracket"
            or plan["tokenizer_sha256"] != tokenizer_sha256
            or plan["chat_template_sha256"] != chat_template_sha256
            or plan["paired_persona_sha256"] != sha256(persona_text.encode("utf-8"))):
        raise ContractError("length_plan_binding_mismatch", "③L 计划与 persona/profile 不一致")
    text = plan["prompt_text"]
    source_ids = plan["source_ids"]
    if (not isinstance(text, str) or not text
            or plan["prompt_sha256"] != sha256(text.encode("utf-8"))
            or not isinstance(source_ids, list)
            or not source_ids
            or any(not isinstance(source_id, str) for source_id in source_ids)):
        raise ContractError("length_plan_invalid", "③L prompt/source/hash 不合法")
    checks = _behavior_checks(text, tuple(source_ids), library=library)
    if plan["manipulation_checks"] != checks:
        raise ContractError("length_checks_drift", "③L manipulation-check 回执漂移")
    expected = set(item_ids)
    if (len(expected) != len(item_ids)
            or any(not isinstance(item_id, str) or not item_id for item_id in item_ids)):
        raise ContractError("length_plan_items_mismatch", "③L item_ids 不合法")
    actual_counts = plan["rendered_prompt_token_counts"]
    target_counts = plan["target_rendered_prompt_token_counts"]
    actual_hashes = plan["rendered_prompt_sha256s"]
    target_hashes = plan["target_rendered_prompt_sha256s"]
    maps = (actual_counts, target_counts, actual_hashes, target_hashes)
    if any(not isinstance(value, Mapping) or set(value) != expected for value in maps):
        raise ContractError("length_plan_items_mismatch", "③L 计划未精确覆盖 item 集")
    if (type(plan["prompt_token_count"]) is not int
            or type(plan["target_prompt_token_count"]) is not int
            or plan["prompt_token_count"] < 1
            or plan["prompt_token_count"] != plan["target_prompt_token_count"]
            or any(type(value) is not int or value < 1 for value in actual_counts.values())
            or any(type(value) is not int or value < 1 for value in target_counts.values())
            or dict(actual_counts) != dict(target_counts)):
        raise ContractError("length_exact_match_failed", "③L 收据未声明逐 item exact-token 等长")
    for value in (*actual_hashes.values(), *target_hashes.values()):
        require_sha(value, "rendered_prompt_sha256")
    search = plan["search"]
    if (not isinstance(search, Mapping)
            or set(search) != {"states_examined", "max_states", "max_sequence_units"}
            or any(type(search[key]) is not int or search[key] < 1 for key in search)
            or search["states_examined"] > search["max_states"]
            or search["max_states"] != library.value["max_search_states"]
            or search["max_sequence_units"] != library.value["max_sequence_units"]):
        raise ContractError("length_plan_invalid", "③L 有界搜索回执不合法")
    return dict(plan)


def exact_length(text: str, target_tokens: int, *, encode: Callable[[str], list[int]],
                 padding_units: tuple[str, ...]) -> str:
    """Historical fixture helper; never accepted by the production compiler.

    Production must use ``generate_paired_prompt_plans`` so all bytes originate in
    the frozen library and final chat serialization is checked for every item.
    """
    if isinstance(target_tokens, bool) or not isinstance(target_tokens, int) or not 1 <= target_tokens <= 4096:
        raise ContractError("bad_target_tokens", "target_tokens 必须为 1..4096 的整数")
    base_count = len(encode(text))
    if base_count > target_tokens:
        raise ContractError("persona_too_long", "人格正文已超过目标 token 数",
                            {"actual": base_count, "target": target_tokens})
    if base_count == target_tokens:
        return text
    frontier = [text]
    seen = {text}
    for _ in range(target_tokens - base_count + 2):
        next_frontier: list[str] = []
        for current in frontier:
            for unit in padding_units:
                candidate = current + unit
                if candidate in seen:
                    continue
                seen.add(candidate)
                count = len(encode(candidate))
                if count == target_tokens:
                    return candidate
                if count < target_tokens:
                    next_frontier.append(candidate)
        frontier = next_frontier[:4096]
        if not frontier:
            break
    raise ContractError("exact_token_unreachable", "冻结 padding_units 无法得到精确 token 长度")


def build_3l(base_text: str, targets: dict[str, int], *, encode: Callable[[str], list[int]],
             padding_units: tuple[str, ...], required_markers: tuple[str, ...]) -> tuple[LengthVariant, ...]:
    """Historical short/medium/long fixture API; not a production ③L plan."""
    if set(targets) != {"short", "medium", "long"}:
        raise ContractError("bad_3l_targets", "3L targets 必须恰为 short/medium/long")
    counts = [targets[k] for k in ("short", "medium", "long")]
    if counts != sorted(set(counts)):
        raise ContractError("bad_3l_order", "3L token 数必须严格递增")
    out = []
    for label in ("short", "medium", "long"):
        text = exact_length(base_text, targets[label], encode=encode, padding_units=padding_units)
        checks = tuple(marker for marker in required_markers if marker in text)
        if checks != required_markers:
            raise ContractError("manipulation_check_failed", f"{label} 缺少冻结 manipulation marker",
                                {"expected": required_markers, "observed": checks})
        out.append(LengthVariant(label, text, len(encode(text)), sha256(text.encode()), checks))
    return tuple(out)
