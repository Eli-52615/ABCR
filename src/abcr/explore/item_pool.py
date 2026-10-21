"""The only primitive allowed to see the full split and export dev-only bundles."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from abcr.control.attestation import (
    DOMAIN_DEV_BUNDLE, sign_attestation, verify_attestation,
)
from abcr.control.contracts import ContractError, canonical_json, require_sha, sha256, utc_now


def _dev_bundle_seal_core(manifest: dict[str, Any]) -> dict[str, Any]:
    """封印锚定的字段:身份 + split 标签 + 内容哈希 + 来源哈希 + 精确 item 集。

    信任根是 itempool 的封印私钥,不是 bundle 自洽性。攻击者手搓一个 manifest
    自称 split=dev 但装 holdout 题,拿不到私钥就签不出匹配的封印 —— verify 时
    在验签这关 fail-closed。这正是 P0-1 缺失的外部信任根。
    """
    return {
        "bundle_id": manifest["bundle_id"],
        "split": manifest["split"],
        "item_ids": list(manifest["item_ids"]),
        "items_sha256": manifest["items_sha256"],
        "source_sha256": manifest["source_sha256"],
        "goal_hash": manifest["goal_hash"],
    }


@dataclass(frozen=True)
class SelectionRequest:
    request_id: str
    goal_hash: str
    count: int
    seed: int
    excluded_item_ids: tuple[str, ...] = ()
    created_at: str | None = None


@dataclass(frozen=True)
class DevBundleRef:
    bundle_id: str
    root: Path
    manifest_hash: str
    item_ids: tuple[str, ...]
    source_hash: str


def _read_items(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ContractError("bad_dataset", f"dataset JSON 无法解析: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("items")
    if not isinstance(data, list) or not data:
        raise ContractError("bad_dataset", "dataset 必须是非空 item list")
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("item_id"), str):
            raise ContractError("bad_item", "每题必须有字符串 item_id")
        if item["item_id"] in seen:
            raise ContractError("duplicate_item", f"重复 item_id: {item['item_id']}")
        seen.add(item["item_id"])
    return data, raw


def _read_split(path: Path) -> tuple[dict[str, list[str]], bytes]:
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or not all(isinstance(data.get(k), list) for k in ("dev", "calibration", "holdout")):
        raise ContractError("bad_split", "split 必须包含 dev/calibration/holdout 列表")
    all_ids = data["dev"] + data["calibration"] + data["holdout"]
    if not all(isinstance(item_id, str) and item_id for item_id in all_ids):
        raise ContractError("bad_split_item", "split item id 必须是非空字符串")
    if len(all_ids) != len(set(all_ids)):
        raise ContractError("split_overlap", "三个 split 存在 item 重叠")
    return data, raw


def build_dev_bundle(request: SelectionRequest, *, dataset_path: Path, split_path: Path,
                     output_root: Path, sealer_private_key: Path,
                     sealer_public_key: Path) -> DevBundleRef:
    require_sha(request.goal_hash, "goal_hash")
    if request.count < 1:
        raise ContractError("bad_count", "count 必须为正整数")
    items, dataset_raw = _read_items(Path(dataset_path))
    split, split_raw = _read_split(Path(split_path))
    by_id = {item["item_id"]: item for item in items}
    missing = set(split["dev"]) - set(by_id)
    if missing:
        raise ContractError("split_item_missing", "dev split 引用了不存在的题", {"ids": sorted(missing)})
    excluded = set(request.excluded_item_ids)
    available = [item_id for item_id in split["dev"] if item_id not in excluded]
    if len(available) < request.count:
        raise ContractError("dev_capacity", "dev 题量不足",
                            {"needed": request.count, "available": len(available)})
    ranked = sorted(available, key=lambda item_id: sha256(
        f"{request.goal_hash}:{request.seed}:{item_id}".encode()))
    selected_ids = tuple(ranked[:request.count])
    selected = [by_id[item_id] for item_id in selected_ids]
    items_raw = b"".join(canonical_json(item) + b"\n" for item in selected)
    source_hash = sha256(dataset_raw + b"\0" + split_raw)
    manifest_core = {
        "schema_version": 1, "request_id": request.request_id, "goal_hash": request.goal_hash,
        "seed": request.seed, "split": "dev", "item_ids": list(selected_ids),
        "item_count": len(selected_ids), "items_sha256": sha256(items_raw),
        "source_sha256": source_hash, "excluded_item_ids": sorted(excluded),
        "created_at": request.created_at or utc_now(),
    }
    bundle_id = sha256(manifest_core)
    manifest = dict(manifest_core, bundle_id=bundle_id,
                    files=[{"path": "items.jsonl", "size": len(items_raw), "sha256": sha256(items_raw)}])
    # itempool 用封印私钥对关键字段签名。这是 dev bundle 的外部信任根。
    seal = sign_attestation(private_key=Path(sealer_private_key),
                            public_key=Path(sealer_public_key),
                            domain=DOMAIN_DEV_BUNDLE, core=_dev_bundle_seal_core(manifest))
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    final = root / bundle_id
    if final.exists():
        existing = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
        if existing != manifest:
            raise ContractError("bundle_collision", "同 bundle_id 内容冲突")
    else:
        tmp = root / f".{bundle_id}.{uuid.uuid4().hex}.tmp"
        tmp.mkdir(mode=0o700)
        try:
            (tmp / "items.jsonl").write_bytes(items_raw)
            (tmp / "manifest.json").write_bytes(canonical_json(manifest) + b"\n")
            (tmp / "seal.json").write_bytes(canonical_json(seal) + b"\n")
            for path in (tmp / "items.jsonl", tmp / "manifest.json", tmp / "seal.json"):
                with path.open("rb") as fh:
                    os.fsync(fh.fileno())
            os.rename(tmp, final)
        finally:
            if tmp.exists():
                for child in tmp.iterdir(): child.unlink()
                tmp.rmdir()
    return DevBundleRef(bundle_id, final, sha256(manifest), selected_ids, source_hash)


def iter_bundle_items(ref: DevBundleRef, trusted_root: Path, *,
                      sealer_public_key: Path) -> Iterable[dict[str, Any]]:
    """Read a DevBundle's items. `trusted_root` and `sealer_public_key` are both mandatory.

    Every read routes through `verify_dev_bundle`, which pins the sealed root, rejects
    symlinks, enforces ``manifest["split"] == "dev"`` **and verifies the itempool seal**.
    A self-built directory labelled dev but full of holdout items fails at the seal —
    the attacker has no itempool private key. Eager (not a generator) so the gate fires
    at call time rather than on first iteration.
    """
    if trusted_root is None or not str(trusted_root).strip():
        raise ContractError("bundle_root_untrusted", "iter_bundle_items 必须显式传入非空可信根")
    manifest = verify_dev_bundle(ref, trusted_root, sealer_public_key=sealer_public_key)
    raw = (Path(ref.root).resolve() / "items.jsonl").read_bytes()
    if sha256(raw) != manifest["items_sha256"] or manifest["bundle_id"] != ref.bundle_id:
        raise ContractError("bundle_tampered", "DevBundle 内容或身份失配")
    return tuple(json.loads(line) for line in raw.splitlines())


def verify_dev_bundle(ref: DevBundleRef, trusted_root: Path, *,
                      sealer_public_key: Path) -> dict[str, Any]:
    """Reconstruct a DevBundle identity from bytes under one configured sealed root.

    `sealer_public_key` is mandatory (no default): the split label and item set are only
    trustworthy because the itempool signed them. Self-consistency of the manifest is a
    cheap precheck, never the trust root — that was exactly the P0-1 defect.
    """
    if sealer_public_key is None or not str(sealer_public_key).strip():
        raise ContractError("bundle_sealer_key_missing", "verify_dev_bundle 必须提供封印公钥")
    raw_root = Path(trusted_root)
    raw_bundle = Path(ref.root)
    if raw_root.is_symlink() or raw_bundle.is_symlink():
        raise ContractError("bundle_path_unsafe", "DevBundle root 不能是 symlink")
    root = raw_root.resolve(); bundle = raw_bundle.resolve()
    if bundle.parent != root or bundle.name != ref.bundle_id:
        raise ContractError("bundle_root_untrusted", "DevBundle 不在固定可信根的直接子目录")
    names = {path.name for path in bundle.iterdir()}
    if names != {"manifest.json", "items.jsonl", "seal.json"}:
        raise ContractError("bundle_files_unexpected", "DevBundle 文件集合不精确")
    manifest_path = bundle / "manifest.json"; items_path = bundle / "items.jsonl"
    seal_path = bundle / "seal.json"
    if manifest_path.is_symlink() or items_path.is_symlink() or seal_path.is_symlink():
        raise ContractError("bundle_path_unsafe", "DevBundle 文件不能是 symlink")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items_raw = items_path.read_bytes()
    if sha256(manifest) != ref.manifest_hash:
        raise ContractError("bundle_manifest_ref_mismatch", "DevBundle manifest hash 与引用不一致")
    if (manifest.get("bundle_id"), tuple(manifest.get("item_ids", ())),
            manifest.get("source_sha256")) != (ref.bundle_id, ref.item_ids, ref.source_hash):
        raise ContractError("bundle_identity_mismatch", "DevBundle 引用字段与 manifest 不一致")
    if manifest.get("split") != "dev" or manifest.get("items_sha256") != sha256(items_raw):
        raise ContractError("bundle_content_mismatch", "DevBundle split 或 items hash 不一致")
    observed_ids = tuple(json.loads(line)["item_id"] for line in items_raw.splitlines())
    if observed_ids != ref.item_ids or len(observed_ids) != len(set(observed_ids)):
        raise ContractError("bundle_item_set_mismatch", "DevBundle item 集合不一致")
    # ---- 信任根:itempool 封印。手搓目录到这里 fail-closed。 ----
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    ok, reason = verify_attestation(seal, public_key=Path(sealer_public_key),
                                    domain=DOMAIN_DEV_BUNDLE,
                                    expected_core=_dev_bundle_seal_core(manifest))
    if not ok:
        raise ContractError("bundle_seal_invalid", f"DevBundle 封印验签失败: {reason}")
    return manifest
