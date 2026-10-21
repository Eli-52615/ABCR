"""tests/control/test_policy_port_equivalence —— 策略移植版与原版的行为等价守门。

`install_abcr_runtime.enforce_release_scientific_content_policy` 的 docstring 自称是
"Standalone stdlib port of the release scientific-content policy" —— 它**有意**复刻
`src/abcr/control/release_policy` 的判定,好让 root 安装器不必 import 候选代码。

两份实现各自有测试、各自全绿,但没有任何测试比对**它们是否给出同一个判定**。
轮8 的 P0 正是这么来的:release 侧放行 tar hardlink 成员(dateutil 这类包合法使用),
移植版直接拒绝;而真实封印 release 里的 `dateutil-zoneinfo.tar.gz` 含 245 个 hardlink,
于是 `verify_receipt` 必然 InstallBlocked —— genesis 装不进去。

这类「多组件对同一事物各持假设」的缺陷在本项目已三次造成阻断级 P0(轮6 文件 mode、
轮7 manifest 尺寸上限、轮8 tar 成员规则)。本文件不检查常量是否相等 —— 那挡不住
行为分叉;它**把同一批字节喂给两侧,断言判定一致**。
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from abcr.control import release_policy


ROOT = Path(__file__).resolve().parents[2]

# 真实封印产物(存在则一并验证;不存在时相关用例 skip,不降低其余断言)
REAL_STAGING = Path(
    "/Users/superagent/.abcr-build/production-b65fdc2-20260725/release-staging/"
    "REL-1762426112003c82c30832d2277917eb245f166c104bbe6723341ed5e7c246e6.staging")
REAL_HARDLINK_TAR = (REAL_STAGING / "env/lib/python3.12/site-packages/dateutil"
                                    "/zoneinfo/dateutil-zoneinfo.tar.gz")


def _load_script(name: str, relative: str):
    path = ROOT / relative
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def installer():
    return _load_script("abcr_installer_port_equiv_test", "scripts/install_abcr_runtime.py")


# ------------------------------------------------------------------ 判定归一化

def _release_verdict(raw: bytes) -> str:
    """release_policy 原版对这批字节的判定:ACCEPT 或 REJECT。"""
    try:
        release_policy._scan_archive(raw, container="probe", depth=0)
        return "ACCEPT"
    except Exception:
        return "REJECT"


def _installer_verdict(installer, raw: bytes) -> str:
    """安装器移植版对同一批字节的判定。"""
    try:
        installer._scan_policy_archive(raw, container="probe", depth=0)
        return "ACCEPT"
    except Exception:
        return "REJECT"


def _assert_equivalent(installer, raw: bytes, label: str) -> None:
    rel = _release_verdict(raw)
    ins = _installer_verdict(installer, raw)
    assert rel == ins, (
        f"策略移植版与原版对「{label}」判定分叉:"
        f"release_policy={rel} 而 install_abcr_runtime={ins}。"
        f"移植版有意复刻原版判定,任何分叉都会让某一端在真实产物上 fail-closed")


# ------------------------------------------------------------------ 样本构造

def _tar_bytes(members: list[tuple[str, bytes | tuple[str, str]]], *, gz: bool = True) -> bytes:
    """构造 tar。成员值为 bytes=普通文件;("link", target)=hardlink;("sym", target)=symlink。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz" if gz else "w") as archive:
        for name, value in members:
            if isinstance(value, bytes):
                info = tarfile.TarInfo(name)
                info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
            else:
                kind, target = value
                info = tarfile.TarInfo(name)
                info.type = tarfile.LNKTYPE if kind == "link" else tarfile.SYMTYPE
                info.linkname = target
                info.size = 0
                archive.addfile(info)
    return buf.getvalue()


