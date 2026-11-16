"""
backend/models.py
SQLAlchemy database models for TantSaakshi.
"""
from __future__ import annotations

import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from backend.database import Base


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class Coop(Base):
    """Stores cooperative information."""
    __tablename__ = "coops"

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    district = Column(String(128), nullable=False)

    users = relationship("User", back_populates="coop", cascade="all, delete-orphan")
    weavers = relationship("Weaver", back_populates="coop", cascade="all, delete-orphan")
    tags = relationship("Tag", back_populates="coop", cascade="all, delete-orphan")
    batches = relationship("Batch", back_populates="coop", cascade="all, delete-orphan")
    tag_logs = relationship("TagGenerationLog", back_populates="coop", cascade="all, delete-orphan")


class User(Base):
    """Stores staff, sellers, and administrators."""
    __tablename__ = "users"

    id = Column(String(64), primary_key=True)
    coop_id = Column(String(64), ForeignKey("coops.id"), nullable=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(32), unique=True, index=True, nullable=False)
    pin_hash = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False)  # 'staff', 'seller', 'admin'

    coop = relationship("Coop", back_populates="users")
    batches = relationship("Batch", back_populates="starter")
    tag_logs = relationship("TagGenerationLog", back_populates="generator")


class Weaver(Base):
    """Stores registered weavers and their public-name permission."""
    __tablename__ = "weavers"

    id = Column(String(64), primary_key=True)
    coop_id = Column(String(64), ForeignKey("coops.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    show_name_publicly = Column(Boolean, default=False, nullable=False)

    coop = relationship("Coop", back_populates="weavers")
    batches = relationship("Batch", back_populates="weaver")


class Tag(Base):
    """
    Stores QR tags and their lifecycle status:
    blank -> registered -> listed -> sold
    """
    __tablename__ = "tags"

    qr_id = Column(String(64), primary_key=True)
    coop_id = Column(String(64), ForeignKey("coops.id"), nullable=False, index=True)
    batch_no = Column(String(64), nullable=False, index=True)
    status = Column(String(32), default="blank", nullable=False, index=True)  # blank, registered, listed, sold

    coop = relationship("Coop", back_populates="tags")
    saree = relationship("Saree", back_populates="tag", uselist=False)
    scans = relationship("CertificateScan", back_populates="tag", cascade="all, delete-orphan")


class Batch(Base):
    """Represents a saree registration session."""
    __tablename__ = "batches"

    id = Column(String(64), primary_key=True)
    coop_id = Column(String(64), ForeignKey("coops.id"), nullable=False, index=True)
    weaver_id = Column(String(64), ForeignKey("weavers.id"), nullable=False, index=True)
    saree_type = Column(String(128), nullable=False)
    started_by = Column(String(64), ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime, default=utc_now, nullable=False)

    coop = relationship("Coop", back_populates="batches")
    weaver = relationship("Weaver", back_populates="batches")
    starter = relationship("User", back_populates="batches")
    sarees = relationship("Saree", back_populates="batch")


class Saree(Base):
    """Stores saree registration information and engine results."""
    __tablename__ = "sarees"

    qr_id = Column(String(64), ForeignKey("tags.qr_id"), primary_key=True)
    batch_id = Column(String(64), ForeignKey("batches.id"), nullable=False, index=True)
    upload_id = Column(String(64), unique=True, index=True, nullable=False)
    image_path = Column(String(512), nullable=False)
    phone_model = Column(String(128), nullable=True)
    epi = Column(Float, nullable=True)
    ppi = Column(Float, nullable=True)
    irregularity = Column(Text, nullable=True)  # JSON formatted
    defects = Column(Text, nullable=True)       # JSON formatted
    grade = Column(String(16), nullable=True)
    grade_provisional = Column(Boolean, default=True, nullable=False)
    fingerprint_path = Column(String(512), nullable=True)  # Kept strictly private
    proc_status = Column(String(32), default="queued", nullable=False, index=True)  # queued, processing, done, failed
    proc_error_code = Column(String(64), nullable=True)
    proc_error_reason = Column(Text, nullable=True)
    registered_at = Column(DateTime, default=utc_now, nullable=False)

    tag = relationship("Tag", back_populates="saree")
    batch = relationship("Batch", back_populates="sarees")
    photos = relationship("SareePhoto", back_populates="saree", cascade="all, delete-orphan")
    verifications = relationship("Verification", back_populates="saree", cascade="all, delete-orphan")


class SareePhoto(Base):
    """Preserves all photos from the registration burst (up to 5 frames)."""
    __tablename__ = "saree_photos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    saree_qr_id = Column(String(64), ForeignKey("sarees.qr_id"), nullable=False, index=True)
    photo_path = Column(String(512), nullable=False)
    frame_index = Column(Integer, default=0, nullable=False)
    uploaded_at = Column(DateTime, default=utc_now, nullable=False)

    saree = relationship("Saree", back_populates="photos")


class Verification(Base):
    """Stores every verification attempt."""
    __tablename__ = "verifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    qr_id = Column(String(64), ForeignKey("sarees.qr_id"), nullable=False, index=True)
    upload_id = Column(String(64), nullable=True, index=True)
    image_path = Column(String(512), nullable=False)
    score = Column(Float, nullable=True)
    match = Column(String(32), nullable=False)  # genuine, no_match, not_calibrated, retake
    reason = Column(Text, nullable=True)
    by_user = Column(String(64), nullable=True)
    at = Column(DateTime, default=utc_now, nullable=False)

    saree = relationship("Saree", back_populates="verifications")


class CertificateScan(Base):
    """Logs public certificate scans to protect against counter-tag copying."""
    __tablename__ = "certificate_scans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    qr_id = Column(String(64), ForeignKey("tags.qr_id"), nullable=False, index=True)
    scanned_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    approximate_location = Column(String(255), nullable=True)

    tag = relationship("Tag", back_populates="scans")


class TagGenerationLog(Base):
    """Logs batch generation of printable QR tags."""
    __tablename__ = "tag_generation_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    coop_id = Column(String(64), ForeignKey("coops.id"), nullable=False, index=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    count = Column(Integer, nullable=False)
    batch_no = Column(String(64), nullable=False)
    pdf_path = Column(String(512), nullable=True)
    generated_at = Column(DateTime, default=utc_now, nullable=False)

    coop = relationship("Coop", back_populates="tag_logs")
    generator = relationship("User", back_populates="tag_logs")
