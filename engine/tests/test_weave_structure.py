"""
Weave-structure probe on synthetic fabrics drawn from real interlacement matrices.
Synthetic validation only — not real-world accuracy.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.config import get_config  # noqa: E402
from engine.fft_grade import run_fft_grade  # noqa: E402
from tools.synth_fabric import WovenSpec, make_woven  # noqa: E402

TOL = 0.02


def _run(**kw):
    kw.setdefault("gaussian_blur_sigma", 1.5)
    img, gt = make_woven(WovenSpec(**kw))
    res = run_fft_grade(img, gt.px_per_mm, get_config())
    assert res["ok"], res
    return res, gt


def _close(a, b, tol=TOL):
    return abs(a - b) / b <= tol


@pytest.mark.parametrize("epi,ppi,angle", [(60, 60, 0), (53.3, 88.9, 3), (80, 70, -5), (45, 100, 0)])
def test_plain_weave_counts_every_pick(epi, ppi, angle):
    """Staggered over/under picks are NOT halved: plain weave counts are direct."""
    res, gt = _run(weave="plain", ends_per_inch=epi, picks_per_inch=ppi, grid_angle_deg=angle)
    assert _close(res["ends_per_inch"], epi)
    assert _close(res["picks_per_inch"], ppi)
    assert res["weave"]["class"] == "plain"
    assert res["weave"]["row_shift_ends"] == 1
    assert res["weave"]["pick_count_ambiguous"] is False


def test_weft_rib_flags_ambiguous_true_count_first():
    res, _ = _run(weave="weft_rib22", ends_per_inch=53.3, picks_per_inch=46.0)
    w = res["weave"]
    assert w["class"] == "paired_ends" and w["row_shift_ends"] == 2
    assert w["pick_count_ambiguous"] is True
    assert _close(w["picks_candidates"][0], 46.0)
    assert _close(res["ends_per_inch"], 53.3)


@pytest.mark.parametrize("angle", [0, 4])
def test_matt_merged_picks_flags_ambiguous_true_count_second(angle):
    """2/2 matt with the two picks of a shed lying together: FFT sees half; flag it."""
    res, _ = _run(weave="matt22", ends_per_inch=53.3, picks_per_inch=88.9,
                  merge_paired_picks=True, grid_angle_deg=angle)
    w = res["weave"]
    assert w["class"] == "paired_ends"
    assert w["pick_count_ambiguous"] is True
    assert _close(w["picks_candidates"][1], 88.9)
    assert _close(res["picks_per_inch"], 88.9 / 2)  # default policy reports visible rows


def test_matt_policy_doubles_when_configured():
    cfg = get_config()
    cfg2 = {**cfg, "fft": {**cfg["fft"], "paired_ends_pick_policy": "matt"}}
    img, gt = make_woven(WovenSpec(weave="matt22", ends_per_inch=53.3, picks_per_inch=88.9,
                                   merge_paired_picks=True, gaussian_blur_sigma=1.5))
    res = run_fft_grade(img, gt.px_per_mm, cfg2)
    assert _close(res["picks_per_inch"], 88.9)
    assert res["weave"]["pick_count_ambiguous"] is False


def test_matt_with_visible_seam_counts_directly():
    res, _ = _run(weave="matt22", ends_per_inch=53.3, picks_per_inch=88.9)
    assert _close(res["picks_per_inch"], 88.9)
    assert res["weave"]["pick_count_ambiguous"] is False


def test_twill_detected_and_counted():
    res, _ = _run(weave="twill12", ends_per_inch=60, picks_per_inch=60)
    assert res["weave"]["class"] == "twill"
    assert _close(res["ends_per_inch"], 60) and _close(res["picks_per_inch"], 60)
    assert res["weave"]["pick_count_ambiguous"] is False


# ---------------------------------------------------------------------------
# Robustness: the detector must never raise a false ambiguity flag on a plain
# weave, and must never silently call a paired-end weave "plain".
# ---------------------------------------------------------------------------

import itertools  # noqa: E402


@pytest.mark.parametrize("weave,merged", [("plain", False), ("matt22", True)])
def test_no_class_crossover_across_conditions(weave, merged):
    """
    Sweep density / angle / blur / noise. Required invariants:
      - a plain weave is NEVER classified paired_ends (no false halving flag);
      - a paired weave is NEVER classified plain (never silently halved with
        false confidence) — it is either paired_ends or honestly 'unclear'.
    """
    dens = [(53.3, 88.9), (60, 60), (70, 55)]
    bad = []
    for (e, p), a, bl, sd in itertools.product(dens, (0, 10), (1.0, 2.0), (1, 7)):
        img, gt = make_woven(WovenSpec(
            weave=weave, ends_per_inch=e, picks_per_inch=p, merge_paired_picks=merged,
            grid_angle_deg=a, gaussian_blur_sigma=bl, noise_sigma=0.02, seed=sd))
        res = run_fft_grade(img, gt.px_per_mm, get_config())
        if not res["ok"]:
            continue
        cls = res["weave"]["class"]
        if weave == "plain" and cls == "paired_ends":
            bad.append((e, p, a, bl, sd, cls))
        if weave == "matt22" and cls == "plain":
            bad.append((e, p, a, bl, sd, cls))
    assert not bad, f"class crossover: {bad}"
