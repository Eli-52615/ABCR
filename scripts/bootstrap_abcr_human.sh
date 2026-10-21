#!/bin/bash
# scripts/bootstrap_abcr_human.sh — 人域签名边界（human_signature_domain）root 幂等引导。
#
# 依据（方案 = ABCR-人格探索单一UI与自动闭环-实现方案-V1.0-20260719.md）:
#   - 方案 L105  人域签名边界门: 固定路径 OpenSSL 3 + Ed25519 / 独立 abcr-human OS 用户 /
#                private key 仅该用户可读 / public key+fingerprint 为 root-owned 只读 trust anchor
#   - 方案 L153-164 文件落点: ABCR-Human(0700)、approval-ed25519.pem(0600)、
#                ABCR-Trust(approval.pub/approval.fingerprint root-owned 0444)、Bridge 三向 spool
#   - 方案 L287-290 ACL 表: ABCR-Trust root:wheel 0555/0444;
#                Bridge/operator-to-human  abcr-operator:abcr-human 0750
#                Bridge/human-to-operator  abcr-human:abcr-operator 0750
#                Bridge/operator-status    abcr-operator:abcr-human 0750
#   - 方案 L530-532 密钥语义: key_id = 公钥 SPKI DER 字节的 SHA-256 小写 hex;
#                轮换绝不由本脚本实现（正常轮换需旧 key 签 rotation statement + root 原子安装）
#   - 清单 L146-150 human_signature_domain 门四条件
#
# 用法:
#   sudo ./scripts/bootstrap_abcr_human.sh          # 真执行（必须 root;需楠授权后才允许真跑）
#   ./scripts/bootstrap_abcr_human.sh --check       # 只读模式: 报告将做什么, 不写任何系统状态
#   ./scripts/bootstrap_abcr_human.sh --rotate      # 一律拒绝: 本脚本不实现轮换, 打印指引后退出
#
# 纪律:
#   - 已存在的私钥【绝不覆盖】; trust anchor 与私钥不一致时诚实失败, 不静默替换。
#   - OpenSSL 用固定绝对路径; 缺失即诚实失败并打印安装指引, 绝不静默换 /usr/bin/openssl(LibreSSL)。
#   - abcr-operator 账户尚不存在时, Bridge spool 步骤打印 SKIP 原因并以 rc=0 归零（分阶段幂等）。
#   - 绝不打印任何私钥字节 / secret / feishu.env 内容。
#
# 退出码: 0=成功(或 --check 且无硬阻塞) 1=硬失败/阻塞 2=用法错误或 --rotate 拒绝
set -euo pipefail

OPENSSL=/opt/homebrew/opt/openssl@3/bin/openssl

HUMAN_USER=abcr-human
HUMAN_GROUP=abcr-human
OPERATOR_USER=abcr-operator
OPERATOR_GROUP=abcr-operator

HUMAN_HOME=/Users/abcr-human
HUMAN_DIR="$HUMAN_HOME/Library/Application Support/ABCR-Human"
KEY_FILE="$HUMAN_DIR/approval-ed25519.pem"

TRUST_DIR="/Library/Application Support/ABCR-Trust"
PUB_FILE="$TRUST_DIR/approval.pub"
FPR_FILE="$TRUST_DIR/approval.fingerprint"

BRIDGE_DIR="/Library/Application Support/ABCR-Bridge"
BRIDGE_O2H="$BRIDGE_DIR/operator-to-human"
BRIDGE_H2O="$BRIDGE_DIR/human-to-operator"
BRIDGE_STA="$BRIDGE_DIR/operator-status"

# staging 探测按发起 sudo 的真实用户 home 找（root 下 $HOME=/var/root 会找错地方）
STAGING_HOME="${SUDO_USER:+/Users/$SUDO_USER}"
STAGING_HOME="${STAGING_HOME:-$HOME}"
STAGING_ENV="$STAGING_HOME/Library/Application Support/ABCR-Human-staging/feishu.env"

