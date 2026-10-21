#!/bin/bash
# Idempotent macOS service-principal bootstrap. No ACLs, keys, code, launchd
# jobs or releases are installed here; those remain separate reviewed gates.
set -euo pipefail

AUTHORITY_SHA=40fd5fb21ff33d7da84648562c6dc12d68f15444dfea60379132af820510d0d1
MODE=check
if [ "${1:-}" = "--check" ] && [ "$#" -eq 1 ]; then
  MODE=check
elif [ "${1:-}" = "--install-reviewed" ] && [ "${2:-}" = "$AUTHORITY_SHA" ] && [ "$#" -eq 2 ]; then
  MODE=install
else
  echo "usage: $0 --check | --install-reviewed $AUTHORITY_SHA" >&2
  exit 64
fi
if [ "$MODE" = install ] && [ "$(/usr/bin/id -u)" -ne 0 ]; then
  echo "BLOCKED: account installation must run as root" >&2
  exit 77
fi

ACCOUNTS=(
  abcr-human abcr-operator abcr-probe abcr-itempool abcr-auditor abcr-builder
  abcr-candidate abcr-verifier abcr-canary abcr-activator abcr-panel
)

ensure_account() {
  local name="$1"
  if /usr/bin/id -u "$name" >/dev/null 2>&1; then
    echo "PASS: account $name exists (uid=$(/usr/bin/id -u "$name"))"
  elif [ "$MODE" = check ]; then
    echo "BLOCKED: account $name is missing"
    return 1
  else
    # 纪律:本函数以 `ensure_account … || FAIL=…` 调用,POSIX 下 set -e 在整个
    # 函数体内失效,因此每条落笔命令都必须显式判返回码,并在落笔后独立复验——
    # 否则失败的创建会静默留下 "INSTALLED" 与 FAIL=0。
    if ! /usr/sbin/sysadminctl -addUser "$name" -fullName "ABCR service: $name" \
        -shell /usr/bin/false -home "/Users/$name" >/dev/null; then
      echo "BLOCKED: sysadminctl could not create account $name"
      return 1
    fi
    if ! /usr/bin/dscl . -create "/Users/$name" Password '*'; then
      echo "BLOCKED: cannot disable password login for $name"
      return 1
    fi
    if ! /usr/bin/dscl . -create "/Users/$name" IsHidden 1; then
      echo "BLOCKED: cannot hide account $name"
      return 1
    fi
    if ! /usr/bin/id -u "$name" >/dev/null 2>&1; then
      echo "BLOCKED: account $name is absent after creation"
      return 1
    fi
    echo "INSTALLED: account $name"
  fi
  if /usr/sbin/dseditgroup -o read "$name" >/dev/null 2>&1; then
    :
  elif [ "$MODE" = install ]; then
    if ! /usr/sbin/dseditgroup -o create -r "ABCR service group: $name" "$name"; then
      echo "BLOCKED: cannot create primary service group $name"
      return 1
    fi
    if ! /usr/sbin/dseditgroup -o read "$name" >/dev/null 2>&1; then
      echo "BLOCKED: primary service group $name is absent after creation"
      return 1
    fi
  else
    echo "BLOCKED: primary service group $name is missing"
    return 1
  fi
  if ! /usr/sbin/dseditgroup -o checkmember -m "$name" "$name" >/dev/null 2>&1; then
    if [ "$MODE" = install ]; then
      if ! /usr/sbin/dseditgroup -o edit -a "$name" -t user "$name"; then
        echo "BLOCKED: cannot add $name to its service group"
        return 1
      fi
      if ! /usr/sbin/dseditgroup -o checkmember -m "$name" "$name" >/dev/null 2>&1; then
        echo "BLOCKED: $name did not become a member of its service group"
        return 1
      fi
    else
      echo "BLOCKED: $name is not a member of its service group"
      return 1
    fi
  fi
  # sysadminctl 只写目录服务记录;home 由 opendirectoryd 在首次交互登录时物化,
  # 而这些账户 shell=/usr/bin/false、Password='*',永不登录 → 永不物化。安装器
  # 对 /Users/abcr-probe/Library 用 mkdir(parents=False),父目录必须先在,否则
  # genesis 内嵌的安装器会 fail-closed。这里显式物化 0700 精简目录(与
  # bootstrap_abcr_human.sh 同形态),不使用 createhomedir——那会拷 User Template
  # 模板目录,平白扩大受检面。
  ensure_service_home "$name" || return 1
}

