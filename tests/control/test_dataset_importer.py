from __future__ import annotations

import copy
import importlib.machinery
import importlib.util
import json
import os
import shutil
from pathlib import Path

import sys

import pytest

from abcr.explore.item_pool import _read_items, _read_split


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY = ROOT / "ops/install/dataset-authority-ifeval-zh-v1.json"
BENCHMARK = ROOT / "data/benchmarks/ifeval_zh_v1.json"
SPLIT_SOURCE = ROOT / "data/splits/ifeval_zh_v1.json"
DATASET_SHA = "1402dec503f9c5345ecb0a9c709028d6a1d32cfb8a0f2fe1dd0f3c65248c6faa"


def _load_script(name: str, relative: str):
    path = ROOT / relative
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture()
def importer():
    return _load_script("abcr_dataset_importer_test", "scripts/import_abcr_dataset.py")


@pytest.fixture()
def installer():
    return _load_script("abcr_runtime_installer_dataset_test",
                        "scripts/install_abcr_runtime.py")


def _authority(importer):
    return importer.load_authority(
        AUTHORITY, owner_uid=os.getuid(),
        allowed_modes={AUTHORITY.stat().st_mode & 0o777})


def _stage(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    source.mkdir(parents=True, mode=0o750)
    shutil.copyfile(BENCHMARK, source / "benchmark.json")
    shutil.copyfile(SPLIT_SOURCE, source / "split-source.json")
    for path in source.iterdir():
        path.chmod(0o440)
    source.chmod(0o750)
    return source, tmp_path / "datasets"


def _import(importer, tmp_path: Path):
    authority = _authority(importer)
    source, dataset_root = _stage(tmp_path)
    gid = os.getgid()
    final, created = importer.import_dataset(
        authority, source_root=source, dataset_root=dataset_root,
        owner_uid=os.getuid(), source_gid=gid, dataset_gid=gid,
        source_root_mode=0o750, dataset_root_mode=0o750)
    return authority, source, dataset_root, final, created


def test_import_normalizes_exact_250_item_dataset_for_itempool(importer, installer,
                                                               tmp_path):
    authority, _, dataset_root, final, created = _import(importer, tmp_path)
    assert created is True and final.name == DATASET_SHA
    items, _ = _read_items(final / "items.json")
    split, _ = _read_split(final / "split.json")
    assert len(items) == 250
    assert {name: len(split[name]) for name in ("dev", "calibration", "holdout")} == {
        "dev": 42, "calibration": 91, "holdout": 117}
    assert set(item["item_id"] for item in items) == set().union(*map(set, split.values()))
    manifest = json.loads((final / "manifest.json").read_text())
    assert manifest["source_commit"] == "6d753307150bb4cf69d83e705fa737da07c738be"
    assert [item["source_path"] for item in manifest["sources"]] == [
        "data/benchmarks/ifeval_zh_v1.json", "data/splits/ifeval_zh_v1.json"]
    assert manifest["dataset_sha256"] == final.name
    # The independently stdlib-only root installer repeats the immutable-byte,
    # owner/group/mode and manifest binding checks before any install mutation.
    dataset_root.chmod(0o550)
    assert installer.validate_installed_dataset(
        dataset_root, authority, owner_uid=os.getuid(), dataset_gid=os.getgid()) == final


def test_import_is_idempotent_and_never_rewrites_existing_bytes(importer, tmp_path):
    authority, source, dataset_root, final, _ = _import(importer, tmp_path)
    before = {path.name: (path.stat().st_ino, path.read_bytes()) for path in final.iterdir()}
    observed, created = importer.import_dataset(
        authority, source_root=source, dataset_root=dataset_root,
        owner_uid=os.getuid(), source_gid=os.getgid(), dataset_gid=os.getgid(),
        source_root_mode=0o750, dataset_root_mode=0o750)
    assert observed == final and created is False
    assert {path.name: (path.stat().st_ino, path.read_bytes())
            for path in final.iterdir()} == before


def test_import_rejects_source_byte_tamper_before_output(importer, tmp_path):
    authority = _authority(importer)
    source, dataset_root = _stage(tmp_path)
    path = source / "benchmark.json"
    path.chmod(0o640)
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + (b" " if raw[-1:] != b" " else b"\n"))
    path.chmod(0o440)
    with pytest.raises(importer.DatasetImportBlocked, match="hash mismatch"):
        importer.import_dataset(
            authority, source_root=source, dataset_root=dataset_root,
            owner_uid=os.getuid(), source_gid=os.getgid(), dataset_gid=os.getgid(),
            source_root_mode=0o750, dataset_root_mode=0o750)
    assert not dataset_root.exists()


