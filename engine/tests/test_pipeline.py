"""
engine/tests/test_pipeline.py
End-to-end integration tests for the TantSaakshi vision engine pipeline (Steps 4 to 6).

Tests:
  - analyze() end to end with synthetic marker card photos
  - Burst stacking with handheld sub-pixel shifts
  - Quality rejection gates (NO_CARD, TOO_TILTED, TOO_DARK)
  - Compat wrapper behavior (grade, fingerprint, match)
  - Debug image artifact export
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from engine import analyze, quality_check
from engine.compat import grade, fingerprint, match
from engine.config import get_config
from tools.synth_fabric import FabricSpec, make_card_scene, to_uint8


@pytest.fixture(scope="module")
def cfg():
    return get_config()


def test_analyze_end_to_end_clean(cfg, tmp_path):
    """
    Test full analyze() on a clean synthetic card photo.
    """
    spec = FabricSpec(
        ends_per_inch=60,
        picks_per_inch=70,
        px_per_mm=30.0,
        window_mm=20.0,
        noise_sigma=0.01,
        seed=42,
    )
    scene_f32, info = make_card_scene(spec, cfg, tilt_deg=0.0, camera_px_per_mm=30.0)
    scene_u8 = to_uint8(scene_f32)

    img_path = str(tmp_path / "card_clean.png")
    cv2.imwrite(img_path, scene_u8)

    out_dir = str(tmp_path / "out")
    debug_dir = str(tmp_path / "debug")

    res = analyze([img_path], out_dir=out_dir, debug_dir=debug_dir)

    assert res["ok"], f"analyze failed: {res.get('code')} — {res.get('reason')}"
    assert res["code"] == "OK"

    # Thread count accuracy (within 2% on full scene rectification)
    gt = info["ground_truth"]
    epi_err = abs(res["ends_per_inch"] - gt.ends_per_inch) / gt.ends_per_inch * 100
    ppi_err = abs(res["picks_per_inch"] - gt.picks_per_inch) / gt.picks_per_inch * 100
    assert epi_err <= 2.0, f"ends_per_inch error {epi_err:.2f}% > 2%"
    assert ppi_err <= 2.0, f"picks_per_inch error {ppi_err:.2f}% > 2%"

    # Output structure contract
    assert "grade" in res
    assert res["grade_provisional"] is True
    assert "quality" in res
    assert "timings_ms" in res
    assert res["timings_ms"]["total"] > 0

    # Verify debug images were saved
    debug_path = Path(debug_dir)
    assert (debug_path / "debug_detected_markers.jpg").exists()
    assert (debug_path / "debug_rectified_window.png").exists()


def test_analyze_burst_stacking(cfg, tmp_path):
    """
    Test analyze() on a burst of 3 frames with sub-pixel handheld shifts.
    Verifies that n_stacked is exposed and exactly 3 of 3 frames get stacked.
    """
    spec = FabricSpec(ends_per_inch=60, picks_per_inch=60)
    burst_paths = []

    # Generate 3 frames with slight perspective / offset variations
    for i in range(3):
        scene_f32, _ = make_card_scene(spec, cfg, tilt_deg=1.0 * (i - 1), camera_px_per_mm=30.0, seed=42 + i)
        p = str(tmp_path / f"burst_{i}.png")
        cv2.imwrite(p, to_uint8(scene_f32))
        burst_paths.append(p)

    out_dir = str(tmp_path / "out_burst")
    res = analyze(burst_paths, out_dir=out_dir)

    assert res["ok"]
    assert res["code"] == "OK"
    assert "n_stacked" in res
    assert res["n_stacked"] == 3, f"Expected 3 frames stacked, got {res['n_stacked']}"
    assert "stacking" in res["timings_ms"]


def test_analyze_burst_one_bad_frame(cfg, tmp_path):
    """
    Item 7: One bad frame must not fail the burst.
    If 3 frames are valid and 1 frame is blurred/corrupted with no card,
    the burst must still succeed and stack the 3 valid frames.
    """
    spec = FabricSpec(ends_per_inch=60, picks_per_inch=60)
    burst_paths = []

    for i in range(3):
        scene_f32, _ = make_card_scene(spec, cfg, tilt_deg=1.0 * (i - 1), camera_px_per_mm=30.0, seed=100 + i)
        p = str(tmp_path / f"burst_good_{i}.png")
        cv2.imwrite(p, to_uint8(scene_f32))
        burst_paths.append(p)

    # 4th frame: pure noise image with no card
    noise_frame = np.full((1200, 1200, 3), 128, dtype=np.uint8)
    p_bad = str(tmp_path / "burst_bad_3.png")
    cv2.imwrite(p_bad, noise_frame)
    burst_paths.append(p_bad)

    out_dir = str(tmp_path / "out_burst_bad_frame")
    res = analyze(burst_paths, out_dir=out_dir)

    assert res["ok"] is True, f"Burst failed unexpectedly: {res.get('code')}"
    assert res["code"] == "OK"
    assert res["n_stacked"] == 3


def test_error_resilience_never_raise(cfg, tmp_path):
    """
    Item 9: Never raise on invalid files. Return codes BAD_IMAGE.
    """
    non_existent = str(tmp_path / "does_not_exist_file.png")

    res_an = analyze([non_existent], out_dir=str(tmp_path))
    assert res_an["ok"] is False
    assert res_an["code"] == "BAD_IMAGE"

    res_qc = quality_check([non_existent])
    assert res_qc["ok"] is False
    assert res_qc["code"] == "BAD_IMAGE"

    res_fp = fingerprint(non_existent)
    assert res_fp is None

    res_match = match("non_existent_a.npz", "non_existent_b.npz")
    assert res_match["ok"] is True or res_match["code"] in ("OK", "MATCH_FAILED")


def test_quality_rejection_no_card(cfg, tmp_path):
    """An image with no marker card must be rejected with NO_CARD."""
    # Plain noise background without markers
    noise_img = np.full((1200, 1200, 3), 128, dtype=np.uint8)
    p = str(tmp_path / "no_card.jpg")
    cv2.imwrite(p, noise_img)

    res = analyze([p], out_dir=str(tmp_path))
    assert not res["ok"]
    assert res["code"] == "NO_CARD"
    assert "card" in res["reason"].lower()


def test_quality_rejection_too_tilted(cfg, tmp_path):
    """An image tilted past max_tilt_deg must be rejected with TOO_TILTED."""
    spec = FabricSpec(ends_per_inch=60, picks_per_inch=60)
    # 32 deg tilt exceeds the 25 deg config limit
    scene_f32, _ = make_card_scene(spec, cfg, tilt_deg=32.0, camera_px_per_mm=30.0)
    p = str(tmp_path / "tilted.jpg")
    cv2.imwrite(p, to_uint8(scene_f32))

    res = analyze([p], out_dir=str(tmp_path))
    assert not res["ok"]
    assert res["code"] == "TOO_TILTED"


def test_quality_rejection_too_dark(cfg, tmp_path):
    """An image that is too dark must be rejected with TOO_DARK."""
    spec = FabricSpec(ends_per_inch=60, picks_per_inch=60)
    scene_f32, _ = make_card_scene(spec, cfg, tilt_deg=0.0, camera_px_per_mm=30.0)
    # Underexpose the whole scene severely (scale by 0.05)
    dark_scene = to_uint8(scene_f32 * 0.05)
    p = str(tmp_path / "dark.jpg")
    cv2.imwrite(p, dark_scene)

    res = analyze([p], out_dir=str(tmp_path))
    assert not res["ok"]
    assert res["code"] in ("TOO_DARK", "NO_CARD")


def test_quality_rejection_glare(cfg, tmp_path):
    """An image with excessive glare in the window must be rejected with GLARE."""
    spec = FabricSpec(ends_per_inch=60, picks_per_inch=60)
    scene_f32, _ = make_card_scene(spec, cfg, camera_px_per_mm=30.0)
    scene_u8 = to_uint8(scene_f32)
    H, W = scene_u8.shape[:2]
    # Saturated white circle at center of window (> 2% saturation)
    cv2.circle(scene_u8, (W // 2, H // 2), radius=80, color=(255, 255, 255), thickness=-1)
    p = str(tmp_path / "glare.png")
    cv2.imwrite(p, scene_u8)

    res = analyze([p], out_dir=str(tmp_path))
    assert not res["ok"]
    assert res["code"] == "GLARE"
    assert "glare" in res["reason"].lower()


def test_quality_rejection_blurry(cfg, tmp_path):
    """An image with a blurry fabric window must be rejected with BLURRY."""
    spec = FabricSpec(ends_per_inch=60, picks_per_inch=60)
    scene_f32, _ = make_card_scene(spec, cfg, camera_px_per_mm=30.0)
    scene_u8 = to_uint8(scene_f32)
    H, W = scene_u8.shape[:2]
    # Blur the central fabric window area while keeping markers sharp
    win_half = int(9.5 * 30.0)
    patch = scene_u8[H // 2 - win_half : H // 2 + win_half, W // 2 - win_half : W // 2 + win_half]
    scene_u8[H // 2 - win_half : H // 2 + win_half, W // 2 - win_half : W // 2 + win_half] = cv2.GaussianBlur(
        patch, (0, 0), sigmaX=8.0
    )
    p = str(tmp_path / "blurry.png")
    cv2.imwrite(p, scene_u8)

    res = analyze([p], out_dir=str(tmp_path))
    assert not res["ok"]
    assert res["code"] == "BLURRY"
    assert "blurry" in res["reason"].lower()


def test_quality_rejection_low_res(cfg, tmp_path):
    """An image captured too far away (< 20 px/mm) must be rejected with LOW_RES."""
    spec = FabricSpec(ends_per_inch=60, picks_per_inch=60)
    # camera_px_per_mm = 14.0 is below min_native_px_per_mm (20.0)
    scene_f32, _ = make_card_scene(spec, cfg, camera_px_per_mm=14.0)
    p = str(tmp_path / "low_res.png")
    cv2.imwrite(p, to_uint8(scene_f32))

    res = analyze([p], out_dir=str(tmp_path))
    assert not res["ok"]
    assert res["code"] == "LOW_RES"
    assert "closer" in res["reason"].lower()


def test_quality_rejection_aliasing(cfg, tmp_path):
    """An image where px per thread < 4.0 must be rejected with ALIASING."""
    # 180 ends/inch = 7.087 threads/mm; at 22 px/mm, 22/7.087 = 3.10 px/thread (< 4.0)
    spec_dense = FabricSpec(ends_per_inch=180.0, picks_per_inch=180.0)
    scene_f32, _ = make_card_scene(spec_dense, cfg, camera_px_per_mm=22.0)
    p = str(tmp_path / "aliasing.png")
    cv2.imwrite(p, to_uint8(scene_f32))

    res = analyze([p], out_dir=str(tmp_path))
    assert not res["ok"]
    assert res["code"] == "ALIASING"
    assert "closer" in res["reason"].lower()


def test_quality_rejection_no_weave(cfg, tmp_path):
    """An image where fabric has no periodic weave must be rejected with NO_WEAVE."""
    spec = FabricSpec(ends_per_inch=60, picks_per_inch=60)
    scene_f32, _ = make_card_scene(spec, cfg, camera_px_per_mm=30.0)
    scene_u8 = to_uint8(scene_f32)
    H, W = scene_u8.shape[:2]
    win_half = int(9.5 * 30.0)
    # Replace window with pure uniform random noise (no weave structure)
    rng = np.random.default_rng(123)
    noise_patch = rng.integers(110, 140, (2 * win_half, 2 * win_half), dtype=np.uint8)
    scene_u8[H // 2 - win_half : H // 2 + win_half, W // 2 - win_half : W // 2 + win_half] = noise_patch
    p = str(tmp_path / "no_weave.png")
    cv2.imwrite(p, scene_u8)

    res = analyze([p], out_dir=str(tmp_path))
    assert not res["ok"]
    assert res["code"] == "NO_WEAVE"
    assert "threads" in res["reason"].lower()


def test_quality_rejection_design_area(cfg, tmp_path):
    """A card placed over large design patterns must be rejected with DESIGN_AREA."""
    spec = FabricSpec(ends_per_inch=60, picks_per_inch=60)
    scene_f32, _ = make_card_scene(spec, cfg, camera_px_per_mm=30.0)
    scene_u8 = to_uint8(scene_f32)
    H, W = scene_u8.shape[:2]
    win_half = int(9.5 * 30.0)
    yy, xx = np.ogrid[: 2 * win_half, : 2 * win_half]
    # 5 mm low-frequency stripe pattern (150 px at 30 px/mm), well below thread frequencies
    stripe = (np.sin(2 * np.pi * xx / 150.0) * 80).astype(np.int16)
    patch = scene_u8[H // 2 - win_half : H // 2 + win_half, W // 2 - win_half : W // 2 + win_half].astype(np.int16)
    patch_mod = np.clip(patch + stripe, 10, 240).astype(np.uint8)
    scene_u8[H // 2 - win_half : H // 2 + win_half, W // 2 - win_half : W // 2 + win_half] = patch_mod
    p = str(tmp_path / "design_area.png")
    cv2.imwrite(p, scene_u8)

    res = analyze([p], out_dir=str(tmp_path))
    assert not res["ok"]
    assert res["code"] == "DESIGN_AREA"
    assert "plain area" in res["reason"].lower()


def test_distance_tilt_independence(cfg, tmp_path):
    """
    Synthetic distance & tilt independence test:
    The same fabric rendered across 3 scales (25, 30, 35 px/mm) and 3 tilts (0°, 8°, 15°)
    must yield thread count within 1.0% error of ground truth across all 9 combinations.
    """
    spec = FabricSpec(ends_per_inch=70.0, picks_per_inch=70.0, noise_sigma=0.01)
    scales = [25.0, 30.0, 35.0]
    tilts = [0.0, 8.0, 15.0]

    for scale in scales:
        for tilt in tilts:
            scene_f32, _ = make_card_scene(spec, cfg, tilt_deg=tilt, camera_px_per_mm=scale, seed=42)
            p = str(tmp_path / f"indep_s{int(scale)}_t{int(tilt)}.png")
            cv2.imwrite(p, to_uint8(scene_f32))

            res = analyze([p], out_dir=str(tmp_path / f"out_s{int(scale)}_t{int(tilt)}"))
            assert res["ok"] is True, f"Failed at scale={scale}, tilt={tilt}: {res.get('code')}"
            assert res["code"] == "OK"

            epi = res["ends_per_inch"]
            ppi = res["picks_per_inch"]
            err_epi = abs(epi - 70.0) / 70.0 * 100.0
            err_ppi = abs(ppi - 70.0) / 70.0 * 100.0

            assert err_epi <= 1.0, f"Scale {scale}, Tilt {tilt}: EPI error {err_epi:.2f}% > 1.0%"
            assert err_ppi <= 1.0, f"Scale {scale}, Tilt {tilt}: PPI error {err_ppi:.2f}% > 1.0%"


def test_timing_4k_burst(cfg, tmp_path):
    """
    Timing benchmark on 5-frame burst of full 4000x3000 (12MP) photos.
    Must complete within 5.0 seconds total (§7.2, §11).
    """
    import time

    spec = FabricSpec(ends_per_inch=60.0, picks_per_inch=65.0)
    burst_paths = []
    for i in range(5):
        scene_f32, _ = make_card_scene(
            spec,
            cfg,
            tilt_deg=1.5 * (i - 2),
            camera_px_per_mm=35.0,
            image_size=(3000, 4000),
            seed=500 + i,
        )
        p = str(tmp_path / f"frame_4k_{i}.jpg")
        cv2.imwrite(p, to_uint8(scene_f32), [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        burst_paths.append(p)

    out_dir = str(tmp_path / "out_timing_4k")
    t0 = time.perf_counter()
    res = analyze(burst_paths, out_dir=out_dir)
    elapsed = time.perf_counter() - t0

    assert res["ok"] is True
    assert res["code"] == "OK"
    assert elapsed <= 5.0, f"5-frame 4K burst took {elapsed:.2f}s > 5.0s budget"


def test_compat_wrappers(tmp_path, cfg):
    """
    Test compat.py wrappers matching backend stub signatures:
        grade(path)
        fingerprint(path)
        match(a, b)
    """
    spec = FabricSpec(ends_per_inch=60, picks_per_inch=60)
    scene_f32, _ = make_card_scene(spec, cfg, tilt_deg=0.0, camera_px_per_mm=30.0)
    p = str(tmp_path / "compat_test.png")
    cv2.imwrite(p, to_uint8(scene_f32))

    # 1. grade(path)
    res_grade = grade(p)
    assert isinstance(res_grade, dict)
    assert res_grade["ok"] is True
    assert "epi" in res_grade
    assert "ppi" in res_grade
    assert "grade" in res_grade

    # 2. fingerprint(path) returns path to residual .npz
    res_fp = fingerprint(p)
    assert res_fp is not None
    assert Path(res_fp).exists()

    # 3. match(a, b) compares fingerprints
    res_match = match(res_fp, res_fp)
    assert isinstance(res_match, dict)
    assert res_match["ok"] is True
    # Self-match has high score
    assert res_match["score_residual"] is not None
    assert res_match["score_residual"] > 0.90
    # Uncalibrated thresholds return match: None
    assert res_match["match"] is None
    assert res_match["calibrated"] is False