MODE=run
usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}
for arg in "$@"; do
  case "$arg" in
    --check) MODE=check ;;
    --rotate)
      echo "REFUSED: 本脚本不实现密钥轮换（方案 L532）。" >&2
      echo "轮换纪律:" >&2
      echo "  - 正常轮换: 用【旧 private key】签 rotation statement（记录 old/new key_id、生效、retire、revocation 窗），" >&2
      echo "    再由 root 走独立的轮换工序【原子】安装新 trust anchor; 不能由 Operator 自报。" >&2
      echo "  - 旧 key 丢失: 走线下 root-owned 更新 + 人工确认。" >&2
      echo "  - token 只接受 issued_at 时 active 的 key; 紧急撤销后拒绝未首次 claim 的旧 key token。" >&2
      echo "本引导脚本只负责首次建域, 对已存在私钥永远不覆盖。" >&2
      exit 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $arg" >&2; echo "用法: $0 [--check|--rotate|--help]" >&2; exit 2 ;;
  esac
done

log()  { echo "[bootstrap_abcr_human] $*"; }
plan() { echo "[bootstrap_abcr_human][check] $*"; }
die()  { echo "[bootstrap_abcr_human] FAIL: $*" >&2; exit 1; }

have_user()  { /usr/bin/id -u "$1" >/dev/null 2>&1; }
have_group() { /usr/sbin/dseditgroup -o read "$1" >/dev/null 2>&1; }
stat_ugm()   { /usr/bin/stat -f '%Su:%Sg:%Lp' "$1" 2>/dev/null; }

# ---- symlink 防护（C-HSD-01）------------------------------------------------
# chown/chmod/mkdir -p/[ -f ] 都会跟随符号链接: root 重跑时, 若人域路径组件或锚文件
# 被换成 symlink, 即成 root 任意 chown/chmod 原语（对抗审查已实测复现）。
# 故所有权限落笔前一律按【lstat 口径】校验——与 check_human_signature_domain.sh 的
# /usr/bin/stat 默认口径一致（macOS stat 不加 -L 即 lstat(2)）:
#   1) [ -L ] 拒绝符号链接（含 dangling, [ -L ] 本身就是 lstat 语义）;
#   2) stat -f %HT 确认 Directory / Regular File 后才允许 chown/chmod。
lstat_type() { /usr/bin/stat -f '%HT' "$1" 2>/dev/null; }
reject_symlink() {  # $1=path $2=上下文
  if [ -L "$1" ]; then
    die "symlink 防护: $1 是符号链接（$2）。拒绝对符号链接做 chown/chmod/写入——疑似路径被植入, 请人工核查后再重跑。"
  fi
}
require_dir_nofollow() {  # $1=path $2=上下文 —— lstat 确认真实目录后才准落笔
  local t
  reject_symlink "$1" "$2"
  t="$(lstat_type "$1")"
  [ "$t" = "Directory" ] || die "symlink 防护: $1 lstat 类型为「${t:-不存在/不可 lstat}」, 要求 Directory（$2）"
}
require_file_nofollow() {  # $1=path $2=上下文 —— lstat 确认真实普通文件后才准落笔
  local t links
  reject_symlink "$1" "$2"
  t="$(lstat_type "$1")"
  [ "$t" = "Regular File" ] || die "symlink 防护: $1 lstat 类型为「${t:-不存在/不可 lstat}」, 要求 Regular File（$2）"
  links="$(/usr/bin/stat -f '%l' "$1" 2>/dev/null || true)"
  [ "$links" = "1" ] || die "hardlink 防护: $1 硬链接数=${links:-不可 stat}, 要求 1（$2）"
}

HARD_BLOCK=0

# ---------------------------------------------------------------- 0. 前置
if [ "$MODE" = run ] && [ "$(/usr/bin/id -u)" -ne 0 ]; then
  die "真执行必须 root（sudo）。只读预览请用 --check。"
fi

