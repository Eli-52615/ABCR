"""Versioned persona artifacts and one-component parent-diff guard."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from abcr.control.contracts import ContractError, canonical_json, require_id, sha256, strict_object


@dataclass(frozen=True)
class PersonaArtifact:
    persona_id: str
    version: int
    parent_ref: str | None
    components: dict[str, str]
    changed_component: str | None
    manipulation_checks: tuple[str, ...]

    @property
    def ref(self) -> str:
        return f"{self.persona_id}@v{self.version}"

    @property
    def digest(self) -> str:
        return sha256({"persona_id": self.persona_id, "version": self.version,
                       "parent_ref": self.parent_ref, "components": self.components,
                       "changed_component": self.changed_component,
                       "manipulation_checks": self.manipulation_checks})

    def render(self) -> str:
        return "\n".join(self.components[k] for k in sorted(self.components))


def parse_persona(obj: dict[str, Any], parent: PersonaArtifact | None = None) -> PersonaArtifact:
    obj = strict_object(obj, required={"persona_id", "version", "parent_ref", "components",
                                              "changed_component", "manipulation_checks"})
    require_id(obj["persona_id"], "persona_id")
    if isinstance(obj["version"], bool) or not isinstance(obj["version"], int) or obj["version"] < 1:
        raise ContractError("bad_persona_version", "persona version 必须是正整数")
    if not isinstance(obj["components"], dict) or not obj["components"] or not all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in obj["components"].items()):
        raise ContractError("bad_persona_components", "components 必须是非空文字 mapping")
    checks = obj["manipulation_checks"]
    if not isinstance(checks, list) or not checks or not all(isinstance(x, str) and x.strip() for x in checks):
        raise ContractError("bad_manipulation_checks", "manipulation_checks 必须非空")
    artifact = PersonaArtifact(obj["persona_id"], obj["version"], obj["parent_ref"],
                               dict(obj["components"]), obj["changed_component"], tuple(checks))
    if parent is None:
        if artifact.version != 1 or artifact.parent_ref is not None or artifact.changed_component is not None:
            raise ContractError("bad_persona_root", "v1 人格必须无 parent 和 changed_component")
        return artifact
    if artifact.parent_ref != parent.ref or artifact.version != parent.version + 1:
        raise ContractError("persona_lineage", "parent_ref 或 version 不连续")
    all_keys = set(parent.components) | set(artifact.components)
    changed = [key for key in all_keys if parent.components.get(key) != artifact.components.get(key)]
    if changed != [artifact.changed_component] or artifact.changed_component is None:
        raise ContractError("persona_multi_component_diff", "子人格必须且只能改变一个登记组件",
                            {"actual_changed": sorted(changed), "declared": artifact.changed_component})
    return artifact


class PersonaRegistry:
    def __init__(self):
        self._by_ref: dict[str, PersonaArtifact] = {}

    def add(self, obj: dict[str, Any]) -> PersonaArtifact:
        parent_ref = obj.get("parent_ref")
        parent = self._by_ref.get(parent_ref) if parent_ref else None
        artifact = parse_persona(obj, parent)
        if artifact.ref in self._by_ref:
            raise ContractError("persona_duplicate", f"人格版本已存在: {artifact.ref}")
        self._by_ref[artifact.ref] = artifact
        return artifact

    def get(self, ref: str) -> PersonaArtifact:
        try:
            return self._by_ref[ref]
        except KeyError as exc:
            raise ContractError("persona_unknown", f"未登记人格: {ref}") from exc

    def load_dir(self, root: Path) -> None:
        pending = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(root).glob("*.json"))]
        while pending:
            before = len(pending)
            for obj in pending[:]:
                if obj.get("parent_ref") is None or obj.get("parent_ref") in self._by_ref:
                    self.add(obj); pending.remove(obj)
            if len(pending) == before:
                raise ContractError("persona_lineage_cycle", "人格谱系存在缺失父本或循环")

    @property
    def registry_hash(self) -> str:
        return sha256([{"ref": ref, "digest": item.digest} for ref, item in sorted(self._by_ref.items())])


def save_persona(path: Path, artifact: PersonaArtifact) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json({"persona_id": artifact.persona_id, "version": artifact.version,
                                     "parent_ref": artifact.parent_ref, "components": artifact.components,
                                     "changed_component": artifact.changed_component,
                                     "manipulation_checks": list(artifact.manipulation_checks)}) + b"\n")
