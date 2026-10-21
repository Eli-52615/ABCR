#!/bin/bash
# Generate finite service signing identities. This provisions keys only; it does
# not write a seal, activate a release, load launchd, or start a service.
set -euo pipefail

AUTHORITY_SHA=40fd5fb21ff33d7da84648562c6dc12d68f15444dfea60379132af820510d0d1
OPENSSL=/opt/homebrew/opt/openssl@3/bin/openssl
BOOTSTRAP="/Library/Application Support/ABCR-Bootstrap"
TRUST="/Library/Application Support/ABCR-Trust"
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
  echo "BLOCKED: service key installation must run as root" >&2
  exit 77
fi
if [ ! -x "$OPENSSL" ] || ! "$OPENSSL" version | /usr/bin/grep -q '^OpenSSL 3\.'; then
  echo "BLOCKED: reviewed OpenSSL 3 runtime is unavailable" >&2
  exit 1
fi

KEY_ROWS=(
  "itempool|abcr-itempool|sealer.pem|dev-bundle-sealer.pub"
  "auditor|abcr-auditor|attestation.pem|auditor-attestation.pub"
  "approval-validator|abcr-auditor|attestation.pem|approval-validator.pub"
  "test-controller|root|attestation.pem|test-controller-attestation.pub"
  "verifier|abcr-verifier|attestation.pem|verifier-attestation.pub"
  "artifact-receipt|abcr-operator|private.pem|artifact-receipt.pub"
)

safe_regular() {
  [ ! -L "$1" ] && [ "$(/usr/bin/stat -f '%HT' "$1" 2>/dev/null || true)" = "Regular File" ] \
    && [ "$(/usr/bin/stat -f '%l' "$1")" = 1 ]
}

check_pair() {
  local keydir="$1" owner="$2" private="$3" public="$4" expected_owner="$owner"
  [ "$owner" = root ] && expected_owner=root
  safe_regular "$private" && safe_regular "$public" \
    || { echo "BLOCKED: signing pair missing/unsafe: $keydir"; return 1; }
  [ "$(/usr/bin/stat -f '%Su:%Lp' "$private")" = "$expected_owner:600" ] \
    && [ "$(/usr/bin/stat -f '%Su:%Sg:%Lp' "$public")" = "root:wheel:444" ] \
    || { echo "BLOCKED: signing pair owner/mode mismatch: $keydir"; return 1; }
  local left right
  left="$($OPENSSL pkey -in "$private" -pubout -outform DER 2>/dev/null | $OPENSSL dgst -sha256 | /usr/bin/awk '{print $NF}')"
  right="$($OPENSSL pkey -pubin -in "$public" -pubout -outform DER 2>/dev/null | $OPENSSL dgst -sha256 | /usr/bin/awk '{print $NF}')"
  [ -n "$left" ] && [ "$left" = "$right" ] \
    || { echo "BLOCKED: signing pair fingerprint mismatch: $keydir"; return 1; }
  echo "PASS: $keydir signing identity"
}

FAIL=0
for row in "${KEY_ROWS[@]}"; do
  IFS='|' read -r name owner private_name public_name <<<"$row"
  keydir="$BOOTSTRAP/keys/$name"
  [ "$name" = artifact-receipt ] && keydir="$BOOTSTRAP/artifact-receipt"
  check_pair "$name" "$owner" "$keydir/$private_name" "$TRUST/$public_name" \
    || FAIL=$((FAIL + 1))
done
if [ "$MODE" = check ]; then
  [ "$FAIL" -eq 0 ] || { echo "service_signing_keys: $FAIL BLOCKED"; exit 1; }
  echo "service_signing_keys: all PASS"
  exit 0
fi

[ ! -L "$BOOTSTRAP" ] && [ ! -L "$TRUST" ] \
  || { echo "BLOCKED: symlink bootstrap/trust root" >&2; exit 1; }
/bin/mkdir -p "$BOOTSTRAP/keys" "$TRUST"
/usr/sbin/chown root:wheel "$BOOTSTRAP/keys" "$TRUST"
/bin/chmod 0700 "$BOOTSTRAP/keys"
/bin/chmod 0755 "$TRUST"

for row in "${KEY_ROWS[@]}"; do
  IFS='|' read -r name owner private_name public_name <<<"$row"
  keydir="$BOOTSTRAP/keys/$name"
  [ "$name" = artifact-receipt ] && keydir="$BOOTSTRAP/artifact-receipt"
  private="$keydir/$private_name"
  public="$TRUST/$public_name"
  if [ ! -e "$private" ]; then
    [ ! -L "$private" ] || { echo "BLOCKED: private key symlink: $name" >&2; exit 1; }
    /bin/mkdir -p "$keydir"
    /usr/sbin/chown "$owner:$owner" "$keydir" 2>/dev/null \
      || /usr/sbin/chown "$owner:wheel" "$keydir"
    /bin/chmod 0700 "$keydir"
    tmp="$(/usr/bin/mktemp /tmp/abcr-service-key.XXXXXX)"
    safe_regular "$tmp" || { echo "BLOCKED: unsafe temporary key file" >&2; exit 1; }
    "$OPENSSL" genpkey -algorithm ED25519 -out "$tmp"
    /usr/sbin/chown "$owner:$owner" "$tmp" 2>/dev/null \
      || /usr/sbin/chown "$owner:wheel" "$tmp"
    /bin/chmod 0600 "$tmp"
    [ ! -e "$private" ] && [ ! -L "$private" ] \
      || { /bin/rm "$tmp"; echo "BLOCKED: private key appeared: $name" >&2; exit 1; }
    /bin/mv "$tmp" "$private"
  fi
  safe_regular "$private" || { echo "BLOCKED: unsafe private key: $name" >&2; exit 1; }
  pubtmp="$(/usr/bin/mktemp /tmp/abcr-service-pub.XXXXXX)"
  "$OPENSSL" pkey -in "$private" -pubout -out "$pubtmp"
  if [ -e "$public" ] || [ -L "$public" ]; then
    safe_regular "$public" && /usr/bin/cmp -s "$pubtmp" "$public" \
      || { /bin/rm "$pubtmp"; echo "BLOCKED: public key conflicts: $name" >&2; exit 1; }
    /bin/rm "$pubtmp"
  else
    /usr/sbin/chown root:wheel "$pubtmp"; /bin/chmod 0444 "$pubtmp"
    /bin/mv "$pubtmp" "$public"
  fi
done
/usr/sbin/chown root:wheel "$TRUST"; /bin/chmod 0555 "$TRUST"
exec "$0" --check
