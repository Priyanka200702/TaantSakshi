"""
engine/fingerprint.py
Micro-texture residual + SIFT fabric fingerprint extraction (§7.8).

Goal: Capture the random micro-texture of a specific saree patch (natural yarn slubs,
hairiness, fibril patterns) rather than the periodic weave structure (which is shared
across all sarees of the same construction).

Pipeline:
  1. Rectify window at fixed fingerprint_px_per_mm (25.0 px/mm across all phones).
  2. Multi-frame burst stacking (if burst provided).
  3. Glare detection to produce boolean glare_mask.
  4. Flat-field correction and zero-mean, unit-variance normalization.
     RULE: No CLAHE, no sharpening, no denoising here.
  5. 2D harmonic notch filter to remove periodic warp and weft weave grid -> residual.
  6. Center crop to residual_size_px (400x400) to eliminate boundary edge effects.
  7. Save:
     - Residual method: residual as float16 + glare_mask as bool in .npz
     - SIFT method: keypoints and descriptors masked by ~glare_mask in .npz
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from engine.card import detect_and_rectify
from engine.config import get_config
from engine.enhance import flatfield_correct, mask_glare, stack_burst_frames
from engine.fft_grade import _find_two_peaks, _make_band_mask


def _ensure_loaded_image(item: str | Path | np.ndarray) -> np.ndarray:
    """Load image from path if string/Path, or return array."""
    if isinstance(item, (str, Path)):
        p = str(item)
        img = cv2.imread(p)
        if img is None:
            raise FileNotFoundError(f"Could not load image: {p}")
        return img
    elif isinstance(item, np.ndarray):
        return item
    else:
        raise TypeError(f"Expected file path or numpy array, got {type(item)}")


def compute_weave_residual(
    window_gray: np.ndarray,
    px_per_mm: float,
    cfg: dict[str, Any],
    peaks: list[dict[str, Any]] | None = None,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """
    Remove periodic weave harmonics using a 2D Fourier notch filter.

    Parameters
    ----------
    window_gray : 2D float32 array
    px_per_mm : effective scale
    cfg : configuration dict
    peaks : optional pre-computed warp/weft peak locations

    Returns
    -------
    residual : 2D float32 array
    peaks : list of peak dicts
    """
    N = window_gray.shape[0]
    cx = cy = N // 2
    defect_cfg = cfg["defects"]
    fft_cfg = cfg["fft"]

    # Flat-field correction before FFT
    ff_sigma = float(cfg["enhance"]["flatfield_sigma_px"])
    ff_img = flatfield_correct(window_gray, sigma_px=ff_sigma)

    if peaks is None:
        # Detect warp and weft fundamental peaks
        hann = np.outer(np.hanning(N), np.hanning(N))
        F_mag = np.abs(np.fft.fftshift(np.fft.fft2(ff_img * hann)))
        band_min_k = N / float(fft_cfg["band_max_px_per_cycle"])
        band_max_k = N / float(fft_cfg["band_min_px_per_cycle"])
        dc_r = float(fft_cfg["dc_mask_radius"])
        band_mask = _make_band_mask(N, dc_r, band_min_k, band_max_k)
        peaks_res = _find_two_peaks(
            F=F_mag,
            band_mask=band_mask,
            N=N,
            excl_deg=float(fft_cfg["peak_exclusion_deg"]),
            perp_tol=float(fft_cfg.get("expect_perpendicular_tol_deg", 15)),
        )
        peaks = []
        if peaks_res.get("peak1"):
            peaks.append(peaks_res["peak1"])
        if peaks_res.get("peak2"):
            peaks.append(peaks_res["peak2"])

    # 2D Notch mask
    notch_r = int(defect_cfg["notch_radius"])
    n_harmonics = int(defect_cfg["harmonics"])
    notch_mask = np.ones((N, N), dtype=bool)  # True = keep

    yy, xx = np.ogrid[:N, :N]

    if len(peaks) >= 2:
        p1, p2 = peaks[0], peaks[1]
        kx1, ky1 = p1["kx"], p1["ky"]
        kx2, ky2 = p2["kx"], p2["ky"]
        # Notch 2D periodic weave grid: h1*(kx1,ky1) + h2*(kx2,ky2)
        for h1 in range(-n_harmonics, n_harmonics + 1):
            for h2 in range(-n_harmonics, n_harmonics + 1):
                if h1 == 0 and h2 == 0:
                    continue
                centre_x = cx + h1 * kx1 + h2 * kx2
                centre_y = cy + h1 * ky1 + h2 * ky2
                if 0 <= centre_x < N and 0 <= centre_y < N:
                    d_sq = (xx.astype(float) - centre_x) ** 2 + (yy.astype(float) - centre_y) ** 2
                    notch_mask[d_sq <= notch_r ** 2] = False
    elif len(peaks) == 1:
        pk = peaks[0]
        kx, ky = pk["kx"], pk["ky"]
        for h in range(1, n_harmonics + 1):
            for sign in [+1, -1]:
                centre_x = cx + sign * h * kx
                centre_y = cy + sign * h * ky
                if 0 <= centre_x < N and 0 <= centre_y < N:
                    d_sq = (xx.astype(float) - centre_x) ** 2 + (yy.astype(float) - centre_y) ** 2
                    notch_mask[d_sq <= notch_r ** 2] = False

    # Inverse FFT of notched spectrum on unwindowed image to preserve spatial fidelity
    F_complex = np.fft.fftshift(np.fft.fft2(ff_img.astype(np.float64)))
    F_complex[~notch_mask] = 0.0
    residual = np.real(np.fft.ifft2(np.fft.ifftshift(F_complex))).astype(np.float32)

    return residual, peaks


def extract_fingerprint(
    image_paths_or_arrays: list[str | Path | np.ndarray] | np.ndarray,
    out_dir: str,
    cfg: dict[str, Any] | None = None,
    prefix: str = "fp",
) -> dict[str, str]:
    """
    Extract fabric fingerprint files (residual.npz and sift.npz) into out_dir.

    Parameters
    ----------
    image_paths_or_arrays : list of image paths/arrays (burst) or single 2D window array
    out_dir : directory where fingerprint npz files will be written
    cfg : optional configuration dict
    prefix : filename prefix (default 'fp')

    Returns
    -------
    dict with keys 'residual_path' and 'sift_path'
    """
    if cfg is None:
        cfg = get_config()

    fp_cfg = cfg["fingerprint"]
    rect_cfg = cfg["rectify"]
    target_scale = float(rect_cfg["fingerprint_px_per_mm"])

    # Determine input mode: direct window array or raw photo burst
    if isinstance(image_paths_or_arrays, np.ndarray) and image_paths_or_arrays.ndim == 2:
        # Already a rectified window
        stacked_window = image_paths_or_arrays.astype(np.float32)
        if stacked_window.max() > 1.0:
            stacked_window /= 255.0
        effective_scale = target_scale
    else:
        items = image_paths_or_arrays if isinstance(image_paths_or_arrays, list) else [image_paths_or_arrays]
        if not items:
            raise ValueError("No images provided for fingerprint extraction")

        rect_windows: list[np.ndarray] = []
        effective_scale = target_scale

        for it in items:
            raw = _ensure_loaded_image(it)
            if raw.ndim == 2 and raw.shape[0] < 1200:
                # Pre-rectified window frame
                w_f32 = raw.astype(np.float32) / (255.0 if raw.dtype == np.uint8 else 1.0)
                rect_windows.append(w_f32)
            else:
                card_res = detect_and_rectify(raw, cfg, target_px_per_mm=target_scale)
                if card_res["ok"] and card_res["window_gray"] is not None:
                    rect_windows.append(card_res["window_gray"])
                    effective_scale = card_res["px_per_mm"]

        if not rect_windows:
            raise RuntimeError("Could not rectify card window for fingerprint extraction")

        if len(rect_windows) > 1:
            stacked_window, _ = stack_burst_frames(rect_windows, top_k=int(cfg["enhance"]["stack_top_k"]))
        else:
            stacked_window = rect_windows[0]

    # Glare detection on raw window before any modification
    sat_level = int(cfg["quality"]["saturation_level"])
    _, raw_glare_mask, _ = mask_glare(stacked_window, saturation_level=sat_level)

    # Compute weave residual
    residual, peaks = compute_weave_residual(stacked_window, effective_scale, cfg)

    # Center crop to residual_size_px (400x400)
    res_sz = int(fp_cfg["residual_size_px"])
    H, W = residual.shape
    cy, cx = H // 2, W // 2
    r_half = res_sz // 2

    # Handle cases where rectified window is slightly smaller than target
    if H < res_sz or W < res_sz:
        crop_res = cv2.resize(residual, (res_sz, res_sz), interpolation=cv2.INTER_LANCZOS4)
        crop_glare = cv2.resize(raw_glare_mask.astype(np.uint8), (res_sz, res_sz), interpolation=cv2.INTER_NEAREST) > 0
    else:
        crop_res = residual[cy - r_half : cy + r_half, cx - r_half : cx + r_half].copy()
        crop_glare = raw_glare_mask[cy - r_half : cy + r_half, cx - r_half : cx + r_half].copy()

    # Zero-mean, unit-variance normalization on the crop
    res_mean = float(np.mean(crop_res))
    res_std = float(np.std(crop_res))
    crop_res = (crop_res - res_mean) / (res_std + 1e-6)

    # -------------------------------------------------------------------------
    # SIFT extraction on the residual
    # -------------------------------------------------------------------------
    n_features = int(fp_cfg["sift_nfeatures"])
    sift = cv2.SIFT_create(nfeatures=n_features)

    # Scale normalized residual [-3, +3] to uint8 [0, 255]
    u8_res = (np.clip((crop_res + 3.0) / 6.0, 0.0, 1.0) * 255.0).astype(np.uint8)

    # Mask out glare pixels so no keypoints originate from glare artifacts
    sift_mask = (~crop_glare).astype(np.uint8) * 255

    keypoints, descriptors = sift.detectAndCompute(u8_res, mask=sift_mask)

    if keypoints:
        pts = np.float32([kp.pt for kp in keypoints])
        sizes = np.float32([kp.size for kp in keypoints])
        angles = np.float32([kp.angle for kp in keypoints])
        responses = np.float32([kp.response for kp in keypoints])
        desc_arr = descriptors if descriptors is not None else np.empty((0, 128), dtype=np.uint8)
    else:
        pts = np.empty((0, 2), dtype=np.float32)
        sizes = np.empty((0,), dtype=np.float32)
        angles = np.empty((0,), dtype=np.float32)
        responses = np.empty((0,), dtype=np.float32)
        desc_arr = np.empty((0, 128), dtype=np.uint8)

    # -------------------------------------------------------------------------
    # Save fingerprint files (.npz)
    # -------------------------------------------------------------------------
    os.makedirs(out_dir, exist_ok=True)
    residual_path = os.path.join(out_dir, f"{prefix}_residual.npz")
    sift_path = os.path.join(out_dir, f"{prefix}_sift.npz")

    np.savez_compressed(
        residual_path,
        residual=crop_res.astype(np.float16),
        glare_mask=crop_glare.astype(bool),
        scale_px_per_mm=float(effective_scale),
    )

    np.savez_compressed(
        sift_path,
        pts=pts,
        descriptors=desc_arr,
        sizes=sizes,
        angles=angles,
        responses=responses,
        scale_px_per_mm=float(effective_scale),
    )

    return {
        "residual_path": str(residual_path),
        "sift_path": str(sift_path),
    }
