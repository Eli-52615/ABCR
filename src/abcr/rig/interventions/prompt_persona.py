"""abcr.rig.interventions.prompt_persona — condition=persona_text 的 system prompt 增量。

纯函数式（无 torch）：输入 trait 工件 + config.intervention（trait/pole/assistant_name），
输出官方同式 system prompt：`You are a/an {assistant_name} assistant. {instruction}`。

官方 assistant_name 规则：pos 用 trait 形容词；neg 有明确反义词用反义词（optimistic→pessimistic），
否则用 helpful。系统提示词拼式与官方 eval_persona 一致。
"""
from __future__ import annotations

# 常见 trait 反义词（neg 极 assistant_name 用；缺则回退 "helpful"）
_ANTONYMS = {
    "optimistic": "pessimistic",
    "conscientiousness": "careless",
    "openness": "closed-minded",
    "neuroticism": "calm",
    "sycophantic": "honest",
}


def assistant_name_for(trait: str, pole: str, override: str | None = None) -> str:
    if override:
        return override
    if pole == "pos":
        return trait
    return _ANTONYMS.get(trait, "helpful")


def build_system(instruction: str, assistant_name: str) -> str:
    return f"You are a/an {assistant_name} assistant. {instruction}"


def from_config(config: dict, trait_artifact: dict) -> str:
    """config.intervention: {trait, trait_pole, assistant_name?, instruction_index?}。
    trait_artifact: 官方 schema {instruction:[{pos,neg}×5], questions, eval_prompt}。"""
    iv = config.get("intervention") or {}
    trait = iv.get("trait", "")
    pole = iv.get("trait_pole", "pos")
    idx = iv.get("instruction_index", 0)
    pairs = trait_artifact["instruction"]
    if not (0 <= idx < len(pairs)):
        raise IndexError(f"instruction_index={idx} 超界（0..{len(pairs) - 1}）")
    instruction = pairs[idx][pole]
    name = assistant_name_for(trait, pole, iv.get("assistant_name"))
    return build_system(instruction, name)
