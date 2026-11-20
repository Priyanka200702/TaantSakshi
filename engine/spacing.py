"""
engine/spacing.py
How evenly the threads are spaced, measured directly in the rectified window.

For each direction the window is cut into strips; in each strip the image is
averaged along the threads into a 1-D profile, every thread row is located, and
the gap to the next row is measured. The spread of those gaps (robust CV:
1.4826 * MAD / median) is the reported variation.

Notes
- The value is the variation of centre-to-centre spacing. If every individual
  thread's width varies by s, centre spacing varies by about 0.71 * s.
- Below ~0.05 the result is at the pixel-noise floor: report it as "very even",
  not as a precise number.
- A direction is only 'reliable' when enough rows were found. In some weaves one
  set of threads is mostly hidden (e.g. warp under weft floats); then nothing is
  claimed for that direction.
- Evenness is a property of the cloth, not proof of hand weaving.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

CORE_LO, CORE_HI = 0.65, 1.5   # gaps outside this (in pitches) are missed/split rows
MIN_GAPS = 30
MIN_FOUND_FRACTION = 0.5


def measure_spacing(window: np.ndarray | None, px_per_thread: dict | None, strips: int = 6) -> dict[str, Any]:
    """Return {'warp': {...}, 'weft': {...}}; never raises."""
    empty = {"cv": None, "n": 0, "expected": 0, "reliable": False}
    out = {"warp": dict(empty), "weft": dict(empty), "method": "row_gaps_mad"}
    try:
        if window is None or not px_per_thread:
            return out
        g = window if window.ndim == 2 else cv2.cvtColor(window, cv2.COLOR_BGR2GRAY)
        g = g.astype(np.float64)
        p_warp = float(px_per_thread.get("warp") or 0)
        p_weft = float(px_per_thread.get("weft") or 0)
        if p_warp > 2:
            out["warp"] = _axis(g.T, p_warp, strips)   # warp threads run down: profile across columns
        if p_weft > 2:
            out["weft"] = _axis(g, p_weft, strips)     # weft rows run across: profile down rows
    except Exception:
        pass
    return out


def _axis(g: np.ndarray, pitch: float, strips: int) -> dict[str, Any]:
    flat = g - cv2.GaussianBlur(g, (0, 0), pitch * 2.0)   # remove slow shading
    n_rows, width = flat.shape
    gaps: list[float] = []
    for s in range(strips):
        band = flat[:, s * width // strips:(s + 1) * width // strips]
        prof = gaussian_filter1d(band.mean(axis=1), pitch * 0.18)
        spread = float(np.std(prof))
        if spread <= 1e-9:
            continue
        for sign in (1.0, -1.0):                            # bright and dark rows
            pk, _ = find_peaks(sign * prof, distance=max(2, int(pitch * 0.6)), prominence=spread * 0.3)
            pos = _subpixel(sign * prof, pk)
            gaps.extend((np.diff(pos) / pitch).tolist())

    expected = int(strips * 2 * max(n_rows / pitch - 1, 0))
    core = np.array([x for x in gaps if CORE_LO < x < CORE_HI], dtype=float)
    reliable = len(core) >= max(MIN_GAPS, MIN_FOUND_FRACTION * expected)
    cv = None
    if len(core) >= 10:
        med = float(np.median(core))
        cv = float(1.4826 * np.median(np.abs(core - med)) / med)
    return {"cv": cv, "n": int(len(core)), "expected": expected, "reliable": bool(reliable and cv is not None)}


def _subpixel(prof: np.ndarray, peaks: np.ndarray) -> np.ndarray:
    """Parabolic refinement of peak positions."""
    out = peaks.astype(float)
    for i, k in enumerate(peaks):
        if 0 < k < len(prof) - 1:
            a, b, c = prof[k - 1], prof[k], prof[k + 1]
            den = a - 2 * b + c
            if abs(den) > 1e-12:
                out[i] = k + 0.5 * (a - c) / den
    return out


def describe(cv: float | None) -> str | None:
    """Plain band for display."""
    if cv is None:
        return None
    if cv < 0.05:
        return "very_even"
    if cv < 0.10:
        return "slightly_varied"
    if cv < 0.15:
        return "varied"
    return "highly_varied"
