"""
backend/routers/weavers.py
Weaver endpoint: GET /weavers
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.auth import require_staff_or_admin
from backend.database import get_db
from backend.models import User, Weaver
from backend.schemas import WeaverResponse

router = APIRouter(tags=["Weavers"])


@router.get("/weavers", response_model=list[WeaverResponse])
def get_weavers(
    user: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):
    """
    Retrieve weavers belonging to the authenticated staff member's cooperative.
    Enforces strict cooperative isolation.
    """
    query = db.query(Weaver)
    if user.role != "admin" or user.coop_id:
        query = query.filter(Weaver.coop_id == user.coop_id)

    weavers = query.order_by(Weaver.name.asc()).all()
    return [WeaverResponse(id=w.id, name=w.name) for w in weavers]
