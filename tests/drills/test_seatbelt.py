"""tests/drills/test_seatbelt.py —— A2-5 冻结区 Seatbelt 拦截四断言的自动化版。

文档 §6·A2-5 验收命令的自动化：读放行；shell 追加 / python open('w') / rm / mv 四种写全被
内核拦（Operation not permitted / PermissionError [Errno 1]，退出码非 0）；冻结区文件字节不变。
sandbox-exec 不可用（非 macOS / ABCR_SANDBOX_DISABLED=1）时整体 SKIP。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from abcr.sandboxing.profiles import available, frozen_profile

pytestmark = pytest.mark.skipif(not available(),
                                reason="sandbox-exec 不可用（非 macOS 或 ABCR_SANDBOX_DISABLED=1）")

_SB = "/usr/bin/sandbox-exec"


@pytest.fixture
def sandbox_root(tmp_path: Path) -> tuple[Path, str, Path]:
    """realpath 化的临时冻结区 + profile 文件。返回 (root, profile_path, golden_file)。"""
    root = Path(os.path.realpath(tmp_path))
    golden = root / "data" / "golden"
    golden.mkdir(parents=True)
    gf = golden / "golden10.json"
    gf.write_text('{"items": []}\n', encoding="utf-8")
    sb = root / "abcr-frozen.sb"
    sb.write_text(frozen_profile(root), encoding="utf-8")
    return root, str(sb), gf


def _run(sb: str, *cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run([_SB, "-f", sb, *cmd], capture_output=True, text=True)


def test_read_allowed(sandbox_root) -> None:
    root, sb, gf = sandbox_root
    r = _run(sb, "cat", str(gf))
    assert r.returncode == 0
    assert "items" in r.stdout


def test_shell_append_blocked(sandbox_root) -> None:
    root, sb, gf = sandbox_root
    before = gf.read_bytes()
    r = _run(sb, "/bin/sh", "-c", f"echo x >> {gf}")
    assert r.returncode != 0
    assert "Operation not permitted" in (r.stdout + r.stderr)
    assert gf.read_bytes() == before  # 字节不变


def test_python_open_w_blocked(sandbox_root) -> None:
    root, sb, gf = sandbox_root
    newf = gf.parent / "x.txt"
    r = _run(sb, sys.executable, "-c", f"open({str(newf)!r}, 'w')")
    assert r.returncode != 0
    assert "PermissionError" in (r.stdout + r.stderr) or "Errno 1" in (r.stdout + r.stderr)
    assert not newf.exists()


def test_rm_blocked(sandbox_root) -> None:
    root, sb, gf = sandbox_root
    r = _run(sb, "/bin/rm", str(gf))
    assert r.returncode != 0
    assert gf.exists()  # 安然无恙


def test_mv_blocked(sandbox_root) -> None:
    root, sb, gf = sandbox_root
    r = _run(sb, "/bin/mv", str(gf), str(gf.parent / "renamed.json"))
    assert r.returncode != 0
    assert gf.exists() and not (gf.parent / "renamed.json").exists()


def test_control_group_outside_frozen_zone_writable(sandbox_root) -> None:
    """对照组：沙箱内写冻结区外（/private/tmp 下）应成功，证明失败确因沙箱。"""
    root, sb, gf = sandbox_root
    outside = root / "scratch.txt"  # 非冻结区
    r = _run(sb, "/bin/sh", "-c", f"echo ok > {outside}")
    assert r.returncode == 0, r.stderr
    assert outside.read_text().strip() == "ok"
