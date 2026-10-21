#!/bin/bash
# scripts/check_human_signature_domain.sh — human_signature_domain 门的诚实探针（非 root 可跑）。
#
# 依据: 清单 L146-150（human_signature_domain: pinned OpenSSL 3, abcr-human UID,
#       0600 private key, root-owned SPKI trust anchor and bidirectional spool ACL are proven;
#       on_fail: LIVE_PILOT.approval is BLOCKED）; 方案 L105/L153-164/L287-290/L530。
#
# 逐项打印 PASS: 或 BLOCKED: 原因; 任一 BLOCKED → 总退出码 1。
# 纪律: 无法验证（权限不够 / 文件缺失 / 工具缺失）一律 BLOCKED——绝不把"未检查"打成 PASS。
# 本脚本只读: 唯一的写动作是在 mktemp 私有目录里做一次 Ed25519 keygen 能力试探, 结束即删。
set -u

OPENSSL=/opt/homebrew/opt/openssl@3/bin/openssl
HUMAN_USER=abcr-human
HUMAN_HOME=/Users/abcr-human
KEY_FILE="$HUMAN_HOME/Library/Application Support/ABCR-Human/approval-ed25519.pem"
TRUST_DIR="/Library/Application Support/ABCR-Trust"
PUB_FILE="$TRUST_DIR/approval.pub"
FPR_FILE="$TRUST_DIR/approval.fingerprint"
BRIDGE_DIR="/Library/Application Support/ABCR-Bridge"

FAILURES=0
pass()    { echo "PASS: $*"; }
blocked() { echo "BLOCKED: $*"; FAILURES=$((FAILURES + 1)); }
# stat -f '%Su:%Sg:%Lp:%l' → owner:group:八进制权限:硬链接数
stat_line() { /usr/bin/stat -f '%Su:%Sg:%Lp:%l' "$1" 2>/dev/null; }
has_extended_acl() {
  /bin/ls -lde "$1" 2>/dev/null \
    | /usr/bin/awk 'NR > 1 && $0 ~ /^[[:space:]]*[0-9]+:/ {found=1} END {exit !found}'
}

echo "== human_signature_domain 诚实探针 (清单 L146-150) =="
echo "-- 以 uid=$(/usr/bin/id -u) ($(/usr/bin/id -un)) 运行; root 才能看进人域 0700 目录, 非 root 下'看不进'如实报 BLOCKED --"

# ---------------------------------------------------------------- [1/5] pinned OpenSSL 3 + Ed25519
OSSL_OK=0
if [ ! -x "$OPENSSL" ]; then
  blocked "[1/5 openssl3] 固定路径 OpenSSL 3 不存在: $OPENSSL （安装: brew install openssl@3; 绝不用 LibreSSL 顶替）"
else
  OSSL_VER="$("$OPENSSL" version 2>/dev/null || true)"
  case "$OSSL_VER" in
    "OpenSSL 3."*)
      TMPD="$(/usr/bin/mktemp -d /tmp/abcr-hsd-probe.XXXXXX)"
      if ( umask 077; "$OPENSSL" genpkey -algorithm ED25519 -out "$TMPD/probe.pem" >/dev/null 2>&1 ); then
        pass "[1/5 openssl3] $OSSL_VER @ $OPENSSL, Ed25519 keygen 实测可用"
        OSSL_OK=1
      else
        blocked "[1/5 openssl3] $OSSL_VER 存在但 Ed25519 keygen 实测失败"
      fi
      /bin/rm -rf "$TMPD"
      ;;
    *)
      blocked "[1/5 openssl3] $OPENSSL 不是 OpenSSL 3（实测: ${OSSL_VER:-无输出}）; LibreSSL/其他一律不合格"
      ;;
  esac
fi

# ---------------------------------------------------------------- [2/5] abcr-human OS 用户
HUMAN_UID="$(/usr/bin/id -u "$HUMAN_USER" 2>/dev/null || true)"
if [ -n "$HUMAN_UID" ]; then
  pass "[2/5 abcr-human] 用户存在 (uid=$HUMAN_UID)"
else
  blocked "[2/5 abcr-human] OS 用户 $HUMAN_USER 不存在（sudo ./scripts/bootstrap_abcr_human.sh 创建, 需楠授权）"
