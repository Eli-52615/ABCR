"""abcr.sandboxing.drills.harness —— 故障演练共用断言库（A2-6，AMENDMENT-17 隔离纪律）。

架构位置：包A·故障演练侧。四演练（R2 门 fable 手跑）的共用地板：隔离 root 管理 + 真链零写入
证明 + 五链自验 + steps 幂等断言 + 演练产物登记 + 统一 VERDICT 打印。

AMENDMENT-17 隔离纪律（逐条落地）：演练一律在临时隔离 root `state/audit/drills/<drill_n>-<UTC>/`
的账本副本上跑，**真链零写入**；注入/检测的 repo_root 一律指向隔离 root；注入事件 payload 带
actor="drill"；演练用独立节流文件（隔离 root 自带 state/audit/，天然隔离）。

契约出处：工程包A §7 专项章 + §8.2 R2-A1~A4。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from abcr.common.evidence_floor import EvidenceError, require_substantive
from abcr.common.ledger_ref import LedgerTampered, RunLedger

LEDGER_CHAINS = ("runs_index", "batches", "costs", "instances", "protocol")


def dispatch_env(iso_root: Path) -> dict[str, str]:
    """把 dispatch/queue/runstate 的输出 root 全指向隔离 root（坑16 切真的隔离旗标）。
    输入(golden/prompts/git 树哈希)仍读真仓——输入输出分离。经 AMENDMENT-38 call-time env。"""
    iso = Path(iso_root)
    return {
        "ABCR_LEDGER_DIR": str(iso / "ledger"),
        "ABCR_RUNS_ROOT": str(iso / "data" / "runs"),
        "ABCR_QUEUE_ROOT": str(iso / "queue"),
        "ABCR_STATE_DIR": str(iso / "state"),
    }


def drive_real_dispatch(repo_root: Path, iso_root: Path,
                        envelope: str = "fixtures/envelope_fixture.json",
                        key: str = "fixtures/test_approval.key",
                        extra_env: dict[str, str] | None = None,
                        ) -> subprocess.CompletedProcess:
    """坑16 切真：subprocess 真调 `python -m abcr.ops.dispatch` 打到隔离 root（非 sim 合成账本）。
    走 subprocess 而非进程内调用，因 crash 演练 faketask 会 os._exit——不能连累演练进程。
    输出 root 经 dispatch_env 指向 iso_root，真链零写入（调用方用 real_ledger_digest 前后比对证）。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    env.update(dispatch_env(iso_root))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "abcr.ops.dispatch", "--envelope", envelope, "--key", key],
        cwd=str(Path(repo_root)), env=env, capture_output=True, text=True)


def run_ids_in(iso_root: Path) -> list[str]:
    """从隔离 root 的 runs_index 链折叠出该批注册的 run_id（真 dispatch 落账后读取）。"""
    ri = RunLedger(Path(iso_root) / "ledger", "runs_index")
    seen: list[str] = []
    for ev in ri.events():
        if ev.get("event") == "run_registered":
            rid = ev.get("subject_id")
            if rid and rid not in seen:
                seen.append(rid)
    return seen


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def new_iso_root(repo_root: Path, drill_name: str, ts: str | None = None) -> Path:
    """建隔离 root state/audit/drills/<drill_name>-<UTC>/，返回其路径。"""
    ts = ts or utc_stamp()
    iso = Path(repo_root) / "state" / "audit" / "drills" / f"{drill_name}-{ts}"
    (iso / "ledger").mkdir(parents=True, exist_ok=True)
    (iso / "state" / "audit").mkdir(parents=True, exist_ok=True)
    return iso


def copy_real_ledger(repo_root: Path, iso_root: Path) -> None:
    """把真链 ledger/*.jsonl 复制进隔离 root（AMENDMENT-17：在副本上跑）。缺则跳过。"""
    src = Path(repo_root) / "ledger"
    dst = Path(iso_root) / "ledger"
    dst.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        for p in src.glob("*.jsonl"):
            shutil.copy2(p, dst / p.name)


