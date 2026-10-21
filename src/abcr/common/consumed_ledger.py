"""abcr.common.consumed_ledger —— 一次性消费账本原语（append-only + genesis + 哈希链）。

架构位置：包C·Governor 侧公共契约库。承载 F-TOKEN-02 架构级 fail-closed 修复所需的
账本原语，被 abcr.common.approval_token 消费；不反向依赖 approval_token（无环）。

—— 为什么要账本（F-TOKEN-02「删除向量」）——
旧实现：consumed store 是一个 list[str]（consumed.json）。损坏/截断已 fail-closed，但
**整体删除** store 会使旧令牌复活——因为「文件不存在」既可能是「全新系统首用（本就无
store）」，也可能是「曾消费后被删」，二者从 store 内容上无法区分。

—— 本模块的三层结构 ——
1) **哈希链账本**（authoritative，`<store>.chain`）：append-only，genesis 根 + 逐条 prev→hash
   链接。任一条目被改/删/插 → 链断 → verify_chain 抛 ConsumedLedgerTampered（fail-closed）。
2) **per-batch genesis 锚**（design point 2）：每条消费记录绑定 batch_genesis =
   H(envelope_sha256 || batch_id)。验证方在消费时用同一公式**独立重算**期望 genesis 并写入，
   经哈希链锚定后不可篡改；改任一 batch_genesis 即断链。
3) **外部锚**（`<state_dir>/.consumed_anchor/<key>.anchor`，**位于 approvals/ 之外**）：
   记录链的 head/count（可选 HMAC 认证）。用于**删除检出**——
     · 锚存在 但 链文件缺失 → 判定「曾建后被删」→ CONSUMED_LEDGER_TAMPERED（fail-closed）；
     · 锚与链均缺失 → 判定「合法首用」→ 空集放行；
     · 删链后**重建自洽空链**（伪 genesis）→ 空链 head==根 ≠ 锚记录的真 head → 篡改。
   锚落在 approvals/ 之外，故「rm approvals/consumed.json*」或「rm -rf approvals/」均被检出。

—— 诚实边界（residual）——
锚与链若被**同时**抹除（如 `rm -rf <state_dir>`），或攻击者**持有 HMAC 密钥**（本仓对称密钥
与 state 同域），则无本地方案可区分冷启动与全量抹除——需**仓外锚**（git/远端 audit）才能真闭合。
本模块把「删 store 文件 / 删 approvals 目录 / 伪 genesis 重建 / 断链 / 截断 / 损坏」全部 fail-closed，
是相对基线的实质收口；全域抹除与密钥失陷登记为 residual。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import List, Optional

_LEDGER_VERSION = "abcr-consumed-ledger-v1"
# 全局链根：固定域分隔常量的摘要（链的第一条 prev）。
GENESIS_ROOT = hashlib.sha256(_LEDGER_VERSION.encode("utf-8") + b":root").hexdigest()
_MIGRATED = "<migrated-legacy>"   # 旧 list[str] 迁入链时的占位 batch 标记


class ConsumedStoreError(Exception):
    """consumed 账本损坏/不可读/被截断/格式非法。fail-closed：宁可拒绝一切消费也不当空集
    使已花令牌复活（F-TOKEN-02/34；与旧 V2 'K5 损坏按空集' 语义相反——旧语义 fail-open）。"""


class ConsumedLedgerTampered(ConsumedStoreError):
    """哈希链断裂 / genesis 不符 / 外部锚指示 store 被删或被重建。fail-closed（F-TOKEN-02 删除向量）。
    继承 ConsumedStoreError：上层 verify_token 统一映射为 'consumed_store_unreadable:<类名>'，
    既保持既有前缀契约，又以类名区分「篡改」与「损坏」。"""


# --------------------------------------------------------------------------- 派生路径
def chain_path(store: Path) -> Path:
    """哈希链账本路径（authoritative）：与 store 同目录，追加 .chain 后缀。"""
    store = Path(store)
    return store.with_name(store.name + ".chain")


def _anchor_root(store: Path) -> Path:
    """外部锚根目录：**刻意置于 store 目录之外**，使「删 store 文件 / 删 approvals 目录」被检出。
    契约布局 state_dir/approvals/consumed.json → 锚落 state_dir/.consumed_anchor/。
    其它布局（如测试 tmp/consumed.json）→ 落 store 父目录的父目录（若可），否则父目录。"""
    store = Path(store)
    parent = store.parent
    if parent.name == "approvals":
        base = parent.parent
    else:
        base = parent.parent if parent.parent != parent else parent
    return base / ".consumed_anchor"


def anchor_path(store: Path) -> Path:
    """外部锚文件路径：以 store 绝对路径摘要为键，多 store 互不覆盖。"""
    abspath = os.path.abspath(str(store))
    key16 = hashlib.sha256(abspath.encode("utf-8")).hexdigest()[:16]
    return _anchor_root(store) / f"{key16}.anchor"


# --------------------------------------------------------------------------- genesis / 链原语
def genesis(envelope_sha256: str, batch_id: str) -> str:
    """per-batch genesis 锚（design point 2）= H(envelope_sha256 || batch_id)。
    验证方在**消费与验证**时用同一公式独立重算；写入哈希链后经链锚定不可篡改。"""
    material = f"{_LEDGER_VERSION}:batch:{envelope_sha256}|{batch_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _entry_core_json(seq: int, token_id: str, batch_id: str, batch_genesis: str) -> str:
    """条目哈希覆盖的规范化核心（紧凑 separators + sort_keys，勿改——签哈希口径）。"""
    return json.dumps(
        {"seq": seq, "token_id": token_id, "batch_id": batch_id, "batch_genesis": batch_genesis},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def _link_hash(prev_hash: str, core_json: str) -> str:
    return hashlib.sha256(f"{prev_hash}|{core_json}".encode("utf-8")).hexdigest()


def verify_chain(data: dict) -> List[dict]:
    """校验哈希链结构与完整性；通过返回 entries（list[dict]），否则抛 ConsumedLedgerTampered。
    检查：顶层类型/版本/genesis 根、entries 为 list、seq 连续从 1、prev 正确（首条=根）、逐条重算 hash 相符。"""
    if not isinstance(data, dict):
        raise ConsumedLedgerTampered("chain 顶层非 object")
    if data.get("format") != _LEDGER_VERSION:
        raise ConsumedLedgerTampered(f"chain 版本不符: {data.get('format')!r}")
    if data.get("genesis") != GENESIS_ROOT:
        raise ConsumedLedgerTampered("chain genesis 根不符（伪 genesis / 版本漂移）")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ConsumedLedgerTampered("chain entries 非 list")
    prev = GENESIS_ROOT
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise ConsumedLedgerTampered(f"entry[{i}] 非 object")
        seq, tid, bid, bg = e.get("seq"), e.get("token_id"), e.get("batch_id"), e.get("batch_genesis")
        if seq != i + 1:
            raise ConsumedLedgerTampered(f"entry[{i}] seq 断裂: {seq!r}")
        if not (isinstance(tid, str) and isinstance(bid, str) and isinstance(bg, str)):
            raise ConsumedLedgerTampered(f"entry[{i}] 字段类型非法")
        if e.get("prev") != prev:
            raise ConsumedLedgerTampered(f"entry[{i}] prev 断链")
        want = _link_hash(prev, _entry_core_json(seq, tid, bid, bg))
        if e.get("hash") != want:
            raise ConsumedLedgerTampered(f"entry[{i}] hash 不符（内容被篡改）")
        prev = want
    return entries


def _chain_head(entries: List[dict]) -> str:
    return entries[-1]["hash"] if entries else GENESIS_ROOT


# --------------------------------------------------------------------------- 原子写
def _atomic_write_text(path: Path, text: str) -> None:
    """原子落盘：写 tmp → fsync(file) → os.replace → fsync(dir)（掉电/并发不产生半截文件）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


