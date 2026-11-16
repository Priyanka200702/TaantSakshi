"""
backend/routers/certificates.py
Public digital authenticity certificate endpoint: GET /c/{qr_id}
"""
from __future__ import annotations

import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.config import BACKEND_DIR, SCAN_WARNING_THRESHOLD, SCAN_WINDOW_HOURS
from backend.database import get_db
from backend.models import Batch, CertificateScan, Coop, Saree, Tag, Weaver

router = APIRouter(tags=["Certificates"])

templates = Jinja2Templates(directory=str(BACKEND_DIR / "templates"))


@router.get("/c/{qr_id}", response_class=HTMLResponse)
def view_public_certificate(
    qr_id: str,
    request: Request,
    lang: str = "bn",  # Default to Bengali for local accessibility
    db: Session = Depends(get_db),
):
    """
    Public digital authenticity certificate.
    Accessible by consumers scanning the QR code without login.
    Renders exactly the 4 required certificate states:
      1. Unknown Tag
      2. Blank Tag
      3. Processing / Queued
      4. Full Authentic Certificate
    Logs certificate scan and triggers anti-copy warning if threshold exceeded.
    Protects weaver identity if permission is not granted.
    Never exposes internal tokens, passwords, or private fingerprint files.
    """
    clean_qr = qr_id.strip()
    active_lang = "bn" if lang.lower().startswith("bn") else "en"

    # 1. Fetch Tag record
    tag = db.query(Tag).filter(Tag.qr_id == clean_qr).first()

    # 2. Log Certificate Scan if tag exists or log probe
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")[:500]

    warning_repeated_scan = False

    if tag:
        scan_log = CertificateScan(
            qr_id=clean_qr,
            scanned_at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
            ip_address=client_ip,
            user_agent=user_agent,
            approximate_location=None,
        )
        db.add(scan_log)
        db.commit()

        # Task 9: Count distinct devices/IPs within time window (not total scans)
        window_start = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(hours=SCAN_WINDOW_HOURS)
        distinct_devices = (
            db.query(CertificateScan.ip_address)
            .filter(
                CertificateScan.qr_id == clean_qr,
                CertificateScan.scanned_at >= window_start,
            )
            .distinct()
            .count()
        )
        # Warning if distinct devices in time window exceed threshold or if tag is marked sold
        if distinct_devices >= SCAN_WARNING_THRESHOLD or tag.status == "sold":
            warning_repeated_scan = True

    # 3. Determine State
    # State 1: Unknown Tag
    if not tag:
        return templates.TemplateResponse(
            request,
            "certificate.html",
            {
                "state": 1,
                "qr_id": clean_qr,
                "lang": active_lang,
                "warning_repeated_scan": False,
            },
            status_code=404,
        )

    # State 2: Blank Tag (printed but not yet registered)
    if tag.status == "blank":
        coop = db.query(Coop).filter(Coop.id == tag.coop_id).first()
        return templates.TemplateResponse(
            request,
            "certificate.html",
            {
                "state": 2,
                "qr_id": clean_qr,
                "coop": coop,
                "lang": active_lang,
                "warning_repeated_scan": warning_repeated_scan,
            },
        )

    # Fetch Saree record
    saree = db.query(Saree).filter(Saree.qr_id == clean_qr).first()

    # State 3: Processing / Queued
    if not saree or saree.proc_status in ("queued", "processing"):
        return templates.TemplateResponse(
            request,
            "certificate.html",
            {
                "state": 3,
                "qr_id": clean_qr,
                "tag": tag,
                "lang": active_lang,
                "warning_repeated_scan": warning_repeated_scan,
            },
        )

    # Saree registration failed quality checks
    if saree.proc_status == "failed":
        return templates.TemplateResponse(
            request,
            "certificate.html",
            {
                "state": 5,
                "qr_id": clean_qr,
                "saree": saree,
                "tag": tag,
                "lang": active_lang,
                "warning_repeated_scan": warning_repeated_scan,
            },
        )

    # State 4: Full Digital Certificate
    batch = db.query(Batch).filter(Batch.id == saree.batch_id).first()
    coop = db.query(Coop).filter(Coop.id == tag.coop_id).first()
    weaver = db.query(Weaver).filter(Weaver.id == batch.weaver_id).first() if batch else None

    # Format registration date
    reg_date_str = ""
    if saree.registered_at:
        reg_date_str = saree.registered_at.strftime("%d %b %Y")

    return templates.TemplateResponse(
        request,
        "certificate.html",
        {
            "state": 4,
            "qr_id": clean_qr,
            "saree": saree,
            "tag": tag,
            "batch": batch,
            "coop": coop,
            "weaver": weaver,
            "reg_date": reg_date_str,
            "lang": active_lang,
            "warning_repeated_scan": warning_repeated_scan,
        },
    )


@router.get("/c/{qr_id}/photo")
def get_certificate_photo(qr_id: str, db: Session = Depends(get_db)):
    """
    Task 11: Serve a downscaled display copy of the registered fabric photo.
    Never exposes internal fingerprint (.npz) files.
    """
    clean_qr = qr_id.strip()
    saree = db.query(Saree).filter(Saree.qr_id == clean_qr).first()
    if not saree or not saree.image_path:
        raise HTTPException(status_code=404, detail="Photo not registered for this saree")

    orig_path = Path(saree.image_path)
    if not orig_path.exists():
        raise HTTPException(status_code=404, detail="Registered photo file not found on disk")

    # Generate or reuse cached downscaled display copy
    display_path = orig_path.parent / f"{orig_path.stem}_display.jpg"
    if not display_path.exists():
        try:
            from PIL import Image
            with Image.open(orig_path) as im:
                im = im.convert("RGB")
                im.thumbnail((800, 800))
                im.save(display_path, "JPEG", quality=85)
        except Exception:
            return FileResponse(str(orig_path), media_type="image/jpeg")

    return FileResponse(str(display_path), media_type="image/jpeg")
