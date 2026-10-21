#!/bin/zsh
# Validate the frozen ACL contract.  Live mutation is intentionally owned by the
# reviewed bootstrap installer; this helper never turns a source checkout into a
# privileged installer by accident.
set -euo pipefail

case "${1:-}" in
  --check) MODE=contract ;;
  --check-live) MODE=live ;;
  --install)
    print -u2 "REFUSED: ACL mutation requires the reviewed root bootstrap installer and a sealed release."
    exit 64
    ;;
  *)
    print -u2 "usage: $0 --check | --check-live | --install"
    exit 64
    ;;
esac

SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h:h}"
export ABCR_ACL_INSTALL_MANIFEST="$SCRIPT_DIR/acl-manifest-v1.json"
export ABCR_ACL_REPO_ROOT="$REPO_ROOT"
export ABCR_ACL_CHECK_MODE="$MODE"

python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import pwd
import stat
import subprocess
import sys
from pathlib import Path

repo = Path(os.environ["ABCR_ACL_REPO_ROOT"])
install_manifest_path = Path(os.environ["ABCR_ACL_INSTALL_MANIFEST"])
mode = os.environ["ABCR_ACL_CHECK_MODE"]


def load_unique(path: Path) -> dict:
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"duplicate JSON key in {path}: {key}")
            out[key] = value
        return out

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError(f"manifest is not an object: {path}")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


manifest = load_unique(install_manifest_path)
if set(manifest) != {
    "schema_version", "authority_sha256", "contracts", "install_mode",
    "live_probes_required", "negative_probes",
} or manifest["schema_version"] != 2:
    raise SystemExit("BLOCKED: invalid ACL installation manifest shape/version")
if manifest["authority_sha256"] != "40fd5fb21ff33d7da84648562c6dc12d68f15444dfea60379132af820510d0d1":
    raise SystemExit("BLOCKED: authority SHA drift")

contracts = manifest["contracts"]
if set(contracts) != {"path_ownership", "acl", "work_stages"}:
    raise SystemExit("BLOCKED: incomplete ACL contract set")
loaded = {}
for name, entry in contracts.items():
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
        raise SystemExit(f"BLOCKED: invalid contract entry: {name}")
    rel = Path(entry["path"])
    if rel.is_absolute() or ".." in rel.parts:
        raise SystemExit(f"BLOCKED: unsafe contract path: {name}")
    path = repo / rel
    if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
        raise SystemExit(f"BLOCKED: unsafe/missing contract file: {name}")
    if "sha256" in entry and digest(path) != entry["sha256"]:
        raise SystemExit(f"BLOCKED: contract hash drift: {name}")
    loaded[name] = load_unique(path)

ownership = loaded["path_ownership"]
acl = loaded["acl"]
stages = loaded["work_stages"]
if ownership.get("authority_sha256") != manifest["authority_sha256"]:
    raise SystemExit("BLOCKED: path ownership is not bound to authority")
if acl.get("authority_sha256") != manifest["authority_sha256"]:
    raise SystemExit("BLOCKED: ACL policy is not bound to authority")
if set(stages.get("states", [])) != {
    "ready", "inflight", "results", "acks", "quarantine", "archive"
}:
    raise SystemExit("BLOCKED: work stage state registry is incomplete")
principals = ownership.get("principals")
roots = ownership.get("roots")
if not isinstance(principals, list) or len(principals) != len(set(principals)):
    raise SystemExit("BLOCKED: principal registry is invalid")
if not isinstance(roots, list) or not roots:
    raise SystemExit("BLOCKED: ownership root registry is empty")
paths = [item.get("path") for item in roots if isinstance(item, dict)]
if len(paths) != len(roots) or len(paths) != len(set(paths)):
    raise SystemExit("BLOCKED: ownership root paths are invalid or duplicated")
print("PASS: frozen ACL/path/work-stage contracts are structurally valid and hash-bound")

if mode == "contract":
    print("BLOCKED: live per-UID ACL probes were not requested; CODE_RC check made no system changes")
    raise SystemExit(0)

if os.geteuid() != 0:
    raise SystemExit("BLOCKED: --check-live must run as root so deny probes are authoritative")

missing = []
for name in principals:
    try:
        pwd.getpwnam(name)
    except KeyError:
        missing.append(name)
if missing:
    raise SystemExit("BLOCKED: missing OS principals: " + ",".join(missing))

failures = []
for item in roots:
    path = Path(item["path"])
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        failures.append(f"missing root: {path}")
        continue
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        failures.append(f"unsafe root type: {path}")
        continue
    expected_mode = item.get("directory_mode")
    if expected_mode and stat.S_IMODE(info.st_mode) != int(expected_mode, 8):
        failures.append(f"root mode drift: {path}")

if failures:
    print("BLOCKED: live ownership roots are not fully installed:")
    for failure in failures:
        print("  - " + failure)
    raise SystemExit(1)
print("PASS: all declared principals and ownership roots exist with declared base modes")
dataset_validator = repo / "scripts/import_abcr_dataset.py"
try:
    result = subprocess.run(
        [sys.executable, "-I", str(dataset_validator), "--check-live"],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=120,
    )
except (OSError, subprocess.SubprocessError) as exc:
    raise SystemExit("BLOCKED: dataset per-UID live validator could not run") from exc
if result.stdout:
    print(result.stdout.rstrip())
if result.returncode != 0:
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    raise SystemExit("BLOCKED: dataset positive/negative per-UID live probes failed")
print("PASS: root-downgraded dataset open/list/read identity matrix is exact")
print("BLOCKED: non-dataset destructive/create/rename probes remain installer-owned")
raise SystemExit(1)
PY
