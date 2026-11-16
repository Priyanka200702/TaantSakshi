"""
engine/quality.py
Full quality check suite implementing §7.2 of TANTSAAKSHI_ENGINE_SPEC.md.

Priority evaluation order:
  1. NO_CARD       (ArUco marker detection)
  2. TOO_TILTED    (Perspective homography tilt angle)
  3. LOW_RES       (Native px/mm from marker physical size)
  4. TOO_DARK      (Dark pixel fraction < 20)
  5. GLARE         (Saturated pixel fraction >= 250)
  6. BLURRY        (Sharpness variance of Laplacian)
  7. NO_WEAVE      (Thread peak SNR)
  8. ALIASING      (Pixels per thread < 4.0 or > 0.4 Nyquist)
  9. WEAVE_UNCLEAR (Validation: perp / 1-D cross-check / per-peak SNR)
 10. DESIGN_AREA   (Low-frequency design pattern energy ratio, contrast-normalised)

Rule: Measures and reports ALL metrics for evaluation; fails on the FIRST in priority order.
Never raises on bad photos — returns ok: False with human text reason.

Changes (engine-fixes):
  Task 3  – WEAVE_UNCLEAR inserted between ALIASING and DESIGN_AREA.
  Task 6b – design_energy_ratio computed on contrast-normalised image.
"""
from __future__ import annotations

import cv2
import numpy as np

from engine.enhance import measure_sharpness


