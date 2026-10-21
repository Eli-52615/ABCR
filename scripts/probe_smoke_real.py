#!/usr/bin/env python
"""scripts/probe_smoke_real.py — 本机快道 LIVE 冒烟（资格化记录用）。

流程：载入冻结 profile → verify_fingerprint()（/api/version + /api/tags +
/api/show 逐项比对）→ 1 题短 generate（确定性 decoding + 显式 seed）→
打印 EngineOutput 摘要与各阶段耗时。

真触网、真推理（本地 ollama，不产生付费 API 调用）。指纹漂移 / 模型缺失 /
daemon 不可达都会 fail-closed 抛错并以非零码退出 —— 本脚本绝不 pull、
绝不换 tag、绝不升级 backend。

用法：
    PYTHONPATH=src .venv312/bin/python scripts/probe_smoke_real.py \
        [--profile configs/probe/profiles/qwen25-7b-q4-v1.json] [--seed 7]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from abcr.probe.ollama_engine import OllamaEngineError, OllamaProbeEngine  # noqa: E402

DEFAULT_PROFILE = REPO / "configs" / "probe" / "profiles" / "qwen25-7b-q4-v1.json"
SMOKE_PROMPT = "只回答两个字：确认。不要输出任何其他内容。"


def main() -> int:
    parser = argparse.ArgumentParser(description="ABCR probe fast-lane live smoke")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--max-output-tokens", type=int, default=8)
    args = parser.parse_args()

    t0 = time.monotonic()
    engine = OllamaProbeEngine(args.profile)
    t_load = time.monotonic() - t0
    print(f"[1/3] profile loaded: {engine.profile_id} "
          f"({engine.model_tag} @ {engine.manifest_digest[:12]}, "
          f"backend ollama/{engine.backend_version}) in {t_load * 1000:.1f} ms")

    t1 = time.monotonic()
    fp = engine.verify_fingerprint()
    t_verify = time.monotonic() - t1
    print(f"[2/3] fingerprint verified in {t_verify * 1000:.1f} ms: "
          + json.dumps({k: fp[k] for k in ("backend_version", "model_tag",
                                           "quantization")}, ensure_ascii=False)
          + f" manifest={fp['manifest_digest'][:12]}… blob={fp['gguf_blob_sha256'][:12]}… "
          + f"template={fp['template_sha256'][:12]}…")

    t2 = time.monotonic()
    out = engine.generate(prompt=SMOKE_PROMPT, seed=args.seed,
                          max_output_tokens=args.max_output_tokens)
    t_gen = time.monotonic() - t2
    print(f"[3/3] one-item generate in {t_gen * 1000:.1f} ms (seed={args.seed}):")
    print(json.dumps({
        "text": out.text,
        "input_tokens": out.input_tokens,
        "output_tokens": out.output_tokens,
        "latency_ms": out.latency_ms,
        "engine_version": out.engine_version,
    }, ensure_ascii=False, indent=2))
    print(f"TOTAL {(time.monotonic() - t0) * 1000:.1f} ms — SMOKE PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except OllamaEngineError as exc:
        print(f"SMOKE FAIL (fail-closed): {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
