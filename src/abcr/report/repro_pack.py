"""abcr.report.repro_pack —— 自包含复现包出包（契约 §C2-2；R2 ④ 的主角）。

架构位置：包C·闭合验收出口。对一个已 SETTLED（最好已 AUDITED）批次出自包含复现包
`demos/repro-<batch_id>/`：原始输出 + 双判分副本 + 独立复评入口 + 逐文件哈希清单。

诚实边界（AMENDMENT-20/31）：
  · 独立复算以 A 的 rescore_copy 判分函数为主副本；B 的 scorer_copy 随包做双实现对照。
  · rescore_copy 是 A 的 src/abcr/audit/rescore.py 判分函数逐字节复制，仅把
    `from abcr.common import constants` 换为等值内联垫片（使副本 stdlib 自包含——
    出包末步空 PYTHONPATH subprocess import 自检强制之，import 失败即拒绝出包报 BLOCKER）。
  · 密钥永不进包（白名单式路径收集，绝不 cp -r 整目录——坑4）。
  · 一切数字 exploratory / rig-validation；non_citable run 在呈现里显式标注。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from abcr.report import ledgerio

PACK_VERSION = "1.0"

# 外部信任根 kind（根因①）：repro_pack 清单摘要 seal 进仓级规范锚存储（external_seal）。
KIND_REPRO_PACK = "repro_pack"

# README 诚实条款（§C2-2 逐字写入，不许改写）。
HONESTY_CLAUSE = (
    "> 本项目承诺的复现 = ① 工件级（原始输出永久保存，任何再分析不依赖重新生成）"
    "+ ② 统计级（同 config 重跑，聚合指标在自身抽样波动内一致）+ ③ 单机确定级"
    "（同机同环境 temp 0 双跑一致）。**不承诺跨硬件 bit 级一致**——浮点归约序差异是"
    "行业已知事实，声称 bit 级可复现反而不诚实。本包一切数字为 exploratory / "
    "rig-validation 性质，mini 环产出不构成任何假设的证据。"
)

_FILE_COUNT_TOKEN = "__FILE_COUNT__"


# ----------------------------------------------------------------------------- helpers
def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _git_commit(repo_root: Path) -> str:
    try:
        r = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 — 出包不因 git 缺失而失败
        return "unknown"


def _run_ids_of_batch(ledger_dir: Path, batch_id: str) -> list[str]:
    """经 runs_index 的 run_registered(batch_id) 折叠该批 run（AMENDMENT-19；含云链段）。"""
    events = ledgerio.read_chain_merged(ledger_dir, "runs_index")
    seen, out = set(), []
    for ev in events:
        if ev.get("event") == "run_registered" and ev.get("batch_id") == batch_id:
            rid = ev.get("subject_id")
            if rid and rid not in seen:
                seen.add(rid)
                out.append(rid)
    return out


def _find_envelope(repo_root: Path, batch_id: str) -> Path | None:
    cand = repo_root / "configs" / "envelopes" / f"{batch_id}.json"
    if cand.exists():
        return cand
    # 后备：R1 fixture 批的信封原件在 fixtures/（batch_id 对得上才用）。
    fx = repo_root / "fixtures" / "envelope_fixture.json"
    if fx.exists():
        try:
            if json.loads(fx.read_text(encoding="utf-8")).get("batch_id") == batch_id:
                return fx
        except Exception:  # noqa: BLE001
            pass
    return None


def _load_scores(run_dir: Path) -> list[dict]:
    p = run_dir / "scores.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ----------------------------------------------------------------------------- tool copies
def _gen_rescore_copy() -> str:
    """A 的 rescore.py 判分函数逐字节复制 + constants 等值内联垫片（自包含）。
    源文件位置经导入模块 __file__ 定位（与数据 repo_root 解耦）。"""
    from abcr.audit import rescore as _rescore
    from abcr.common import constants
    src = Path(_rescore.__file__).read_text(encoding="utf-8")
    import_line = "from abcr.common import constants\n"
    if import_line not in src:
        raise RuntimeError(
            "BLOCKER: A 的 rescore.py 未见 `from abcr.common import constants` 导入行——"
            "自包含垫片替换点漂移，出包中止（AMENDMENT-20 fail-closed）。")
    shim = (
        "# --- standalone shim（AMENDMENT-20 自包含副本）：以下命名空间原由\n"
        "#     `from abcr.common import constants` 提供，出包时按冻结值等值内联，\n"
        "#     令本副本 stdlib 自包含（空 PYTHONPATH 可 import）；判分函数逐字节复制。\n"
        "class constants:  # noqa: N801 — 内联垫片，保持 `constants.X` 引用逐字不变\n"
        f"    HEDGING_WORDS = {constants.HEDGING_WORDS!r}\n"
        f"    SELF_CHECK_MARKERS = {constants.SELF_CHECK_MARKERS!r}\n"
        f"    SENTENCE_SEPARATORS = {constants.SENTENCE_SEPARATORS!r}\n"
    )
    return src.replace(import_line, shim, 1)


def _gen_scorer_copy() -> str:
    """B 的 scorer.py 逐字节复制（已 stdlib 自包含，第二副本双实现对照）。"""
    from abcr.rig import scorer as _scorer
    return Path(_scorer.__file__).read_text(encoding="utf-8")


# rescore_standalone.py：stdlib + 同目录两副本，绝不 import abcr。逐字随包（AMENDMENT-20）。
# fail-closed 加固（R2 ②③④）：① 空集判 FAIL 而非满分（agr None + 实质证据地板）；
# ② 清单反查未申报文件（堵未申报 __pycache__/.pyc 影子）；③ 路径类型白名单——清单/盘上
#    出现任何 .pyc/.pyo/.so/__pycache__ 一律判污染（合法包永不含字节码，出包侧 -B 保证），
#    堵住"把对齐的影子 pyc 申报进重生成清单"这一变体；④ 两副本不走 import 机制，改为对
#    【已核验的源码字节】当场重核 sha256 后 compile+exec——被核验的 .py 就是被执行的那份，
#    结构上不存在任何 pyc 缓存通路。
_STANDALONE_SRC = r'''#!/usr/bin/env python3
"""复现包独立复评入口（stdlib + 同目录 rescore_copy/scorer_copy；不 import abcr 包）。

