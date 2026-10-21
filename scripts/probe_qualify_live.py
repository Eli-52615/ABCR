#!/usr/bin/env python
"""Strict ABCR local probe LIVE qualification (2 personas + vanilla x 20 dev).

The ``--personas`` file has this exact shape::

    {"schema_version": 1, "personas": [
      {"persona_ref": "qual-a@v1", "persona_text": "..."},
      {"persona_ref": "qual-b@v1", "persona_text": "..."}
    ]}

The command refuses non-20-item bundles and never downloads or switches a model.
Its PASS is scoped to the local frozen model/DevBundle/SLO only; the JSON keeps the
deployed Feishu/queue E2E layer BLOCKED until that separate path is exercised.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from abcr.probe.qualification import (  # noqa: E402
    QualificationConfig,
    QualificationError,
    live_engine,
    load_persona_config,
    qualify_local_probe,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Qualify frozen local probe: exactly 2 personas + vanilla x 20 dev")
    parser.add_argument("--profile", default=str(
        REPO / "configs/probe/profiles/qwen25-7b-q4-v1.json"))
    parser.add_argument("--dev-bundle-root", required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--bundle-sealer-public-key", required=True)
    parser.add_argument(
        "--bundle-authority", required=True,
        choices=("production_itempool", "qualification_fixture"),
        help="explicit DevBundle trust class; fixture never proves production itempool E2E")
    parser.add_argument("--personas", required=True,
                        help="exact-shape JSON file containing exactly two personas")
    parser.add_argument("--predict", required=True,
                        help="required one-line prediction; empty/multiline is rejected")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--max-output-tokens", type=int, default=256)
    parser.add_argument("--with-3l", action="store_true",
                        help="request full persona+own-③L arms; requires --length-controls")
    parser.add_argument("--length-controls",
                        help="precompiled exact-shape ③L JSON array; never generated here")
    parser.add_argument("--lab-root", required=True)
    parser.add_argument("--evidence", required=True,
                        help="new JSON path; existing evidence is never overwritten")
    args = parser.parse_args(argv)

    try:
        personas = load_persona_config(Path(args.personas))
        if args.with_3l != bool(args.length_controls):
            raise QualificationError("--with-3l requires --length-controls and vice versa")
        length_controls = ()
        if args.length_controls:
            raw_controls = json.loads(Path(args.length_controls).read_text(encoding="utf-8"))
            if not isinstance(raw_controls, list):
                raise QualificationError("length-controls file must contain a JSON array")
            length_controls = tuple(raw_controls)
        config = QualificationConfig(
            profile_path=Path(args.profile),
            trusted_dev_bundle_root=Path(args.dev_bundle_root),
            bundle_id=args.bundle_id,
            bundle_sealer_public_key=Path(args.bundle_sealer_public_key),
            lab_root=Path(args.lab_root),
            evidence_path=Path(args.evidence),
            personas=personas,
            prediction=args.predict,
            seed=args.seed,
            max_output_tokens=args.max_output_tokens,
            bundle_authority=args.bundle_authority,
            with_length_control=args.with_3l,
            length_controls=length_controls,
        )
        result = qualify_local_probe(
            config, engine=live_engine(config.profile_path), mode="live")
    except Exception as exc:
        print(json.dumps({"scope_status": "BLOCKED", "error_type": type(exc).__name__,
                          "reason": str(exc)[:1000]}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({
        "scope_status": result["scope_status"],
        "elapsed_seconds": result["elapsed_seconds"],
        "evidence": str(config.evidence_path),
        "evidence_sha256": result["evidence_sha256"],
        "deployment_e2e": result["deployment_e2e"]["status"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result["scope_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