def seed_frozen_inputs(repo_root: Path, iso_root: Path) -> None:
    """把 auditor/rescore/sim 所需的冻结输入（data/golden + fixtures）拷进隔离 root。"""
    for rel in ("data/golden/golden10.json",
                "fixtures/envelope_fixture.json",
                "fixtures/expected_scores.jsonl"):
        src = Path(repo_root) / rel
        if src.exists():
            dst = Path(iso_root) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def real_ledger_digest(repo_root: Path) -> dict[str, str]:
    """真链 ledger/*.jsonl 逐文件 sha256（.lock 排除）——演练前后比对证明真链零写入。"""
    src = Path(repo_root) / "ledger"
    out: dict[str, str] = {}
    if src.is_dir():
        for p in sorted(src.glob("*.jsonl")):
            out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def verify_all_chains(iso_root: Path) -> tuple[bool, list[str]]:
    """五链逐条 verify_chain。返回 (全过?, 证据行)。

    根因②闭合（空即失败）：过去缺失链一律 SKIP 且 ok 保持 True——于是**全部链缺失/全空**
    的空账本能冒充"五链完整"通过。现经 evidence_floor.require_substantive 设地板：至少一条链
    须**存在且非空且验过**，否则整体 FAIL。空/缺失只 SKIP 计数、不计入实质验证；等价攻击
    （touch 空链文件、清空全部链）都到不了 PASS。fail-closed 走返回 (False,证据) 不抛（底层
    读取不崩、演练照打印，与 AMENDMENT-17 隔离纪律一致）。"""
    ev: list[str] = []
    ok = True
    verified = 0
    for chain in LEDGER_CHAINS:
        p = Path(iso_root) / "ledger" / f"{chain}.jsonl"
        if not p.exists():
            ev.append(f"链 {chain}: 空链 SKIP")
            continue
        try:
            ledger = RunLedger(p.parent, p.stem)
            ledger.verify_chain()
            _, n = ledger.head_and_length()
            if n > 0:
                verified += 1
                ev.append(f"链 {chain}: verify_chain 通过 ({n} 条)")
            else:
                ev.append(f"链 {chain}: 空链(0 条) SKIP")
        except LedgerTampered as e:
            ok = False
            ev.append(f"链 {chain}: 断链 {e}")
    try:
        require_substantive(verified, f"{Path(iso_root).name}/ledger 可验链", minimum=1)
    except EvidenceError as e:
        ok = False
        ev.append(f"无一条实质链可验——空账本不得冒充五链完整 (evidence_floor): {e}")
    return ok, ev


def no_duplicate_steps(run_dir: Path) -> tuple[bool, list[str]]:
    """steps.jsonl 无重复 (item_id, random_seed, step_id)（幂等证明），且**必须有实质 step**。

    根因②闭合（空即失败）：过去缺文件/空文件直接返回 (True, ...)——于是"清空 steps 绕过无重复
    检查"是免费的（等价于伪报完成）。现经 evidence_floor.require_substantive 设地板：0 实质 step
    直接判 FAIL。健康的 kill/resume 演练必产出 step，故对合法路径无影响；而"清空 steps"这类
    等价攻击不再能靠"无内容→无重复→通过"绕过。fail-closed 走返回 (False,证据) 不抛（底层读取
    保持不崩，把硬 FAIL 留在 gate 侧，与承重梁纪律一致）。"""
    p = Path(run_dir) / "steps.jsonl"
    lines: list[str] = []
    if p.exists():
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    try:
        require_substantive(len(lines), f"{run_dir.name}/steps.jsonl", minimum=1)
    except EvidenceError as e:
        return False, [f"{run_dir.name}: 0 实质 step——空即失败，不得靠无内容绕过无重复检查 "
                       f"(evidence_floor): {e}"]
    seen: set[tuple] = set()
    dups: list[str] = []
    for ln in lines:
        st = json.loads(ln)
        key = (st.get("item_id"), st.get("random_seed"), st.get("step_id"))
        if key in seen:
            dups.append(f"{run_dir.name}: 重复 step {key}")
        seen.add(key)
    return (not dups), (dups or [f"{run_dir.name}: {len(seen)} step 无重复 (item,seed,step_id)"])


def write_readme(iso_root: Path, meta: dict) -> Path:
    """演练目录 README：登记人造账目（actor=drill 可识别）+ 注入参数 + 断言结果。"""
    p = Path(iso_root) / "README.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def load_sim(repo_root: Path) -> ModuleType:
    """载入 A 侧脚手架 scripts/a_sim_b_fixture.py（构建 fixture 批的 run/step/manifest 共用件）。"""
    path = Path(repo_root) / "scripts" / "a_sim_b_fixture.py"
    spec = importlib.util.spec_from_file_location("_a_sim_b_fixture_drill", path)
    mod = importlib.util.module_from_spec(spec)
    if str(Path(repo_root) / "src") not in sys.path:
        sys.path.insert(0, str(Path(repo_root) / "src"))
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def finish(drill_n: int, passed: bool, iso_root: Path,
           artifacts: list[str], meta: dict) -> int:
    """收尾：写 README + 打印 DRILL n VERDICT + 留痕清单路径。返回退出码（0/1）。"""
    meta = {**meta, "verdict": "PASS" if passed else "FAIL",
            "artifacts": artifacts, "iso_root": str(iso_root)}
    readme = write_readme(iso_root, meta)
    print(f"\n留痕目录: {iso_root}")
    print(f"  README: {readme}")
    for a in artifacts:
        print(f"  - {a}")
    print(f"\nDRILL {drill_n} VERDICT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1