# 固定绝对路径 OpenSSL 3 —— 缺失/非 OpenSSL3 都是硬失败, 绝不退回 LibreSSL
if [ ! -x "$OPENSSL" ]; then
  echo "[bootstrap_abcr_human] BLOCKED: 固定路径 OpenSSL 3 不存在: $OPENSSL" >&2
  echo "  安装指引: brew install openssl@3   （装到 /opt/homebrew/opt/openssl@3）" >&2
  echo "  绝不退回 /usr/bin/openssl（LibreSSL, 无法保证 Ed25519/SPKI 语义一致）。" >&2
  [ "$MODE" = check ] && { HARD_BLOCK=1; plan "后续密钥/anchor 步骤全部被此项阻塞"; }
  [ "$MODE" = run ] && exit 1
else
  OSSL_VER="$("$OPENSSL" version 2>/dev/null || true)"
  case "$OSSL_VER" in
    "OpenSSL 3."*) : ;;
    *)
      echo "[bootstrap_abcr_human] BLOCKED: $OPENSSL 不是 OpenSSL 3（实测: ${OSSL_VER:-无输出}），拒绝使用。" >&2
      [ "$MODE" = check ] && HARD_BLOCK=1
      [ "$MODE" = run ] && exit 1
      ;;
  esac
  [ "$HARD_BLOCK" -eq 0 ] && log "OpenSSL 固定点 OK: $OSSL_VER ($OPENSSL)"
fi

# ---------------------------------------------------------------- 1. abcr-human 用户/组
if have_user "$HUMAN_USER"; then
  log "用户 $HUMAN_USER 已存在 (uid=$(/usr/bin/id -u "$HUMAN_USER")) — 跳过创建"
else
  if [ "$MODE" = check ]; then
    plan "WILL: sysadminctl -addUser ${HUMAN_USER}（shell=/usr/bin/false, home=$HUMAN_HOME, 无交互登录, IsHidden=1, Password='*'）"
  else
    log "创建用户 ${HUMAN_USER}（无交互登录）"
    /usr/sbin/sysadminctl -addUser "$HUMAN_USER" \
      -fullName "ABCR Human Signature Domain" \
      -shell /usr/bin/false \
      -home "$HUMAN_HOME" 2>&1 | grep -v -i 'password' || true
    have_user "$HUMAN_USER" || die "sysadminctl 创建 $HUMAN_USER 失败"
    # 禁用口令登录（crypt 字段置 '*'）并隐藏账户
    /usr/bin/dscl . -create "/Users/$HUMAN_USER" Password '*'
    /usr/bin/dscl . -create "/Users/$HUMAN_USER" IsHidden 1
    log "用户 $HUMAN_USER 创建完成 (uid=$(/usr/bin/id -u "$HUMAN_USER"))"
  fi
fi

if have_group "$HUMAN_GROUP"; then
  log "组 $HUMAN_GROUP 已存在 — 跳过创建"
else
  if [ "$MODE" = check ]; then
    plan "WILL: dseditgroup 创建组 $HUMAN_GROUP 并把 $HUMAN_USER 加入"
  else
    /usr/sbin/dseditgroup -o create -r "ABCR Human Domain" "$HUMAN_GROUP"
    log "组 $HUMAN_GROUP 创建完成"
  fi
fi
if [ "$MODE" = run ]; then
  if ! /usr/sbin/dseditgroup -o checkmember -m "$HUMAN_USER" "$HUMAN_GROUP" >/dev/null 2>&1; then
    /usr/sbin/dseditgroup -o edit -a "$HUMAN_USER" -t user "$HUMAN_GROUP"
    log "已把 $HUMAN_USER 加入组 $HUMAN_GROUP"
  fi
fi

# ---------------------------------------------------------------- 2. 人域目录（0700, 属 abcr-human）
if [ "$MODE" = check ]; then
  if [ -d "$HUMAN_DIR" ]; then
    plan "OK: $HUMAN_DIR 已存在（现状 $(stat_ugm "$HUMAN_DIR" || echo '不可 stat—无穿越权')）; WILL 校准为 $HUMAN_USER:$HUMAN_GROUP 0700"
  else
    plan "WILL: mkdir -p '$HUMAN_DIR' 并链式 chown $HUMAN_USER:$HUMAN_GROUP + chmod 0700（home 起每级）"
  fi