def test_import_rejects_symlinked_source_and_output(importer, tmp_path):
    authority = _authority(importer)
    source, dataset_root = _stage(tmp_path)
    split = source / "split-source.json"
    split.chmod(0o640)
    split.unlink()
    split.symlink_to(SPLIT_SOURCE)
    with pytest.raises(importer.DatasetImportBlocked, match="trusted file"):
        importer.import_dataset(
            authority, source_root=source, dataset_root=dataset_root,
            owner_uid=os.getuid(), source_gid=os.getgid(), dataset_gid=os.getgid(),
            source_root_mode=0o750, dataset_root_mode=0o750)

    source, dataset_root = _stage(tmp_path / "second")
    dataset_root.mkdir(mode=0o750)
    (dataset_root / DATASET_SHA).symlink_to(source, target_is_directory=True)
    with pytest.raises(importer.DatasetImportBlocked, match="trusted directory"):
        importer.import_dataset(
            authority, source_root=source, dataset_root=dataset_root,
            owner_uid=os.getuid(), source_gid=os.getgid(), dataset_gid=os.getgid(),
            source_root_mode=0o750, dataset_root_mode=0o750)


def test_import_rejects_symlinked_ancestor(importer, tmp_path):
    authority = _authority(importer)
    real = tmp_path / "real"
    source, _ = _stage(real)
    link = tmp_path / "redirect"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(importer.DatasetImportBlocked, match="non-symlink path"):
        importer.import_dataset(
            authority, source_root=link / "source",
            dataset_root=tmp_path / "datasets", owner_uid=os.getuid(),
            source_gid=os.getgid(), dataset_gid=os.getgid(),
            source_root_mode=0o750, dataset_root_mode=0o750)

def test_replay_conflict_is_fail_closed_and_not_clobbered(importer, tmp_path):
    authority = _authority(importer)
    source, dataset_root = _stage(tmp_path)
    dataset_root.mkdir(mode=0o750)
    final = dataset_root / DATASET_SHA
    final.mkdir(mode=0o750)
    planted = final / "attacker.txt"
    planted.write_text("keep", encoding="utf-8")
    planted.chmod(0o440)
    final.chmod(0o550)
    with pytest.raises(importer.DatasetImportBlocked, match="file set mismatch"):
        importer.import_dataset(
            authority, source_root=source, dataset_root=dataset_root,
            owner_uid=os.getuid(), source_gid=os.getgid(), dataset_gid=os.getgid(),
            source_root_mode=0o750, dataset_root_mode=0o750)
    assert planted.read_text() == "keep"


def test_split_assignment_drift_fails_scientific_invariants(importer):
    authority = _authority(importer)
    benchmark_raw = BENCHMARK.read_bytes()
    split = json.loads(SPLIT_SOURCE.read_text())
    split["assignments"]["ifzh-0002"] = "holdout"
    split_raw = importer.canonical(split) + b"\n"
    drift_authority = copy.deepcopy(authority)
    drift_authority["source_combined_sha256"] = importer.digest(
        benchmark_raw + b"\0" + split_raw)
    with pytest.raises(importer.DatasetImportBlocked,
                       match="split distribution/hash drift"):
        importer.normalize(drift_authority, benchmark_raw, split_raw)


