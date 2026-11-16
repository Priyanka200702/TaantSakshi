"""
engine/fft_grade.py
Thread density measurement, irregularity, defect detection, and provisional grade
via 2D FFT analysis of a rectified fabric window.

Input:  float32 grayscale OR colour (H×W×3) window array.
        px_per_mm: scale of the input image.
        cfg: engine config dict (from engine.config.get_config()).

Output: dict with all measurements plus pass/fail codes.

§7.3 Pre-processing → §7.4 Thread density → §7.5 Irregularity → §7.6 Defects → §7.7 Grade

Tasks implemented:
  Task 1 – Thread band in physical units (min_tpi: 20, max_tpi: 200).
  Task 2 – Expected-axis wedge search (expected_axis_tol_deg: 20) around 0° and 90°.
  Task 3 – Validation: perp within 90°±15°, 1-D cross-check within 5%, per-peak SNR ≥ min_peak_snr.
           Failure returns ok=False, code=WEAVE_UNCLEAR, with English and Bengali reasons.
  Task 4 – Fingerprint rotation by measured angle only if validation passed; else 0°.
  Task 6a/6c – Highest local thread contrast channel selection; reported in quality metrics.
  Task 6b – Local contrast-normalised DESIGN_AREA ratio.
  Task 7 – spectrum_peaks.png with TPI band and search wedges; fingerprint_residual.png in debug_dir.
"""
from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np
from scipy import ndimage as ndi


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_fft_grade(
    window: np.ndarray,
    px_per_mm: float,
    cfg: dict[str, Any],
    debug_dir: str | None = None,
) -> dict[str, Any]:
    """
    Analyse a rectified fabric window image.

    Parameters
    ----------
    window : float32 array, values in [0, 1].
             Shape: (H, W) grayscale OR (H, W, 3) colour.
    px_per_mm : scale of `window`.
    cfg : full engine config dict.
    debug_dir : if given, save log-spectrum PNG and peak overlay here.

    Returns
    -------
    dict with keys: ok, code, reason, ends_per_inch, picks_per_inch,
                    warp_angle_deg, weft_angle_deg,
                    px_per_thread, irregularity, defects, grade,
                    grade_provisional, quality, timings_ms, ...
    """
    import time

    t0 = time.perf_counter()

    fft_cfg     = cfg["fft"]
    defect_cfg  = cfg["defects"]
    grade_cfg   = cfg["grade"]
    quality_cfg = cfg["quality"]

    # ---- Task 6a: select channel with highest local thread contrast ----------
    img_work, channel_used = _select_best_channel(window)

    # ---- §7.3 Pre-processing ------------------------------------------------
    img_flat, img_hann = _preprocess(img_work, fft_cfg)
    N = img_hann.shape[0]

    # ---- §7.4 FFT peak finding ----------------------------------------------
    F = _compute_spectrum(img_hann)

    # Task 1: convert physical TPI limits to cycles per window (k-space radius)
    band_min_k_classic = N / float(fft_cfg["band_max_px_per_cycle"])
    band_max_k_classic = N / float(fft_cfg["band_min_px_per_cycle"])
    dc_r               = float(fft_cfg["dc_mask_radius"])

    min_tpi = float(fft_cfg.get("min_tpi", 20.0))
    max_tpi = float(fft_cfg.get("max_tpi", 200.0))

    window_mm = (N / px_per_mm) if px_per_mm > 0 else 20.0
    k_at_min_tpi = (min_tpi / 25.4) * window_mm
    k_at_max_tpi = (max_tpi / 25.4) * window_mm

    thread_band_min_k = max(band_min_k_classic, k_at_min_tpi)
    thread_band_max_k = min(band_max_k_classic, k_at_max_tpi)

    full_band_mask = _make_band_mask(N, dc_r, band_min_k_classic, band_max_k_classic)
    thread_band_mask = _make_band_mask(N, dc_r, thread_band_min_k, thread_band_max_k)

    axis_tol = float(fft_cfg.get("expected_axis_tol_deg", 20.0))
    cross_check_tol = float(fft_cfg.get("cross_check_tol", 0.05))
    min_peak_snr = float(quality_cfg["min_peak_snr"])

    # Task 2 & 3: Find peaks with axis-aware search and validate
    peak_result = _find_and_validate_peaks(
        F=F,
        img_flat=img_flat,
        thread_band_mask=thread_band_mask,
        N=N,
        px_per_mm=px_per_mm,
        axis_tol=axis_tol,
        perp_tol=float(fft_cfg.get("expect_perpendicular_tol_deg", 15.0)),
        min_peak_snr=min_peak_snr,
        cross_check_tol=cross_check_tol,
        min_tpi=min_tpi,
        max_tpi=max_tpi,
    )

    if peak_result["code"] != "OK":
        return _fail(peak_result["code"], peak_result["reason"], extra={
            "reason_bn": peak_result.get("reason_bn", "বুনন অস্পষ্ট: কার্ডটি অন্য একটি সাদামাটা জায়গায় সরান"),
            "quality": {
                "peak_snr_warp": peak_result.get("snr1", 0.0),
                "peak_snr_weft": peak_result.get("snr2", 0.0),
                "channel_used": channel_used,
            },
            "timings_ms": {"total": (time.perf_counter() - t0) * 1000},
        })

    p1 = peak_result["peak1"]
    p2 = peak_result["peak2"]
    p_warp, p_weft = _assign_warp_weft(p1, p2)

    # ---- Compute thread counts ----------------------------------------------
    def _counts(peak: dict) -> dict:
        kx, ky = peak["kx"], peak["ky"]
        k = math.hypot(kx, ky)
        px_per_thread = N / k if k > 0 else float("inf")
        threads_per_mm = k / window_mm if window_mm > 0 else 0.0
        threads_per_inch = threads_per_mm * 25.4
        angle_deg = math.degrees(math.atan2(ky, kx))
        return dict(
            k=k,
            px_per_thread=px_per_thread,
            threads_per_mm=threads_per_mm,
            threads_per_inch=threads_per_inch,
            angle_deg=angle_deg,
        )

    warp_c = _counts(p_warp)
    weft_c = _counts(p_weft)

    # ---- Quality: aliasing check (§7.2) ------------------------------------
    min_ppt = quality_cfg["min_px_per_thread"]
    if warp_c["px_per_thread"] < min_ppt or weft_c["px_per_thread"] < min_ppt:
        return _fail("ALIASING", "Move closer — threads too small to count reliably", extra={
            "quality": {
                "warp_px_per_thread": warp_c["px_per_thread"],
                "weft_px_per_thread": weft_c["px_per_thread"],
                "channel_used": channel_used,
            },
            "timings_ms": {"total": (time.perf_counter() - t0) * 1000},
        })

    nyquist_k = N / 2
    if p_warp["k"] > 0.4 * nyquist_k or p_weft["k"] > 0.4 * nyquist_k:
        return _fail("ALIASING", "Move closer — thread frequency too close to Nyquist", extra={
            "quality": {"channel_used": channel_used},
            "timings_ms": {"total": (time.perf_counter() - t0) * 1000},
        })

    if px_per_mm > 0:
        max_tpi_resolvable = px_per_mm * 25.4 / min_ppt
        if warp_c["threads_per_inch"] > max_tpi_resolvable or weft_c["threads_per_inch"] > max_tpi_resolvable:
            return _fail("ALIASING", "Move closer — not enough pixels per thread at this scale", extra={
                "quality": {"channel_used": channel_used},
                "timings_ms": {"total": (time.perf_counter() - t0) * 1000},
            })

    # Task 4: validation passed -> rotation angle is measured thread angle
    rotation_angle_deg = warp_c["angle_deg"]
    rotation_source = "measured"

    # ---- §7.5 Irregularity --------------------------------------------------
    fwhm0 = float(fft_cfg.get("fwhm0", 2.25))
    irr_warp = _measure_irregularity(F, p_warp, N, fwhm0=fwhm0)
    irr_weft = _measure_irregularity(F, p_weft, N, fwhm0=fwhm0)

    # ---- §7.6 Defects -------------------------------------------------------
    residual, defect_result = _detect_defects(
        img_flat, [p_warp, p_weft], N, defect_cfg, px_per_mm=px_per_mm, debug_dir=debug_dir
    )

    # ---- §7.7 Grade ---------------------------------------------------------
    overall_irregularity = max(irr_warp["irregularity"], irr_weft["irregularity"])
    grade_str = _compute_grade(overall_irregularity, defect_result["area_fraction"], grade_cfg)

    snr_warp = p_warp.get("snr", float("nan"))
    snr_weft = p_weft.get("snr", float("nan"))

    # ---- Debug: spectrum image (Task 7) -------------------------------------
    if debug_dir is not None:
        _save_debug_spectrum(
            F=F,
            band_mask=full_band_mask,
            peaks=[p_warp, p_weft],
            band_min_k=band_min_k_classic,
            band_max_k=band_max_k_classic,
            dc_r=dc_r,
            debug_dir=debug_dir,
            N=N,
            thread_band_min_k=thread_band_min_k,
            thread_band_max_k=thread_band_max_k,
            axis_tol=axis_tol,
            px_per_mm=px_per_mm,
        )

    t_total = (time.perf_counter() - t0) * 1000

    return {
        "ok": True,
        "code": "OK",
        "reason": "",
        "ends_per_inch": warp_c["threads_per_inch"],
        "picks_per_inch": weft_c["threads_per_inch"],
        "warp_angle_deg": warp_c["angle_deg"],
        "weft_angle_deg": weft_c["angle_deg"],
        "rotation_angle_deg": rotation_angle_deg,
        "rotation_source": rotation_source,
        "px_per_thread": {
            "warp": warp_c["px_per_thread"],
            "weft": weft_c["px_per_thread"],
        },
        "irregularity": {
            "warp": irr_warp["irregularity"],
            "weft": irr_weft["irregularity"],
        },
        "defects": defect_result,
        "grade": grade_str,
        "grade_provisional": True,
        "quality": {
            "peak_snr_warp": snr_warp,
            "peak_snr_weft": snr_weft,
            "warp_px_per_thread": warp_c["px_per_thread"],
            "weft_px_per_thread": weft_c["px_per_thread"],
            "warp_energy_concentration": irr_warp["energy_concentration"],
            "weft_energy_concentration": irr_weft["energy_concentration"],
            "channel_used": channel_used,
        },
        "timings_ms": {"fft_grade": t_total},
        "_peaks": {"warp": p_warp, "weft": p_weft},
    }


