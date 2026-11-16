"""
backend/tests/test_certificates.py
Automated tests for Public Digital Certificate Page & Anti-Counterfeit Warnings (Tests 34-41).
"""
import io
import pytest
from fastapi import status

from backend.models import Batch, CertificateScan, Saree, Tag, Weaver
from backend.worker.worker import process_one_job


def test_34_state_1_unknown_qr(client):
    """Test 34: Unknown QR tag displays State 1: 'Not a valid TantSaakshi tag'."""
    resp = client.get("/c/TS-NONEXISTENT")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    html = resp.text
    assert "Not a valid TantSaakshi tag" in html or "বৈধ তাঁতসাক্ষী ট্যাগ নয়" in html


def test_35_state_2_blank_qr(client):
    """Test 35: Blank unassigned tag displays State 2: 'This tag has not been registered'."""
    resp = client.get("/c/TS-COOPA001?lang=en")
    assert resp.status_code == status.HTTP_200_OK
    html = resp.text
    assert "This tag has not been registered" in html


def test_36_state_3_processing_qr(client, token_staff_a, sample_image_bytes):
    """Test 36: Registered but queued/processing tag displays State 3: 'Certificate being prepared'."""
    # Register saree
    client.post(
        "/saree",
        data={"qr_id": "TS-COOPA001", "batch_id": "BATCH-A-01", "upload_id": "upload-state-3"},
        files=[("photos", ("photo.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))],
        headers={"Authorization": f"Bearer {token_staff_a}"},
    )

    resp = client.get("/c/TS-COOPA001?lang=en")
    assert resp.status_code == status.HTTP_200_OK
    html = resp.text
    assert "Certificate being prepared" in html


def test_37_to_39_and_41_state_4_full_certificate(client, token_staff_a, test_env, sample_image_bytes):
    """
    Test 37: Completed registration displays State 4: Full authenticity certificate.
    Test 38: Weaver privacy is respected (show_name_publicly).
    Test 39: Certificate scan log is created.
    Test 41: Fingerprint paths are never exposed in public certificate HTML.
    """
    session = test_env["session"]
    headers = {"Authorization": f"Bearer {token_staff_a}"}

    # Register and process saree
    client.post(
        "/saree",
        data={"qr_id": "TS-COOPA001", "batch_id": "BATCH-A-01", "upload_id": "upload-state-4"},
        files=[("photos", ("photo.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))],
        headers=headers,
    )
    process_one_job(session)

    # Request English certificate
    resp_en = client.get("/c/TS-COOPA001?lang=en")
    assert resp_en.status_code == status.HTTP_200_OK
    html_en = resp_en.text

    assert "TS-COOPA001" in html_en
    assert "Verified Genuine Handloom" in html_en
    assert "Dhaniakhali Weavers Society" in html_en
    # Task 2: Under provisional_tpi_only, no letter grade is faked
    assert "Quality grade: provisional / not yet assigned" in html_en
    assert "Grade A" not in html_en

    # Task 11: Display photo endpoint works
    resp_photo = client.get("/c/TS-COOPA001/photo")
    assert resp_photo.status_code == status.HTTP_200_OK
    assert "image/jpeg" in resp_photo.headers["content-type"]

    # Test 38: Weaver WVR-A1 has show_name_publicly=True -> name appears
    assert "Amiya Basak" in html_en

    # Test 39: Verify scan log recorded
    session.expire_all()
    scan = session.query(CertificateScan).filter(CertificateScan.qr_id == "TS-COOPA001").first()
    assert scan is not None

    # Test 41: Verify private fingerprint paths are NEVER in the certificate HTML
    assert ".npz" not in html_en
    assert "fingerprints" not in html_en
    assert "pin_hash" not in html_en


def test_38_weaver_privacy_hidden(client, token_staff_a, test_env, sample_image_bytes):
    """Test 38 (hidden): When weaver show_name_publicly=False, public name is masked."""
    session = test_env["session"]

    # Create a batch with private weaver WVR-A2
    batch_priv = Batch(id="BATCH-PRIV", coop_id="COOP-A", weaver_id="WVR-A2", saree_type="Cotton", started_by="USR-STAFF-A")
    tag_priv = Tag(qr_id="TS-PRIV001", coop_id="COOP-A", batch_no="BATCH-PRIV", status="blank")
    session.add_all([batch_priv, tag_priv])
    session.commit()

    # Register and process
    headers = {"Authorization": f"Bearer {token_staff_a}"}
    client.post(
        "/saree",
        data={"qr_id": "TS-PRIV001", "batch_id": "BATCH-PRIV", "upload_id": "upload-priv-001"},
        files=[("photos", ("photo.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))],
        headers=headers,
    )
    process_one_job(session)

    resp = client.get("/c/TS-PRIV001?lang=en")
    assert resp.status_code == status.HTTP_200_OK
    html = resp.text

    # Private name "Private Weaver" should NOT appear
    assert "Private Weaver" not in html
    # Masked designation should appear
    assert "Registered Cooperative Weaver" in html


def test_40_repeated_scan_warning(client, test_env):
    """Test 40 / Task 9: Warning banner appears after distinct IP scan count exceeds threshold."""
    session = test_env["session"]

    # Scans from the SAME IP do not trigger warning even with 15 scans
    for _ in range(15):
        client.get("/c/TS-COOPA001", headers={"X-Forwarded-For": "10.0.0.1"})

    resp_same = client.get("/c/TS-COOPA001?lang=en", headers={"X-Forwarded-For": "10.0.0.1"})
    assert "Notice: Possible Duplicate Scan" not in resp_same.text

    # Distinct IPs exceeding threshold (threshold is 10) trigger warning
    for i in range(12):
        client.get("/c/TS-COOPA001", headers={"X-Forwarded-For": f"192.168.1.{i+1}"})

    resp = client.get("/c/TS-COOPA001?lang=en")
    html = resp.text
    assert "Notice: Possible Duplicate Scan" in html or "This tag has been scanned multiple times" in html
