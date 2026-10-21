"""abcr.common.cost_ledger —— 项目成本账本（种子三契约最小 fail-closed 实现）。

架构位置：包A/C 共用的公共成本契约库（与 approval_token / ledger_ref 同层）。
落地种子 JSON 的三契约的**最小可用**子集，专攻 fail-closed 成本记账：

  1. project_cost_ledger_genesis_contract —— 单例创世根（带 W1/项目双 cap）。
     二次创世 / reset / fork / audit-local 影子账本 一律 ERROR。
  2. project_cost_ledger_event_contract —— append-only 事件链（RESERVED/SETTLED/RELEASED），
     哈希链 + fencing_token 严格递增（防 stale reservation / 防并发 tip 双写）+
     tip compare-and-swap；非有限(NaN/Inf)/负金额一律拒；RESERVED 前校验 W1(≤150) 与
     项目(≤4000) 两个独立 cap（不塌缩为单 min-cap）。
  3. cost_receipt_manifest_contract —— 收据清单（按 transaction 汇总 reservation/settlement）。

fail-closed 语义（与旧 fail-open 相反）：
  - 创世缺失 → 拒绝一切事件（不当空账本放行）。
  - 账本损坏/断链 → verify_chain raise，spent 读取按 fail-closed 抛错。
  - 金额非有限或负 → 拒（N-COST-NAN-SETTLE：结算 amt=nan 不再静默跳过）。
  - reservation 会超任一 cap → 拒（幽灵负债在架构上被阻断）。
  - fencing_token 非严格递增 / tip 不匹配 → 拒（并发双写恰一个成功）。

序列化口径与 ledger_ref 一致：canonical = json.dumps(obj, ensure_ascii=False, sort_keys=True)；
record_sha256 = sha256(canonical(记录去 record_sha256 字段) + prev_record_sha256 字节)。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 契约冻结常量（cost_receipt_manifest_contract: w1_scope_cap const 150 / project_cap const 4000）。
W1_SCOPE_CAP_CNY: float = 150.0
PROJECT_CAP_CNY: float = 4000.0
CURRENCY = "CNY"

GENESIS_FILE = "cost_genesis.json"
EVENTS_FILE = "cost_events.jsonl"

EVENT_TYPES = frozenset({"RESERVED", "SETTLED", "RELEASED"})


# ────────────────────────── 异常（全部 fail-closed 方向）──────────────────────────
class CostLedgerError(Exception):
    """成本账本通用错误（fail-closed：宁可拒绝也不静默放行）。"""


class GenesisError(CostLedgerError):
    """创世违例：缺失 / 二次创世 / reset / fork。"""


class CostLedgerTampered(CostLedgerError):
    """事件哈希链断裂——记录被改/删/插/截断。"""

    def __init__(self, index: int, reason: str) -> None:
        self.index, self.reason = index, reason
        super().__init__(f"cost ledger tampered at event #{index}: {reason}")


class StaleFencingToken(CostLedgerError):
    """fencing_token 非严格递增——stale reservation / 并发双写被挡。"""


class TipConflict(CostLedgerError):
    """compare-and-swap 失败：expected_tip 与账本当前 tip 不符（并发覆写被挡）。"""


class AmountInvalid(CostLedgerError):
    """金额非有限(NaN/Inf)或为负（N-COST-NAN-SETTLE 收口点）。"""


class CapExceeded(CostLedgerError):
    """预留会击穿 W1(≤150) 或项目(≤4000) cap。"""


class ReservationError(CostLedgerError):
    """结算/释放引用了不存在或已终结的 reservation。"""


# ────────────────────────── 哈希/规范化 ──────────────────────────
def _canonical(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record_hash(rec_core: dict, prev_hash: str) -> str:
    """rec_core 不含 record_sha256 字段，含全部其他字段。"""
    return _sha256_hex(_canonical(rec_core).encode("utf-8") + prev_hash.encode("utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finite_nonneg(x: object) -> bool:
    return (isinstance(x, (int, float)) and not isinstance(x, bool)
            and math.isfinite(x) and x >= 0)


def _finite_pos(x: object) -> bool:
    return _finite_nonneg(x) and x > 0


# ────────────────────────── 创世（契约1：单例根 + 双 cap）──────────────────────────
def genesis(
    ledger_dir: Path,
    *,
    project_scope_id: str,
    ledger_authority_id: str,
    authority_registry_sha256: str,
    w1_budget_scope_id: str,
    currency: str = CURRENCY,
    opening_project_settled: float = 0.0,
    opening_project_liability: float = 0.0,
    created_at: Optional[str] = None,
) -> dict:
    """写唯一创世根。二次创世 / reset / fork → GenesisError（append-only 单例）。

    project_cost_ledger_id = sha256(canonical(['ABCR_PROJECT_COST_LEDGER', project_scope_id,
        ledger_authority_id, authority_registry_sha256, created_at]))。
    """
    ledger_dir = Path(ledger_dir)
    if not (isinstance(currency, str) and currency == CURRENCY):
        raise GenesisError(f"currency 必须为 {CURRENCY!r}")
    for name, val in (("project_scope_id", project_scope_id),
                      ("ledger_authority_id", ledger_authority_id),
                      ("w1_budget_scope_id", w1_budget_scope_id)):
        if not (isinstance(val, str) and val.strip()):
            raise GenesisError(f"{name} 不得为空")
    if not (isinstance(authority_registry_sha256, str)
            and len(authority_registry_sha256) == 64
            and all(c in "0123456789abcdef" for c in authority_registry_sha256)):
        raise GenesisError("authority_registry_sha256 须为 64 位小写 hex")
    if not (_finite_nonneg(opening_project_settled) and _finite_nonneg(opening_project_liability)):
        raise GenesisError("opening_project_settled/liability 须为有限非负数")

    ledger_dir.mkdir(parents=True, exist_ok=True)
    gpath = ledger_dir / GENESIS_FILE
    # 单例：文件已存在即拒（不覆盖、不 reset、不 fork）。用 O_EXCL 原子创建防 TOCTOU。
    created_at = created_at or _now()
    project_cost_ledger_id = _sha256_hex(_canonical(
        ["ABCR_PROJECT_COST_LEDGER", project_scope_id, ledger_authority_id,
         authority_registry_sha256, created_at]).encode("utf-8"))
    rec = {
        "schema_version": "abcr.project-cost-ledger-genesis.v1",
        "project_cost_ledger_id": project_cost_ledger_id,
        "project_scope_id": project_scope_id,
        "ledger_authority_id": ledger_authority_id,
        "authority_registry_sha256": authority_registry_sha256,
        "w1_budget_scope_id": w1_budget_scope_id,
        "currency": CURRENCY,
        "opening_project_settled": float(opening_project_settled),
        "opening_project_liability": float(opening_project_liability),
        "created_at": created_at,
        "previous_seal_sha256": None,
    }
    rec["genesis_record_sha256"] = _sha256_hex(_canonical(rec).encode("utf-8"))
    body = json.dumps(rec, ensure_ascii=False, indent=2)
    try:
        fd = os.open(str(gpath), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as e:
        raise GenesisError(
            f"创世根已存在 {gpath}：拒绝二次创世/reset/fork（append-only 单例）") from e
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        # 写失败则清掉半成品，保持单例语义可重试
        try:
            os.unlink(str(gpath))
        except OSError:
            pass
        raise
    return rec


# ────────────────────────── 账本（契约2：事件链 + fencing + CAS）──────────────────────────
class CostLedger:
    """项目成本账本单链。创世缺失 → fail-closed（拒绝一切事件）。"""

    def __init__(self, ledger_dir: Path) -> None:
        self.dir = Path(ledger_dir)
        self.gpath = self.dir / GENESIS_FILE
        self.epath = self.dir / EVENTS_FILE
        if not self.gpath.exists():
            raise GenesisError(f"创世根缺失 {self.gpath}：无账本根，拒绝一切成本事件（fail-closed）")
        self.gen = json.loads(self.gpath.read_text(encoding="utf-8"))
        # 校验创世自洽（防篡改根）
        core = {k: v for k, v in self.gen.items() if k != "genesis_record_sha256"}
        if _sha256_hex(_canonical(core).encode("utf-8")) != self.gen.get("genesis_record_sha256"):
            raise GenesisError("创世根 genesis_record_sha256 自洽校验失败（根被篡改）")
        self.ledger_id = self.gen["project_cost_ledger_id"]
        self.genesis_sha = self.gen["genesis_record_sha256"]
        self.w1_scope = self.gen["w1_budget_scope_id"]

    # ---- 读取 ----
    def events(self) -> list[dict]:
        if not self.epath.exists():
            return []
        return [json.loads(ln) for ln in self.epath.read_text(encoding="utf-8").splitlines()
                if ln.strip()]

    def tip(self) -> str:
        evs = self.events()
        return evs[-1]["record_sha256"] if evs else self.genesis_sha

    def _replay(self, evs: list[dict]) -> dict:
        """重放事件得到当前状态：settled/liability + 每个 reservation 的账。fail-closed。"""
        settled = float(self.gen["opening_project_settled"])
        liability = float(self.gen["opening_project_liability"])
        max_token = 0
        reservations: dict[str, dict] = {}   # reservation_id -> {reserved, settled(bool)}
        for i, ev in enumerate(evs):
            tok = ev.get("transaction_fencing_token")
            if isinstance(tok, int) and not isinstance(tok, bool):
                max_token = max(max_token, tok)
            et = ev.get("event_type")
            amt = ev.get("amount_cny")
            rid = ev.get("reservation_id")
            if et == "RESERVED":
                if not _finite_pos(amt):
                    raise CostLedgerTampered(i, "RESERVED amount 非有限正数")
                reservations[rid] = {"reserved": float(amt), "closed": False}
                liability += float(amt)
            elif et in ("SETTLED", "RELEASED"):
                r = reservations.get(rid)
                if r is None:
                    raise CostLedgerTampered(i, f"结算引用未知 reservation {rid!r}")
                if r["closed"]:
                    raise CostLedgerTampered(i, f"reservation {rid!r} 重复终结")
                reserved = r["reserved"]
                actual = float(amt) if et == "SETTLED" else 0.0
                liability -= reserved
                settled += actual
                r["closed"] = True
            else:
                raise CostLedgerTampered(i, f"未知 event_type {et!r}")
        return {"settled": settled, "liability": liability,
                "max_token": max_token, "reservations": reservations}

    def spent(self) -> tuple[float, float]:
        """返回 (settled, outstanding_liability)。链损坏 → raise（fail-closed）。"""
        self.verify_chain()
        st = self._replay(self.events())
        return st["settled"], st["liability"]

    def worst_case_spent(self) -> float:
        """预算护栏用的悲观口径：已结算 + 未结算负债（fail-closed，负债计入占用）。"""
        settled, liability = self.spent()
        return settled + liability

    # ---- 写入（append_event）----
    def append_event(
        self,
        *,
        event_type: str,
        transaction_id: str,
        fencing_token: int,
        amount_cny: float,
        reservation_id: str,
        expected_tip: Optional[str] = None,
        approved_action_ids: Optional[list[str]] = None,
        approve_cost_receipt_sha256: Optional[str] = None,
        audit_id: str = "abcr-w1",
        occurred_at: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> dict:
        """追加一条成本事件。全程持 <events>.jsonl.lock 排它锁，锁内重读账本状态：
          - fencing_token 必须 > 当前最大（防 stale reservation / 并发双写）。
          - expected_tip（若给）必须等于当前 tip（compare-and-swap）。
          - 金额非有限(NaN/Inf)/负 → AmountInvalid。
          - RESERVED：amount>0，且校验 W1(≤150) 与项目(≤4000) 两个独立 cap。
          - SETTLED：0≤actual≤reserved；RELEASED：actual=0；负债按整笔 reserved 释放。
        """
        if event_type not in EVENT_TYPES:
            raise CostLedgerError(f"event_type 须属 {sorted(EVENT_TYPES)}，得 {event_type!r}")
        if not (isinstance(fencing_token, int) and not isinstance(fencing_token, bool)
                and fencing_token >= 1):
            raise StaleFencingToken(f"fencing_token 须为 ≥1 的整数，得 {fencing_token!r}")
        if not (isinstance(transaction_id, str) and transaction_id.strip()):
            raise CostLedgerError("transaction_id 不得为空")
        if not (isinstance(reservation_id, str) and reservation_id.strip()):
            raise CostLedgerError("reservation_id 不得为空")
        # 金额 fail-closed：NaN/Inf/负一律拒（N-COST-NAN-SETTLE）。
        if not _finite_nonneg(amount_cny):
            raise AmountInvalid(
                f"amount_cny 须为有限非负数（拒 NaN/Inf/负）：{amount_cny!r}")
        if event_type == "RESERVED" and not _finite_pos(amount_cny):
            raise AmountInvalid(f"RESERVED amount_cny 须为有限正数：{amount_cny!r}")
        if event_type == "RELEASED" and float(amount_cny) != 0.0:
            raise AmountInvalid(f"RELEASED actual 须为 0：{amount_cny!r}")

        self.dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.epath.with_name(self.epath.name + ".lock")
        with lock_path.open("a", encoding="utf-8") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                evs = self.events()
                # 链完整性先验（锁内，防在断链账本上继续写）。
                self._verify(evs)
                st = self._replay(evs)
                # fencing 严格递增（stale / 并发双写 → 拒）。
                if fencing_token <= st["max_token"]:
                    raise StaleFencingToken(
                        f"fencing_token {fencing_token} 未严格大于当前最大 {st['max_token']}")
                cur_tip = evs[-1]["record_sha256"] if evs else self.genesis_sha
                if expected_tip is not None and expected_tip != cur_tip:
                    raise TipConflict(
                        f"expected_tip {str(expected_tip)[:12]}… != 当前 tip {cur_tip[:12]}…")

                prior_settled = st["settled"]
                prior_liability = st["liability"]
                if event_type == "RESERVED":
                    if reservation_id in st["reservations"]:
                        raise ReservationError(f"reservation {reservation_id!r} 重复预留")
                    new_liability = prior_liability + float(amount_cny)
                    # 双独立 cap（不塌缩为单 min-cap）：settled + 负债(含本次) 均须 ≤ 各自 cap。
                    projected = prior_settled + new_liability
                    if projected > W1_SCOPE_CAP_CNY:
                        raise CapExceeded(
                            f"W1 cap 击穿：settled+liability={projected} > {W1_SCOPE_CAP_CNY}")
                    if projected > PROJECT_CAP_CNY:
                        raise CapExceeded(
                            f"项目 cap 击穿：settled+liability={projected} > {PROJECT_CAP_CNY}")
                    post_settled, post_liability = prior_settled, new_liability
                else:  # SETTLED / RELEASED
                    r = st["reservations"].get(reservation_id)
                    if r is None:
                        raise ReservationError(f"结算引用未知 reservation {reservation_id!r}")
                    if r["closed"]:
                        raise ReservationError(f"reservation {reservation_id!r} 已终结，拒绝二次结算")
                    reserved = r["reserved"]
                    actual = float(amount_cny) if event_type == "SETTLED" else 0.0
                    if actual > reserved:
                        raise AmountInvalid(
                            f"actual {actual} > reserved {reserved}（禁跨预留补贴）")
                    post_liability = prior_liability - reserved
                    post_settled = prior_settled + actual

                seq = len(evs) + 1
                occurred_at = occurred_at or _now()
                event_id = event_id or f"COSTEV-{event_type}-{seq:06d}"
                rec = {
                    "schema_version": "abcr.project-cost-ledger-event.v1",
                    "project_cost_ledger_id": self.ledger_id,
                    "project_cost_ledger_genesis_sha256": self.genesis_sha,
                    "w1_budget_scope_id": self.w1_scope,
                    "sequence": seq,
                    "prev_record_sha256": cur_tip,
                    "event_id": event_id,
                    "event_type": event_type,
                    "transaction_id": transaction_id,
                    "transaction_fencing_token": fencing_token,
                    "audit_id": audit_id,
                    "approve_cost_receipt_sha256": approve_cost_receipt_sha256,
                    "reservation_id": reservation_id,
                    "approved_action_ids": approved_action_ids,
                    "amount_cny": float(amount_cny),
                    "prior_w1_settled": prior_settled,
                    "prior_w1_liability": prior_liability,
                    "post_w1_settled": post_settled,
                    "post_w1_liability": post_liability,
                    "prior_project_settled": prior_settled,
                    "prior_project_liability": prior_liability,
                    "post_project_settled": post_settled,
                    "post_project_liability": post_liability,
                    "occurred_at": occurred_at,
                }
                rec["record_sha256"] = _record_hash(rec, cur_tip)
                with self.epath.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                return rec
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)

    # ---- 校验 ----
    def _verify(self, evs: list[dict]) -> bool:
        prev = self.genesis_sha
        for i, rec in enumerate(evs):
            if "prev_record_sha256" not in rec or "record_sha256" not in rec:
                raise CostLedgerTampered(i, "缺链字段 prev_record_sha256/record_sha256")
            if rec["prev_record_sha256"] != prev:
                raise CostLedgerTampered(
                    i, f"prev 断链（期望 {prev[:12]}…，得 {str(rec['prev_record_sha256'])[:12]}…）")
            if rec.get("sequence") != i + 1:
                raise CostLedgerTampered(i, f"sequence 非连续（期望 {i + 1}，得 {rec.get('sequence')!r}）")
            core = {k: v for k, v in rec.items() if k != "record_sha256"}
            recomputed = _record_hash(core, rec["prev_record_sha256"])
            if recomputed != rec["record_sha256"]:
                raise CostLedgerTampered(
                    i, f"record_sha256 失配（期望 {recomputed[:12]}…，得 {str(rec['record_sha256'])[:12]}…）")
            prev = rec["record_sha256"]
        return True

    def verify_chain(self) -> bool:
        """重放整条事件链，改/删/插/截任一条即 raise CostLedgerTampered。"""
        return self._verify(self.events())

    # ---- 收据清单（契约3：最小实现）----
    def receipt_manifest(self, transaction_id: str) -> dict:
        """按 transaction 汇总本账本内该 transaction 的 reservation/settlement。
        worst_case_unsettled_liability 必须为 0（即该 transaction 每个 reservation 已终结），
        否则 fail-closed（在飞负债不得出收据）。"""
        self.verify_chain()
        evs = [e for e in self.events() if e.get("transaction_id") == transaction_id]
        if not evs:
            raise CostLedgerError(f"transaction {transaction_id!r} 无事件，无法出收据")
        reservations: dict[str, dict] = {}
        settlements: list[dict] = []
        reservation_total = 0.0
        settled_total = 0.0
        for ev in evs:
            rid = ev["reservation_id"]
            if ev["event_type"] == "RESERVED":
                reservations[rid] = {"reservation_id": rid,
                                     "reserved_amount": ev["amount_cny"],
                                     "closed": False}
                reservation_total += ev["amount_cny"]
            else:
                r = reservations.get(rid)
                actual = ev["amount_cny"] if ev["event_type"] == "SETTLED" else 0.0
                reserved = r["reserved_amount"] if r else 0.0
                if r:
                    r["closed"] = True
                settled_total += actual
                settlements.append({
                    "reservation_id": rid,
                    "status": ev["event_type"],
                    "reserved_amount": reserved,
                    "actual_amount": actual,
                    "released_amount": reserved - actual,
                    "outstanding_liability_after": 0,
                })
        outstanding = sum(r["reserved_amount"] for r in reservations.values() if not r["closed"])
        if outstanding != 0:
            raise CostLedgerError(
                f"transaction {transaction_id!r} 尚有在飞负债 {outstanding}，拒绝出收据（fail-closed）")
        settled, liability = self.spent()
        manifest = {
            "schema_version": "abcr.cost-receipt-manifest.v1",
            "transaction_id": transaction_id,
            "project_cost_ledger_id": self.ledger_id,
            "project_cost_ledger_genesis_sha256": self.genesis_sha,
            "w1_budget_scope_id": self.w1_scope,
            "currency": CURRENCY,
            "w1_scope_cap": 150,
            "project_cap": 4000,
            "ledger_tip_after_sha256": self.tip(),
            "reservation_total": reservation_total,
            "settled_total": settled_total,
            "worst_case_unsettled_liability": 0,
            "post_project_settled": settled,
            "post_project_unsettled_liability": liability,
            "reservations": [{"reservation_id": r["reservation_id"],
                              "reserved_amount": r["reserved_amount"]}
                             for r in reservations.values()],
            "settlements": settlements,
        }
        manifest["manifest_record_sha256"] = _sha256_hex(_canonical(manifest).encode("utf-8"))
        return manifest
