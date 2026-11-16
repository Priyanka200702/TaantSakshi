"""
backend/routers/login.py
Authentication endpoint: POST /login
"""
from __future__ import annotations

import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth import create_access_token, verify_pin
from backend.database import get_db
from backend.models import LoginAttempt, User
from backend.schemas import LoginRequest, LoginResponse

router = APIRouter(tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate user by phone and PIN.
    Returns JWT token and user profile including cooperative ID and role.
    Locks phone number for 15 minutes after 5 wrong PIN attempts.
    """
    phone = payload.phone.strip()
    pin = payload.pin.strip()

    # Task 7: Lock phone number for 15 minutes after 5 wrong PINs
    cutoff = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(minutes=15)
    recent_failures = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.phone == phone,
            LoginAttempt.success == False,
            LoginAttempt.attempted_at >= cutoff,
        )
        .count()
    )
    if recent_failures >= 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Account temporarily locked due to 5 consecutive failed login attempts. Please try again after 15 minutes.",
        )

    user = db.query(User).filter(User.phone == phone).first()
    if not user or not verify_pin(pin, user.pin_hash):
        db.add(LoginAttempt(phone=phone, success=False))
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong phone or PIN",
        )

    # Login successful: clear failure history for this phone
    db.query(LoginAttempt).filter(LoginAttempt.phone == phone).delete()
    db.add(LoginAttempt(phone=phone, success=True))
    db.commit()

    token = create_access_token(
        data={
            "sub": user.id,
            "role": user.role,
            "coop_id": user.coop_id,
            "name": user.name,
        }
    )

    return LoginResponse(
        token=token,
        name=user.name,
        role=user.role,
        coop_id=user.coop_id,
    )
