"""
engine/match.py
Fingerprint matching module implementing §7.9 of TANTSAAKSHI_ENGINE_SPEC.md.

Compares two fabric fingerprints using dual complementary methods:
  1. Residual method: 2D phase correlation & masked normalized cross-correlation across small rotation search (-3°..+3°).
  2. SIFT method: L2 nearest-neighbour, Lowe ratio test (0.80), and RANSAC partial affine verification.
     Impostor coincidences are rejected if scale change > 10% or rotation > 8°.

Decision logic:
  - If thresholds in config are null, returns match: None, calibrated: False. Never fakes a decision.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from engine.config import get_config


def _resolve_paths(fp: dict[str, Any] | str | Path) -> tuple[str | None, str | None]:
    """Extract (residual_path, sift_path) from dict or path."""
    if isinstance(fp, dict):
        res_p = fp.get("residual_path")
        sift_p = fp.get("sift_path")
        return (str(res_p) if res_p else None, str(sift_p) if sift_p else None)
    elif isinstance(fp, (str, Path)):
        p = str(fp)
        if "sift" in p.lower():
            return None, p
        return p, None
    return None, None


def match_residuals(
    res_a: np.ndarray,
    glare_a: np.ndarray,
    res_b: np.ndarray,
    glare_b: np.ndarray,
    rotation_range_deg: int = 3,
) -> tuple[float, float, tuple[float, float], float]:
    """
    Match two residual images using phase correlation over a small rotation search.

    Returns
    -------
    best_ncc : float, masked normalized cross correlation [-1, 1]
    best_resp : float, phaseCorrelate peak response
    best_shift : tuple (dx, dy)
    best_rotation : float in degrees
    """
    H, W = res_a.shape
    hann = cv2.createHanningWindow((W, H), cv2.CV_64F)

    best_ncc = -1.0
    best_resp = 0.0
    best_shift = (0.0, 0.0)
    best_rot = 0.0

    cx, cy = W / 2.0, H / 2.0

    for rot_deg in range(-rotation_range_deg, rotation_range_deg + 1):
        if rot_deg != 0:
            M_rot = cv2.getRotationMatrix2D((cx, cy), float(rot_deg), 1.0)
            rot_b = cv2.warpAffine(
                res_b.astype(np.float32),
                M_rot,
                (W, H),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT_101,
            )
            rot_glare_b = cv2.warpAffine(
                glare_b.astype(np.uint8),
                M_rot,
                (W, H),
                flags=cv2.INTER_NEAREST,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=1,
            ) > 0
        else:
            rot_b = res_b.astype(np.float32)
            rot_glare_b = glare_b

        # Phase correlation
        (dx, dy), phase_resp = cv2.phaseCorrelate(
            res_a.astype(np.float64),
            rot_b.astype(np.float64),
            hann,
        )

        # Translate rot_b by detected shift to align onto res_a
        M_shift = np.float32([[1.0, 0.0, -dx], [0.0, 1.0, -dy]])
        shifted_b = cv2.warpAffine(
            rot_b,
            M_shift,
            (W, H),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        shifted_glare_b = cv2.warpAffine(
            rot_glare_b.astype(np.uint8),
            M_shift,
            (W, H),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=1,
        ) > 0

        # Mask: exclude border margin (15 px at 10 px/mm = 1.5 mm) and glare pixels
        border = 15
        valid = np.ones((H, W), dtype=bool)
        valid[:border, :] = False
        valid[-border:, :] = False
        valid[:, :border] = False
        valid[:, -border:] = False
        valid = valid & (~glare_a) & (~shifted_glare_b)

        if np.sum(valid) > 200:
            v_a = res_a[valid]
            v_b = shifted_b[valid]
            std_a = np.std(v_a)
            std_b = np.std(v_b)
            if std_a > 1e-6 and std_b > 1e-6:
                ncc = float(np.mean((v_a - np.mean(v_a)) * (v_b - np.mean(v_b))) / (std_a * std_b))
            else:
                ncc = 0.0
        else:
            ncc = 0.0

        if ncc > best_ncc:
            best_ncc = ncc
            best_resp = float(phase_resp)
            best_shift = (float(dx), float(dy))
            best_rot = float(rot_deg)

    return float(best_ncc), float(best_resp), best_shift, best_rot


def match_sift_descriptors(
    pts_a: np.ndarray,
    desc_a: np.ndarray,
    pts_b: np.ndarray,
    desc_b: np.ndarray,
    ratio_test: float = 0.80,
    ransac_reproj_px: float = 3.0,
    max_scale_change: float = 0.10,
    max_rotation_deg: float = 8.0,
) -> tuple[int, float, float, int]:
    """
    Match SIFT keypoints & descriptors using Lowe's ratio test and partial affine RANSAC.

    Returns
    -------
    inliers : int (0 if rejected or insufficient matches)
    scale_change : float
    rotation_deg : float
    total_good_matches : int
    """
    if desc_a is None or desc_b is None or len(desc_a) < 4 or len(desc_b) < 4:
        return 0, 0.0, 0.0, 0

    bf = cv2.BFMatcher(cv2.NORM_L2)
    matches = bf.knnMatch(desc_a, desc_b, k=2)

    good_matches = []
    for pair in matches:
        if len(pair) == 2:
            m, n = pair
            if m.distance < ratio_test * n.distance:
                good_matches.append(m)

    total_good = len(good_matches)
    if total_good < 4:
        return 0, 0.0, 0.0, total_good

    src_pts = np.float32([pts_a[m.queryIdx] for m in good_matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([pts_b[m.trainIdx] for m in good_matches]).reshape(-1, 1, 2)

    M, inliers_mask = cv2.estimateAffinePartial2D(
        src_pts,
        dst_pts,
        method=cv2.RANSAC,
        ransacReprojThreshold=ransac_reproj_px,
    )

    if M is None or inliers_mask is None:
        return 0, 0.0, 0.0, total_good

    # Extract transformation scale and rotation:
    # M = [[s*cos(theta), -s*sin(theta), tx], [s*sin(theta), s*cos(theta), ty]]
    scale = float(math.hypot(M[0, 0], M[1, 0]))
    scale_change = abs(scale - 1.0)
    theta_rad = math.atan2(M[1, 0], M[0, 0])
    rot_deg = abs(math.degrees(theta_rad))

    # Reject transforms outside legitimate placement tolerance (§7.9)
    if scale_change > max_scale_change or rot_deg > max_rotation_deg:
        return 0, scale_change, rot_deg, total_good

    inliers_count = int(np.sum(inliers_mask))
    return inliers_count, scale_change, rot_deg, total_good


def match_fingerprints(
    fp_a: dict[str, Any] | str,
    fp_b: dict[str, Any] | str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Compare two fabric fingerprints.

    Parameters
    ----------
    fp_a : fingerprint dict {"residual_path", "sift_path"} or file path
    fp_b : fingerprint dict {"residual_path", "sift_path"} or file path
    cfg : optional configuration dict

    Returns
    -------
    dict:
      match : bool | None (None when thresholds are uncalibrated null)
      calibrated : bool
      score_residual : float | None
      inliers : int | None
      score : float
      method : str ("residual" | "sift" | "both")
      details : dict
    """
    if cfg is None:
        cfg = get_config()

    fp_cfg = cfg["fingerprint"]
    method = fp_cfg.get("method", "both")

    res_p_a, sift_p_a = _resolve_paths(fp_a)
    res_p_b, sift_p_b = _resolve_paths(fp_b)

    score_residual = None
    inliers = None
    phase_resp = 0.0
    best_shift = (0.0, 0.0)
    best_rot = 0.0
    scale_change = 0.0
    sift_rot = 0.0
    total_good = 0

    # 1. Residual matching
    if res_p_a and res_p_b and Path(res_p_a).exists() and Path(res_p_b).exists():
        data_a = np.load(res_p_a)
        data_b = np.load(res_p_b)
        r_a = data_a["residual"].astype(np.float32)
        g_a = data_a["glare_mask"].astype(bool)
        r_b = data_b["residual"].astype(np.float32)
        g_b = data_b["glare_mask"].astype(bool)

        ncc, phase_resp, best_shift, best_rot = match_residuals(r_a, g_a, r_b, g_b)
        score_residual = float(ncc)

    # 2. SIFT matching
    if sift_p_a and sift_p_b and Path(sift_p_a).exists() and Path(sift_p_b).exists():
        data_a = np.load(sift_p_a)
        data_b = np.load(sift_p_b)
        pts_a = data_a["pts"]
        desc_a = data_a["descriptors"]
        pts_b = data_b["pts"]
        desc_b = data_b["descriptors"]

        inl, scale_change, sift_rot, total_good = match_sift_descriptors(
            pts_a=pts_a,
            desc_a=desc_a,
            pts_b=pts_b,
            desc_b=desc_b,
            ratio_test=float(fp_cfg.get("ratio_test", 0.80)),
            ransac_reproj_px=float(fp_cfg.get("ransac_reproj_px", 3.0)),
            max_scale_change=float(fp_cfg.get("max_scale_change", 0.10)),
            max_rotation_deg=float(fp_cfg.get("max_rotation_deg", 8.0)),
        )
        inliers = int(inl)

    # Decision logic based on config thresholds
    thresh_residual = fp_cfg.get("match_threshold_residual")
    thresh_inliers = fp_cfg.get("match_threshold_inliers")

    calibrated = (thresh_residual is not None) and (thresh_inliers is not None)

    match_decision = None
    if calibrated:
        res_pass = (score_residual is not None and score_residual >= float(thresh_residual))
        inl_pass = (inliers is not None and inliers >= int(thresh_inliers))
        if method == "residual":
            match_decision = res_pass
        elif method == "sift":
            match_decision = inl_pass
        else:  # "both"
            match_decision = (res_pass and inl_pass)

    # Primary score reporting
    primary_score = float(score_residual if score_residual is not None else (inliers or 0.0))

    return {
        "match": match_decision,
        "calibrated": calibrated,
        "score_residual": score_residual,
        "inliers": inliers,
        "score": primary_score,
        "method": method,
        "details": {
            "best_shift": [float(best_shift[0]), float(best_shift[1])],
            "best_rotation_deg": float(best_rot),
            "phase_response": float(phase_resp),
            "sift_scale_change": float(scale_change),
            "sift_rotation_deg": float(sift_rot),
            "sift_good_matches": int(total_good),
        },
    }
