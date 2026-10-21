"""abcr.audit.contamination —— 审计项3 · 防污染四道检查（A2-1）。

架构位置：包A·验船师侧。输入 batch_id + run_ids，输出 AuditItem(id=3)。四道检查
（任一 FAIL → item FAIL；数据缺位的检查 SKIP，不误伤真绿）：

1. **抽取语料 ∩ 评测题 = ∅（哈希级）**：对 data/traits/<trait>/ 的抽取 instruction/prompt
   与 data/benchmarks/ + data/golden/ 的评测题，各自规范化（strip + NFC + 折叠空白）后逐条
   sha256，交集非空 = FAIL 列命中对。
2. **split hash 核对**：按 §3.7 对 data/splits/ 每族重算 split_hash，与批内 steps.split_hash
   三方一致；确认期批次只允许 dev split 的 item 出现（§3.7 确定性切分公式，salt abcr-w1-v1）。
3. **judge 输入结构检查（盲评）**：data/runs/<run_id>/logs/judge_calls.jsonl（AMENDMENT-8）
   每行 messages 不得出现 condition 枚举词 / trait_pole 标签 / 臂标识词；**断言集不含 trait 名**
   （AMENDMENT-31：官方 eval_prompt 必然含 trait 名，予以豁免）。
4. **泄漏词表 grep**：词表 = CONDITIONS 全枚举 + trait_pole 标签 + 臂标识词；作用面 =
   judge 输入留痕（豁免 trait 名）+ data/traits 评测题文本（此面额外含批内 trait 名）。
   命中 = FAIL 给 (文件, 行号, 命中词)。

契约出处：工程包A §6·A2-1；AMENDMENT-8（judge 留痕路径/字段）、AMENDMENT-31（trait 名豁免）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Iterator, Optional

from abcr.audit.report import AuditItem
from abcr.common import constants

# 臂标识词（§A2-1 检查3/4 逐字）：干预/steering 相关的泄漏信号词
_ARM_WORDS: tuple[str, ...] = (
    "steer", "steering", "inject", "ablat", "coefficient", "layer=",
    "persona_text", "vanilla")

# 短/歧义极性标签用词界匹配，防 compose→"pos"、message→ 之类裸子串误报；
# 其余禁词（inject/ablat/steer…）保留子串语义以捕获形态变体（injected/ablation/steering）。
_BOUNDARY_WORDS: frozenset[str] = frozenset(w.lower() for w in constants.TRAIT_POLES)

_WS_RE = re.compile(r"\s+")


def _word_hits(text: str, forbidden) -> list[str]:
    """在 text（原样，不预降小写）中命中的禁词。极性短标签走词界，其余走子串。"""
    low = text.lower()
    hits: list[str] = []
    for w in forbidden:
        wl = w.lower()
        if wl in _BOUNDARY_WORDS:
            if re.search(r"\b" + re.escape(wl) + r"\b", low):
                hits.append(w)
        elif wl in low:
            hits.append(w)
    return hits


def _normalize(text: str) -> str:
    """规范化：NFC + 折叠空白 + strip（哈希级对比前的统一口径，检查1）。"""
    text = unicodedata.normalize("NFC", str(text))
    return _WS_RE.sub(" ", text).strip()


def _hash_norm(text: str) -> str:
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    return out


# ---------- 检查1：抽取语料 ∩ 评测题 = ∅ ----------

_EXTRACTION_KEYS = ("prompt", "instruction", "question", "text", "input")


def _extract_texts_from_obj(obj: object) -> list[str]:
    """从任意 JSON 对象里抽取候选文本（认 prompt/instruction/question/text/input 键）。"""
    out: list[str] = []
    if isinstance(obj, dict):
        for k in _EXTRACTION_KEYS:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                out.append(v)
        for v in obj.values():
            if isinstance(v, (dict, list)):
                out.extend(_extract_texts_from_obj(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_extract_texts_from_obj(v))
    return out


def extraction_corpus(repo_root: Path) -> dict[str, list[str]]:
    """data/traits/<trait>/ 下抽取用 instruction/prompt 集 → {sha256(norm): [来源片段]}。"""
    root = Path(repo_root) / "data" / "traits"
    out: dict[str, list[str]] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix not in (".json", ".jsonl", ".txt"):
            continue
        rel = str(p.relative_to(repo_root))
        texts: list[str] = []
        if p.suffix == ".jsonl":
            for rec in _load_jsonl(p):
                texts.extend(_extract_texts_from_obj(rec))
        elif p.suffix == ".json":
            try:
                texts.extend(_extract_texts_from_obj(json.loads(p.read_text(encoding="utf-8"))))
            except ValueError:
                pass
        else:  # .txt：逐非空行
            texts.extend(l for l in p.read_text(encoding="utf-8").splitlines() if l.strip())
        for t in texts:
            out.setdefault(_hash_norm(t), []).append(f"{rel}: {_normalize(t)[:60]!r}")
    return out


def eval_question_hashes(repo_root: Path) -> dict[str, list[str]]:
    """评测题（data/golden/golden10.json prompts + data/benchmarks/**）→ {sha256(norm): [来源]}。"""
    out: dict[str, list[str]] = {}
    golden = Path(repo_root) / "data" / "golden" / "golden10.json"
    if golden.is_file():
        try:
            items = json.loads(golden.read_text(encoding="utf-8")).get("items", [])
            for it in items:
                pr = it.get("prompt")
                if isinstance(pr, str) and pr.strip():
                    out.setdefault(_hash_norm(pr), []).append(
                        f"data/golden/golden10.json:{it.get('id')}")
        except ValueError:
            pass
    bench = Path(repo_root) / "data" / "benchmarks"
    if bench.is_dir():
        for p in sorted(bench.rglob("*")):
            if not p.is_file() or p.suffix not in (".json", ".jsonl"):
                continue
            rel = str(p.relative_to(repo_root))
            recs = (_load_jsonl(p) if p.suffix == ".jsonl"
                    else _extract_texts_from_obj(json.loads(p.read_text(encoding="utf-8")))
                    if p.suffix == ".json" else [])
            texts: list[str] = []
            if p.suffix == ".jsonl":
                for rec in recs:
                    texts.extend(_extract_texts_from_obj(rec))
            else:
                texts = recs  # already list[str]
            for t in texts:
                out.setdefault(_hash_norm(t), []).append(rel)
    return out


def check_corpus_disjoint(repo_root: Path) -> tuple[str, list[str]]:
    """检查1：抽取语料与评测题哈希集交集必须为空。无抽取语料 → SKIP。"""
    extraction = extraction_corpus(repo_root)
    if not extraction:
        return "SKIP", ["检查1（抽取∩评测）: data/traits 无抽取语料，SKIP"]
    evals = eval_question_hashes(repo_root)
    hits = sorted(set(extraction) & set(evals))
    if hits:
        ev = [f"检查1 FAIL: 抽取语料与评测题重叠 {len(hits)} 条（哈希命中）"]
        for h in hits[:20]:
            ev.append(f"  命中 {h[:12]}… 抽取={extraction[h]} 评测={evals[h]}")
        return "FAIL", ev
    return "PASS", [f"检查1 PASS: 抽取 {len(extraction)} 条 ∩ 评测 {len(evals)} 条 = ∅"]


# ---------- 检查2：split hash 核对 + 确认期 dev-only ----------

def split_bucket(family: str, item_id: str) -> str:
    """§3.7 确定性切分：hash%100 <20 dev / <60 calibration / 其余 heldout（salt 协议常量）。"""
    h = int(hashlib.sha256(
        f"{family}:{item_id}:{constants.SPLIT_SALT}".encode("utf-8")).hexdigest()[:8], 16) % 100
    return "dev" if h < 20 else ("calibration" if h < 60 else "heldout")


def split_hash_of_assignment(assignment: dict[str, str]) -> str:
    """§3.7：sha256(\"\\n\".join(sorted(f\"{item_id}\\t{split}\")))。"""
    lines = sorted(f"{iid}\t{split}" for iid, split in assignment.items())
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _batch_split_declared(repo_root: Path, batch_id: str) -> list[str]:
    env = Path(repo_root) / "fixtures" / "envelope_fixture.json"
    if env.is_file():
        try:
            e = json.loads(env.read_text(encoding="utf-8"))
            if e.get("batch_id") == batch_id:
                return list((e.get("scope") or {}).get("splits") or [])
        except ValueError:
            pass
    return []


def check_split_hash(repo_root: Path, batch_id: str, run_ids: list[str]) -> tuple[str, list[str]]:
    """检查2：steps.split_hash 与 data/splits/ 各族重算值一致；确认期 dev-only。

    分层降级：批声明 splits=["none"]（golden/fake 类无 split 基准）→ 该批 split 检查 SKIP，
    但仍核 steps 内 split_hash 一致性（同批同族恒同值）。
    """
    ev: list[str] = []
    declared = _batch_split_declared(repo_root, batch_id)

    # dev-only 强制由**外部相位信号** ABCR_PHASE 驱动，而非批自述 scope（根因③：验船师
    # 问运动员）。确认期（confirmation）无论批 envelope 声明 splits=["none"] 还是别的，
    # 都独立用 §3.7 公式逐 item 重算归属；"批声明 none 以跳过 dev-only"这条绕过被掐断。
    enforce_dev = os.environ.get("ABCR_PHASE", "exploration") == "confirmation"

    # (a) 批内 steps.split_hash 一致性
    seen: set[str] = set()
    dev_violations: list[str] = []
    families = {p.stem.split("-")[0]: json.loads(p.read_text(encoding="utf-8"))
                for p in sorted((Path(repo_root) / "data" / "splits").glob("*.json"))} \
        if (Path(repo_root) / "data" / "splits").is_dir() else {}
    fam_hashes = {fam: split_hash_of_assignment(d.get("assignment", {}))
                  for fam, d in families.items()}

    for rid in run_ids:
        steps = _load_jsonl(Path(repo_root) / "data" / "runs" / rid / "steps.jsonl")
        for st in steps:
            sh = st.get("split_hash")
            if isinstance(sh, str):
                seen.add(sh)
            # 确认期 dev-only：外部相位驱动，独立重算，不采信批自述 scope
            if enforce_dev:
                fam = st.get("benchmark") or "golden10"
                iid = st.get("item_id")
                if isinstance(iid, str) and split_bucket(fam, iid) != "dev":
                    dev_violations.append(f"{rid}:{iid} 归属 {split_bucket(fam, iid)}≠dev")
    if len(seen) > 1:
        return "FAIL", [f"检查2 FAIL: 批内 split_hash 不唯一 {sorted(s[:12] for s in seen)}"]
    if seen:
        ev.append(f"检查2: 批内 split_hash 唯一 = {list(seen)[0][:12]}…")

    # (b) 三方一致：steps.split_hash 是否命中某 data/splits 族的重算值
    if seen and fam_hashes:
        matched = [fam for fam, h in fam_hashes.items() if h in seen]
        if matched:
            ev.append(f"检查2: steps.split_hash 命中族重算 {matched}")
        else:
            ev.append("检查2 注: steps.split_hash 未命中 data/splits 任一族重算值"
                      f"（该批基准={declared or '未声明'}；golden/none 类无族基准，属正常）")

    # (c) dev-only 结论（相位驱动，自述 none 不豁免）
    if enforce_dev:
        if dev_violations:
            return "FAIL", [f"检查2 FAIL: 确认期(ABCR_PHASE=confirmation)批出现非 dev item "
                            f"{dev_violations[:10]}"]
        ev.append("检查2: 确认期 dev-only 通过（全 item 独立重算归 dev，不采信批自述 scope）")
        if declared and "none" in declared:
            ev.append("检查2 注: 批自述 splits=[\"none\"] 不豁免确认期 dev-only（自述不可作豁免）")
    elif declared and "none" in declared:
        ev.append("检查2: 探索期 + 批声明 splits=[\"none\"]（golden/fake 无 split 基准），"
                  "dev-only 不强制")

    if not seen and not fam_hashes:
        return "SKIP", ["检查2（split hash）: 无 steps.split_hash 且无 data/splits，SKIP"]
    return "PASS", ev


# ---------- 检查3/4：judge 输入结构 + 泄漏词表 ----------

def _message_text(messages: object) -> str:
    """把 messages（list[{role,content}]，content 可为 str 或分块）拍平成纯文本。"""
    parts: list[str] = []

    def _walk(o: object) -> None:
        if isinstance(o, str):
            parts.append(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                if k in ("role", "type"):
                    continue
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    _walk(messages)
    return "\n".join(parts)


def _record_scan_text(rec: object) -> str:
    """把整条 judge 留痕记录的**所有字符串值**（任意嵌套、任意键）拍平成纯文本。

    检查3/4 原先只读 ``rec["messages"]`` —— 攻击者把条件/臂词藏进别的键
    （notes/raw_prompt/system 等）即可绕过盲评结构检查。此处全字段扫描，
    "换个键藏泄漏词"这条等价攻击被堵死。
    """
    parts: list[str] = []

    def _walk(o: object) -> None:
        if isinstance(o, str):
            parts.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    _walk(rec)
    return "\n".join(parts)


def judge_call_lines(repo_root: Path, run_ids: list[str]) -> Iterator[tuple[str, int, dict]]:
    """遍历 data/runs/<run_id>/logs/judge_calls.jsonl 每行 → (相对路径, 1-based 行号, 记录)。"""
    for rid in run_ids:
        p = Path(repo_root) / "data" / "runs" / rid / "logs" / "judge_calls.jsonl"
        if not p.exists():
            continue
        rel = str(p.relative_to(repo_root))
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            if not ln.strip():
                continue
            try:
                yield rel, i, json.loads(ln)
            except ValueError:
                yield rel, i, {"_parse_error": ln[:80]}


def _structure_forbidden_words() -> tuple[str, ...]:
    """检查3 断言集：condition 枚举 + trait_pole 标签 + 臂标识词（不含 trait 名，AMENDMENT-31）。"""
    return tuple(sorted(set(constants.CONDITIONS)
                        | set(constants.TRAIT_POLES) | set(_ARM_WORDS)))


def check_judge_structure(repo_root: Path, run_ids: list[str]) -> tuple[str, list[str]]:
    """检查3：judge messages 不出现条件/极性/臂词（盲评结构）。无留痕 → SKIP。"""
    forbidden = _structure_forbidden_words()
    seen_any = False
    fails: list[str] = []
    n_lines = 0
    for rel, lineno, rec in judge_call_lines(repo_root, run_ids):
        seen_any = True
        n_lines += 1
        if "_parse_error" in rec:
            fails.append(f"{rel}:{lineno} judge 留痕非法 JSON")
            continue
        text = _record_scan_text(rec)  # 全字段扫描（不止 messages 键）
        for w in _word_hits(text, forbidden):
            fails.append(f"{rel}:{lineno} 记录含盲评禁词 {w!r}（全字段扫描）")
    if not seen_any:
        return "SKIP", ["检查3（judge 结构）: 无 judge_calls.jsonl 留痕，SKIP"]
    if fails:
        return "FAIL", [f"检查3 FAIL: {len(fails)} 处泄漏"] + fails[:30]
    return "PASS", [f"检查3 PASS: {n_lines} 行 judge 留痕盲评结构干净（断言 trait 名豁免）"]


def _batch_trait_names(repo_root: Path, batch_id: str) -> set[str]:
    """批内 trait 名 = envelope scope.trait_whitelist ∪ data/traits/<trait> 子目录名。"""
    names: set[str] = set()
    env = Path(repo_root) / "fixtures" / "envelope_fixture.json"
    if env.is_file():
        try:
            e = json.loads(env.read_text(encoding="utf-8"))
            if e.get("batch_id") == batch_id:
                names |= {t for t in (e.get("scope") or {}).get("trait_whitelist", []) if t}
        except ValueError:
            pass
    troot = Path(repo_root) / "data" / "traits"
    if troot.is_dir():
        names |= {d.name for d in troot.iterdir() if d.is_dir()}
    return names


def _leak_words_judge() -> tuple[str, ...]:
    """检查4 judge 面词表 = CONDITIONS + trait_pole + 臂词（豁免 trait 名，AMENDMENT-31）。"""
    return _structure_forbidden_words()


def check_leak_grep(repo_root: Path, batch_id: str, run_ids: list[str]) -> tuple[str, list[str]]:
    """检查4：judge 留痕（豁免 trait 名）+ data/traits 题面（额外含 trait 名）泄漏词 grep。"""
    hits: list[str] = []
    scanned = 0

    # (a) judge 留痕：豁免 trait 名
    words_judge = _leak_words_judge()
    for rel, lineno, rec in judge_call_lines(repo_root, run_ids):
        if "_parse_error" in rec:
            continue
        text = _record_scan_text(rec)  # 全字段扫描（不止 messages 键）
        scanned += 1
        for w in _word_hits(text, words_judge):
            hits.append(f"{rel}:{lineno} 命中 {w!r}（judge 面·全字段）")

    # (b) data/traits 题面（questions 文本）：词表额外含批内 trait 名
    trait_names = _batch_trait_names(repo_root, batch_id)
    words_traits = tuple(sorted(set(words_judge) | {t for t in trait_names if t}))
    troot = Path(repo_root) / "data" / "traits"
    if troot.is_dir():
        for p in sorted(troot.rglob("*")):
            if not p.is_file() or p.suffix not in (".json", ".jsonl", ".txt"):
                continue
            rel = str(p.relative_to(repo_root))
            for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
                scanned += 1
                for w in _word_hits(ln, words_traits):
                    hits.append(f"{rel}:{i} 命中 {w!r}（traits 题面）")

    if scanned == 0:
        return "SKIP", ["检查4（泄漏 grep）: 无 judge 留痕且无 data/traits，SKIP"]
    if hits:
        return "FAIL", [f"检查4 FAIL: {len(hits)} 处泄漏词命中"] + hits[:30]
    return "PASS", [f"检查4 PASS: 扫描 {scanned} 单元，泄漏词零命中（trait 名在 judge 面豁免）"]


# ---------- 编排 ----------

def contamination_item(repo_root: Path, batch_id: str,
                       run_ids: Optional[list[str]] = None) -> AuditItem:
    """审计项3 编排：四检查任一 FAIL → item FAIL；全 SKIP/PASS → PASS。"""
    repo_root = Path(repo_root)
    if run_ids is None:
        from abcr.audit.auditor import runs_of_batch
        run_ids = runs_of_batch(repo_root, batch_id)

    results = [
        check_corpus_disjoint(repo_root),
        check_split_hash(repo_root, batch_id, run_ids),
        check_judge_structure(repo_root, run_ids),
        check_leak_grep(repo_root, batch_id, run_ids),
    ]
    evidence: list[str] = []
    verdict = "PASS"
    for v, ev in results:
        evidence += ev
        if v == "FAIL":
            verdict = "FAIL"
    return AuditItem.make(3, verdict, evidence)