fi

# ---------------------------------------------------------------- [3/5] 私钥 0600 仅属主
KEY_STAT="$(stat_line "$KEY_FILE")"
if [ -n "$KEY_STAT" ]; then
  K_OWNER="${KEY_STAT%%:*}"; rest="${KEY_STAT#*:}"
  K_GROUP="${rest%%:*}";     rest="${rest#*:}"
  K_MODE="${rest%%:*}";      K_LINKS="${rest#*:}"
  if [ "$K_OWNER" != "$HUMAN_USER" ]; then
    blocked "[3/5 private-key] $KEY_FILE 属主是 $K_OWNER, 要求 $HUMAN_USER"
  elif [ "$K_MODE" != "600" ]; then
    blocked "[3/5 private-key] $KEY_FILE 权限是 0$K_MODE, 要求 0600（仅属主可读写）"
  elif [ "$K_LINKS" != "1" ]; then
    blocked "[3/5 private-key] $KEY_FILE 硬链接数=$K_LINKS, 要求 1（防别名逃逸）"
  elif has_extended_acl "$KEY_FILE"; then
    blocked "[3/5 private-key] $KEY_FILE 存在扩展 ACL；要求仅 0600 mode、无额外 ACL 主体"
  elif [ "$OSSL_OK" -ne 1 ]; then
    blocked "[3/5 private-key] 文件权限合格,但 OpenSSL 3 不可用,无法验证它是 Ed25519 私钥"
  elif ! "$OPENSSL" pkey -in "$KEY_FILE" -pubout -outform DER >/dev/null 2>&1; then
    blocked "[3/5 private-key] $KEY_FILE 不能由固定 OpenSSL 3 解析并导出公钥（不是有效私钥或已损坏）"
  else
    pass "[3/5 private-key] $KEY_FILE 0600 $K_OWNER:$K_GROUP links=1,无扩展 ACL,OpenSSL 3 可解析"
  fi
else
  # 区分"确实没有"与"没权限看"——两者都 BLOCKED, 但原因必须说实话
  if [ ! -d "$HUMAN_HOME" ]; then
    blocked "[3/5 private-key] $HUMAN_HOME 不存在 → 私钥必然未建"
  elif [ -n "$HUMAN_UID" ] && [ ! -x "$HUMAN_HOME" ]; then
    blocked "[3/5 private-key] 当前 uid 无权穿越 $HUMAN_HOME(0700 属人域是正确设计), 本探针【无法验证】私钥状态; 未检查≠PASS——请以 root 重跑本探针取得权威结论"
  else
    blocked "[3/5 private-key] $KEY_FILE 不存在或不可 stat（引导未跑或未生成）"
  fi
fi

# ---------------------------------------------------------------- [4/5] ABCR-Trust 锚 root-owned 0444
TRUST_FAIL=0
D_STAT="$(stat_line "$TRUST_DIR")"
if [ -z "$D_STAT" ]; then
  blocked "[4/5 trust-anchor] $TRUST_DIR 不存在"
  TRUST_FAIL=1
