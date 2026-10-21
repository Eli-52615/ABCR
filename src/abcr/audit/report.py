"""abcr.audit.report —— AuditReport 数据结构 + 双格式同源输出（A1-7）。

架构位置：包A·验船师侧。JSON（机器可读，C 的同步视图消费）与 MD（人读）同源生成
——MD 由 JSON 渲染，禁止两处手写。verdict ∈ {PASS, FAIL, SKIP}（SKIP 必附原因）；
overall = 全 PASS 才 PASS；FAIL 项 evidence 必含证据指针（文件路径 + 行/链尾哈希）。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

AUDIT_SCHEMA_VERSION = "1.0"
AUDITOR_VERSION = "a-audit/1.0.0"

_ITEM_NAMES = {
    0: "batch_evidence_floor",
    1: "manifest_completeness", 2: "rescore_comparison",
    3: "contamination", 4: "health_panel",
    5: "version_consistency", 6: "cost_reconciliation",
}
# 批级地板项（id=0）：它检查的是"这批到底有没有证据可审"（run 集非空 + 账本链外部锚），
# 不是任何一项实质审计。它的 PASS **不得**替代实质审计项去满足 overall 的 ≥1 PASS 地板，
# 否则"把所有实质项做成数据缺位 → 全 SKIP + 地板项 PASS → 绿"又是一条绕过路径。
NON_SUBSTANTIVE_ITEM_IDS = frozenset({0})


@dataclass
class AuditItem:
    id: int
    name: str
    verdict: str                       # PASS | FAIL | SKIP
    evidence: list[str] = field(default_factory=list)
    disposition: Optional[str] = None
    substantive: bool = True           # False = 元/地板项，其 PASS 不满足 overall 地板

    @staticmethod
    def make(item_id: int, verdict: str, evidence: list[str],
             disposition: Optional[str] = None) -> "AuditItem":
        return AuditItem(id=item_id, name=_ITEM_NAMES.get(item_id, f"item{item_id}"),
                         verdict=verdict, evidence=evidence, disposition=disposition,
                         substantive=item_id not in NON_SUBSTANTIVE_ITEM_IDS)


@dataclass
class AuditReport:
    batch_id: str
    generated_at: str
    thresholds: dict[str, float]
    items: list[AuditItem] = field(default_factory=list)
    evidence_pointers: dict = field(default_factory=dict)
    audit_schema_version: str = AUDIT_SCHEMA_VERSION
    auditor_version: str = AUDITOR_VERSION

    @property
    def overall(self) -> str:
        """任一 FAIL → FAIL；无任何实质 PASS 项（全 SKIP / 空）→ FAIL；否则 PASS。

        根因②闭合（空/缺失被当成功）：原实现"无 FAIL 即 PASS"会让一份**全 SKIP**
        （或压根没跑任何项）的审计报告拿到 overall=PASS——等价攻击"把所有检查都做成
        数据缺位 → 全 SKIP → 绿"直接绕过验船。此处加实质项地板：overall=PASS 必须
        至少有一项**实质**项真正 PASS，否则 fail-closed。SKIP 不再单独构成通过；
        批级地板项（substantive=False）也不构成通过——它只证明"有东西可审"，
        不证明"审过了"。
        """
        if any(it.verdict == "FAIL" for it in self.items):
            return "FAIL"
        if not any(it.verdict == "PASS" and it.substantive for it in self.items):
            return "FAIL"
        return "PASS"

    def to_dict(self) -> dict:
        return {
            "audit_schema_version": self.audit_schema_version,
            "batch_id": self.batch_id,
            "generated_at": self.generated_at,
            "auditor_version": self.auditor_version,
            "thresholds": self.thresholds,
            "items": [asdict(it) for it in self.items],
            "overall": self.overall,
            "evidence_pointers": self.evidence_pointers,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_md(self) -> str:
        """由 to_dict() 渲染（同源，禁两处手写）。"""
        d = self.to_dict()
        badge = "✅ PASS" if d["overall"] == "PASS" else "❌ FAIL"
        lines = [
            f"# 审计报告 · {d['batch_id']}",
            "",
            f"- **overall**: {badge}",
            f"- 生成时间: {d['generated_at']}",
            f"- auditor: {d['auditor_version']}",
            f"- 阈值: {json.dumps(d['thresholds'], ensure_ascii=False)}",
            "",
            "## 逐项结果",
            "",
            "| # | 项 | verdict | 处置 |",
            "|---|---|---|---|",
        ]
        for it in d["items"]:
            disp = it.get("disposition") or "-"
            lines.append(f"| {it['id']} | {it['name']} | {it['verdict']} | {disp} |")
        lines.append("")
        lines.append("## 证据")
        lines.append("")
        for it in d["items"]:
            lines.append(f"### item {it['id']} · {it['name']} — {it['verdict']}")
            lines.append("")
            lines.append("```")
            for e in it["evidence"]:
                lines.append(e)
            if not it["evidence"]:
                lines.append("(无证据行)")
            lines.append("```")
            lines.append("")
        # 证据指针
        lines.append("## 证据指针")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(d["evidence_pointers"], ensure_ascii=False, indent=2))
        lines.append("```")
        return "\n".join(lines) + "\n"

    def write(self, repo_root: Path) -> tuple[Path, Path]:
        """同源写 reports/audit/<batch_id>.{json,md}。整文件原子写（tmp+replace，坑6）。"""
        out_dir = Path(repo_root) / "reports" / "audit"
        out_dir.mkdir(parents=True, exist_ok=True)
        json_p = out_dir / f"{self.batch_id}.json"
        md_p = out_dir / f"{self.batch_id}.md"
        for path, content in ((json_p, self.to_json()), (md_p, self.to_md())):
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
        return json_p, md_p
