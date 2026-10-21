"""Append-only JSONL step writer with hash chain and idempotent resume.

外部信任根接线（对抗根因①）：步骤链锚在 ZERO_HASH，链内自洽可被整链重算伪造。
finalize()/close() 收口时把「全链内容摘要 + 条目数」seal 进仓级规范锚存储
（abcr.common.external_seal，kind='step_chain'，subject_id=run_id，默认取
run_dir 目录名）；验证端用 verify_external_seal() 重算并只与规范锚比对——
不读被验证物内部/相邻目录的任何材料。原有 append/verify_chain 行为不变。
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from abcr.common import external_seal
from .errors import AbcrError, E07_STEPS_TAIL_CORRUPT, E08_CHAIN_BROKEN, E09_RESUME_CONFLICT
from .schema import validate_step, canonical_json

ZERO_HASH = "0" * 64


class StepWriter:
    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = Path(run_dir)
        self.steps_path = self.run_dir / "steps.jsonl"
        self._chain_tail = ZERO_HASH
        self._done: set[tuple[str, int, str, int]] = set()
        if self.steps_path.exists():
            self._load_existing()

    def _load_existing(self) -> None:
        lines = self.steps_path.read_text().splitlines()
        if not lines:
            return
        for i, line in enumerate(lines):
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                if i == len(lines) - 1:
                    raise AbcrError(E07_STEPS_TAIL_CORRUPT,
                                    f"tail line {i + 1} is corrupt; use --repair")
                raise AbcrError(E08_CHAIN_BROKEN, f"non-tail line {i + 1} corrupt")
            key = (d["item_id"], d["random_seed"], d["condition"], d["step_id"])
            self._done.add(key)
            self._chain_tail = d["entry_hash"]

    def load_done(self) -> set[tuple[str, int, str, int]]:
        return set(self._done)

    def is_done(self, item_id: str, random_seed: int, condition: str, step_id: int = 0) -> bool:
        return (item_id, random_seed, condition, step_id) in self._done

    def append(self, step_dict: dict[str, Any]) -> None:
        key = (step_dict["item_id"], step_dict["random_seed"],
               step_dict["condition"], step_dict["step_id"])
        if key in self._done:
            raise AbcrError(E09_RESUME_CONFLICT, f"duplicate step: {key}")

        step_dict["prev_hash"] = self._chain_tail
        cj = canonical_json(step_dict)
        entry_hash = hashlib.sha256((cj + self._chain_tail).encode()).hexdigest()
        step_dict["entry_hash"] = entry_hash

        validate_step(step_dict)

        line = json.dumps(step_dict, ensure_ascii=False, sort_keys=False)
        with open(self.steps_path, "a") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

        self._chain_tail = entry_hash
        self._done.add(key)

    # ---- 外部信任根（external_seal 接线；不改变既有 append/verify_chain 语义）----

    @staticmethod
    def _load_entries(steps_path: Path) -> list[dict[str, Any]]:
        """全量读 steps.jsonl 条目（供摘要重算；行损坏直接抛 E08）。"""
        if not steps_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for i, line in enumerate(steps_path.read_text().splitlines()):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                raise AbcrError(E08_CHAIN_BROKEN, f"line {i + 1} not valid JSON")
        return entries

    def head_and_length(self) -> tuple[str, int]:
        """(全链内容摘要, 条目数)。摘要=external_seal.chain_digest_and_length，
        承诺每条记录全部内容（不是只承诺 entry_hash 列）。"""
        return external_seal.chain_digest_and_length(self._load_entries(self.steps_path))

    def finalize(self, run_id: str | None = None,
                 extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """收口：把当前步骤链 seal 进规范锚存储，返回锚记录。

        kind='step_chain'，subject_id=run_id（默认 run_dir 目录名）。
        重复 finalize 合法（append-only 重封，verify 取最后一条锚）。
        """
        subject_id = run_id or self.run_dir.name
        digest, length = self.head_and_length()
        meta = {"steps_path": str(self.steps_path), "chain_tail": self._chain_tail}
        if extra:
            meta.update(extra)
        return external_seal.seal(external_seal.KIND_STEP_CHAIN, subject_id,
                                  digest, length, extra=meta)

    def close(self, run_id: str | None = None) -> dict[str, Any]:
        """finalize 别名：收口即 seal。"""
        return self.finalize(run_id=run_id)

    @staticmethod
    def verify_external_seal(path: str | Path,
                             run_id: str | None = None) -> tuple[bool, str]:
        """验证端：重算 steps 链并【只】与规范锚比对。fail-closed。

        - path 可以是 run_dir 或 steps.jsonl 本身；subject_id 默认取
          run_dir 目录名（与 finalize 缺省一致）。
        - 先跑内部 verify_chain（链内自洽），再重算内容摘要与条目数，
          交给 external_seal.verify：缺锚 → False('no external seal')；
          length 或 digest 任一不符 → False。
        - 绝不做多路径搜索：被验证物内部/相邻目录的影子锚文件零影响。
        """
        p = Path(path)
        steps_path = p / "steps.jsonl" if p.is_dir() else p
        subject_id = run_id or steps_path.parent.name
        if not steps_path.exists():
            return False, "steps file missing"
        try:
            StepWriter.verify_chain(steps_path)
        except AbcrError as e:
            return False, f"internal chain invalid: {e}"
        digest, length = external_seal.chain_digest_and_length(
            StepWriter._load_entries(steps_path))
        return external_seal.verify(external_seal.KIND_STEP_CHAIN,
                                    subject_id, digest, length)

    @staticmethod
    def verify_chain(path: str | Path) -> bool:
        path = Path(path)
        if not path.exists():
            raise AbcrError(E08_CHAIN_BROKEN, "steps file does not exist")
        lines = path.read_text().splitlines()
        if not lines:
            return True
        prev = ZERO_HASH
        for i, line in enumerate(lines):
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                raise AbcrError(E08_CHAIN_BROKEN, f"line {i + 1} not valid JSON")
            expected_prev = d.get("prev_hash")
            if expected_prev != prev:
                raise AbcrError(E08_CHAIN_BROKEN,
                                f"line {i + 1}: prev_hash mismatch (expected {prev[:16]}..., got {str(expected_prev)[:16]}...)")
            cj = canonical_json(d)
            computed = hashlib.sha256((cj + prev).encode()).hexdigest()
            if d.get("entry_hash") != computed:
                raise AbcrError(E08_CHAIN_BROKEN,
                                f"line {i + 1}: entry_hash mismatch")
            prev = computed
        return True

    @staticmethod
    def repair(run_dir: str | Path) -> dict[str, Any]:
        run_dir = Path(run_dir)
        steps_path = run_dir / "steps.jsonl"
        ts = time.strftime("%Y%m%d-%H%M%S")
        crashed_path = steps_path.with_name(f"steps.jsonl.crashed-{ts}")
        steps_path.rename(crashed_path)

        valid_lines: list[str] = []
        for line in crashed_path.read_text().splitlines():
            try:
                json.loads(line)
                valid_lines.append(line)
            except json.JSONDecodeError:
                break

        prev = ZERO_HASH
        repaired: list[str] = []
        for line in valid_lines:
            d = json.loads(line)
            d["prev_hash"] = prev
            cj = canonical_json(d)
            entry_hash = hashlib.sha256((cj + prev).encode()).hexdigest()
            d["entry_hash"] = entry_hash
            repaired.append(json.dumps(d, ensure_ascii=False, sort_keys=False))
            prev = entry_hash

        steps_path.write_text("\n".join(repaired) + ("\n" if repaired else ""))

        return {
            "type": "repair",
            "timestamp": ts,
            "crashed_file": str(crashed_path),
            "original_lines": len(crashed_path.read_text().splitlines()),
            "valid_lines": len(repaired),
        }
