"""
engine/card.py
Marker detection and perspective rectification for the TantSaakshi marker card.

Detects 4 ArUco markers (DICT_4X4_50) around the 20x20 mm window, computes the
physical homography (pixels -> mm), estimates tilt and native resolution,
and rectifies ONLY the measurement window to canonical scale.

Implements §7.1 of TANTSAAKSHI_ENGINE_SPEC.md.
"""
from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np


def detect_and_rectify(
    image: np.ndarray,
    cfg: dict[str, Any],
    target_px_per_mm: float | None = None,
) -> dict[str, Any]:
    """
    Detect the marker card in `image` and rectify the measurement window.

    Parameters
    ----------
    image : np.ndarray
        Input image in BGR or grayscale (uint8 or float32).
    cfg : dict
        Engine configuration dictionary.
    target_px_per_mm : float | None
        Target output resolution. If None, uses rectify.canonical_px_per_mm from config.
        Guaranteed NEVER to upsample beyond native resolution.

    Returns
    -------
    dict with keys:
        ok : bool
        code : str ("OK", "NO_CARD", "TOO_TILTED", "LOW_RES")
        reason : str
        window_gray : np.ndarray (float32 [0, 1]) | None
        window_color : np.ndarray (uint8 BGR) | None
        px_per_mm : float
        native_px_per_mm : float
        tilt_deg : float
        detected_marker_ids : list[int]
        corners_dict : dict[int, np.ndarray]
        homography_img_to_mm : np.ndarray | None
    """
    card_cfg = cfg["card"]
    rect_cfg = cfg["rectify"]
    qual_cfg = cfg["quality"]

    window_mm = float(card_cfg["window_mm"])
    marker_size_mm = float(card_cfg["marker_size_mm"])
    marker_gap_mm = float(card_cfg["marker_gap_mm"])
    margin_mm = float(card_cfg["margin_mm"])
    required_ids = list(card_cfg["marker_ids"])
    dict_name = str(card_cfg["aruco_dict"])

    # Normalise input to grayscale uint8 for detection
    if image.dtype != np.uint8:
        img_uint8 = (np.clip(image, 0.0, 1.0) * 255).astype(np.uint8)
    else:
        img_uint8 = image

    if len(img_uint8.shape) == 3 and img_uint8.shape[2] == 3:
        gray = cv2.cvtColor(img_uint8, cv2.COLOR_BGR2GRAY)
        color = img_uint8
    else:
        gray = img_uint8
        color = cv2.cvtColor(img_uint8, cv2.COLOR_GRAY2BGR)

    # ArUco detector setup
    dict_id = getattr(cv2.aruco, dict_name, cv2.aruco.DICT_4X4_50)
    aruco_dict = cv2.aruco.getPredefinedDictionary(dict_id)
    detector_params = cv2.aruco.DetectorParameters()
    detector_params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX

    detector = cv2.aruco.ArucoDetector(aruco_dict, detector_params)

    # Fast detection: downscale large images (e.g. >1500 px) for marker detection, then refine at full res
    max_dim = max(gray.shape)
    if max_dim > 1500:
        scale_f = 1500.0 / float(max_dim)
        gray_small = cv2.resize(gray, (0, 0), fx=scale_f, fy=scale_f, interpolation=cv2.INTER_AREA)
        corners_list_small, ids, _ = detector.detectMarkers(gray_small)
        if corners_list_small:
            corners_list = [c / scale_f for c in corners_list_small]
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.05)
            for idx in range(len(corners_list)):
                corners_list[idx] = cv2.cornerSubPix(
                    gray, np.float32(corners_list[idx]), winSize=(5, 5), zeroZone=(-1, -1), criteria=criteria
                )
        else:
            corners_list = []
    else:
        corners_list, ids, _ = detector.detectMarkers(gray)

    # Quality Gate 1: Check required markers
    detected_ids = [int(i) for i in ids.flatten()] if ids is not None else []
    corners_by_id: dict[int, np.ndarray] = {}
    if ids is not None:
        for idx, mid in enumerate(detected_ids):
            corners_by_id[mid] = corners_list[idx][0]  # shape (4, 2)

    missing_ids = [req for req in required_ids if req not in corners_by_id]
    if missing_ids:
        return {
            "ok": False,
            "code": "NO_CARD",
            "reason": "Show the whole card — missing markers: " + str(missing_ids),
            "window_gray": None,
            "window_color": None,
            "px_per_mm": 0.0,
            "native_px_per_mm": 0.0,
            "tilt_deg": 0.0,
            "detected_marker_ids": detected_ids,
            "corners_dict": corners_by_id,
            "homography_img_to_mm": None,
        }

    # Physical coordinates in millimeters on the card plane
    # Origin (0, 0) is at card top-left outer margin
    # Window spans [win_min, win_max] on both x and y
    win_min = margin_mm + marker_size_mm + marker_gap_mm
    win_max = win_min + window_mm
    card_size_mm = win_max + marker_gap_mm + marker_size_mm + margin_mm

    # Exact physical corners of each marker [TL, TR, BR, BL] in mm
    pts_mm_list = []
    pts_px_list = []

    marker_positions_mm = {
        0: (margin_mm, margin_mm),  # TL
        1: (card_size_mm - margin_mm - marker_size_mm, margin_mm),  # TR
        2: (card_size_mm - margin_mm - marker_size_mm, card_size_mm - margin_mm - marker_size_mm),  # BR
        3: (margin_mm, card_size_mm - margin_mm - marker_size_mm),  # BL
    }

    marker_px_lengths = []
    for mid in required_ids:
        mx, my = marker_positions_mm[mid]
        # ArUco corner order is TL, TR, BR, BL
        mm_corners = np.array([
            [mx, my],
            [mx + marker_size_mm, my],
            [mx + marker_size_mm, my + marker_size_mm],
            [mx, my + marker_size_mm],
        ], dtype=np.float32)

        px_corners = corners_by_id[mid]  # shape (4, 2)
        pts_mm_list.append(mm_corners)
        pts_px_list.append(px_corners)

        # Marker side lengths in image pixels
        for i in range(4):
            p_a = px_corners[i]
            p_b = px_corners[(i + 1) % 4]
            side_len = math.hypot(p_b[0] - p_a[0], p_b[1] - p_a[1])
            marker_px_lengths.append(side_len)

    all_pts_mm = np.vstack(pts_mm_list)
    all_pts_px = np.vstack(pts_px_list)

    # 4. Native resolution: average marker side in pixels / marker_size_mm
    avg_marker_side_px = float(np.mean(marker_px_lengths))
    native_px_per_mm = avg_marker_side_px / marker_size_mm

    # Compute homography (image pixels -> card mm)
    H_px_to_mm, _ = cv2.findHomography(all_pts_px, all_pts_mm, cv2.RANSAC)
    if H_px_to_mm is None:
        return {
            "ok": False,
            "code": "NO_CARD",
            "reason": "Could not compute planar homography from card markers",
            "window_gray": None,
            "window_color": None,
            "px_per_mm": 0.0,
            "native_px_per_mm": native_px_per_mm,
            "tilt_deg": 0.0,
            "detected_marker_ids": detected_ids,
            "corners_dict": corners_by_id,
            "homography_img_to_mm": None,
        }

    # 5. Tilt estimation from perspective foreshortening across marker centers
    c0 = np.mean(corners_by_id[0], axis=0)
    c1 = np.mean(corners_by_id[1], axis=0)
    c2 = np.mean(corners_by_id[2], axis=0)
    c3 = np.mean(corners_by_id[3], axis=0)

    # Physical distance in mm between opposite marker centers
    span_mm = float(card_size_mm - 2 * margin_mm - marker_size_mm)
    vx = (c1 - c0 + c2 - c3) / (2.0 * span_mm)
    vy = (c3 - c0 + c2 - c1) / (2.0 * span_mm)
    J = np.column_stack([vx, vy])
    s = np.linalg.svd(J, compute_uv=False)
    ratio = float(s[1] / (s[0] + 1e-6))
    tilt_rad = math.acos(np.clip(ratio, 0.0, 1.0))
    tilt_deg = math.degrees(tilt_rad)

    # Check Quality Gate 1 thresholds:
    max_tilt = float(qual_cfg["max_tilt_deg"])
    if tilt_deg > max_tilt:
        return {
            "ok": False,
            "code": "TOO_TILTED",
            "reason": f"Hold the phone flat over the card (tilt is {tilt_deg:.1f}°, max {max_tilt:.0f}°)",
            "window_gray": None,
            "window_color": None,
            "px_per_mm": 0.0,
            "native_px_per_mm": native_px_per_mm,
            "tilt_deg": tilt_deg,
            "detected_marker_ids": detected_ids,
            "corners_dict": corners_by_id,
            "homography_img_to_mm": H_px_to_mm,
        }

    min_res = float(qual_cfg["min_native_px_per_mm"])
    if native_px_per_mm < min_res:
        return {
            "ok": False,
            "code": "LOW_RES",
            "reason": f"Move closer — resolution {native_px_per_mm:.1f} px/mm is below {min_res:.0f} px/mm",
            "window_gray": None,
            "window_color": None,
            "px_per_mm": 0.0,
            "native_px_per_mm": native_px_per_mm,
            "tilt_deg": tilt_deg,
            "detected_marker_ids": detected_ids,
            "corners_dict": corners_by_id,
            "homography_img_to_mm": H_px_to_mm,
        }

    # 6. Target scale selection — rule §7.1: NEVER upsample beyond native resolution
    requested_scale = target_px_per_mm or float(rect_cfg["canonical_px_per_mm"])
    effective_scale = min(requested_scale, native_px_per_mm)

    # Crop 0.5 mm inside window border (§7.1 step 7) so card edge never appears
    border_crop_mm = 0.5
    crop_win_min = win_min + border_crop_mm
    crop_win_max = win_max - border_crop_mm
    effective_win_mm = crop_win_max - crop_win_min
    out_dim_px = int(round(effective_win_mm * effective_scale))

    # Build destination coordinates in rectified output pixels
    pts_rect_dst = np.float32([
        [0, 0],
        [out_dim_px, 0],
        [out_dim_px, out_dim_px],
        [0, out_dim_px],
    ])

    # Corresponding physical coordinates in card mm
    pts_rect_mm = np.float32([
        [crop_win_min, crop_win_min],
        [crop_win_max, crop_win_min],
        [crop_win_max, crop_win_max],
        [crop_win_min, crop_win_max],
    ])

    # Convert card mm points back to source image pixels using H_mm_to_px
    H_mm_to_px = np.linalg.inv(H_px_to_mm)
    pts_rect_mm_hom = np.hstack([pts_rect_mm, np.ones((4, 1), dtype=np.float32)])
    pts_src_px_hom = (H_mm_to_px @ pts_rect_mm_hom.T).T
    pts_src_px = (pts_src_px_hom[:, :2] / pts_src_px_hom[:, 2:3]).astype(np.float32)

    # Warp perspective directly from source image to canonical window
    M_warp = cv2.getPerspectiveTransform(pts_src_px, pts_rect_dst)

    window_gray_u8 = cv2.warpPerspective(
        gray, M_warp, (out_dim_px, out_dim_px),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101
    )
    window_color_u8 = cv2.warpPerspective(
        color, M_warp, (out_dim_px, out_dim_px),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101
    )

    window_gray_f32 = (window_gray_u8.astype(np.float32) / 255.0)

    return {
        "ok": True,
        "code": "OK",
        "reason": "",
        "window_gray": window_gray_f32,
        "window_color": window_color_u8,
        "px_per_mm": effective_scale,
        "native_px_per_mm": native_px_per_mm,
        "tilt_deg": tilt_deg,
        "detected_marker_ids": detected_ids,
        "corners_dict": corners_by_id,
        "homography_img_to_mm": H_px_to_mm,
    }
