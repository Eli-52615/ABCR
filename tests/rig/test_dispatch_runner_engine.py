"""dispatch↔runner engine 分支 + torch-mock（R2 真批接线；B2-5 × dispatch，坑16 后续）。

torch 只在 abcr.rig.models.load_model 与 abcr.rig.runner.generate_once 触及——monkeypatch 这两点
即可在无 torch 的 Mac 上覆盖"真 engine"全执行路径。验证两件事：
  1) runner.run_items 产出过 schema.validate_step 的真 48 字段 step + 真 22 键 manifest（engine≠fake）；
  2) dispatch 按 cfg.model.engine 分发到 runner（非 fake），落全套账本事件（registered→...→scored），
     产出的真 manifest/step 带真模型字段——即 R2 真批可审计的形状（fake 路径 R1 回归另测保绿）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from abcr.common import approval_token as tok
from abcr.common.ledger_ref import RunLedger
from abcr.governor import envelope as gv
from abcr.ledger.schema import validate_step
from abcr.ops import dispatch
from abcr.rig import runner

REPO = Path(__file__).resolve().parents[2]


@dataclass
class FakeInfo:
    model_id: str = "Qwen/Qwen2.5-7B-Instruct"
    revision: str = "test-rev"
    chat_template_hash: str = "0" * 64
    dtype: str = "bfloat16"
    device: str = "cuda:0"
    engine: str = "transformers"
    engine_version: str = "4.44.0"
    torch_version: str = "2.4.0"


class FakeTok:
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        return messages[-1]["content"]


def _fake_load_model(cfg):
    return object(), FakeTok(), FakeInfo()


def _fake_generate_once(model, tokenizer, rendered_prompt, temperature=0.0,
                        max_new_tokens=512, hook_spec=None):
    # 确定性 mock：输出随 prompt 变，token 计数固定
    return (f"[mock-7b] {rendered_prompt[:24]}", 7, 5, "eos")


def _patch_torch_surface(monkeypatch):
    monkeypatch.setattr("abcr.rig.models.load_model", _fake_load_model)
    monkeypatch.setattr(runner, "generate_once", _fake_generate_once)


def test_run_items_produces_real_step_and_manifest(tmp_path, monkeypatch):
    _patch_torch_surface(monkeypatch)
    cfg = {
        "config_version": "1.0", "protocol_ref": "W1-V0.9",
        "model": {"model_id": "Qwen/Qwen2.5-7B-Instruct", "revision": "test-rev",
                  "dtype": "bfloat16", "device": "cuda:0", "engine": "transformers"},
        "benchmark": {"family": "golden10", "split": "none", "item_limit": 3},
        "condition": "vanilla", "intervention": None,
        "decoding": {"temperature": 0.0, "max_new_tokens": 32, "seeds": [1]},
    }
    chash = dispatch.config_hash(cfg)
    run_id = f"20260714T090000Z-{chash[:12]}"
    run_dir = tmp_path / "runs" / run_id
    steps: list[dict] = []
    done: list[str] = []
    prompts = {"g01": "q1", "g02": "q2", "g03": "q3"}

    runner.run_items(["g01", "g02", "g03"], cfg, 1, run_id, chash, "abc123def456",
                     prompts, lambda i, s: steps.append(s), lambda i: done.append(i),
                     run_dir, batch_id="B-20260714T090000Z-0001")

    assert done == ["g01", "g02", "g03"]
    assert len(steps) == 3
    for s in steps:
        assert s["model_id"] == "Qwen/Qwen2.5-7B-Instruct"
        assert s["engine"] == "transformers"
        assert s["torch_version"] == "2.4.0"
        res = validate_step(s)
        assert res.ok, f"真 step 未过 schema: {res.anomalies}"
    man = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert man["engine"] == "transformers"
    assert man["model_id"] == "Qwen/Qwen2.5-7B-Instruct"
    assert man["status"] == "completed"
    assert man["batch_id"] == "B-20260714T090000Z-0001"       # 显式 batch_id 未污染 config_hash
    assert dispatch.config_hash(cfg) == chash                  # cfg 未被 run_items 改动


def _real_engine_envelope(dst: Path) -> tuple[Path, str]:
    """由 fixture 信封改 engine=transformers 并重签令牌（envelope_sha256 去 approval，故重算重签）。
    只保留 vanilla 臂：persona_text 臂需 trait 工件（真云跑提供），run_items 传 trait_artifacts=None
    会 fail-closed——这是正确行为，但不属本测试要证的"engine 路由"，故此处只取 vanilla 证路由。"""
    env = json.loads((REPO / "fixtures" / "envelope_fixture.json").read_text(encoding="utf-8"))
    env["run_configs"] = [rc for rc in env["run_configs"] if rc.get("condition") == "vanilla"]
    for rc in env["run_configs"]:
        rc["model"] = {"model_id": "Qwen/Qwen2.5-7B-Instruct", "revision": "test-rev",
                       "dtype": "bfloat16", "device": "cuda:0", "engine": "transformers"}
    key = (REPO / "fixtures" / "test_approval.key").read_bytes()
    env["approval"]["token"] = tok.sign_token(env["batch_id"], gv.envelope_sha256(env),
                                              human_secret=key)
    dst.write_text(json.dumps(env, ensure_ascii=False), encoding="utf-8")
    return dst, env["batch_id"]


def test_dispatch_routes_nonfake_engine_to_runner_e2e(tmp_path, monkeypatch):
    _patch_torch_surface(monkeypatch)
    iso = tmp_path
    monkeypatch.setenv("ABCR_LEDGER_DIR", str(iso / "ledger"))
    monkeypatch.setenv("ABCR_RUNS_ROOT", str(iso / "data" / "runs"))
    monkeypatch.setenv("ABCR_QUEUE_ROOT", str(iso / "queue"))
    monkeypatch.setenv("ABCR_STATE_DIR", str(iso / "state"))
    envp, batch_id = _real_engine_envelope(tmp_path / "env_real.json")

    rc = dispatch.dispatch(str(envp), str(REPO / "fixtures" / "test_approval.key"))
    assert rc == 0, "真 engine 批次未正常收口"

    events = RunLedger(iso / "ledger", "runs_index").events()
    regd = [e["subject_id"] for e in events if e["event"] == "run_registered"]
    assert len(regd) == 3, f"应 3 vanilla run registered，实 {len(regd)}"
    for r in regd:
        evs = {e["event"] for e in events if e["subject_id"] == r}
        assert {"run_started", "run_completed", "run_scored"} <= evs, f"{r} 账本事件缺: {evs}"

    rid = regd[0]
    man = json.loads((iso / "data" / "runs" / rid / "manifest.json").read_text(encoding="utf-8"))
    assert man["engine"] == "transformers"
    assert man["model_id"] == "Qwen/Qwen2.5-7B-Instruct"
    assert man["batch_id"] == batch_id

    steps = [json.loads(x) for x in
             (iso / "data" / "runs" / rid / "steps.jsonl").read_text(encoding="utf-8").splitlines()
             if x.strip()]
    assert len(steps) == 10                    # golden10 → 10 步
    assert all(s["engine"] == "transformers" and s["model_id"] == "Qwen/Qwen2.5-7B-Instruct"
               for s in steps)
    assert all(validate_step(s).ok for s in steps)


def test_fake_engine_still_routes_to_faketask(tmp_path, monkeypatch):
    """回归护栏：engine=fake（默认）仍走 faketask——真 step 的 model_id 绝不出现在 fake 批。"""
    iso = tmp_path
    monkeypatch.setenv("ABCR_LEDGER_DIR", str(iso / "ledger"))
    monkeypatch.setenv("ABCR_RUNS_ROOT", str(iso / "data" / "runs"))
    monkeypatch.setenv("ABCR_QUEUE_ROOT", str(iso / "queue"))
    monkeypatch.setenv("ABCR_STATE_DIR", str(iso / "state"))
    # 若真被误路由到 runner，会因无 torch mock 而炸；这里不 patch，engine=fake 应安然跑通
    rc = dispatch.dispatch(str(REPO / "fixtures" / "envelope_fixture.json"),
                           str(REPO / "fixtures" / "test_approval.key"))
    assert rc == 0
    events = RunLedger(iso / "ledger", "runs_index").events()
    rid = next(e["subject_id"] for e in events if e["event"] == "run_registered")
    man = json.loads((iso / "data" / "runs" / rid / "manifest.json").read_text(encoding="utf-8"))
    assert man["engine"] == "fake"
    assert man["model_id"] == "fake/deterministic-v1"
