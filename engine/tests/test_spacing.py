"""Thread-spacing evenness (engine/spacing.py). Synthetic checks + the real red saree."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.spacing import describe, measure_spacing  # noqa: E402
from tools.synth_fabric import WovenSpec, make_woven  # noqa: E402

PX_MM = 40.0


def _pitch(tpi):
    return PX_MM * 25.4 / tpi


def _jitter_rows(img, pitch_px, sigma, seed):
    """Give every pick its own width: pitch * (1 + N(0, sigma))."""
    rng = np.random.default_rng(seed)
    n_px = img.shape[0]
    n = int(n_px / pitch_px) + 4
    w = pitch_px * np.clip(1 + rng.normal(0, sigma, n), 0.4, 1.8)
    edges_out = np.concatenate([[0], np.cumsum(w)])
    edges_in = np.arange(n + 1) * pitch_px
    src = np.interp(np.arange(n_px, dtype=np.float32), edges_out, edges_in).astype(np.float32)
    mx = np.tile(np.arange(n_px, dtype=np.float32), (n_px, 1))
    my = np.tile(src[:, None], (1, n_px))
    return cv2.remap(img, mx, my, cv2.INTER_LINEAR)


def _u8(img):
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)


@pytest.mark.parametrize("weave,merged", [("plain", False), ("matt22", True), ("twill12", False)])
def test_even_cloth_reads_very_even(weave, merged):
    img, _ = make_woven(WovenSpec(weave=weave, ends_per_inch=55, picks_per_inch=90,
                                  merge_paired_picks=merged, gaussian_blur_sigma=1.5, noise_sigma=0.03))
    rows = 45 if merged else 90
    m = measure_spacing(_u8(img), {"warp": _pitch(55), "weft": _pitch(rows)})
    for axis in ("warp", "weft"):
        assert m[axis]["reliable"], m
        assert m[axis]["cv"] < 0.05, m
        assert describe(m[axis]["cv"]) == "very_even"


@pytest.mark.parametrize("sigma", [0.06, 0.10, 0.15, 0.20])
def test_uneven_weft_is_measured(sigma):
    """Centre spacing varies ~0.71*sigma; allow 20% relative error. Warp stays even."""
    expect = 0.707 * sigma
    vals = []
    for seed in range(3):
        img, _ = make_woven(WovenSpec(weave="plain", ends_per_inch=55, picks_per_inch=60,
                                      gaussian_blur_sigma=1.5, noise_sigma=0.03, seed=seed))
        img = _jitter_rows(img, _pitch(60), sigma, seed)
        m = measure_spacing(_u8(img), {"warp": _pitch(55), "weft": _pitch(60)})
        assert m["weft"]["reliable"] and m["warp"]["reliable"]
        assert m["warp"]["cv"] < 0.03
        vals.append(m["weft"]["cv"])
    assert abs(np.mean(vals) - expect) <= 0.2 * expect, (sigma, vals)


def test_missing_inputs_never_raise():
    assert measure_spacing(None, None)["weft"]["reliable"] is False
    assert measure_spacing(np.zeros((50, 50), np.uint8), {"warp": 10, "weft": 10})["weft"]["reliable"] is False


def test_red_saree_weft_uneven_warp_not_claimed():
    """Real red saree: weft rows clearly vary; warp is mostly hidden under weft floats."""
    photo = _ROOT / "data" / "samples" / "real" / "20261116_130240.jpeg"
    if not photo.exists():
        pytest.skip("real photo not present")
    from engine._analyze import analyze
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        res = analyze([str(photo)], out_dir=d)
    sp = res["spacing"]
    assert sp["weft"]["reliable"], sp
    assert 0.10 <= sp["weft"]["cv"] <= 0.30, sp
    assert sp["warp"]["reliable"] is False, sp
