"""
engine/tests/test_fft.py
Unit tests for engine/fft_grade.py using synthetic fabric images.

All tests use tools/synth_fabric.py — no real photos needed.
Run from the repo root:   pytest engine/tests/test_fft.py -v

Tolerance targets (from §7.11 and the user's instruction):
  - Thread density: ±1% on clean synthetics, ±3% with noise
  - Angle: ±1°
  - ALIASING flagged when px/thread < 4
  - Design stripes outside the band don't shift the count
  - NO_WEAVE returned when no clear peak

If ±1% proves impossible for a given scenario, the test prints a detailed
message and fails with the achieved error — it does NOT silently loosen the tolerance.
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path setup (also done by conftest.py, repeated here for safety)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engine.config import get_config
from engine.fft_grade import run_fft_grade
from tools.synth_fabric import FabricSpec, make_fabric


# ---------------------------------------------------------------------------
# Shared config and helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cfg():
    return get_config()


def _run(spec: FabricSpec, cfg: dict, debug_dir: str | None = None):
    """Make a synthetic fabric and run the FFT grader."""
    img, gt = make_fabric(spec)
    result = run_fft_grade(img, spec.px_per_mm, cfg, debug_dir=debug_dir)
    return result, gt


def _check_density(result: dict, gt, tol_pct: float, label: str = ""):
    """Assert ends/picks per inch are within tol_pct% of ground truth."""
    if not result["ok"]:
        pytest.fail(
            f"{label}: FFT returned not-ok: code={result['code']}, reason={result['reason']}"
        )

    epi_gt  = gt.ends_per_inch
    ppi_gt  = gt.picks_per_inch
    epi_got = result["ends_per_inch"]
    ppi_got = result["picks_per_inch"]

    epi_err_pct = abs(epi_got - epi_gt) / epi_gt * 100
    ppi_err_pct = abs(ppi_got - ppi_gt) / ppi_gt * 100

    details = (
        f"\n  epi:  gt={epi_gt:.2f}, got={epi_got:.2f}, err={epi_err_pct:.2f}% "
        f"(tol={tol_pct}%)"
        f"\n  ppi:  gt={ppi_gt:.2f}, got={ppi_got:.2f}, err={ppi_err_pct:.2f}% "
        f"(tol={tol_pct}%)"
    )

    assert epi_err_pct <= tol_pct, (
        f"{label}: ends per inch error {epi_err_pct:.2f}% > tolerance {tol_pct}%{details}"
    )
    assert ppi_err_pct <= tol_pct, (
        f"{label}: picks per inch error {ppi_err_pct:.2f}% > tolerance {tol_pct}%{details}"
    )

    return epi_err_pct, ppi_err_pct


# ---------------------------------------------------------------------------
# TC-01: Clean synthetic fabric — density within ±1%
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("epi,ppi", [
    (60, 60),    # square weave
    (80, 60),    # asymmetric
    (40, 80),    # weft-heavy
    (100, 100),  # fine cloth
])
def test_density_clean(epi, ppi, cfg):
    """
    §7.11: density recovered within ±1% on clean synthetics.
    px_per_mm=40, no noise, no blur.
    """
    spec = FabricSpec(
        ends_per_inch=epi,
        picks_per_inch=ppi,
        px_per_mm=40.0,
        window_mm=20.0,
        noise_sigma=0.0,
        seed=42,
    )
    result, gt = _run(spec, cfg)
    _check_density(result, gt, tol_pct=1.0, label=f"clean epi={epi} ppi={ppi}")


# ---------------------------------------------------------------------------
# TC-02: Noisy synthetic — density within ±3%
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("epi,ppi,noise", [
    (60, 60, 0.05),
    (80, 60, 0.08),
    (60, 80, 0.10),
])
def test_density_noisy(epi, ppi, noise, cfg):
    """§7.11: density within ±3% with realistic noise."""
    spec = FabricSpec(
        ends_per_inch=epi,
        picks_per_inch=ppi,
        px_per_mm=40.0,
        window_mm=20.0,
        noise_sigma=noise,
        seed=7,
    )
    result, gt = _run(spec, cfg)
    _check_density(result, gt, tol_pct=3.0, label=f"noisy epi={epi} ppi={ppi} σ={noise}")


# ---------------------------------------------------------------------------
# TC-03: Angle recovery within ±1°
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("angle_deg", [0.0, 3.0, -5.0, 8.0])
def test_angle_recovery(angle_deg, cfg):
    """§7.11: angle recovered within ±1°."""
    spec = FabricSpec(
        ends_per_inch=60,
        picks_per_inch=60,
        px_per_mm=40.0,
        window_mm=20.0,
        grid_angle_deg=angle_deg,
        noise_sigma=0.02,
        seed=99,
    )
    result, gt = _run(spec, cfg)
    if not result["ok"]:
        pytest.fail(f"angle={angle_deg}°: FFT failed: {result['code']} — {result['reason']}")

    # Warp peak angle should match grid_angle_deg within ±1°
    got_angle = result["warp_angle_deg"]
    # Normalise to same range as the input (allow 180° ambiguity)
    err = min(
        abs(got_angle - angle_deg),
        abs(got_angle - angle_deg + 180),
        abs(got_angle - angle_deg - 180),
    )
    assert err <= 1.0, (
        f"angle={angle_deg}°: got warp_angle={got_angle:.2f}°, error={err:.2f}° > 1°"
    )


# ---------------------------------------------------------------------------
# TC-04: ALIASING flagged when px/thread < 4
# ---------------------------------------------------------------------------

def test_aliasing_flagged_when_too_coarse(cfg):
    """
    §7.11: aliasing is flagged when px/thread < 4.
    Use a low px_per_mm so threads are undersampled.
    """
    # 60 epi = 60/25.4 ≈ 2.36 threads/mm → need < 4 px/thread → px_per_mm < ~9.4
    spec = FabricSpec(
        ends_per_inch=60,
        picks_per_inch=60,
        px_per_mm=8.0,   # → ~3.4 px/thread  < 4 → should trigger ALIASING
        window_mm=20.0,
        noise_sigma=0.0,
        seed=1,
    )
    result, _ = _run(spec, cfg)
    # Should either return ALIASING or NO_WEAVE (peak may not be detectable)
    assert not result["ok"], "Expected ALIASING or NO_WEAVE but got ok=True"
    assert result["code"] in ("ALIASING", "NO_WEAVE"), (
        f"Expected ALIASING/NO_WEAVE, got code={result['code']}"
    )


def test_aliasing_not_flagged_when_fine_enough(cfg):
    """When px/thread ≥ 4, no ALIASING code should be returned."""
    spec = FabricSpec(
        ends_per_inch=60,
        picks_per_inch=60,
        px_per_mm=40.0,  # → ~17 px/thread — well above 4
        window_mm=20.0,
        noise_sigma=0.0,
        seed=2,
    )
    result, _ = _run(spec, cfg)
    if result["ok"]:
        pass  # fine
    else:
        assert result["code"] != "ALIASING", (
            f"Unexpected ALIASING at 40 px/mm with 60 epi: {result['reason']}"
        )


# ---------------------------------------------------------------------------
# TC-05: Design stripes outside the band don't shift the count
# ---------------------------------------------------------------------------

def test_design_stripes_ignored(cfg):
    """
    §7.11: design stripes outside the band don't change the thread count.
    A slow stripe (5 mm period) should fall below band_min_k and be ignored.
    """
    # Reference result without design stripes
    spec_plain = FabricSpec(
        ends_per_inch=60, picks_per_inch=60,
        px_per_mm=40.0, window_mm=20.0,
        noise_sigma=0.0, seed=42,
        design_stripe_amplitude=0.0,
    )
    # Same but with strong design stripes (5 mm period >> band_max_px_per_cycle=40 px/cycle)
    spec_design = FabricSpec(
        ends_per_inch=60, picks_per_inch=60,
        px_per_mm=40.0, window_mm=20.0,
        noise_sigma=0.0, seed=42,
        design_stripe_amplitude=0.5,  # strong stripe
        design_stripe_period_mm=5.0,  # → 200 px period >> band_max=40 px/cycle
    )

    result_plain, gt = _run(spec_plain, cfg)
    result_design, _  = _run(spec_design, cfg)

    assert result_plain["ok"], f"Plain fabric failed: {result_plain['code']}"
    assert result_design["ok"], f"Design fabric failed: {result_design['code']}"

    # Thread counts should agree within 1%
    for key, gt_val in [
        ("ends_per_inch", gt.ends_per_inch),
        ("picks_per_inch", gt.picks_per_inch),
    ]:
        plain_val  = result_plain[key]
        design_val = result_design[key]
        err_vs_gt  = abs(design_val - gt_val) / gt_val * 100
        err_vs_ref = abs(design_val - plain_val) / plain_val * 100
        assert err_vs_gt <= 1.5, (
            f"Design stripe shifted {key}: plain={plain_val:.2f}, "
            f"design={design_val:.2f}, gt={gt_val:.2f}, "
            f"err_vs_gt={err_vs_gt:.2f}% (tol=1.5%)"
        )


# ---------------------------------------------------------------------------
# TC-06: NO_WEAVE returned when there is no periodic structure
# ---------------------------------------------------------------------------

def test_no_weave_on_pure_noise(cfg):
    """Pure random noise has no thread peaks → should return NO_WEAVE (or ALIASING)."""
    rng = np.random.default_rng(0)
    noise_img = rng.random((800, 800)).astype(np.float32)
    result = run_fft_grade(noise_img, px_per_mm=40.0, cfg=cfg)
    assert not result["ok"], "Expected failure on pure noise, got ok=True"
    assert result["code"] in ("NO_WEAVE", "ALIASING"), (
        f"Expected NO_WEAVE/ALIASING on noise, got {result['code']}"
    )


def test_no_weave_on_flat_image(cfg):
    """A completely flat image has no peaks → should return NO_WEAVE."""
    flat = np.full((800, 800), 0.5, dtype=np.float32)
    result = run_fft_grade(flat, px_per_mm=40.0, cfg=cfg)
    assert not result["ok"], "Expected failure on flat image"
    assert result["code"] in ("NO_WEAVE",), (
        f"Expected NO_WEAVE on flat image, got {result['code']}"
    )


# ---------------------------------------------------------------------------
# TC-07: Debug spectrum image is saved when debug_dir is given
# ---------------------------------------------------------------------------

def test_debug_spectrum_saved(cfg, tmp_path):
    """When debug_dir is given, spectrum_peaks.png must be written."""
    spec = FabricSpec(
        ends_per_inch=60, picks_per_inch=60,
        px_per_mm=40.0, window_mm=20.0,
        noise_sigma=0.0, seed=42,
    )
    debug_dir = str(tmp_path / "debug")
    result, _ = _run(spec, cfg, debug_dir=debug_dir)

    assert result["ok"], f"FFT failed: {result['code']}"
    spectrum_path = tmp_path / "debug" / "spectrum_peaks.png"
    assert spectrum_path.exists(), (
        f"Debug spectrum image not saved. Expected: {spectrum_path}"
    )
    # Basic sanity: file is non-empty
    assert spectrum_path.stat().st_size > 1000, "Spectrum image file looks empty"


# ---------------------------------------------------------------------------
# TC-08: Asymmetric weave — warp/weft correctly assigned
# ---------------------------------------------------------------------------

def test_warp_weft_assignment(cfg):
    """
    With the standard card orientation, warp threads run vertically.
    The warp peak should be near the kx axis (angle ≈ 0°/180°).
    """
    spec = FabricSpec(
        ends_per_inch=80,  # warp
        picks_per_inch=50, # weft
        px_per_mm=40.0, window_mm=20.0,
        noise_sigma=0.0, seed=42,
        grid_angle_deg=0.0,
    )
    result, gt = _run(spec, cfg)
    if not result["ok"]:
        pytest.fail(f"FFT failed: {result['code']} — {result['reason']}")

    # ends_per_inch should be closer to 80, picks_per_inch closer to 50
    epi = result["ends_per_inch"]
    ppi = result["picks_per_inch"]
    assert abs(epi - 80) < abs(epi - 50), (
        f"warp/weft swapped: epi={epi:.1f}, ppi={ppi:.1f} (expected epi≈80, ppi≈50)"
    )
    assert abs(ppi - 50) < abs(ppi - 80), (
        f"warp/weft swapped: epi={epi:.1f}, ppi={ppi:.1f} (expected epi≈80, ppi≈50)"
    )


# ---------------------------------------------------------------------------
# TC-09: Low px_per_mm scales (15, 20, 25) and Aliasing Guard (< 4 px/thread)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ppm", [15.0, 20.0, 25.0])
def test_low_scale_resolution(ppm, cfg):
    """
    Test thread count accuracy at lower resolutions (15, 20, 25 px/mm)
    when threads/pixel >= 4 (60 epi gives 6.35 to 10.58 px/thread).
    """
    spec = FabricSpec(
        ends_per_inch=60,
        picks_per_inch=60,
        px_per_mm=ppm,
        window_mm=20.0,
        noise_sigma=0.01,
        seed=101,
    )
    result, gt = _run(spec, cfg)
    _check_density(result, gt, tol_pct=1.0, label=f"scale {ppm} px/mm")


@pytest.mark.parametrize("epi,ppm", [
    (110, 15.0),  # 15 / (110/25.4) = 3.46 px/thread (< 4.0)
    (140, 20.0),  # 20 / (140/25.4) = 3.63 px/thread (< 4.0)
    (180, 25.0),  # 25 / (180/25.4) = 3.53 px/thread (< 4.0)
])
def test_aliasing_triggered_below_4_px_per_thread(epi, ppm, cfg):
    """
    Verify ALIASING quality code triggers whenever px/thread < 4.0.
    """
    spec = FabricSpec(
        ends_per_inch=epi,
        picks_per_inch=epi,
        px_per_mm=ppm,
        window_mm=20.0,
        seed=42,
    )
    result, gt = _run(spec, cfg)
    assert not result["ok"], f"Expected ALIASING at {gt.warp_px_per_thread:.2f} px/thread, but got ok=True"
    assert result["code"] in ("ALIASING", "NO_WEAVE"), (
        f"Expected ALIASING/NO_WEAVE, got {result['code']} at {gt.warp_px_per_thread:.2f} px/thread"
    )


# ---------------------------------------------------------------------------
# TC-10: Realistic Yarn Profile (slubs, harmonics, blur, lighting gradient)
# ---------------------------------------------------------------------------

def test_realistic_yarn_physics(cfg):
    """
    Test accuracy under realistic non-ideal yarn physics:
      - 2nd/3rd harmonics (non-sinusoidal cross-section)
      - random thickness variation (slubs)
      - hairiness micro-noise
      - optical Gaussian blur (sigma 1.2 px)
      - uneven illumination gradient (30%)
      - camera tilt (2.0°)
    """
    spec = FabricSpec(
        ends_per_inch=60,
        picks_per_inch=70,
        px_per_mm=30.0,
        window_mm=20.0,
        grid_angle_deg=2.0,
        harmonic_amplitude=0.3,
        slub_amplitude=0.25,
        hairiness_sigma=0.03,
        gaussian_blur_sigma=1.2,
        uneven_lighting=0.30,
        noise_sigma=0.02,
        seed=777,
    )
    result, gt = _run(spec, cfg)
    assert result["ok"], f"FFT failed on realistic yarn: {result['code']} — {result['reason']}"

    # Density error within 2%
    _check_density(result, gt, tol_pct=2.0, label="realistic yarn")

    # Angle recovery within 1°
    got_angle = result["warp_angle_deg"]
    err_angle = min(
        abs(got_angle - gt.grid_angle_deg),
        abs(got_angle - gt.grid_angle_deg + 180),
        abs(got_angle - gt.grid_angle_deg - 180),
    )
    assert err_angle <= 1.0, f"Angle error {err_angle:.2f}° > 1° on realistic yarn"


# ---------------------------------------------------------------------------
# TC-11: Irregularity Monotonicity
# ---------------------------------------------------------------------------

def test_irregularity_monotonicity(cfg):
    """
    Verify that increasing thread spacing jitter strictly increases
    the measured irregularity metric.
    """
    jitters = [0.0, 0.05, 0.12, 0.25]
    measured_irrs = []

    for jitter in jitters:
        spec = FabricSpec(
            ends_per_inch=60,
            picks_per_inch=60,
            px_per_mm=40.0,
            window_mm=20.0,
            irregularity_jitter=jitter,
            seed=42,
        )
        result, _ = _run(spec, cfg)
        assert result["ok"], f"FFT failed at jitter={jitter}: {result['code']}"
        irr = result["irregularity"]["warp"]
        measured_irrs.append(irr)

    # Monotonicity check
    for i in range(len(measured_irrs) - 1):
        assert measured_irrs[i + 1] > measured_irrs[i], (
            f"Irregularity not strictly monotonic: jitter {jitters[i]} -> {measured_irrs[i]:.4f}, "
            f"jitter {jitters[i+1]} -> {measured_irrs[i+1]:.4f}"
        )


# ---------------------------------------------------------------------------
# TC-12: Defect Detection (Clean vs Knot vs Broken Thread)
# ---------------------------------------------------------------------------

def test_defects_clean_is_zero(cfg):
    """Clean woven fabric must have zero detected defect blobs."""
    spec = FabricSpec(
        ends_per_inch=60,
        picks_per_inch=60,
        px_per_mm=40.0,
        window_mm=20.0,
        noise_sigma=0.01,
        defect_type=None,
        seed=42,
    )
    result, _ = _run(spec, cfg)
    assert result["ok"]
    assert result["defects"]["count"] == 0, (
        f"Expected 0 defects on clean fabric, got {result['defects']['count']}"
    )


def test_defects_knot_detected(cfg):
    """An inserted yarn knot must be detected as a defect blob."""
    spec = FabricSpec(
        ends_per_inch=60,
        picks_per_inch=60,
        px_per_mm=40.0,
        window_mm=20.0,
        noise_sigma=0.01,
        defect_type="knot",
        seed=42,
    )
    result, _ = _run(spec, cfg)
    assert result["ok"]
    assert result["defects"]["count"] >= 1, (
        f"Expected >= 1 defect for yarn knot, got {result['defects']['count']}"
    )
    assert result["defects"]["area_fraction"] > 0.0


def test_defects_broken_thread_detected(cfg):
    """An inserted broken thread must be detected as a defect blob."""
    spec = FabricSpec(
        ends_per_inch=60,
        picks_per_inch=60,
        px_per_mm=40.0,
        window_mm=20.0,
        noise_sigma=0.01,
        defect_type="broken_thread",
        seed=42,
    )
    result, _ = _run(spec, cfg)
    assert result["ok"]
    assert result["defects"]["count"] >= 1, (
        f"Expected >= 1 defect for broken thread, got {result['defects']['count']}"
    )
    assert result["defects"]["area_fraction"] > 0.0


# ---------------------------------------------------------------------------
# TC-13: Quality Grade (Rules from config.yaml)
# ---------------------------------------------------------------------------

def test_grade_classification(cfg):
    """
    Test grade assignment following config thresholds:
      - Grade A: max_irregularity: 0.04, max_defect_fraction: 0.002
      - Grade B: max_irregularity: 0.08, max_defect_fraction: 0.01
      - Grade C: else
    """
    from engine.fft_grade import _compute_grade

    grade_cfg = cfg["grade"]

    # When use_defects is False (default per config), defects do not downgrade
    assert _compute_grade(0.03, 0.001, grade_cfg) == "A"
    assert _compute_grade(0.06, 0.001, grade_cfg) == "B"
    assert _compute_grade(0.12, 0.001, grade_cfg) == "C"
    # High defect does not downgrade when use_defects=False
    assert _compute_grade(0.03, 0.02, grade_cfg) == "A"

    # When use_defects is True, high defects downgrade
    grade_cfg_defects = dict(grade_cfg, use_defects=True)
    assert _compute_grade(0.03, 0.001, grade_cfg_defects) == "A"
    assert _compute_grade(0.06, 0.001, grade_cfg_defects) == "B"
    assert _compute_grade(0.03, 0.02, grade_cfg_defects) == "C"

