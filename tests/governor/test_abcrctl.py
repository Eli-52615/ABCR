"""C1-3 abcrctl 测试（§C1-3 测试要求；subprocess 跑 CLI，cwd=tmp 伪 worktree）。"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ABCRCTL = REPO / "scripts" / "abcrctl"
FIXTURE = REPO / "fixtures" / "envelope_fixture.json"
TEST_KEY = REPO / "fixtures" / "test_approval.key"


def _run(args, cwd, state_dir):
    """在伪 worktree cwd 里跑 abcrctl；ABCR_STATE_DIR 重定向到 tmp。"""
    env = dict(os.environ)
    env["ABCR_STATE_DIR"] = str(state_dir)
    env["PYTHONPATH"] = str(REPO / "src")
    return subprocess.run([sys.executable, str(ABCRCTL), *args],
                          cwd=str(cwd), env=env, capture_output=True, text=True)


@pytest.fixture
def wt(tmp_path):
    """伪 worktree：configs/envelopes/ 下放 fixture 副本；state/ 独立。"""
    (tmp_path / "configs" / "envelopes").mkdir(parents=True)
    (tmp_path / "ledger").mkdir()
    state = tmp_path / "state"
    dst = tmp_path / "configs" / "envelopes" / "batch.json"
    shutil.copy(FIXTURE, dst)
    return {"root": tmp_path, "state": state, "env": dst}


# ① approve：退出码 0、七字段、key 0600
def test_approve_ok(wt):
    r = _run(["approve", "configs/envelopes/batch.json"], wt["root"], wt["state"])
    assert r.returncode == 0, r.stderr
    env = json.loads(wt["env"].read_text(encoding="utf-8"))
    token = env["approval"]["token"]
    for k in ("token_id", "scope", "task_id", "changeset_sha256", "expires_at",
              "persona_change", "sig"):
        assert k in token, f"缺令牌字段 {k}"
    keyp = wt["state"] / "approval.key"
    assert keyp.exists()
    assert stat.S_IMODE(os.stat(keyp).st_mode) == 0o600


# ② a) fixture 原件字节不变；b) 原件预签令牌用 test key 重验仍 ok
def test_fixture_original_untouched(wt):
    before = FIXTURE.read_bytes()
    _run(["approve", "configs/envelopes/batch.json"], wt["root"], wt["state"])
    assert FIXTURE.read_bytes() == before   # 只动副本，原件不变


def test_fixture_original_token_still_valid(tmp_path):
    sys.path.insert(0, str(REPO / "src"))
    from abcr.common import approval_token as tok
    from abcr.governor import envelope as envmod
    env = envmod.load_envelope(FIXTURE)
    ok, why = tok.verify_token(env["approval"]["token"],
                               expected_envelope_sha256=envmod.envelope_sha256(env),
                               verify_secret=TEST_KEY.read_bytes(),
                               consumed_store=tmp_path / "c.json")
    assert (ok, why) == (True, "ok")


# ③ 结构破坏的信封 approve → 退出码 2、无 approval、无账本事件
def test_broken_envelope_rejected(wt):
    broken = json.loads(wt["env"].read_text(encoding="utf-8"))
    del broken["approval"]
    del broken["batch_id"]     # 破坏结构
    wt["env"].write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
    r = _run(["approve", "configs/envelopes/batch.json"], wt["root"], wt["state"])
    assert r.returncode == 2
    after = json.loads(wt["env"].read_text(encoding="utf-8"))
    assert "approval" not in after
    assert not (wt["root"] / "ledger" / "batches.jsonl").exists()


# ④ reject 生成 .reject.json
def test_reject(wt):
    r = _run(["reject", "configs/envelopes/batch.json", "--reason", "测试驳回"],
             wt["root"], wt["state"])
    assert r.returncode == 0, r.stderr
    assert (wt["root"] / "configs" / "envelopes" / "batch.reject.json").exists()


# ⑤ status 三态
def test_status_three_states(wt):
    envdir = wt["root"] / "configs" / "envelopes"
    # DRAFT：去掉 approval
    draft = json.loads((envdir / "batch.json").read_text(encoding="utf-8"))
    draft.pop("approval", None)
    draft["batch_id"] = "B-20260714T000000Z-0002"
    (envdir / "draft.json").write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    # APPROVED：原 batch.json 已含 approval
    # REJECTED：造一个带 .reject.json 的
    rej = json.loads((envdir / "batch.json").read_text(encoding="utf-8"))
    rej["batch_id"] = "B-20260714T000000Z-0003"
    (envdir / "rej.json").write_text(json.dumps(rej, ensure_ascii=False), encoding="utf-8")
    (envdir / "rej.reject.json").write_text("{}", encoding="utf-8")

    r = _run(["status"], wt["root"], wt["state"])
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "DRAFT(待批)" in out
    assert "APPROVED" in out
    assert "REJECTED(人)" in out


# ⑥ 落账断言（AMENDMENT-10）：actor=="human"、event/subject_id 正确
def test_ledger_actor_human(wt):
    _run(["approve", "configs/envelopes/batch.json"], wt["root"], wt["state"])
    ledger = wt["root"] / "ledger" / "batches.jsonl"
    assert ledger.exists()
    last = [ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()][-1]
    rec = json.loads(last)
    assert rec["event"] == "batch_approved"
    assert rec["subject_id"] == "B-20260714T090000Z-0001"   # 冻结 fixture 的 batch_id（AMENDMENT-41）
    assert rec["actor"] == "human"
    # 链完整性最小校验：有 prev_hash / entry_hash
    assert "prev_hash" in rec and "entry_hash" in rec

    # reject 也落账
    _run(["reject", "configs/envelopes/batch.json", "--reason", "x"], wt["root"], wt["state"])
    last2 = [ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()][-1]
    rec2 = json.loads(last2)
    assert rec2["event"] == "batch_rejected" and rec2["actor"] == "human"


# ⑦ consumed.json 损坏 → status 标注且不崩（K5）
def test_status_corrupt_consumed(wt):
    (wt["state"] / "approvals").mkdir(parents=True)
    (wt["state"] / "approvals" / "consumed.json").write_text("not-json", encoding="utf-8")
    r = _run(["status"], wt["root"], wt["state"])
    assert r.returncode == 0, r.stderr
    assert "consumed.json 损坏" in r.stdout
