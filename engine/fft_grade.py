"""
engine/fft_grade.py
Thread density measurement, irregularity, defect detection, and provisional grade
via 2D FFT analysis of a rectified fabric window.

Input:  float32 grayscale window array (any size; square assumed but not required).
        px_per_mm: scale of the input image.
        cfg: engine config dict (from engine.config.get_config()).

Output: dict with all measurements plus pass/fail codes.

This module has NO dependency on card.py or enhance.py; it operates on a plain array.
Enhancement (stacking, flat-field) happens upstream and is optional.

§7.3 Pre-processing → §7.4 Thread density → §7.5 Irregularity → §7.6 Defects → §7.7 Grade
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
    window : float32 grayscale array, values in [0, 1].  Shape: (H, W).
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

    # ---- §7.3 Pre-processing ------------------------------------------------
    img_flat, img_hann = _preprocess(window, fft_cfg)
    N = img_hann.shape[0]  # assume square after preprocessing (we use the smaller dim)

    # ---- §7.4 FFT peak finding ----------------------------------------------
    F = _compute_spectrum(img_hann)

    # Frequency axis: index k → spatial frequency = k/N cycles/pixel
    # Band: convert px_per_cycle limits → radius limits in FFT index units
    band_min_k = N / fft_cfg["band_max_px_per_cycle"]   # slow cutoff → small k
    band_max_k = N / fft_cfg["band_min_px_per_cycle"]   # fast cutoff → large k
    dc_r       = fft_cfg["dc_mask_radius"]

    # Build the band mask (half-plane, upper half to avoid duplicates)
    band_mask = _make_band_mask(N, dc_r, band_min_k, band_max_k)

    # Detect peaks
    peak_result = _find_two_peaks(
        F, band_mask, N,
        excl_deg   = fft_cfg["peak_exclusion_deg"],
        perp_tol   = fft_cfg["expect_perpendicular_tol_deg"],
    )

    t_peaks = time.perf_counter()

    if peak_result["code"] != "OK":
        return _fail(peak_result["code"], peak_result["reason"], extra={
            "quality": {"peak_snr": peak_result.get("snr")},
            "timings_ms": {"total": (time.perf_counter() - t0) * 1000},
        })

    # ---- SNR gate (§7.2 NO_WEAVE) ------------------------------------------
    snr = peak_result.get("snr", 0.0)
    if snr < quality_cfg["min_peak_snr"]:
        return _fail("NO_WEAVE", "Can't see the threads — move closer / refocus", extra={
            "quality": {"peak_snr": snr},
            "timings_ms": {"total": (time.perf_counter() - t0) * 1000},
        })

    p1 = peak_result["peak1"]  # warp (near kx axis after card orientation)
    p2 = peak_result["peak2"]  # weft (near ky axis)

    # Assign warp/weft based on card orientation:
    # Warp threads run vertically → peak near kx axis (angle ≈ 0°/180°)
    # i.e. |ky/kx| < 1 for warp peak
    p_warp, p_weft = _assign_warp_weft(p1, p2)

    # ---- Compute thread counts ----------------------------------------------
    window_mm = px_per_mm and (N / px_per_mm)  # effective window size in mm
    # Note: we use the actual image size in pixels and the given px_per_mm.

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
            },
            "timings_ms": {"total": (time.perf_counter() - t0) * 1000},
        })

    # Check 2: harmonic aliasing — peak > 0.4 × Nyquist
    nyquist_k = N / 2
    if p_warp["k"] > 0.4 * nyquist_k or p_weft["k"] > 0.4 * nyquist_k:
        return _fail("ALIASING", "Move closer — thread frequency too close to Nyquist", extra={
            "timings_ms": {"total": (time.perf_counter() - t0) * 1000},
        })

    # Check 3: explicit px/thread from known scale (catches aliased peaks inside the band)
    if px_per_mm > 0:
        max_tpi_resolvable = px_per_mm * 25.4 / min_ppt
        if warp_c["threads_per_inch"] > max_tpi_resolvable or weft_c["threads_per_inch"] > max_tpi_resolvable:
            return _fail("ALIASING", "Move closer — not enough pixels per thread at this scale", extra={
                "timings_ms": {"total": (time.perf_counter() - t0) * 1000},
            })

    # ---- §7.5 Irregularity --------------------------------------------------
    fwhm0 = float(fft_cfg.get("fwhm0", 2.00))
    irr_warp = _measure_irregularity(F, p_warp, N, fwhm0=fwhm0)
    irr_weft = _measure_irregularity(F, p_weft, N, fwhm0=fwhm0)

    # ---- §7.6 Defects -------------------------------------------------------
    residual, defect_result = _detect_defects(
        img_flat, [p_warp, p_weft], N, defect_cfg, px_per_mm=px_per_mm, debug_dir=debug_dir
    )

    # ---- §7.7 Grade (uses max of warp and weft irregularity) ----------------
    overall_irregularity = max(irr_warp["irregularity"], irr_weft["irregularity"])
    grade_str = _compute_grade(overall_irregularity, defect_result["area_fraction"], grade_cfg)

    # ---- Peak SNR (also used as a quality metric) ---------------------------
    snr_warp = p_warp.get("snr", float("nan"))
    snr_weft = p_weft.get("snr", float("nan"))

    # ---- Debug: spectrum image ----------------------------------------------
    if debug_dir is not None:
        _save_debug_spectrum(
            F, band_mask, [p_warp, p_weft],
            band_min_k, band_max_k, dc_r, debug_dir, N,
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
        },
        "timings_ms": {"fft_grade": t_total},
        # Raw FFT peaks (for debugging / downstream use)
        "_peaks": {"warp": p_warp, "weft": p_weft},
    }


# ---------------------------------------------------------------------------
# §7.3 Pre-processing
# ---------------------------------------------------------------------------

def _preprocess(window: np.ndarray, fft_cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    """
    Flat-field correction + Hann windowing.
    Input: float32 [0,1].
    Returns: (img_flat, img_hann) both shape (N, N) zero-mean float32.
    """
    img = window.astype(np.float32)

    # Use smaller dimension for square FFT
    H, W = img.shape[:2]
    N = min(H, W)
    img = img[:N, :N]

    # Flat-field: divide by Gaussian blur, then subtract mean
    # (removes uneven lighting and torch hotspots)
    sigma = float(fft_cfg.get("flatfield_sigma_px", 25.0)) if isinstance(fft_cfg, dict) else 25.0
    blur = cv2.GaussianBlur(img, (0, 0), sigma)
    # Avoid division by zero
    blur = np.where(blur < 1e-6, 1e-6, blur)
    img_flat = img / blur
    img_flat = img_flat - img_flat.mean()

    # 2D Hann window (suppresses spectral leakage at edges)
    hann_1d = np.hanning(N).astype(np.float32)
    hann_2d = np.outer(hann_1d, hann_1d)
    img_hann = img_flat * hann_2d

    return img_flat.astype(np.float32), img_hann.astype(np.float32)


# ---------------------------------------------------------------------------
# §7.4 FFT spectrum
# ---------------------------------------------------------------------------

def _compute_spectrum(img: np.ndarray) -> np.ndarray:
    """Return the magnitude spectrum (fftshift applied, upper half only)."""
    F_complex = np.fft.fft2(img.astype(np.float64))
    F_shift = np.fft.fftshift(F_complex)
    F_mag = np.abs(F_shift).astype(np.float64)
    return F_mag


def _make_band_mask(N: int, dc_r: float, band_min_k: float, band_max_k: float) -> np.ndarray:
    """
    Boolean mask: True where we search for thread peaks.
    - Removes DC disc (radius dc_r)
    - Keeps only the band [band_min_k, band_max_k]
    - Only upper half-plane (ky >= 0) to avoid symmetric duplicates
    """
    cy = cx = N // 2
    yy, xx = np.ogrid[:N, :N]
    r = np.sqrt((xx - cx).astype(float) ** 2 + (yy - cy).astype(float) ** 2)
    ky = yy - cy  # signed, positive = upper half in image coords

    mask = (
        (r >= band_min_k)
        & (r <= band_max_k)
        & (r > dc_r)
        & (ky.astype(float) >= 0)  # upper half-plane only
    )
    return mask.astype(bool)


def _find_two_peaks(
    F: np.ndarray,
    band_mask: np.ndarray,
    N: int,
    excl_deg: float,
    perp_tol: float,
) -> dict:
    """
    Find the two dominant perpendicular thread peaks in the band.
    Returns dict with keys: code, reason, peak1, peak2, snr.
    """
    cy = cx = N // 2
    F_band = F.copy()
    F_band[~band_mask] = 0.0

    # --- Peak 1 ---
    idx1 = np.argmax(F_band)
    r1, c1 = np.unravel_index(idx1, F_band.shape)
    if F_band[r1, c1] == 0:
        return {"code": "NO_WEAVE", "reason": "No thread peaks found in spectrum"}

    # Sub-pixel refinement for peak 1
    p1 = _subpixel_refine(F, r1, c1, cy, cx)

    # Peak SNR = peak value / median of band values (excluding zeros)
    band_vals = F[band_mask]
    median_band = float(np.median(band_vals))
    snr = float(F[r1, c1]) / (median_band + 1e-10)

    # --- Peak 2: exclude angular wedge around peak 1 ---
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

    # --- Check perpendicularity ---
    diff = abs(angle2 - angle1) % 180
    if diff > 90:
        diff = 180 - diff
    angle_diff = abs(90 - diff)  # error from 90°
    if angle_diff > perp_tol:
        # Try searching in the perpendicular wedge explicitly
        perp_target = angle1 + 90
        perp_wedge = _angle_wedge_mask(N, cy, cx, perp_target, perp_tol)
        F_band3 = F_band.copy()
        F_band3[~perp_wedge] = 0.0
        F_band3[wedge_mask] = 0.0
        idx3 = np.argmax(F_band3)
        r3, c3 = np.unravel_index(idx3, F_band3.shape)
        if F_band3[r3, c3] > 0:
            p2 = _subpixel_refine(F, r3, c3, cy, cx)

    # --- Harmonic check: prefer fundamental over harmonic ---
    p1, p2 = _prefer_fundamental(F, p1, p2, band_mask, N)

    # Attach separate SNRs to each peak
    val1 = float(F[int(round(cy + p1["ky"])), int(round(cx + p1["kx"]))])
    val2 = float(F[int(round(cy + p2["ky"])), int(round(cx + p2["kx"]))])
    snr1 = val1 / (median_band + 1e-10)
    snr2 = val2 / (median_band + 1e-10)
    p1["snr"] = snr1
    p2["snr"] = snr2
    min_snr = min(snr1, snr2)

    return {"code": "OK", "reason": "", "peak1": p1, "peak2": p2, "snr": min_snr, "snr1": snr1, "snr2": snr2}


def _subpixel_refine(F: np.ndarray, r: int, c: int, cy: int, cx: int) -> dict:
    """
    Fit a 2D quadratic to the 3×3 neighbourhood of (r, c) in F.
    Returns dict with kx, ky (fractional cycles relative to DC centre), k, angle_deg.
    """
    H, W = F.shape
    r = int(np.clip(r, 1, H - 2))
    c = int(np.clip(c, 1, W - 2))

    patch = F[r - 1:r + 2, c - 1:c + 2]

    # 1D parabolic interpolation along each axis
    def parabolic_peak(vals):
        # vals = [v_left, v_centre, v_right]
        d = vals[0] - 2 * vals[1] + vals[2]
        if abs(d) < 1e-12:
            return 0.0
        return 0.5 * (vals[0] - vals[2]) / d

    dr = parabolic_peak([float(patch[0, 1]), float(patch[1, 1]), float(patch[2, 1])])
    dc = parabolic_peak([float(patch[1, 0]), float(patch[1, 1]), float(patch[1, 2])])

    r_sub = r + dr
    c_sub = c + dc
    kx = c_sub - cx
    ky = r_sub - cy  # positive ky = upward in frequency
    k = math.hypot(kx, ky)
    angle_deg = math.degrees(math.atan2(ky, kx))

    return {"r": r_sub, "c": c_sub, "kx": kx, "ky": ky, "k": k, "angle_deg": angle_deg}


def _angle_wedge_mask(N: int, cy: int, cx: int, center_deg: float, half_width_deg: float) -> np.ndarray:
    """
    Boolean mask: True for pixels whose angle from (cy, cx) is within
    ±half_width_deg of center_deg (and its 180° opposite).
    """
    yy, xx = np.ogrid[:N, :N]
    angle = np.degrees(np.arctan2((yy - cy).astype(float), (xx - cx).astype(float)))
    # Wrap to [-180, 180]
    diff = ((angle - center_deg + 180) % 360) - 180
    mask = np.abs(diff) <= half_width_deg
    # Also the opposite direction
    diff2 = ((angle - (center_deg + 180) + 180) % 360) - 180
    mask |= np.abs(diff2) <= half_width_deg
    return mask


def _prefer_fundamental(
    F: np.ndarray,
    p1: dict, p2: dict,
    band_mask: np.ndarray,
    N: int,
) -> tuple[dict, dict]:
    """
    If a detected peak looks like the 2nd harmonic of a weaker fundamental
    still inside the band, prefer the fundamental.

    A peak at k is a harmonic if the value at k/2 is STRONGER than the value at k
    (i.e. the alleged "fundamental" at k/2 dominates).  In normal fabric the
    fundamental is the strongest peak, so we only replace it when the half-
    frequency is genuinely larger.
    """
    cy = cx = N // 2

    def _check_harmonic(pk: dict) -> dict | None:
        """Return the half-frequency peak IFF it is stronger than pk (pk is a harmonic)."""
        kx_half = pk["kx"] / 2
        ky_half = pk["ky"] / 2
        r_fund = int(round(cy + ky_half))
        c_fund = int(round(cx + kx_half))
        if not (0 <= r_fund < N and 0 <= c_fund < N):
            return None
        if not band_mask[r_fund, c_fund]:
            return None
        pk_r = int(round(pk["r"]))
        pk_c = int(round(pk["c"]))
        pk_r = int(np.clip(pk_r, 0, N - 1))
        pk_c = int(np.clip(pk_c, 0, N - 1))
        # Only replace if the half-frequency value is STRONGER (pk is a harmonic of that)
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
    """
    Assign warp/weft based on card orientation:
    Warp threads run vertically → their FFT peak is on the kx axis (|ky/kx| small).
    The peak with smaller |ky/kx| ratio = warp.
    """
    ratio1 = abs(p1["ky"]) / (abs(p1["kx"]) + 1e-9)
    ratio2 = abs(p2["ky"]) / (abs(p2["kx"]) + 1e-9)
    if ratio1 <= ratio2:
        return p1, p2  # p1 = warp, p2 = weft
    else:
        return p2, p1


# ---------------------------------------------------------------------------
# §7.5 Irregularity (FWHM of the radial peak profile)
# ---------------------------------------------------------------------------

def _measure_irregularity(F: np.ndarray, peak: dict, N: int, fwhm0: float = 2.00) -> dict:
    """
    Measure FWHM of the radial profile through the peak.
    Returns: irregularity (= FWHM/k), energy_concentration.
    """
    cy = cx = N // 2
    kx, ky = peak["kx"], peak["ky"]
    k = peak["k"]

    if k < 1e-6:
        return {"irregularity": float("nan"), "fwhm": float("nan"), "energy_concentration": 0.0}

    # Sample F along the radial line through the peak
    # from 0 to 2k in steps of 0.5 pixel
    n_samples = int(2 * k * 2) + 1
    t_vals = np.linspace(0, 2 * k, n_samples)
    sample_r = cy + (ky / k) * t_vals
    sample_c = cx + (kx / k) * t_vals
    coords = np.array([sample_r, sample_c])
    profile = ndi.map_coordinates(F, coords, order=1)

    # Peak position in the profile ≈ k
    peak_idx = np.argmax(profile)
    peak_val = profile[peak_idx]
    half_max = peak_val / 2.0

    # Find half-max crossings on each side of peak
    def _crossing(arr, peak_i, direction):
        idx = peak_i
        while 0 < idx < len(arr) - 1:
            idx += direction
            if arr[idx] <= half_max:
                # Linear interpolation
                frac = (arr[idx + (-direction)] - half_max) / (arr[idx + (-direction)] - arr[idx] + 1e-12)
                return idx - direction * (1 - frac)
        return float(idx)

    left_cross  = _crossing(profile, peak_idx, -1)
    right_cross = _crossing(profile, peak_idx, +1)
    fwhm_samples = max(0.0, right_cross - left_cross)
    # Convert from sample index (0.5 px steps) to frequency units (k-space)
    fwhm_k = fwhm_samples * (2 * k / max(n_samples - 1, 1))

    # Instrument-limited peak width (FWHM0 from config, default 2.00)
    # Subtract in quadrature so perfect synthetic weaves yield ~0 irregularity
    fwhm_excess = math.sqrt(max(fwhm_k ** 2 - fwhm0 ** 2, 0.0))
    irregularity = fwhm_excess / (k + 1e-9)

    # Energy concentration: energy within radius 2 of peak vs band energy
    yy, xx = np.ogrid[:N, :N]
    r2 = (xx - (cx + kx)) ** 2 + (yy - (cy + ky)) ** 2
    near_mask  = r2 <= 4  # radius 2
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
# §7.6 Defect detection
# ---------------------------------------------------------------------------

def _detect_defects(
    img: np.ndarray,
    peaks: list[dict],
    N: int,
    defect_cfg: dict,
    px_per_mm: float = 40.0,
    debug_dir: str | None = None,
) -> tuple[np.ndarray, dict]:
    """
    Build a notch mask removing each peak, its harmonics and 2D weave grid combinations,
    then inverse-FFT the residual and threshold it to find defects.
    """
    cy = cx = N // 2

    F_complex = np.fft.fftshift(np.fft.fft2(img.astype(np.float64)))
    notch_mask = np.ones((N, N), dtype=bool)  # True = keep

    notch_r = defect_cfg["notch_radius"]
    n_harmonics = defect_cfg["harmonics"]

    yy, xx = np.ogrid[:N, :N]

    if len(peaks) >= 2:
        p1, p2 = peaks[0], peaks[1]
        kx1, ky1 = p1["kx"], p1["ky"]
        kx2, ky2 = p2["kx"], p2["ky"]
        # Notch the 2D periodic weave grid: h1*(kx1,ky1) + h2*(kx2,ky2)
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

    # Residual: inverse FFT of the notched spectrum
    F_notched = F_complex.copy()
    F_notched[~notch_mask] = 0.0
    residual = np.real(np.fft.ifft2(np.fft.ifftshift(F_notched))).astype(np.float32)

    # Threshold on centered residual
    res_c = residual - np.median(residual)
    sigma_k = defect_cfg["residual_sigma_k"]
    mad = float(np.median(np.abs(res_c)))
    robust_sigma = 1.4826 * mad
    threshold_floor = float(defect_cfg.get("threshold_floor", 0.04))
    threshold = max(sigma_k * robust_sigma, threshold_floor)

    binary = (np.abs(res_c) > threshold).astype(np.uint8)

    # Mask out outer boundary margin (1 mm at given scale, minimum 20 px) to avoid FFT edge Gibbs ripples
    margin = max(int(round(px_per_mm * 1.0)), 20)
    if 2 * margin < N:
        binary[:margin, :] = 0
        binary[-margin:, :] = 0
        binary[:, :margin] = 0
        binary[:, -margin:] = 0

    # Morphological clean-up
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    # Connected components
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

    return residual, {"count": count, "area_fraction": float(area_fraction)}


# ---------------------------------------------------------------------------
# §7.7 Grade
# ---------------------------------------------------------------------------

def _compute_grade(irregularity: float, defect_fraction: float, grade_cfg: dict) -> str:
    """Rule-based provisional grade. Always mark grade_provisional=True."""
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
# Debug: spectrum image with band and peaks annotated
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
) -> None:
    """
    Save a colour PNG of the log-magnitude spectrum with:
    - band boundaries drawn as circles
    - peak positions marked with crosshairs and labels
    - DC region marked
    Saved to debug_dir/spectrum_peaks.png
    """
    import os
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(debug_dir, exist_ok=True)

    log_F = np.log1p(F)
    # Normalise to [0,1] for display
    log_F_norm = (log_F - log_F.min()) / ((log_F.max() - log_F.min()) + 1e-10)

    fig, ax = plt.subplots(1, 1, figsize=(7, 7))
    ax.imshow(log_F_norm, cmap="inferno", origin="upper")

    cy = cx = N // 2

    # Band boundaries
    for r_px, label, ls in [
        (band_min_k, f"band min ({band_min_k:.1f} px/cyc)", "--"),
        (band_max_k, f"band max ({band_max_k:.1f} px/cyc)", "-"),
        (dc_r,       f"DC mask (r={dc_r})", ":"),
    ]:
        circle = plt.Circle((cx, cy), r_px, color="cyan", fill=False,
                             linestyle=ls, linewidth=1, alpha=0.7)
        ax.add_patch(circle)
        ax.text(cx + r_px * 0.72, cy - r_px * 0.72, label,
                color="cyan", fontsize=7, ha="center")

    # Peak markers
    colors_pk = ["lime", "yellow"]
    labels_pk = ["warp peak", "weft peak"]
    for pk, col, lbl in zip(peaks, colors_pk, labels_pk):
        px_c = cx + pk["kx"]
        px_r = cy + pk["ky"]
        ax.plot(px_c, px_r, "+", color=col, markersize=14, markeredgewidth=2)
        ax.annotate(
            f"{lbl}\nk={pk['k']:.1f} cyc\n{pk['k'] / N * 25.4:.0f} tpi*\n"
            f"({pk['angle_deg']:.1f}°)",
            xy=(px_c, px_r), xytext=(px_c + 15, px_r - 15),
            color=col, fontsize=8,
            arrowprops=dict(arrowstyle="->", color=col, lw=0.8),
        )
        # Symmetric twin
        ax.plot(cx - pk["kx"], cy - pk["ky"], "x", color=col, markersize=8, markeredgewidth=1, alpha=0.5)

    ax.set_title("Log-magnitude FFT spectrum\n(* tpi = threads/inch estimate using px_per_mm)", fontsize=10)
    ax.set_xlabel("kx (frequency, cycles per window)")
    ax.set_ylabel("ky (frequency, cycles per window)")

    # Custom tick labels: convert pixel coords to frequency
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
    print(f"[debug] Spectrum saved: {out_path}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fail(code: str, reason: str, extra: dict | None = None) -> dict:
    result = {"ok": False, "code": code, "reason": reason}
    if extra:
        result.update(extra)
    return result