def test_holdout_is_contractually_hidden_from_ordinary_consumers():
    ownership = json.loads((ROOT / "configs/control/path-ownership-v1.json").read_text())
    dataset = next(item for item in ownership["roots"]
                   if item["path"] == "/Library/Application Support/ABCR-Datasets")
    assert dataset["readers"] == ["abcr-itempool", "abcr-auditor"]
    assert {"abcr-operator", "abcr-probe", "abcr-builder", "abcr-candidate",
            "abcr-panel"}.issubset(dataset["must_deny"])
    account_source = (ROOT / "scripts/bootstrap_abcr_accounts.sh").read_text()
    assert ('ensure_role_group abcr-dataset-read "ABCR frozen dataset readers" '
            '\\\n  "abcr-itempool abcr-auditor"') in account_source
    authority = json.loads(AUTHORITY.read_text())
    assert authority["access_policy"]["readers"] == dataset["readers"]
    assert set(authority["access_policy"]["must_deny"]) == set(dataset["must_deny"])


def test_installer_binds_itempool_config_to_exact_hash_directory():
    source = (ROOT / "scripts/install_abcr_runtime.py").read_text()
    assert 'dataset_dir / "items.json"' in source
    assert 'dataset_dir / "split.json"' in source
    assert 'dataset_root / "items.jsonl"' not in source
    assert "validate_installed_dataset(" in source


def test_privileged_importer_refuses_mutable_source_checkout(importer):
    with pytest.raises(importer.DatasetImportBlocked, match="root-owned reviewed/sealed"):
        importer._require_reviewed_execution_path()


def _acl_identity(name: str):
    groups = {"dataset-read"} if name in {"abcr-itempool", "abcr-auditor"} else {
        f"{name}-group"}
    return name, 10_000 + sum(map(ord, name)), frozenset(groups)


def _acl_text(*entries: str) -> str:
    return "dr-xr-x---+ 1 root abcr-dataset-read 0 Jul 22 00:00 dataset\n" + "".join(
        f" {index}: {entry}\n" for index, entry in enumerate(entries))


@pytest.mark.parametrize("entry", [
    "user:abcr-probe allow read,list,search",
    "user:10138 inherited allow read_data",
    "group:abcr-probe-group inherited allow list,search",
    "group:everyone allow read_data",
])
def test_importer_rejects_named_or_inherited_acl_grant(importer, entry):
    # Pin the numeric case to the injected abcr-probe identity.
    def identity(name):
        resolved = _acl_identity(name)
        return (resolved[0], 10138 if name == "abcr-probe" else resolved[1], resolved[2])

    with pytest.raises(importer.DatasetImportBlocked, match="must-deny identity"):
        importer.require_no_must_deny_acl_grant(
            [Path("/dataset")], ["abcr-probe"],
            acl_reader=lambda path: _acl_text(entry), identity_resolver=identity)


def test_importer_allows_deny_acl_and_authorized_group_acl(importer):
    importer.require_no_must_deny_acl_grant(
        [Path("/dataset")], ["abcr-probe"],
        acl_reader=lambda path: _acl_text(
            "user:abcr-probe inherited deny read,list,search",
            "group:dataset-read allow read,list,search"),
        identity_resolver=_acl_identity)


def test_posix_reader_group_membership_of_must_deny_identity_blocks_both_sides(
        importer, installer):
    identity = lambda name: (name, 10138, frozenset({"abcr-dataset-read"}))
    with pytest.raises(importer.DatasetImportBlocked, match="POSIX reader group"):
        importer.require_no_must_deny_acl_grant(
            [Path("/dataset")], ["abcr-probe"], acl_reader=lambda path: _acl_text(),
            identity_resolver=identity, posix_reader_groups=("abcr-dataset-read",))
    with pytest.raises(installer.InstallBlocked, match="POSIX reader group"):
        installer.require_no_dataset_acl_grant(
            [Path("/dataset")], ["abcr-probe"], acl_reader=lambda path: _acl_text(),
            identity_resolver=identity, posix_reader_groups=("abcr-dataset-read",))


