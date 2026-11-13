"""
engine/fingerprint.py
Micro-texture residual + SIFT fabric fingerprint extraction (§7.8).

Goal: Capture the random micro-texture of a specific saree patch (natural yarn slubs,
hairiness, fibril patterns) rather than the periodic weave structure (which is shared
across all sarees of the same construction).

Pipeline:
  1. Input validation: NEVER upsample. If native_px_per_mm < scale_px_per_mm (10 px/mm),
     fails immediately with LOW_RES_FINGERPRINT.
  2. Multi-frame burst stacking (if burst provided).
  3. Glare detection to produce boolean glare_mask.
  4. Flat-field correction and zero-mean, unit-variance normalization.
     RULE: No CLAHE, no sharpening, no denoising.
  5. 2D harmonic lattice notch filter (scaled to peak FWHM) to completely eliminate periodic
     warp and weft weave harmonics and skirts.
  6. Canonical orientation normalisation: rotates the de-weaved image so warp threads are
     strictly vertical (axis-aligned).
  7. Slub-scale band-pass filter: keeps structures of roughly 0.5–5.0 mm.
  8. Downsample to fixed low scale (10 px/mm) using cv2.INTER_AREA (anti-aliased downsampling,
     robust to camera blur and sensor noise).
  9. Center crop to residual_size_px (160x160 px, 16x16 mm) to eliminate border effects.
 10. Save:
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
from engine.fft_grade import _find_two_peaks, _make_band_mask, _subpixel_refine


def _ensure_loaded_image(item: str | Path | np.ndarray) -> np.ndarray:
    """Load image from path if string/Path, or return array."""
    if isinstance(item, (str, Path)):
        p = str(item)
        img = cv2.imread(p)
        if img is None:
            raise ValueError(f"Could not load image: {p}")
        return img
    elif isinstance(item, np.ndarray):
        return item
    else:
        raise TypeError(f"Expected file path or numpy array, got {type(item)}")


def compute_weave_residual_and_orientation(
    window_gray: np.ndarray,
    px_per_mm: float,
    cfg: dict[str, Any],
) -> tuple[np.ndarray, float, np.ndarray]:
    """
    Remove periodic weave harmonics using a scaled 2D Fourier lattice notch filter,
    and compute warp thread orientation for canonical axis-alignment.

    Returns
    -------
    deweaver : 2D float32 array
    warp_angle_deg : float
    notch_mask : 2D boolean array
    """
    N = window_gray.shape[0]
    cy = cx = N // 2
    defect_cfg = cfg["defects"]
    fft_cfg = cfg["fft"]

    # Flat-field correction before FFT
    ff_sigma = float(fft_cfg.get("flatfield_sigma_px", 25.0))
    ff_img = flatfield_correct(window_gray, sigma_px=ff_sigma)

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

    p1 = peaks_res.get("peak1")
    p2 = peaks_res.get("peak2")

    yy, xx = np.ogrid[:N, :N]
    notch_mask = np.ones((N, N), dtype=bool)  # True = keep

    warp_angle_deg = 0.0
    if p1 and p2:
        kx1, ky1 = p1["kx"], p1["ky"]
        kx2, ky2 = p2["kx"], p2["ky"]

        # Identify warp peak: warp threads run vertically -> frequency peak on kx axis (|ky/kx| small)
        ratio1 = abs(ky1) / (abs(kx1) + 1e-9)
        ratio2 = abs(ky2) / (abs(kx2) + 1e-9)
        p_warp = p1 if ratio1 <= ratio2 else p2

        # Ensure warp frequency vector points into the positive kx half-plane
        w_kx = float(p_warp["kx"])
        w_ky = float(p_warp["ky"])
        if w_kx < 0 or (abs(w_kx) < 1e-6 and w_ky < 0):
            w_kx = -w_kx
            w_ky = -w_ky
        warp_angle_deg = math.degrees(math.atan2(w_ky, w_kx))

        # Notch radius scaled to peak FWHM (or window resolution)
        notch_r = max(int(round(N / px_per_mm * 0.35)), 6)
        n_harmonics = int(defect_cfg.get("harmonics", 6))

        # Notch 2D periodic weave lattice: h1*(kx1, ky1) + h2*(kx2, ky2)
        for h1 in range(-n_harmonics, n_harmonics + 1):
            for h2 in range(-n_harmonics, n_harmonics + 1):
                if h1 == 0 and h2 == 0:
                    continue
                hx = cx + h1 * kx1 + h2 * kx2
                hy = cy + h1 * ky1 + h2 * ky2
                if 0 <= hx < N and 0 <= hy < N:
                    d_sq = (xx.astype(float) - hx) ** 2 + (yy.astype(float) - hy) ** 2
                    notch_mask[d_sq <= notch_r ** 2] = False
    elif p1:
        kx1, ky1 = p1["kx"], p1["ky"]
        notch_r = max(int(round(N / px_per_mm * 0.35)), 6)
        for h in range(1, 7):
            for s in [+1, -1]:
                hx = cx + s * h * kx1
                hy = cy + s * h * ky1
                if 0 <= hx < N and 0 <= hy < N:
                    d_sq = (xx.astype(float) - hx) ** 2 + (yy.astype(float) - hy) ** 2
                    notch_mask[d_sq <= notch_r ** 2] = False

    # Inverse FFT of notched spectrum on unwindowed flat-field image
    F_complex = np.fft.fftshift(np.fft.fft2(ff_img.astype(np.float64)))
    F_complex[~notch_mask] = 0.0
    deweaver = np.real(np.fft.ifft2(np.fft.ifftshift(F_complex))).astype(np.float32)

    return deweaver, warp_angle_deg, notch_mask


def extract_fingerprint(
    image_paths_or_arrays: list[str | Path | np.ndarray] | np.ndarray,
    out_dir: str,
    cfg: dict[str, Any] | None = None,
    prefix: str = "fp",
    px_per_mm: float | None = None,
) -> dict[str, Any]:
    """
    Extract fabric fingerprint files (residual.npz and sift.npz) into out_dir.

    Parameters
    ----------
    image_paths_or_arrays : list of image paths/arrays (burst) or single 2D window array
    out_dir : directory where fingerprint npz files will be written
    cfg : optional configuration dict
    prefix : filename prefix (default 'fp')
    px_per_mm : optional scale of pre-rectified window

    Returns
    -------
    dict with keys 'residual_path' and 'sift_path'
    """
    if cfg is None:
        cfg = get_config()

    fp_cfg = cfg["fingerprint"]
    rect_cfg = cfg["rectify"]

    # Target low scale: 10 px/mm (below any phone camera native resolution)
    target_scale = float(fp_cfg.get("scale_px_per_mm", rect_cfg.get("fingerprint_px_per_mm", 10.0)))

    # 1. Determine input mode: direct window array or raw photo burst
    if isinstance(image_paths_or_arrays, np.ndarray) and image_paths_or_arrays.ndim == 2:
        effective_scale = px_per_mm or target_scale
        if effective_scale < target_scale:
            raise ValueError(f"LOW_RES_FINGERPRINT: native resolution {effective_scale:.1f} < target {target_scale:.1f} px/mm")
        stacked_window = image_paths_or_arrays.astype(np.float32)
        if stacked_window.max() > 1.0:
            stacked_window /= 255.0
    else:
        items = image_paths_or_arrays if isinstance(image_paths_or_arrays, list) else [image_paths_or_arrays]
        if not items:
            raise ValueError("No images provided for fingerprint extraction")

        rect_windows: list[np.ndarray] = []
        passing_cards = []
        raw_burst = []

        for it in items:
            raw = _ensure_loaded_image(it)
            if isinstance(raw, np.ndarray) and raw.ndim == 2 and raw.shape[0] < 1200:
                # Pre-rectified window float/uint8 2D array
                w_f32 = raw.astype(np.float32) / (255.0 if raw.dtype == np.uint8 else 1.0)
                rect_windows.append(w_f32)
            else:
                card_res = detect_and_rectify(raw, cfg)
                if card_res["ok"]:
                    passing_cards.append(card_res)
                    raw_burst.append(raw)
                else:
                    # If card detection failed, check if image is already a cropped window (e.g. from master-fabric renderer)
                    if raw.ndim == 3:
                        raw_gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
                    else:
                        raw_gray = raw
                    if raw_gray.shape[0] <= 1000 and raw_gray.shape[1] <= 1000:
                        w_f32 = raw_gray.astype(np.float32) / (255.0 if raw_gray.dtype == np.uint8 else 1.0)
                        rect_windows.append(w_f32)

        if not rect_windows and not passing_cards:
            raise ValueError("Could not rectify any card window for fingerprint extraction")

        if passing_cards:
            min_native = min(float(c.get("native_px_per_mm", 0.0)) for c in passing_cards)
            if min_native < target_scale:
                raise ValueError(
                    f"LOW_RES_FINGERPRINT: native resolution {min_native:.1f} < target {target_scale:.1f} px/mm"
                )
            canonical_scale = float(cfg["rectify"]["canonical_px_per_mm"])
            common_scale = min(min_native, canonical_scale)
            for raw in raw_burst:
                c_rect = detect_and_rectify(raw, cfg, target_px_per_mm=common_scale)
                if c_rect["ok"] and c_rect["window_gray"] is not None:
                    rect_windows.append(c_rect["window_gray"])
            effective_scale = common_scale
        else:
            effective_scale = px_per_mm or target_scale

        if len(rect_windows) > 1:
            stacked_window, _ = stack_burst_frames(rect_windows, top_k=int(cfg["enhance"]["stack_top_k"]))
        else:
            stacked_window = rect_windows[0]

    # Glare detection on raw window before any modification
    sat_level = int(cfg["quality"]["saturation_level"])
    _, raw_glare_mask, _ = mask_glare(stacked_window, saturation_level=sat_level)

    # 2. De-weave and extract orientation angle
    deweaver, warp_angle_deg, _ = compute_weave_residual_and_orientation(stacked_window, effective_scale, cfg)

    # 3. Canonical orientation normalisation: rotate so warp threads are strictly vertical
    H, W = deweaver.shape
    cy, cx = H / 2.0, W / 2.0
    if abs(warp_angle_deg) > 0.05:
        M_rot = cv2.getRotationMatrix2D((cx, cy), warp_angle_deg, 1.0)
        deweaver = cv2.warpAffine(deweaver, M_rot, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
        raw_glare_mask = cv2.warpAffine(
            raw_glare_mask.astype(np.uint8), M_rot, (W, H), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=1
        ) > 0

    # 4. Slub-scale band-pass filter: keep structures of roughly 0.5–5.0 mm
    min_feature_mm = float(fp_cfg.get("min_feature_mm", 0.5))
    max_feature_mm = float(fp_cfg.get("max_feature_mm", 5.0))
    sig_low = (min_feature_mm * effective_scale) / 3.0
    sig_high = (max_feature_mm * effective_scale) / 3.0

    low_p = cv2.GaussianBlur(deweaver, (0, 0), sigmaX=sig_low, sigmaY=sig_low)
    high_p = cv2.GaussianBlur(deweaver, (0, 0), sigmaX=sig_high, sigmaY=sig_high)
    bandpass = low_p - high_p

    # 5. Downsample to fixed low scale (10 px/mm) using cv2.INTER_AREA (anti-aliased)
    window_mm = float(cfg["card"]["window_mm"]) - 2 * 0.5  # 19.0 mm effective window
    out_dim = int(round(window_mm * target_scale))
    downsampled = cv2.resize(bandpass, (out_dim, out_dim), interpolation=cv2.INTER_AREA)
    down_glare = cv2.resize(raw_glare_mask.astype(np.uint8), (out_dim, out_dim), interpolation=cv2.INTER_NEAREST) > 0

    # 6. Center crop to residual_size_px (160x160 px = 16x16 mm)
    crop_sz = int(fp_cfg.get("residual_size_px", 160))
    cy_d, cx_d = out_dim // 2, out_dim // 2
    r_h = crop_sz // 2
    if out_dim < crop_sz:
        crop_res = cv2.resize(downsampled, (crop_sz, crop_sz), interpolation=cv2.INTER_LANCZOS4)
        crop_glare = cv2.resize(down_glare.astype(np.uint8), (crop_sz, crop_sz), interpolation=cv2.INTER_NEAREST) > 0
    else:
        crop_res = downsampled[cy_d - r_h : cy_d + r_h, cx_d - r_h : cx_d + r_h].copy()
        crop_glare = down_glare[cy_d - r_h : cy_d + r_h, cx_d - r_h : cx_d + r_h].copy()

    # Zero-mean, unit-variance normalization
    res_mean = float(np.mean(crop_res))
    res_std = float(np.std(crop_res))
    crop_res = (crop_res - res_mean) / (res_std + 1e-6)

    # 7. SIFT extraction on slub residual
    n_features = int(fp_cfg.get("sift_nfeatures", 500))
    sift = cv2.SIFT_create(nfeatures=n_features, contrastThreshold=0.02)
    u8_res = (np.clip((crop_res + 2.5) / 5.0, 0.0, 1.0) * 255.0).astype(np.uint8)
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

    # 8. Save .npz files
    os.makedirs(out_dir, exist_ok=True)
    residual_path = os.path.join(out_dir, f"{prefix}_residual.npz")
    sift_path = os.path.join(out_dir, f"{prefix}_sift.npz")

    np.savez_compressed(
        residual_path,
        residual=crop_res.astype(np.float16),
        glare_mask=crop_glare.astype(bool),
        scale_px_per_mm=float(target_scale),
        warp_angle_deg=float(warp_angle_deg),
    )

    np.savez_compressed(
        sift_path,
        pts=pts,
        descriptors=desc_arr,
        sizes=sizes,
        angles=angles,
        responses=responses,
        scale_px_per_mm=float(target_scale),
    )

    return {
        "residual_path": str(residual_path),
        "sift_path": str(sift_path),
    }
