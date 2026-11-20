"""
backend/routers/certificates.py
Public digital authenticity certificate endpoint: GET /c/{qr_id}
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.config import BACKEND_DIR, SCAN_WARNING_THRESHOLD, SCAN_WINDOW_HOURS
from backend.database import get_db
from backend.models import Batch, CertificateScan, Coop, Saree, Tag, Verification, Weaver

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
            **_certificate_details(db, saree, clean_qr),
        },
    )


def _weave_summary(saree: Saree) -> dict | None:
    """Human-readable weave line from the engine's stored weave probe."""
    try:
        w = json.loads(saree.weave_json) if saree.weave_json else None
    except (TypeError, ValueError):
        w = None
    if not isinstance(w, dict):
        return None
    cls = w.get("class")
    rule = str(w.get("picks_rule") or "")
    if cls == "plain":
        en, bn = "Plain weave", "সাধারণ বুনন (প্লেইন)"
    elif cls == "twill":
        en, bn = "Twill", "টুইল বুনন"
    elif cls == "paired_ends":
        if rule.startswith("matt"):
            en, bn = "2/2 matt · paired ends", "২/২ ম্যাট · জোড়া টানা"
        elif rule.startswith("rib"):
            en, bn = "2/2 weft rib · paired ends", "২/২ রিব · জোড়া টানা"
        else:
            en, bn = "Paired ends (2/2)", "জোড়া টানা (২/২)"
    else:
        return None
    cands = [round(c, 1) for c in (w.get("picks_candidates") or []) if isinstance(c, (int, float))]
    return {
        "label_en": en,
        "label_bn": bn,
        "ambiguous": bool(w.get("pick_count_ambiguous")) and len(cands) == 2,
        "candidates": cands,
    }


def _certificate_details(db: Session, saree: Saree, qr_id: str) -> dict:
    """Extra, already-public facts for the full certificate. Never file paths."""
    epi, ppi = saree.epi, saree.ppi
    checks = (
        db.query(Verification)
        .filter(Verification.qr_id == qr_id, Verification.match.in_(("genuine", "no_match", "not_calibrated")))
        .order_by(Verification.at.desc())
        .all()
    )
    last = checks[0] if checks else None
    return {
        "evenness": _evenness_rows(saree),
        "declared": _declared_rows(saree),
        "weave": _weave_summary(saree),
        "total_tpi": round(epi + ppi, 1) if epi is not None and ppi is not None else None,
        "has_fingerprint": bool(saree.fingerprint_path),
        "has_closeup": bool(saree.closeup_path and Path(saree.closeup_path).exists()),
        "scan_count": db.query(CertificateScan).filter(CertificateScan.qr_id == qr_id).count(),
        "check_count": len(checks),
        "last_check": {
            "result": last.match,
            "date": last.at.strftime("%d %b %Y") if last.at else "",
        } if last else None,
    }


@router.get("/c/{qr_id}/photo")
def get_certificate_photo(qr_id: str, db: Session = Depends(get_db)):
    """
    Task 11: Serve a downscaled display copy of the registered fabric photo.
    Never exposes internal fingerprint (.npz) files.
    """
    clean_qr = qr_id.strip()
    saree = db.query(Saree).filter(Saree.qr_id == clean_qr).first()
    if not saree or not saree.image_path or saree.proc_status != "done":
        raise HTTPException(status_code=404, detail="Photo not available for this saree")
    return _display_copy(Path(saree.image_path), "_display.jpg", 800)


@router.get("/c/{qr_id}/closeup")
def get_certificate_closeup(qr_id: str, db: Session = Depends(get_db)):
    """Downscaled close-up of the measured cloth (inside the card window)."""
    clean_qr = qr_id.strip()
    saree = db.query(Saree).filter(Saree.qr_id == clean_qr).first()
    if not saree or not saree.closeup_path or saree.proc_status != "done":
        raise HTTPException(status_code=404, detail="Close-up not available for this saree")
    return _display_copy(Path(saree.closeup_path), "_display.jpg", 480)