# sysadminctl 只写目录服务记录;home 由 opendirectoryd 在首次交互登录时物化,而
# 服务账户 shell=/usr/bin/false、Password='*',永不登录 → 永不物化。安装器对
# /Users/abcr-probe/Library 用 mkdir(parents=False),父目录缺失会让 genesis 内嵌
# 安装器 fail-closed。此处显式物化 0700 精简目录(与 bootstrap_abcr_human.sh 同
# 形态),不使用 createhomedir——那会拷 User Template 模板目录,平白扩大受检面。
#
# 纪律(C-HSD-01 同源):调用方以 `ensure_account … || FAIL=…` 形式调用,POSIX 下
# `set -e` 在整个函数体内失效,因此**每一条落笔命令都必须显式判返回码**;绝不允许
# 失败的 mkdir 穿透到 chown/chmod——那两条都跟随 symlink,等于给出一个 root 符号
# 链接跟随原语。落笔前后各做一次 lstat 型别/属主/权限核验,不符即 BLOCKED。
ensure_service_home() {
  local name="$1"
  local home="/Users/$name"
  # %Op 含文件型别与高位(setuid/setgid/sticky);%Lp 只有低 9 位,会把
  # 41700(sticky)看成与 40700 相同。目录的期望全模式是 40700。
  local expected="Directory:$name:$name:40700"
  local observed stat_out stat_rc

  stat_out="$(/usr/bin/stat -f '%HT:%Su:%Sg:%Op' "$home" 2>&1)" && stat_rc=0 || stat_rc=$?
  if [ "$stat_rc" -ne 0 ]; then
    case "$stat_out" in
      *"No such file or directory"*) observed="" ;;
      # 存在但不可达(EACCES 等)绝不能被诊断成 "missing" 而引导去 --install-reviewed
      *) echo "BLOCKED: cannot lstat $home: $stat_out"; return 1 ;;
    esac
  else
    observed="$stat_out"
  fi

  if [ -z "$observed" ]; then
    if [ "$MODE" != install ]; then
      echo "BLOCKED: home directory $home is missing"
      return 1
    fi
    if ! /bin/mkdir -m 0700 "$home"; then
      echo "BLOCKED: cannot create home directory $home"
      return 1
    fi
    observed="$(/usr/bin/stat -f '%HT:%Su:%Sg:%Op' "$home" 2>/dev/null || true)"
    if [ -z "$observed" ]; then
      echo "BLOCKED: $home unavailable immediately after creation"
      return 1
    fi
  fi

  case "$observed" in
    Directory:*) : ;;
    *) echo "BLOCKED: $home lstat type is ${observed%%:*}, expected Directory"
       return 1 ;;
  esac

  # POSIX 位相同不代表私密:一条 everyone allow 的继承 ACE 对 stat 完全不可见,
  # 而 chmod 0700 也不会清除 ACL(需 -N)。按本仓纪律只观察不擅自改,发现即 BLOCKED。
  if /bin/ls -lde "$home" 2>/dev/null | /usr/bin/awk 'NR > 1 && $0 ~ /^[[:space:]]*[0-9]+:/ {found=1} END {exit !found}'; then
    echo "BLOCKED: $home carries an extended ACL; investigate and clear it explicitly"
    return 1
  fi

  if [ "$observed" != "$expected" ]; then
    if [ "$MODE" != install ]; then
      echo "BLOCKED: $home is $observed, expected $expected"
      return 1
    fi
    # -h:落笔目标若在核验后被换成 symlink,只作用于链接本身而非其指向,
    # 杜绝 root 符号链接跟随原语(check→mutate 之间的 TOCTOU 窗口)。
    if ! /usr/sbin/chown -h "$name:$name" "$home"; then
      echo "BLOCKED: cannot chown $home"
      return 1
    fi
    if ! /bin/chmod -h 0700 "$home"; then
      echo "BLOCKED: cannot chmod $home"
      return 1
    fi
    observed="$(/usr/bin/stat -f '%HT:%Su:%Sg:%Op' "$home" 2>/dev/null || true)"
    if [ "$observed" != "$expected" ]; then
      echo "BLOCKED: $home did not converge to $expected (observed ${observed:-unavailable})"
      return 1
    fi
    echo "INSTALLED: home $home"
  fi
  # 显式返回:否则函数返回值是最后一条 echo 的退出码,stdout 上的 EPIPE/ENOSPC
  # 会把一次完全成功的物化算成 FAIL。
  return 0
}

FAIL=0
for account in "${ACCOUNTS[@]}"; do
  ensure_account "$account" || FAIL=$((FAIL + 1))
done

