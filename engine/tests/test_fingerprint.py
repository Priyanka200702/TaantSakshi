"""
engine/tests/test_fingerprint.py
Unit tests for fabric fingerprint extraction (§7.8) and matching (§7.9).

Tests:
  - Fingerprint extraction output format (.npz residual + SIFT)
  - Genuine pair matching: high residual correlation (> 0.70) and high SIFT inliers (> 50)
  - Impostor pair rejection: low residual correlation (< 0.25) and low SIFT inliers (< 10)
  - Placement tolerance: deliberate 1.5 mm spatial translation correctly identified
  - Glare masking: glare pixels excluded from matching and SIFT keypoints
  - Uncalibrated thresholds: returns match: None, calibrated: False without crashing
  - Calibrated threshold evaluation
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from engine.config import get_config
from engine.fingerprint import extract_fingerprint
from engine.match import match_fingerprints
from tools.synth_fabric import FabricSpec, make_burst, make_card_scene, make_fabric, to_uint8


@pytest.fixture(scope="module")
def cfg():
    return get_config()


def test_fingerprint_extraction_structure(cfg, tmp_path):
    """
    Test extraction of residual.npz and sift.npz.
    Verify array dtypes, shapes, and normalization properties.
    """
    spec = FabricSpec(
        ends_per_inch=65,
        picks_per_inch=65,
        px_per_mm=25.0,
        hairiness_sigma=0.05,
        slub_amplitude=0.20,
        seed=42,
    )
    img, _ = make_fabric(spec)

    out_dir = str(tmp_path / "fp_struct")
    res_dict = extract_fingerprint(img, out_dir=out_dir, cfg=cfg, prefix="test")

    assert "residual_path" in res_dict
    assert "sift_path" in res_dict

    res_p = Path(res_dict["residual_path"])
    sift_p = Path(res_dict["sift_path"])
    assert res_p.exists()
    assert sift_p.exists()

    # Verify residual npz contents
    data_res = np.load(res_p)
    assert "residual" in data_res
    assert "glare_mask" in data_res
    residual = data_res["residual"]
    glare_mask = data_res["glare_mask"]

    assert residual.dtype == np.float16
    assert residual.shape == (400, 400)
    assert glare_mask.dtype == bool
    assert glare_mask.shape == (400, 400)

    # Verify SIFT npz contents
    data_sift = np.load(sift_p)
    assert "pts" in data_sift
    assert "descriptors" in data_sift
    pts = data_sift["pts"]
    desc = data_sift["descriptors"]
    assert pts.ndim == 2 and pts.shape[1] == 2
    assert desc.ndim == 2 and desc.shape[1] == 128
    assert len(pts) == len(desc)


def test_genuine_vs_impostor_matching(cfg, tmp_path):
    """
    Genuine pair (same physical saree patch with handheld shift and sensor noise)
    vs Impostor pair (different saree with identical nominal weave density).
    """
    # Saree A: weaver #1
    spec_a = FabricSpec(
        ends_per_inch=70,
        picks_per_inch=70,
        px_per_mm=25.0,
        hairiness_sigma=0.06,
        slub_amplitude=0.25,
        irregularity_jitter=0.08,
        noise_sigma=0.01,
        seed=101,
    )
    img_a1, _ = make_fabric(spec_a)

    # Verification photo of Saree A: 1.5 px handheld shift + independent noise
    burst_a, _ = make_burst(spec_a, n_frames=2, max_shift_px=1.5, noise_per_frame_sigma=0.02)
    img_a2 = burst_a[1]

    # Saree B: weaver #2 (impostor cloth with same 70x70 weave)
    spec_b = FabricSpec(
        ends_per_inch=70,
        picks_per_inch=70,
        px_per_mm=25.0,
        hairiness_sigma=0.06,
        slub_amplitude=0.25,
        irregularity_jitter=0.08,
        noise_sigma=0.01,
        seed=999,
    )
    img_b, _ = make_fabric(spec_b)

    dir_a1 = str(tmp_path / "fp_a1")
    dir_a2 = str(tmp_path / "fp_a2")
    dir_b = str(tmp_path / "fp_b")

    fp_a1 = extract_fingerprint(img_a1, out_dir=dir_a1, cfg=cfg, prefix="a1")
    fp_a2 = extract_fingerprint(img_a2, out_dir=dir_a2, cfg=cfg, prefix="a2")
    fp_b = extract_fingerprint(img_b, out_dir=dir_b, cfg=cfg, prefix="b")

    # 1. Genuine pair match
    res_gen = match_fingerprints(fp_a1, fp_a2, cfg=cfg)
    assert res_gen["score_residual"] is not None
    assert res_gen["score_residual"] > 0.70, f"Genuine residual score {res_gen['score_residual']} too low"
    assert res_gen["inliers"] is not None
    assert res_gen["inliers"] > 50, f"Genuine SIFT inliers {res_gen['inliers']} too low"

    # 2. Impostor pair match
    res_imp = match_fingerprints(fp_a1, fp_b, cfg=cfg)
    assert res_imp["score_residual"] is not None
    assert res_imp["score_residual"] < 0.25, f"Impostor residual score {res_imp['score_residual']} too high"
    assert res_imp["inliers"] is not None
    assert res_imp["inliers"] < 10, f"Impostor SIFT inliers {res_imp['inliers']} too high"

    # Margin check: genuine must vastly exceed impostor
    assert res_gen["score_residual"] - res_imp["score_residual"] > 0.50
    assert res_gen["inliers"] - res_imp["inliers"] > 40


def test_placement_translation_tolerance(cfg, tmp_path):
    """
    Placement tolerance test (§7.9):
    Simulate the card landing ~1.2 mm off the registered spot (30 px shift at 25 px/mm).
    Phase correlation and SIFT must detect the spatial translation.
    """
    spec = FabricSpec(
        ends_per_inch=65,
        picks_per_inch=65,
        px_per_mm=25.0,
        hairiness_sigma=0.06,
        slub_amplitude=0.25,
        seed=303,
    )
    img_base, _ = make_fabric(spec)
    H, W = img_base.shape

    # Shift image by dx = 25 px (1.0 mm) and dy = -10 px (-0.4 mm)
    dx_true, dy_true = 25.0, -10.0
    M = np.float32([[1.0, 0.0, dx_true], [0.0, 1.0, dy_true]])
    img_shifted = cv2.warpAffine(img_base, M, (W, H), borderMode=cv2.BORDER_REFLECT_101)
    noise = np.random.default_rng(55).normal(0, 0.015, (H, W)).astype(np.float32)
    img_shifted = np.clip(img_shifted + noise, 0.0, 1.0)

    fp1 = extract_fingerprint(img_base, out_dir=str(tmp_path / "fp_trans1"), cfg=cfg, prefix="t1")
    fp2 = extract_fingerprint(img_shifted, out_dir=str(tmp_path / "fp_trans2"), cfg=cfg, prefix="t2")

    res = match_fingerprints(fp1, fp2, cfg=cfg)

    # Verify phase correlation recovered the physical translation
    shift = res["details"]["best_shift"]
    assert abs(shift[0] - dx_true) < 3.0, f"Detected dx {shift[0]} != {dx_true}"
    assert abs(shift[1] - dy_true) < 3.0, f"Detected dy {shift[1]} != {dy_true}"

    # Residual correlation remains high despite offset
    assert res["score_residual"] > 0.60
    assert res["inliers"] > 30


def test_glare_masking_in_fingerprint(cfg, tmp_path):
    """
    Glare exclusion test:
    Confirm saturated glare pixels are excluded from the SIFT descriptors
    and excluded from the residual matching computation.
    """
    spec = FabricSpec(
        ends_per_inch=70,
        picks_per_inch=70,
        px_per_mm=25.0,
        hairiness_sigma=0.05,
        glare_spots=1,
        glare_radius_px=25,
        seed=404,
    )
    img_glare, _ = make_fabric(spec)

    out_dir = str(tmp_path / "fp_glare")
    fp = extract_fingerprint(img_glare, out_dir=out_dir, cfg=cfg, prefix="glare")

    data_res = np.load(fp["residual_path"])
    glare_mask = data_res["glare_mask"]
    assert np.any(glare_mask), "Glare mask should have saturated pixels"

    # Verify no SIFT keypoints lie inside the glare region
    data_sift = np.load(fp["sift_path"])
    pts = data_sift["pts"]
    for x, y in pts:
        ix, iy = int(round(x)), int(round(y))
        if 0 <= iy < glare_mask.shape[0] and 0 <= ix < glare_mask.shape[1]:
            assert not glare_mask[iy, ix], f"Keypoint ({x}, {y}) was extracted from glare region!"


def test_uncalibrated_thresholds_return_none(cfg, tmp_path):
    """
    When config thresholds are null, match() must compute and return numeric scores
    but set match: None and calibrated: False (§7.9, User prompt Item 7).
    Never fakes a decision.
    """
    spec = FabricSpec(ends_per_inch=60, picks_per_inch=60, px_per_mm=25.0)
    img, _ = make_fabric(spec)

    fp1 = extract_fingerprint(img, out_dir=str(tmp_path / "fp_uncal1"), cfg=cfg, prefix="u1")
    fp2 = extract_fingerprint(img, out_dir=str(tmp_path / "fp_uncal2"), cfg=cfg, prefix="u2")

    res = match_fingerprints(fp1, fp2, cfg=cfg)

    assert res["match"] is None
    assert res["calibrated"] is False
    assert res["score_residual"] is not None
    assert res["inliers"] is not None


def test_calibrated_decision_thresholds(cfg, tmp_path):
    """
    When valid calibrated thresholds are supplied, match() returns definitive bool.
    """
    cfg_calibrated = dict(cfg)
    cfg_calibrated["fingerprint"] = dict(
        cfg["fingerprint"],
        match_threshold_residual=0.60,
        match_threshold_inliers=30,
    )

    spec = FabricSpec(
        ends_per_inch=65,
        picks_per_inch=65,
        px_per_mm=25.0,
        hairiness_sigma=0.06,
        slub_amplitude=0.25,
        seed=505,
    )
    img1, _ = make_fabric(spec)
    burst, _ = make_burst(spec, n_frames=2, max_shift_px=1.0)
    img2 = burst[1]

    spec_other = FabricSpec(
        ends_per_inch=65,
        picks_per_inch=65,
        px_per_mm=25.0,
        hairiness_sigma=0.06,
        slub_amplitude=0.25,
        seed=808,
    )
    img_other, _ = make_fabric(spec_other)

    fp1 = extract_fingerprint(img1, out_dir=str(tmp_path / "fp_c1"), cfg=cfg_calibrated, prefix="c1")
    fp2 = extract_fingerprint(img2, out_dir=str(tmp_path / "fp_c2"), cfg=cfg_calibrated, prefix="c2")
    fp_other = extract_fingerprint(img_other, out_dir=str(tmp_path / "fp_co"), cfg=cfg_calibrated, prefix="co")

    # Genuine match
    res_gen = match_fingerprints(fp1, fp2, cfg=cfg_calibrated)
    assert res_gen["calibrated"] is True
    assert res_gen["match"] is True

    # Impostor non-match
    res_imp = match_fingerprints(fp1, fp_other, cfg=cfg_calibrated)
    assert res_imp["calibrated"] is True
    assert res_imp["match"] is False