# ---------------------------------------------------------------------------
# Task 6a: Best-contrast channel selection
# ---------------------------------------------------------------------------

def _select_best_channel(window: np.ndarray) -> tuple[np.ndarray, str]:
    """
    Select the channel with highest local thread contrast.
    Uses high-pass / bandpass standard deviation at yarn scale (sigma 1-3 px).
    Returns (single-channel float32 array, channel_name_string).
    """
    if window.ndim == 2:
        return window.astype(np.float32), "gray"

    channel_names = ["blue", "green", "red"]
    best_contrast = -1.0
    best_ch = 0

    for c in range(window.shape[2]):
        ch = window[:, :, c].astype(np.float32)
        # Bandpass filter at thread scale
        b1 = cv2.GaussianBlur(ch, (0, 0), 1.0)
        b2 = cv2.GaussianBlur(ch, (0, 0), 3.0)
        hp = b1 - b2
        contrast = float(np.std(hp))
        if contrast > best_contrast:
            best_contrast = contrast
            best_ch = c

    return window[:, :, best_ch].astype(np.float32), channel_names[best_ch]


# ---------------------------------------------------------------------------
# §7.3 Pre-processing
# ---------------------------------------------------------------------------

def _preprocess(window: np.ndarray, fft_cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    """Flat-field correction + Hann windowing."""
    img = window.astype(np.float32)
    H, W = img.shape[:2]
    N = min(H, W)
    img = img[:N, :N]

    sigma = float(fft_cfg.get("flatfield_sigma_px", 25.0)) if isinstance(fft_cfg, dict) else 25.0
    blur = cv2.GaussianBlur(img, (0, 0), sigma)
    blur = np.where(blur < 1e-6, 1e-6, blur)
    img_flat = img / blur
    img_flat = img_flat - img_flat.mean()

    hann_1d = np.hanning(N).astype(np.float32)
    hann_2d = np.outer(hann_1d, hann_1d)
    img_hann = img_flat * hann_2d

    return img_flat.astype(np.float32), img_hann.astype(np.float32)


# ---------------------------------------------------------------------------
# §7.4 FFT spectrum
# ---------------------------------------------------------------------------

def _compute_spectrum(img: np.ndarray) -> np.ndarray:
    """Return the magnitude spectrum (fftshift applied)."""
    F_complex = np.fft.fft2(img.astype(np.float64))
    F_shift = np.fft.fftshift(F_complex)
    return np.abs(F_shift).astype(np.float64)


def _make_band_mask(N: int, dc_r: float, band_min_k: float, band_max_k: float) -> np.ndarray:
    """Upper half-plane band mask."""
    cy = cx = N // 2
    yy, xx = np.ogrid[:N, :N]
    r = np.sqrt((xx - cx).astype(float) ** 2 + (yy - cy).astype(float) ** 2)
    ky = yy - cy

    mask = (
        (r >= band_min_k)
        & (r <= band_max_k)
        & (r > dc_r)
        & (ky.astype(float) >= 0)
    )
    return mask.astype(bool)


# ---------------------------------------------------------------------------
# Task 2 & 3: Axis-aware peak finding with full validation suite
# ---------------------------------------------------------------------------

def _find_and_validate_peaks(
    F: np.ndarray,
    img_flat: np.ndarray,
    thread_band_mask: np.ndarray,
    N: int,
    px_per_mm: float,
    axis_tol: float,
    perp_tol: float,
    min_peak_snr: float,
    cross_check_tol: float,
    min_tpi: float,
    max_tpi: float,
) -> dict:
    """
    Search wedges around 0° (warp, kx) and 90° (weft, ky) first.
    Validate candidate pairs against:
      a) perpendicularity (90° ± 15°)
      b) 1-D cross-check agreement within cross_check_tol (5%)
      c) peak SNR ≥ min_peak_snr
    """
    cy = cx = N // 2
    window_mm = (N / px_per_mm) if px_per_mm > 0 else 20.0

    band_vals = F[thread_band_mask]
    if band_vals.size == 0 or np.max(band_vals) == 0.0:
        return {"code": "NO_WEAVE", "reason": "No thread peaks found in spectrum"}
    med_band = float(np.median(band_vals)) if band_vals.size > 0 else 1.0

    wedge_warp = _angle_wedge_mask(N, cy, cx, center_deg=0.0, half_width_deg=axis_tol)
    wedge_weft = _angle_wedge_mask(N, cy, cx, center_deg=90.0, half_width_deg=axis_tol)

    warp_cands = _extract_local_peaks(F, thread_band_mask & wedge_warp, cy, cx, N, top_k=6)
    weft_cands = _extract_local_peaks(F, thread_band_mask & wedge_weft, cy, cx, N, top_k=6)

    # In plain handloom weaves with heavy slubs, a 2-yarn repeat / slub occurs at k/2 (< 35 tpi).
    # If a peak is at sub-harmonic frequency and its 2x harmonic exists in F, resolve to true thread frequency.
    warp_cands = [_resolve_subharmonic(pk, F, cy, cx, N, window_mm) for pk in warp_cands]
    weft_cands = [_resolve_subharmonic(pk, F, cy, cx, N, window_mm) for pk in weft_cands]

    # Deduplicate candidates within 2 pixels
    warp_cands = _dedup_peaks(warp_cands)
    weft_cands = _dedup_peaks(weft_cands)

    # Sort candidates by peak value
    warp_cands.sort(key=lambda p: -p.get("val", 0.0))
    weft_cands.sort(key=lambda p: -p.get("val", 0.0))

    # Evaluate candidate pairs
    for pw in warp_cands:
        for pwt in weft_cands:
            # a) Check perpendicularity (90° ± 15°)
            ang_w = pw["angle_deg"]
            ang_wt = pwt["angle_deg"]
            diff = abs(ang_wt - ang_w) % 180
            if diff > 90:
                diff = 180 - diff
            perp_err = abs(90 - diff)
            if perp_err > perp_tol:
                continue

            # c) Check peak SNR
            snr_w = pw.get("val", F[int(round(cy + pw["ky"])), int(round(cx + pw["kx"]))]) / (med_band + 1e-10)
            snr_wt = pwt.get("val", F[int(round(cy + pwt["ky"])), int(round(cx + pwt["kx"]))]) / (med_band + 1e-10)
            if snr_w < min_peak_snr or snr_wt < min_peak_snr:
                continue

            # b) Check 1-D projection cross-check
            k1_w = _compute_1d_projection_k(img_flat, ang_w, "warp", N, px_per_mm, min_tpi, max_tpi)
            if abs(k1_w - pw["k"]) / pw["k"] > cross_check_tol:
                continue

            k1_wt = _compute_1d_projection_k(img_flat, ang_wt, "weft", N, px_per_mm, min_tpi, max_tpi)
            if abs(k1_wt - pwt["k"]) / pwt["k"] > cross_check_tol:
                continue

            # Validation passed!
            pw["snr"] = float(snr_w)
            pwt["snr"] = float(snr_wt)
            return {
                "code": "OK",
                "reason": "",
                "peak1": pw,
                "peak2": pwt,
                "snr": min(snr_w, snr_wt),
                "snr1": snr_w,
                "snr2": snr_wt,
            }

    # Fallback: global search for unaligned weaves
    global_res = _find_two_peaks_global(F, thread_band_mask, N, cy, cx, excl_deg=25.0, perp_tol=perp_tol, median_band=med_band)
    if global_res["code"] == "OK":
        p1, p2 = global_res["peak1"], global_res["peak2"]
        # Validate global peaks
        diff = abs(p2["angle_deg"] - p1["angle_deg"]) % 180
        if diff > 90: diff = 180 - diff
        if abs(90 - diff) <= perp_tol:
            snr1 = p1.get("snr", 0.0)
            snr2 = p2.get("snr", 0.0)
            if snr1 >= min_peak_snr and snr2 >= min_peak_snr:
                k1_1 = _compute_1d_projection_k(img_flat, p1["angle_deg"], "warp", N, px_per_mm, min_tpi, max_tpi)
                k1_2 = _compute_1d_projection_k(img_flat, p2["angle_deg"], "weft", N, px_per_mm, min_tpi, max_tpi)
                if abs(k1_1 - p1["k"]) / p1["k"] <= cross_check_tol and abs(k1_2 - p2["k"]) / p2["k"] <= cross_check_tol:
                    return global_res

    # Validation failed -> WEAVE_UNCLEAR
    return {
        "code": "WEAVE_UNCLEAR",
        "reason": "Weave unclear: move the card to another plain spot",
        "reason_bn": "বুনন অস্পষ্ট: কার্ডটি অন্য একটি সাদামাটা জায়গায় সরান",
    }


def _extract_local_peaks(F: np.ndarray, mask: np.ndarray, cy: int, cx: int, N: int, top_k: int = 6) -> list[dict]:
    """Find top_k local maxima in F within mask."""
    F_m = F.copy()
    F_m[~mask] = 0.0
    peaks = []
    yy, xx = np.ogrid[:N, :N]

    for _ in range(top_k):
        idx = np.argmax(F_m)
        r, c = np.unravel_index(idx, F_m.shape)
        val = float(F_m[r, c])
        if val <= 0.0:
            break
        pk = _subpixel_refine(F, r, c, cy, cx)
        pk["val"] = val
        peaks.append(pk)
        # Suppress local neighbourhood
        F_m[(yy - r) ** 2 + (xx - c) ** 2 <= 25] = 0.0

    return peaks


def _resolve_subharmonic(pk: dict, F: np.ndarray, cy: int, cx: int, N: int, window_mm: float) -> dict:
    """
    If peak has tpi < 33, check if 2x thread harmonic exists in F.
    In plain weaves, weave repeat occurs at k/2 (sub-harmonic) due to alternating over/under yarn contrast.
    """
    tpi = (pk["k"] / window_mm) * 25.4
    if tpi < 35.0:
        kx2 = pk["kx"] * 2.0
        ky2 = pk["ky"] * 2.0
        r2 = int(round(cy + ky2))
        c2 = int(round(cx + kx2))
        if 2 <= r2 < N - 2 and 2 <= c2 < N - 2:
            sub = F[r2 - 2:r2 + 3, c2 - 2:c2 + 3]
            peak_val = pk.get("val", 1.0)
            if np.max(sub) > 0.15 * peak_val:
                max_loc = np.unravel_index(np.argmax(sub), sub.shape)
                best_r = r2 - 2 + max_loc[0]
                best_c = c2 - 2 + max_loc[1]
                p2 = _subpixel_refine(F, best_r, best_c, cy, cx)
                p2["val"] = float(F[best_r, best_c])
                return p2
    return pk


def _dedup_peaks(peaks: list[dict]) -> list[dict]:
    """Deduplicate peaks within 2 cycles of each other."""
    res = []
    for pk in peaks:
        if not any(math.hypot(pk["kx"] - q["kx"], pk["ky"] - q["ky"]) < 2.0 for q in res):
            res.append(pk)
    return res


# ---------------------------------------------------------------------------
# Task 3b: 1-D projection onto thread axis
# ---------------------------------------------------------------------------

def _compute_1d_projection_k(
    img_flat: np.ndarray,
    peak_angle_deg: float,
    axis_type: str,
    N: int,
    px_per_mm: float,
    min_tpi: float,
    max_tpi: float,
) -> float:
    """
    Project window onto thread spacing axis by integrating along thread lines.
    Aligns thread lines to axis, averages across thread length, and extracts dominant 1-D period.
    """
    if axis_type == "warp":
        # Warp threads run vertically. Peak is near kx axis (0° or 180°).
        rot_deg = peak_angle_deg if abs(peak_angle_deg) <= 45 else (
            peak_angle_deg - 180 if peak_angle_deg > 0 else peak_angle_deg + 180
        )
        M = cv2.getRotationMatrix2D((N / 2.0, N / 2.0), rot_deg, 1.0)
        rot = cv2.warpAffine(img_flat, M, (N, N), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
        margin = max(int(N * 0.08), 8)
        crop = rot[margin:-margin, margin:-margin]
        proj = np.mean(crop, axis=0)  # Average along vertical thread lines
    else:
        # Weft threads run horizontally. Peak is near ky axis (90°).
        rot_deg = peak_angle_deg - 90.0
        M = cv2.getRotationMatrix2D((N / 2.0, N / 2.0), rot_deg, 1.0)
        rot = cv2.warpAffine(img_flat, M, (N, N), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
        margin = max(int(N * 0.08), 8)
        crop = rot[margin:-margin, margin:-margin]
        proj = np.mean(crop, axis=1)  # Average along horizontal thread lines

    hann = np.hanning(len(proj))
    pf = np.abs(np.fft.rfft((proj - proj.mean()) * hann))

    k_scale = N / len(proj)
    window_mm = (N / px_per_mm) if px_per_mm > 0 else 20.0
    k_min = (min_tpi / 25.4) * window_mm
    k_max = (max_tpi / 25.4) * window_mm

    i_min = max(int(math.floor(k_min / k_scale)), 1)
    i_max = min(int(math.ceil(k_max / k_scale)), len(pf) - 1)

    if i_min >= i_max:
        return 0.0

    sub = pf[i_min:i_max + 1]
    best_i = np.argmax(sub) + i_min

    # Parabolic sub-sample refinement
    if 1 <= best_i < len(pf) - 1:
        y0, y1, y2 = pf[best_i - 1], pf[best_i], pf[best_i + 1]
        denom = y0 - 2 * y1 + y2
        delta = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
        best_i = best_i + delta

    return float(best_i * k_scale)


# ---------------------------------------------------------------------------
# Global peak finding fallback
# ---------------------------------------------------------------------------

def _find_two_peaks_global(
    F: np.ndarray,
    band_mask: np.ndarray,
    N: int,
    cy: int, cx: int,
    excl_deg: float,
    perp_tol: float,
    median_band: float,
) -> dict:
    """Global two-peak finder (fallback when wedge search yields no peaks)."""
    F_band = F.copy()
    F_band[~band_mask] = 0.0

    idx1 = np.argmax(F_band)
    r1, c1 = np.unravel_index(idx1, F_band.shape)
    if F_band[r1, c1] == 0:
        return {"code": "NO_WEAVE", "reason": "No thread peaks found in spectrum"}

    p1 = _subpixel_refine(F, r1, c1, cy, cx)
    angle1 = math.degrees(math.atan2(p1["ky"], p1["kx"]))
    wedge_mask = _angle_wedge_mask(N, cy, cx, angle1, excl_deg)

    F_band2 = F_band.copy()
    F_band2[wedge_mask] = 0.0
    idx2 = np.argmax(F_band2)
    r2, c2 = np.unravel_index(idx2, F_band2.shape)

    if F_band2[r2, c2] == 0:
        return {"code": "NO_WEAVE", "reason": "Only one thread direction found"}

    p2 = _subpixel_refine(F, r2, c2, cy, cx)
    angle2 = math.degrees(math.atan2(p2["ky"], p2["kx"]))

    diff = abs(angle2 - angle1) % 180
    if diff > 90:
        diff = 180 - diff
    angle_diff = abs(90 - diff)
    if angle_diff > perp_tol:
        perp_target = angle1 + 90
        perp_wedge = _angle_wedge_mask(N, cy, cx, perp_target, perp_tol)
        F_band3 = F_band.copy()
        F_band3[~perp_wedge] = 0.0
        F_band3[wedge_mask] = 0.0
        idx3 = np.argmax(F_band3)
        r3, c3 = np.unravel_index(idx3, F_band3.shape)
        if F_band3[r3, c3] > 0:
            p2 = _subpixel_refine(F, r3, c3, cy, cx)

    p1, p2 = _prefer_fundamental(F, p1, p2, band_mask, N)

    for pk in (p1, p2):
        r_i = int(np.clip(round(cy + pk["ky"]), 0, F.shape[0] - 1))
        c_i = int(np.clip(round(cx + pk["kx"]), 0, F.shape[1] - 1))
        pk["snr"] = float(F[r_i, c_i]) / (median_band + 1e-10)

    min_snr = min(p1["snr"], p2["snr"])
    return {"code": "OK", "reason": "", "peak1": p1, "peak2": p2, "snr": min_snr, "snr1": p1["snr"], "snr2": p2["snr"]}


# ---------------------------------------------------------------------------
# Sub-pixel peak refinement and math helpers
# ---------------------------------------------------------------------------

def _subpixel_refine(F: np.ndarray, r: int, c: int, cy: int, cx: int) -> dict:
    H, W = F.shape
    r = int(np.clip(r, 1, H - 2))
    c = int(np.clip(c, 1, W - 2))

    patch = F[r - 1:r + 2, c - 1:c + 2]

    def parabolic_peak(vals):
        d = vals[0] - 2 * vals[1] + vals[2]
        if abs(d) < 1e-12:
            return 0.0
        return 0.5 * (vals[0] - vals[2]) / d

    dr = parabolic_peak([float(patch[0, 1]), float(patch[1, 1]), float(patch[2, 1])])
    dc = parabolic_peak([float(patch[1, 0]), float(patch[1, 1]), float(patch[1, 2])])

    r_sub = r + dr
    c_sub = c + dc
    kx = c_sub - cx
    ky = r_sub - cy
    k = math.hypot(kx, ky)
    angle_deg = math.degrees(math.atan2(ky, kx))

    return {"r": r_sub, "c": c_sub, "kx": kx, "ky": ky, "k": k, "angle_deg": angle_deg}


def _angle_wedge_mask(N: int, cy: int, cx: int, center_deg: float, half_width_deg: float) -> np.ndarray:
    yy, xx = np.ogrid[:N, :N]
    angle = np.degrees(np.arctan2((yy - cy).astype(float), (xx - cx).astype(float)))
    diff = ((angle - center_deg + 180) % 360) - 180
    mask = np.abs(diff) <= half_width_deg
    diff2 = ((angle - (center_deg + 180) + 180) % 360) - 180
    mask |= np.abs(diff2) <= half_width_deg
    return mask


def _prefer_fundamental(
    F: np.ndarray,
    p1: dict, p2: dict,
    band_mask: np.ndarray,
    N: int,
) -> tuple[dict, dict]:
    cy = cx = N // 2

    def _check_harmonic(pk: dict) -> dict | None:
        kx_half = pk["kx"] / 2
        ky_half = pk["ky"] / 2
        r_fund = int(round(cy + ky_half))
        c_fund = int(round(cx + kx_half))
        if not (0 <= r_fund < N and 0 <= c_fund < N):
            return None
        if not band_mask[r_fund, c_fund]:
            return None
        pk_r = int(np.clip(int(round(pk["r"])), 0, N - 1))
        pk_c = int(np.clip(int(round(pk["c"])), 0, N - 1))
        if F[r_fund, c_fund] > F[pk_r, pk_c]:
            return _subpixel_refine(F, r_fund, c_fund, cy, cx)
        return None

    fund1 = _check_harmonic(p1)
    if fund1 is not None:
        p1 = fund1

    fund2 = _check_harmonic(p2)
    if fund2 is not None:
        p2 = fund2

    return p1, p2


def _assign_warp_weft(p1: dict, p2: dict) -> tuple[dict, dict]:
    """Warp threads run vertically -> frequency peak near kx axis (|ky/kx| small)."""
    ratio1 = abs(p1["ky"]) / (abs(p1["kx"]) + 1e-9)
    ratio2 = abs(p2["ky"]) / (abs(p2["kx"]) + 1e-9)
    if ratio1 <= ratio2:
        return p1, p2
    else:
        return p2, p1


# ---------------------------------------------------------------------------
# §7.5 Irregularity
# ---------------------------------------------------------------------------

def _measure_irregularity(F: np.ndarray, peak: dict, N: int, fwhm0: float = 2.25) -> dict:
    cy = cx = N // 2
    kx, ky = peak["kx"], peak["ky"]
    k = peak["k"]

    if k < 1e-6:
        return {"irregularity": float("nan"), "fwhm": float("nan"), "energy_concentration": 0.0}

    n_samples = int(2 * k * 2) + 1
    t_vals = np.linspace(0, 2 * k, n_samples)
    sample_r = cy + (ky / k) * t_vals
    sample_c = cx + (kx / k) * t_vals
    coords = np.array([sample_r, sample_c])
    profile = ndi.map_coordinates(F, coords, order=1)

    peak_idx = np.argmax(profile)
    peak_val = profile[peak_idx]
    half_max = peak_val / 2.0

    def _crossing(arr, peak_i, direction):
        idx = peak_i
        while 0 < idx < len(arr) - 1:
            idx += direction
            if arr[idx] <= half_max:
                frac = (arr[idx + (-direction)] - half_max) / (arr[idx + (-direction)] - arr[idx] + 1e-12)
                return idx - direction * (1 - frac)
        return float(idx)

    left_cross  = _crossing(profile, peak_idx, -1)
    right_cross = _crossing(profile, peak_idx, +1)
    fwhm_samples = max(0.0, right_cross - left_cross)
    fwhm_k = fwhm_samples * (2 * k / max(n_samples - 1, 1))

    fwhm_excess = math.sqrt(max(fwhm_k ** 2 - fwhm0 ** 2, 0.0))
    irregularity = fwhm_excess / (k + 1e-9)

    yy, xx = np.ogrid[:N, :N]
    r2 = (xx - (cx + kx)) ** 2 + (yy - (cy + ky)) ** 2
    near_mask  = r2 <= 4
    band_mask2 = (np.sqrt((xx - cx).astype(float) ** 2 + (yy - cy).astype(float) ** 2) > 0)
    energy_near = float(np.sum(F[near_mask] ** 2))
    energy_band = float(np.sum(F[band_mask2] ** 2)) + 1e-10
    energy_concentration = energy_near / energy_band

    return {
        "irregularity": float(irregularity),
        "fwhm": float(fwhm_k),
        "energy_concentration": float(energy_concentration),
    }


# ---------------------------------------------------------------------------
# §7.6 Defect detection & Task 7 residual PNG export
# ---------------------------------------------------------------------------

def _detect_defects(
    img: np.ndarray,
    peaks: list[dict],
    N: int,
    defect_cfg: dict,
    px_per_mm: float = 40.0,
    debug_dir: str | None = None,
) -> tuple[np.ndarray, dict]:
    """Notch periodic weave grid, invert FFT, and threshold residual for defects."""
    import os

    cy = cx = N // 2
    F_complex = np.fft.fftshift(np.fft.fft2(img.astype(np.float64)))
    notch_mask = np.ones((N, N), dtype=bool)

    notch_r = defect_cfg["notch_radius"]
    n_harmonics = defect_cfg["harmonics"]
    yy, xx = np.ogrid[:N, :N]

    if len(peaks) >= 2:
        p1, p2 = peaks[0], peaks[1]
        kx1, ky1 = p1["kx"], p1["ky"]
        kx2, ky2 = p2["kx"], p2["ky"]
        for h1 in range(-n_harmonics, n_harmonics + 1):
            for h2 in range(-n_harmonics, n_harmonics + 1):
                if h1 == 0 and h2 == 0:
                    continue
                centre_x = cx + h1 * kx1 + h2 * kx2
                centre_y = cy + h1 * ky1 + h2 * ky2
                if 0 <= centre_x < N and 0 <= centre_y < N:
                    notch_mask[(xx.astype(float) - centre_x) ** 2 + (yy.astype(float) - centre_y) ** 2 <= notch_r ** 2] = False
    else:
        for pk in peaks:
            kx, ky = pk["kx"], pk["ky"]
            for h in range(1, n_harmonics + 1):
                for sign in [+1, -1]:
                    centre_x = cx + sign * h * kx
                    centre_y = cy + sign * h * ky
                    if 0 <= centre_x < N and 0 <= centre_y < N:
                        notch_mask[(xx.astype(float) - centre_x) ** 2 + (yy.astype(float) - centre_y) ** 2 <= notch_r ** 2] = False

    F_notched = F_complex.copy()
    F_notched[~notch_mask] = 0.0
    residual = np.real(np.fft.ifft2(np.fft.ifftshift(F_notched))).astype(np.float32)

    res_c = residual - np.median(residual)
    sigma_k = defect_cfg["residual_sigma_k"]
    mad = float(np.median(np.abs(res_c)))
    robust_sigma = 1.4826 * mad
    threshold_floor = float(defect_cfg.get("threshold_floor", 0.04))
    threshold = max(sigma_k * robust_sigma, threshold_floor)

    binary = (np.abs(res_c) > threshold).astype(np.uint8)

    margin = max(int(round(px_per_mm * 1.0)), 20)
    if 2 * margin < N:
        binary[:margin, :] = 0
        binary[-margin:, :] = 0
        binary[:, :margin] = 0
        binary[:, -margin:] = 0

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    min_blob = defect_cfg["min_blob_area_px"]
    count = 0
    total_area = 0
    for i in range(1, n_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area >= min_blob:
            count += 1
            total_area += area

    area_fraction = total_area / (N * N)

    # Task 7: save fingerprint residual PNG
    if debug_dir is not None:
        try:
            os.makedirs(debug_dir, exist_ok=True)
            res_norm = res_c - res_c.min()
            denom = res_c.max() - res_c.min()
            if denom > 1e-10:
                res_norm = res_norm / denom
            res_u8 = (np.clip(res_norm, 0.0, 1.0) * 255).astype(np.uint8)
            residual_path = os.path.join(debug_dir, "fingerprint_residual.png")
            cv2.imwrite(residual_path, res_u8)
        except Exception:
            pass

    return residual, {"count": count, "area_fraction": float(area_fraction)}


# ---------------------------------------------------------------------------
# §7.7 Grade
# ---------------------------------------------------------------------------

def _compute_grade(irregularity: float, defect_fraction: float, grade_cfg: dict) -> str:
    if math.isnan(irregularity):
        return "C"
    a_cfg = grade_cfg["A"]
    b_cfg = grade_cfg["B"]
    use_defects = grade_cfg.get("use_defects", False)

    irr_a = irregularity <= a_cfg["max_irregularity"]
    def_a = (defect_fraction <= a_cfg["max_defect_fraction"]) if use_defects else True
    if irr_a and def_a:
        return "A"

    irr_b = irregularity <= b_cfg["max_irregularity"]
    def_b = (defect_fraction <= b_cfg["max_defect_fraction"]) if use_defects else True
    if irr_b and def_b:
        return "B"

    return "C"


# ---------------------------------------------------------------------------
# Task 7: Debug spectrum image
# ---------------------------------------------------------------------------

def _save_debug_spectrum(
    F: np.ndarray,
    band_mask: np.ndarray,
    peaks: list[dict],
    band_min_k: float,
    band_max_k: float,
    dc_r: float,
    debug_dir: str,
    N: int,
    thread_band_min_k: float | None = None,
    thread_band_max_k: float | None = None,
    axis_tol: float = 20.0,
    px_per_mm: float = 0.0,
) -> None:
    """Save colour PNG with classic band, TPI band, search wedges, and peak markers."""
    import os
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    os.makedirs(debug_dir, exist_ok=True)

    log_F = np.log1p(F)
    log_F_norm = (log_F - log_F.min()) / ((log_F.max() - log_F.min()) + 1e-10)

    fig, ax = plt.subplots(1, 1, figsize=(8, 8))
    ax.imshow(log_F_norm, cmap="inferno", origin="upper")

    cy = cx = N // 2

    # Classic band boundaries
    for r_px, label, ls, col in [
        (band_min_k, f"classic min ({band_min_k:.0f} k)", "--", "cyan"),
        (band_max_k, f"classic max ({band_max_k:.0f} k)", "-", "cyan"),
        (dc_r,       f"DC mask (r={dc_r:.0f})", ":", "cyan"),
    ]:
        circle = plt.Circle((cx, cy), r_px, color=col, fill=False, linestyle=ls, linewidth=1, alpha=0.7)
        ax.add_patch(circle)
        ax.text(cx + r_px * 0.72, cy - r_px * 0.72, label, color=col, fontsize=6.5, ha="center")

    # Task 1: TPI thread band boundaries (magenta)
    if thread_band_min_k is not None:
        c2 = plt.Circle((cx, cy), thread_band_min_k, color="magenta", fill=False, linestyle="--", linewidth=1.5, alpha=0.9)
        ax.add_patch(c2)
        ax.text(cx - thread_band_min_k * 0.7, cy + thread_band_min_k * 0.7,
                f"min_tpi band ({thread_band_min_k:.1f} k)", color="magenta", fontsize=6.5, ha="center")
    if thread_band_max_k is not None:
        c3 = plt.Circle((cx, cy), thread_band_max_k, color="magenta", fill=False, linestyle="-", linewidth=1.5, alpha=0.9)
        ax.add_patch(c3)
        ax.text(cx + thread_band_max_k * 0.72, cy - thread_band_max_k * 0.72,
                f"max_tpi band ({thread_band_max_k:.1f} k)", color="magenta", fontsize=6.5, ha="center")

    # Task 2: Search wedges
    r_outer = thread_band_max_k if thread_band_max_k is not None else band_max_k
    for center_deg, wedge_color, wedge_label in [
        (0.0, "lime", f"warp wedge (0°±{axis_tol:.0f}°)"),
        (90.0, "yellow", f"weft wedge (90°±{axis_tol:.0f}°)"),
    ]:
        for angle_offset in [0, 180]:
            start = center_deg + angle_offset - axis_tol
            end = center_deg + angle_offset + axis_tol
            wedge = mpatches.Wedge(
                (cx, cy), r_outer, start, end,
                width=r_outer - dc_r,
                color=wedge_color, alpha=0.12,
            )
            ax.add_patch(wedge)
        ax.text(
            cx + r_outer * 0.5 * math.cos(math.radians(center_deg)),
            cy - r_outer * 0.5 * math.sin(math.radians(center_deg)),
            wedge_label, color=wedge_color, fontsize=6.5, ha="center",
        )

    # Peak markers
    colors_pk = ["lime", "yellow"]
    labels_pk = ["warp peak", "weft peak"]
    for pk, col, lbl in zip(peaks, colors_pk, labels_pk):
        px_c = cx + pk["kx"]
        px_r = cy + pk["ky"]
        tpi_est = pk["k"] / N * px_per_mm * 25.4 if px_per_mm > 0 else float("nan")
        ax.plot(px_c, px_r, "+", color=col, markersize=14, markeredgewidth=2)
        ax.annotate(
            f"{lbl}\nk={pk['k']:.1f}\n{tpi_est:.0f} tpi\n({pk['angle_deg']:.1f}°)",
            xy=(px_c, px_r), xytext=(px_c + 15, px_r - 15),
            color=col, fontsize=8,
            arrowprops=dict(arrowstyle="->", color=col, lw=0.8),
        )
        ax.plot(cx - pk["kx"], cy - pk["ky"], "x", color=col, markersize=8, markeredgewidth=1, alpha=0.5)

    ax.set_title("Log-magnitude FFT spectrum\n(magenta=TPI band, shaded=search wedges)", fontsize=10)
    ax.set_xlabel("kx (frequency, cycles per window)")
    ax.set_ylabel("ky (frequency, cycles per window)")

    tick_positions = np.linspace(0, N - 1, 9, dtype=int)
    tick_labels = [f"{t - cy}" for t in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, fontsize=7)
    ax.set_yticks(tick_positions)
    ax.set_yticklabels(tick_labels, fontsize=7)

    plt.tight_layout()
    out_path = os.path.join(debug_dir, "spectrum_peaks.png")
    plt.savefig(out_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Task 6b: Contrast-normalised DESIGN_AREA ratio
# ---------------------------------------------------------------------------

def compute_design_energy_ratio_normalized(
    window_gray: np.ndarray,
    cfg: dict,
) -> float:
    """
    Compute DESIGN_AREA ratio after local contrast normalisation.
    Divides by local standard deviation so uniformly dark cloth isn't penalised.
    """
    img = window_gray.astype(np.float64)
    if img.max() > 1.0:
        img = img / 255.0

    sigma = 10.0
    local_mean = cv2.GaussianBlur(img.astype(np.float32), (0, 0), sigma).astype(np.float64)
    local_mean_sq = cv2.GaussianBlur((img ** 2).astype(np.float32), (0, 0), sigma).astype(np.float64)
    local_var = np.maximum(local_mean_sq - local_mean ** 2, 0.0)
    local_std = np.sqrt(local_var)

    std_floor = float(np.percentile(local_std[local_std > 0], 10)) if np.any(local_std > 0) else 1e-6
    std_floor = max(std_floor, 1e-6)
    img_norm = img / np.where(local_std > std_floor, local_std, std_floor)
    img_norm = img_norm - img_norm.mean()

    N = min(img_norm.shape)
    img_norm = img_norm[:N, :N]

    F_mag = np.abs(np.fft.fftshift(np.fft.fft2(img_norm)))
    cy = cx = N // 2
    yy, xx = np.ogrid[:N, :N]
    r = np.sqrt((xx - cx).astype(float) ** 2 + (yy - cy).astype(float) ** 2)

    band_min_k = N / cfg["fft"]["band_max_px_per_cycle"]
    band_max_k = N / cfg["fft"]["band_min_px_per_cycle"]
    dc_r = cfg["fft"]["dc_mask_radius"]

    low_freq_mask = (r > dc_r) & (r < band_min_k)
    in_band_mask  = (r >= band_min_k) & (r <= band_max_k)

    e_low  = float(np.sum(F_mag[low_freq_mask] ** 2))
    e_band = float(np.sum(F_mag[in_band_mask] ** 2)) + 1e-9
    return float(e_low / e_band)


# ---------------------------------------------------------------------------
# Helpers & Backward compatibility alias
# ---------------------------------------------------------------------------

def _fail(code: str, reason: str, extra: dict | None = None) -> dict:
    result = {"ok": False, "code": code, "reason": reason}
    if extra:
        result.update(extra)
    return result


def _find_two_peaks(
    F: np.ndarray,
    band_mask: np.ndarray,
    N: int,
    excl_deg: float,
    perp_tol: float,
) -> dict:
    """Backward-compatible alias used by tests/fingerprint."""
    cy = cx = N // 2
    band_vals = F[band_mask]
    med = float(np.median(band_vals)) if band_vals.size > 0 else 1.0
    return _find_two_peaks_global(F, band_mask, N, cy, cx, excl_deg, perp_tol, med)
