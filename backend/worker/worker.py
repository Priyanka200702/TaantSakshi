"""
backend/worker/worker.py
Simple background worker loop for asynchronous saree image processing.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from sqlalchemy.orm import Session

# Ensure project path is accessible
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.database import SessionLocal
from backend.models import Saree, SareePhoto, Tag
from backend.services.vision_adapter import QUALITY_FAILURE_CODES, run_registration_analysis

logger = logging.getLogger("tantsaakshi.worker")


def process_one_job(db: Session) -> bool:
    """
    Safely claim and execute one queued registration job.
    Returns True if a job was found and processed, False otherwise.
    """
    # 1. Safely claim one queued saree record atomically
    saree = (
        db.query(Saree)
        .filter(Saree.proc_status == "queued")
        .order_by(Saree.registered_at.asc())
        .with_for_update() if db.bind.dialect.name != "sqlite" else db.query(Saree).filter(Saree.proc_status == "queued").order_by(Saree.registered_at.asc())
    ).first()

    if not saree:
        return False

    qr_id = saree.qr_id
    # Mark as processing immediately
    saree.proc_status = "processing"
    db.commit()

    logger.info("Processing saree registration for QR %s", qr_id)

    # 2. Gather burst photographs
    photos = (
        db.query(SareePhoto)
        .filter(SareePhoto.saree_qr_id == qr_id)
        .order_by(SareePhoto.frame_index.asc())
        .all()
    )
    photo_paths = [p.photo_path for p in photos] if photos else [saree.image_path]

    # Verify that photo paths exist on disk
    valid_paths = [p for p in photo_paths if Path(p).exists()]
    if not valid_paths:
        logger.error("No valid photo files found on disk for QR %s", qr_id)
        saree.proc_status = "failed"
        saree.proc_error_code = "BAD_IMAGE"
        saree.proc_error_reason = "Uploaded photo files could not be located on disk"
        db.commit()
        return True

    # 3. Call vision engine through adapter
    analysis = run_registration_analysis(photo_paths=valid_paths, qr_id=qr_id)

    # 4. Handle analysis outcome
    if analysis["ok"]:
        logger.info("Successfully analyzed QR %s (Grade: %s, EPI: %s, PPI: %s)",
                    qr_id, analysis.get("grade"), analysis.get("ends_per_inch"), analysis.get("picks_per_inch"))
        saree.proc_status = "done"
        saree.epi = analysis.get("ends_per_inch")
        saree.ppi = analysis.get("picks_per_inch")
        saree.grade = analysis.get("grade")
        saree.grade_provisional = analysis.get("grade_provisional", True)
        saree.irregularity = json.dumps(analysis.get("irregularity", {}))
        saree.defects = json.dumps(analysis.get("defects", {}))
        saree.fingerprint_path = analysis.get("fingerprint_path")
        weave = analysis.get("weave")
        if weave is not None:
            weave = {**weave, "visible_rows_per_inch": analysis.get("visible_rows_per_inch")}
        saree.weave_json = json.dumps(weave) if weave is not None else None
        saree.closeup_path = analysis.get("closeup_path")
        spacing = analysis.get("spacing")
        saree.spacing_json = json.dumps(spacing) if spacing is not None else None
        saree.proc_error_code = None
        saree.proc_error_reason = None
        db.commit()
    else:
        code = analysis.get("code", "UNKNOWN")
        reason_en = analysis.get("reason_en", "Analysis failed")
        logger.warning("Quality check or processing failed for QR %s: %s (%s)", qr_id, code, reason_en)

        saree.proc_status = "failed"
        saree.proc_error_code = code
        saree.proc_error_reason = reason_en

        # If rejected due to photo quality, release the QR tag back to 'blank'
        # so staff can retake the photos without consuming the tag!
        if analysis.get("is_quality_failure") or code in QUALITY_FAILURE_CODES:
            tag = db.query(Tag).filter(Tag.qr_id == qr_id).first()
            if tag:
                logger.info("Releasing QR tag %s back to 'blank' due to photo quality rejection (%s)", qr_id, code)
                tag.status = "blank"

        db.commit()

    return True


def process_all_queued(db: Session) -> int:
    """Process all currently queued saree jobs synchronously until queue is empty."""
    count = 0
    while process_one_job(db):
        count += 1
    return count


def run_worker_loop(poll_interval: float = 2.0) -> None:
    """Run perpetual background worker loop."""
    logger.info("Starting TantSaakshi background worker loop (poll interval: %.1fs)...", poll_interval)
    while True:
        db = SessionLocal()
        try:
            had_job = process_one_job(db)
        except Exception as exc:
            logger.exception("Unexpected error in worker loop: %s", exc)
            had_job = False
        finally:
            db.close()

        if not had_job:
            time.sleep(poll_interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    run_worker_loop()