def test_import_rejects_staging_acl_drift_before_publication(importer, tmp_path):
    authority = _authority(importer)
    source, dataset_root = _stage(tmp_path)

    def acl_reader(path):
        if path == source / "benchmark.json":
            return _acl_text("user:abcr-probe inherited allow read_data")
        return _acl_text()

    with pytest.raises(importer.DatasetImportBlocked, match="must-deny identity"):
        importer.import_dataset(
            authority, source_root=source, dataset_root=dataset_root,
            owner_uid=os.getuid(), source_gid=os.getgid(), dataset_gid=os.getgid(),
            source_root_mode=0o750, dataset_root_mode=0o750,
            enforce_acl=True, acl_reader=acl_reader,
            identity_resolver=_acl_identity)
    assert not dataset_root.exists()


def test_importer_and_independent_installer_reject_final_acl_drift(
        importer, installer, tmp_path):
    authority, _, dataset_root, final, _ = _import(importer, tmp_path)
    dataset_root.chmod(0o550)

    def acl_reader(path):
        if path == final:
            return _acl_text("group:abcr-candidate-group inherited allow list,search")
        return _acl_text()

    with pytest.raises(importer.DatasetImportBlocked, match="must-deny identity"):
        importer.verify_installed(
            authority, dataset_root=dataset_root, owner_uid=os.getuid(),
            dataset_gid=os.getgid(), enforce_acl=True, acl_reader=acl_reader,
            identity_resolver=_acl_identity)
    with pytest.raises(installer.InstallBlocked, match="must-deny identity"):
        installer.validate_installed_dataset(
            dataset_root, authority, owner_uid=os.getuid(), dataset_gid=os.getgid(),
            enforce_acl=True, acl_reader=acl_reader,
            identity_resolver=_acl_identity)


def test_acl_identity_or_reader_uncertainty_blocks_both_sides(
        importer, installer):
    for module, function, error in (
            (importer, importer.require_no_must_deny_acl_grant,
             importer.DatasetImportBlocked),
            (installer, installer.require_no_dataset_acl_grant,
             installer.InstallBlocked)):
        with pytest.raises(error, match="identity unavailable"):
            function([Path("/dataset")], ["abcr-probe"],
                     acl_reader=lambda path: _acl_text(),
                     identity_resolver=lambda name: (_ for _ in ()).throw(KeyError(name)))
        with pytest.raises(error, match="inspect"):
            function([Path("/dataset")], ["abcr-probe"],
                     acl_reader=lambda path: (_ for _ in ()).throw(OSError("drift")),
                     identity_resolver=_acl_identity)


def _exact_group_kwargs(*, direct_names=("abcr-itempool", "abcr-auditor"),
                        direct_guids=("GUID-ITEMPOOL", "GUID-AUDITOR"),
                        nested_guids=(), extra_effective=()):
    readers = {"abcr-itempool": "GUID-ITEMPOOL", "abcr-auditor": "GUID-AUDITOR"}
    visible = ("root", "superagent", "abcr-human", *readers, *extra_effective)
    effective = frozenset(readers) | frozenset(extra_effective)
    return {
        "group_record_reader": lambda group: (
            tuple(direct_names), tuple(direct_guids), tuple(nested_guids)),
        "user_guid_resolver": readers.__getitem__,
        "visible_users_resolver": lambda: tuple(dict.fromkeys(visible)),
        "effective_groups_resolver": lambda name: frozenset(
            {"abcr-dataset-read"} if name in effective else {f"{name}-primary"}),
    }


def test_dataset_reader_group_is_exact_on_importer_and_independent_installer(
        importer, installer):
    access = _authority(importer)["access_policy"]
    for module in (importer, installer):
        module.validate_exact_dataset_reader_group(access, **_exact_group_kwargs())


@pytest.mark.parametrize(("override", "message"), [
    ({"direct_names": ("abcr-itempool", "abcr-auditor", "superagent")},
     "direct membership.*not exact"),
    ({"direct_guids": ("GUID-ITEMPOOL", "GUID-AUDITOR", "UNKNOWN-GUID")},
     "GUID membership.*not exact"),
    ({"nested_guids": ("NESTED-UNREVIEWED",)}, "nested membership"),
    ({"extra_effective": ("abcr-human",)}, "effective membership.*not exact"),
    ({"extra_effective": ("superagent",)}, "effective membership.*not exact"),
    ({"extra_effective": ("unknown-reader",)}, "effective membership.*not exact"),
])
def test_unreviewed_direct_nested_or_effective_dataset_member_blocks_both_sides(
        importer, installer, override, message):
    access = _authority(importer)["access_policy"]
    for module in (importer, installer):
        with pytest.raises((module.DatasetImportBlocked
                            if module is importer else module.InstallBlocked),
                           match=message):
            module.validate_exact_dataset_reader_group(
                access, **_exact_group_kwargs(**override))


