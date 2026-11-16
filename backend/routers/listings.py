"""
backend/routers/listings.py
Listing endpoint for Group 5 selling/catalog platform: GET /listing/{design_id}
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Batch, Coop, Saree, Tag
from backend.schemas import ListingResponse

router = APIRouter(tags=["Listings"])


@router.get("/listing/{design_id}", response_model=ListingResponse)
def get_listing_details(
    design_id: str,
    db: Session = Depends(get_db),
):
    """
    Supplies authentic handloom specifications to Group 5's selling/listing platform.
    Matches either specific saree QR ID, batch ID, or saree variety name.
    Preserves QR status lifecycle: blank -> registered -> listed -> sold.
    """
    clean_id = design_id.strip()

    # 1. Search by QR ID
    saree = db.query(Saree).filter(Saree.qr_id == clean_id).first()

    # 2. Fallback: search by batch ID or saree type
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

    # Status follows tag lifecycle (e.g. 'registered', 'listed', 'sold')
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
