"""
backend/schemas.py
Pydantic schemas for TantSaakshi API request and response validation.
"""
from __future__ import annotations

import datetime
from typing import Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Error Schema
# ---------------------------------------------------------------------------
class ErrorResponse(BaseModel):
    code: str
    message_en: str
    message_bn: str


# ---------------------------------------------------------------------------
# Authentication Schemas
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    phone: str = Field(..., description="User mobile phone number")
    pin: str = Field(..., description="4 to 6 digit security PIN")


class LoginResponse(BaseModel):
    token: str
    name: str
    role: str
    coop_id: str | None = None


# ---------------------------------------------------------------------------
# Weaver Schemas
# ---------------------------------------------------------------------------
class WeaverResponse(BaseModel):
    id: str
    name: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Batch Schemas
# ---------------------------------------------------------------------------
class BatchCreateRequest(BaseModel):
    weaver_id: str
    saree_type: str


class BatchResponse(BaseModel):
    batch_id: str


# ---------------------------------------------------------------------------
# Tag Generation Schemas
# ---------------------------------------------------------------------------
class TagGenerateRequest(BaseModel):
    count: int = Field(54, ge=1, le=1080, description="Number of tags to generate (54 per page)")


class TagGenerateResponse(BaseModel):
    batch_no: str
    count: int
    pdf_url: str


# ---------------------------------------------------------------------------
# Saree Registration & Status Schemas
# ---------------------------------------------------------------------------
class SareeRegistrationResponse(BaseModel):
    status: str = "queued"


class SareeStatusResponse(BaseModel):
    status: Literal["queued", "processing", "done", "failed"]
    code: str | None = None
    grade: str | None = None
    ends_per_inch: float | None = None
    picks_per_inch: float | None = None
    reason: str | None = None
    reason_bn: str | None = None


# ---------------------------------------------------------------------------
# Verification Schemas
# ---------------------------------------------------------------------------
class VerificationResponse(BaseModel):
    result: Literal["genuine", "no_match", "not_calibrated", "retake"]
    score: float | None = None
    reason: str | None = None
    code: str | None = None
    message_en: str | None = None
    message_bn: str | None = None


# ---------------------------------------------------------------------------
# Listing Schema (Group 5)
# ---------------------------------------------------------------------------
class ListingResponse(BaseModel):
    design_id: str
    saree_type: str
    cooperative: str
    district: str | None = None
    grade: str | None = None
    ends_per_inch: float | None = None
    picks_per_inch: float | None = None
    status: str
    registered_at: datetime.datetime | str | None = None
