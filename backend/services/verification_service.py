"""
backend/services/verification_service.py
Fabric authenticity verification service adhering to calibration rules.
"""
from __future__ import annotations

import datetime
import json
import shutil
from pathlib import Path
from fastapi import UploadFile, status
from sqlalchemy.orm import Session

from backend.auth import raise_bilingual_error
from backend.config import ALLOWED_EXTENSIONS, IMAGES_DIR, MAX_FILE_SIZE_BYTES
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
    """
    # 1. Check upload_id idempotency for verifications
    if upload_id:
        existing_ver = db.query(Verification).filter(Verification.upload_id == upload_id).first()
        if existing_ver:
            return {
                "result": existing_ver.match,
                "score": existing_ver.score,
                "reason": existing_ver.reason,
            }

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
                "reason": "Saree registration image processing is still underway. Please wait for completion.",
            }
        else:
            return {
                "result": "retake",
                "score": None,
                "reason": "Original saree registration failed quality analysis. Verification cannot be performed.",
            }

    # 4. Check registered fingerprint availability
    if not saree.fingerprint_path or not Path(saree.fingerprint_path).exists():
        return {
            "result": "retake",
            "score": None,
            "reason": "Registered fingerprint file is not available on server.",
        }

    # 5. Check uploaded verification photos
    if not photos or len(photos) == 0:
        raise_bilingual_error(status.HTTP_400_BAD_REQUEST, "BAD_IMAGE", "At least one verification photograph is required")

    verify_burst = photos[:5]

    # 6. Save verification photographs
    ts_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    verify_dir = IMAGES_DIR / f"verify_{qr_id}_{ts_str}"
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
    fp_res = run_verification_fingerprint(saved_photo_paths, qr_id)
    if not fp_res["ok"]:
        # Quality check failed: save attempt and return 'retake'
        rec = Verification(
            qr_id=qr_id,
            upload_id=upload_id,
            image_path=primary_verify_photo,
            score=None,
            match="retake",
            reason=fp_res.get("reason_en", "Photo quality check failed"),
            by_user=user.name,
            at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
        )
        db.add(rec)
        db.commit()

        return {
            "result": "retake",
            "score": None,
            "reason": fp_res.get("reason_en", "Photograph quality unsuitable. Please retake photo."),
        }

    verify_fp = fp_res["fingerprint"]

    # 8. Compare against registered fingerprint
    # Find matching SIFT file if available
    reg_residual = saree.fingerprint_path
    reg_sift = str(Path(reg_residual).parent / Path(reg_residual).name.replace("residual.npz", "sift.npz"))
    if not Path(reg_sift).exists():
        reg_sift = None

    reg_fp_dict = {"residual_path": reg_residual, "sift_path": reg_sift}

    match_result = compare_fingerprints(reg_fp_dict, verify_fp)

    result_decision = match_result["result"]  # genuine | no_match | not_calibrated | retake
    result_score = match_result.get("score")
    result_reason = match_result.get("reason")

    # 9. Store verification attempt in database
    rec = Verification(
        qr_id=qr_id,
        upload_id=upload_id,
        image_path=primary_verify_photo,
        score=result_score,
        match=result_decision,
        reason=result_reason,
        by_user=user.name,
        at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
    )
    db.add(rec)
    db.commit()

    return {
        "result": result_decision,
        "score": result_score,
        "reason": result_reason,
    }
