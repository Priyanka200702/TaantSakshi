"""
backend/tests/test_verification.py
Automated tests for Saree Verification & Calibration Enforcement (Tests 28-33).
"""
import io
import pytest
from fastapi import status

from backend.config import FINGERPRINTS_DIR
from backend.models import Saree, Verification
from backend.services.vision_adapter import compare_fingerprints
from backend.worker.worker import process_one_job


def test_28_to_31_verification_uncalibrated(client, token_staff_a, token_seller, test_env, sample_image_bytes):
    """
    Test 28: New photo verified against original registered fingerprint.
    Test 29: Verification record saved in database.
    Test 30: Uncalibrated engine (null threshold in config) returns 'not_calibrated'.
    Test 31: NEVER returns genuine or no_match when uncalibrated!
    """
    session = test_env["session"]
    headers_staff = {"Authorization": f"Bearer {token_staff_a}"}
    headers_seller = {"Authorization": f"Bearer {token_seller}"}

    # 1. Register saree
    data = {
        "qr_id": "TS-COOPA001",
        "batch_id": "BATCH-A-01",
        "upload_id": "upload-reg-ver",
    }
    files = [("photos", ("photo1.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))]
    resp = client.post("/saree", data=data, files=files, headers=headers_staff)
    assert resp.status_code == status.HTTP_200_OK

    # 2. Process with worker
    process_one_job(session)

    # 3. Seller submits new photograph for verification
    v_data = {"upload_id": "verify-attempt-001"}
    v_files = [("photos", ("verify_photo.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))]

    resp_v = client.post("/verify/TS-COOPA001", data=v_data, files=v_files, headers=headers_seller)
    assert resp_v.status_code == status.HTTP_200_OK
    v_json = resp_v.json()

    # Test 30 & 31: Because config.yaml has null match thresholds, MUST return 'not_calibrated'
    assert v_json["result"] == "not_calibrated"
    assert v_json["score"] is None  # Score must not be faked
    assert "pending calibration" in v_json["reason"].lower()
    assert v_json["code"] == "NOT_CALIBRATED"
    assert "pending calibration" in v_json["message_en"].lower()
    assert len(v_json["message_bn"]) > 0

    # Test unique fingerprint folder per verification
    verify_fp_dir = FINGERPRINTS_DIR / "verify_verify-attempt-001"
    assert verify_fp_dir.exists()

    # Test 29: Verification record saved in database
    session.expire_all()
    rec = session.query(Verification).filter(Verification.qr_id == "TS-COOPA001").first()
    assert rec is not None
    assert rec.match == "not_calibrated"
    assert rec.code == "NOT_CALIBRATED"
    assert rec.by_user == "Seller User"


def test_32_verification_quality_failure_returns_retake(client, token_staff_a, token_seller, test_env, sample_image_bytes, sample_tilted_image_bytes):
    """Test 32: Unsuitable quality photograph submitted for verification returns 'retake'."""
    session = test_env["session"]
    headers_staff = {"Authorization": f"Bearer {token_staff_a}"}
    headers_seller = {"Authorization": f"Bearer {token_seller}"}

    # Register saree with good image
    client.post(
        "/saree",
        data={"qr_id": "TS-COOPA001", "batch_id": "BATCH-A-01", "upload_id": "upload-retake-test"},
        files=[("photos", ("photo1.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))],
        headers=headers_staff,
    )
    process_one_job(session)

    # Verify with heavily tilted image
    v_files = [("photos", ("tilted.png", io.BytesIO(sample_tilted_image_bytes), "image/png"))]
    resp_v = client.post("/verify/TS-COOPA001", files=v_files, headers=headers_seller)
    assert resp_v.status_code == status.HTTP_200_OK
    v_json = resp_v.json()

    assert v_json["result"] == "retake"
    assert v_json["score"] is None
    assert v_json["code"] is not None
    assert v_json["message_en"] is not None
    assert v_json["message_bn"] is not None


def test_33_calibrated_engine_result_mapping():
    """Test 33: Mocked calibrated engine responses map correctly to 'genuine' or 'no_match'."""
    # When calibrated and match is True -> 'genuine'
    calibrated_true = {
        "ok": True,
        "calibrated": True,
        "match": True,
        "score": 0.85,
    }
    # Test adapter mapping logic with mock
    from unittest.mock import patch
    with patch("engine.compat.match", return_value=calibrated_true):
        res = compare_fingerprints("fp_a", "fp_b")
        assert res["result"] == "genuine"
        assert res["score"] == 0.85

    # When calibrated and match is False -> 'no_match'
    calibrated_false = {
        "ok": True,
        "calibrated": True,
        "match": False,
        "score": 0.12,
    }
    with patch("engine.compat.match", return_value=calibrated_false):
        res2 = compare_fingerprints("fp_a", "fp_b")
        assert res2["result"] == "no_match"
        assert res2["score"] == 0.12
