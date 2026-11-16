"""
backend/tests/test_coop_isolation.py
Automated tests for Cooperative Isolation (Tests 6-8).
"""
import io
import pytest
from fastapi import status


def test_06_staff_sees_only_own_weavers(client, token_staff_a, token_staff_b):
    """Test 6: Staff sees only their own cooperative's weavers."""
    headers_a = {"Authorization": f"Bearer {token_staff_a}"}
    resp_a = client.get("/weavers", headers=headers_a)
    assert resp_a.status_code == status.HTTP_200_OK
    weavers_a = resp_a.json()
    assert len(weavers_a) == 2
    ids_a = {w["id"] for w in weavers_a}
    assert "WVR-A1" in ids_a
    assert "WVR-A2" in ids_a
    assert "WVR-B1" not in ids_a

    headers_b = {"Authorization": f"Bearer {token_staff_b}"}
    resp_b = client.get("/weavers", headers=headers_b)
    assert resp_b.status_code == status.HTTP_200_OK
    weavers_b = resp_b.json()
    assert len(weavers_b) == 1
    assert weavers_b[0]["id"] == "WVR-B1"


def test_07_staff_cannot_register_other_coop_tag(client, token_staff_a, sample_image_bytes):
    """Test 7: Staff A cannot register Coop B's tag (TAG_OTHER_COOP error)."""
    headers_a = {"Authorization": f"Bearer {token_staff_a}"}
    # TS-COOPB001 belongs to COOP-B
    data = {
        "qr_id": "TS-COOPB001",
        "batch_id": "BATCH-A-01",
        "upload_id": "upload-iso-001",
        "phone_model": "Pixel 7",
    }
    files = [("photos", ("test.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))]

    resp = client.post("/saree", data=data, files=files, headers=headers_a)
    assert resp.status_code == status.HTTP_409_CONFLICT
    res_json = resp.json()
    assert res_json["code"] == "TAG_OTHER_COOP"
    assert "message_en" in res_json
    assert "message_bn" in res_json


def test_08_staff_cannot_use_other_coop_batch(client, token_staff_b):
    """Test 8: Staff B cannot create batch using Coop A's weaver (WEAVER_OTHER_COOP)."""
    headers_b = {"Authorization": f"Bearer {token_staff_b}"}
    resp = client.post("/batch", json={"weaver_id": "WVR-A1", "saree_type": "Silk"}, headers=headers_b)
    assert resp.status_code == status.HTTP_409_CONFLICT
    res_json = resp.json()
    assert res_json["code"] == "WEAVER_OTHER_COOP"
