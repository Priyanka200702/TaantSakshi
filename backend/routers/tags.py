"""
backend/routers/tags.py
Tag generation endpoint: POST /tags/generate and PDF download
"""
from __future__ import annotations

import datetime
import secrets
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.auth import require_staff_or_admin
from backend.config import BASE_URL, TAGS_PDF_DIR
from backend.database import get_db
from backend.models import Tag, TagGenerationLog, User
from backend.schemas import TagGenerateRequest, TagGenerateResponse
from backend.services.qr_service import generate_tags_pdf, generate_unique_qr_ids

router = APIRouter(tags=["Tags"])


@router.post("/tags/generate", response_model=TagGenerateResponse)
def generate_tags(
    payload: TagGenerateRequest,
    user: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):
    """
    Generate unique printable QR tags for the authenticated staff member's cooperative.
    Saves tags with status 'blank' and creates a printable 54-tag A4 PDF sheet.
    """
    if not user.coop_id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_COOP", "message_en": "User is not assigned to a cooperative", "message_bn": "ব্যবহারকারী কোনো সমবায় সমিতির সাথে যুক্ত নয়"},
        )

    coop_id = user.coop_id or "COOP-ADMIN"
    count = payload.count

    # Generate distinct batch number
    ts_code = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
    rand_suffix = secrets.token_hex(2).upper()
    batch_no = f"BATCH-{coop_id}-{ts_code}-{rand_suffix}"

    # Query existing IDs to avoid any collision
    existing_ids = {row[0] for row in db.query(Tag.qr_id).all()}
    qr_ids = generate_unique_qr_ids(count=count, existing_ids=existing_ids)

    # Insert tags with status 'blank'
    for qid in qr_ids:
        tag = Tag(
            qr_id=qid,
            coop_id=coop_id,
            batch_no=batch_no,
            status="blank",
        )
        db.add(tag)

    # Generate printable 54-tag A4 PDF
    pdf_path = generate_tags_pdf(qr_ids=qr_ids, batch_no=batch_no, base_url=BASE_URL)

    # Log generation
    log_entry = TagGenerationLog(
        coop_id=coop_id,
        user_id=user.id,
        count=len(qr_ids),
        batch_no=batch_no,
        pdf_path=str(pdf_path),
        generated_at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
    )
    db.add(log_entry)
    db.commit()

    pdf_url = f"{BASE_URL}/tags/pdf/{pdf_path.name}"

    return TagGenerateResponse(
        batch_no=batch_no,
        count=len(qr_ids),
        pdf_url=pdf_url,
    )


@router.get("/tags/pdf/{filename}")
def download_tags_pdf(filename: str):
    """Serve generated tags PDF for printing."""
    # Sanitize filename
    clean_name = Path(filename).name
    pdf_path = TAGS_PDF_DIR / clean_name
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Tag PDF file not found")
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        filename=clean_name,
    )