def _zip_bytes(members: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, value in members:
            archive.writestr(name, value)
    return buf.getvalue()


# ------------------------------------------------------------------ 等价性用例

def test_hardlink_member_verdict_matches(installer):
    """轮8 P0 的最小复现:含 hardlink 成员的 tar,两侧判定必须一致。

    真实 release 内 dateutil-zoneinfo.tar.gz 就是这个形状(245 个 hardlink 成员)。
    """
    raw = _tar_bytes([
        ("pkg/data/real.txt", b"payload-bytes"),
        ("pkg/data/alias.txt", ("link", "pkg/data/real.txt")),
    ])

    _assert_equivalent(installer, raw, "含 hardlink 成员的 tar")


def test_plain_tar_verdict_matches(installer):
    raw = _tar_bytes([("pkg/a.txt", b"aaa"), ("pkg/b.txt", b"bbb")])

    _assert_equivalent(installer, raw, "普通 tar")


def test_symlink_member_verdict_matches(installer):
    """symlink 两侧都应拒绝 —— 确认等价性不是靠「两边都放行一切」达成的。"""
    raw = _tar_bytes([
        ("pkg/real.txt", b"payload"),
        ("pkg/evil.txt", ("sym", "../../etc/passwd")),
    ])

    _assert_equivalent(installer, raw, "含 symlink 成员的 tar")
    assert _release_verdict(raw) == "REJECT", "symlink 必须被拒,否则本用例失去意义"


def test_dangling_hardlink_verdict_matches(installer):
    """hardlink 指向归档内不存在的成员 —— 两侧都应拒绝。"""
    raw = _tar_bytes([
        ("pkg/real.txt", b"payload"),
        ("pkg/alias.txt", ("link", "pkg/does-not-exist.txt")),
    ])

    _assert_equivalent(installer, raw, "悬空 hardlink 的 tar")
    assert _release_verdict(raw) == "REJECT", "悬空 hardlink 必须被拒"


def test_duplicate_member_verdict_matches(installer):
    """同名重复成员 —— release 侧显式拒绝,移植版必须同步。"""
    raw = _tar_bytes([("pkg/dup.txt", b"first"), ("pkg/dup.txt", b"second")])

    _assert_equivalent(installer, raw, "含重复成员的 tar")


def test_zip_verdict_matches(installer):
    raw = _zip_bytes([("pkg/a.txt", b"aaa")])

    _assert_equivalent(installer, raw, "普通 zip")


def test_nested_archive_verdict_matches(installer):
    """嵌套归档:tar 里套 zip,两侧的深度处理必须一致。"""
    inner = _zip_bytes([("inner/a.txt", b"aaa")])
    raw = _tar_bytes([("pkg/inner.zip", inner)])

    _assert_equivalent(installer, raw, "tar 内嵌 zip")


# ------------------------------------------------------------------ 路径归一化

@pytest.mark.parametrize("value", [
    "",                       # 空名
    "a\\b.txt",               # 反斜杠(Windows 分隔符)
    "a\x00b.txt",             # NUL 字节
    "/etc/passwd",            # 绝对路径
    "../escape.txt",          # 父目录逃逸
    "pkg/../../escape.txt",   # 中段逃逸
    "pkg/./a.txt",            # 单点段
    "pkg/a.txt",              # 合法(确认不是「两边都拒一切」)
])
def test_member_path_normalization_verdict_matches(installer, value):
    """归档成员路径的准入判定,两侧必须逐字等价。

    路径归一化是两份实现共享的契约:release 侧 `_safe_name`、移植版 `_policy_name`。
    任一侧收紧或放松,都会让某个真实成员在一端通过、另一端 fail-closed。
    """
    def verdict(fn) -> str:
        try:
            fn(value, container="probe")
            return "ACCEPT"
        except Exception:
            return "REJECT"

    rel = verdict(release_policy._safe_name)
    ins = verdict(installer._policy_name)

    assert rel == ins, (
        f"成员路径 {value!r} 的归一化判定分叉:"
        f"release_policy._safe_name={rel} 而 install_abcr_runtime._policy_name={ins}")


# ------------------------------------------------------------------ 真实产物

@pytest.mark.skipif(not REAL_HARDLINK_TAR.exists(),
                    reason="真实封印 staging 不在本机(仅在构建过 release 的机器上可测)")
def test_real_release_hardlink_tar_accepted_by_both(installer):
    """终极断言:真实封印 release 里的那个 tar,两侧都必须接受。

    这是轮8 P0 的实物 —— 245 个 hardlink 成员。它被任一侧拒绝,genesis 就装不进去。
    """
    raw = REAL_HARDLINK_TAR.read_bytes()

    _assert_equivalent(installer, raw, "真实 release 的 dateutil-zoneinfo.tar.gz")
    assert _release_verdict(raw) == "ACCEPT", (
        "真实封印产物必须被 release 策略接受,否则 release 根本不该被构建出来")


@pytest.mark.skipif(not REAL_HARDLINK_TAR.exists(), reason="真实封印 staging 不在本机")
def test_real_tar_really_contains_hardlinks():
    """守住本文件的前提:那个 tar 确实含 hardlink 成员。

    若将来依赖升级使 hardlink 消失,本文件的真实产物断言会退化成空转 —— 此用例会先报警。
    """
    with tarfile.open(REAL_HARDLINK_TAR) as archive:
        hardlinks = [m for m in archive.getmembers() if m.islnk()]

    assert len(hardlinks) > 0, (
        "真实 tar 不再含 hardlink 成员:轮8 P0 的实物前提已变,"
        "请复核本文件的真实产物用例是否仍有意义")