else
  # C-HSD-01: mkdir -p 之前先逐级拒绝 symlink（mkdir -p 对已存在组件也会跟随链接,
  # 否则后续 chown/chmod 会落到域外目标上）
  for d in "$HUMAN_HOME" "$HUMAN_HOME/Library" "$HUMAN_HOME/Library/Application Support" "$HUMAN_DIR"; do
    reject_symlink "$d" "人域目录链 mkdir 前置校验"
    if [ -e "$d" ]; then
      t="$(lstat_type "$d")"
      [ "$t" = "Directory" ] || die "symlink 防护: $d 已存在但 lstat 类型为「${t:-未知}」, 要求 Directory——请人工核查后再重跑"
    fi
  done
  /bin/mkdir -p "$HUMAN_DIR"
  for d in "$HUMAN_HOME" "$HUMAN_HOME/Library" "$HUMAN_HOME/Library/Application Support" "$HUMAN_DIR"; do
    require_dir_nofollow "$d" "人域目录链 chown/chmod 落笔前"
    /usr/sbin/chown "$HUMAN_USER:$HUMAN_GROUP" "$d"
    /bin/chmod 0700 "$d"
  done
  log "人域目录就位: $HUMAN_DIR ($(stat_ugm "$HUMAN_DIR"))"
fi

# ---------------------------------------------------------------- 3. 私钥（绝不覆盖）
KEY_EXISTS=0
if [ "$MODE" = run ]; then
  # C-HSD-01: [ -f ] 跟随符号链接——KEY_FILE 若被换成 symlink, 存在性判定和后面的
  # chown/chmod 都会落到链接目标上。先按 lstat 口径拒绝。
  reject_symlink "$KEY_FILE" "私钥存在性判定前"
  [ -f "$KEY_FILE" ] && KEY_EXISTS=1
else
  # --check 以非 root 跑时可能无穿越权; 诚实报告"无法确认"而不是猜
  if [ -f "$KEY_FILE" ]; then KEY_EXISTS=1
  elif [ ! -r "$HUMAN_DIR" ] && [ -d "$HUMAN_HOME" ]; then KEY_EXISTS=-1; fi
fi

if [ "$KEY_EXISTS" -eq 1 ]; then
  log "私钥已存在: $KEY_FILE — 绝不覆盖（轮换需显式 --rotate, 且本脚本会拒绝并打印指引）"
  if [ "$MODE" = run ]; then
    # C-HSD-01: chown/chmod 落笔前 lstat 确认真实普通文件
    require_file_nofollow "$KEY_FILE" "私钥 chown/chmod 落笔前"
    /usr/sbin/chown "$HUMAN_USER:$HUMAN_GROUP" "$KEY_FILE"
    /bin/chmod 0600 "$KEY_FILE"
  fi
elif [ "$KEY_EXISTS" -eq -1 ]; then
  plan "UNKNOWN: 无权穿越 $HUMAN_DIR, 无法确认私钥是否已存在（root 真跑时会准确判断; 已存在则绝不覆盖）"
else
  if [ "$MODE" = check ]; then
    [ "$HARD_BLOCK" -eq 1 ] || plan "WILL: umask 077 后 $OPENSSL genpkey -algorithm ED25519 生成 ${KEY_FILE}（0600, $HUMAN_USER:${HUMAN_GROUP}）"
  else
    log "生成 Ed25519 私钥（仅 $HUMAN_USER 可读）"
    # 临时私钥绝不在 abcr-human 可写目录内生成。root 私有的 0700 mktemp
    # 目录关闭「检查→openssl 打开」之间的 symlink 竞态，完成后再原子 rename。
    KEY_TMPD="$(/usr/bin/mktemp -d /tmp/abcr-human-key.XXXXXX)"
    /bin/chmod 0700 "$KEY_TMPD"
    TMP_KEY="$KEY_TMPD/approval-ed25519.pem"
    (
      umask 077
      trap '/bin/rm -rf "$KEY_TMPD"' EXIT
      "$OPENSSL" genpkey -algorithm ED25519 -out "$TMP_KEY"
      require_file_nofollow "$TMP_KEY" "私钥临时文件生成后"
      /usr/sbin/chown "$HUMAN_USER:$HUMAN_GROUP" "$TMP_KEY"
      /bin/chmod 0600 "$TMP_KEY"
      reject_symlink "$KEY_FILE" "私钥原子安装前"
      [ ! -e "$KEY_FILE" ] || die "私钥安装竞态: $KEY_FILE 在生成期间出现;拒绝覆盖"
      /bin/mv "$TMP_KEY" "$KEY_FILE"
      require_file_nofollow "$KEY_FILE" "私钥原子安装后"
    )
    log "私钥生成完成: $KEY_FILE (0600 $HUMAN_USER:$HUMAN_GROUP; 私钥字节不打印)"
  fi
