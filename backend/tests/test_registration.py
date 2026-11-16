"""
backend/tests/test_registration.py
Automated tests for Saree Registration Workflow (Tests 14-20).
"""
import io
import pytest
from fastapi import status

from backend.models import Saree, SareePhoto, Tag


def test_14_to_20_saree_registration(client, token_staff_a, test_env, sample_image_bytes):
    """
    Test 14: Valid blank tag is accepted.
    Test 18: Duplicate upload does not create another saree (idempotency).
    Test 19: Multiple original burst photos are retained.
    Test 20: Backend immediately returns status 'queued'.
    """
    headers = {"Authorization": f"Bearer {token_staff_a}"}

    # Upload burst of 3 photos
    data = {
        "qr_id": "TS-COOPA001",
        "batch_id": "BATCH-A-01",
        "upload_id": "upload-uuid-001",
        "phone_model": "Pixel 7 Pro",
    }
    files = [
        ("photos", ("photo1.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")),
        ("photos", ("photo2.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")),
        ("photos", ("photo3.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")),
    ]

    # Test 14 & 20: Registration accepts tag and returns 'queued' immediately
    resp = client.post("/saree", data=data, files=files, headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == {"status": "queued"}

    session = test_env["session"]

    # Verify Tag locked as 'registered'
    tag = session.query(Tag).filter(Tag.qr_id == "TS-COOPA001").first()
    assert tag.status == "registered"

    # Verify Saree created with status 'queued'
    saree = session.query(Saree).filter(Saree.qr_id == "TS-COOPA001").first()
    assert saree is not None
    assert saree.proc_status == "queued"
    assert saree.upload_id == "upload-uuid-001"

    # Test 19: Verify all 3 burst photos are saved and linked in SareePhoto
    photos = session.query(SareePhoto).filter(SareePhoto.saree_qr_id == "TS-COOPA001").order_by(SareePhoto.frame_index.asc()).all()
    assert len(photos) == 3
    assert photos[0].frame_index == 0
    assert photos[1].frame_index == 1
    assert photos[2].frame_index == 2

    # Test 18: Duplicate upload ID returns earlier result without creating duplicate saree
    files_repeat = [("photos", ("photo1.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))]
    resp_dup = client.post("/saree", data=data, files=files_repeat, headers=headers)
    assert resp_dup.status_code == status.HTTP_200_OK
    assert resp_dup.json() == {"status": "queued"}

    # Count sarees should still be exactly 1
    saree_count = session.query(Saree).filter(Saree.qr_id == "TS-COOPA001").count()
    assert saree_count == 1


def test_15_unknown_tag_rejected(client, token_staff_a, sample_image_bytes):
    """Test 15: Unknown QR tag returns HTTP 404 TAG_UNKNOWN."""
    headers = {"Authorization": f"Bearer {token_staff_a}"}
    data = {
        "qr_id": "TS-UNKNOWN99",
        "batch_id": "BATCH-A-01",
        "upload_id": "upload-uuid-002",
    }
    files = [("photos", ("photo.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))]

    resp = client.post("/saree", data=data, files=files, headers=headers)
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["code"] == "TAG_UNKNOWN"


def test_16_used_tag_rejected(client, token_staff_a, test_env, sample_image_bytes):
    """Test 16: Already registered tag returns HTTP 409 TAG_USED."""
    session = test_env["session"]
    # Mark tag as already registered
    tag = session.query(Tag).filter(Tag.qr_id == "TS-COOPA001").first()
    tag.status = "registered"
    session.commit()

    headers = {"Authorization": f"Bearer {token_staff_a}"}
    data = {
        "qr_id": "TS-COOPA001",
        "batch_id": "BATCH-A-01",
        "upload_id": "upload-uuid-003",
    }
    files = [("photos", ("photo.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))]

    resp = client.post("/saree", data=data, files=files, headers=headers)
    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.json()["code"] == "TAG_USED"


def test_retake_workflow_after_quality_failure(client, token_staff_a, test_env, sample_image_bytes, sample_tilted_image_bytes):
    """
    Task 4: Retake bug fix test:
      fail quality check -> release tag to blank -> retake with new upload_id -> queued -> done.
    Verifies that UNIQUE sarees.qr_id constraint collision does not occur.
    """
    from backend.worker.worker import process_one_job
    session = test_env["session"]
    headers = {"Authorization": f"Bearer {token_staff_a}"}

    # 1. Initial attempt with tilted photo (fails quality check)
    data1 = {
        "qr_id": "TS-COOPA001",
        "batch_id": "BATCH-A-01",
        "upload_id": "upload-fail-001",
    }
    files1 = [("photos", ("tilted.jpg", io.BytesIO(sample_tilted_image_bytes), "image/jpeg"))]
    resp1 = client.post("/saree", data=data1, files=files1, headers=headers)
    assert resp1.status_code == status.HTTP_200_OK

    # Process: worker fails on quality and releases tag back to blank
    assert process_one_job(session) is True
    session.expire_all()
    saree1 = session.query(Saree).filter(Saree.qr_id == "TS-COOPA001").first()
    tag = session.query(Tag).filter(Tag.qr_id == "TS-COOPA001").first()
    assert saree1.proc_status == "failed"
    assert tag.status == "blank"

    # 2. Retake registration with NEW upload_id and clean photo
    data2 = {
        "qr_id": "TS-COOPA001",
        "batch_id": "BATCH-A-01",
        "upload_id": "upload-retake-002",
    }
    files2 = [("photos", ("clean.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))]
    resp2 = client.post("/saree", data=data2, files=files2, headers=headers)
    assert resp2.status_code == status.HTTP_200_OK
    assert resp2.json()["status"] == "queued"

    # Verify old failed record was replaced with queued record
    session.expire_all()
    saree2 = session.query(Saree).filter(Saree.qr_id == "TS-COOPA001").first()
    assert saree2.upload_id == "upload-retake-002"
    assert saree2.proc_status == "queued"

    # 3. Process retake: must successfully finish (status 'done')
    assert process_one_job(session) is True
    session.expire_all()
    saree_done = session.query(Saree).filter(Saree.qr_id == "TS-COOPA001").first()
    assert saree_done.proc_status == "done"
    assert saree_done.epi is not None
    assert saree_done.ppi is not None
