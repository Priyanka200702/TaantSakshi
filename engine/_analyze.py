"""
engine/_analyze.py
Top-level orchestration pipeline for the TantSaakshi vision engine.

Implements §6.1, §6.2:
  photo(s) -> detect card -> quality gate 1
           -> rectify window (canonical scale)
           -> enhance (stack burst, flat-field)
           -> quality gate 2 (sharpness, glare, dark, design-energy, aliasing)
           -> FFT grade: ends/inch, picks/inch, irregularity, defects, grade
           -> fingerprint (Step 8)
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from engine.card import detect_and_rectify
from engine.config import get_config
from engine.debug import save_debug_images
from engine.enhance import (
    flatfield_correct,
    mask_glare,
    stack_burst_frames,
)
from engine.fft_grade import run_fft_grade
from engine.fingerprint import extract_fingerprint, extract_fingerprint_from_window
from engine.match import match_fingerprints
from engine.quality import evaluate_quality


def _load_image(path_or_array: str | np.ndarray) -> np.ndarray:
    """
    Load image from disk if path, or return numpy array.
    Task 5: supports .heic/.heif via pillow-heif; on failure returns None
    (caller must check and return BAD_IMAGE with reason 'Save photos as JPEG').
    """
    if isinstance(path_or_array, (str, Path)):
        p = str(path_or_array)
        ext = Path(p).suffix.lower()
        if ext in (".heic", ".heif"):
            img = _load_heic(p)
        else:
            img = cv2.imread(p)
        if img is None:
            raise FileNotFoundError(f"Image could not be read: {p}")
        return img
    elif isinstance(path_or_array, np.ndarray):
        return path_or_array
    else:
        raise TypeError(f"Expected file path or numpy array, got {type(path_or_array)}")


def _load_heic(path: str) -> np.ndarray | None:
    """
    Task 5: Load a HEIC/HEIF file using pillow-heif.
    Returns a BGR numpy array, or None if loading fails.
    """
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        from PIL import Image
        pil_img = Image.open(path)
        pil_img = pil_img.convert("RGB")
        arr = np.array(pil_img, dtype=np.uint8)
        # Convert RGB -> BGR for OpenCV convention
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception:
        # pillow_heif not installed or file unreadable
        return None


def quality_check(image_paths: list[str | np.ndarray]) -> dict[str, Any]:
    """
    Fast quality check used by verification flow and evaluation (§6.2).
    Returns {ok, code, reason, metrics}.
    """
    cfg = get_config()
    if not image_paths:
        return {"ok": False, "code": "NO_CARD", "reason": "No image frames provided", "metrics": {}}

    try:
        first_img = _load_image(image_paths[0])
        if first_img is None or first_img.size == 0:
            return {"ok": False, "code": "BAD_IMAGE", "reason": "First image is empty or invalid", "metrics": {}}
    except Exception as e:
        return {"ok": False, "code": "BAD_IMAGE", "reason": f"Failed to load image: {e}", "metrics": {}}

    card_res = detect_and_rectify(first_img, cfg)

    # If card detection failed at Gate 1
    if not card_res["ok"]:
        q_eval = evaluate_quality(first_img, card_res, None, None, cfg)
        return {
            "ok": False,
            "code": q_eval["code"],
            "reason": q_eval["reason"],
            "metrics": q_eval["metrics"],
        }

    # Evaluate Gate 2 checks on rectified window
    win_gray = card_res["window_gray"]
    win_color = card_res.get("window_color")
    sat_level = int(cfg["quality"]["saturation_level"])
    clean_gray, _, _ = mask_glare(win_gray, saturation_level=sat_level)
    fft_input = win_color if win_color is not None else clean_gray
    fft_res = run_fft_grade(fft_input, card_res["px_per_mm"], cfg)
    q_eval = evaluate_quality(first_img, card_res, win_gray, fft_res, cfg)

    return {
        "ok": q_eval["ok"],
        "code": q_eval["code"],
        "reason": q_eval["reason"],
        "metrics": q_eval["metrics"],
    }


def analyze(
    image_paths: list[str | np.ndarray],
    out_dir: str,
    debug_dir: str | None = None,
) -> dict[str, Any]:
    """
    One-call registration analysis (§6.2).
    Processes burst of 1..N frames and returns full registration metrics.
    """
    t_start = time.perf_counter()
    timings: dict[str, float] = {}

    cfg = get_config()
    if not image_paths:
        return {
            "ok": False,
            "code": "NO_CARD",
            "reason": "No image frames provided",
            "timings_ms": {"total": 0.0},
        }

    # 1. Load burst frames (Item 9: never raise, return BAD_IMAGE)
    t0 = time.perf_counter()
    raw_images: list[np.ndarray] = []
    for item in image_paths:
        try:
            img = _load_image(item)
            if img is None or img.size == 0:
                timings["total"] = (time.perf_counter() - t_start) * 1000
                return {
                    "ok": False,
                    "code": "BAD_IMAGE",
                    "reason": f"Image is empty or unreadable: {item}",
                    "timings_ms": timings,
                }
            raw_images.append(img)
        except FileNotFoundError as e:
            # Task 5: distinguish HEIC load failure from general missing file
            path_str = str(item)
            ext = Path(path_str).suffix.lower() if isinstance(item, (str, Path)) else ""
            if ext in (".heic", ".heif"):
                reason = "Save photos as JPEG"
            else:
                reason = f"Failed to load image: {e}"
            timings["total"] = (time.perf_counter() - t_start) * 1000
            return {
                "ok": False,
                "code": "BAD_IMAGE",
                "reason": reason,
                "timings_ms": timings,
            }
        except Exception as e:
            timings["total"] = (time.perf_counter() - t_start) * 1000
            return {
                "ok": False,
                "code": "BAD_IMAGE",
                "reason": f"Failed to load image: {e}",
                "timings_ms": timings,
            }

    # Detect cards across burst frames
    card_results: list[dict] = []
    for img in raw_images:
        c_res = detect_and_rectify(img, cfg)
        card_results.append(c_res)

    timings["card_detection"] = (time.perf_counter() - t0) * 1000

    # Item 7: Filter frames that passed card detection
    good_indices = [i for i, c in enumerate(card_results) if c.get("ok")]

    if not good_indices:
        # None passed Gate 1: evaluate Gate 1 failure on the first frame
        first_img = raw_images[0]
        first_card = card_results[0]
        q_eval = evaluate_quality(first_img, first_card, None, None, cfg)
        timings["total"] = (time.perf_counter() - t_start) * 1000
        return {
            "ok": False,
            "code": q_eval["code"],
            "reason": q_eval["reason"],
            "quality": q_eval["metrics"],
            "timings_ms": timings,
        }

    # Item 7: Pick the BEST card result among frames that passed (lowest tilt, highest native res)
    best_idx = sorted(
        good_indices,
        key=lambda i: (card_results[i]["tilt_deg"], -card_results[i]["native_px_per_mm"])
    )[0]
    best_card = card_results[best_idx]
    primary_img = raw_images[best_idx]

    # Item 8: Rectify all frames of a burst at ONE common scale = min(native of all good frames, canonical), so stacking works
    canonical_scale = float(cfg["rectify"]["canonical_px_per_mm"])
    min_native = min(card_results[i]["native_px_per_mm"] for i in good_indices)
    common_scale = min(min_native, canonical_scale)

    rect_gray_frames: list[np.ndarray] = []
    rect_color_frames: list[np.ndarray] = []
    for i in good_indices:
        c_rect = detect_and_rectify(raw_images[i], cfg, target_px_per_mm=common_scale)
        if c_rect["ok"] and c_rect["window_gray"] is not None:
            rect_gray_frames.append(c_rect["window_gray"])
            rect_color_frames.append(c_rect["window_color"])

    # 2. Multi-frame enhancement & stacking (§8)
    t0 = time.perf_counter()
    top_k = int(cfg["enhance"]["stack_top_k"])
    stacked_gray, n_stacked = stack_burst_frames(rect_gray_frames, top_k=top_k)
    timings["stacking"] = (time.perf_counter() - t0) * 1000

    # Glare masking and clean-up
    t0 = time.perf_counter()
    sat_level = int(cfg["quality"]["saturation_level"])
    clean_gray, glare_mask, glare_frac = mask_glare(stacked_gray, saturation_level=sat_level)
    timings["glare_masking"] = (time.perf_counter() - t0) * 1000

    # 3. FFT Analysis & Provisional Grading (§7.3 - §7.7)
    # Task 6a: use colour window if available so run_fft_grade can select best contrast channel
    t0 = time.perf_counter()
    fft_input = rect_color_frames[0] if rect_color_frames and rect_color_frames[0] is not None else clean_gray
    fft_res = run_fft_grade(fft_input, common_scale, cfg, debug_dir=debug_dir)
    timings["fft_grade"] = (time.perf_counter() - t0) * 1000

    # 4. Quality Gate Evaluation (§7.2 priority sequence)
    q_eval = evaluate_quality(primary_img, best_card, stacked_gray, fft_res, cfg)

    # 5. Debug artifact export (§7.10)
    if debug_dir:
        t0 = time.perf_counter()
        save_debug_images(
            debug_dir=debug_dir,
            raw_img=primary_img,
            card_result=best_card,
            window_color=rect_color_frames[0] if rect_color_frames else None,
            fft_result=fft_res,
        )
        timings["debug_export"] = (time.perf_counter() - t0) * 1000

    timings["total"] = (time.perf_counter() - t_start) * 1000

    # If any quality check failed, return failing status with reason
    if not q_eval["ok"]:
        return {
            "ok": False,
            "code": q_eval["code"],
            "reason": q_eval["reason"],
            "quality": q_eval["metrics"],
            "n_stacked": n_stacked,
            "timings_ms": timings,
        }

    # 6. Fingerprint extraction (§7.8) - Item 9: never raise, return codes BAD_IMAGE / FINGERPRINT_FAILED
    t0 = time.perf_counter()
    fp_prefix = Path(image_paths[0]).stem if isinstance(image_paths[0], (str, Path)) else "fp"

    # Task 4: pass the validated rotation angle (or 0 if validation failed)
    # fft_res["rotation_source"] == "measured" means validation passed
    fp_rotation_deg = float(fft_res.get("rotation_angle_deg", 0.0))
    fp_rotation_source = fft_res.get("rotation_source", "card_axes")

    try:
        fp_result = extract_fingerprint_from_window(
            window=stacked_gray,
            px_per_mm=common_scale,
            out_dir=out_dir,
            cfg=cfg,
            prefix=fp_prefix,
            rotation_angle_deg=fp_rotation_deg,
            rotation_source=fp_rotation_source,
        )
    except Exception as e:
        err_s = str(e)
        code = "LOW_RES_FINGERPRINT" if "LOW_RES_FINGERPRINT" in err_s else "FINGERPRINT_FAILED"
        timings["total"] = (time.perf_counter() - t_start) * 1000
        return {
            "ok": False,
            "code": code,
            "reason": f"Fingerprint extraction failed: {e}",
            "quality": q_eval["metrics"],
            "n_stacked": n_stacked,
            "timings_ms": timings,
        }

    timings["fingerprint"] = (time.perf_counter() - t0) * 1000
    timings["total"] = (time.perf_counter() - t_start) * 1000

    # Success payload matching contract (§6.2)
    return {
        "ok": True,
        "code": "OK",
        "reason": "",
        "n_stacked": n_stacked,
        "native_px_per_mm": best_card["native_px_per_mm"],
        "px_per_thread": fft_res.get("px_per_thread", {}),
        "ends_per_inch": fft_res.get("ends_per_inch"),
        "picks_per_inch": fft_res.get("picks_per_inch"),
        "warp_angle_deg": fft_res.get("warp_angle_deg"),
        "weft_angle_deg": fft_res.get("weft_angle_deg"),
        "irregularity": fft_res.get("irregularity", {}),
        "defects": fft_res.get("defects", {}),
        "grade": fft_res.get("grade"),
        "grade_provisional": True,
        "quality": q_eval["metrics"],
        "fingerprint": fp_result,
        "timings_ms": timings,
    }


def make_fingerprint(image_paths: list[str | np.ndarray], out_dir: str) -> dict[str, Any]:
    """
    Verification flow: quality check + fingerprint only (§6.2).
    """
    cfg = get_config()
    try:
        qc = quality_check(image_paths)
    except Exception as e:
        return {
            "ok": False,
            "code": "BAD_IMAGE",
            "reason": f"Failed to check image: {e}",
            "fingerprint": {"residual_path": None, "sift_path": None},
        }

    if not qc["ok"]:
        return {
            "ok": False,
            "code": qc["code"],
            "reason": qc["reason"],
            "fingerprint": {"residual_path": None, "sift_path": None},
        }

    fp_prefix = Path(image_paths[0]).stem if isinstance(image_paths[0], (str, Path)) else "fp"
    try:
        fp_result = extract_fingerprint(image_paths, out_dir=out_dir, cfg=cfg, prefix=fp_prefix)
        return {
            "ok": True,
            "code": "OK",
            "reason": "",
            "fingerprint": fp_result,
        }
    except Exception as e:
        err_s = str(e)
        code = "LOW_RES_FINGERPRINT" if "LOW_RES_FINGERPRINT" in err_s else "FINGERPRINT_FAILED"
        return {
            "ok": False,
            "code": code,
            "reason": f"Fingerprint extraction failed: {e}",
            "fingerprint": {"residual_path": None, "sift_path": None},
        }


def match(fp_a: dict | str, fp_b: dict | str) -> dict[str, Any]:
    """
    Fingerprint comparison (§6.2, §7.9).
    """
    cfg = get_config()
    try:
        res = match_fingerprints(fp_a, fp_b, cfg=cfg)
        res["ok"] = True
        res["code"] = "OK"
        res["reason"] = ""
        return res
    except Exception as e:
        return {
            "ok": False,
            "code": "MATCH_FAILED",
            "reason": f"Match failed: {e}",
            "match": None,
            "score": None,
            "score_residual": None,
            "inliers": 0,
            "calibrated": False,
            "method": cfg.get("fingerprint", {}).get("method", "residual"),
            "details": {},
        }