fi

# ---------------------------------------------------------------- 4. Trust anchor（root:wheel, 目录 0555, 文件 0444）
if [ "$MODE" = check ]; then
  if [ -f "$PUB_FILE" ] && [ -f "$FPR_FILE" ]; then
    plan "OK: trust anchor 已存在（$PUB_FILE / ${FPR_FILE}）; 真跑时会与私钥导出比对, 不一致则诚实失败(不静默替换); 一致则幂等重申 root:wheel 0555/0444"
  elif [ ! -e "$PUB_FILE" ] && [ ! -L "$PUB_FILE" ] && [ ! -e "$FPR_FILE" ] && [ ! -L "$FPR_FILE" ]; then
    plan "WILL: 从私钥导出 approval.pub(SPKI PEM) 与 approval.fingerprint(SPKI DER sha256 小写hex=key_id, 方案 L530)"
    plan "WILL: 安装进 $TRUST_DIR — 目录 root:wheel 0555, 文件 root:wheel 0444, 临时解锁目录写位后回锁"
  else
    plan "PARTIAL: trust anchor 残缺（approval.pub 与 approval.fingerprint 只存其一, 或存在 symlink 残件）——真跑会诚实失败并要求人工清理, 绝不自动补全/替换"
  fi
else
  [ -f "$KEY_FILE" ] || die "私钥缺失, 无法导出 trust anchor（不应发生: 上一步已生成）"
  require_file_nofollow "$KEY_FILE" "trust anchor 导出（私钥读取）前"
  TMPD="$(/usr/bin/mktemp -d /tmp/abcr-trust.XXXXXX)"
  trap '/bin/rm -rf "$TMPD"' EXIT
  "$OPENSSL" pkey -in "$KEY_FILE" -pubout -out "$TMPD/approval.pub"
  NEW_FPR="$("$OPENSSL" pkey -in "$KEY_FILE" -pubout -outform DER | "$OPENSSL" dgst -sha256 | /usr/bin/awk '{print $NF}')"
  echo "$NEW_FPR" | /usr/bin/grep -Eq '^[0-9a-f]{64}$' || die "fingerprint 计算异常（非 64 位小写 hex）"
  printf '%s\n' "$NEW_FPR" > "$TMPD/approval.fingerprint"

  # C-HSD-01: 锚路径先按 lstat 口径拒绝 symlink（[ -f ]/cmp/chown/chmod 都会跟随链接）
  reject_symlink "$TRUST_DIR" "trust anchor 目录判定前"
  reject_symlink "$PUB_FILE"  "trust anchor 文件判定前"
  reject_symlink "$FPR_FILE"  "trust anchor 文件判定前"

  # C-HSD-02: 三态分支——双在=cmp 校验; 双缺=首次安装; 单在=partial anchor 明确诊断,
  # 绝不把残缺锚说成「key 不一致」, 也绝不自动补全/替换。
  PUB_PRESENT=0; FPR_PRESENT=0
  [ -e "$PUB_FILE" ] && PUB_PRESENT=1
  [ -e "$FPR_FILE" ] && FPR_PRESENT=1

  if [ "$PUB_PRESENT" -eq 1 ] && [ "$FPR_PRESENT" -eq 1 ]; then
    require_file_nofollow "$PUB_FILE" "锚内容比对前"
    require_file_nofollow "$FPR_FILE" "锚内容比对前"
    if /usr/bin/cmp -s "$TMPD/approval.pub" "$PUB_FILE" \
       && /usr/bin/cmp -s "$TMPD/approval.fingerprint" "$FPR_FILE"; then
      log "trust anchor 已存在且与私钥一致 (key_id=$NEW_FPR) — 内容不动"
      # C-HSD-03a: 幂等重申属主/权限——内容一字不动, 但权限/属主漂移要拉回
      # root:wheel + 目录 0555 + 文件 0444（方案 L287 ACL 表）
      require_dir_nofollow "$TRUST_DIR" "锚属主/权限重申前"
      /usr/sbin/chown root:wheel "$TRUST_DIR" "$PUB_FILE" "$FPR_FILE"
      /bin/chmod 0555 "$TRUST_DIR"
      /bin/chmod 0444 "$PUB_FILE" "$FPR_FILE"
      log "trust anchor 属主/权限已幂等重申: root:wheel; 目录 0555; 文件 0444"
    else
      die "trust anchor 已存在但与当前私钥【不一致】。拒绝静默替换（方案 L532: 轮换必须走旧 key 签名的 rotation statement + root 原子安装, 或线下 root-owned 更新+人工确认）。请人工核对 $TRUST_DIR 与 ${KEY_FILE}。"
    fi
  elif [ "$PUB_PRESENT" -eq 0 ] && [ "$FPR_PRESENT" -eq 0 ]; then
    /bin/mkdir -p "$TRUST_DIR"
    require_dir_nofollow "$TRUST_DIR" "锚目录 chmod/安装前"
    /bin/chmod 0755 "$TRUST_DIR"
    /usr/bin/install -o root -g wheel -m 0444 "$TMPD/approval.pub" "$PUB_FILE"
    /usr/bin/install -o root -g wheel -m 0444 "$TMPD/approval.fingerprint" "$FPR_FILE"
    /usr/sbin/chown root:wheel "$TRUST_DIR"
    /bin/chmod 0555 "$TRUST_DIR"
    log "trust anchor 安装完成: $TRUST_DIR (root:wheel 0555; 文件 0444; key_id=$NEW_FPR)"
  else
    if [ "$PUB_PRESENT" -eq 1 ]; then
      ANCHOR_HAVE="$PUB_FILE"; ANCHOR_MISS="$FPR_FILE"
    else
      ANCHOR_HAVE="$FPR_FILE"; ANCHOR_MISS="$PUB_FILE"
    fi
    die "trust anchor 处于【partial anchor（残缺锚）】状态: 已存在 ${ANCHOR_HAVE}, 缺失 ${ANCHOR_MISS}。这【不是 key 不一致】, 是锚安装/清理不完整。拒绝自动补全或替换——请人工核查 $TRUST_DIR 的来源, 确认后手工清理残件, 再重跑本脚本。"
  fi
