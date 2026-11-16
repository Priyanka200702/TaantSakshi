"""
backend/auth.py
Authentication, bcrypt password hashing, JWT tokens, and cooperative RBAC.
"""
from __future__ import annotations

import datetime
import bcrypt
import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, SECRET_KEY, get_message
from backend.database import get_db
from backend.models import User

security = HTTPBearer(auto_error=False)


def hash_pin(pin: str) -> str:
    """Hash a numeric or alphanumeric PIN using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pin.encode("utf-8"), salt).decode("utf-8")


def verify_pin(pin: str, pin_hash: str) -> bool:
    """Verify a plain-text PIN against its bcrypt hash."""
    try:
        return bcrypt.checkpw(pin.encode("utf-8"), pin_hash.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: datetime.timedelta | None = None) -> str:
    """Issue a signed JWT bearer token."""
    to_encode = data.copy()
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    expire = now_utc + (
        expires_delta or datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": now_utc})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT bearer token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message_en": "Token has expired", "message_bn": "টোকেনের মেয়াদ শেষ হয়ে গেছে"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_INVALID", "message_en": "Invalid token", "message_bn": "অবৈধ টোকেন"},
        )


def raise_bilingual_error(status_code: int, code: str, default_en: str = "") -> None:
    """Convenience helper to raise an HTTPException with agreed bilingual payload."""
    en = get_message(code, "en", default_en)
    bn = get_message(code, "bn", default_en)
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message_en": en, "message_bn": bn},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Extract and validate current authenticated user from Authorization header.
    Requires Bearer token.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message_en": "Authentication required", "message_bn": "প্রমাণীকরণ প্রয়োজন"},
        )

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_INVALID", "message_en": "Invalid token subject", "message_bn": "অবৈধ টোকেন"},
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "USER_NOT_FOUND", "message_en": "User does not exist", "message_bn": "ব্যবহারকারী পাওয়া যায়নি"},
        )

    return user


def require_staff_or_admin(user: User = Depends(get_current_user)) -> User:
    """Ensure user is cooperative staff or global admin."""
    if user.role not in ("staff", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message_en": "Cooperative staff access only", "message_bn": "শুধুমাত্র সমবায় কর্মীদের জন্য অনুমোদিত"},
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Ensure user is global admin (project team only)."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message_en": "Administrative access only", "message_bn": "শুধুমাত্র প্রশাসকদের জন্য অনুমোদিত"},
        )
    return user


def require_seller_or_staff(user: User = Depends(get_current_user)) -> User:
    """Ensure user is authorized seller, staff, or admin for verification."""
    if user.role not in ("seller", "staff", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message_en": "Seller authentication required", "message_bn": "বিক্রেতার প্রমাণীকরণ প্রয়োজন"},
        )
    return user
