"""
backend/routers/login.py
Authentication endpoint: POST /login
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth import create_access_token, verify_pin
from backend.database import get_db
from backend.models import User
from backend.schemas import LoginRequest, LoginResponse

router = APIRouter(tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate user by phone and PIN.
    Returns JWT token and user profile including cooperative ID and role.
    """
    user = db.query(User).filter(User.phone == payload.phone.strip()).first()
    if not user or not verify_pin(payload.pin.strip(), user.pin_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong phone or PIN",
        )

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
