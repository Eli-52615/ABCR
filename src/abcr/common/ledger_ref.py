"""运行账本 —— append-only JSONL + 哈希链 + fsync。
改写自 AILH V2 TraceWriter。
每条记录: {ts, run_id, event, ...payload, prev_hash, entry_hash}
  prev_hash  = 上一条的 entry_hash（首条为 GENESIS_HASH）
  entry_hash = sha256(canonical_json(含 prev_hash、不含 entry_hash 的本条) + prev_hash字节)
改一条 → 其后全部 prev_hash 失配 → verify_chain() 定位断链点。

相对原实现的三处增强：append 后 flush+os.fsync（原实现无，掉电会丢行）；
链尾哈希内存缓存（原实现每次 append 全文件重读，O(n^2)——仅单写者链 shared=False 依赖此假设）；
全局链并发写互斥（AMENDMENT-15）：shared=True（缺省，ledger/ 五链）时 append 对
<chain>.jsonl.lock 持 fcntl.flock(LOCK_EX)，锁内重读链尾再写（全局链放弃链尾缓存）；
data/runs/<id>/steps.jsonl 单写者用 shared=False 保留缓存。

维护权归窗口 A（A1-1 接管）。使用约定（三包同守）：五账本实例化 chain_id = 文件 stem
（类字段 run_id 是历史命名，语义是 chain_id）；业务主体放 payload 的 subject_id 键
（AMENDMENT-4）；append() payload 键不得用 ts/run_id/event/prev_hash/entry_hash。

冻结版增补（fable 广播 20260715 · AMENDMENT-36，B 包闭环硬依赖）：
events(event=, subject_id=) 过滤、has_event()（dispatch 幂等）、模块级 append_record()
（steps.jsonl 整记录挂链通道）。记录形状冻结 A 形；B 形 seq 字段废。

外部信任根接线（R2 根因修复①）：RunLedger 新增 head_and_length() /
seal_chain() / verify_external_seal()——收口时 seal 到仓级规范锚存储
（abcr.common.external_seal），验证端只认规范锚，防整链重算与尾部截断。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from abcr.common import external_seal

GENESIS_HASH = "0" * 64  # 协议常量：改动即令所有既有链失配

# append() payload 不得覆盖的保留键（维护性守卫，A1-1 测试用例6）
_RESERVED_PAYLOAD_KEYS = ("ts", "run_id", "event", "prev_hash", "entry_hash")


class LedgerTampered(Exception):
    """哈希链断链 —— 记录被改/删/插/截断。index=-1 表示链尾摘要漂移。"""
    def __init__(self, index: int, reason: str) -> None:
        self.index, self.reason = index, reason
        super().__init__(f"ledger tampered at record #{index}: {reason}")


def _entry_hash(rec_core: dict, prev_hash: str) -> str:
    """rec_core 必须含 prev_hash 字段、不含 entry_hash 字段（把本条钉死在前一条之后）。"""
    payload = json.dumps(rec_core, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload + prev_hash.encode("utf-8")).hexdigest()


class RunLedger:
    """单链 append-only 账本。只暴露 append，无 update/delete 接口。"""

    def __init__(self, root: Path, run_id: str, shared: bool = True) -> None:
        """shared=True（缺省，ledger/ 全局五链）：append 经 <chain>.jsonl.lock 的
        fcntl.flock(LOCK_EX) 互斥、锁内重读链尾再写（AMENDMENT-15）；
        shared=False（data/runs/<id>/steps.jsonl 单写者）：保留链尾内存缓存。"""
        self.run_id = run_id
        self.root = Path(root)
        self.path = self.root / f"{run_id}.jsonl"
        self.shared = shared
        self._tail: Optional[str] = None  # 链尾缓存；None=尚未从磁盘装载

    def _tail_hash(self) -> str:
        if self._tail is None:
            evs = self.events()
            self._tail = evs[-1]["entry_hash"] if evs else GENESIS_HASH
        return self._tail

    def append(self, event: str, **payload: Any) -> dict:
        """追加一条事件并链入哈希。payload 键不得用 ts/run_id/event/prev_hash/entry_hash。
        shared=True 时全程持 <chain>.jsonl.lock 排它锁并在锁内重读链尾（AMENDMENT-15）。"""
        # 保留键守卫（A1-1 测试用例6）：原实现被 **payload 静默覆盖语义，改为显式拒绝。
        bad = [k for k in _RESERVED_PAYLOAD_KEYS if k in payload]
        if bad:
            raise ValueError(f"payload 不得含保留键 {bad}（业务主体用 subject_id）")
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.shared:                      # 单写者链（steps.jsonl）：保留链尾缓存
            return self._append_one(event, payload)
        lock_path = self.path.with_name(self.path.name + ".lock")   # <chain>.jsonl.lock
        with lock_path.open("a", encoding="utf-8") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                self._tail = None                # 全局链放弃链尾缓存：锁内重读链尾再写
                return self._append_one(event, payload)
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)

    def _append_one(self, event: str, payload: dict) -> dict:
        prev_hash = self._tail_hash()
        rec: dict = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": self.run_id,
            "event": event,
            **payload,
        }
        rec["prev_hash"] = prev_hash
        rec["entry_hash"] = _entry_hash(rec, prev_hash)  # 此刻 rec 含 prev、不含 entry
        with self.path.open("a", encoding="utf-8") as f:   # 'a' 追加：物理上只增不改
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())                            # 进程被杀/掉电不丢已 append 的行
        self._tail = rec["entry_hash"]
        return rec

    def events(self, event: Optional[str] = None,
               subject_id: Optional[str] = None) -> List[dict]:
        """全量读链；可按 event / payload 的 subject_id 过滤（AMENDMENT-36 增补，缺省行为不变）。"""
        if not self.path.exists():
            return []
        out = [json.loads(ln) for ln in self.path.read_text(encoding="utf-8").splitlines()
               if ln.strip()]
        if event is not None:
            out = [e for e in out if e.get("event") == event]
        if subject_id is not None:
            out = [e for e in out if e.get("subject_id") == subject_id]
        return out

    def has_event(self, event: str, subject_id: str) -> bool:
        """事件幂等判定（B dispatch 契约 §4.4 纪律①：写开局事件前先扫）。"""
        return any(e.get("event") == event and e.get("subject_id") == subject_id
                   for e in self.events())

    def verify_chain(self) -> bool:
        """重放整条链；改/删/插/截任一条即 raise LedgerTampered（定位条目下标）。"""
        prev = GENESIS_HASH
        for i, rec in enumerate(self.events()):
            if "prev_hash" not in rec or "entry_hash" not in rec:
                raise LedgerTampered(i, "missing chain field (prev_hash/entry_hash)")
            if rec["prev_hash"] != prev:
                raise LedgerTampered(
                    i, f"prev_hash break (expected {prev[:12]}…, got {str(rec['prev_hash'])[:12]}…)")
            core = {k: v for k, v in rec.items() if k != "entry_hash"}
            recomputed = _entry_hash(core, rec["prev_hash"])
            if recomputed != rec["entry_hash"]:
                raise LedgerTampered(
                    i, f"entry_hash mismatch (expected {recomputed[:12]}…, got {str(rec['entry_hash'])[:12]}…)")
            prev = rec["entry_hash"]
        return True

    def snapshot_digest(self) -> str:
        """链尾哈希=整条链累积指纹。空链返回 GENESIS_HASH。供异地留存后比对。"""
        evs = self.events()
        return evs[-1]["entry_hash"] if evs else GENESIS_HASH

    def verify_against_digest(self, expected_tail: str) -> bool:
        self.verify_chain()
        actual = self.snapshot_digest()
        if actual != expected_tail:
            raise LedgerTampered(-1, f"tail digest drift (expected {expected_tail[:12]}…, got {actual[:12]}…)")
        return True

    # ---- 外部信任根（external_seal 接线，对抗根因①）----
    # 链锚在 GENESIS_HASH → 链内自洽可被"整链从 genesis 重算"伪造；链尾截断后
    # verify_chain 依旧通过。收口时 seal_chain() 把「全链内容摘要 + 条目数」写进
    # 仓级规范锚存储（kind='ledger_chain'，subject_id=链名即 self.run_id）；
    # 验证端 verify_external_seal() 重算并只与规范锚比对——length 防截断，
    # digest 承诺全部内容（不只 entry_hash 列）防整链重算。

    def head_and_length(self) -> Tuple[str, int]:
        """(链尾 entry_hash, 条目数)。空链 → (GENESIS_HASH, 0)。供收口方留痕。"""
        evs = self.events()
        return (evs[-1]["entry_hash"] if evs else GENESIS_HASH, len(evs))

    def seal_chain(self, kind: str = external_seal.KIND_LEDGER_CHAIN,
                   extra: Optional[dict] = None) -> dict:
        """收口：把本链 seal 进规范锚存储，返回锚记录。

        批次链（batches）与成本链（costs）在 dispatch/结算收口处调用；
        subject_id = 链名（self.run_id，历史命名，语义是 chain_id）。
        """
        evs = self.events()
        digest, length = external_seal.chain_digest_and_length(evs)
        tail, _ = (evs[-1]["entry_hash"], length) if evs else (GENESIS_HASH, 0)
        meta = {"chain_path": str(self.path), "chain_tail": tail}
        if extra:
            meta.update(extra)
        return external_seal.seal(kind, self.run_id, digest, length, extra=meta)

    def verify_external_seal(self,
                             kind: str = external_seal.KIND_LEDGER_CHAIN
                             ) -> Tuple[bool, str]:
        """验证端：先内部 verify_chain，再重算摘要+条目数【只】与规范锚比对。

        fail-closed：缺锚 → (False, 'no external seal ...')；截断 → length 不符
        → False；整链重算 → digest（及通常 length）不符 → False。
        不做任何多路径搜索，影子锚文件零影响。
        """
        try:
            self.verify_chain()
        except LedgerTampered as e:
            return False, f"internal chain invalid: {e}"
        digest, length = external_seal.chain_digest_and_length(self.events())
        return external_seal.verify(kind, self.run_id, digest, length)


def append_record(path: Path, record: dict) -> dict:
    """整记录挂链通道（AMENDMENT-36 增补）：供 data/runs/<id>/steps.jsonl 等
    自带完整业务 schema 的记录使用——record 原样保留（含业务 run_id 字段），
    本函数只补 prev_hash / entry_hash 两个链字段。seq 字段废（AMENDMENT-36）。

    与 RunLedger.append 的分工：全局五链走 RunLedger（事件语义 + 保留键守卫）；
    steps 整记录走本函数（48 字段 schema 由 abcr.ledger.schema.validate_step 守卫）。
    并发安全：<file>.jsonl.lock flock 互斥 + 锁内重读链尾（与 AMENDMENT-15 同法）。
    """
    if "prev_hash" in record or "entry_hash" in record:
        raise ValueError("record 不得预含链字段 prev_hash/entry_hash（由本函数补）")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock_path = p.with_name(p.name + ".lock")
    with lock_path.open("a", encoding="utf-8") as lk:
        fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
        try:
            prev = GENESIS_HASH
            if p.exists():
                lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
                if lines:
                    prev = json.loads(lines[-1])["entry_hash"]
            rec = dict(record)
            rec["prev_hash"] = prev
            rec["entry_hash"] = _entry_hash(rec, prev)   # 此刻含 prev、不含 entry
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            return rec
        finally:
            fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
