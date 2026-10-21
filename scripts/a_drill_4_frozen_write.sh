#!/usr/bin/env bash
# scripts/a_drill_4_frozen_write.sh —— 演练4 · 沙箱内越权写冻结区（EPERM + 留痕，A2-6 / R2-A4）。
#
# 单命令可跑，结束打印 `DRILL 4 VERDICT: PASS|FAIL` + 留痕清单。期望检测者 = 内核 Seatbelt
# （非任何应用层代码）——防线在 syscall 层。AMENDMENT-17 隔离：在隔离 root 的 data/golden 副本上
# 演练（真冻结区零触碰；写被内核拦，副本亦不变）。
#
# 步骤：① 记录冻结区全树哈希；② Seatbelt 包裹下四种写法（shell 追加 / python open('w') / rm / mv）
# 目标均为副本 golden10.json → 全部 Operation not permitted / PermissionError；③ 树哈希前后一致；
# ④ 沙箱外对照组（写 /private/tmp 副本）成功——证明失败确因沙箱。
#
# 前置：/usr/bin/sandbox-exec 可用（macOS）；缺则 SKIP。python 解释器经 ABCR_PYTHON 传入
# （默认 python3；R2 由 fable 在 .venv312 激活态手跑）；不硬编码绝对解释器路径。
set -u

DRILL=4
REPO_ROOT="${ABCR_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${ABCR_PYTHON:-python3}"
PY_ABS="$(command -v "$PY" || true)"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
SBX=/usr/bin/sandbox-exec

skip() { echo "SKIP: $1"; echo "DRILL 4 VERDICT: SKIP"; exit 0; }

[ -x "$SBX" ] || skip "/usr/bin/sandbox-exec 不可用（非 macOS）"
[ -n "$PY_ABS" ] || skip "python 解释器不可用（设 ABCR_PYTHON）"
[ -f "$REPO_ROOT/data/golden/golden10.json" ] || skip "缺 data/golden/golden10.json"
avail="$("$PY_ABS" -c "from abcr.sandboxing.profiles import available; print('1' if available() else '0')" 2>/dev/null || echo 0)"
[ "$avail" = "1" ] || skip "profiles.available()=False（ABCR_SANDBOX_DISABLED?）"

TS="$("$PY_ABS" -c "from abcr.sandboxing.drills.harness import utc_stamp; print(utc_stamp())")"
ISO="$REPO_ROOT/state/audit/drills/drill4-frozen-write-$TS"
mkdir -p "$ISO/data/golden" "$ISO/logs"
cp "$REPO_ROOT/data/golden/golden10.json" "$ISO/data/golden/golden10.json"
TARGET="$ISO/data/golden/golden10.json"

SB="$ISO/abcr-frozen.sb"
"$PY_ABS" -c "from pathlib import Path; from abcr.sandboxing.profiles import frozen_profile; Path('$SB').write_text(frozen_profile('$ISO'))"

thash() { "$PY_ABS" -c "from pathlib import Path; from abcr.audit.treehash import code_tree_hash; print(code_tree_hash(Path('$ISO')))"; }
H0="$(thash)"

pass=1
blocked() {  # args: name rc errfile
  local name="$1" rc="$2" ef="$3"
  if [ "$rc" -ne 0 ] && grep -qiE "Operation not permitted|PermissionError|Errno 1|not permitted" "$ef"; then
    echo "[PASS] 写法「${name}」被内核拦（rc=${rc}）: $(head -1 "$ef")"
  else
    echo "[FAIL] 写法「${name}」未被拦（rc=${rc}）: $(head -1 "$ef")"; pass=0
  fi
}

"$SBX" -f "$SB" /bin/sh -c "echo x >> '$TARGET'" 2> "$ISO/logs/1-shell-append.err"; blocked "shell 追加重定向" "$?" "$ISO/logs/1-shell-append.err"
"$SBX" -f "$SB" "$PY_ABS" -c "open('$TARGET','w')" 2> "$ISO/logs/2-python-open-w.err"; blocked "python open('w')" "$?" "$ISO/logs/2-python-open-w.err"
"$SBX" -f "$SB" /bin/rm "$TARGET" 2> "$ISO/logs/3-rm.err"; blocked "/bin/rm" "$?" "$ISO/logs/3-rm.err"
"$SBX" -f "$SB" /bin/mv "$TARGET" "$ISO/data/golden/renamed.json" 2> "$ISO/logs/4-mv.err"; blocked "/bin/mv" "$?" "$ISO/logs/4-mv.err"

H1="$(thash)"
if [ "$H0" = "$H1" ] && [ -f "$TARGET" ]; then
  echo "[PASS] 冻结区树哈希前后逐字节一致（${H0:0:12}…），目标安然无恙"
else
  echo "[FAIL] 冻结区树哈希漂移 或 目标丢失（before=${H0:0:12} after=${H1:0:12}）"; pass=0
fi

# 对照组：沙箱外写 /private/tmp 副本应成功
CTRL="/private/tmp/abcr-drill4-ctrl-$TS.json"
cp "$TARGET" "$CTRL"
if echo "x" >> "$CTRL" 2>/dev/null && [ -f "$CTRL" ]; then
  echo "[PASS] 对照组（沙箱外写 ${CTRL}）成功——证明失败确因沙箱，非其他"
else
  echo "[FAIL] 对照组写失败——无法归因于沙箱"; pass=0
fi
rm -f "$CTRL"

# README 留痕
"$PY_ABS" - "$ISO" "$pass" "$H0" "$H1" <<'PYEOF'
import json, sys
from pathlib import Path
iso, ok, h0, h1 = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
meta = {"drill": "frozen_zone_write_eperm", "verdict": "PASS" if ok == "1" else "FAIL",
        "tree_hash_before": h0, "tree_hash_after": h1,
        "attempts": ["shell-append", "python-open-w", "rm", "mv"],
        "iso_root": iso, "note": "在隔离 data/golden 副本上；真冻结区零触碰"}
Path(iso, "README.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
PYEOF

echo ""
echo "留痕目录: $ISO"
echo "  README: $ISO/README.json"
echo "  stderr 捕获: $ISO/logs/{1-shell-append,2-python-open-w,3-rm,4-mv}.err"
echo ""
if [ "$pass" -eq 1 ]; then echo "DRILL 4 VERDICT: PASS"; exit 0; else echo "DRILL 4 VERDICT: FAIL"; exit 1; fi
