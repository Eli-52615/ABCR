"""abcr.governor.shadow —— 影子模式：草案 vs 人工最终决策差异记录（契约 §C2-1）。

架构位置：包C·Governor。阶段2 起对真实批次记录"planner 草案 vs 人工最终信封"的
结构化差异。人批人派不变——本模块只观察、只记录，永不签发令牌、永不写账本、永不改信封。
差异记录是阶段3「信封内自动派发」毕业判据的证据流（毕业检查器见 scripts/c_shadow_graduation.py）。

工作流约定（人工执行序）：
  1. `abcrctl draft <spec>` 出草案后，立即 `cp configs/envelopes/<batch_id>.json
     plans/shadow/<batch_id>.draft.json` 一份草案快照（人随后可能就地改信封）；
  2. 人（楠/fable）自行决定最终信封并 `abcrctl approve`；
  3. 跑 `python -m abcr.governor.shadow --draft plans/shadow/<batch_id>.draft.json
     --final configs/envelopes/<batch_id>.json [--notes "人口述"]` 产差异记录。
  notes 由人口述、你转录——只记事实不记评价。

关键差异定义（冻结措辞，毕业判据用；与 §7.2 逐字同一）：
  预算维度 budget.gpu_hours_max / budget.cost_cap_cny、条件集合 set(scope.conditions)、
  split 选择 set(scope.splits)、题量 scope.item_limit_per_run —— 任一不同即关键差异；
  措辞差异不算。seeds / trait_whitelist / deadline / run_configs / goal = 非关键（照记，不入判定）。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from abcr.common import external_seal
from abcr.governor.envelope import envelope_sha256

SHADOW_VERSION = "1.0"
SHADOW_KIND = "shadow_diff"   # external_seal kind：影子差异记录锚在仓级规范锚存储

# (维度名, 取值函数, 是否关键, 是否集合语义)
_KEY_DIMS = (
    ("budget.gpu_hours_max", lambda e: e.get("budget", {}).get("gpu_hours_max"), True, False),
    ("budget.cost_cap_cny", lambda e: e.get("budget", {}).get("cost_cap_cny"), True, False),
    ("conditions", lambda e: e.get("scope", {}).get("conditions", []), True, True),
    ("splits", lambda e: e.get("scope", {}).get("splits", []), True, True),
    ("item_limit_per_run", lambda e: e.get("scope", {}).get("item_limit_per_run"), True, False),
)
_NONKEY_DIMS = (
    ("seeds", lambda e: e.get("scope", {}).get("seeds", []), False, True),
    ("trait_whitelist", lambda e: e.get("scope", {}).get("trait_whitelist", []), False, True),
)


def _diff_one(draft_val: object, final_val: object, is_set: bool) -> tuple[object, object, bool]:
    """返回 (draft_呈现值, final_呈现值, diff)。集合语义：先 set 化再比（列表乱序不算差异）。"""
    if is_set:
        d = list(draft_val) if isinstance(draft_val, (list, tuple)) else draft_val
        f = list(final_val) if isinstance(final_val, (list, tuple)) else final_val
        try:
            diff = set(draft_val or []) != set(final_val or [])
        except TypeError:  # 不可哈希元素 → 退化为有序相等
            diff = list(draft_val or []) != list(final_val or [])
        return d, f, diff
    return draft_val, final_val, draft_val != final_val


def compare(draft: dict, final: dict) -> dict:
    """纯函数：逐维比较草案与最终信封，产出 dimensions 表 + key_difference。

    集合维度（conditions/splits/seeds/trait_whitelist）先 set 化再比——列表乱序不算差异。
    key_difference = 任一 key=true 维度 diff=true。
    """
    dimensions: dict[str, dict] = {}
    key_difference = False
    for name, getter, is_key, is_set in (*_KEY_DIMS, *_NONKEY_DIMS):
        d, f, diff = _diff_one(getter(draft), getter(final), is_set)
        dimensions[name] = {"draft": d, "final": f, "key": is_key, "diff": diff}
        if is_key and diff:
            key_difference = True
    return {"dimensions": dimensions, "key_difference": key_difference}


def build_record(draft: dict, final: dict, draft_path: str, final_path: str,
                 notes: str = "", compared_at: str | None = None) -> dict:
    """组装差异记录 v1（§C2-1 格式）。哈希单点走 envelope.envelope_sha256（去 approval）。"""
    cmp = compare(draft, final)
    return {
        "shadow_version": SHADOW_VERSION,
        "batch_id": final.get("batch_id") or draft.get("batch_id"),
        "draft_path": draft_path,
        "draft_envelope_sha256": envelope_sha256(draft),
        "final_envelope_path": final_path,
        "final_envelope_sha256": envelope_sha256(final),
        "compared_at": compared_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dimensions": cmp["dimensions"],
        "key_difference": cmp["key_difference"],
        "notes": notes,
    }


def _record_digest_length(rec: dict) -> tuple[str, int]:
    """对整条差异记录算 (内容摘要, 1)。生产端 seal 与验证端 verify 共用本函数
    → 记录任一字节被改（key_difference 翻真为假、维度值改动）外部 verify 即失配。"""
    return external_seal.chain_digest_and_length([rec])


def seal_record(rec: dict) -> dict:
    """把差异记录锚进仓级规范锚存储（对抗根因①：plans/shadow/*.shadow.json 可手写伪造）。
    subject_id=batch_id；extra 附 key_difference 供人工审读。返回锚记录。"""
    digest, length = _record_digest_length(rec)
    return external_seal.seal(SHADOW_KIND, rec["batch_id"], digest, length,
                              extra={"key_difference": bool(rec.get("key_difference"))})


def verify_seal(rec: dict) -> tuple[bool, str]:
    """验证端：重算记录摘要并只与规范锚比对（fail-closed）。缺锚/失配 → (False, reason)。
    毕业检查器据此把"无锚/被篡改"的 shadow 记录排除计数。"""
    bid = rec.get("batch_id")
    if not bid:
        return False, "shadow record missing batch_id"
    digest, length = _record_digest_length(rec)
    return external_seal.verify(SHADOW_KIND, bid, digest, length)


def run(draft_path: Path, final_path: Path, out_dir: Path = Path("plans/shadow"),
        notes: str = "") -> Path:
    """读草案 + 最终信封 → 产 plans/shadow/<batch_id>.shadow.json，并 seal 进外部锚根。"""
    draft_path, final_path = Path(draft_path), Path(final_path)
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    final = json.loads(final_path.read_text(encoding="utf-8"))
    rec = build_record(draft, final, str(draft_path), str(final_path), notes)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{rec['batch_id']}.shadow.json"
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    seal_record(rec)   # 外部信任根：毕业计数只认已锚记录
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="abcr.governor.shadow",
                                 description="草案 vs 人工最终决策差异记录（§C2-1）")
    ap.add_argument("--draft", required=True, help="草案快照 plans/shadow/<id>.draft.json")
    ap.add_argument("--final", required=True, help="人工最终信封 configs/envelopes/<id>.json")
    ap.add_argument("--out-dir", default="plans/shadow")
    ap.add_argument("--notes", default="", help="人口述、你转录（只记事实不记评价）")
    args = ap.parse_args()
    out = run(Path(args.draft), Path(args.final), Path(args.out_dir), args.notes)
    rec = json.loads(out.read_text(encoding="utf-8"))
    print(f"已生成: {out}")
    print(f"key_difference={rec['key_difference']}"
          + ("（关键差异——毕业计数排除此批）" if rec["key_difference"] else "（无关键差异——计入毕业）"))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