def test_dataset_group_membership_uncertainty_blocks_both_sides(importer, installer):
    access = _authority(importer)["access_policy"]
    for module in (importer, installer):
        error = (module.DatasetImportBlocked if module is importer
                 else module.InstallBlocked)
        kwargs = _exact_group_kwargs()
        kwargs["effective_groups_resolver"] = lambda name: (_ for _ in ()).throw(
            KeyError(name))
        with pytest.raises(error, match="membership unavailable"):
            module.validate_exact_dataset_reader_group(access, **kwargs)


def test_bootstrap_and_installer_validate_exact_group_without_silent_removal():
    bootstrap = (ROOT / "scripts/bootstrap_abcr_accounts.sh").read_text()
    assert "validate_exact_dataset_reader_group || FAIL=" in bootstrap
    assert "/Groups/$group\" NestedGroups" in bootstrap
    assert "/usr/bin/dscl /Search -list /Users UniqueID" in bootstrap
    assert "/usr/bin/id -Gn" in bootstrap
    assert " -d " not in bootstrap and "-o delete" not in bootstrap

    installer = (ROOT / "scripts/install_abcr_runtime.py").read_text()
    exact_gate = installer.index(
        'validate_exact_dataset_reader_group(dataset_authority["access_policy"])')
    first_mutation = installer.index("        install_directories()")
    assert exact_gate < first_mutation


def test_live_dataset_access_requires_exact_positive_and_negative_matrix(
        importer):
    authority = _authority(importer)
    root = Path("/Library/Application Support/ABCR-Datasets")
    final = root / DATASET_SHA

    def good_probe(name, dataset_root, dataset_dir):
        assert dataset_root == root and dataset_dir == final
        expected = "ok" if name in authority["access_policy"]["readers"] else "denied"
        return {operation: expected for operation in importer._LIVE_OPERATIONS}

    importer.validate_live_dataset_access(
        authority, dataset_root=root, final=final, identity_probe=good_probe,
        group_validator=lambda access: None,
        effective_uid=0, platform_name="darwin")

    def leaked_probe(name, dataset_root, dataset_dir):
        observed = good_probe(name, dataset_root, dataset_dir)
        if name == "abcr-candidate":
            observed["open_items"] = "ok"
        return observed

    with pytest.raises(importer.DatasetImportBlocked, match="unexpectedly succeeded"):
        importer.validate_live_dataset_access(
            authority, dataset_root=root, final=final, identity_probe=leaked_probe,
            group_validator=lambda access: None,
            effective_uid=0, platform_name="darwin")

    def broken_reader(name, dataset_root, dataset_dir):
        observed = good_probe(name, dataset_root, dataset_dir)
        if name == "abcr-itempool":
            observed["list_final"] = "denied"
        return observed

    with pytest.raises(importer.DatasetImportBlocked, match="authorized.*failed"):
        importer.validate_live_dataset_access(
            authority, dataset_root=root, final=final, identity_probe=broken_reader,
            group_validator=lambda access: None,
            effective_uid=0, platform_name="darwin")

    with pytest.raises(importer.DatasetImportBlocked,
                       match="reader group validation failed"):
        importer.validate_live_dataset_access(
            authority, dataset_root=root, final=final, identity_probe=good_probe,
            group_validator=lambda access: (_ for _ in ()).throw(
                RuntimeError("unexpected effective member")),
            effective_uid=0, platform_name="darwin")


