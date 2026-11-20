"""
backend/routers/listings.py
Listing and Voice Studio endpoints for TantSaakshi.

Rules
- Only fully processed sarees ('done') are listed or exported.
- Publishing a listing needs a cooperative staff (or admin) login, and staff can
  only list their own cooperative's sarees.
- No made-up values: missing grade, price, district etc. stay empty.
- Weaver names only when the weaver agreed (show_name_publicly).
- /transcribe has no speech recognition connected yet: it returns a clearly
  marked sample ('demo': true) for staff to edit.
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import require_staff_or_admin
from backend.config import BASE_URL
from backend.database import get_db
from backend.models import Batch, Coop, Saree, Tag, User, Weaver
from backend.schemas import ListingResponse

router = APIRouter(tags=["Listings"])


class ListingPayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=140)
    price_inr: float | None = Field(None, gt=0, le=10_000_000)
    story_bn: str | None = Field(None, max_length=2000)
    story_en: str | None = Field(None, max_length=2000)
    occasion: str | None = Field(None, max_length=120)
    colour: str | None = Field(None, max_length=120)
    motif: str | None = Field(None, max_length=160)
    language: str | None = Field("bn", max_length=8)


class SharePayload(BaseModel):
    to: str | None = Field(None, max_length=20)


def _not_found(qr_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "LISTING_NOT_FOUND",
            "message_en": f"No certified saree found for '{qr_id}'.",
            "message_bn": f"'{qr_id}'-এর জন্য কোনো সনদপ্রাপ্ত শাড়ি পাওয়া যায়নি।",
        },
    )


def _listing_meta(saree: Saree) -> dict | None:
    try:
        return json.loads(saree.listing_json) if saree.listing_json else None
    except (TypeError, ValueError):
        return None


def _image_url(saree: Saree) -> str:
    """Real cloth of this saree: close-up if available, otherwise the registration photo."""
    if saree.closeup_path and Path(saree.closeup_path).exists():
        return f"/c/{saree.qr_id}/closeup"
    return f"/c/{saree.qr_id}/photo"


def _done_saree(db: Session, qr_id: str) -> Saree:
    saree = db.query(Saree).filter(Saree.qr_id == qr_id).first()
    if not saree or saree.proc_status != "done":
        raise _not_found(qr_id)
    return saree


@router.get("/listings")
def get_all_listings(db: Session = Depends(get_db)):
    """Certified sarees (processing finished) for the catalogue and the voice studio."""
    results = []
    sarees = (
        db.query(Saree)
        .filter(Saree.proc_status == "done")
        .order_by(Saree.registered_at.desc())
        .all()
    )
    for s in sarees:
        batch = db.query(Batch).filter(Batch.id == s.batch_id).first() if s.batch_id else None
        coop = db.query(Coop).filter(Coop.id == batch.coop_id).first() if batch and batch.coop_id else None
        weaver = db.query(Weaver).filter(Weaver.id == batch.weaver_id).first() if batch and batch.weaver_id else None
        tag = db.query(Tag).filter(Tag.qr_id == s.qr_id).first()
        results.append({
            "qr_id": s.qr_id,
            "saree_type": batch.saree_type if batch else None,
            "cooperative": coop.name if coop else None,
            "district": coop.district if coop else None,
            "weaver": weaver.name if weaver and weaver.show_name_publicly else None,
            "ends_per_inch": s.epi,
            "picks_per_inch": s.ppi,
            "grade": s.grade,
            "grade_provisional": s.grade is None,
            "tag_status": tag.status if tag else None,
            "photo_url": _image_url(s),
            "certificate_url": f"/c/{s.qr_id}",
            "listing": _listing_meta(s),
        })
    return {"listings": results}


@router.get("/listing/{design_id}", response_model=ListingResponse)
def get_listing_details(
    design_id: str,
    db: Session = Depends(get_db),
):
    """
    Supplies authentic handloom specifications to selling/listing platform.
    """
    clean_id = design_id.strip()

    saree = db.query(Saree).filter(Saree.qr_id == clean_id).first()
    if not saree:
        batch = db.query(Batch).filter((Batch.id == clean_id) | (Batch.saree_type == clean_id)).first()
        if batch:
            saree = db.query(Saree).filter(Saree.batch_id == batch.id, Saree.proc_status == "done").first()

    if not saree:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "LISTING_NOT_FOUND",
                "message_en": f"No active listing found for design ID '{clean_id}'",
                "message_bn": f"ডিজাইন আইডি '{clean_id}'-এর জন্য কোনো সক্রিয় তালিকা পাওয়া যায়নি",
            },
        )

    tag = db.query(Tag).filter(Tag.qr_id == saree.qr_id).first()
    batch = db.query(Batch).filter(Batch.id == saree.batch_id).first()
    coop = db.query(Coop).filter(Coop.id == batch.coop_id).first() if batch else None
    status_val = tag.status if tag else "registered"

    return ListingResponse(
        design_id=clean_id,
        saree_type=batch.saree_type if batch else "Handloom Saree",
        cooperative=coop.name if coop else "Handloom Weavers Cooperative",
        district=coop.district if coop else None,
        grade=saree.grade,
        ends_per_inch=saree.epi,
        picks_per_inch=saree.ppi,
        status=status_val,
        registered_at=saree.registered_at.isoformat() if saree.registered_at else None,
    )



@router.post("/transcribe")
async def transcribe_voice(
    audio: UploadFile = File(...),
    user: User = Depends(require_staff_or_admin),
):
    """
    Voice studio. Speech recognition is NOT connected yet: this returns a fixed,
    clearly marked sample listing ('demo': true) so staff can see the flow and
    edit every field before publishing. The audio is not analysed.
    """
    return {
        "demo": True,
        "notice_en": "Sample listing — voice recognition is not connected yet. Please edit every field.",
        "notice_bn": "নমুনা তালিকা — ভয়েস শনাক্তকরণ এখনও যুক্ত হয়নি। প্রতিটি তথ্য নিজে ঠিক করে নিন।",
        "transcript": "এই শাড়িটি হাতে বোনা সুতির তাঁত, লাল পাড় ও সোনালি বুটি। পুজো ও উৎসবের জন্য।",
        "fields": {
            "title_en": "Handwoven cotton tant with red border",
            "title_bn": "হাতে বোনা সুতির তাঁত শাড়ি, লাল পাড়",
            "saree_type": "Tant",
            "colour": "Red & cream (লাল ও ক্রিম)",
            "motif": "Small butis (ছোট বুটি)",
            "occasion": "Puja & festive wear (পুজো ও উৎসব)",
            "price_inr": None,
            "story_bn": "সমবায়ের তাঁতিরা হাতে বুনেছেন। সুতোর ঘনত্ব নিবন্ধনের সময় ছবি থেকে মাপা হয়েছে।",
            "story_en": "Handwoven by the cooperative's weavers. Thread count was measured from photographs at registration.",
        },
    }


@router.post("/listings/{qr_id}")
def publish_listing(
    qr_id: str,
    payload: ListingPayload,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    """Publish a listing for one of this cooperative's certified sarees."""
    clean_qr = qr_id.strip()
    saree = _done_saree(db, clean_qr)
    batch = db.query(Batch).filter(Batch.id == saree.batch_id).first()
    if user.role != "admin" and (not batch or batch.coop_id != user.coop_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "LISTING_OTHER_COOP",
                "message_en": "This saree belongs to another cooperative.",
                "message_bn": "এই শাড়িটি অন্য সমবায়ের।",
            },
        )
    tag = db.query(Tag).filter(Tag.qr_id == clean_qr).first()
    if tag and tag.status == "sold":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "LISTING_SOLD", "message_en": "This saree is already sold.", "message_bn": "এই শাড়িটি বিক্রি হয়ে গেছে।"},
        )
    if tag and tag.status in ("registered", "listed"):
        tag.status = "listed"
    data = payload.model_dump()
    saree.listing_json = json.dumps(data, ensure_ascii=False)
    db.commit()
    return {"qr_id": clean_qr, "status": "listed", "certificate_url": f"/c/{clean_qr}", "listing": data}