def _display_copy(src: Path, suffix: str, max_side: int) -> FileResponse:
    """Serve a cached, downscaled JPEG copy. Never serves the original file."""
    if not src.exists():
        raise HTTPException(status_code=404, detail="Image file not found")
    display_path = src.parent / f"{src.stem}{suffix}"
    if not display_path.exists():
        try:
            from PIL import Image
            try:
                import pillow_heif  # noqa: F401
                pillow_heif.register_heif_opener()
            except Exception:
                pass
            with Image.open(src) as im:
                im = im.convert("RGB")
                im.thumbnail((max_side, max_side))
                im.save(display_path, "JPEG", quality=85)
        except Exception:
            raise HTTPException(status_code=500, detail="Could not prepare the image")
    return FileResponse(str(display_path), media_type="image/jpeg")



_EVEN_BANDS = {  # engine.spacing.describe() bands
    "very_even": ("Very even", "খুব সমান"),
    "slightly_varied": ("Slightly varied", "সামান্য অসমান"),
    "varied": ("Varied", "অসমান"),
    "highly_varied": ("Highly varied", "বেশ অসমান"),
}


def _evenness_rows(saree: Saree) -> list[dict]:
    """Only directions the engine marked reliable are shown."""
    from engine.spacing import describe

    try:
        sp = json.loads(saree.spacing_json) if saree.spacing_json else None
    except (TypeError, ValueError):
        sp = None
    if not isinstance(sp, dict):
        return []
    rows = []
    for axis, en, bn in (("weft", "Weft rows", "বানার সারি"), ("warp", "Warp threads", "টানা সুতো")):
        d = sp.get(axis) or {}
        cv = d.get("cv")
        if not d.get("reliable") or not isinstance(cv, (int, float)):
            continue
        band = describe(float(cv))
        b_en, b_bn = _EVEN_BANDS[band]
        rows.append({
            "axis_en": en, "axis_bn": bn, "band_en": b_en, "band_bn": b_bn,
            "pct": None if band == "very_even" else int(round(cv * 100)),
        })
    return rows


_DECLARED_VALUES = {
    "fibre": {"cotton": ("Cotton", "সুতি"), "silk": ("Silk", "রেশম"), "cotton-silk": ("Cotton–silk blend", "সুতি-রেশম মিশ্র"),
              "linen": ("Linen", "লিনেন"), "other": ("Other", "অন্যান্য")},
    "dye": {"natural": ("Natural dyes", "প্রাকৃতিক রং"), "chemical": ("Chemical dyes", "রাসায়নিক রং"), "mixed": ("Natural and chemical", "মিশ্র রং")},
    "loom_type": {"pit": ("Pit loom", "গর্ত তাঁত"), "frame": ("Frame loom", "ফ্রেম তাঁত"),
                  "jacquard": ("Jacquard handloom", "জ্যাকার্ড তাঁত"), "other": ("Other", "অন্যান্য")},
}
_DECLARED_ORDER = [
    ("fibre", "Fibre", "সুতোর ধরন"), ("yarn_count", "Yarn count", "সুতোর কাউন্ট"), ("dye", "Dye", "রং"),
    ("loom_type", "Loom", "তাঁত"), ("border", "Border (paar)", "পাড়"), ("motifs", "Motifs", "নকশা"),
    ("length_m", "Length", "দৈর্ঘ্য"), ("weight_g", "Weight", "ওজন"), ("days_to_weave", "Time to weave", "বুনতে সময়"),
]


def _declared_rows(saree: Saree) -> list[dict]:
    """Cooperative-declared details, only the ones that were filled in."""
    try:
        d = json.loads(saree.declared_json) if saree.declared_json else None
    except (TypeError, ValueError):
        d = None
    if not isinstance(d, dict):
        return []
    rows = []
    for key, en, bn in _DECLARED_ORDER:
        v = d.get(key)
        if v in (None, ""):
            continue
        if key in _DECLARED_VALUES:
            v_en, v_bn = _DECLARED_VALUES[key].get(str(v), (str(v), str(v)))
        elif key == "length_m":
            v_en, v_bn = f"{v:g} m", f"{v:g} মিটার"
        elif key == "weight_g":
            v_en, v_bn = f"{v} g", f"{v} গ্রাম"
        elif key == "days_to_weave":
            v_en, v_bn = f"{v} day{'s' if v != 1 else ''}", f"{v} দিন"
        else:
            v_en = v_bn = str(v)
        rows.append({"label_en": en, "label_bn": bn, "value_en": v_en, "value_bn": v_bn})
    return rows
