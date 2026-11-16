"""
backend/tests/test_worker.py
Automated tests for Background Worker & Vision Engine Integration (Tests 21-27).
"""
import io
from pathlib import Path
import pytest
from fastapi import status

from backend.models import Saree, Tag
from backend.worker.worker import process_one_job


def test_21_to_23_and_27_worker_success(client, token_staff_a, test_env, sample_image_bytes):
    """
    Test 21: Queued records are picked up and processed.
    Test 22: Processing status changes from 'queued' to 'done'.
    Test 23: Engine metrics (EPI, PPI, Grade, Irregularity, Defects) are stored.
    Test 27: Fingerprint files remain private (not exposed in public responses).
    """
    session = test_env["session"]
    headers = {"Authorization": f"Bearer {token_staff_a}"}

    # Register valid saree
    data = {
        "qr_id": "TS-COOPA001",
        "batch_id": "BATCH-A-01",
        "upload_id": "upload-worker-001",
    }
    files = [("photos", ("photo1.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))]
    resp = client.post("/saree", data=data, files=files, headers=headers)
    assert resp.status_code == status.HTTP_200_OK

    saree_before = session.query(Saree).filter(Saree.qr_id == "TS-COOPA001").first()
    assert saree_before.proc_status == "queued"

    # Run worker to process the job
    processed = process_one_job(session)
    assert processed is True

    # Re-fetch saree from database
    session.expire_all()
    saree_after = session.query(Saree).filter(Saree.qr_id == "TS-COOPA001").first()
    assert saree_after.proc_status == "done"
    assert saree_after.epi is not None
    assert saree_after.ppi is not None
    assert saree_after.grade == "A"
    assert saree_after.fingerprint_path is not None
    assert Path(saree_after.fingerprint_path).exists()

    # Test 27: Verify GET /saree/{qr_id} does not leak fingerprint path
    resp_status = client.get("/saree/TS-COOPA001", headers=headers)
    assert resp_status.status_code == status.HTTP_200_OK
    status_data = resp_status.json()
    assert "fingerprint_path" not in status_data
    assert "fingerprint" not in status_data
    assert status_data["status"] == "done"
    assert status_data["grade"] == "A"


def test_24_to_25_worker_quality_rejection_releases_tag(client, token_staff_a, test_env, sample_tilted_image_bytes):
    """
    Test 24: Photo quality failure marks status as 'failed' with reason.
    Test 25: Photo quality rejection releases tag back to 'blank' for retake!
    """
    session = test_env["session"]
    headers = {"Authorization": f"Bearer {token_staff_a}"}

    # Register saree using heavily tilted image (triggers TOO_TILTED failure)
    data = {
        "qr_id": "TS-COOPA001",
        "batch_id": "BATCH-A-01",
        "upload_id": "upload-tilt-001",
    }
    files = [("photos", ("tilted.png", io.BytesIO(sample_tilted_image_bytes), "image/png"))]
    resp = client.post("/saree", data=data, files=files, headers=headers)
    assert resp.status_code == status.HTTP_200_OK

    # Process job with worker
    processed = process_one_job(session)
    assert processed is True

    session.expire_all()
    saree = session.query(Saree).filter(Saree.qr_id == "TS-COOPA001").first()
    tag = session.query(Tag).filter(Tag.qr_id == "TS-COOPA001").first()

    # Test 24: Saree marked failed with error code
    assert saree.proc_status == "failed"
    assert saree.proc_error_code is not None

    # Test 25: Tag released back to 'blank' so staff can retake!
    assert tag.status == "blank"


def test_26_technical_failure_handled_safely(test_env):
    """Test 26: Missing/corrupt photo path is safely handled as failed without crashing."""
    session = test_env["session"]

    # Manually create a queued saree with non-existent photo file
    corrupt_saree = Saree(
        qr_id="TS-COOPA001",
        batch_id="BATCH-A-01",
        upload_id="upload-corrupt-001",
        image_path="/nonexistent/path/image.jpg",
        proc_status="queued",
    )
    session.add(corrupt_saree)
    session.commit()

    # Worker should handle safely without throwing unhandled exception
    processed = process_one_job(session)
    assert processed is True

    session.expire_all()
    saree = session.query(Saree).filter(Saree.qr_id == "TS-COOPA001").first()
    assert saree.proc_status == "failed"
    assert saree.proc_error_code == "BAD_IMAGE"
