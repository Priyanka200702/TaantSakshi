"""
backend/tests/test_admin_listing.py
Automated tests for Admin Dashboard, CSV Export, and Group 5 Listing (Tests 42-45).
"""
import io
import pytest
from fastapi import status

from backend.models import Saree, Tag
from backend.worker.worker import process_one_job


def test_42_to_44_admin_dashboard_and_csv(client, token_admin, token_staff_a, test_env, sample_image_bytes):
    """
    Test 42: Admin authentication grants access to /admin.
    Test 43: Staff or ordinary users cannot access /admin.
    Test 44: CSV export contains proposal metrics (EPI, PPI, Grades).
    """
    session = test_env["session"]

    # Register and process a saree
    client.post(
        "/saree",
        data={"qr_id": "TS-COOPA001", "batch_id": "BATCH-A-01", "upload_id": "upload-admin-test"},
        files=[("photos", ("photo.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))],
        headers={"Authorization": f"Bearer {token_staff_a}"},
    )
    process_one_job(session)

    # Test 43: Staff cannot access admin dashboard (401 / 403)
    resp_staff = client.get("/admin", headers={"Authorization": f"Bearer {token_staff_a}"})
    assert resp_staff.status_code == status.HTTP_401_UNAUTHORIZED or resp_staff.status_code == status.HTTP_403_FORBIDDEN

    # Test 42: Admin user accesses /admin successfully
    resp_admin = client.get("/admin", headers={"Authorization": f"Bearer {token_admin}"})
    assert resp_admin.status_code == status.HTTP_200_OK
    assert "TantSaakshi Admin Dashboard" in resp_admin.text
    assert "TS-COOPA001" in resp_admin.text

    # Test 44: Admin downloads CSV export
    resp_csv = client.get("/admin/export.csv", headers={"Authorization": f"Bearer {token_admin}"})
    assert resp_csv.status_code == status.HTTP_200_OK
    assert "text/csv" in resp_csv.headers["content-type"]
    csv_text = resp_csv.text

    # Verify CSV headers & data
    assert "qr_id,coop_id,coop_name" in csv_text
    assert "ends_per_inch_warp" in csv_text
    assert "picks_per_inch_weft" in csv_text
    assert "TS-COOPA001" in csv_text
    assert "Dhaniakhali Weavers Society" in csv_text


def test_45_listing_endpoint(client, token_staff_a, test_env, sample_image_bytes):
    """Test 45: Listing endpoint /listing/{design_id} returns agreed handloom specifications."""
    session = test_env["session"]

    # Register and process saree
    client.post(
        "/saree",
        data={"qr_id": "TS-COOPA001", "batch_id": "BATCH-A-01", "upload_id": "upload-listing-test"},
        files=[("photos", ("photo.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))],
        headers={"Authorization": f"Bearer {token_staff_a}"},
    )
    process_one_job(session)

    # Update tag status to 'listed'
    session.expire_all()
    tag = session.query(Tag).filter(Tag.qr_id == "TS-COOPA001").first()
    tag.status = "listed"
    session.commit()

    # Query listing endpoint by QR ID
    resp = client.get("/listing/TS-COOPA001")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["design_id"] == "TS-COOPA001"
    assert data["saree_type"] == "Dhaniakhali Cotton"
    assert data["cooperative"] == "Dhaniakhali Weavers Society"
    assert data["district"] == "Hooghly"
    assert data["grade"] is None
    assert data["status"] == "listed"
    assert data["ends_per_inch"] is not None
    assert data["picks_per_inch"] is not None
