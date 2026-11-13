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
from engine.fingerprint import extract_fingerprint
from engine.match import match_fingerprints
from engine.quality import evaluate_quality


def _load_image(path_or_array: str | np.ndarray) -> np.ndarray:
    """Load image from disk if path, or return numpy array."""
    if isinstance(path_or_array, (str, Path)):
        p = str(path_or_array)
        img = cv2.imread(p)
        if img is None:
            raise FileNotFoundError(f"Image could not be read: {p}")
        return img
    elif isinstance(path_or_array, np.ndarray):
        return path_or_array
    else:
        raise TypeError(f"Expected file path or numpy array, got {type(path_or_array)}")


def quality_check(image_paths: list[str | np.ndarray]) -> dict[str, Any]:
    """
    Fast quality check used by verification flow and evaluation (§6.2).
    Returns {ok, code, reason, metrics}.
    """
    cfg = get_config()
    if not image_paths:
        return {"ok": False, "code": "NO_CARD", "reason": "No image frames provided", "metrics": {}}

    first_img = _load_image(image_paths[0])
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
    sat_level = int(cfg["quality"]["saturation_level"])
    clean_gray, _, _ = mask_glare(win_gray, saturation_level=sat_level)
    fft_res = run_fft_grade(clean_gray, card_res["px_per_mm"], cfg)
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

    # 1. Load burst frames and detect/rectify card
    t0 = time.perf_counter()
    raw_images: list[np.ndarray] = []
    rect_gray_frames: list[np.ndarray] = []
    rect_color_frames: list[np.ndarray] = []
    card_results: list[dict] = []

    for item in image_paths:
        img = _load_image(item)
        raw_images.append(img)
        c_res = detect_and_rectify(img, cfg)
        card_results.append(c_res)
        if c_res["ok"] and c_res["window_gray"] is not None:
            rect_gray_frames.append(c_res["window_gray"])
            rect_color_frames.append(c_res["window_color"])

    timings["card_detection"] = (time.perf_counter() - t0) * 1000

    # If no frames passed card detection, return Gate 1 failure from the first frame
    if not rect_gray_frames:
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

    # Use the best card result for metadata
    best_card = card_results[0]
    effective_scale = best_card["px_per_mm"]
    native_scale = best_card["native_px_per_mm"]

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
    t0 = time.perf_counter()
    fft_res = run_fft_grade(clean_gray, effective_scale, cfg, debug_dir=debug_dir)
    timings["fft_grade"] = (time.perf_counter() - t0) * 1000

    # 4. Quality Gate Evaluation (§7.2 priority sequence)
    # Note: evaluate exposure/glare on stacked_gray before inpainting
    primary_img = raw_images[0]
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
            "timings_ms": timings,
        }

    # 5. Fingerprint extraction (§7.8)
    t0 = time.perf_counter()
    fp_prefix = Path(image_paths[0]).stem if isinstance(image_paths[0], (str, Path)) else "fp"
    fp_result = extract_fingerprint(image_paths, out_dir=out_dir, cfg=cfg, prefix=fp_prefix)
    timings["fingerprint"] = (time.perf_counter() - t0) * 1000

    timings["total"] = (time.perf_counter() - t_start) * 1000

    # Success payload matching contract (§6.2)
    return {
        "ok": True,
        "code": "OK",
        "reason": "",
        "native_px_per_mm": native_scale,
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
    qc = quality_check(image_paths)
    if not qc["ok"]:
        return {
            "ok": False,
            "code": qc["code"],
            "reason": qc["reason"],
            "fingerprint": {"residual_path": None, "sift_path": None},
        }

    fp_prefix = Path(image_paths[0]).stem if isinstance(image_paths[0], (str, Path)) else "fp"
    fp_result = extract_fingerprint(image_paths, out_dir=out_dir, cfg=cfg, prefix=fp_prefix)
    return {
        "ok": True,
        "code": "OK",
        "reason": "",
        "fingerprint": fp_result,
    }


def match(fp_a: dict | str, fp_b: dict | str) -> dict[str, Any]:
    """
    Fingerprint comparison (§6.2, §7.9).
    """
    cfg = get_config()
    res = match_fingerprints(fp_a, fp_b, cfg=cfg)
    res["ok"] = True
    res["code"] = "OK"
    res["reason"] = ""
    return res