fi

# ---------------------------------------------------------------- 5. Bridge 双向 spool（abcr-operator 缺席则 SKIP, rc 归零）
bridge_step() {
  if ! have_user "$OPERATOR_USER"; then
    log "SKIP: Bridge spool 未建 — 原因: 账户 $OPERATOR_USER 尚不存在（由 operator 域引导负责创建）。分阶段幂等: 本步骤按设计跳过、不计失败, 待 $OPERATOR_USER 就位后重跑本脚本即可补齐。"
    return 0
  fi
  if [ "$MODE" = check ]; then
    plan "WILL: 确保组 $OPERATOR_GROUP 存在并含 $OPERATOR_USER"
    plan "WILL: mkdir Bridge spool（父目录 $BRIDGE_DIR root:wheel 0755）:"
    plan "  $BRIDGE_O2H  -> $OPERATOR_USER:$HUMAN_GROUP 0750   (operator 写, human 只读导入)"
    plan "  $BRIDGE_H2O  -> $HUMAN_USER:$OPERATOR_GROUP 0750   (human 写, operator 只读导入)"
    plan "  $BRIDGE_STA  -> $OPERATOR_USER:$HUMAN_GROUP 0750   (operator 原子写脱敏 snapshot, human 只读)"
    return 0
  fi
  if ! have_group "$OPERATOR_GROUP"; then
    /usr/sbin/dseditgroup -o create -r "ABCR Operator Domain" "$OPERATOR_GROUP"
    log "组 $OPERATOR_GROUP 创建完成"
  fi
  if ! /usr/sbin/dseditgroup -o checkmember -m "$OPERATOR_USER" "$OPERATOR_GROUP" >/dev/null 2>&1; then
    /usr/sbin/dseditgroup -o edit -a "$OPERATOR_USER" -t user "$OPERATOR_GROUP"
  fi
  # C-HSD-01 同类防护: spool 链 mkdir 前逐一拒绝 symlink, chown/chmod 落笔前 lstat 确认真实目录
  for d in "$BRIDGE_DIR" "$BRIDGE_O2H" "$BRIDGE_H2O" "$BRIDGE_STA"; do
    reject_symlink "$d" "Bridge spool mkdir 前置校验"
    if [ -e "$d" ]; then
      t="$(lstat_type "$d")"
      [ "$t" = "Directory" ] || die "symlink 防护: $d 已存在但 lstat 类型为「${t:-未知}」, 要求 Directory——请人工核查后再重跑"
    fi
  done
  /bin/mkdir -p "$BRIDGE_O2H" "$BRIDGE_H2O" "$BRIDGE_STA"
  for d in "$BRIDGE_DIR" "$BRIDGE_O2H" "$BRIDGE_H2O" "$BRIDGE_STA"; do
    require_dir_nofollow "$d" "Bridge spool chown/chmod 落笔前"
  done
  /usr/sbin/chown root:wheel "$BRIDGE_DIR";               /bin/chmod 0755 "$BRIDGE_DIR"
  /usr/sbin/chown "$OPERATOR_USER:$HUMAN_GROUP" "$BRIDGE_O2H"; /bin/chmod 0750 "$BRIDGE_O2H"
  /usr/sbin/chown "$HUMAN_USER:$OPERATOR_GROUP" "$BRIDGE_H2O"; /bin/chmod 0750 "$BRIDGE_H2O"
  /usr/sbin/chown "$OPERATOR_USER:$HUMAN_GROUP" "$BRIDGE_STA"; /bin/chmod 0750 "$BRIDGE_STA"
  log "Bridge spool 就位:"
  log "  operator-to-human $(stat_ugm "$BRIDGE_O2H")"
  log "  human-to-operator $(stat_ugm "$BRIDGE_H2O")"
  log "  operator-status   $(stat_ugm "$BRIDGE_STA")"
}
bridge_step

