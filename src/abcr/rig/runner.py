"""abcr.rig.runner — rig 正式执行器（真实模型 run 驱动，B2-5）。

替换 dispatch 中 engine=fake 的分支（dispatch 按 config.model.engine 分发到 faketask 或 runner）。
流程：config → 前置检查 → manifest 先行 → 逐 item×逐 seed（渲染 prompt→按臂 hook→generate→
组装 48 字段 step 挂链→激活抽样→mark_item_done→heartbeat）→ 幂等续跑（去重以 steps 为准）。

torch/transformers 惰性导入（模块可无 torch import，供纯逻辑单测/dispatch 引用）。
Mac 结果一律 non-citable（MPS）；seed 制 AMENDMENT-29：decoding.seeds 在 run 内循环。
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from abcr.common.constants import CONDITIONS, PROTOCOL_REF
from abcr.common.evidence_floor import require_substantive
from abcr.common.ledger_ref import append_record
from abcr.control.contracts import ContractError
from abcr.ops import runstate
from abcr.ops.dispatch import (_append_prompt_sidecar_once, _code_tree_hash,
                               _git_clean, config_hash)
from abcr.ops.heartbeat import Heartbeat
from abcr.rig import scorer
from abcr.rig.models import (TOKENIZER_FINGERPRINT_SCHEMA,
                             tokenizer_identity_sha256)

RUNS_ROOT_DEFAULT = Path("data/runs")


def _runs_root() -> Path:
    """run 产物根调用时读 env（AMENDMENT-38；与 dispatch._runs_root 同款,供 cloud-day/隔离）。
    无 env 时=data/runs,不改既有真跑单测行为。"""
    return Path(os.environ.get("ABCR_RUNS_ROOT", str(RUNS_ROOT_DEFAULT)))

# method 映射（condition → step.method / 干预臂类型）
_METHOD = {
    "vanilla": None, "persona_text": "prompt", "length_instruct": "prompt",
    "inject": "residual_inject", "ablate": "residual_ablate",
    "inject_random": "residual_inject", "ablate_random": "residual_ablate",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def activation_sample_hit(item_id: str) -> bool:
    """§3.7 抽样规则：item_id sha256 尾 hex 位 <2（约 12.5%≈10%）。"""
    return int(hashlib.sha256(item_id.encode()).hexdigest()[-1], 16) < 2


def compute_run_id(cfg: dict) -> tuple[str, str]:
    """run_id = f"{batch时间戳段}-{config_hash[:12]}"（AMENDMENT-22）。
    有 batch_id 用其内嵌时间戳（确定性）；无信封 --dev 裸跑用当刻 UTC。"""
    chash = config_hash(cfg)
    bid = cfg.get("batch_id", "")
    if bid.startswith("B-") and len(bid) >= 18:
        ts = bid.split("-")[1]   # B-<UTC>-<seq>
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{chash[:12]}", chash


def build_step(run_id: str, item_id: str, output_text: str, cfg: dict, seed: int,
               chash: str, prompt: str, info, git_commit: str, *, split_hash: str,
               latency_ms: int, input_tokens: int, output_tokens: int,
               stop_reason: str, activation_summary: Optional[str] = None) -> dict:
    """组装真实 run 的 48 字段 step 记录（契约 §3.3；过 validate_step）。"""
    cond = cfg.get("condition", "vanilla")
    iv = cfg.get("intervention") or {}
    coef = iv.get("coefficient")
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "trajectory_id": f"{run_id}-{item_id}-{seed}",
        "step_id": 0,
        "parent_run": None,
        "git_commit": git_commit,
        "model_id": info.model_id,
        "model_revision": info.revision,
        "dtype": info.dtype,
        "quantization": None,
        "device": info.device,
        "engine": info.engine,
        "engine_version": info.engine_version,
        "torch_version": info.torch_version,
        "cuda_version": None if not info.device.startswith("cuda") else "cuda",
        "benchmark": cfg.get("benchmark", {}).get("family", "golden10"),
        "split_hash": split_hash,
        "item_id": item_id,
        "condition": cond,
        "trait": iv.get("trait"),
        "trait_pole": iv.get("trait_pole"),
        "method": _METHOD.get(cond),
        "layer": iv.get("layer"),
        "coefficient": float(coef) if coef is not None else None,
        "intervention_strength": float(coef) if coef is not None else None,
        "random_seed": seed,
        "env_seed": None,
        "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "chat_template_hash": info.chat_template_hash,
        "config_hash": chash,
        "action": "generate",
        "obs_hash": None,
        "remaining_budget": None,
        "output_text": output_text,
        "parsed_answer": output_text,
        "is_correct": None,          # 权威值在 scores.jsonl
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "stop_reason": stop_reason,
        "trajectory_stop_reason": "task_done",
        "trait_score": None,
        "fluency_score": None,
        "safety_flags": [],
        "activation_summary": activation_summary,
        "state_snapshot_ref": None,
        "protocol_ref": PROTOCOL_REF,
        "env_lock_ref": "requirements-mac.txt",
    }


def write_manifest(run_dir: Path, run_id: str, cfg: dict, chash: str, info,
                   seeds: list[int], split_hash: str, git_commit: str,
                   status: str, finished_at: Optional[str], non_citable: bool = True,
                   batch_id: Optional[str] = None) -> None:
    """22 键 manifest（AMENDMENT-31；真实 run 版）。batch_id 显式传入优先（dispatch 驱动时不改 cfg
    以免 config_hash 漂移）；未传则回落 cfg.get("batch_id")（runner 独立跑）。"""
    release = cfg.get("release_pin") or {}
    manifest = {
        "run_id": run_id, "config": cfg, "config_hash": chash,
        "git_commit": git_commit, "git_clean": _git_clean(), "code_tree_hash": _code_tree_hash(),
        "model_id": info.model_id, "model_revision": info.revision,
        "chat_template_hash": info.chat_template_hash, "split_hash": split_hash,
        "tokenizer_sha256": getattr(info, "tokenizer_sha256", None),
        "tokenizer_fingerprint_schema": getattr(
            info, "tokenizer_fingerprint_schema", None),
        "engine": info.engine, "engine_version": info.engine_version,
        "torch_version": info.torch_version, "python_version": platform.python_version(),
        "env_lock_ref": "requirements-mac.txt", "seeds": seeds,
        "started_at": _now() if finished_at is None else None, "finished_at": finished_at,
        "status": status, "non_citable": non_citable,
        "protocol_ref": PROTOCOL_REF, "batch_id": batch_id if batch_id is not None else cfg.get("batch_id", ""),
        "release_id": release.get("release_id"),
        "release_tree_hash": release.get("release_tree_hash"),
        "release_lock_hash": release.get("release_lock_hash"),
    }
    p = run_dir / "manifest.json"
    if p.exists():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
            if old.get("started_at"):
                manifest["started_at"] = old["started_at"]
        except (OSError, ValueError):
            pass
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _existing_step_keys(steps_path: Path) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    if steps_path.exists():
        for line in steps_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                keys.add((r["item_id"], r["random_seed"]))
    return keys


def render_prompt(tokenizer, item_prompt: str, system_prompt: Optional[str]) -> str:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": item_prompt})
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def _token_ids(tokenizer, text: str) -> list[int]:
    encode = getattr(tokenizer, "encode", None)
    if callable(encode):
        try:
            ids = encode(text, add_special_tokens=False)
        except TypeError:
            ids = encode(text)
    elif callable(tokenizer):
        encoded = tokenizer(text, add_special_tokens=False)
        ids = encoded["input_ids"]
    else:
        raise ContractError("tokenizer_encode_unavailable", "tokenizer 不支持精确 token 复算")
    if ids and isinstance(ids[0], list):
        ids = ids[0]
    return list(ids)


def _verify_inline_prompt(cfg: dict, tokenizer, system_prompt: Optional[str]) -> None:
    condition = cfg.get("condition")
    if condition not in {"persona_text", "length_instruct"}:
        return
    if system_prompt is None:
        raise ContractError("inline_prompt_missing", f"{condition} 缺 inline prompt_text")
    if "prompt_text" not in cfg:  # frozen legacy trait-artifact fixture only
        return
    if cfg.get("prompt_sha256") != hashlib.sha256(system_prompt.encode("utf-8")).hexdigest():
        raise ContractError("inline_prompt_hash_mismatch", "inline prompt_text 与 prompt_sha256 不一致")
    expected_count = cfg.get("prompt_token_count")
    if (isinstance(expected_count, bool) or not isinstance(expected_count, int)
            or expected_count < 1 or len(_token_ids(tokenizer, system_prompt)) != expected_count):
        raise ContractError("inline_prompt_token_mismatch", "inline prompt token 数与冻结值不一致")


def _verify_runtime_evidence_binding(cfg: dict, tokenizer, info) -> None:
    """Recheck profile facts against the *actual* loaded tokenizer/model.

    A count match is not an identity check.  For every compiled evidence run (and
    unconditionally for a ③L arm), this gate remeasures the fast-tokenizer backend
    and requires the RunConfig, evidence block, ModelInfo and ③L receipt to agree
    on both fingerprint schema and digest before the first generation.
    """
    evidence_run = "dev_bundle_ref" in cfg
    exact_length_run = cfg.get("condition") == "length_instruct"
    if not evidence_run and not exact_length_run:
        return
    evidence = cfg.get("evidence_inputs")
    release = cfg.get("release_pin")
    if not isinstance(evidence, dict) or not isinstance(release, dict):
        raise ContractError("runtime_evidence_binding_missing", "证据 runner 缺 evidence/release pin")
    actual_tokenizer = tokenizer_identity_sha256(tokenizer)
    if actual_tokenizer is None:
        raise ContractError(
            "runtime_tokenizer_identity_unavailable",
            "实际 tokenizer 无完整可序列化 backend；③L/evidence 资格 fail-closed",
        )
    info_tokenizer = getattr(info, "tokenizer_sha256", None)
    info_schema = getattr(info, "tokenizer_fingerprint_schema", None)
    declared_hashes = {
        "RunConfig.tokenizer_sha256": cfg.get("tokenizer_sha256"),
        "evidence_inputs.tokenizer_sha256": evidence.get("tokenizer_sha256"),
        "ModelInfo.tokenizer_sha256": info_tokenizer,
    }
    declared_schemas = {
        "RunConfig.tokenizer_fingerprint_schema": cfg.get("tokenizer_fingerprint_schema"),
        "evidence_inputs.tokenizer_fingerprint_schema": evidence.get(
            "tokenizer_fingerprint_schema"),
        "ModelInfo.tokenizer_fingerprint_schema": info_schema,
    }
    if exact_length_run:
        receipt = cfg.get("length_control_receipt")
        if not isinstance(receipt, dict):
            raise ContractError("runtime_tokenizer_binding_missing",
                                "③L RunConfig 缺冻结 length_control_receipt")
        declared_hashes["length_control_receipt.tokenizer_sha256"] = receipt.get(
            "tokenizer_sha256")
    if any(value != actual_tokenizer for value in declared_hashes.values()):
        raise ContractError(
            "runtime_tokenizer_binding_mismatch",
            "RunConfig/profile/ModelInfo 与实际 tokenizer fingerprint 不一致",
            {"actual": actual_tokenizer,
             "mismatched_fields": sorted(name for name, value in declared_hashes.items()
                                         if value != actual_tokenizer)},
        )
    if any(value != TOKENIZER_FINGERPRINT_SCHEMA for value in declared_schemas.values()):
        raise ContractError(
            "runtime_tokenizer_schema_mismatch",
            "RunConfig/profile/ModelInfo tokenizer fingerprint schema 不一致",
            {"expected": TOKENIZER_FINGERPRINT_SCHEMA,
             "mismatched_fields": sorted(name for name, value in declared_schemas.items()
                                         if value != TOKENIZER_FINGERPRINT_SCHEMA)},
        )
    observed = {"model_id": info.model_id, "model_revision": info.revision,
                "chat_template_sha256": info.chat_template_hash,
                "scorer_id": scorer.SCORER_ID, "scorer_version": scorer.SCORER_VERSION}
    for field, value in observed.items():
        if evidence.get(field) != value:
            raise ContractError("runtime_evidence_binding_mismatch",
                                f"runner 重算 {field} 与批准配置不一致")
    for field in ("release_id", "release_tree_hash", "release_lock_hash"):
        if release.get(field) != evidence.get(field):
            raise ContractError("release_pin_mismatch", f"runner release {field} 不一致")
    if os.environ.get("ABCR_SERVICE_LABEL") and os.environ.get("ABCR_RELEASE_ID") != release.get("release_id"):
        raise ContractError("active_release_mismatch", "runner active release 与批准 release 不一致")


def _verify_final_rendered_prompt(cfg: dict, tokenizer, item_id: str,
                                  rendered_prompt: str) -> int | None:
    """Second exact-token gate after the chat template has serialized messages."""
    expected = cfg.get("rendered_prompt_token_counts")
    if cfg.get("condition") != "length_instruct" and not isinstance(expected, dict):
        return None
    count = len(_token_ids(tokenizer, rendered_prompt))
    if cfg.get("condition") == "length_instruct":
        if (not isinstance(expected, dict) or set(expected) != set(cfg.get("item_ids", []))
                or isinstance(expected.get(item_id), bool)
                or not isinstance(expected.get(item_id), int)):
            raise ContractError("rendered_prompt_token_plan_missing",
                                "length_instruct 必须精确绑定每个 item 的最终序列化 token 数")
        if count != expected[item_id]:
            raise ContractError("rendered_prompt_token_mismatch",
                                "最终序列化 prompt token 数与冻结 ③L 计划不一致")
    elif isinstance(expected, dict) and item_id in expected and count != expected[item_id]:
        raise ContractError("rendered_prompt_token_mismatch", "最终序列化 prompt token 数不一致")
    return count


def generate_once(model, tokenizer, rendered_prompt: str, temperature: float = 0.0,
                  max_new_tokens: int = 512, hook_spec: Optional[dict] = None) -> tuple[str, int, int, str]:
    """单次生成（torch）。返回 (output_text, input_tokens, output_tokens, stop_reason)。"""
    import torch
    from contextlib import nullcontext
    from abcr.rig.hooks import ResidualHook

    inputs = tokenizer(rendered_prompt, return_tensors="pt").to(model.device)
    n_in = int(inputs["input_ids"].shape[1])
    hook = None
    ctx = nullcontext()
    if hook_spec is not None:
        hook = ResidualHook(model, hook_spec["vector"], hook_spec["layer"],
                            hook_spec["mode"], hook_spec.get("coef", 0.0))
        ctx = hook
    with torch.no_grad(), ctx:
        out = model.generate(**inputs, max_new_tokens=max_new_tokens,
                             do_sample=temperature > 0,
                             temperature=temperature if temperature > 0 else None)
    if hook is not None:
        hook.raise_if_unverified()   # §2.11 判据接线：干预未真正生效即 fail-closed（根因④）
    gen_ids = out[0][n_in:]
    text = tokenizer.decode(gen_ids, skip_special_tokens=True)
    n_out = int(gen_ids.shape[0])
    stop = "max_tokens" if n_out >= max_new_tokens else "eos"
    return text, n_in, n_out, stop


def build_hook_spec(cfg: dict, save_dir: Optional[Path] = None) -> Optional[dict]:
    """按 condition 造 hook 规格（vanilla/persona_text 等无 hook 臂返 None）。torch 惰性（在子模块内）。

    臂纯度白名单（根因③）：未知/拼错的 condition 此前经 _METHOD.get→None 被【静默当 vanilla】跑掉，
    污染物无声混入。这里对不在协议白名单 constants.CONDITIONS 内的 condition fail-closed 拒跑，
    绝不静默降级。白名单内但非 hook 臂（vanilla/persona_text/neutral_token/length_instruct）才返 None。
    """
    cond = cfg.get("condition", "vanilla")
    if cond not in CONDITIONS:
        raise ValueError(
            f"未知 condition '{cond}'：不在协议白名单，拒绝静默降级为 vanilla（臂纯度 fail-closed）")
    if cond in ("inject", "ablate"):
        from abcr.rig.interventions.residual_vector import spec_from_config
        return spec_from_config(cfg)
    if cond in ("inject_random", "ablate_random"):
        from abcr.rig.interventions.controls import spec_from_config
        return spec_from_config(cfg, save_dir=save_dir)
    return None


def build_system_prompt(cfg: dict, trait_artifacts: Optional[dict]) -> Optional[str]:
    condition = cfg.get("condition")
    if condition in {"persona_text", "length_instruct"}:
        inline = cfg.get("prompt_text")
        if isinstance(inline, str) and inline:
            return inline
        if condition == "length_instruct" or "dev_bundle_ref" in cfg:
            raise ContractError("inline_prompt_missing", f"{condition} 必须使用批准信封内联 prompt_text")
    if condition == "persona_text":
        from abcr.rig.interventions.prompt_persona import from_config
        trait = (cfg.get("intervention") or {}).get("trait", "")
        artifact = (trait_artifacts or {}).get(trait)
        if artifact is None:
            raise ValueError(f"persona_text 臂缺 trait 工件：{trait}")
        return from_config(cfg, artifact)
    return None


# ────────────────────────── benchmark / split ──────────────────────────
def load_benchmark(cfg: dict) -> list[dict]:
    """按 config.benchmark 载入 items（split 过滤 + item_limit）。

    此前 golden10 分支【提前 return】绕过 sort 与 item_limit——声明的 item_limit 被静默无视，
    实际跑的题量与信封声明不一致。现统一走 sort→limit。空题集（split 打空/family 错）此前会
    "0 题跑完拿满分"，现经 evidence_floor.require_substantive 在入口 fail-closed（根因②）。
    """
    b = cfg.get("benchmark", {})
    family = b.get("family", "golden10")
    if family == "golden10":
        raw = json.loads(Path("data/golden/golden10.json").read_text(encoding="utf-8"))["items"]
        items = [{"item_id": it["id"], "prompt": it["prompt"], **it} for it in raw]
        # golden10 无 split 文件（AMENDMENT-31）——不做 split 过滤
    else:
        path = Path(f"data/benchmarks/{family}.json")
        items = json.loads(path.read_text(encoding="utf-8"))["items"]
        split = b.get("split")
        if split and split != "none":
            from abcr.rig.splits import assign_split
            items = [it for it in items if assign_split(family, it["item_id"]) == split]
    items.sort(key=lambda it: it["item_id"])
    limit = b.get("item_limit")
    if limit:
        items = items[:limit]
    require_substantive(len(items), f"benchmark items（family={family} split={b.get('split')}）")
    return items


def split_hash_for(cfg: dict) -> str:
    """split_hash 从【实际 assignments 复算】，不采信文件自述的 split_hash 字段（根因③：验船师不问运动员）。
    若文件既声明 split_hash 又与复算不符 → 判为被篡改，fail-closed 拒跑（新跑硬门；历史批仍存旧值，
    本函数只作用于新跑）。golden10 无 split 文件，仍记 "fixture"（不改历史语义）。"""
    if "dev_bundle_ref" in cfg:
        source_hash = (cfg.get("evidence_inputs") or {}).get("source_hash")
        if not isinstance(source_hash, str) or len(source_hash) != 64:
            raise ContractError("split_hash_unbound", "证据 runner 缺 DevBundle source/split hash")
        return source_hash
    family = cfg.get("benchmark", {}).get("family", "golden10")
    if family == "golden10":
        return "fixture"   # golden10 无 split 文件（AMENDMENT-31）
    p = Path(f"data/splits/{family}.json")
    if not p.exists():
        return "fixture"
    from abcr.rig.splits import split_hash as _split_hash
    data = json.loads(p.read_text(encoding="utf-8"))
    assignments = data.get("assignments") or {}
    require_substantive(len(assignments), f"split assignments（{family}）")
    recomputed = _split_hash(assignments)
    declared = data.get("split_hash")
    if declared is not None and declared != recomputed:
        raise ValueError(
            f"split_hash 篡改：{family} 自述 {declared} 但 assignments 复算为 {recomputed}（fail-closed）")
    return recomputed


def precheck(cfg: dict, dev: bool) -> bool:
    """前置检查（契约 §3.6，不过拒跑）：git clean（否则须 --dev 且 non_citable）；
    revision/chat_template/split 一致性交 models.load_model 的样例检 + config 校验。
    返回 non_citable。"""
    clean = _git_clean()
    if not clean and not dev:
        raise RuntimeError("git 工作区不干净：须加 --dev 旗标（manifest 打 non_citable:true）")
    return (not clean) or dev or True   # Mac/rig 一律 non_citable


def capture_projection(model, tokenizer, full_text: str, vector, layer: int, n_prompt: int) -> dict:
    """§3.7 激活抽样：对 response tokens 在 v̂ 上的投影序列 + 分层统计（mean/p50/p90）。
    post-hoc 单次前向（temp0 与逐步一致；采样臂对已生成 token 复算——rig-validation 口径）。"""
    import torch
    import numpy as np
    inputs = tokenizer(full_text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model(**inputs, output_hidden_states=True)
    hs = out.hidden_states[layer][0]            # [seq, hidden]
    v = vector.to(dtype=torch.float32, device=hs.device)
    vhat = v / v.norm()
    proj = (hs.to(torch.float32) @ vhat).cpu().numpy()
    resp = proj[max(n_prompt - 1, 0):]          # response 段
    return {"proj_seq": resp, "mean": float(np.mean(resp)) if len(resp) else 0.0,
            "p50": float(np.percentile(resp, 50)) if len(resp) else 0.0,
            "p90": float(np.percentile(resp, 90)) if len(resp) else 0.0}


def run_config(config_path: str | Path, dev: bool = False, temp0_once: bool = False,
               trait_artifacts: Optional[dict] = None) -> str:
    """主驱动：真实模型逐 item×seed 执行，幂等续跑（去重以 steps 为准）。返回 run_id。"""
    from abcr.rig import models

    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    non_citable = precheck(cfg, dev)
    run_id, chash = compute_run_id(cfg)
    run_dir = _runs_root() / run_id
    (run_dir / "activations").mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    steps_path = run_dir / "steps.jsonl"

    items = load_benchmark(cfg)
    sh = split_hash_for(cfg)
    seeds = cfg.get("decoding", {}).get("seeds", [1])
    if temp0_once:
        seeds = seeds[:1]
    temperature = 0.0 if temp0_once else float(cfg.get("decoding", {}).get("temperature", 0.0))
    max_new = int(cfg.get("decoding", {}).get("max_new_tokens", 512))

    import subprocess
    git_commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                text=True).stdout.strip() or "unknown"

    model, tok, info = models.load_model(cfg)
    _verify_runtime_evidence_binding(cfg, tok, info)
    system_prompt = build_system_prompt(cfg, trait_artifacts)
    _verify_inline_prompt(cfg, tok, system_prompt)
    hook_spec = build_hook_spec(cfg, save_dir=run_dir / "activations")

    item_seed_ids = [f"{it['item_id']}:{s}" for it in items for s in seeds]
    runstate.register_run(run_id, item_seed_ids, meta={"config_hash": chash})
    write_manifest(run_dir, run_id, cfg, chash, info, seeds, sh, git_commit,
                   status="running", finished_at=None, non_citable=non_citable)

    done_keys = _existing_step_keys(steps_path)   # AMENDMENT-25 续跑去重
    # 心跳落账（runs_index step_progress）由 dispatch 承担；runner 独立跑时用 no-op 仅计数
    start_done = len(done_keys)
    hb = Heartbeat(lambda *a, **k: None, run_id, start_items=start_done)
    import torch

    for it in items:
        for seed in seeds:
            if (it["item_id"], seed) in done_keys:
                runstate.mark_item_done(run_id, f"{it['item_id']}:{seed}")
                continue
            torch.manual_seed(seed)
            rendered = render_prompt(tok, it["prompt"], system_prompt)
            rendered_tokens = _verify_final_rendered_prompt(cfg, tok, it["item_id"], rendered)
            prompt_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
            _append_prompt_sidecar_once(run_dir, {
                "run_id": run_id, "item_id": it["item_id"], "seed": seed, "random_seed": seed,
                "config_hash": chash, "arm_id": cfg.get("arm_id"),
                "condition": cfg.get("condition", "vanilla"), "prompt_text": rendered,
                "prompt_hash": prompt_hash,
                "system_prompt_hash": hashlib.sha256((system_prompt or "").encode("utf-8")).hexdigest(),
                "template_hash": info.chat_template_hash, "token_count": rendered_tokens,
            })
            import time
            t0 = time.time()
            text, n_in, n_out, stop = generate_once(
                model, tok, rendered, temperature=temperature,
                max_new_tokens=max_new, hook_spec=hook_spec)
            latency = int((time.time() - t0) * 1000)
            act_summary = None
            if hook_spec is not None and activation_sample_hit(it["item_id"]):
                import numpy as np
                stats = capture_projection(model, tok, rendered + text,
                                           hook_spec["vector"], hook_spec["layer"], n_in)
                npz = run_dir / "activations" / f"{it['item_id']}_{seed}.npz"
                np.savez(npz, proj_seq=stats["proj_seq"], mean=stats["mean"],
                         p50=stats["p50"], p90=stats["p90"])
                act_summary = f"activations/{it['item_id']}_{seed}.npz"
            step = build_step(run_id, it["item_id"], text, cfg, seed, chash, rendered, info,
                              git_commit, split_hash=sh, latency_ms=latency,
                              input_tokens=n_in, output_tokens=n_out, stop_reason=stop,
                              activation_summary=act_summary)
            if step["prompt_hash"] != prompt_hash:
                raise ContractError("prompt_sidecar_hash_mismatch", "step 与 prompt sidecar hash 不一致")
            append_record(steps_path, step)
            runstate.mark_item_done(run_id, f"{it['item_id']}:{seed}")
            hb.tick()

    write_manifest(run_dir, run_id, cfg, chash, info, seeds, sh, git_commit,
                   status="completed", finished_at=_now(), non_citable=non_citable)
    scorer.score_run(run_dir)
    return run_id


def run_items(pending_items, cfg: dict, seed: int, run_id: str, chash: str,
              git_commit: str, prompts: dict[str, str],
              append_step, mark_done, run_dir: Path, batch_id: str = "") -> object:
    """dispatch 可调的真模型逐-item 执行器（engine≠fake；坑16/R2 真批接线）。

    职责分工：dispatch 握账本事件(run_started/completed/scored)、队列收口、心跳(经 mark_done→hb.tick)、
    评分(dispatch 统一 scorer.score_run)；**本函数只负责**模型加载→逐 item 真生成→真 48 字段 step→
    真 manifest(running/completed)。run_id/chash 用 dispatch 传入(不重算)；不改 cfg(免 config_hash 漂移)。

    torch 只在 models.load_model 与 generate_once 触及——单测经 monkeypatch 这两点即可无 torch 覆盖本函数。

    支持臂：vanilla、inject/ablate（向量臂，需真 .pt 向量→build_hook_spec）、inject_random/ablate_random。
    **persona_text 臂**需 trait 工件（build_system_prompt(cfg, None) 会 ValueError fail-closed，被 dispatch
    捕获→run_failed）——经 dispatch 驱动时暂不支持（trait_artifacts 未接线）；真云跑该臂走 runner.run_config
    独立驱动或后续给 dispatch 接 trait_artifacts 装载。
    """
    from abcr.rig import models

    run_dir = Path(run_dir)
    (run_dir / "activations").mkdir(parents=True, exist_ok=True)
    model, tok, info = models.load_model(cfg)          # ← torch 面（mock 点1）
    _verify_runtime_evidence_binding(cfg, tok, info)
    system_prompt = build_system_prompt(cfg, None)
    _verify_inline_prompt(cfg, tok, system_prompt)
    hook_spec = build_hook_spec(cfg, save_dir=run_dir / "activations")
    sh = split_hash_for(cfg)
    temperature = float(cfg.get("decoding", {}).get("temperature", 0.0))
    max_new = int(cfg.get("decoding", {}).get("max_new_tokens", 512))

    write_manifest(run_dir, run_id, cfg, chash, info, [seed], sh, git_commit,
                   status="running", finished_at=None, non_citable=True, batch_id=batch_id)
    for item_id in list(pending_items):
        rendered = render_prompt(tok, prompts.get(item_id, ""), system_prompt)
        rendered_tokens = _verify_final_rendered_prompt(cfg, tok, item_id, rendered)
        prompt_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        _append_prompt_sidecar_once(run_dir, {
            "run_id": run_id, "item_id": item_id, "seed": seed, "random_seed": seed,
            "config_hash": chash, "arm_id": cfg.get("arm_id"),
            "condition": cfg.get("condition", "vanilla"), "prompt_text": rendered,
            "prompt_hash": prompt_hash,
            "system_prompt_hash": hashlib.sha256((system_prompt or "").encode("utf-8")).hexdigest(),
            "template_hash": info.chat_template_hash, "token_count": rendered_tokens,
        })
        text, n_in, n_out, stop = generate_once(         # ← torch 面（mock 点2）
            model, tok, rendered, temperature=temperature,
            max_new_tokens=max_new, hook_spec=hook_spec)
        step = build_step(run_id, item_id, text, cfg, seed, chash, rendered, info, git_commit,
                          split_hash=sh, latency_ms=0, input_tokens=n_in, output_tokens=n_out,
                          stop_reason=stop)
        if step["prompt_hash"] != prompt_hash:
            raise ContractError("prompt_sidecar_hash_mismatch", "step 与 prompt sidecar hash 不一致")
        append_step(item_id, step)
        mark_done(item_id)
    write_manifest(run_dir, run_id, cfg, chash, info, [seed], sh, git_commit,
                   status="completed", finished_at=_now(), non_citable=True, batch_id=batch_id)
    return info


def main() -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="rig 真实模型 run 驱动（B2-5）")
    ap.add_argument("--config", required=True)
    ap.add_argument("--dev", action="store_true", help="允许 git 不干净（manifest non_citable:true）")
    ap.add_argument("--temp0-once", action="store_true", help="G1 双跑一致检：temp0 单 seed")
    a = ap.parse_args()
    run_id = run_config(a.config, dev=a.dev, temp0_once=a.temp0_once)
    print(f"run_id={run_id}；产物在 data/runs/{run_id}/")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
