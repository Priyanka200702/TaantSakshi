"""
backend/services/registration_service.py
Transactional saree registration, upload idempotency, and burst photo storage.
"""
from __future__ import annotations

import datetime
import shutil
from pathlib import Path
from fastapi import UploadFile, status
from sqlalchemy.orm import Session

from backend.auth import raise_bilingual_error
from backend.config import ALLOWED_EXTENSIONS, IMAGES_DIR, MAX_FILE_SIZE_BYTES
from backend.models import Batch, Saree, SareePhoto, Tag, User, Weaver


def validate_and_register_saree(
    db: Session,
    user: User,
    qr_id: str,
    batch_id: str,
    upload_id: str,
    phone_model: str | None,
    photos: list[UploadFile],
) -> dict:
    """
    Validate registration requirements, preserve original photo burst,
    create queued saree record, update tag lifecycle to 'registered',
    and enforce cooperative isolation & upload idempotency.
    """
    # 1. Check upload_id idempotency (protection against network retries)
    existing_by_upload = db.query(Saree).filter(Saree.upload_id == upload_id).first()
    if existing_by_upload:
        # Same upload ID submitted again: return earlier result without creating duplicate
        return {"status": existing_by_upload.proc_status}

    # 2. Check QR tag existence
    tag = db.query(Tag).filter(Tag.qr_id == qr_id).first()
    if not tag:
        raise_bilingual_error(status.HTTP_404_NOT_FOUND, "TAG_UNKNOWN")

    # 3. Check cooperative ownership of tag
    # Admin can register on behalf of cooperative if needed, staff can only register their own coop's tags
    if user.role != "admin" and tag.coop_id != user.coop_id:
        raise_bilingual_error(status.HTTP_409_CONFLICT, "TAG_OTHER_COOP")

    # 4. Check tag status is blank
    if tag.status != "blank":
        raise_bilingual_error(status.HTTP_409_CONFLICT, "TAG_USED")

    # 5. Check batch existence & cooperative ownership
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise_bilingual_error(status.HTTP_404_NOT_FOUND, "BATCH_UNKNOWN")

    if user.role != "admin" and batch.coop_id != user.coop_id:
        raise_bilingual_error(status.HTTP_409_CONFLICT, "BATCH_OTHER_COOP")

    # 6. Check batch references a valid weaver of this cooperative
    weaver = db.query(Weaver).filter(Weaver.id == batch.weaver_id).first()
    if not weaver:
        raise_bilingual_error(status.HTTP_404_NOT_FOUND, "WEAVER_UNKNOWN")

    if user.role != "admin" and weaver.coop_id != user.coop_id:
        raise_bilingual_error(status.HTTP_409_CONFLICT, "WEAVER_OTHER_COOP")

    # 7. Check uploaded files presence (burst of 1..5 photos)
    if not photos or len(photos) == 0:
        raise_bilingual_error(status.HTTP_400_BAD_REQUEST, "BAD_IMAGE", "At least one photograph must be provided")

    burst_photos = photos[:5]  # Accept up to 5 burst frames

    # Task 4: If tag was released back to 'blank' after a previous quality failure,
    # clean up the old failed Saree record, its SareePhoto records, and any stale files.
    old_saree = db.query(Saree).filter(Saree.qr_id == qr_id).first()
    if old_saree:
        old_photos = db.query(SareePhoto).filter(SareePhoto.saree_qr_id == qr_id).all()
        for p in old_photos:
            try:
                Path(p.photo_path).unlink(missing_ok=True)
            except Exception:
                pass
            db.delete(p)
        db.delete(old_saree)
        db.flush()

    # 8. Save original photographs safely to storage/images/{qr_id}/
    saree_dir = IMAGES_DIR / qr_id
    saree_dir.mkdir(parents=True, exist_ok=True)

    saved_photo_paths: list[str] = []
    for idx, upload_file in enumerate(burst_photos):
        ext = Path(upload_file.filename or "image.jpg").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise_bilingual_error(
                status.HTTP_400_BAD_REQUEST,
                "BAD_IMAGE",
                f"Unsupported file extension {ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )
        target_file = saree_dir / f"frame_{idx:02d}{ext}"

        # Write original content without altering compression, filters, or resolution
        upload_file.file.seek(0)
        with open(target_file, "wb") as f_out:
            shutil.copyfileobj(upload_file.file, f_out)

        # Check file size limit
        if target_file.stat().st_size > MAX_FILE_SIZE_BYTES:
            raise_bilingual_error(status.HTTP_400_BAD_REQUEST, "BAD_IMAGE", "File exceeds maximum permitted size")

        saved_photo_paths.append(str(target_file))

    primary_image_path = saved_photo_paths[0]

    # 9. Create Saree record
    saree = Saree(
        qr_id=qr_id,
        batch_id=batch_id,
        upload_id=upload_id,
        image_path=primary_image_path,
        phone_model=phone_model or "Unknown",
        proc_status="queued",
        registered_at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
    )
    db.add(saree)

    # 10. Create SareePhoto records for all preserved burst frames
    for idx, path_str in enumerate(saved_photo_paths):
        s_photo = SareePhoto(
            saree_qr_id=qr_id,
            photo_path=path_str,
            frame_index=idx,
            uploaded_at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
        )
        db.add(s_photo)

    # 11. Lock tag lifecycle to 'registered'
    tag.status = "registered"

    # 12. Commit transaction atomically
    db.commit()

    return {"status": "queued"}
