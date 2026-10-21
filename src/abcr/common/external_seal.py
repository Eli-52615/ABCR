"""abcr.common.external_seal —— 外部信任根（单一规范锚存储，对抗根因①：无外部锚）。

问题模型
--------
仓内各哈希链（steps 步骤链、ledger 五链、repro_pack 自签）都锚在 ZERO_HASH/GENESIS：
链内自洽 ≠ 链外可信。攻击者可以：
  (a) 整链从 genesis 重算 → 内部 verify_chain 全绿；
  (b) 截断链尾 → 剩余前缀仍是合法链；
  (c) 在被验证物旁边放"影子锚"文件，诱导按目录搜索的验证端读到伪锚。
本模块提供仓级**单一规范锚存储**：生产端在收口时把「链摘要 + 条目数」seal 进
规范锚文件；验证端 verify **只读规范锚路径这一处**，不做任何多路径搜索。

协议（冻结语义）
----------------
- 规范锚存储：`<repo_root>/anchors/seals.jsonl`（append-only、git 可跟踪）。
  路径仅可用环境变量 ``ABCR_ANCHOR_STORE`` 覆盖（测试隔离必需；调用时读，
  不在 import 时快照——与 constants 纪律一致）。
- 记录形状：``{ts, kind, subject_id, digest, length, extra}`` 一行一 JSON。
- 同一 (kind, subject_id) 允许多次 seal（append-only 不改旧行），**最后一条为准**
  （重封=覆盖语义；锚文件本身是信任根，能追加锚文件者本就在信任边界内）。
  ⚠️ V09：裸 ``seal`` 的无条件覆盖语义可被用来"洗白"——攻击者截断/改写链后重封，
  用当前内容盖掉旧锚，把已可检出的篡改抹成合规。故 **生产收口封印一律走
  ``guarded_reseal``**（seal-once + 前缀校验，只允许合法 append-only 前向扩展；
  截断/前缀改写一律 ResealRefused，绝不覆盖旧锚）。``seal`` 只留给"首封"与测试。
- ``verify`` fail-closed：锚文件缺失 / 无匹配记录 → ``(False, 'no external seal')``；
  digest 或 length 任一不符 → False。**length 比对是防尾部截断的独立防线**。
- ``chain_digest_and_length(entries)``：对每条 entry 的 canonical JSON 先做单条
  sha256，再串联进总 sha256——摘要承诺**每条记录的全部内容**（不是只承诺
  entry_hash 列），因此即使链内 entry_hash 字段被保持不动、内容被改，外部
  verify 也会失配；也不依赖链内哈希诚实。

kind 约定（消费方对齐用）
------------------------
- ``step_chain``   : data/runs/<run_id>/steps.jsonl 步骤链，subject_id=run_id。
- ``ledger_chain`` : ledger/ 全局五链，subject_id=链名（runs_index/batches/costs/...）。
- 其余（repro_pack、audit_anchor 等）由各消费组自定 kind，语义同上。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple

ANCHOR_STORE_ENV = "ABCR_ANCHOR_STORE"
DEFAULT_ANCHOR_RELPATH = Path("anchors") / "seals.jsonl"

# kind 常量（生产端/验证端共用，防手抖拼错）
KIND_STEP_CHAIN = "step_chain"
KIND_LEDGER_CHAIN = "ledger_chain"


def repo_root() -> Path:
    """仓根 = 本文件（<root>/src/abcr/common/external_seal.py）向上 3 级。"""
    return Path(__file__).resolve().parents[3]


def anchor_store_path() -> Path:
    """规范锚存储路径。ABCR_ANCHOR_STORE 调用时读（测试隔离）；否则仓根缺省。

    这是全模块**唯一**的路径来源：seal 写它，verify 只读它。没有搜索、没有
    候选列表、没有"相邻目录回退"——影子锚文件因此不可能被读到。
    """
    env = os.environ.get(ANCHOR_STORE_ENV)
    if env:
        return Path(env)
    return repo_root() / DEFAULT_ANCHOR_RELPATH


def chain_digest_and_length(entries: Iterable[Any]) -> Tuple[str, int]:
    """对链条目序列计算 (全链内容摘要, 条目数)。生产端/验证端必须共用本函数。

    摘要构造：sha256( ⊕_i sha256(canonical(entry_i)) )。
    - canonical(dict/list) = json.dumps(sort_keys=True, ensure_ascii=False)
    - 单条先内层 sha256 再喂外层，天然定界，无串接歧义。
    - 空序列 → (sha256(b'').hexdigest(), 0)：空是一个明确的、可区分的值，
      但按 evidence_floor 纪律，门上游应先 require_substantive 拒掉空链。
    """
    outer = hashlib.sha256()
    n = 0
    for e in entries:
        if isinstance(e, (dict, list)):
            b = json.dumps(e, ensure_ascii=False, sort_keys=True).encode("utf-8")
        elif isinstance(e, bytes):
            b = e
        else:
            b = str(e).encode("utf-8")
        outer.update(hashlib.sha256(b).digest())
        n += 1
    return outer.hexdigest(), n


def seal(kind: str, subject_id: str, digest: str, length: int,
         extra: Optional[dict] = None) -> dict:
    """向规范锚存储追加一条锚记录，返回该记录。

    - append-only + flock 互斥 + fsync（与仓内账本纪律同法）。
    - 对哈希链：digest=chain_digest_and_length 的全链摘要，length=条目数。
    - 同 (kind, subject_id) 重复 seal 合法（重封覆盖语义，verify 取最后一条）。
    """
    if not kind or not subject_id:
        raise ValueError("seal 需要非空 kind 与 subject_id")
    if not isinstance(length, int) or length < 0:
        raise ValueError(f"length 必须是非负整数，got {length!r}")
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "subject_id": subject_id,
        "digest": digest,
        "length": length,
        "extra": extra or {},
    }
    store = anchor_store_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    lock_path = store.with_name(store.name + ".lock")
    with lock_path.open("a", encoding="utf-8") as lk:
        fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
        try:
            with store.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        finally:
            fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
    return rec


def latest_seal(kind: str, subject_id: str) -> Optional[dict]:
    """读规范锚存储，返回 (kind, subject_id) 的最后一条锚记录；无则 None。

    只读 anchor_store_path() 这一处。锚文件中无法解析的行按"不存在"处理
    （解析不了的行不可能构成有效锚 → 语义仍 fail-closed）。
    """
    return _latest_seal_scoped(kind, subject_id)


def _latest_seal_scoped(kind: str, subject_id: str,
                        scope_extra: Optional[dict] = None) -> Optional[dict]:
    """latest_seal 的可归属版：返回 (kind, subject_id) 的最后一条锚记录。

    scope_extra 非空时，只认 extra 中这些键全部相等的记录——用于跨 repo/ledger 归属：
    同一 subject_id（如链名 'costs'）可能被多个 repo_root（演练沙箱/临时仓/测试）
    写进同一锚存储，别家的锚（chain_path 不同）对本主体等同"不存在"。这与 auditor
    ._ledger_anchor_status 的归属判定同口径，避免 guarded_reseal 拿别家的锚当本链的
    "既有承诺"而误拒本链的合法首封。scope_extra=None → 退化为纯 (kind,subject_id)。
    """
    store = anchor_store_path()
    if not store.exists():
        return None
    found: Optional[dict] = None
    for ln in store.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if not (isinstance(rec, dict) and rec.get("kind") == kind
                and rec.get("subject_id") == subject_id):
            continue
        if scope_extra:
            pe = rec.get("extra") or {}
            if any(pe.get(k) != v for k, v in scope_extra.items()):
                continue
        found = rec
    return found


def chain_prefix_digest(entries: Iterable[Any], length: int) -> str:
    """对 entries 的前 length 条计算与 chain_digest_and_length 同式的摘要。

    用于 guarded_reseal 的前缀校验：既有锚承诺了链的前 L0 条，要判断当前链是否
    仍以那 L0 条为前缀（合法 append-only 前向扩展），就重算前 L0 条的摘要并与旧锚
    的 digest 比对。length<0 视为 0。
    """
    ents = list(entries)
    if length < 0:
        length = 0
    return chain_digest_and_length(ents[:length])[0]


class ResealRefused(Exception):
    """V09 防洗白：既有锚与当前内容非"合法前向扩展"关系，拒绝用新内容覆盖旧锚。

    触发场景（均是"已被检出/可检出的篡改想借重封洗成合规"）：
      - 当前链条目数 < 既有锚承诺条目数（尾部截断，典型：删掉 costs.jsonl 超支行）；
      - 既有锚承诺的前 L0 条被改写（前缀摘要失配，典型：整链重算/改写历史条目）。
    调用方应据此落一条不可覆盖的 anchor_mismatch 告警，绝不静默。
    """

    def __init__(self, kind: str, subject_id: str, reason: str) -> None:
        self.kind = kind
        self.subject_id = subject_id
        self.reason = reason
        super().__init__(
            f"guarded reseal refused kind={kind!r} subject_id={subject_id!r}: {reason}")


def guarded_reseal(kind: str, subject_id: str, entries: Iterable[Any],
                   extra: Optional[dict] = None,
                   scope_extra_keys: Tuple[str, ...] = ()) -> dict:
    """**生产收口封印的唯一入口**（V09 防洗白）：seal-once + 前缀校验重封。

    与裸 ``seal`` 的差别：``seal`` 是无条件覆盖语义（append-only 存储、verify 取最后
    一条），任何能触发重封者都能拿"当前内容"覆盖旧锚——攻击者据此把一条已被
    length/digest 检出的篡改重新封印成合规，且洗完锚里只留一条"正常"记录、零残留。
    ``guarded_reseal`` 把重封收窄为"仅允许合法 append-only 前向扩展"：

    - 无既有锚 → 首封（正常 seal，返回新记录）。
    - 有既有锚 (D0, L0)：
        * 当前 entries 条目数 length ≥ L0 **且** 当前链前 L0 条摘要 == D0
          → 合法前向扩展（旧承诺的前缀原封未动，只是又追加了新条目）
          → 把锚推进到当前全链摘要（返回新记录）。
        * 否则（length<L0 尾部截断，或前缀摘要失配即历史条目被改写）
          → raise ResealRefused，**绝不覆盖旧锚**。旧锚原样留存，
            _verify_ledger_anchors 下次仍会拿它抓出这条篡改。

    幂等：内容未变时 length==L0 且前缀==全链==D0，走"前向扩展(扩展 0 条)"分支，
    重封为同一 digest/length，无害。

    scope_extra_keys：跨 repo/ledger 归属键（如 ('chain_path',)）。同一锚存储可能被
    多个 repo_root 用相同 subject_id（链名）写过，别家的锚不应约束本链的首封——故
    "既有锚"只在 extra 的这些键与本次一致时才算数（与 auditor 归属判定同口径）。
    收口方传的 extra.chain_path 由真实 led.path 计算、非攻击者可控，故不构成绕过：
    真截断攻击里 chain_path 不变、guard 照常触发。
    """
    ents = list(entries)
    digest, length = chain_digest_and_length(ents)
    scope_extra = {k: (extra or {}).get(k) for k in scope_extra_keys} if scope_extra_keys else None
    prior = _latest_seal_scoped(kind, subject_id, scope_extra)
    if prior is None:
        return seal(kind, subject_id, digest, length, extra=extra)
    prior_len = prior.get("length")
    prior_digest = prior.get("digest")
    if not isinstance(prior_len, int) or prior_len < 0:
        raise ResealRefused(kind, subject_id,
                            f"既有锚 length 非法 {prior_len!r}，拒绝重封")
    if length < prior_len:
        raise ResealRefused(
            kind, subject_id,
            f"当前链条目数 {length} < 既有锚承诺 {prior_len}（尾部截断嫌疑），拒绝重封")
    got_prefix = chain_prefix_digest(ents, prior_len)
    if got_prefix != prior_digest:
        raise ResealRefused(
            kind, subject_id,
            f"既有锚承诺的前 {prior_len} 条已被改写（前缀摘要 "
            f"{got_prefix[:16]}… ≠ 锚 {str(prior_digest)[:16]}…），拒绝重封")
    return seal(kind, subject_id, digest, length, extra=extra)


def verify(kind: str, subject_id: str, actual_digest: str,
           actual_length: int) -> Tuple[bool, str]:
    """将实际重算值与规范锚比对。fail-closed：缺锚绝不判过。

    返回 (ok, reason)：
    - 锚存储缺失或无匹配记录 → (False, 'no external seal')。
    - length 不符 → False（防尾部截断/整链重算改条目数的独立防线）。
    - digest 不符 → False。
    - 全符 → (True, 'ok')。
    只读 anchor_store_path() 这一处；被验证物内部/相邻目录的任何自洽材料
    （含影子 seals.jsonl）对结果零影响。
    """
    rec = latest_seal(kind, subject_id)
    if rec is None:
        return False, f"no external seal for kind={kind!r} subject_id={subject_id!r}"
    sealed_length = rec.get("length")
    sealed_digest = rec.get("digest")
    if sealed_length != actual_length:
        return False, (f"length mismatch: sealed={sealed_length!r} "
                       f"actual={actual_length!r} (truncation/recount suspected)")
    if sealed_digest != actual_digest:
        return False, (f"digest mismatch: sealed={str(sealed_digest)[:16]}… "
                       f"actual={str(actual_digest)[:16]}…")
    return True, "ok"