# ---------------------------------------------------------------- 6. staging 迁移提示（只提示, 绝不自动迁移, 不读内容）
if [ -f "$STAGING_ENV" ]; then
  log "NOTICE: 发现 staging 凭据文件 $STAGING_ENV"
  log "  本脚本【不自动迁移】(内容含 secret, 一字不读不打印)。迁移动作留给 root 执行段人工确认后执行, 例如:"
  log "    sudo /bin/mv '$STAGING_ENV' '$HUMAN_DIR/feishu.env' && sudo /usr/sbin/chown $HUMAN_USER:$HUMAN_GROUP '$HUMAN_DIR/feishu.env' && sudo /bin/chmod 0600 '$HUMAN_DIR/feishu.env'"
else
  log "staging 凭据: $STAGING_ENV 不存在 — 无迁移事项"
fi

# ---------------------------------------------------------------- 收尾
if [ "$MODE" = check ]; then
  if [ "$HARD_BLOCK" -eq 1 ]; then
    plan "结论: 存在硬阻塞（OpenSSL 3 固定点缺失/不合格）, 真跑会失败。exit 1"
    exit 1
  fi
  plan "结论: 只读检查完成, 未写任何系统状态。真跑请: sudo $0 （需楠授权）"
  exit 0
fi
log "引导完成（幂等: 重跑安全; 私钥永不覆盖）。验收请跑: ./scripts/check_human_signature_domain.sh"