流程（AMENDMENT-20 + R2 加固）：
  1. 按 pack_manifest.json 逐文件核 sha256（正向）+ 反查包内实际文件是否全被清单管辖
     （反向：未申报文件=污染）+ 路径类型白名单（任何 .pyc/.pyo/.so/__pycache__ 无论是否
     申报一律判污染）——任一不符报污染、退出码 2；
  2. 两副本不走 import：读源码字节 → 当场重核 sha256（防核验后被换）→ compile+exec，
     绝不经过 import 机制，故任何 .pyc 缓存（含"已申报且 mtime/size 对齐"的影子）都无法
     被执行；被核验的 .py 就是被执行的那份；
  3. 遍历 runs/*/steps.jsonl → 以 A 的 rescore_copy 判分函数为主重算全部确定性指标；
  4. 与 scores.jsonl 中 scorer_id ∈ {deterministic_v1(B), rescore_v1(A)} 两组分数
     逐 (run_id,item_id,step_id,seed,metric) 分别对比 → 各组一致率（空集=None，判 FAIL）；
  5. 需有实质复算（recompute_triples>0 且两组一致率均定义且==1.0）方判 PASS；
  6. judge 指标（trait_score 等）非确定性，不在复算范围。
"""
import argparse
import hashlib
import json
import sys
import types
from pathlib import Path

sys.dont_write_bytecode = True  # 不落 .pyc：包内文件集恒与清单一致，杜绝 __pycache__ 影子

RECOMPUTE_SCORERS = ("deterministic_v1", "rescore_v1")

# 路径类型门（白名单式）：合法复现包只含【源码与数据】。任何字节码/原生扩展一律拒绝——
# 无论它是否被申报进清单。攻击变体"伪造 mtime/size 对齐的 .pyc + 重生成清单把它申报进去"
# 正是靠"已申报即合法"绕过反查的；此处按路径形状拒绝，与申报与否无关。
DENY_SUFFIXES = (".pyc", ".pyo", ".pyd", ".so", ".dylib", ".dll")
DENY_DIR_PARTS = ("__pycache__",)
ALLOW_SUFFIXES = (".py", ".json", ".jsonl", ".md", ".txt", ".png", ".npz",
                  ".csv", ".yaml", ".yml", ".toml", ".svg", ".log")


def _path_type_violation(rel):
    """返回污染原因字符串；合规返回 None。rel 为包内相对路径字符串。"""
    p = Path(rel)
    for part in p.parts:
        if part in DENY_DIR_PARTS:
            return "字节码目录(__pycache__)——合法包永不含字节码"
    suf = p.suffix.lower()
    if suf in DENY_SUFFIXES:
        return f"字节码/原生扩展({suf})——合法包永不含字节码"
    if suf not in ALLOW_SUFFIXES:
        return f"非白名单文件类型({suf or '无后缀'})——只允许源码与数据"
    return None


def _load_jsonl(p):
    return [json.loads(ln) for ln in Path(p).read_text(encoding="utf-8").splitlines() if ln.strip()]


def _exec_verified_module(pack, rel, name, declared_sha):
    """按【已核验的源码字节】compile+exec 成模块——不经 import 机制，故永不读 .pyc。

    读到的字节当场重核 sha256（防清单核验与执行之间被换），核过的正是被 exec 的那份。
    """
    src_p = pack / rel
    src = src_p.read_bytes()
    got = hashlib.sha256(src).hexdigest()
    if got != declared_sha:
        raise RuntimeError(f"{rel}: 执行前重核 sha256 不符（期望{declared_sha} 实得{got}）")
    mod = types.ModuleType(name)
    mod.__file__ = str(src_p)
    sys.modules[name] = mod
    exec(compile(src, str(src_p), "exec"), mod.__dict__)
    return mod


def _verify_manifest(pack: Path, report_rel):
    man = json.loads((pack / "pack_manifest.json").read_text(encoding="utf-8"))
    declared = {f["path"] for f in man["files"]}
    bad = []
    # 正向：清单每条都在盘且 sha256 相符 + 路径类型合规（申报了也不放行字节码）。
    for f in man["files"]:
        why = _path_type_violation(f["path"])
        if why:
            bad.append((f["path"], f"清单声明了被禁类型: {why}", "-", "已申报"))
            continue
        fp = pack / f["path"]
        if not fp.exists():
            bad.append((f["path"], "缺失", f["sha256"], "-"))
            continue
        got = hashlib.sha256(fp.read_bytes()).hexdigest()
        if got != f["sha256"]:
            bad.append((f["path"], "sha256不符", f["sha256"], got))
    # 反向：包内每个实际文件都必须被清单管辖。清单只承诺它列举的文件，故"申报外文件"
    # 是核验盲区——已核验的 rescore_copy.py 可被同名 __pycache__/*.pyc 影子在 import 时
    # 顶替。此处把任何未申报文件判污染，配合"核验后才 import"彻底堵死影子替换。
    exclude = {"pack_manifest.json"}
    if report_rel:
        exclude.add(report_rel)
    for p in sorted(pack.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(pack))
        # 路径类型门先于 exclude：字节码/非白名单文件在盘即污染，与申报、与豁免无关。
        why = _path_type_violation(rel)
        if why and rel not in exclude:
            bad.append((rel, f"被禁类型在盘: {why}", "-", "在盘"))
            continue
        if rel in exclude:
            continue
        if rel not in declared:
            bad.append((rel, "未申报(疑影子/夹带文件)", "-", "在盘"))
    return man, bad


def _num_eq(a, b):
    try:
        return abs(float(a) - float(b)) <= 1e-9
    except (TypeError, ValueError):
        return a == b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True, help="复现包根目录")
    ap.add_argument("--report", required=True, help="复评报告输出 json")
    args = ap.parse_args()
    pack = Path(args.pack).resolve()

    # 报告输出文件自身不受清单管辖（首跑尚未生成；重跑时的旧报告不应被当污染）。
    report_abs = Path(args.report)
    if not report_abs.is_absolute():
        report_abs = Path.cwd() / report_abs
    try:
        report_rel = str(report_abs.resolve().relative_to(pack))
    except ValueError:
        report_rel = None

    man, bad = _verify_manifest(pack, report_rel)
    if bad:
        rep = {"integrity_ok": False, "verdict": "FAIL",
               "verdict_reasons": ["完整性/污染核验失败"],
               "contamination": [
                   {"path": p, "reason": r, "expected": e, "got": g} for p, r, e, g in bad]}
        Path(args.report).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print("完整性核验失败（污染）：", len(bad), "个文件不符/未申报", file=sys.stderr)
        for p, r, e, g in bad:
            print(f"  {p}: {r}", file=sys.stderr)
        return 2

    # 两副本：不 import（import 会优先吃 __pycache__ 里的 .pyc），改为对已核验源码字节
    # 当场重核 sha256 后 compile+exec。被核验的 .py 就是被执行的那份。
    sha_by_path = {f["path"]: f["sha256"] for f in man["files"]}
    try:
        rescore_copy = _exec_verified_module(
            pack, "tools/rescore_copy.py", "rescore_copy", sha_by_path["tools/rescore_copy.py"])
        scorer_copy = _exec_verified_module(
            pack, "tools/scorer_copy.py", "scorer_copy", sha_by_path["tools/scorer_copy.py"])
    except (KeyError, RuntimeError) as e:
        rep = {"integrity_ok": False, "verdict": "FAIL",
               "verdict_reasons": [f"判分副本加载失败（源码未受清单管辖或执行前重核失配）: {e}"],
               "contamination": [{"path": "tools/rescore_copy.py", "reason": str(e),
                                  "expected": "-", "got": "-"}]}
        Path(args.report).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"判分副本加载失败：{e}", file=sys.stderr)
        return 2
    _ = scorer_copy

    # 重算：以 A 的 rescore_copy 为主副本
    recomputed = {}   # (run_id,item_id,step_id,seed,metric) -> value
    runs_root = pack / "runs"
    for steps_p in sorted(runs_root.glob("*/steps.jsonl")):
        for st in _load_jsonl(steps_p):
            for row in rescore_copy.rescore_step(st):
                key = (row["run_id"], row["item_id"], row["step_id"],
                       row["random_seed"], row["metric_name"])
                recomputed[key] = row["metric_value"]

    # 逐 scorer 组比对
    groups = {s: {"total": 0, "matched": 0, "mismatch": []} for s in RECOMPUTE_SCORERS}
    triples = set()
    for scores_p in sorted(runs_root.glob("*/scores.jsonl")):
        for r in _load_jsonl(scores_p):
            sid = r.get("scorer_id")
            if sid not in RECOMPUTE_SCORERS:
                continue
            key = (r.get("run_id"), r.get("item_id"), r.get("step_id"),
                   r.get("random_seed"), r.get("metric_name"))
            if key not in recomputed:
                continue   # 该指标不在 rescore_copy 复算范围（judge 等）
            g = groups[sid]
            g["total"] += 1
            triples.add((r.get("run_id"), r.get("item_id"), r.get("metric_name")))
            if _num_eq(recomputed[key], r.get("metric_value")):
                g["matched"] += 1
            else:
                g["mismatch"].append({
                    "run_id": key[0], "item_id": key[1], "step_id": key[2],
                    "seed": key[3], "metric": key[4], "scorer_id": sid,
                    "expected_recompute": recomputed[key], "got_scores": r.get("metric_value")})

    def agr(s):
        g = groups[s]
        # total==0 → None（证据不足，绝不 1.0）："零对比零分歧" 不等于 "完全一致"。
        return (g["matched"] / g["total"]) if g["total"] else None

    agreements = {s: agr(s) for s in RECOMPUTE_SCORERS}
    all_mm = groups["deterministic_v1"]["mismatch"] + groups["rescore_v1"]["mismatch"]

    # 实质证据地板 + 全组一致率门（None/≠1.0/有不一致 → FAIL）：把"空集走完全程拿满分"掐断。
    reasons = []
    if len(triples) == 0:
        reasons.append("无实质复算：0 个 (run,item,metric) 三元组被复算比对")
    for s in RECOMPUTE_SCORERS:
        a = agreements[s]
        if a is None:
            reasons.append(f"{s}: 无可比对分数，一致率未定义（证据不足）")
        elif a != 1.0:
            reasons.append(f"{s}: 一致率 {a} != 1.0")
    if all_mm:
        reasons.append(f"{len(all_mm)} 条判分不一致")

    rep = {
        "integrity_ok": True,
        "files_verified": len(man["files"]),
        "recompute_triples": len(triples),
        "agreement_deterministic_v1": agreements["deterministic_v1"],
        "agreement_rescore_v1": agreements["rescore_v1"],
        "compared": {s: groups[s]["total"] for s in RECOMPUTE_SCORERS},
        "mismatches": all_mm,
        "verdict": "PASS" if not reasons else "FAIL",
        "verdict_reasons": reasons,
    }
    Path(args.report).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"integrity_ok=True files={rep['files_verified']} triples={rep['recompute_triples']} "
          f"verdict={rep['verdict']}")
    print(f"agreement_deterministic_v1={rep['agreement_deterministic_v1']} "
          f"agreement_rescore_v1={rep['agreement_rescore_v1']}")
    if rep["verdict"] != "PASS":
        print("复评 FAIL，原因：", file=sys.stderr)
        for why in reasons:
            print(f"  - {why}", file=sys.stderr)
        for m in all_mm:
            print(f"  不一致 {m['run_id']} {m['item_id']} {m['metric']} ({m['scorer_id']}): "
                  f"期望{m['expected_recompute']} 实得{m['got_scores']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


# ----------------------------------------------------------------------------- figure
def _make_figure(out_png: Path, run_meta: list[dict]) -> None:
    """双联图（AMENDMENT-31）：左=三臂逐 seed is_correct 均值点图；右=每臂 output_len_tokens 分布。
    数据出自各 run 的 scores（is_correct 优先 deterministic_v1，长度取 rescore_v1）。图注含
    "rig-validation, not evidence"。任何数据缺失都产占位图而不让出包失败。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 归拢：condition -> {seed: mean_is_correct}, condition -> [len_tokens...]
    by_cond_correct: dict[str, dict] = {}
    by_cond_len: dict[str, list] = {}
    for rm in run_meta:
        cond = rm["condition"] or "?"
        scores = rm["scores"]
        ic = [r["metric_value"] for r in scores
              if r.get("metric_name") == "is_correct" and r.get("scorer_id") == "deterministic_v1"]
        if not ic:
            ic = [r["metric_value"] for r in scores if r.get("metric_name") == "is_correct"]
        seed = rm["seed"]
        if ic:
            by_cond_correct.setdefault(cond, {})[seed] = sum(ic) / len(ic)
        lens = [r["metric_value"] for r in scores if r.get("metric_name") == "output_len_tokens"]
        if lens:
            by_cond_len.setdefault(cond, []).extend(lens)

    fig, (axl, axr) = plt.subplots(1, 2, figsize=(11, 4.2))
    conds = sorted(set(by_cond_correct) | set(by_cond_len)) or ["(无数据)"]
    xpos = {c: i for i, c in enumerate(conds)}
    # 左：逐 seed 均值点
    for c in conds:
        for seed, mean in sorted(by_cond_correct.get(c, {}).items()):
            axl.scatter(xpos[c], mean, s=60, alpha=0.75)
            axl.annotate(f"s{seed}", (xpos[c], mean), fontsize=7,
                         xytext=(4, 2), textcoords="offset points")
    axl.set_xticks(list(xpos.values()))
    axl.set_xticklabels(conds, rotation=20, ha="right", fontsize=8)
    axl.set_ylabel("is_correct mean (per seed)")
    axl.set_ylim(-0.05, 1.05)
    axl.set_title("Per-arm accuracy (each seed a point)")
    # 右：output_len_tokens 分布（箱线）
    data = [by_cond_len.get(c, []) for c in conds]
    if any(data):
        axr.boxplot([d or [0] for d in data], tick_labels=conds)
    axr.set_xticklabels(conds, rotation=20, ha="right", fontsize=8)
    axr.set_ylabel("output_len_tokens")
    axr.set_title("Per-arm output length dist.")
    fig.suptitle("rig-validation, not evidence — exploratory / non-citable", fontsize=10)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=110)
    plt.close(fig)


# ----------------------------------------------------------------------------- docs
def _readme(batch_id: str, run_ids: list[str], any_non_citable: bool) -> str:
    nc = ("\n> ⚠ 本包含 `non_citable: true` 的 run（Mac dev 档）——一切呈现均按 non-citable 处理。"
          if any_non_citable else "")
    return "\n".join([
        f"# 复现包 · {batch_id}",
        "",
        "## 诚实条款",
        HONESTY_CLAUSE + nc,
        "",
        "## 复评（独立复算，无需原仓库/权重）",
        "```bash",
        "python tools/rescore_standalone.py --pack . --report rescore_report.json",
        "```",
        "从 `runs/*/steps.jsonl` 的 output_text 以 A 的 rescore_copy 判分函数重算全部确定性指标，"
        "并与 scores.jsonl 的 deterministic_v1（B）/ rescore_v1（A）两组分数分别对比；"
        "预期两组一致率均 == 1.0。judge 指标（trait_score 等）非确定性，不在复算范围。",
        "",
        "## 复跑（需原仓库与模型权重——包内不含权重）",
        "复跑指向原仓库 B 的 dispatch，config 原件见 `configs/`：",
        "```bash",
        "# 在原仓库根（需 .venv312 + 模型权重）：",
        "PYTHONPATH=src python -m abcr.ops.dispatch --envelope configs/<batch_id>.json ...",
        "```",
        "本包只保证工件级/统计级/单机确定级复现；复跑生成需要原仓库环境与权重，故与复评分列。",
        "",
        "## 内容",
        f"- runs: {len(run_ids)} 个（`runs/<run_id>/{{manifest.json,steps.jsonl,scores.jsonl}}`）",
        "- configs/：信封原件 + 逐 run config",
        "- activations/：10% 抽样激活摘要 npz（如有）",
        "- figures/main.png：双联图（rig-validation, not evidence）",
        "- tools/：rescore_copy.py（A 主副本）+ scorer_copy.py（B 双实现对照）+ rescore_standalone.py",
        "- pack_manifest.json：逐文件 sha256 + bytes",
        "- ACCEPTANCE.md：闭合验收协议（全新会话仅凭本包复算的完整指令书）",
        "",
    ]) + "\n"


def _acceptance(batch_id: str, run_ids: list[str], file_count_token: str) -> str:
    """C2-3 闭合验收协议模板实例化（batch_id / 文件数 / 预期一致率）。"""
    return "\n".join([
        f"# 闭合验收协议 · {batch_id}",
        "",
        "> 本文件是给「**只拿到本目录的全新会话**」的完整指令书（R2 ④）。逐步执行，全程不回读原仓库。",
        "",
        "## 1. 前提声明",
        "你（验收会话）只拥有本目录。**禁止**访问原仓库、shared-brain、网络；一切依据 = 包内文件。",
        "本包一切数字为 exploratory / rig-validation，non_citable，不构成任何科学结论。",
        "",
        "## 2. 完整性核验（逐文件对 pack_manifest.json 核 sha256）",
        "```bash",
        "python -c \"import json,hashlib,pathlib; m=json.load(open('pack_manifest.json')); "
        "bad=[f['path'] for f in m['files'] if hashlib.sha256(pathlib.Path(f['path']).read_bytes())"
        ".hexdigest()!=f['sha256']]; print('完整性:', 'PASS' if not bad else ('FAIL '+str(bad)))\"",
        "```",
        f"预期：PASS（本包共 {file_count_token} 个受清单管辖文件）。",
        "",
        "## 3. 独立复算",
        "```bash",
        "python tools/rescore_standalone.py --pack . --report rescore_report.json",
        "```",
        "以 A 的 rescore_copy 重算全部确定性指标，对 deterministic_v1 与 rescore_v1 分别对比"
        "（AMENDMENT-20）。**预期两组一致率均 == 1.0，且复算三元组数 recompute_triples > 0**"
        "（空集/零复算判 FAIL，绝不判满分）。任何不一致逐条列 "
        "(run_id, item_id, metric, scorer_id, 期望, 实得)。",
        "",
        "## 4. 判定",
        "**完整性核验通过 且 有实质复算(recompute_triples > 0) 且 两组一致率均 == 1.0"
        "(None/未定义判 FAIL) 且 无任何不一致 = PASS**；否则 **FAIL** 并原样报告"
        "（不许「大体一致」措辞）。rescore_report.json 的 `verdict` 字段即上述判定的机读结论。",
        "",
        "## 5. 报告格式",
        "PASS/FAIL + 核验文件数 + 复算覆盖 (run,item,metric) 三元组数 + 不一致清单 + "
        "验收会话环境（python 版本、平台）。",
        "",
        "```bash",
        "python -c \"import json,platform,sys; r=json.load(open('rescore_report.json')); "
        "ok=(r.get('verdict')=='PASS' and r.get('integrity_ok') and "
        "r.get('recompute_triples',0)>0 and r.get('agreement_deterministic_v1')==1.0 and "
        "r.get('agreement_rescore_v1')==1.0 and not r.get('mismatches')); "
        "print(('PASS' if ok else 'FAIL'), '| files', r.get('files_verified'), "
        "'| triples', r.get('recompute_triples'), "
        "'| det', r.get('agreement_deterministic_v1'), 'resc', r.get('agreement_rescore_v1'), "
        "'| verdict', r.get('verdict'), '| reasons', r.get('verdict_reasons'), "
        "'| env', sys.version.split()[0], platform.platform())\"",
        "```",
        "",
        f"批次 run 数：{len(run_ids)}。",
        "",
    ]) + "\n"


# ----------------------------------------------------------------------------- pack
def _collect_files(pack_dir: Path) -> list[dict]:
    """遍历包内全部文件（除 pack_manifest.json），产 [{path,sha256,bytes}]，path 相对包根、排序。"""
    files = []
    for p in sorted(pack_dir.rglob("*")):
        if not p.is_file() or p.name == "pack_manifest.json":
            continue
        b = p.read_bytes()
        files.append({"path": str(p.relative_to(pack_dir)), "sha256": _sha256_bytes(b), "bytes": len(b)})
    return files


def _self_check(tools_dir: Path) -> None:
    """出包末步（AMENDMENT-20）：空 PYTHONPATH subprocess import 两副本，验 stdlib 自包含。
    import 失败即拒绝出包并报 BLOCKER。"""
    # PYTHONPATH 置空 → abcr 不可达，真验自包含；-B / PYTHONDONTWRITEBYTECODE 防在包内
    # tools/ 落 __pycache__（否则该 .pyc 未被 pack_manifest 管辖，会触发 standalone 反查污染）。
    env = {**os.environ, "PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, "-B", "-c", "import rescore_copy, scorer_copy"],
                       cwd=str(tools_dir), env=env, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(
            "BLOCKER: 出包自检失败——两副本非 stdlib 自包含（空 PYTHONPATH import 失败）。\n"
            f"stderr:\n{r.stderr}\n"
            "契约冻结「判分副本 stdlib 自包含」被违反，拒绝出包（AMENDMENT-20 fail-closed）。")


def pack(batch_id: str, out_root: Path = Path("demos"),
         repo_root: Path = Path("."), ledger_dir: Path | None = None) -> Path:
    """对 batch_id 出自包含复现包 demos/repro-<batch_id>/。返回包目录。

    失败路径（fail-closed）：无 run / 无信封 / 自检不过 → raise（后两者删半成品包）。
    """
    repo_root = Path(repo_root).resolve()
    ledger_dir = Path(ledger_dir) if ledger_dir else repo_root / "ledger"
    runs_root = repo_root / "data" / "runs"

    run_ids = _run_ids_of_batch(ledger_dir, batch_id)
    if not run_ids:
        raise RuntimeError(f"BLOCKER: 账本中 batch {batch_id} 无 run_registered，无可出包 run")
    envelope_p = _find_envelope(repo_root, batch_id)
    if envelope_p is None:
        raise RuntimeError(f"BLOCKER: 未找到 batch {batch_id} 的信封原件"
                           f"（configs/envelopes/{batch_id}.json 或 fixtures/envelope_fixture.json）")

    pack_dir = Path(out_root) / f"repro-{batch_id}"
    if pack_dir.exists():
        import shutil
        shutil.rmtree(pack_dir)
    (pack_dir / "configs").mkdir(parents=True)
    (pack_dir / "tools").mkdir(parents=True)

    # --- configs：信封原件 + 逐 run config（从 manifest.config 抽） ---
    (pack_dir / "configs" / envelope_p.name).write_bytes(envelope_p.read_bytes())
    any_non_citable = False
    run_meta = []
    for rid in run_ids:
        rd = runs_root / rid
        dst = pack_dir / "runs" / rid
        dst.mkdir(parents=True)
        manifest = {}
        for fname in ("manifest.json", "steps.jsonl", "scores.jsonl"):
            src = rd / fname
            if src.exists():
                (dst / fname).write_bytes(src.read_bytes())   # 白名单式收集（坑4）
        mp = rd / "manifest.json"
        if mp.exists():
            manifest = json.loads(mp.read_text(encoding="utf-8"))
            if manifest.get("non_citable"):
                any_non_citable = True
            cfg = manifest.get("config")
            if cfg is not None:
                (pack_dir / "configs" / f"config-{rid}.json").write_text(
                    json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # activations（如有）——整目录只收 .npz（白名单式）
        act_src = rd / "activations"
        if act_src.exists():
            act_dst = pack_dir / "activations" / rid
            act_dst.mkdir(parents=True)
            for npz in sorted(act_src.glob("*.npz")):
                (act_dst / npz.name).write_bytes(npz.read_bytes())
        scores = _load_scores(rd)
        seed = None
        if manifest.get("config"):
            seed = manifest["config"].get("random_seed")
        if seed is None:
            seeds = {r.get("random_seed") for r in scores if r.get("random_seed") is not None}
            seed = next(iter(seeds)) if len(seeds) == 1 else "?"
        conds = {r.get("condition") for r in scores if r.get("condition")}
        cond = next(iter(conds)) if len(conds) == 1 else (manifest.get("config", {}).get("condition"))
        run_meta.append({"run_id": rid, "condition": cond, "seed": seed, "scores": scores})

    # --- env ---
    (pack_dir / "env").mkdir()
    try:
        freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"],
                                capture_output=True, text=True, timeout=60).stdout
    except Exception:  # noqa: BLE001
        freeze = "(pip freeze 失败)\n"
    (pack_dir / "env" / "requirements.lock.txt").write_text(freeze, encoding="utf-8")
    versions = {"python": platform.python_version(), "platform": platform.platform(),
                "git_commit": _git_commit(repo_root), "duckdb": None, "torch": None}
    for mod in ("duckdb", "torch"):
        try:
            versions[mod] = __import__(mod).__version__
        except Exception:  # noqa: BLE001
            versions[mod] = None
    (pack_dir / "env" / "versions.json").write_text(
        json.dumps(versions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # --- figures ---
    _make_figure(pack_dir / "figures" / "main.png", run_meta)

    # --- tools（两副本 + standalone）+ 出包末步自检 ---
    (pack_dir / "tools" / "rescore_copy.py").write_text(_gen_rescore_copy(), encoding="utf-8")
    (pack_dir / "tools" / "scorer_copy.py").write_text(_gen_scorer_copy(), encoding="utf-8")
    (pack_dir / "tools" / "rescore_standalone.py").write_text(_STANDALONE_SRC, encoding="utf-8")

    # --- docs ---
    (pack_dir / "README.md").write_text(_readme(batch_id, run_ids, any_non_citable), encoding="utf-8")
    (pack_dir / "ACCEPTANCE.md").write_text(
        _acceptance(batch_id, run_ids, _FILE_COUNT_TOKEN), encoding="utf-8")

    # --- pack_manifest（清单不含自身；文件数 = 清单条目数，回填 ACCEPTANCE 占位）---
    files = _collect_files(pack_dir)   # ACCEPTANCE 已在盘（计入总数），占位符不改文件计数
    acc_p = pack_dir / "ACCEPTANCE.md"
    acc_p.write_text(acc_p.read_text(encoding="utf-8").replace(_FILE_COUNT_TOKEN, str(len(files))),
                     encoding="utf-8")
    files = _collect_files(pack_dir)   # ACCEPTANCE 内容已定，重算清单哈希（文件数不变）

    # --- 外部信任根（根因①）：把"逐文件哈希清单"的全链摘要 seal 进仓级规范锚存储 ---
    # pack_manifest 本身是自签自证（清单内含各文件 sha256）——链内自洽 ≠ 链外可信：
    # 攻击者整包重生成（一致重算全部 sha256）仍能过 standalone 内部核验。外部锚把
    # 「chain_digest_and_length(files)」写到 pack 之外的规范锚存储，能追加锚者才在信任
    # 边界内；审计端 verify_pack_external_seal 重算 files 摘要只与外部锚比对（root ④ 接线，
    # 非只写文档）。standalone(stdlib) 够不到外部锚，故此为治理/审计侧的额外信任根校验。
    from abcr.common import external_seal
    anchor_digest, anchor_length = external_seal.chain_digest_and_length(files)
    _env_set = False
    if not os.environ.get(external_seal.ANCHOR_STORE_ENV):
        # 锚存储归属被打包的数据仓 repo_root（生产即工作树本身）；未指定隔离路径时落此。
        os.environ[external_seal.ANCHOR_STORE_ENV] = str(repo_root / "anchors" / "seals.jsonl")
        _env_set = True
    try:
        seal_rec = external_seal.seal(
            KIND_REPRO_PACK, batch_id, anchor_digest, anchor_length,
            extra={"pack_dir": f"repro-{batch_id}", "n_files": len(files),
                   "git_commit": _git_commit(repo_root)})
    finally:
        if _env_set:
            del os.environ[external_seal.ANCHOR_STORE_ENV]

    manifest_obj = {
        "pack_version": PACK_VERSION,
        "batch_id": batch_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(repo_root),
        "run_ids": run_ids,
        "files": files,
        "labels": ["exploratory", "rig-validation"],
        "commitments": {
            "artifact_level": True, "statistical_level": True,
            "single_machine_deterministic": True, "cross_hardware_bit_level": False},
        # 外部锚指针（便利副本）——权威在规范锚存储；审计端以 chain_digest_and_length(files)
        # 重算后与外部锚比对，不信任本内嵌 digest（改内嵌值不改判定）。
        "external_anchor": {
            "store_relpath": "anchors/seals.jsonl",
            "kind": KIND_REPRO_PACK,
            "subject_id": batch_id,
            "digest": anchor_digest,
            "length": anchor_length,
            "sealed_ts": seal_rec.get("ts"),
        },
    }
    (pack_dir / "pack_manifest.json").write_text(
        json.dumps(manifest_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # --- 出包末步自检（AMENDMENT-20）：失败删半成品包并抛 BLOCKER ---
    try:
        _self_check(pack_dir / "tools")
        # 外部锚强制门（root ①·接线）：出包收口即以审计端同一函数重算 files 摘要并与
        # 规范锚存储比对。verify_pack_external_seal 因此在生产路径上被真实执行，不是
        # 只供文档引用的死代码；缺锚/digest/length 任一不符 → 删包 raise（fail-closed）。
        ok, why = verify_pack_external_seal(pack_dir, repo_root)
        if not ok:
            raise RuntimeError(f"BLOCKER: 出包外部锚校验失败（{why}）——清单摘要与规范锚"
                               f"存储不符，拒绝交付该包。")
        # 出包侧同样执行 standalone 的路径类型门：包内绝不允许字节码/非白名单文件外流。
        _assert_no_bytecode(pack_dir, files)
    except RuntimeError:
        import shutil
        shutil.rmtree(pack_dir, ignore_errors=True)
        raise
    return pack_dir


# standalone 内嵌的同一套白名单/黑名单（单一权威：从 _STANDALONE_SRC 的常量行解析，
# 杜绝生产侧与包内验证侧出现"平行副本各改一遍"的漂移）。
def _standalone_path_policy() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    # 直接 exec standalone 源里的常量段（纯字面量，无副作用）——策略只有一处定义。
    ns: dict = {}
    src = _STANDALONE_SRC
    start = src.index("DENY_SUFFIXES")
    end = src.index("def _path_type_violation")
    exec(compile(src[start:end], "<standalone-policy>", "exec"), ns)
    return ns["DENY_SUFFIXES"], ns["DENY_DIR_PARTS"], ns["ALLOW_SUFFIXES"]


def _assert_no_bytecode(pack_dir: Path, files: list[dict]) -> None:
    """出包侧路径类型门：策略常量取自 _STANDALONE_SRC（单一权威定义），不另建副本。"""
    deny_suf, deny_dirs, allow_suf = _standalone_path_policy()
    bad = []
    for rel in [f["path"] for f in files] + [
            str(p.relative_to(pack_dir)) for p in pack_dir.rglob("*") if p.is_file()]:
        rp = Path(rel)
        if rp.name == "pack_manifest.json":
            continue
        if any(part in deny_dirs for part in rp.parts) or rp.suffix.lower() in deny_suf:
            bad.append(rel)
        elif rp.suffix.lower() not in allow_suf:
            bad.append(rel)
    if bad:
        raise RuntimeError("BLOCKER: 出包含字节码/非白名单文件（standalone 会判污染）："
                           + ", ".join(sorted(set(bad))[:10]))


def verify_pack_external_seal(pack_dir: Path,
                              repo_root: Path | None = None) -> tuple[bool, str]:
    """审计/治理端（有 abcr + 规范锚存储访问）：重算包清单摘要，只与外部锚比对。

    fail-closed（root ①）：缺锚 / length 或 digest 不符 → (False, reason)。standalone
    (stdlib) 够不到外部锚，故此校验是 pack 内部核验之外的独立信任根。

    - digest/length 由 chain_digest_and_length(man['files']) 重算，绝不信任 manifest
      内嵌的 external_anchor.digest（那是便利指针，改它不改判定）。
    - repo_root 给定且未设 ABCR_ANCHOR_STORE 时，锚存储取 <repo_root>/anchors/seals.jsonl
      （与出包端一致）；否则遵从环境变量。
    """
    from abcr.common import external_seal
    pack_dir = Path(pack_dir)
    man = json.loads((pack_dir / "pack_manifest.json").read_text(encoding="utf-8"))
    files = man.get("files", [])
    digest, length = external_seal.chain_digest_and_length(files)
    anchor = man.get("external_anchor") or {}
    kind = anchor.get("kind", KIND_REPRO_PACK)
    subject = anchor.get("subject_id") or man.get("batch_id")
    if not subject:
        return False, "manifest 缺 external_anchor.subject_id/batch_id，无法定位外部锚"
    _env_set = False
    if repo_root is not None and not os.environ.get(external_seal.ANCHOR_STORE_ENV):
        os.environ[external_seal.ANCHOR_STORE_ENV] = str(
            Path(repo_root).resolve() / "anchors" / "seals.jsonl")
        _env_set = True
    try:
        return external_seal.verify(kind, subject, digest, length)
    finally:
        if _env_set:
            del os.environ[external_seal.ANCHOR_STORE_ENV]


def main() -> int:
    ap = argparse.ArgumentParser(prog="abcr.report.repro_pack", description="复现包出包（§C2-2）")
    ap.add_argument("--batch", required=True, help="批次 batch_id（B-...）")
    ap.add_argument("--out", default="demos", help="出包根目录（缺省 demos/）")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--ledger-dir", default=None)
    args = ap.parse_args()
    pack_dir = pack(args.batch, Path(args.out), Path(args.repo_root),
                    Path(args.ledger_dir) if args.ledger_dir else None)
    man = json.loads((pack_dir / "pack_manifest.json").read_text(encoding="utf-8"))
    print(f"已出包: {pack_dir}（{len(man['files'])} 文件，run {len(man['run_ids'])} 个）")
    print("出包自检通过：两副本 stdlib 自包含。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