@router.post("/listings/{qr_id}/share")
def share_listing(qr_id: str, payload: SharePayload, db: Session = Depends(get_db)):
    """WhatsApp share link for a certified saree (only builds a link; sends nothing)."""
    clean_qr = qr_id.strip()
    saree = _done_saree(db, clean_qr)
    meta = _listing_meta(saree) or {}
    title = meta.get("title") or f"Bengal handloom saree ({clean_qr})"
    price = f"₹{meta['price_inr']:,.0f}" if meta.get("price_inr") else "Price on request"
    text = (
        f"🌸 *TantSaakshi · তাঁতসাক্ষী*\n"
        f"*{title}*\n"
        f"💰 {price}\n"
        f"🧵 Thread count measured at the cooperative.\n"
        f"📜 Birth certificate: {BASE_URL}/c/{clean_qr}"
    )
    phone = "".join(ch for ch in (payload.to or "") if ch.isdigit())
    encoded = urllib.parse.quote(text)
    share_url = f"https://wa.me/{phone}?text={encoded}" if phone else f"https://wa.me/?text={encoded}"
    return {"sent": False, "share_url": share_url, "message": "Share link generated"}


@router.get("/ondc/{qr_id}")
def get_ondc_payload(qr_id: str, db: Session = Depends(get_db)):
    """
    Draft catalogue item in ONDC/Beckn shape for a certified saree.
    Not registered on the ONDC network; only real values are included.
    """
    clean_qr = qr_id.strip()
    saree = _done_saree(db, clean_qr)
    batch = db.query(Batch).filter(Batch.id == saree.batch_id).first() if saree.batch_id else None
    coop = db.query(Coop).filter(Coop.id == batch.coop_id).first() if batch and batch.coop_id else None
    meta = _listing_meta(saree) or {}
    host = urllib.parse.urlparse(BASE_URL).netloc or "tantsaakshi.local"

    tags = {"certificate_url": f"{BASE_URL}/c/{clean_qr}"}
    if batch and batch.saree_type:
        tags["craft"] = batch.saree_type
    if saree.epi is not None:
        tags["epi"] = f"{saree.epi:.1f}"
    if saree.ppi is not None:
        tags["ppi"] = f"{saree.ppi:.1f}"
    tags["grade"] = saree.grade or "provisional"

    item = {
        "id": clean_qr,
        "descriptor": {
            "name": meta.get("title") or (f"{batch.saree_type} saree" if batch and batch.saree_type else "Handloom saree"),
            "images": [f"{BASE_URL}{_image_url(saree)}"],
            "short_desc": meta.get("story_en") or "Thread count measured from photographs at registration.",
            "long_desc": meta.get("story_bn") or "",
        },
        "category_id": "Saree",
        "tags": tags,
    }
    if meta.get("price_inr"):
        item["price"] = {"currency": "INR", "value": f"{meta['price_inr']:.0f}"}

    return {
        "draft": True,
        "note": "Draft payload in ONDC/Beckn format. Not published to the ONDC network.",
        "context": {"domain": "ONDC:RET12", "country": "IND", "core_version": "1.2.0", "bpp_id": host},
        "message": {
            "catalog": {
                "bpp/providers": [
                    {
                        "id": coop.id if coop else None,
                        "descriptor": {"name": coop.name if coop else None},
                        "items": [item],
                    }
                ]
            }
        },
    }
