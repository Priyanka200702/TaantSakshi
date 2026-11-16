"""
backend/routers/sarees.py
Saree registration endpoint: POST /saree and processing status: GET /saree/{qr_id}
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from backend.auth import get_current_user, raise_bilingual_error, require_staff_or_admin
from backend.config import get_message
from backend.database import get_db
from backend.models import Saree, User
from backend.schemas import SareeRegistrationResponse, SareeStatusResponse
from backend.services.registration_service import validate_and_register_saree

router = APIRouter(tags=["Sarees"])


@router.post("/saree", response_model=SareeRegistrationResponse)
def register_saree(
    qr_id: str = Form(..., description="QR ID on physical tag"),
    batch_id: str = Form(..., description="Associated registration batch ID"),
    upload_id: str = Form(..., description="Client-generated idempotent upload UUID"),
    phone_model: str | None = Form(None, description="Client device model"),
    photos: list[UploadFile] = File(..., description="Burst of up to 5 original JPEG photos"),
    user: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):
    """
    Register a genuine handloom saree and upload original burst photographs.
    Validates QR status, locks tag as 'registered', preserves full-resolution photos,
    and returns {'status': 'queued'} immediately.
    """
    res = validate_and_register_saree(
        db=db,
        user=user,
        qr_id=qr_id.strip(),
        batch_id=batch_id.strip(),
        upload_id=upload_id.strip(),
        phone_model=phone_model.strip() if phone_model else None,
        photos=photos,
    )
    return SareeRegistrationResponse(status=res["status"])


@router.get("/saree/{qr_id}", response_model=SareeStatusResponse)
def get_saree_status(
    qr_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Check vision engine processing status for a registered saree.
    Enforces cooperative isolation: staff may only inspect sarees from their cooperative.
    """
    clean_qr = qr_id.strip()
    saree = db.query(Saree).filter(Saree.qr_id == clean_qr).first()
    if not saree:
        raise_bilingual_error(status.HTTP_404_NOT_FOUND, "TAG_UNKNOWN")

    # Enforce cooperative isolation
    if user.role != "admin" and user.coop_id:
        if saree.batch and saree.batch.coop_id != user.coop_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message_en": "Cannot access saree from another cooperative", "message_bn": "অন্য সমবায় সমিতির শাড়ি দেখতে পারবেন না"},
            )

    bn_reason = None
    if saree.proc_error_code:
        bn_reason = get_message(saree.proc_error_code, "bn", default=saree.proc_error_reason or "")

    return SareeStatusResponse(
        status=saree.proc_status,
        grade=saree.grade,
        ends_per_inch=saree.epi,
        picks_per_inch=saree.ppi,
        reason=saree.proc_error_reason,
        reason_bn=bn_reason,
    )
