"""Run manifest writer — captures full provenance at run start/end."""

import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from .errors import AbcrError, E06_ARM_PURITY_VIOLATION
from .schema import canonical_json

# --- Arm purity: WHITELIST model (F-INT-05 / F-ARM-01) ---------------------
# Previously these two sets were used as a *blacklist*: only 7 literal top-level
# keys were checked, so any renamed key, nested dict, or free-text persona/vector
# reference bypassed the gate and the manifest reported has_persona_ref=false.
#
# We now enforce a whitelist per arm: the intervention spec may ONLY contain
# keys allowed for its declared method, all values must be scalar (no nested
# dict/list obfuscation), and any deviation is an E06 violation.
E06_VECTOR_KEYS = {"vector_dir", "vector_path", "match_to", "direction_seed", "target_norm"}
E06_PERSONA_KEYS = {"artifact", "instruction_index"}

# Descriptive labels allowed on any arm (benign metadata, carry no reference).
_COMMON_KEYS = {"method", "trait", "trait_pole"}

# Extra vector-arm tuning knobs that may legitimately appear in the spec.
_VECTOR_TUNING_KEYS = {"layer", "coefficient", "intervention_strength", "match_layer", "positions"}

# Per-method whitelist of allowed intervention-spec keys (in addition to _COMMON_KEYS).
_ARM_ALLOWED_KEYS: dict[str, set[str]] = {
    "none": set(),
    "prompt_persona": set(E06_PERSONA_KEYS),
    "residual_vector": E06_VECTOR_KEYS | _VECTOR_TUNING_KEYS,
    "random_direction": E06_VECTOR_KEYS | _VECTOR_TUNING_KEYS,
    "projection_ablation": E06_VECTOR_KEYS | _VECTOR_TUNING_KEYS,
}


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """temp -> fsync(file) -> atomic rename -> fsync(dir) (F-A-10 / L-20).

    A crash mid-write can never leave a truncated half-file in place; the old
    complete file survives until the rename flips atomically to the new one.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp), str(path))
        # fsync the directory so the rename itself is durable.
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(Path(path), text.encode("utf-8"))


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "UNKNOWN"


def _pip_freeze(run_dir: Path) -> str:
    lock_path = run_dir / "env.lock"
    sections: list[str] = []
    for venv in (".venv", ".venv-pv"):
        venv_python = Path(venv) / "bin" / "python"
        if not venv_python.exists():
            continue
        header = f"# --- {venv} ---"
        try:
            out = subprocess.check_output(
                ["uv", "pip", "freeze", "--python", str(venv_python)],
                text=True, stderr=subprocess.DEVNULL,
            )
            sections.append(f"{header}\n{out}")
        except Exception:
            try:
                out = subprocess.check_output(
                    [str(venv_python), "-m", "pip", "freeze"],
                    text=True, stderr=subprocess.DEVNULL,
                )
                sections.append(f"{header}\n{out}")
            except Exception:
                pass
    if sections:
        _atomic_write_text(lock_path, "\n".join(sections))
    else:
        _atomic_write_text(lock_path, "UNAVAILABLE")
    return "env.lock"


def _clean_ref(value: str) -> str:
    """Collapse a protocol_ref to a single clean line (F-OPS-15).

    A protocol_ref must be a single-line token (path@sha256:...); embedded
    newlines corrupt downstream single-line parsers. Returns the first
    non-empty line, or the UNAVAILABLE sentinel if none.
    """
    for ln in value.splitlines():
        ln = ln.strip()
        if ln:
            return ln
    return "UNAVAILABLE-see-DEVIATIONS"


def _protocol_ref() -> str:
    ref_path = Path("configs/protocol_ref.txt")
    if ref_path.exists():
        return _clean_ref(ref_path.read_text())
    doc_path = Path("/Users/superagent/shared-brain/L2-project/docs/1Personality-Experiment-Final/ABCR-W1执行方案-V1.0.md")
    try:
        content = doc_path.read_bytes()
        h = hashlib.sha256(content).hexdigest()
        ref = f"docs/1Personality-Experiment-Final/ABCR-W1执行方案-V1.0.md@sha256:{h}"
        _atomic_write_text(ref_path, ref)
        return _clean_ref(ref)
    except Exception:
        ref = "UNAVAILABLE-see-DEVIATIONS"
        _atomic_write_text(ref_path, ref)
        return ref


def _arm_purity(spec: dict) -> dict[str, Any]:
    """Whitelist-based arm purity check (F-INT-05 / F-ARM-01).

    Fail-closed: any intervention spec whose keys fall outside the whitelist for
    its declared method — including renamed keys, nested dicts/lists, or
    free-text persona/vector references smuggled under a new key — raises
    E06_ARM_PURITY_VIOLATION rather than being silently reported as pure.

    The returned has_vector_ref / has_persona_ref are only ever emitted for a
    spec that passed the gate, so the manifest can no longer lie: a written
    manifest's purity flags always reflect the (verified-clean) arm.
    """
    if not isinstance(spec, dict):
        raise AbcrError(E06_ARM_PURITY_VIOLATION,
                        f"intervention spec must be a dict, got {type(spec).__name__}")

    method = spec.get("method", "none")
    if method not in _ARM_ALLOWED_KEYS:
        raise AbcrError(E06_ARM_PURITY_VIOLATION,
                        f"unknown intervention method: {method!r}")

    allowed = _COMMON_KEYS | _ARM_ALLOWED_KEYS[method]

    # (1) No nested structure: every value must be a scalar. A dict/list value is
    #     an obfuscation vector (e.g. persona_config={artifact:...}) regardless of
    #     the outer key name.
    for k, v in spec.items():
        if isinstance(v, (dict, list)):
            raise AbcrError(
                E06_ARM_PURITY_VIOLATION,
                f"method={method}: nested structure not allowed in intervention "
                f"spec (key {k!r} has {type(v).__name__} value)",
            )

    # (2) Whitelist: any key outside the allowed set for this arm is a violation.
    #     This catches renamed vector keys, persona keys on the wrong arm, and
    #     arbitrary free-text keys (system_text, persona, ...).
    extra_keys = set(spec.keys()) - allowed
    if extra_keys:
        raise AbcrError(
            E06_ARM_PURITY_VIOLATION,
            f"method={method}: disallowed intervention key(s) {sorted(extra_keys)} "
            f"(allowed: {sorted(allowed)})",
        )

    # (3) Cross-arm reference belt-and-suspenders. With the whitelist above these
    #     can only be true on the arm that legitimately owns them.
    has_vector_ref = bool((E06_VECTOR_KEYS | _VECTOR_TUNING_KEYS) & set(spec.keys()))
    has_persona_ref = bool(E06_PERSONA_KEYS & set(spec.keys()))
    if has_persona_ref and method != "prompt_persona":
        raise AbcrError(E06_ARM_PURITY_VIOLATION,
                        f"method={method} carries persona reference keys")
    if has_vector_ref and method not in ("residual_vector", "random_direction", "projection_ablation"):
        raise AbcrError(E06_ARM_PURITY_VIOLATION,
                        f"method={method} carries vector reference keys")

    return {
        "declared_method": method,
        "has_vector_ref": has_vector_ref,
        "has_persona_ref": has_persona_ref,
        "purity_checked": "whitelist",
    }


def write_manifest(
    run_dir: Path,
    config: dict[str, Any],
    extra: dict[str, Any],
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    config_json = canonical_json(config)
    config_hash = hashlib.sha256(config_json.encode()).hexdigest()

    env_lock_ref = _pip_freeze(run_dir)

    manifest = {
        "run_id": extra["run_id"],
        "config": config,
        "config_hash": config_hash,
        "git_commit": _git_commit(),
        "model": {
            "key": config.get("model_key", ""),
            "id": extra.get("model_id", ""),
            "revision": extra.get("model_revision", ""),
            "dtype": extra.get("dtype", ""),
            "device_backend": extra.get("device_backend", ""),
        },
        "chat_template_hash": extra.get("chat_template_hash", ""),
        "split_hash": extra.get("split_hash", ""),
        "arm_purity": _arm_purity(config.get("intervention", {})),
        "env_lock_ref": env_lock_ref,
        "protocol_ref": _protocol_ref(),
        "started_at": extra.get("started_at", ""),
        "finished_at": None,
        "n_steps_expected": extra.get("n_steps_expected", 0),
        "n_steps_written": 0,
        "repair_events": [],
        "citable": extra.get("citable", False),
    }

    manifest_path = run_dir / "manifest.json"
    _atomic_write_text(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False))

    config_copy = run_dir / "config.yaml"
    if not config_copy.exists():
        import yaml
        _atomic_write_text(config_copy, yaml.safe_dump(config, allow_unicode=True, sort_keys=False))

    return manifest


def finalize_manifest(
    run_dir: Path,
    n_steps_written: int,
    repair_events: list[dict] | None = None,
    resource_events: list[dict] | None = None,
) -> None:
    run_dir = Path(run_dir)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest["n_steps_written"] = n_steps_written
    if repair_events:
        manifest["repair_events"].extend(repair_events)
    if resource_events:
        manifest.setdefault("resource_events", []).extend(resource_events)
    _atomic_write_text(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False))
