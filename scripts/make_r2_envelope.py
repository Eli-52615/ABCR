#!/usr/bin/env python3
"""一键生成并签发 golden10 R2 真批信封（非实验团队人员可直接用）。

它替你做掉唯一需要专业知识的步骤——手工签 HMAC 审批令牌。你只需运行本脚本，它会：
  1) 首次运行时在 state/approval.key 生成你的审批密钥（代表"你批准了这一批"，请勿删）；
  2) 造一个 golden10 基准批的信封（vanilla 臂 × 你给的 seed），engine 按 --engine 定；
  3) 用你的密钥签好令牌，写到 configs/envelopes/<batch_id>.json；
  4) 打印 batch_id 和"下一步该敲什么"。

用法：
  # 云端真跑（真 7B）：
  PYTHONPATH=src python scripts/make_r2_envelope.py --engine transformers
  # 本地自证（Mac 无 GPU 也能跑通全链，验证脚本链没问题）：
  PYTHONPATH=src python scripts/make_r2_envelope.py --engine fake
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from abcr.common import approval_token as tok
from abcr.governor import envelope as gv

REPO = Path(__file__).resolve().parents[1]


def ensure_approval_key(state_dir: Path) -> bytes:
    kp = state_dir / "approval.key"
    if not kp.exists():
        kp.parent.mkdir(parents=True, exist_ok=True)
        kp.write_bytes(secrets.token_bytes(32))
        print(f"[首次] 已生成你的审批密钥 → {kp}（代表你的批准；请勿删、勿改）")
    return kp.read_bytes()


def build_run_config(engine: str, model_id: str, seed: int, batch_id: str,
                     revision: str = "main") -> dict:
    if engine == "fake":
        model = {"model_id": "fake/deterministic-v1", "revision": "fixture",
                 "dtype": "none", "device": "none", "engine": "fake"}
        max_new = 0
    else:
        # revision 必须是 HF 上真实存在的 git ref（分支/tag/commit sha）。默认 main;
        # 要 citable 就传 --revision <真实 snapshot sha>（钉死可复现）。
        model = {"model_id": model_id, "revision": revision,
                 "dtype": "bfloat16", "device": "cuda:0", "engine": engine}
        max_new = 256
    return {
        "config_version": "1.0", "protocol_ref": "W1-V0.9",
        "model": model,
        "benchmark": {"family": "golden10", "split": "none", "item_limit": 10},
        "condition": "vanilla", "intervention": None,
        "decoding": {"temperature": 0.0, "max_new_tokens": max_new, "seeds": [seed]},
        "batch_id": batch_id,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="生成并签发 golden10 R2 真批信封")
    ap.add_argument("--engine", default="transformers",
                    choices=["transformers", "vllm", "fake"],
                    help="transformers/vllm=真 7B（云端）；fake=本地自证（Mac 可跑）")
    ap.add_argument("--model-id", default="Qwen/Qwen2.5-7B-Instruct")
    ap.add_argument("--revision", default="main",
                    help="HF git ref（分支/tag/commit sha）。默认 main;citable 请传真实 snapshot sha")
    ap.add_argument("--seeds", default="1,2,3", help="逗号分隔；每个 seed 一个 vanilla run")
    a = ap.parse_args()

    state_dir = Path(os.environ.get("ABCR_STATE_DIR", "state"))
    key = ensure_approval_key(state_dir)

    now = datetime.now(timezone.utc)
    batch_id = f"B-{now.strftime('%Y%m%dT%H%M%SZ')}-0001"
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]

    # 以 fixture 信封为结构模板（保证过 validate_envelope），只换 batch_id / run_configs / deadline / approval
    env = json.loads((REPO / "fixtures" / "envelope_fixture.json").read_text(encoding="utf-8"))
    env["batch_id"] = batch_id
    env["deadline_utc"] = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    env["run_configs"] = [build_run_config(a.engine, a.model_id, s, batch_id, a.revision)
                          for s in seeds]
    env["drafted_by"] = "make_r2_envelope"
    env["approval"] = {
        "token": tok.sign_token(batch_id, gv.envelope_sha256(env), human_secret=key),
        "approved_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    ok, problems = gv.validate_envelope(env)
    if not ok:
        print("[错误] 生成的信封未过结构校验：", problems)
        return 1

    out = REPO / "configs" / "envelopes" / f"{batch_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ 信封已生成并签好：{out}")
    print(f"   batch_id = {batch_id}   engine = {a.engine}   runs = {len(seeds)}（vanilla × seeds {seeds}）")
    print(f"\n下一步（照抄）：")
    print(f"   export PYTHONPATH=src")
    print(f"   python -m abcr.ops.dispatch --envelope {out.relative_to(REPO)} --key {state_dir}/approval.key")
    print(f"   python scripts/a_rescore.py {batch_id} --repo-root .")
    print(f"   python scripts/a_audit.py {batch_id} --items 1,2,3,4,5,6")
    print(f'   python -c "from abcr.report.repro_pack import pack; print(pack(\'{batch_id}\'))"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
