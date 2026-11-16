"""
backend/services/vision_adapter.py
Safe integration adapter connecting backend to the existing read-only vision engine.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.config import BILINGUAL_MESSAGES, FINGERPRINTS_DIR, get_message

logger = logging.getLogger("tantsaakshi.vision_adapter")

# Set of recognized photo quality failure codes that allow tag release back to blank
QUALITY_FAILURE_CODES = {
    "NO_CARD",
    "TOO_TILTED",
    "LOW_RES",
    "TOO_DARK",
    "GLARE",
    "BLURRY",
    "NO_WEAVE",
    "ALIASING",
    "WEAVE_UNCLEAR",
    "DESIGN_AREA",
    "BAD_IMAGE",
}


def run_registration_analysis(
    photo_paths: list[str],
    qr_id: str,
) -> dict[str, Any]:
    """
    Execute full registration analysis on burst of 1..5 photos.
    Calls engine.analyze without modifying any engine code.

    Outputs are saved to private storage (FINGERPRINTS_DIR).
    """
    import engine

    target_out_dir = FINGERPRINTS_DIR / qr_id
    target_out_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = engine.analyze(
            image_paths=photo_paths,
            out_dir=str(target_out_dir),
            debug_dir=None,
        )
    except Exception as exc:
        logger.exception("Engine exception during analyze for %s: %s", qr_id, exc)
        return {
            "ok": False,
            "code": "ENGINE_ERROR",
            "is_quality_failure": False,
            "reason_en": f"Image processing failed: {exc}",
            "reason_bn": "ছবি প্রক্রিয়াকরণে অপ্রত্যাশিত ত্রুটি ঘটেছে।",
            "raw": {},
        }

    ok = bool(result.get("ok", False))
    code = result.get("code", "UNKNOWN" if not ok else "OK")
    reason = result.get("reason", "")
    is_quality = code in QUALITY_FAILURE_CODES

    # Fetch bilingual messages
    en_msg = get_message(code, "en", default=reason)
    bn_msg = get_message(code, "bn", default=reason)

    if not ok:
        return {
            "ok": False,
            "code": code,
            "is_quality_failure": is_quality,
            "reason_en": en_msg,
            "reason_bn": bn_msg,
            "raw": result,
        }

    # Extract fingerprint file path
    fp_dict = result.get("fingerprint", {})
    residual_path = fp_dict.get("residual_path")
    sift_path = fp_dict.get("sift_path")

    return {
        "ok": True,
        "code": "OK",
        "is_quality_failure": False,
        "ends_per_inch": result.get("ends_per_inch"),
        "picks_per_inch": result.get("picks_per_inch"),
        "irregularity": result.get("irregularity", {}),
        "defects": result.get("defects", {}),
        "grade": result.get("grade"),
        "grade_provisional": result.get("grade_provisional", True),
        "fingerprint": {
            "residual_path": residual_path,
            "sift_path": sift_path,
        },
        "fingerprint_path": residual_path,
        "raw": result,
    }


def run_verification_fingerprint(
    photo_paths: list[str],
    upload_id: str,
) -> dict[str, Any]:
    """
    Extract verification fingerprint from a new photograph burst.
    Calls engine.make_fingerprint without modifying any engine code.
    Saves fingerprint into unique directory verify_{upload_id}.
    """
    import engine

    target_out_dir = FINGERPRINTS_DIR / f"verify_{upload_id}"
    target_out_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = engine.make_fingerprint(
            image_paths=photo_paths,
            out_dir=str(target_out_dir),
        )
    except Exception as exc:
        logger.exception("Engine exception during make_fingerprint for %s: %s", upload_id, exc)
        return {
            "ok": False,
            "code": "ENGINE_ERROR",
            "is_quality_failure": False,
            "reason_en": f"Fingerprint extraction failed: {exc}",
            "reason_bn": "ফিঙ্গারপ্রিন্ট তৈরিতে ত্রুটি ঘটেছে।",
            "fingerprint": {},
        }

    ok = bool(result.get("ok", False))
    code = result.get("code", "UNKNOWN" if not ok else "OK")
    reason = result.get("reason", "")
    is_quality = code in QUALITY_FAILURE_CODES

    en_msg = get_message(code, "en", default=reason)
    bn_msg = get_message(code, "bn", default=reason)

    if not ok:
        return {
            "ok": False,
            "code": code,
            "is_quality_failure": is_quality,
            "reason_en": en_msg,
            "reason_bn": bn_msg,
            "fingerprint": {},
        }

    return {
        "ok": True,
        "code": "OK",
        "is_quality_failure": False,
        "fingerprint": result.get("fingerprint", {}),
        "reason_en": en_msg,
        "reason_bn": bn_msg,
    }


def compare_fingerprints(
    registered_fp: dict | str,
    verification_fp: dict | str,
) -> dict[str, Any]:
    """
    Compare registered and verification fingerprints.
    Calls engine.compat.match without modifying any engine code.
    Strictly preserves calibration rules:
      - If match is None (uncalibrated), returns result: 'not_calibrated'.
      - Never fakes 'genuine' or 'no_match'.
    """
    # Use compat.match function which safely handles file paths or dicts
    from engine.compat import match as compat_match

    try:
        match_res = compat_match(registered_fp, verification_fp)
    except Exception as exc:
        logger.exception("Engine exception during match: %s", exc)
        return {
            "ok": False,
            "result": "retake",
            "score": None,
            "reason": f"Matching failed: {exc}",
            "code": "MATCH_FAILED",
            "message_en": f"Matching failed: {exc}",
            "message_bn": get_message("MATCH_FAILED", "bn", default="ম্যাচিং প্রক্রিয়া ব্যর্থ হয়েছে।"),
            "calibrated": False,
        }

    calibrated = bool(match_res.get("calibrated", False))
    match_val = match_res.get("match")
    score = match_res.get("score")

    # Strictly enforce calibration requirements
    if not calibrated or match_val is None:
        return {
            "ok": True,
            "result": "not_calibrated",
            "score": None,
            "reason": get_message("NOT_CALIBRATED", "en"),
            "code": "NOT_CALIBRATED",
            "message_en": get_message("NOT_CALIBRATED", "en"),
            "message_bn": get_message("NOT_CALIBRATED", "bn"),
            "calibrated": False,
            "raw_score": score,
        }

    decision = "genuine" if match_val is True else "no_match"
    code = "GENUINE" if match_val is True else "NO_MATCH"
    reason = f"Verification completed with score {score:.4f}" if score is not None else get_message(code, "en")
    return {
        "ok": True,
        "result": decision,
        "score": score,
        "reason": reason,
        "code": code,
        "message_en": get_message(code, "en", default=reason),
        "message_bn": get_message(code, "bn"),
        "calibrated": True,
        "raw": match_res,
    }
