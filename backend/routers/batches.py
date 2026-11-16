"""
backend/routers/batches.py
Batch registration endpoint: POST /batch
"""
from __future__ import annotations

import datetime
import secrets
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.auth import raise_bilingual_error, require_staff_or_admin
from backend.database import get_db
from backend.models import Batch, User, Weaver
from backend.schemas import BatchCreateRequest, BatchResponse

router = APIRouter(tags=["Batches"])


@router.post("/batch", response_model=BatchResponse)
def create_batch(
    payload: BatchCreateRequest,
    user: User = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
):
    """
    Start a saree registration batch linked to a cooperative weaver.
    Derives cooperative ownership from authenticated user.
    """
    coop_id = user.coop_id
    if not coop_id and user.role != "admin":
        raise_bilingual_error(status.HTTP_400_BAD_REQUEST, "NO_COOP", "User has no assigned cooperative")

    # Validate that weaver exists
    weaver = db.query(Weaver).filter(Weaver.id == payload.weaver_id.strip()).first()
    if not weaver:
        raise_bilingual_error(status.HTTP_404_NOT_FOUND, "WEAVER_UNKNOWN")

    # Enforce cooperative isolation: staff cannot use another cooperative's weaver
    if user.role != "admin" and weaver.coop_id != coop_id:
        raise_bilingual_error(status.HTTP_409_CONFLICT, "WEAVER_OTHER_COOP")

    # If admin creates batch for a weaver, inherit weaver's coop_id
    assigned_coop = coop_id or weaver.coop_id

    # Create batch ID
    ts_code = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
    rand_hex = secrets.token_hex(2).upper()
    batch_id = f"BATCH-{assigned_coop}-{ts_code}-{rand_hex}"

    batch = Batch(
        id=batch_id,
        coop_id=assigned_coop,
        weaver_id=weaver.id,
        saree_type=payload.saree_type.strip(),
        started_by=user.id,
        started_at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
    )
    db.add(batch)
    db.commit()

    return BatchResponse(batch_id=batch.id)
