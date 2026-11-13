"""
engine/tests/test_fingerprint.py
Unit tests for fabric fingerprint extraction (§7.8) and matching (§7.9).

Includes physically consistent synthetic phone photos (high-res master fabric
downsampled with cv2.INTER_AREA, independent blur, sensor noise, card shifts,
and phone scale variations) per Item 5 of user feedback.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
import pytest

from engine.config import get_config
from engine.fingerprint import extract_fingerprint
from engine.match import match_fingerprints
from tools.synth_fabric import FabricSpec, make_fabric


@pytest.fixture(scope="module")
def cfg():
    return get_config()


def _render_phone_photo(
    master_fabric: np.ndarray,
    master_px_per_mm: float,
    phone_px_per_mm: float,
    shift_mm: tuple[float, float] = (0.0, 0.0),
    rotation_deg: float = 0.0,
    blur_sigma_px: float = 0.8,
    noise_sigma: float = 0.015,
    seed: int = 42,
    window_mm: float = 20.0,
) -> np.ndarray:
    """
    Simulate a phone camera capture from a high-resolution master fabric patch.
    Applies spatial shift (mm), rotation (deg), downsampling via INTER_AREA,
    optical Gaussian blur, and independent Gaussian sensor noise.
    """
    H, W = master_fabric.shape
    cx, cy = W / 2.0, H / 2.0

    # Shift in master pixels
    dx_m = shift_mm[0] * master_px_per_mm
    dy_m = shift_mm[1] * master_px_per_mm

    # Transformation: rotate around center and shift
    M = cv2.getRotationMatrix2D((cx, cy), rotation_deg, 1.0)
    M[0, 2] += dx_m
    M[1, 2] += dy_m

    transformed_master = cv2.warpAffine(
        master_fabric,
        M,
        (W, H),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )

    # Crop central window_mm
    win_master_sz = int(round(window_mm * master_px_per_mm))
    r_h = win_master_sz // 2
    cropped = transformed_master[int(cy) - r_h : int(cy) + r_h, int(cx) - r_h : int(cx) + r_h]

    # Downsample to phone sensor scale using anti-aliased area interpolation
    out_dim = int(round(window_mm * phone_px_per_mm))
    phone_img = cv2.resize(cropped, (out_dim, out_dim), interpolation=cv2.INTER_AREA)

    # Optical blur
    if blur_sigma_px > 0:
        phone_img = cv2.GaussianBlur(phone_img, (0, 0), sigmaX=blur_sigma_px, sigmaY=blur_sigma_px)

    # Independent sensor noise
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, noise_sigma, phone_img.shape).astype(np.float32)
    phone_img = np.clip(phone_img + noise, 0.0, 1.0)

    return phone_img


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
    res_dict = extract_fingerprint(img, out_dir=out_dir, cfg=cfg, prefix="test", px_per_mm=25.0)

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
    assert "scale_px_per_mm" in data_res
    assert "warp_angle_deg" in data_res

    residual = data_res["residual"]
    glare_mask = data_res["glare_mask"]
    res_sz = int(cfg["fingerprint"].get("residual_size_px", 160))

    assert residual.dtype == np.float16
    assert residual.shape == (res_sz, res_sz)
    assert glare_mask.dtype == bool
    assert glare_mask.shape == (res_sz, res_sz)

    # Verify SIFT npz contents
    data_sift = np.load(sift_p)
    assert "pts" in data_sift
    assert "descriptors" in data_sift
    pts = data_sift["pts"]
    desc = data_sift["descriptors"]
    assert pts.ndim == 2 and pts.shape[1] == 2
    assert desc.ndim == 2 and desc.shape[1] == 128
    assert len(pts) == len(desc)


def test_never_upsample_low_res(cfg, tmp_path):
    """
    Item 3: If native resolution is below target fingerprint scale (10 px/mm),
    extract_fingerprint must return LOW_RES_FINGERPRINT and never upsample.
    """
    # 8 px/mm is below the 10 px/mm fingerprint scale
    low_res_img = np.full((160, 160), 0.5, dtype=np.float32)

    with pytest.raises(ValueError) as excinfo:
        extract_fingerprint(
            low_res_img,
            out_dir=str(tmp_path),
            cfg=cfg,
            px_per_mm=8.0,
        )
    assert "LOW_RES_FINGERPRINT" in str(excinfo.value)


def test_genuine_vs_impostor_distributions_physically_consistent(cfg, tmp_path):
    """
    Item 5: Physically consistent synthetic validation.
    Render ONE high-res master fabric (60 px/mm) per 'saree', downsample per phone scale (INTER_AREA)
    with independent sensor noise and optical blur per photo, plus card shifts of 0, 1, 2, 3 mm
    and rotations of 0, 5, 10 degrees.
    Impostors = different master with IDENTICAL weave density and slub parameters.
    """
    master_scale = 60.0  # 60 px/mm master
    spec_master_a = FabricSpec(
        ends_per_inch=68,
        picks_per_inch=68,
        px_per_mm=master_scale,
        window_mm=28.0,  # 28x28 mm to allow shifting up to 3 mm
        slub_amplitude=0.25,
        irregularity_jitter=0.07,
        hairiness_sigma=0.06,
        seed=101,
    )
    master_a, _ = make_fabric(spec_master_a)

    spec_master_b = FabricSpec(
        ends_per_inch=68,
        picks_per_inch=68,
        px_per_mm=master_scale,
        window_mm=28.0,
        slub_amplitude=0.25,
        irregularity_jitter=0.07,
        hairiness_sigma=0.06,
        seed=999,  # Impostor saree with identical weave statistics
    )
    master_b, _ = make_fabric(spec_master_b)

    out_base = tmp_path / "fp_dist"
    out_base.mkdir()

    # 1. Registration photo of Saree A (Phone 1: 30 px/mm, 0 shift, 0 rot)
    p_reg = _render_phone_photo(master_a, master_scale, phone_px_per_mm=30.0, shift_mm=(0.0, 0.0), rotation_deg=0.0, seed=1)
    fp_reg = extract_fingerprint(p_reg, out_dir=str(out_base / "reg"), cfg=cfg, prefix="reg", px_per_mm=30.0)

    # 2. Genuine verification photos of Saree A under various conditions
    genuine_conditions = [
        ("same_phone_0mm", (0.0, 0.0), 0.0, 30.0, 2),
        ("shift_1mm", (1.0, 0.0), 0.0, 30.0, 3),
        ("shift_2mm", (2.0, 0.0), 0.0, 30.0, 4),
        ("shift_3mm", (3.0, 0.0), 0.0, 30.0, 5),
        ("rot_5deg", (0.0, 0.0), 5.0, 30.0, 6),
        ("rot_10deg", (0.0, 0.0), 10.0, 30.0, 7),
        ("phone_low_22px", (0.0, 0.0), 0.0, 22.0, 8),
        ("phone_high_38px", (0.0, 0.0), 0.0, 38.0, 9),
    ]

    genuine_scores = []
    for label, shift, rot, scale, s_seed in genuine_conditions:
        photo = _render_phone_photo(master_a, master_scale, phone_px_per_mm=scale, shift_mm=shift, rotation_deg=rot, seed=s_seed)
        fp = extract_fingerprint(photo, out_dir=str(out_base / label), cfg=cfg, prefix=label, px_per_mm=scale)
        m_res = match_fingerprints(fp_reg, fp, cfg=cfg)
        score = m_res["score_residual"]
        assert score is not None
        genuine_scores.append((label, score))
        # Genuine score must exceed 0.60 across all handheld shifts, rotations, and scales
        assert score > 0.60, f"Genuine condition '{label}' failed with residual score {score:.4f} <= 0.60"

    # 3. Impostor verification photos (Saree B)
    impostor_conditions = [
        ("impostor_0mm", (0.0, 0.0), 0.0, 30.0, 101),
        ("impostor_shift_1mm", (1.0, 0.0), 0.0, 30.0, 102),
        ("impostor_rot_5deg", (0.0, 0.0), 5.0, 30.0, 103),
    ]

    impostor_scores = []
    for label, shift, rot, scale, s_seed in impostor_conditions:
        photo = _render_phone_photo(master_b, master_scale, phone_px_per_mm=scale, shift_mm=shift, rotation_deg=rot, seed=s_seed)
        fp = extract_fingerprint(photo, out_dir=str(out_base / label), cfg=cfg, prefix=label, px_per_mm=scale)
        m_res = match_fingerprints(fp_reg, fp, cfg=cfg)
        score = m_res["score_residual"]
        assert score is not None
        impostor_scores.append((label, score))
        # Impostor score must remain low (< 0.20)
        assert score < 0.20, f"Impostor condition '{label}' has excessive score {score:.4f} >= 0.20"

    # 4. Distribution separation check
    min_gen = min(s for _, s in genuine_scores)
    max_imp = max(s for _, s in impostor_scores)
    separation_margin = min_gen - max_imp
    assert separation_margin > 0.45, f"Separation margin {separation_margin:.4f} is too narrow (< 0.45)"


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
    fp = extract_fingerprint(img_glare, out_dir=out_dir, cfg=cfg, prefix="glare", px_per_mm=25.0)

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

    fp1 = extract_fingerprint(img, out_dir=str(tmp_path / "fp_uncal1"), cfg=cfg, prefix="u1", px_per_mm=25.0)
    fp2 = extract_fingerprint(img, out_dir=str(tmp_path / "fp_uncal2"), cfg=cfg, prefix="u2", px_per_mm=25.0)

    res = match_fingerprints(fp1, fp2, cfg=cfg)

    assert res["match"] is None
    assert res["calibrated"] is False
    assert res["score_residual"] is not None
    assert res["inliers"] is not None


def test_card_shift_2mm_diagonal(cfg, tmp_path):
    """
    Item 4: Card shift 2 mm diagonal (the weakest case: genuine NCC min 0.33).
    Must achieve genuine NCC >= 0.33 and clear separation over impostor.
    """
    master_scale = 60.0
    spec_master_a = FabricSpec(
        ends_per_inch=68,
        picks_per_inch=68,
        px_per_mm=master_scale,
        window_mm=28.0,
        slub_amplitude=0.25,
        irregularity_jitter=0.07,
        hairiness_sigma=0.06,
        seed=101,
    )
    master_a, _ = make_fabric(spec_master_a)

    spec_master_b = FabricSpec(
        ends_per_inch=68,
        picks_per_inch=68,
        px_per_mm=master_scale,
        window_mm=28.0,
        slub_amplitude=0.25,
        irregularity_jitter=0.07,
        hairiness_sigma=0.06,
        seed=999,
    )
    master_b, _ = make_fabric(spec_master_b)

    out_base = tmp_path / "fp_diag"
    out_base.mkdir()

    p_reg = _render_phone_photo(master_a, master_scale, phone_px_per_mm=30.0, shift_mm=(0.0, 0.0), rotation_deg=0.0, seed=1)
    fp_reg = extract_fingerprint(p_reg, out_dir=str(out_base / "reg"), cfg=cfg, prefix="reg", px_per_mm=30.0)

    # 2 mm diagonal shift (dx = 2.0 mm, dy = 2.0 mm)
    p_diag = _render_phone_photo(master_a, master_scale, phone_px_per_mm=30.0, shift_mm=(2.0, 2.0), rotation_deg=0.0, seed=2)
    fp_diag = extract_fingerprint(p_diag, out_dir=str(out_base / "diag"), cfg=cfg, prefix="diag", px_per_mm=30.0)

    res_diag = match_fingerprints(fp_reg, fp_diag, cfg=cfg)
    score_gen = res_diag["score_residual"]

    assert score_gen is not None
    assert score_gen >= 0.33, f"Genuine 2 mm diagonal shift NCC {score_gen:.4f} < 0.33"

    # Impostor on same diagonal condition
    p_imp = _render_phone_photo(master_b, master_scale, phone_px_per_mm=30.0, shift_mm=(2.0, 2.0), rotation_deg=0.0, seed=3)
    fp_imp = extract_fingerprint(p_imp, out_dir=str(out_base / "imp"), cfg=cfg, prefix="imp", px_per_mm=30.0)

    res_imp = match_fingerprints(fp_reg, fp_imp, cfg=cfg)
    score_imp = res_imp["score_residual"]
    assert score_imp is not None
    assert score_gen - score_imp > 0.40, f"Separation margin {score_gen - score_imp:.4f} too small"


def test_calibrated_decision_thresholds(cfg, tmp_path):
    """
    When valid calibrated residual threshold is supplied, match() returns definitive bool.
    Decision uses only residual NCC threshold (Item 1). SIFT is kept for diagnostic only.
    """
    cfg_calibrated = dict(cfg)
    cfg_calibrated["fingerprint"] = dict(
        cfg["fingerprint"],
        match_threshold_residual=0.60,
        match_threshold_inliers=None,
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
    img2 = cv2.GaussianBlur(img1, (3, 3), 0.5)

    spec_other = FabricSpec(
        ends_per_inch=65,
        picks_per_inch=65,
        px_per_mm=25.0,
        hairiness_sigma=0.06,
        slub_amplitude=0.25,
        seed=808,
    )
    img_other, _ = make_fabric(spec_other)

    fp1 = extract_fingerprint(img1, out_dir=str(tmp_path / "fp_c1"), cfg=cfg_calibrated, prefix="c1", px_per_mm=25.0)
    fp2 = extract_fingerprint(img2, out_dir=str(tmp_path / "fp_c2"), cfg=cfg_calibrated, prefix="c2", px_per_mm=25.0)
    fp_other = extract_fingerprint(img_other, out_dir=str(tmp_path / "fp_co"), cfg=cfg_calibrated, prefix="co", px_per_mm=25.0)

    # Genuine match
    res_gen = match_fingerprints(fp1, fp2, cfg=cfg_calibrated)
    assert res_gen["calibrated"] is True
    assert res_gen["match"] is True

    # Impostor non-match
    res_imp = match_fingerprints(fp1, fp_other, cfg=cfg_calibrated)
    assert res_imp["calibrated"] is True
    assert res_imp["match"] is False