else
  case "$D_STAT" in
    root:wheel:555:*) : ;;
    *) blocked "[4/5 trust-anchor] $TRUST_DIR 现状 $D_STAT, 要求 root:wheel 0555"; TRUST_FAIL=1 ;;
  esac
  if has_extended_acl "$TRUST_DIR"; then
    blocked "[4/5 trust-anchor] $TRUST_DIR 存在扩展 ACL,要求无额外 ACL"; TRUST_FAIL=1
  fi
  for f in "$PUB_FILE" "$FPR_FILE"; do
    F_STAT="$(stat_line "$f")"
    if [ -z "$F_STAT" ]; then
      blocked "[4/5 trust-anchor] $f 不存在"; TRUST_FAIL=1
    else
      case "$F_STAT" in
        root:wheel:444:1) : ;;
        *) blocked "[4/5 trust-anchor] $f 现状 $F_STAT, 要求 root:wheel 0444 links=1"; TRUST_FAIL=1 ;;
      esac
      if has_extended_acl "$f"; then
        blocked "[4/5 trust-anchor] $f 存在扩展 ACL,要求无额外 ACL"; TRUST_FAIL=1
      fi
    fi
  done
  if [ "$TRUST_FAIL" -eq 0 ]; then
    if [ "$OSSL_OK" -ne 1 ]; then
      blocked "[4/5 trust-anchor] 属主/权限合格, 但 OpenSSL 3 不可用, 无法验证 approval.pub 是 Ed25519 SPKI、无法复算 fingerprint; 未检查≠PASS"
    else
      FPR_CONTENT="$(/bin/cat "$FPR_FILE" 2>/dev/null | /usr/bin/tr -d '\n')"
      CALC_FPR="$("$OPENSSL" pkey -pubin -in "$PUB_FILE" -pubout -outform DER 2>/dev/null | "$OPENSSL" dgst -sha256 2>/dev/null | /usr/bin/awk '{print $NF}')"
      if ! "$OPENSSL" pkey -pubin -in "$PUB_FILE" -noout -text 2>/dev/null | /usr/bin/grep -q 'ED25519'; then
        blocked "[4/5 trust-anchor] $PUB_FILE 无法解析为 Ed25519 SPKI 公钥"
      elif ! echo "$FPR_CONTENT" | /usr/bin/grep -Eq '^[0-9a-f]{64}$'; then
        blocked "[4/5 trust-anchor] approval.fingerprint 内容不是 64 位小写 hex（方案 L530: key_id=SPKI DER sha256 小写hex）"
      elif [ "$FPR_CONTENT" != "$CALC_FPR" ]; then
        blocked "[4/5 trust-anchor] fingerprint 与 approval.pub 的 SPKI DER sha256 不一致（记录=$FPR_CONTENT 复算=${CALC_FPR}）"
      elif [ -n "$KEY_STAT" ]; then
        KEY_FPR="$("$OPENSSL" pkey -in "$KEY_FILE" -pubout -outform DER 2>/dev/null | "$OPENSSL" dgst -sha256 2>/dev/null | /usr/bin/awk '{print $NF}')"
        if [ -z "$KEY_FPR" ] || [ "$KEY_FPR" != "$FPR_CONTENT" ]; then
          blocked "[4/5 trust-anchor] 私钥导出的 SPKI fingerprint 与 root trust anchor 不一致"
        else
          pass "[4/5 trust-anchor] $TRUST_DIR root:wheel 0555;pub/fingerprint root:wheel 0444;私钥↔公钥↔fingerprint 三方一致 (key_id=$FPR_CONTENT)"
        fi
      else
        blocked "[4/5 trust-anchor] trust anchor 自洽,但当前进程无法读取/验证私钥与 anchor 是否匹配;未检查≠PASS"
      fi
    fi
  fi
fi

# ---------------------------------------------------------------- [5/5] Bridge 双向 spool ACL（同属清单 L148-149 门文本）
check_spool() {
  # $1=path $2=expect_owner $3=expect_group
  S="$(stat_line "$1")"
  if [ -z "$S" ]; then
    blocked "[5/5 bridge-spool] $1 不存在"
    return
  fi
  case "$S" in
    "$2:$3:750:"*) pass "[5/5 bridge-spool] $1 $2:$3 0750" ;;
    *) blocked "[5/5 bridge-spool] $1 现状 $S, 要求 $2:$3 0750（方案 L288-290）" ;;
  esac
}
if [ ! -d "$BRIDGE_DIR" ]; then
  blocked "[5/5 bridge-spool] $BRIDGE_DIR 不存在（bootstrap 的 Bridge 步骤未跑, 或因 abcr-operator 缺席被 SKIP）"
else
  check_spool "$BRIDGE_DIR/operator-to-human" abcr-operator abcr-human
  check_spool "$BRIDGE_DIR/human-to-operator" abcr-human abcr-operator
  check_spool "$BRIDGE_DIR/operator-status"   abcr-operator abcr-human
fi

# ---------------------------------------------------------------- 汇总
echo "== 汇总 =="
if [ "$FAILURES" -eq 0 ]; then
  echo "human_signature_domain: 全部 PASS — live approval v2 资格化前置满足"
  exit 0
fi
echo "human_signature_domain: $FAILURES 项 BLOCKED — LIVE_PILOT.approval 维持 BLOCKED（清单 L150 on_fail）"
exit 1
