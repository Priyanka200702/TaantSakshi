"""
backend/scripts/backup.py
Automated backup procedure for TantSaakshi SQLite database, original photos, and fingerprints.
Usage:
    python backup.py
"""
from __future__ import annotations

import datetime
import os
import shutil
import sqlite3
import sys
import tarfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.config import BACKUPS_DIR, DATABASE_URL, FINGERPRINTS_DIR, IMAGES_DIR, STORAGE_DIR


def perform_backup(dest_dir: Path | None = None) -> Path:
    """
    Execute a consistent, safe backup of:
      1. SQLite database (using SQLite online backup API to prevent corruption).
      2. Original saree photograph bursts (storage/images).
      3. Private fabric fingerprints (storage/fingerprints).
    Archives into a compressed .tar.gz bundle.
    """
    dest_dir = dest_dir or BACKUPS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_bundle_name = f"tantsaakshi_backup_{timestamp}.tar.gz"
    backup_bundle_path = dest_dir / backup_bundle_name

    # Create temporary staging directory
    staging_dir = dest_dir / f"tmp_stage_{timestamp}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Consistent SQLite online backup
        db_path = STORAGE_DIR / "tantsaakshi.db"
        if db_path.exists():
            target_db_path = staging_dir / "tantsaakshi.db"
            src_conn = sqlite3.connect(str(db_path))
            dst_conn = sqlite3.connect(str(target_db_path))
            with dst_conn:
                src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()

        # 2. Copy original images
        if IMAGES_DIR.exists():
            shutil.copytree(IMAGES_DIR, staging_dir / "images", dirs_exist_ok=True)

        # 3. Copy private fingerprints
        if FINGERPRINTS_DIR.exists():
            shutil.copytree(FINGERPRINTS_DIR, staging_dir / "fingerprints", dirs_exist_ok=True)

        # 4. Pack staging directory into .tar.gz archive
        with tarfile.open(backup_bundle_path, "w:gz") as tar:
            tar.add(staging_dir, arcname="tantsaakshi_backup")

        print(f"Backup created successfully: {backup_bundle_path} ({backup_bundle_path.stat().st_size} bytes)")
        return backup_bundle_path

    finally:
        # Clean up temporary staging directory
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


if __name__ == "__main__":
    perform_backup()
