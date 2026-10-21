#!/bin/bash
# Provision the independent root-only ResearchMemory seal key.  This does not
# touch the ledger and does not create a PASS seal for an absent/stale ledger.
set -euo pipefail

OPENSSL=/opt/homebrew/opt/openssl@3/bin/openssl
PRIVATE_DIR="/Library/Application Support/ABCR-Bootstrap/seal-broker"
PRIVATE_KEY="$PRIVATE_DIR/research-memory-ed25519.pem"
TRUST_DIR="/Library/Application Support/ABCR-Trust"
PUBLIC_KEY="$TRUST_DIR/research-memory-sealer.pub"
FINGERPRINT="$TRUST_DIR/research-memory-sealer.fingerprint"
MODE=run
if [ "${1:-}" = "--check" ] && [ "$#" -eq 1 ]; then
  MODE=check
elif [ "$#" -ne 0 ]; then
  echo "usage: $0 [--check]" >&2
  exit 64
fi
if [ "$MODE" = run ] && [ "$(/usr/bin/id -u)" -ne 0 ]; then
  echo "BLOCKED: provisioning must run as root" >&2
  exit 77
fi
if [ ! -x "$OPENSSL" ] || ! "$OPENSSL" version | /usr/bin/grep -q '^OpenSSL 3\.'; then
  echo "BLOCKED: pinned OpenSSL 3 is unavailable" >&2
  exit 1
fi

type_of() { /usr/bin/stat -f '%HT' "$1" 2>/dev/null || true; }
links_of() { /usr/bin/stat -f '%l' "$1" 2>/dev/null || true; }
safe_dir() {
  [ ! -L "$1" ] && [ "$(type_of "$1")" = "Directory" ] \
    || { echo "BLOCKED: unsafe directory: $1" >&2; exit 1; }
}
safe_file() {
  [ ! -L "$1" ] && [ "$(type_of "$1")" = "Regular File" ] \
    && [ "$(links_of "$1")" = "1" ] \
    || { echo "BLOCKED: unsafe file: $1" >&2; exit 1; }
}
fingerprint_private() {
  "$OPENSSL" pkey -in "$PRIVATE_KEY" -pubout -outform DER 2>/dev/null \
    | "$OPENSSL" dgst -sha256 | /usr/bin/awk '{print $NF}'
}
fingerprint_public() {
  "$OPENSSL" pkey -pubin -in "$PUBLIC_KEY" -pubout -outform DER 2>/dev/null \
    | "$OPENSSL" dgst -sha256 | /usr/bin/awk '{print $NF}'
}

if [ "$MODE" = check ]; then
  FAIL=0
  for path in "$PRIVATE_KEY" "$PUBLIC_KEY" "$FINGERPRINT"; do
    if [ ! -e "$path" ] || [ -L "$path" ]; then
      echo "BLOCKED: missing/unsafe $path"; FAIL=$((FAIL + 1))
    fi
  done
  if [ "$FAIL" -ne 0 ]; then exit 1; fi
  safe_file "$PRIVATE_KEY"; safe_file "$PUBLIC_KEY"; safe_file "$FINGERPRINT"
  P_STAT="$(/usr/bin/stat -f '%Su:%Sg:%Lp' "$PRIVATE_KEY")"
  U_STAT="$(/usr/bin/stat -f '%Su:%Sg:%Lp' "$PUBLIC_KEY")"
  F_STAT="$(/usr/bin/stat -f '%Su:%Sg:%Lp' "$FINGERPRINT")"
  RECORDED="$(/bin/cat "$FINGERPRINT" | /usr/bin/tr -d '\n')"
  if [ "$P_STAT" != "root:wheel:600" ] || [ "$U_STAT" != "root:wheel:444" ] \
      || [ "$F_STAT" != "root:wheel:444" ] \
      || [ "$(fingerprint_private)" != "$RECORDED" ] \
      || [ "$(fingerprint_public)" != "$RECORDED" ]; then
    echo "BLOCKED: ResearchMemory seal key owner/mode/fingerprint mismatch"
    exit 1
  fi
  echo "PASS: ResearchMemory root seal key and public trust anchor match"
  exit 0
fi

for dir in "/Library/Application Support/ABCR-Bootstrap" "$PRIVATE_DIR" "$TRUST_DIR"; do
  [ ! -L "$dir" ] || { echo "BLOCKED: symlink directory: $dir" >&2; exit 1; }
done
/bin/mkdir -p "$PRIVATE_DIR" "$TRUST_DIR"
safe_dir "$PRIVATE_DIR"; safe_dir "$TRUST_DIR"

if [ ! -e "$PRIVATE_KEY" ]; then
  TMPD="$(/usr/bin/mktemp -d /tmp/abcr-research-seal.XXXXXX)"
  trap '/bin/rm -rf "$TMPD"' EXIT
  /bin/chmod 0700 "$TMPD"
  "$OPENSSL" genpkey -algorithm ED25519 -out "$TMPD/key.pem"
  safe_file "$TMPD/key.pem"
  /usr/sbin/chown root:wheel "$TMPD/key.pem"; /bin/chmod 0600 "$TMPD/key.pem"
  [ ! -e "$PRIVATE_KEY" ] && [ ! -L "$PRIVATE_KEY" ] \
    || { echo "BLOCKED: private key appeared during install" >&2; exit 1; }
  /bin/mv "$TMPD/key.pem" "$PRIVATE_KEY"
else
  safe_file "$PRIVATE_KEY"
fi
/usr/sbin/chown root:wheel "$PRIVATE_DIR" "$PRIVATE_KEY"
/bin/chmod 0700 "$PRIVATE_DIR"; /bin/chmod 0600 "$PRIVATE_KEY"

TMPD="$(/usr/bin/mktemp -d /tmp/abcr-research-pub.XXXXXX)"
trap '/bin/rm -rf "$TMPD"' EXIT
"$OPENSSL" pkey -in "$PRIVATE_KEY" -pubout -out "$TMPD/public.pem"
NEW_FPR="$(fingerprint_private)"
/usr/bin/printf '%s\n' "$NEW_FPR" > "$TMPD/fingerprint"
if [ -e "$PUBLIC_KEY" ] || [ -e "$FINGERPRINT" ] || [ -L "$PUBLIC_KEY" ] || [ -L "$FINGERPRINT" ]; then
  safe_file "$PUBLIC_KEY"; safe_file "$FINGERPRINT"
  /usr/bin/cmp -s "$TMPD/public.pem" "$PUBLIC_KEY" \
    && /usr/bin/cmp -s "$TMPD/fingerprint" "$FINGERPRINT" \
    || { echo "BLOCKED: existing ResearchMemory trust anchor conflicts with private key" >&2; exit 1; }
else
  /bin/chmod 0755 "$TRUST_DIR"
  /usr/bin/install -o root -g wheel -m 0444 "$TMPD/public.pem" "$PUBLIC_KEY"
  /usr/bin/install -o root -g wheel -m 0444 "$TMPD/fingerprint" "$FINGERPRINT"
fi
/usr/sbin/chown root:wheel "$TRUST_DIR" "$PUBLIC_KEY" "$FINGERPRINT"
/bin/chmod 0555 "$TRUST_DIR"; /bin/chmod 0444 "$PUBLIC_KEY" "$FINGERPRINT"
exec "$0" --check
