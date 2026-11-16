"""
backend/routers/admin.py
Admin portal endpoint: GET /admin and CSV export: GET /admin/export.csv
"""
from __future__ import annotations

import csv
import io
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.auth import decode_access_token, verify_pin
from backend.config import BACKEND_DIR
from backend.database import get_db
from backend.models import Batch, Coop, Saree, Tag, User, Verification, Weaver

router = APIRouter(tags=["Admin"])

templates = Jinja2Templates(directory=str(BACKEND_DIR / "templates"))
basic_security = HTTPBasic(auto_error=False)


def authenticate_admin_request(
    request: Request,
    token: str | None = Query(None),
    credentials: HTTPBasicCredentials | None = Depends(basic_security),
    db: Session = Depends(get_db),
) -> User:
    """
    Authenticate administrative access via Bearer header, Query token, or HTTP Basic Auth.
    Ensures role == 'admin'.
    """
    # 1. Check Bearer token in Authorization header
    auth_hdr = request.headers.get("Authorization")
    raw_token = None
    if auth_hdr and auth_hdr.startswith("Bearer "):
        raw_token = auth_hdr.split(" ", 1)[1]
    elif token:
        raw_token = token

    if raw_token:
        try:
            payload = decode_access_token(raw_token)
            user_id = payload.get("sub")
            user = db.query(User).filter(User.id == user_id).first()
            if user and user.role == "admin":
                return user
        except Exception:
            pass

    # 2. Check HTTP Basic Auth (Phone as username, PIN as password)
    if credentials:
        user = db.query(User).filter(User.phone == credentials.username.strip()).first()
        if user and user.role == "admin" and verify_pin(credentials.password.strip(), user.pin_hash):
            return user

    # Raise 401 with WWW-Authenticate header to trigger browser login prompt
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin access required. Provide admin token or HTTP Basic credentials (phone & PIN).",
        headers={"WWW-Authenticate": "Basic"},
    )


@router.get("/admin", response_class=HTMLResponse)
def view_admin_dashboard(
    request: Request,
    admin_user: User = Depends(authenticate_admin_request),
    db: Session = Depends(get_db),
):
    """
    Admin dashboard displaying all saree registrations, computer vision thread density metrics,
    quality grades, and authenticity verification records.
    """
    sarees = db.query(Saree).order_by(Saree.registered_at.desc()).all()
    total_tags = db.query(Tag).count()
    total_verifications = db.query(Verification).count()
    total_done = sum(1 for s in sarees if s.proc_status == "done")

    rows = []
    for s in sarees:
        batch = db.query(Batch).filter(Batch.id == s.batch_id).first()
        coop = db.query(Coop).filter(Coop.id == batch.coop_id).first() if batch else None
        weaver = db.query(Weaver).filter(Weaver.id == batch.weaver_id).first() if batch else None
        vers = db.query(Verification).filter(Verification.qr_id == s.qr_id).order_by(Verification.at.desc()).all()

        irreg_summary = "—"
        if s.irregularity:
            try:
                irreg_data = json.loads(s.irregularity)
                if isinstance(irreg_data, dict):
                    irreg_summary = f"W:{irreg_data.get('warp', 0):.2f} F:{irreg_data.get('weft', 0):.2f}"
            except Exception:
                pass

        defects_summary = "—"
        if s.defects:
            try:
                defects_data = json.loads(s.defects)
                if isinstance(defects_data, dict):
                    cnt = defects_data.get("count", 0)
                    frac = defects_data.get("area_fraction", 0.0)
                    defects_summary = f"{cnt} ({frac*100:.2f}%)"
            except Exception:
                pass

        rows.append({
            "qr_id": s.qr_id,
            "coop_name": coop.name if coop else "—",
            "district": coop.district if coop else "—",
            "weaver_name": weaver.name if weaver else "—",
            "saree_type": batch.saree_type if batch else "—",
            "proc_status": s.proc_status,
            "grade": s.grade,
            "epi": s.epi,
            "ppi": s.ppi,
            "irregularity_summary": irreg_summary,
            "defects_summary": defects_summary,
            "registered_at": s.registered_at,
            "verification_count": len(vers),
            "latest_verification": vers[0] if vers else None,
        })

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "admin_user": admin_user,
            "rows": rows,
            "total_sarees": len(sarees),
            "total_done": total_done,
            "total_verifications": total_verifications,
            "total_tags": total_tags,
        },
    )


@router.get("/admin/export.csv")
def export_admin_csv(
    admin_user: User = Depends(authenticate_admin_request),
    db: Session = Depends(get_db),
):
    """
    Download complete scientific & operational CSV export containing thread counts,
    irregularity, defect metrics, grades, and verification scores.
    """
    sarees = db.query(Saree).order_by(Saree.registered_at.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "qr_id",
        "coop_id",
        "coop_name",
        "district",
        "weaver_id",
        "weaver_name",
        "saree_type",
        "registered_at_utc",
        "processing_status",
        "grade",
        "grade_provisional",
        "ends_per_inch_warp",
        "picks_per_inch_weft",
        "irregularity_warp",
        "irregularity_weft",
        "defects_count",
        "defects_area_fraction",
        "total_verifications",
        "latest_verification_result",
        "latest_verification_score",
        "latest_verification_at_utc",
    ])

    for s in sarees:
        batch = db.query(Batch).filter(Batch.id == s.batch_id).first()
        coop = db.query(Coop).filter(Coop.id == batch.coop_id).first() if batch else None
        weaver = db.query(Weaver).filter(Weaver.id == batch.weaver_id).first() if batch else None
        vers = db.query(Verification).filter(Verification.qr_id == s.qr_id).order_by(Verification.at.desc()).all()

        irreg_warp, irreg_weft = None, None
        if s.irregularity:
            try:
                irreg_data = json.loads(s.irregularity)
                if isinstance(irreg_data, dict):
                    irreg_warp = irreg_data.get("warp")
                    irreg_weft = irreg_data.get("weft")
            except Exception:
                pass

        def_cnt, def_frac = None, None
        if s.defects:
            try:
                def_data = json.loads(s.defects)
                if isinstance(def_data, dict):
                    def_cnt = def_data.get("count")
                    def_frac = def_data.get("area_fraction")
            except Exception:
                pass

        latest_ver = vers[0] if vers else None

        writer.writerow([
            s.qr_id,
            coop.id if coop else "",
            coop.name if coop else "",
            coop.district if coop else "",
            weaver.id if weaver else "",
            weaver.name if weaver else "",
            batch.saree_type if batch else "",
            s.registered_at.isoformat() if s.registered_at else "",
            s.proc_status,
            s.grade or "",
            s.grade_provisional,
            s.epi if s.epi is not None else "",
            s.ppi if s.ppi is not None else "",
            irreg_warp if irreg_warp is not None else "",
            irreg_weft if irreg_weft is not None else "",
            def_cnt if def_cnt is not None else "",
            def_frac if def_frac is not None else "",
            len(vers),
            latest_ver.match if latest_ver else "",
            latest_ver.score if latest_ver and latest_ver.score is not None else "",
            latest_ver.at.isoformat() if latest_ver else "",
        ])

    csv_content = output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tantsaakshi_saree_metrics.csv"},
    )
