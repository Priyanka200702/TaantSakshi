"""
backend/tests/test_qr_generation.py
Automated tests for QR Tag Generation & PDF printing (Tests 9-13).
"""
from pathlib import Path
import pytest
from fastapi import status

from backend.models import Tag, TagGenerationLog
from backend.services.qr_service import SAFE_CHARSET, generate_unique_qr_ids


def test_09_qr_ids_random_and_unique():
    """Test 9: QR IDs are cryptographically random and unique."""
    ids = generate_unique_qr_ids(1000)
    assert len(ids) == 1000
    assert len(set(ids)) == 1000
    for qid in ids:
        assert qid.startswith("TS-")
        assert len(qid) == 11  # "TS-" (3) + 8 chars


def test_10_confusing_characters_excluded():
    """Test 10: Confusing characters (0, O, 1, I, L) are strictly excluded from charset."""
    confusing = {"0", "O", "1", "I", "L"}
    for char in confusing:
        assert char not in SAFE_CHARSET

    # Generate 500 IDs and verify none contain confusing characters
    ids = generate_unique_qr_ids(500)
    for qid in ids:
        code_part = qid.replace("TS-", "")
        for char in confusing:
            assert char not in code_part


def test_11_to_13_tag_generation_api(client, token_staff_a, test_env):
    """
    Test 11: Tags saved as 'blank'.
    Test 12: PDF generation works and URL is returned.
    Test 13: Tag generation is logged in database.
    """
    headers = {"Authorization": f"Bearer {token_staff_a}"}
    resp = client.post("/tags/generate", json={"count": 54}, headers=headers)
    assert resp.status_code == status.HTTP_200_OK

    data = resp.json()
    assert "batch_no" in data
    assert data["count"] == 54
    assert "pdf_url" in data
    assert "/tags/pdf/" in data["pdf_url"]

    # Verify tags saved in DB with status 'blank'
    session = test_env["session"]
    saved_tags = session.query(Tag).filter(Tag.batch_no == data["batch_no"]).all()
    assert len(saved_tags) == 54
    for tag in saved_tags:
        assert tag.status == "blank"
        assert tag.coop_id == "COOP-A"

    # Verify generation is logged
    log_entry = session.query(TagGenerationLog).filter(TagGenerationLog.batch_no == data["batch_no"]).first()
    assert log_entry is not None
    assert log_entry.count == 54
    assert log_entry.coop_id == "COOP-A"
    assert log_entry.user_id == "USR-STAFF-A"
    assert Path(log_entry.pdf_path).exists()

    # Task 6: Secure PDF download checks
    pdf_filename = Path(data["pdf_url"]).name

    # 1. Unauthenticated download fails with 401
    resp_unauth = client.get(f"/tags/pdf/{pdf_filename}")
    assert resp_unauth.status_code == status.HTTP_401_UNAUTHORIZED

    # 2. Authenticated download by Coop-A staff succeeds
    resp_coop_a = client.get(f"/tags/pdf/{pdf_filename}", headers=headers)
    assert resp_coop_a.status_code == status.HTTP_200_OK
    assert "application/pdf" in resp_coop_a.headers["content-type"]

    # 3. Authenticated download by Coop-B staff is rejected with 403 Forbidden
    from backend.auth import create_access_token
    token_staff_b = create_access_token({"sub": "USR-STAFF-B", "role": "staff", "coop_id": "COOP-B", "name": "Staff B"})
    resp_coop_b = client.get(f"/tags/pdf/{pdf_filename}", headers={"Authorization": f"Bearer {token_staff_b}"})
    assert resp_coop_b.status_code == status.HTTP_403_FORBIDDEN
