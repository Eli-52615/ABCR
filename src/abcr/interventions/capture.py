"""Projection capture utility (Package B).

Read-only hook that records per-token projection scalars (h . d_hat)
onto the injected direction. Used by residual_vector and random_direction
when capture_path is set.

This module provides the finalize utility for saving captures; the actual
per-token recording is integrated into each intervention's hook.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import numpy as np


def finalize(path: str, projections: list[float], meta: dict) -> dict:
    arr = np.array(projections, dtype=np.float32)
    np.savez(path, proj=arr, meta=np.array([json.dumps(meta)]))
    return {
        "path": path,
        "layer": meta.get("layer"),
        "proj_mean": float(np.mean(arr)),
        "proj_p50": float(np.median(arr)),
        "proj_p90": float(np.percentile(arr, 90)),
    }


def load_capture(path: str) -> dict:
    data = np.load(path, allow_pickle=False)
    proj = data["proj"]
    meta_raw = data["meta"]
    meta = json.loads(str(meta_raw[0]))
    return {
        "proj": proj,
        "meta": meta,
        "summary": {
            "path": path,
            "layer": meta.get("layer"),
            "proj_mean": float(np.mean(proj)),
            "proj_p50": float(np.median(proj)),
            "proj_p90": float(np.percentile(proj, 90)),
        },
    }
