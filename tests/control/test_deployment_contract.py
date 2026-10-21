from __future__ import annotations

import importlib.machinery
import importlib.util
import importlib
import json
import os
import plistlib
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

AUTHORITATIVE_MODULES = {
    "com.abcr.human-gateway": "abcr.control.human_gateway",
    "com.abcr.operator-reconciler": "abcr.control.operator",
    "com.abcr.probe-worker": "abcr.probe.service",
    "com.abcr.itempool": "abcr.explore.itempool_service",
    "com.abcr.auditor": "abcr.audit.service",
    "com.abcr.mission-builder": "abcr.control.mission_worker",
    "com.abcr.test-controller": "abcr.control.test_controller",
    "com.abcr.verifier": "abcr.control.verifier",
    "com.abcr.canary-controller": "abcr.control.canary_controller",
    "com.abcr.release-activator": "abcr.control.release",
    "com.abcr.panel": "abcr.control.panel",
    "com.abcr.seal-broker": "abcr.control.seal_broker",
}


def test_all_json_configs_parse_and_schemas_are_strict():
    for path in sorted((ROOT / "configs").rglob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
    for path in (ROOT / "configs" / "schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text())
        assert schema["$schema"].endswith("2020-12/schema")
        assert schema["type"] == "object" and schema["additionalProperties"] is False
    expected = {
        "implementation-manifest-v1.schema.json", "control-command-v1.schema.json",
        "action-result-v1.schema.json", "spool-envelope-v1.schema.json",
        "approval-token-v2.schema.json", "approval-request-bundle-v1.schema.json",
        "seal-request-v1.schema.json", "work-envelope-v1.schema.json",
        "dataset-manifest-v1.schema.json", "experiment-goal-v1.schema.json",
        "persona-artifact-v1.schema.json", "mission-v1.schema.json",
        "acceptance-profile-v1.schema.json", "round-index-v1.schema.json",
    }
    assert expected.issubset({path.name for path in (ROOT / "configs/schemas").glob("*.json")})


def test_twelve_plists_match_topology_and_contain_no_secrets():
    topology = json.loads((ROOT / "configs/control/service-topology-v1.json").read_text())
    configured = {x["label"]: x["module"] for x in topology["services"]}
    assert configured == AUTHORITATIVE_MODULES
    expected = set(configured)
    plists = sorted((ROOT / "ops/launchd").glob("com.abcr.*.plist"))
    assert len(expected) == len(plists) == 12
    observed = set()
    for path in plists:
        raw = path.read_bytes(); data = plistlib.loads(raw)
        label = data["Label"]
        observed.add(label)
        component = ("seal-broker" if label == "com.abcr.seal-broker" else
                     "test-controller" if label == "com.abcr.test-controller" else "launcher")
        expected_args = (["/usr/local/libexec/abcr-bootstrap-selector", component]
                         if component != "launcher" else
                         ["/usr/local/libexec/abcr-bootstrap-selector", "launcher", label])
        assert data["ProgramArguments"] == expected_args
        assert data["WorkingDirectory"] == "/var/empty"
        assert data["Umask"] in {0o027, 0o077}
        assert data["EnvironmentVariables"] == {
            "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1"}
        if "QueueDirectories" in data:
            # launchd.plist(5) requires an array of absolute path strings.
            queue_dirs = data["QueueDirectories"]
            assert isinstance(queue_dirs, list) and queue_dirs, label
            assert all(isinstance(item, str) and item.startswith("/")
                       for item in queue_dirs), label
        lowered = raw.lower()
        assert b"secret" not in lowered and b"token" not in lowered and b"private_key" not in lowered
    assert observed == expected


def test_all_twelve_service_modules_expose_callable_main():
    """A syntactically valid plist is not a runnable service.

    Collect every defect in one failure so a missing module or a library-only module
    cannot hide behind the first import error and let deployment be reported green.
    """
    defects = []
    for label, module_name in AUTHORITATIVE_MODULES.items():
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # report all twelve entrypoints in one assertion
            defects.append(f"{label}: cannot import {module_name}: {type(exc).__name__}: {exc}")
            continue
        if not callable(getattr(module, "main", None)):
            defects.append(f"{label}: {module_name} has no callable main()")
    assert not defects, "service entrypoint defects:\n" + "\n".join(defects)


def load_service_runner():
    path = ROOT / "scripts/abcr-service"
    loader = importlib.machinery.SourceFileLoader("abcr_service", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module); return module


def test_service_doctor_rejects_module_without_callable_main(monkeypatch):
    runner = load_service_runner()
    monkeypatch.setattr(runner.importlib, "import_module", lambda _: SimpleNamespace())
    monkeypatch.setattr(sys, "argv", ["abcr-service", "fixture.no_main", "--doctor"])
    with pytest.raises(SystemExit, match=r"fixture\.no_main has no callable main\(\)"):
        runner.main()


def test_service_doctor_validates_but_does_not_run_main(monkeypatch, capsys):
    runner = load_service_runner(); called = []
    fake = SimpleNamespace(main=lambda: called.append(True))
    monkeypatch.setattr(runner.importlib, "import_module", lambda _: fake)
    monkeypatch.setattr(sys, "argv", ["abcr-service", "fixture.valid", "--doctor"])
    assert runner.main() == 0
    assert called == []
    assert json.loads(capsys.readouterr().out) == {
        "ok": True, "module": "fixture.valid", "entrypoint": "main"}


def test_seven_deny_default_sandbox_profiles():
    profiles = sorted((ROOT / "ops/sandbox").glob("*.sb"))
    assert len(profiles) == 7
    for path in profiles:
        text = path.read_text()
        assert "(deny default)" in text and "(allow default)" not in text
    candidate = (ROOT / "ops/sandbox/abcr-candidate.sb").read_text()
    assert "RESULT" not in candidate and "network" in candidate


def load_launcher():
    path = ROOT / "scripts/abcr-launch"
    loader = importlib.machinery.SourceFileLoader("abcr_launch", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module); return module


def test_stable_launcher_rejects_symlink_and_resolves_regular_active(tmp_path):
    launcher = load_launcher(); releases = tmp_path / "releases"; release = releases / "REL-fixture"
    (release / "env/bin").mkdir(parents=True); python = release / "env/bin/python"
    python.write_text("fixture"); python.chmod(0o500)
    (release / "release-manifest.json").write_text(json.dumps({"release_id": "REL-fixture",
                                                                "service_payloads": {"abcr.control.panel": {}}}))
    active = tmp_path / "active.json"; active.write_text(json.dumps({"release_id": "REL-fixture"})); active.chmod(0o444)
    resolved, manifest = launcher.resolve_active(active, releases)
    assert resolved == release.resolve() and manifest["release_id"] == "REL-fixture"
    link = tmp_path / "active-link.json"; link.symlink_to(active)
    with pytest.raises(RuntimeError): launcher.resolve_active(link, releases)


def test_work_stage_and_acl_manifests_are_complete():
    stages = json.loads((ROOT / "configs/control/work-stages-v1.json").read_text())
    assert len(stages["stages"]) == 9 and len(set(stages["stages"])) == 9
    acl = json.loads((ROOT / "ops/acl/acl-manifest-v1.json").read_text())
    assert "candidate_cannot_read_test_results" in acl["negative_probes"]


def load_installer():
    path = ROOT / "scripts/install_abcr_runtime.py"
    loader = importlib.machinery.SourceFileLoader("abcr_installer", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module); return module


def _sealed_release_fixture(tmp_path, *, python_mode=0o550):
    """一棵形如封印 release 的树:目录 0550、数据 0440、可执行体 0550。"""
    release = tmp_path / "REL-fixture"
    (release / "env/bin").mkdir(parents=True)
    (release / "scripts").mkdir()
    python = release / "env/bin/python"
    python.write_text("#!/bin/sh\n")
    data = release / "env/bin/data.json"
    data.write_text("{}\n")
    launcher = release / "scripts/abcr-launch"
    launcher.write_text("#!/usr/bin/env python3\n")
    manifest = {"tree_entries": [
        {"path": "env/bin/python", "mode": 0o555, "size": 1, "sha256": "x"},
        {"path": "env/bin/data.json", "mode": 0o444, "size": 1, "sha256": "y"},
        {"path": "scripts/abcr-launch", "mode": 0o555, "size": 1, "sha256": "z"},
    ]}
    for path, mode in ((data, 0o440), (python, python_mode), (launcher, 0o550)):
        os.chmod(path, mode)
    for directory in (release / "env/bin", release / "env", release / "scripts", release):
        os.chmod(directory, 0o550)
    return release, manifest


def test_release_read_policy_accepts_sealed_executables(tmp_path, monkeypatch):
    """P0 回归:封印策略按可执行位分流(0o550/0o440),而 release.prepare 又**要求**
    env/bin/python 带 x 位。若此闸一律要求 0o440,任何合法 release 都会被拒,
    genesis 永远无法完成。此前该函数零测试覆盖。"""
    installer = load_installer()
    release, manifest = _sealed_release_fixture(tmp_path)
    monkeypatch.setattr(installer, "gid", lambda _name: os.getgid())
    monkeypatch.setattr(installer.os, "walk", installer.os.walk)
    # 属主断言在测试环境下不可满足(需 root:abcr-release-read),只中和这两项;
    # 模式规则原样执行。
    real_lstat = Path.lstat

    def patched(self):
        info = real_lstat(self)
        return os.stat_result((info.st_mode, info.st_ino, info.st_dev, info.st_nlink,
                               0, os.getgid(), info.st_size,
                               info.st_atime, info.st_mtime, info.st_ctime))
    monkeypatch.setattr(Path, "lstat", patched)
    installer.verify_release_read_policy(release, manifest)   # 不得抛出


def test_release_read_policy_still_rejects_undeclared_executable(tmp_path, monkeypatch):
    """放宽只按 manifest 声明派生:未声明的文件仍必须被拒,不得因带 x 位就放行。"""
    installer = load_installer()
    release, manifest = _sealed_release_fixture(tmp_path)
    stray = release / "scripts" / "stray"
    os.chmod(release / "scripts", 0o750)
    stray.write_text("#!/bin/sh\n")
    os.chmod(stray, 0o550)
    os.chmod(release / "scripts", 0o550)
    monkeypatch.setattr(installer, "gid", lambda _name: os.getgid())
    real_lstat = Path.lstat

    def patched(self):
        info = real_lstat(self)
        return os.stat_result((info.st_mode, info.st_ino, info.st_dev, info.st_nlink,
                               0, os.getgid(), info.st_size,
                               info.st_atime, info.st_mtime, info.st_ctime))
    monkeypatch.setattr(Path, "lstat", patched)
    with pytest.raises(installer.InstallBlocked, match="undeclared file"):
        installer.verify_release_read_policy(release, manifest)


def _oversized_manifest(tmp_path, *, mebibytes: int = 9):
    """构造一个超过 8 MiB 的 manifest —— 真实 release 约 23 MiB(20,417 条目)。"""
    entries = []
    filler = "x" * 40
    index = 0
    while True:
        entries.append({"path": f"env/lib/python3.12/site-packages/pkg{index}/{filler}.py",
                        "mode": 0o444, "size": 10, "sha256": "a" * 64})
        index += 1
        if index % 2000 == 0:
            probe = json.dumps({"release_id": "REL-" + "a" * 64, "tree_entries": entries})
            if len(probe) > mebibytes * 1024 * 1024:
                break
    path = tmp_path / "release-manifest.json"
    path.write_text(json.dumps({"release_id": "REL-" + "a" * 64,
                                "tree_entries": entries}, separators=(",", ":")))
    os.chmod(path, 0o440)
    return path


def test_every_manifest_reader_accepts_a_real_sized_manifest(tmp_path):
    """P0 回归:真实封印 manifest 内嵌全部树条目(约 23 MiB),而 genesis/installer/
    selector/launcher 的读取上限原本是 4/8 MiB —— 任何真实 release 都会被拒:
    genesis 装不进去、selector 选不出组件、launcher 起不了服务。测试夹具此前一律
    很小,所以 1500 个绿灯全程看不见这一层。"""
    manifest = _oversized_manifest(tmp_path)
    assert manifest.stat().st_size > 8 * 1024 * 1024
    uid = os.getuid()
    cap = 128 * 1024 * 1024

    genesis = _load_script("scripts/bootstrap_abcr_genesis.py", "genesis_caps")
    assert genesis._read_json(manifest, owner_uid=uid, max_bytes=cap)["release_id"]
    with pytest.raises(genesis.GenesisBlocked):
        genesis._read_json(manifest, owner_uid=uid)          # 默认上限仍拒绝

    installer = load_installer()
    assert installer.read_json(manifest, owner_uid=uid, max_bytes=cap)["release_id"]

    selector = _load_script("scripts/abcr-bootstrap-selector", "selector_caps")
    assert selector._read_json(manifest, uid, max_bytes=cap)["release_id"]

    launcher = load_launcher()
    assert launcher._read_json(manifest, owner_uid=uid, max_bytes=cap)["release_id"]


def _load_script(relative: str, name: str):
    path = ROOT / relative
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module); return module