@pytest.mark.parametrize(("euid", "platform"), [(501, "darwin"), (0, "linux")])
def test_live_dataset_access_never_pseudo_passes_without_root_mac(
        importer, euid, platform):
    authority = _authority(importer)
    with pytest.raises(importer.DatasetImportBlocked, match="requires root.*macOS"):
        importer.validate_live_dataset_access(
            authority, dataset_root=Path("/tmp/datasets"), final=Path("/tmp/final"),
            identity_probe=lambda *args: {}, effective_uid=euid,
            platform_name=platform, group_validator=lambda access: None)


@pytest.mark.skipif(sys.platform != "darwin",
                    reason="nobody 哨兵 gid 是 macOS 目录服务的特性")
def test_identity_resolves_macos_nobody_sentinel_gid_accounts(importer):
    """macOS 内置服务账户 primary gid = nobody 哨兵(-2 的无符号拼写)。

    os.getgrouplist 要有符号 C int(拒 4294967294),grp.getgrgid 要无符号 32 位
    (拒 -2)。不做拼写归一化时 OverflowError 会逃逸,让"枚举全部可见用户"的
    exact-group 校验在任何原厂 macOS 上必然 BLOCKED。
    """
    assert importer._canonical_gid(-2) == 4294967294
    assert importer._canonical_gid(18446744073709551614) == 4294967294
    assert importer._canonical_gid(4294967294) == 4294967294
    assert importer._c_int_gid(4294967294) == -2
    assert importer._c_int_gid(20) == 20

    name, uid, groups = importer._identity("nobody")
    assert name == "nobody" and isinstance(uid, int)
    assert "everyone" in groups          # 组名解析走无符号拼写
    assert "4294967294" in groups        # 数值拼写已归一化,不出现 -2/64 位形式
    assert not any(item.startswith("-") for item in groups)


@pytest.mark.skipif(sys.platform != "darwin",
                    reason="nobody 哨兵 gid 是 macOS 目录服务的特性")
def test_visible_user_sweep_survives_sentinel_accounts(importer):
    """exact-group 校验会扫过每个可见用户;哨兵账户不得让它整体失败。"""
    import pwd
    sentinels = [u.pw_name for u in pwd.getpwall() if u.pw_gid > 2 ** 31 - 1]
    assert sentinels, "本机没有哨兵账户,用例失去意义"
    for account in sentinels[:5]:
        resolved, _uid, groups = importer._identity(account)
        assert resolved == account and isinstance(groups, frozenset) and groups


@pytest.mark.skipif(sys.platform != "darwin",
                    reason="BSD stat -f / macOS ACL 语义")
def test_service_home_materialization_is_symlink_safe_and_propagates_failure(tmp_path):
    """C-HSD-01 同源纪律:失败的 mkdir 绝不得穿透到 chown/chmod。

    调用方以 `ensure_account … || FAIL=…` 形式调用,POSIX 下 set -e 在整个函数体内
    失效——这正是本用例要钉死的语义:symlink 冒充必须 BLOCKED、返回非零,且被
    冒充的目标目录字节/权限分毫不动。
    """
    import subprocess
    script = (ROOT / "scripts/bootstrap_abcr_accounts.sh").read_text(encoding="utf-8")
    start = script.index("ensure_service_home() {")
    end = script.index("\n}\n", start) + 3
    body = script[start:end].replace('/Users/$name', str(tmp_path) + '/$name')

    victim = tmp_path / "victim"
    victim.mkdir(mode=0o755)
    (tmp_path / "abcr-fake").symlink_to(victim)
    before = victim.stat().st_mode

    harness = tmp_path / "probe.sh"
    harness.write_text(
        "set -euo pipefail\nMODE=install\n" + body +
        "\nFAIL=0\nensure_service_home abcr-fake || FAIL=1\necho \"FAIL=$FAIL\"\n",
        encoding="utf-8")
    done = subprocess.run(["/bin/bash", str(harness)], capture_output=True,
                          text=True, timeout=30)
    assert "lstat type is Symbolic Link" in done.stdout
    assert "FAIL=1" in done.stdout
    assert victim.stat().st_mode == before   # 未被 chown/chmod 穿透触碰


@pytest.mark.skipif(sys.platform != "darwin",
                    reason="BSD stat -f / macOS ACL 语义")
