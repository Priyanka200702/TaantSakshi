"""
backend/services/verification_service.py
Fabric authenticity verification service adhering to calibration rules.
"""
from __future__ import annotations

import datetime
import json
import shutil
import uuid
from pathlib import Path
from fastapi import UploadFile, status
from sqlalchemy.orm import Session

from backend.auth import raise_bilingual_error
from backend.config import ALLOWED_EXTENSIONS, IMAGES_DIR, MAX_FILE_SIZE_BYTES, get_message
from backend.models import Saree, User, Verification
from backend.services.vision_adapter import compare_fingerprints, run_verification_fingerprint


def verify_saree_authenticity(
    db: Session,
    user: User,
    qr_id: str,
    upload_id: str | None,
    photos: list[UploadFile],
) -> dict:
    """
    Execute authenticity verification against the saree's registered fingerprint.
    Enforces calibration rule:
      If thresholds in config are null, returns 'not_calibrated'.
      Never returns genuine or no_match when uncalibrated.
      Returns 'retake' if verification photo quality check fails.
      Fingerprints stored in unique folder verify_{upload_id}.
      Always returns code, message_en, message_bn.
    """
    # 1. Check upload_id idempotency for verifications
    if upload_id:
        existing_ver = db.query(Verification).filter(Verification.upload_id == upload_id).first()
        if existing_ver:
            code = existing_ver.code or ("NOT_CALIBRATED" if existing_ver.match == "not_calibrated" else existing_ver.match.upper())
            return {
                "result": existing_ver.match,
                "score": existing_ver.score,
                "reason": existing_ver.reason,
                "code": code,
                "message_en": existing_ver.message_en or existing_ver.reason or get_message(code, "en"),
                "message_bn": existing_ver.message_bn or get_message(code, "bn", default=existing_ver.reason or ""),
            }

    # Generate unique upload identifier if not provided
    effective_upload_id = upload_id or f"{qr_id}_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    # 2. Check saree registration existence
    saree = db.query(Saree).filter(Saree.qr_id == qr_id).first()
    if not saree:
        raise_bilingual_error(status.HTTP_404_NOT_FOUND, "TAG_UNKNOWN")

    # 3. Check saree processing status
    if saree.proc_status != "done":
        if saree.proc_status in ("queued", "processing"):
            return {
                "result": "retake",
                "score": None,
                "reason": get_message("REGISTRATION_PENDING", "en"),
                "code": "REGISTRATION_PENDING",
                "message_en": get_message("REGISTRATION_PENDING", "en"),
                "message_bn": get_message("REGISTRATION_PENDING", "bn"),
            }
        else:
            return {
                "result": "retake",
                "score": None,
                "reason": get_message("REGISTRATION_FAILED", "en"),
                "code": "REGISTRATION_FAILED",
                "message_en": get_message("REGISTRATION_FAILED", "en"),
                "message_bn": get_message("REGISTRATION_FAILED", "bn"),
            }

    # 4. Check registered fingerprint availability
    if not saree.fingerprint_path or not Path(saree.fingerprint_path).exists():
        return {
            "result": "retake",
            "score": None,
            "reason": get_message("FINGERPRINT_NOT_FOUND", "en"),
            "code": "FINGERPRINT_NOT_FOUND",
            "message_en": get_message("FINGERPRINT_NOT_FOUND", "en"),
            "message_bn": get_message("FINGERPRINT_NOT_FOUND", "bn"),
        }

    # 5. Check uploaded verification photos
    if not photos or len(photos) == 0:
        raise_bilingual_error(status.HTTP_400_BAD_REQUEST, "BAD_IMAGE", "At least one verification photograph is required")

    verify_burst = photos[:5]

    # 6. Save verification photographs
    verify_dir = IMAGES_DIR / f"verify_{effective_upload_id}"
    verify_dir.mkdir(parents=True, exist_ok=True)

    saved_photo_paths: list[str] = []
    for idx, upload_file in enumerate(verify_burst):
        ext = Path(upload_file.filename or "image.jpg").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            ext = ".jpg"
        target_file = verify_dir / f"verify_frame_{idx:02d}{ext}"

        upload_file.file.seek(0)
        with open(target_file, "wb") as f_out:
            shutil.copyfileobj(upload_file.file, f_out)

        if target_file.stat().st_size > MAX_FILE_SIZE_BYTES:
            raise_bilingual_error(status.HTTP_400_BAD_REQUEST, "BAD_IMAGE", "File exceeds maximum permitted size")

        saved_photo_paths.append(str(target_file))

    primary_verify_photo = saved_photo_paths[0]

    # 7. Extract fingerprint from verification photograph
    fp_res = run_verification_fingerprint(saved_photo_paths, effective_upload_id)
    if not fp_res["ok"]:
        # Quality check failed: save attempt and return 'retake'
        code = fp_res.get("code", "BAD_IMAGE")
        reason_en = fp_res.get("reason_en", get_message(code, "en", default="Photo quality check failed"))
        reason_bn = fp_res.get("reason_bn", get_message(code, "bn", default="ছবির গুণমান উপযুক্ত নয়। অনুগ্রহ করে আবার ছবি তুলুন।"))
        rec = Verification(
            qr_id=qr_id,
            upload_id=upload_id,
            image_path=primary_verify_photo,
            score=None,
            match="retake",
            reason=reason_en,
            code=code,
            message_en=reason_en,
            message_bn=reason_bn,
            by_user=user.name,
            at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
        )
        db.add(rec)
        db.commit()

        return {
            "result": "retake",
            "score": None,
            "reason": reason_en,
            "code": code,
            "message_en": reason_en,
            "message_bn": reason_bn,
        }

    verify_fp = fp_res["fingerprint"]

    # 8. Compare against registered fingerprint
    reg_residual = saree.fingerprint_path
    reg_sift = str(Path(reg_residual).parent / Path(reg_residual).name.replace("residual.npz", "sift.npz"))
    if not Path(reg_sift).exists():
        reg_sift = None

    reg_fp_dict = {"residual_path": reg_residual, "sift_path": reg_sift}

    match_result = compare_fingerprints(reg_fp_dict, verify_fp)

    result_decision = match_result["result"]  # genuine | no_match | not_calibrated | retake
    result_score = match_result.get("score")
    result_reason = match_result.get("reason")
    result_code = match_result.get("code", result_decision.upper())
    result_message_en = match_result.get("message_en", result_reason)
    result_message_bn = match_result.get("message_bn", get_message(result_code, "bn"))

    # 9. Store verification attempt in database
    rec = Verification(
        qr_id=qr_id,
        upload_id=upload_id,
        image_path=primary_verify_photo,
        score=result_score,
        match=result_decision,
        reason=result_reason,
        code=result_code,
        message_en=result_message_en,
        message_bn=result_message_bn,
        by_user=user.name,
        at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
    )
    db.add(rec)
    db.commit()

    return {
        "result": result_decision,
        "score": result_score,
        "reason": result_reason,
        "code": result_code,
        "message_en": result_message_en,
        "message_bn": result_message_bn,
    }
