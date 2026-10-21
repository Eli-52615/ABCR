#!/bin/zsh
set -euo pipefail
if [[ "${1:-}" != "--check" ]]; then
  print -u2 "Refusing mutation in CODE_RC; production installer requires explicit reviewed wrapper."
  exit 64
fi
SCRIPT_DIR="${0:A:h}"
ABCR_ACL_MANIFEST="$SCRIPT_DIR/acl-manifest-v1.json" python3 - <<'PY'
import json
import os
from pathlib import Path
p=Path(os.environ['ABCR_ACL_MANIFEST'])
d=json.loads(p.read_text())
assert d['schema_version']==1 and d['roots'] and d['negative_probes']
print('ACL manifest structurally valid; live per-UID probes remain BLOCKED until installation')
PY
