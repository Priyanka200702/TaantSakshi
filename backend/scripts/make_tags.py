"""
backend/scripts/make_tags.py
CLI script for batch generating printable QR tags and A4 PDF sheets.
Usage:
    python make_tags.py --coop COOP-DHANIAKHALI --count 54
"""
from __future__ import annotations

import argparse
import datetime
import secrets
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.config import BASE_URL
from backend.database import SessionLocal, init_db
from backend.models import Coop, Tag, TagGenerationLog
from backend.services.qr_service import generate_tags_pdf, generate_unique_qr_ids


def main():
    parser = argparse.ArgumentParser(description="Generate TantSaakshi QR tags and printable PDF")
    parser.add_argument("--coop", required=True, help="Cooperative ID (e.g. COOP-DHANIAKHALI)")
    parser.add_argument("--count", type=int, default=54, help="Number of tags to generate (default 54)")
    parser.add_argument("--user", default="USR-ADMIN", help="User ID generating the batch")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    try:
        coop = db.query(Coop).filter(Coop.id == args.coop).first()
        if not coop:
            print(f"Error: Cooperative '{args.coop}' does not exist in database.")
            sys.exit(1)

        ts_code = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
        rand_hex = secrets.token_hex(2).upper()
        batch_no = f"BATCH-{args.coop}-{ts_code}-{rand_hex}"

        existing_ids = {row[0] for row in db.query(Tag.qr_id).all()}
        qr_ids = generate_unique_qr_ids(count=args.count, existing_ids=existing_ids)

        for qid in qr_ids:
            tag = Tag(qr_id=qid, coop_id=args.coop, batch_no=batch_no, status="blank")
            db.add(tag)

        pdf_path = generate_tags_pdf(qr_ids=qr_ids, batch_no=batch_no, base_url=BASE_URL)

        log_entry = TagGenerationLog(
            coop_id=args.coop,
            user_id=args.user,
            count=len(qr_ids),
            batch_no=batch_no,
            pdf_path=str(pdf_path),
            generated_at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
        )
        db.add(log_entry)
        db.commit()

        print(f"Successfully generated {len(qr_ids)} tags for {coop.name} ({coop.id})")
        print(f"Batch No: {batch_no}")
        print(f"Printable PDF: {pdf_path}")
        print("Sample QR IDs:", ", ".join(qr_ids[:5]))

    finally:
        db.close()


if __name__ == "__main__":
    main()