ensure_role_group() {
  local group="$1" description="$2" members="$3" account
  if /usr/sbin/dseditgroup -o read "$group" >/dev/null 2>&1; then
    :
  elif [ "$MODE" = install ]; then
    if ! /usr/sbin/dseditgroup -o create -r "$description" "$group" \
        || ! /usr/sbin/dseditgroup -o read "$group" >/dev/null 2>&1; then
      echo "BLOCKED: cannot create role group $group"
      FAIL=$((FAIL + 1))
      return
    fi
  else
    echo "BLOCKED: role group $group is missing"
    FAIL=$((FAIL + 1))
    return
  fi
  for account in $members; do
    if ! /usr/sbin/dseditgroup -o checkmember -m "$account" "$group" >/dev/null 2>&1; then
      if [ "$MODE" = install ]; then
        if ! /usr/sbin/dseditgroup -o edit -a "$account" -t user "$group" \
            || ! /usr/sbin/dseditgroup -o checkmember -m "$account" "$group" >/dev/null 2>&1; then
          echo "BLOCKED: cannot add $account to $group"
          FAIL=$((FAIL + 1))
        fi
      else
        echo "BLOCKED: $account is not in $group"
        FAIL=$((FAIL + 1))
      fi
    fi
  done
}

DIRECTORY_VALUES=""
read_directory_values() {
  # dscl returns exit zero for an absent attribute, so its exact diagnostic is
  # handled separately.  Any other shape is indeterminate and blocks.
  local record="$1" attribute="$2" allow_missing="$3" observed
  if ! observed="$(/usr/bin/dscl . -read "$record" "$attribute" 2>&1)"; then
    echo "BLOCKED: cannot inspect $record $attribute" >&2
    return 1
  fi
  if [ "$observed" = "No such key: $attribute" ]; then
    if [ "$allow_missing" = yes ]; then
      DIRECTORY_VALUES=""
      return 0
    fi
    echo "BLOCKED: $record has no $attribute" >&2
    return 1
  fi
  if [ "${observed%%:*}" != "$attribute" ]; then
    echo "BLOCKED: invalid $record $attribute record" >&2
    return 1
  fi
  DIRECTORY_VALUES="${observed#*:}"
}

is_dataset_authority_reader() {
  case "$1" in
    abcr-itempool|abcr-auditor) return 0 ;;
    *) return 1 ;;
  esac
}

validate_exact_dataset_reader_group() {
  # Observation only: install mode may add a missing reviewed reader above,
  # but this validator never removes or disguises an unexpected identity.
  local group=abcr-dataset-read value count itempool_count auditor_count
  local itempool_guid auditor_guid user_rows account user_id extra groups member

  if ! /usr/sbin/dseditgroup -o read "$group" >/dev/null 2>&1; then
    echo "BLOCKED: exact dataset reader group is unavailable" >&2
    return 1
  fi

  read_directory_values "/Users/abcr-itempool" GeneratedUID no || return 1
  set -- $DIRECTORY_VALUES
  if [ "$#" -ne 1 ]; then
    echo "BLOCKED: abcr-itempool has ambiguous GeneratedUID" >&2
    return 1
  fi
  itempool_guid="$1"
  read_directory_values "/Users/abcr-auditor" GeneratedUID no || return 1
  set -- $DIRECTORY_VALUES
  if [ "$#" -ne 1 ]; then
    echo "BLOCKED: abcr-auditor has ambiguous GeneratedUID" >&2
    return 1
  fi
  auditor_guid="$1"
  if [ "$itempool_guid" = "$auditor_guid" ]; then
    echo "BLOCKED: dataset authority readers share a GeneratedUID" >&2
    return 1
  fi

  read_directory_values "/Groups/$group" GroupMembership no || return 1
  count=0
  itempool_count=0
  auditor_count=0
  for value in $DIRECTORY_VALUES; do
    count=$((count + 1))
    case "$value" in
      abcr-itempool) itempool_count=$((itempool_count + 1)) ;;
      abcr-auditor) auditor_count=$((auditor_count + 1)) ;;
      *)
        echo "BLOCKED: unreviewed direct dataset reader: $value" >&2
        return 1
        ;;
    esac
  done
  if [ "$count" -ne 2 ] || [ "$itempool_count" -ne 1 ] || [ "$auditor_count" -ne 1 ]; then
    echo "BLOCKED: dataset reader direct membership is not exact" >&2
    return 1
  fi

  read_directory_values "/Groups/$group" GroupMembers no || return 1
  count=0
  itempool_count=0
  auditor_count=0
  for value in $DIRECTORY_VALUES; do
    count=$((count + 1))
    if [ "$value" = "$itempool_guid" ]; then
      itempool_count=$((itempool_count + 1))
    elif [ "$value" = "$auditor_guid" ]; then
      auditor_count=$((auditor_count + 1))
    else
      echo "BLOCKED: unreviewed dataset reader GUID: $value" >&2
      return 1
    fi
  done
  if [ "$count" -ne 2 ] || [ "$itempool_count" -ne 1 ] || [ "$auditor_count" -ne 1 ]; then
    echo "BLOCKED: dataset reader GUID membership is not exact" >&2
    return 1
  fi

  read_directory_values "/Groups/$group" NestedGroups yes || return 1
  set -- $DIRECTORY_VALUES
  if [ "$#" -ne 0 ]; then
    echo "BLOCKED: dataset reader group contains nested membership" >&2
    return 1
  fi

  # `/Search` covers every identity visible to this host.  `id -Gn` resolves
  # primary and nested/effective membership, not just the direct name list.
  if ! user_rows="$(/usr/bin/dscl /Search -list /Users UniqueID 2>&1)"; then
    echo "BLOCKED: cannot enumerate directory users" >&2
    return 1
  fi
  count=0
  itempool_count=0
  auditor_count=0
  while IFS= read -r value; do
    [ -n "$value" ] || continue
    set -- $value
    if [ "$#" -ne 2 ]; then
      echo "BLOCKED: invalid directory user enumeration" >&2
      return 1
    fi
    account="$1"
    user_id="$2"
    case "$account" in ''|*[!A-Za-z0-9._-]*)
      echo "BLOCKED: invalid directory account name" >&2
      return 1 ;;
    esac
    case "$user_id" in -*) extra="${user_id#-}" ;; *) extra="$user_id" ;; esac
    case "$extra" in ''|*[!0-9]*)
      echo "BLOCKED: invalid directory account UID" >&2
      return 1 ;;
    esac
    if ! groups="$(/usr/bin/id -Gn "$account" 2>/dev/null)"; then
      echo "BLOCKED: effective groups unavailable for $account" >&2
      return 1
    fi
    member=no
    for value in $groups; do
      if [ "$value" = "$group" ]; then
        member=yes
      fi
    done
    if [ "$member" = yes ]; then
      if ! is_dataset_authority_reader "$account"; then
        echo "BLOCKED: unreviewed effective dataset reader: $account" >&2
        return 1
      fi
      count=$((count + 1))
      case "$account" in
        abcr-itempool) itempool_count=$((itempool_count + 1)) ;;
        abcr-auditor) auditor_count=$((auditor_count + 1)) ;;
      esac
    fi
  done <<< "$user_rows"
  if [ "$count" -ne 2 ] || [ "$itempool_count" -ne 1 ] || [ "$auditor_count" -ne 1 ]; then
    echo "BLOCKED: dataset reader effective membership is not exact" >&2
    return 1
  fi
  echo "PASS: $group contains exactly abcr-itempool and abcr-auditor (direct/GUID/effective; no nested groups)"
}