# --------------------------------------------------------------------------- 锚
def _anchor_mac(head: str, count: int, verify_secret: Optional[bytes]) -> Optional[str]:
    if not verify_secret:
        return None
    msg = f"{head}|{count}|{GENESIS_ROOT}".encode("utf-8")
    return hmac.new(verify_secret, msg, hashlib.sha256).hexdigest()


def _write_anchor(store: Path, head: str, count: int, verify_secret: Optional[bytes]) -> None:
    ap = anchor_path(store)
    payload = {"head": head, "count": count, "root": GENESIS_ROOT,
               "mac": _anchor_mac(head, count, verify_secret)}
    _atomic_write_text(ap, json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _read_anchor(store: Path) -> Optional[dict]:
    ap = anchor_path(store)
    if not ap.exists():
        # A broken symlink (present-but-unresolvable) is suspicious, not "absent":
        # treating it as absent would let an attacker neutralise the delete-detect
        # anchor by replacing it with a dangling link. Fail-closed.
        if ap.is_symlink():
            raise ConsumedLedgerTampered("anchor 是悬空 symlink（present-but-unresolvable，拒绝）")
        return None
    try:
        raw = ap.read_text(encoding="utf-8")
    except OSError as e:
        raise ConsumedLedgerTampered(f"anchor 不可读: {e}") from e
    if raw.strip() == "":
        raise ConsumedLedgerTampered("anchor 被截断为空")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise ConsumedLedgerTampered(f"anchor 损坏: {e}") from e
    if not isinstance(data, dict) or "head" not in data or "count" not in data:
        raise ConsumedLedgerTampered("anchor 结构非法")
    return data


def _load_projection(store: Path) -> Optional[List[str]]:
    """读旧口径 list[str] 投影文件（consumed.json 本体）。
    返回 None=文件不存在；否则返回 list[str]；损坏/截断/非 list[str] → 抛 ConsumedStoreError。"""
    p = Path(store)
    if not p.exists():
        return None
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ConsumedStoreError(f"unreadable: {e}") from e
    if raw.strip() == "":
        raise ConsumedStoreError("empty/truncated consumed store")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise ConsumedStoreError(f"corrupt json: {e}") from e
    if not isinstance(data, list) or any(not isinstance(x, str) for x in data):
        raise ConsumedStoreError("consumed store 不是 list[str]")
    return data


def _load_chain(store: Path) -> Optional[List[dict]]:
    """读哈希链账本。None=不存在；否则 verify_chain 通过返回 entries，损坏/断链→抛（fail-closed）。"""
    cp = chain_path(store)
    if not cp.exists():
        return None
    try:
        raw = cp.read_text(encoding="utf-8")
    except OSError as e:
        raise ConsumedLedgerTampered(f"chain 不可读: {e}") from e
    if raw.strip() == "":
        raise ConsumedLedgerTampered("chain 被截断为空")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise ConsumedLedgerTampered(f"chain 损坏: {e}") from e
    return verify_chain(data)


# --------------------------------------------------------------------------- 对外：读 / 写
def load_consumed(store: Path, *, verify_secret: Optional[bytes] = None) -> set:
    """读已消费 token_id 集合，**fail-closed**（F-TOKEN-02）。

    判定矩阵（chain=哈希链账本, proj=旧 list 投影, anchor=外部锚）：
      · chain 存在 → 以链为准（authoritative）：
          - anchor 存在且带 mac 且 verify_secret 给定 → 校验 mac，不符→篡改；
          - anchor 存在 → 校验 head/count 与链一致，不符→篡改（伪 genesis 重建等）；
          - 同时 proj 存在则必须为合法 list[str]（否则→损坏 fail-closed，兼容旧损坏检出）；
          - 返回链中全部 token_id。
      · chain 不存在 但 anchor 存在 → **曾建后被删** → ConsumedLedgerTampered（fail-closed，删除向量）。
      · chain 不存在 且 anchor 不存在：
          - proj 存在为合法 list[str] → 旧格式/迁移前，返回其集合；损坏→抛；
          - proj 也不存在 → 合法首用，返回空集。
    """
    store = Path(store)
    anchor = _read_anchor(store)
    entries = _load_chain(store)

    if entries is not None:
        # 链存在：链为准
        if anchor is not None:
            ac = int(anchor.get("count", -1))
            ah = anchor.get("head")
            # 锚自认证：mac 覆盖锚自己记录的 (head,count)，无密钥不可伪造下调（防裁剪 + 改锚自洽）。
            # F-TOKEN-02-R3-01：verify_secret 在场即**要求 keyed 完整性**——mac 必须存在且校验通过。
            # 缺失/null mac 是 alg=none 式降级（CWE-347）：能写锚但读不到密钥的攻击者剥掉 mac + 伪造
            # keyless 空链即可复活令牌。故 mac is None 直接判篡改，不再把校验 gate 在攻击者可控的 mac 字段上。
            if verify_secret:
                mac = anchor.get("mac")
                if mac is None:
                    raise ConsumedLedgerTampered("anchor 缺 mac 但 verify_secret 在场（alg=none 降级，拒绝）")
                want_mac = _anchor_mac(str(ah), ac, verify_secret)
                if not hmac.compare_digest(str(mac), str(want_mac)):
                    raise ConsumedLedgerTampered("anchor mac 不符（无密钥伪造 / 链被裁剪）")
            # 锚必须是**当前 append-only 链的一个前缀**：
            #   · ac > len(entries) → 链被裁剪/删后重建（伪 genesis 空链）→ 篡改；
            #   · 锚记录的 head 须等于该前缀末端 hash（ac==0 时=根）→ 否则篡改。
            # 该「前缀」判定对「写链后、写锚前」的无锁并发读天然容错（锚滞后≤1 次 append 仍是合法前缀）。
            if ac < 0 or ac > len(entries):
                raise ConsumedLedgerTampered("anchor count 超出链长（链被裁剪 / 伪 genesis 重建）")
            expected_head_at_ac = GENESIS_ROOT if ac == 0 else entries[ac - 1]["hash"]
            if ah != expected_head_at_ac:
                raise ConsumedLedgerTampered("anchor head 非链前缀末端（链被替换 / 伪 genesis 重建）")
        # proj 存在则必须合法（承接旧损坏检出契约）；不存在不强求
        _load_projection(store)
        return {e["token_id"] for e in entries}

    # 链不存在
    if anchor is not None:
        raise ConsumedLedgerTampered("consumed 链缺失但外部锚存在——store 被删除（F-TOKEN-02 删除向量）")

    proj = _load_projection(store)
    if proj is None:
        return set()          # 合法首用
    return set(proj)          # 旧 list 格式（迁移前）


def append(store: Path, *, token_id: str, batch_id: str, batch_genesis: str,
           verify_secret: Optional[bytes] = None) -> None:
    """向账本追加一条消费记录（append-only）。**调用方须已持 store 文件锁**（与 approval_token 的
    flock 临界区配合）。原子更新：哈希链账本 → list 投影 → 外部锚（锚**最后**写，掉电不误报删除）。

    先 load_consumed（fail-closed）：链/锚被篡改则不追加、直接抛，绝不在坏账本上续写掩盖篡改。
    旧 list 投影迁入：若链尚不存在但 proj 有历史 token_id，先把它们作为 <migrated> 条目铺进链，
    不丢历史消费态。"""
    store = Path(store)
    # 1) 载入现状（fail-closed）
    existing = load_consumed(store, verify_secret=verify_secret)  # 篡改→抛
    entries = _load_chain(store)
    if entries is None:
        entries = []
        # 迁移旧 list 投影里的历史 token_id（链尚未建立时）
        proj = _load_projection(store)
        if proj:
            prev = GENESIS_ROOT
            for legacy_tid in proj:
                seq = len(entries) + 1
                core = _entry_core_json(seq, legacy_tid, _MIGRATED, _MIGRATED)
                h = _link_hash(prev, core)
                entries.append({"seq": seq, "token_id": legacy_tid, "batch_id": _MIGRATED,
                                "batch_genesis": _MIGRATED, "prev": prev, "hash": h})
                prev = h

    if token_id in {e["token_id"] for e in entries}:
        # 幂等：已在链中，仅确保投影/锚一致后返回
        head, count = _chain_head(entries), len(entries)
        _atomic_write_text(store, json.dumps(sorted({e["token_id"] for e in entries}),
                                             ensure_ascii=False))
        _write_anchor(store, head, count, verify_secret)
        return

    # 2) 追加新条目
    prev = _chain_head(entries)
    seq = len(entries) + 1
    core = _entry_core_json(seq, token_id, batch_id, batch_genesis)
    h = _link_hash(prev, core)
    entries.append({"seq": seq, "token_id": token_id, "batch_id": batch_id,
                    "batch_genesis": batch_genesis, "prev": prev, "hash": h})

    # 3) 原子落盘：链 → 投影 → 锚（锚最后）
    chain_obj = {"format": _LEDGER_VERSION, "genesis": GENESIS_ROOT, "entries": entries}
    _atomic_write_text(chain_path(store), json.dumps(chain_obj, ensure_ascii=False, sort_keys=True))
    token_ids = sorted({e["token_id"] for e in entries})
    _atomic_write_text(store, json.dumps(token_ids, ensure_ascii=False))
    _write_anchor(store, h, len(entries), verify_secret)
