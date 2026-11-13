"""
engine/compat.py
Thin wrappers matching the backend stub signatures (§6.3).
Backend can switch from stub to real engine by changing one import line.

Stub signatures (simplified from §6.3):
    def grade(path)       -> {"epi", "ppi", "irregularity", "defects", "grade", "ok"}
    def fingerprint(path) -> path to a fingerprint file
    def match(a, b)       -> {"score", "inliers", "match"}

These are implemented on top of analyze() / make_fingerprint() / match().
When the backend teammate shares their real stub, adjust these wrappers to match exactly.
"""
from __future__ import annotations

import tempfile
from pathlib import Path


def grade(path: str) -> dict:
    """
    Compat wrapper: analyze a single image for thread density and grade.
    Returns the minimal dict the backend stub exposes.
    """
    # Import here to avoid circular imports during package bootstrap
    from engine._analyze import analyze

    with tempfile.TemporaryDirectory() as tmp:
        result = analyze([path], out_dir=tmp, debug_dir=None)

    return {
        "ok": result.get("ok", False),
        "epi": result.get("ends_per_inch"),
        "ppi": result.get("picks_per_inch"),
        "irregularity": result.get("irregularity"),
        "defects": result.get("defects"),
        "grade": result.get("grade"),
        # Pass through code and reason so the backend can surface them
        "code": result.get("code"),
        "reason": result.get("reason"),
    }


def fingerprint(path: str) -> str | None:
    """
    Compat wrapper: extract a fingerprint for a single image.
    Returns the path to the residual .npz file (or None on failure).
    """
    from engine._analyze import make_fingerprint

    out_dir = Path(path).parent / "fingerprints"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = make_fingerprint([path], out_dir=str(out_dir))

    if not result.get("ok"):
        return None
    fp = result.get("fingerprint", {})
    return fp.get("residual_path")


def match(a: str | dict, b: str | dict) -> dict:
    """
    Compat wrapper: compare two fingerprints.
    Accepts either a file path (str) or the fingerprint dict from make_fingerprint().
    Returns {"score", "inliers", "match"}.
    """
    from engine._analyze import match as _match

    # Normalise: if strings are passed, wrap into the dict the engine expects
    def _as_fp_dict(x: str | dict) -> dict:
        if isinstance(x, str):
            return {"residual_path": x, "sift_path": None}
        return x

    result = _match(_as_fp_dict(a), _as_fp_dict(b))
    return {
        "ok": result.get("ok", False),
        "code": result.get("code", "OK" if result.get("ok") else "UNKNOWN"),
        "reason": result.get("reason", ""),
        "match": result.get("match"),
        "score": result.get("score"),
        "score_residual": result.get("score_residual"),
        "inliers": result.get("inliers"),
        # Extra context kept for debugging
        "calibrated": result.get("calibrated", False),
        "method": result.get("method"),
        "details": result.get("details"),
    }

