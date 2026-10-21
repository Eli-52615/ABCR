"""Adversarial checks for the code-release scientific-data boundary."""
from __future__ import annotations

import io
import gzip
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from abcr.control.contracts import ContractError, canonical_json, sha256
from abcr.control.release_policy import enforce_release_content_policy
from abcr.control.seal_broker import SealBroker
from abcr.control.worktree import scan_tree, tree_hash


ROOT = Path(__file__).resolve().parents[2]


def _zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)


def test_release_rejects_canonical_scientific_path(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    path = root / "data/benchmarks/items.json"
    path.parent.mkdir(parents=True)
    path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(ContractError) as caught:
        enforce_release_content_policy(root)

    assert caught.value.code == "release_scientific_path_forbidden"


def test_release_rejects_exact_frozen_bytes_after_rename(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    path = root / "assets/runtime-table.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes((ROOT / "data/benchmarks/ifeval_zh_v1.json").read_bytes())

    with pytest.raises(ContractError) as caught:
        enforce_release_content_policy(root)

    assert caught.value.code == "release_scientific_bytes_forbidden"


def test_release_rejects_legacy_full_item_source_after_rename(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    path = root / "assets/runtime-table.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes((ROOT / "data/items/ifeval_style/items.jsonl").read_bytes())

    with pytest.raises(ContractError) as caught:
        enforce_release_content_policy(root)

    assert caught.value.code == "release_scientific_bytes_forbidden"


@pytest.mark.parametrize("authority_key", ["items_sha256", "split_sha256"])
@pytest.mark.parametrize("wrapper", ["plain", "zip", "gzip"])
def test_release_rejects_normalized_dataset_bytes_after_rename(
        tmp_path: Path, authority_key: str, wrapper: str) -> None:
    """The normalized authority outputs must never leak through code release."""
    authority = json.loads((ROOT / "ops/install/dataset-authority-ifeval-zh-v1.json")
                           .read_text(encoding="utf-8"))
    source_name = "items.json" if authority_key == "items_sha256" else "split.json"
    # Generate the exact frozen bytes through the reviewed importer contract;
    # do not check a second scientific copy into the repository.
    benchmark = json.loads((ROOT / "data/benchmarks/ifeval_zh_v1.json")
                           .read_text(encoding="utf-8"))
    if source_name == "items.json":
        raw = json.dumps(benchmark["items"], ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    else:
        split_source = json.loads((ROOT / "data/splits/ifeval_zh_v1.json")
                                  .read_text(encoding="utf-8"))
        split = {name: sorted(item_id for item_id, value
                              in split_source["assignments"].items() if value == name)
                 for name in ("dev", "calibration", "holdout")}
        raw = json.dumps(split, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    assert sha256(raw) == authority["output"][authority_key]

    root = tmp_path / "candidate"
    root.mkdir()
    if wrapper == "plain":
        (root / "runtime-table.dat").write_bytes(raw)
    elif wrapper == "zip":
        _zip(root / "runtime-cache.dat", {"pkg/assets/table.bin": raw})
    else:
        (root / "runtime-cache.dat").write_bytes(gzip.compress(raw))

    with pytest.raises(ContractError) as caught:
        enforce_release_content_policy(root)
    assert caught.value.code == "release_scientific_bytes_forbidden"


def test_release_rejects_scientific_resource_inside_wheel(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    _zip(root / "adapter.whl", {
        "abcr_adapter/__init__.py": b"VALUE = 1\n",
        "abcr_adapter/resources/splits/dev.json": b"{}\n",
    })

    with pytest.raises(ContractError) as caught:
        enforce_release_content_policy(root)

    assert caught.value.code == "release_scientific_path_forbidden"


def test_release_rejects_renamed_frozen_bytes_inside_nested_archive(
        tmp_path: Path) -> None:
    benchmark = (ROOT / "data/benchmarks/ifeval_zh_v1.json").read_bytes()
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("pkg/assets/table.bin", benchmark)
    root = tmp_path / "candidate"
    root.mkdir()
    _zip(root / "outer.pyz", {"pkg/vendor/inner.zip": inner.getvalue()})

    with pytest.raises(ContractError) as caught:
        enforce_release_content_policy(root)

    assert caught.value.code == "release_scientific_bytes_forbidden"


def test_release_rejects_renamed_frozen_bytes_inside_gzip_stream(
        tmp_path: Path) -> None:
    benchmark = (ROOT / "data/benchmarks/ifeval_zh_v1.json").read_bytes()
    root = tmp_path / "candidate"
    root.mkdir()
    # Neither the outer filename nor the compression stream carries a
    # scientific path.  The expanded bytes must still be inspected.
    (root / "runtime-cache.dat").write_bytes(gzip.compress(benchmark))

    with pytest.raises(ContractError) as caught:
        enforce_release_content_policy(root)

    assert caught.value.code == "release_scientific_bytes_forbidden"


def test_release_rejects_unsupported_renamed_archive_magic(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    (root / "runtime-cache.dat").write_bytes(b"\x28\xb5\x2f\xfdopaque-zstd")

    with pytest.raises(ContractError) as caught:
        enforce_release_content_policy(root)

    assert caught.value.code == "release_archive_unsupported"


def test_release_rejects_archive_nesting_beyond_reviewed_depth(
        tmp_path: Path) -> None:
    payload = b"harmless at this layer\n"
    for index in range(4):
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, "w") as archive:
            archive.writestr(f"pkg/layer-{index}.zip", payload)
        payload = nested.getvalue()
    root = tmp_path / "candidate"
    root.mkdir()
    (root / "adapter.pyz").write_bytes(payload)

    with pytest.raises(ContractError) as caught:
        enforce_release_content_policy(root)

    assert caught.value.code == "release_archive_limits"


def test_safe_package_archive_remains_eligible(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    _zip(root / "adapter.whl", {
        "abcr_adapter/__init__.py": b"VALUE = 1\n",
        "abcr_adapter/resources/status.json": b'{"ok":true}\n',
    })

    enforce_release_content_policy(root)


def test_safe_dependency_tar_hardlink_is_scanned_as_bytes_not_recreated(
        tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    with tarfile.open(root / "dependency.tar.gz", "w:gz") as archive:
        raw = b"harmless timezone bytes\n"
        source = tarfile.TarInfo("pkg/zone/GMT+0")
        source.size = len(raw)
        archive.addfile(source, io.BytesIO(raw))
        alias = tarfile.TarInfo("pkg/zone/GMT0")
        alias.type = tarfile.LNKTYPE
        alias.linkname = source.name
        archive.addfile(alias)

    enforce_release_content_policy(root)


def test_tar_hardlink_cannot_escape_or_target_another_link(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    with tarfile.open(root / "dependency.tar", "w") as archive:
        alias = tarfile.TarInfo("pkg/alias")
        alias.type = tarfile.LNKTYPE
        alias.linkname = "../outside"
        archive.addfile(alias)

    with pytest.raises(ContractError) as caught:
        enforce_release_content_policy(root)
    assert caught.value.code in {
        "release_archive_path_invalid", "release_archive_member_unsafe"}


def test_root_broker_independently_rejects_release_archive_leak(
        tmp_path: Path) -> None:
    staging_root = tmp_path / "staging"
    source = staging_root / "REL-candidate"
    source.mkdir(parents=True)
    _zip(source / "adapter.whl", {
        "pkg/resources/golden/answers.jsonl": b'{"answer":42}\n',
    })
    releases = tmp_path / "releases"
    broker = SealBroker(
        {"seal_release": releases}, tmp_path / "receipts",
        source_roots={"seal_release": staging_root})

    with pytest.raises(ContractError) as caught:
        broker.seal_tree(
            "seal_release", source, nonce="n-science",
            expected_tree_hash=tree_hash(scan_tree(source)),
            object_id="REL-" + "a" * 64)

    assert caught.value.code == "release_scientific_path_forbidden"
    assert not releases.exists()


def test_legacy_receipt_cannot_grandfather_frozen_bytes_into_activation(
        tmp_path: Path) -> None:
    releases = tmp_path / "releases"
    release_id = "REL-" + "b" * 64
    sealed = releases / release_id
    path = sealed / "assets/runtime-table.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes((ROOT / "data/benchmarks/ifeval_zh_v1.json").read_bytes())
    receipts = tmp_path / "receipts"
    broker = SealBroker(
        {"seal_release": releases}, receipts,
        source_roots={"seal_release": tmp_path / "staging"})
    observed = tree_hash(scan_tree(sealed))
    core = {"operation": "seal_release", "nonce": "legacy",
            "tree_hash": observed, "object_id": release_id}
    receipt_id = sha256(core)
    receipt = {**core, "receipt_id": receipt_id,
               "sealed_tree_hash": observed, "sealed_path": str(sealed),
               "created_at": "2026-07-22T00:00:00+00:00"}
    receipt_path = receipts / f"{receipt_id}.json"
    receipt_path.write_bytes(canonical_json(receipt) + b"\n")
    receipt_path.chmod(0o440)

    with pytest.raises(ContractError) as caught:
        broker._resolve_receipt(receipt_id, release_id)

    assert caught.value.code == "release_scientific_bytes_forbidden"
