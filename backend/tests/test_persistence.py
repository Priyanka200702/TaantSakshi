"""
backend/tests/test_persistence.py
Automated tests for Data, Photo, and Fingerprint Persistence & Backups (Tests 46-49).
"""
import io
import shutil
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Saree, Tag
from backend.scripts.backup import perform_backup
from backend.services.registration_service import validate_and_register_saree
from backend.worker.worker import process_one_job


def test_46_to_48_data_photos_fingerprints_survive_restart(tmp_path, sample_image_bytes):
    """
    Test 46: Database records survive server restart / session closure.
    Test 47: Photos survive server restart on disk.
    Test 48: Fingerprint files survive server restart on disk.
    """
    db_file = tmp_path / "persistence.db"
    db_url = f"sqlite:///{db_file}"

    from backend.database import Base
    engine1 = create_engine(db_url)
    Base.metadata.create_all(bind=engine1)
    Session1 = sessionmaker(bind=engine1)
    s1 = Session1()

    from backend.models import Batch, Coop, User, Weaver
    coop = Coop(id="COOP-PERSIST", name="Persist Society", district="Hooghly")
    weaver = Weaver(id="WVR-PERSIST", coop_id="COOP-PERSIST", name="Master Weaver", show_name_publicly=True)
    user = User(id="USR-PERSIST", coop_id="COOP-PERSIST", name="Staff", phone="9111111111", pin_hash="hash", role="staff")
    batch = Batch(id="BATCH-PERSIST", coop_id="COOP-PERSIST", weaver_id="WVR-PERSIST", saree_type="Cotton", started_by="USR-PERSIST")
    tag = Tag(qr_id="TS-PERSIST01", coop_id="COOP-PERSIST", batch_no="BATCH-PERSIST", status="blank")
    s1.add_all([coop, weaver, user, batch, tag])
    s1.commit()

    # Create dummy upload file
    from fastapi import UploadFile
    dummy_photo = UploadFile(filename="photo.jpg", file=io.BytesIO(sample_image_bytes))

    # Register saree
    validate_and_register_saree(
        db=s1,
        user=user,
        qr_id="TS-PERSIST01",
        batch_id="BATCH-PERSIST",
        upload_id="upload-persist-001",
        phone_model="Pixel",
        photos=[dummy_photo],
    )

    # Process with worker
    process_one_job(s1)

    saree1 = s1.query(Saree).filter(Saree.qr_id == "TS-PERSIST01").first()
    photo_path = saree1.image_path
    fp_path = saree1.fingerprint_path

    assert Path(photo_path).exists()
    assert Path(fp_path).exists()

    # SIMULATE SERVER RESTART / CRASH:
    # Close session and dispose engine completely
    s1.close()
    engine1.dispose()

    # Reconnect with brand new engine and session
    engine2 = create_engine(db_url)
    Session2 = sessionmaker(bind=engine2)
    s2 = Session2()

    # Test 46: Verify database record persisted
    saree2 = s2.query(Saree).filter(Saree.qr_id == "TS-PERSIST01").first()
    assert saree2 is not None
    assert saree2.proc_status == "done"
    assert saree2.grade == "A"

    # Test 47: Verify photo file exists on disk after restart
    assert Path(saree2.image_path).exists()
    assert Path(saree2.image_path).stat().st_size > 0

    # Test 48: Verify fingerprint file exists on disk after restart
    assert Path(saree2.fingerprint_path).exists()
    assert Path(saree2.fingerprint_path).stat().st_size > 0

    s2.close()
    engine2.dispose()


def test_49_backup_procedure(tmp_path):
    """Test 49: Backup procedure successfully packages DB, photos, and fingerprints into tar.gz."""
    backup_dest = tmp_path / "backups"
    archive_path = perform_backup(dest_dir=backup_dest)

    assert archive_path.exists()
    assert archive_path.is_file()
    assert archive_path.suffix == ".gz"
    assert archive_path.stat().st_size > 0
