"""
backend/routers/verification.py
Fabric authenticity verification endpoint: POST /verify/{qr_id}
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from backend.auth import require_seller_or_staff
from backend.database import get_db
from backend.models import User
from backend.schemas import VerificationResponse
from backend.services.verification_service import verify_saree_authenticity

router = APIRouter(tags=["Verification"])


@router.post("/verify/{qr_id}", response_model=VerificationResponse)
def verify_saree(
    qr_id: str,
    upload_id: str | None = Form(None, description="Idempotent verification request ID"),
    photos: list[UploadFile] = File(..., description="New verification photograph burst"),
    user: User = Depends(require_seller_or_staff),
    db: Session = Depends(get_db),
):
    """
    Verify fabric authenticity using a new photograph against registered identity.
    Strictly enforces calibration rules:
      - If calibration threshold is null, returns 'not_calibrated'.
      - Never invents scores or returns fake genuine results.
      - Returns 'retake' if quality check fails.
      - Result is strictly one of: genuine | no_match | not_calibrated | retake.
    """
    res = verify_saree_authenticity(
        db=db,
        user=user,
        qr_id=qr_id.strip(),
        upload_id=upload_id.strip() if upload_id else None,
        photos=photos,
    )
    return VerificationResponse(
        result=res["result"],
        score=res["score"],
        reason=res["reason"],
        code=res.get("code"),
        message_en=res.get("message_en"),
        message_bn=res.get("message_bn"),
    )