def test_service_home_check_mode_requires_exact_owner_and_mode(tmp_path):
    import subprocess
    script = (ROOT / "scripts/bootstrap_abcr_accounts.sh").read_text(encoding="utf-8")
    start = script.index("ensure_service_home() {")
    end = script.index("\n}\n", start) + 3
    body = script[start:end].replace('/Users/$name', str(tmp_path) + '/$name')

    loose = tmp_path / "abcr-loose"
    loose.mkdir(mode=0o777)
    harness = tmp_path / "check.sh"
    harness.write_text(
        "set -euo pipefail\nMODE=check\n" + body +
        "\nFAIL=0\nensure_service_home abcr-loose || FAIL=1\necho \"FAIL=$FAIL\"\n",
        encoding="utf-8")
    done = subprocess.run(["/bin/bash", str(harness)], capture_output=True,
                          text=True, timeout=30)
    assert "expected Directory:abcr-loose:abcr-loose:40700" in done.stdout
    assert "FAIL=1" in done.stdout


@pytest.mark.skipif(sys.platform != "darwin", reason="BSD stat -f / macOS ACL 语义")
def test_service_home_rejects_extended_acl_and_high_mode_bits(tmp_path):
    """POSIX 位相同不等于私密:扩展 ACL 与 sticky/setgid 高位都必须被看见。"""
    import subprocess
    script = (ROOT / "scripts/bootstrap_abcr_accounts.sh").read_text(encoding="utf-8")
    start = script.index("ensure_service_home() {")
    end = script.index("\n}\n", start) + 3
    body = script[start:end].replace('/Users/$name', str(tmp_path) + '/$name')

    def run(mode: str, name: str) -> str:
        harness = tmp_path / f"{name}-{mode}.sh"
        harness.write_text(f"set -euo pipefail\nMODE={mode}\n" + body +
                           f'\nFAIL=0\nensure_service_home {name} || FAIL=1\necho "FAIL=$FAIL"\n',
                           encoding="utf-8")
        return subprocess.run(["/bin/bash", str(harness)], capture_output=True,
                              text=True, timeout=30).stdout

    acl_home = tmp_path / "abcr-acl"
    acl_home.mkdir(mode=0o700)
    subprocess.run(["/bin/chmod", "+a", "everyone allow read,write,search",
                    str(acl_home)], check=True, timeout=30)
    out = run("check", "abcr-acl")
    assert "carries an extended ACL" in out and "FAIL=1" in out

    sticky = tmp_path / "abcr-sticky"
    sticky.mkdir(mode=0o700)
    os.chmod(sticky, 0o1700)   # mkdir(2) 不保留 sticky,必须显式 chmod
    out = run("check", "abcr-sticky")
    assert ":41700, expected" in out and "FAIL=1" in out   # %Lp 会漏掉的高位


@pytest.mark.skipif(sys.platform != "darwin", reason="BSD stat -f 语义")
def test_service_home_mkdir_failure_does_not_fall_through(tmp_path):
    """P1-1 的原始形态:mkdir 失败绝不得穿透到 chown/chmod。

    通过把父目录设为不可写来强制 mkdir 失败(此前 set -e 失效会让流程继续)。
    """
    import subprocess
    script = (ROOT / "scripts/bootstrap_abcr_accounts.sh").read_text(encoding="utf-8")
    start = script.index("ensure_service_home() {")
    end = script.index("\n}\n", start) + 3
    parent = tmp_path / "locked"
    parent.mkdir(mode=0o500)
    body = script[start:end].replace('/Users/$name', str(parent) + '/$name')
    harness = tmp_path / "mkdirfail.sh"
    harness.write_text("set -euo pipefail\nMODE=install\n" + body +
                       '\nFAIL=0\nensure_service_home abcr-blocked || FAIL=1\necho "FAIL=$FAIL"\n',
                       encoding="utf-8")
    done = subprocess.run(["/bin/bash", str(harness)], capture_output=True,
                          text=True, timeout=30)
    assert "cannot create home directory" in done.stdout
    assert "INSTALLED" not in done.stdout
    assert "FAIL=1" in done.stdout