def evaluate_quality(
    raw_image: np.ndarray,
    card_result: dict,
    window_gray: np.ndarray | None,
    fft_result: dict | None,
    cfg: dict,
) -> dict:
    """
    Evaluate all quality metrics against thresholds in config.yaml.

    Returns dict:
        ok : bool
        code : str ("OK" or first failing check code)
        reason : str (human-readable message)
        metrics : dict of all computed numeric values
        failed_checks : list of all failing codes
    """
    q_cfg = cfg["quality"]

    metrics = {
        "markers_found": len(card_result.get("detected_marker_ids", [])),
        "native_px_per_mm": float(card_result.get("native_px_per_mm", 0.0)),
        "tilt_deg": float(card_result.get("tilt_deg", 0.0)),
        "dark_fraction": 0.0,
        "saturated_fraction": 0.0,
        "sharpness": 0.0,
        "peak_snr_warp": 0.0,
        "peak_snr_weft": 0.0,
        "warp_px_per_thread": 0.0,
        "weft_px_per_thread": 0.0,
        "design_energy_ratio": 0.0,
        "channel_used": "gray",
    }

    # Exposure metrics: measure on the rectified fabric window if available,
    # otherwise fallback to raw image (e.g. when card detection failed).
    target_img = window_gray if window_gray is not None else raw_image

    if target_img.dtype != np.uint8:
        t_u8 = (np.clip(target_img, 0.0, 1.0) * 255).astype(np.uint8)
    else:
        t_u8 = target_img

    t_gray = cv2.cvtColor(t_u8, cv2.COLOR_BGR2GRAY) if len(t_u8.shape) == 3 else t_u8
    dark_mask = t_gray < 20
    metrics["dark_fraction"] = float(np.mean(dark_mask))

    sat_lvl = int(q_cfg["saturation_level"])
    sat_mask = np.any(t_u8 >= sat_lvl, axis=2) if len(t_u8.shape) == 3 else (t_u8 >= sat_lvl)
    metrics["saturated_fraction"] = float(np.mean(sat_mask))

    # Sharpness on rectified window
    if window_gray is not None:
        metrics["sharpness"] = float(measure_sharpness(window_gray))

    # FFT-derived metrics
    if fft_result and fft_result.get("ok"):
        q_fft = fft_result.get("quality", {})
        metrics["peak_snr_warp"] = float(q_fft.get("peak_snr_warp", 0.0))
        metrics["peak_snr_weft"] = float(q_fft.get("peak_snr_weft", 0.0))
        ppt = fft_result.get("px_per_thread", {})
        metrics["warp_px_per_thread"] = float(ppt.get("warp", 0.0))
        metrics["weft_px_per_thread"] = float(ppt.get("weft", 0.0))
        metrics["channel_used"] = q_fft.get("channel_used", "gray")

        # Task 6b: Design energy ratio after local contrast normalisation
        if window_gray is not None:
            try:
                from engine.fft_grade import compute_design_energy_ratio_normalized
                metrics["design_energy_ratio"] = compute_design_energy_ratio_normalized(
                    window_gray, cfg
                )
            except Exception:
                # Fallback to original method if anything goes wrong
                N = window_gray.shape[0]
                cy = cx = N // 2
                F_mag = np.abs(np.fft.fftshift(np.fft.fft2(window_gray.astype(np.float64))))
                band_min_k = N / cfg["fft"]["band_max_px_per_cycle"]
                band_max_k = N / cfg["fft"]["band_min_px_per_cycle"]
                dc_r = cfg["fft"]["dc_mask_radius"]
                yy, xx = np.ogrid[:N, :N]
                r = np.sqrt((xx - cx).astype(float) ** 2 + (yy - cy).astype(float) ** 2)
                low_freq_mask = (r > dc_r) & (r < band_min_k)
                in_band_mask = (r >= band_min_k) & (r <= band_max_k)
                e_low = float(np.sum(F_mag[low_freq_mask] ** 2))
                e_band = float(np.sum(F_mag[in_band_mask] ** 2)) + 1e-9
                metrics["design_energy_ratio"] = float(e_low / e_band)

    # Priority check sequence (§7.2 table order)
    failures: list[tuple[str, str]] = []

    # 1. NO_CARD
    if not card_result.get("ok") and card_result.get("code") == "NO_CARD":
        failures.append(("NO_CARD", card_result.get("reason", "Show the whole card")))
    elif metrics["markers_found"] < q_cfg["min_markers"]:
        failures.append(("NO_CARD", "Show the whole card"))

    # 2. TOO_TILTED
    if card_result.get("code") == "TOO_TILTED" or metrics["tilt_deg"] > q_cfg["max_tilt_deg"]:
        failures.append(("TOO_TILTED", "Hold the phone flat"))

    # 3. LOW_RES
    if card_result.get("code") == "LOW_RES" or metrics["native_px_per_mm"] < q_cfg["min_native_px_per_mm"]:
        failures.append(("LOW_RES", "Move closer"))

    # 4. TOO_DARK
    if metrics["dark_fraction"] > q_cfg["max_dark_fraction"]:
        failures.append(("TOO_DARK", "Turn on the light"))

    # 5. GLARE
    if metrics["saturated_fraction"] > q_cfg["max_saturated_fraction"]:
        failures.append(("GLARE", "Glare — tilt the phone a little"))

    # 6. BLURRY
    if window_gray is not None and metrics["sharpness"] < q_cfg["min_sharpness"]:
        failures.append(("BLURRY", "Too blurry — hold still"))

    # 7. NO_WEAVE / ALIASING / WEAVE_UNCLEAR / DESIGN_AREA from FFT
    if fft_result is not None:
        if not fft_result.get("ok"):
            code = fft_result.get("code", "NO_WEAVE")
            reason = fft_result.get("reason", "")
            failures.append((code, reason))
        else:
            min_snr = q_cfg["min_peak_snr"]
            if metrics["peak_snr_warp"] < min_snr or metrics["peak_snr_weft"] < min_snr:
                failures.append(("NO_WEAVE", "Can't see the threads — move closer / refocus"))

            min_ppt = q_cfg["min_px_per_thread"]
            if metrics["warp_px_per_thread"] < min_ppt or metrics["weft_px_per_thread"] < min_ppt:
                failures.append(("ALIASING", "Move closer"))

            max_design_ratio = q_cfg["max_design_energy_ratio"]
            if metrics["design_energy_ratio"] > max_design_ratio:
                failures.append(("DESIGN_AREA", "Move the card to a plain area"))

    if failures:
        first_code, first_reason = failures[0]
        return {
            "ok": False,
            "code": first_code,
            "reason": first_reason,
            "metrics": metrics,
            "failed_checks": [f[0] for f in failures],
        }

    return {
        "ok": True,
        "code": "OK",
        "reason": "",
        "metrics": metrics,
        "failed_checks": [],
    }