# Every non-primary group named by path-ownership-v1 is provisioned here.  The
# list is deliberately finite: adding a new reader requires changing this
# reviewed bootstrap, not placing a caller-controlled group in an environment.
ensure_role_group abcr-panel-read "ABCR public snapshot readers" \
  "abcr-panel"
ensure_role_group abcr-auditor-read "ABCR evidence readers" \
  "abcr-auditor"
ensure_role_group abcr-research-read "ABCR research readers" \
  "abcr-auditor"
ensure_role_group abcr-lab-read "ABCR probe lab readers" \
  "abcr-probe abcr-operator abcr-auditor"
ensure_role_group abcr-devread "ABCR sealed development bundle readers" \
  "abcr-itempool abcr-operator abcr-probe abcr-auditor"
ensure_role_group abcr-dataset-read "ABCR frozen dataset readers" \
  "abcr-itempool abcr-auditor"
validate_exact_dataset_reader_group || FAIL=$((FAIL + 1))
# The outer mission coordinator writes a finite plain input.  The builder may
# read that input but may not write it or traverse the operator's control root.
ensure_role_group abcr-builder-input "ABCR sealed mission input readers" \
  "abcr-operator abcr-builder"
# These principals execute their immutable service runtime from the release.
# This does not grant the untrusted Codex/candidate children access: their
# Seatbelt profiles explicitly omit/deny RELEASE_ROOT.
ensure_role_group abcr-release-read "ABCR sealed release and receipt readers" \
  "abcr-human abcr-operator abcr-probe abcr-itempool abcr-auditor abcr-builder abcr-verifier abcr-canary abcr-activator abcr-panel"
ensure_role_group abcr-broker-clients "ABCR broker socket clients" \
  "abcr-human abcr-operator abcr-probe abcr-itempool abcr-auditor abcr-builder abcr-verifier abcr-canary abcr-activator"

# FAIL 在两种模式下都必须致命:install 模式此前无条件打印 "installation complete"
# 并 exit 0,使任何 BLOCKED 诊断都无法让本次安装失败。
if [ "$FAIL" -ne 0 ]; then
  echo "service_accounts: $FAIL checks BLOCKED"
  exit 1
fi
if [ "$MODE" = check ]; then
  echo "service_accounts: all PASS"
  exit 0
fi

echo "service_accounts: installation complete; rerun --check before ACL bootstrap"
