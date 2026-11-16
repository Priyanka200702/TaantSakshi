"""
backend/tests/test_auth.py
Automated tests for Authentication & RBAC (Tests 1-5).
"""
import pytest
from fastapi import status


def test_01_login_correct_credentials(client):
    """Test 1: Correct phone and PIN returns valid JWT token and profile."""
    resp = client.post("/login", json={"phone": "9000000001", "pin": "1234"})
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "token" in data
    assert data["name"] == "Staff A"
    assert data["role"] == "staff"
    assert data["coop_id"] == "COOP-A"


def test_02_login_incorrect_credentials(client):
    """Test 2: Incorrect phone or PIN returns HTTP 401 and agreed message 'Wrong phone or PIN'."""
    # Wrong PIN
    resp = client.post("/login", json={"phone": "9000000001", "pin": "9999"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Wrong phone or PIN" in resp.text

    # Unknown phone
    resp2 = client.post("/login", json={"phone": "9999999999", "pin": "1234"})
    assert resp2.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Wrong phone or PIN" in resp2.text


def test_03_token_authentication(client, token_staff_a):
    """Test 3: Valid bearer token successfully accesses protected route."""
    headers = {"Authorization": f"Bearer {token_staff_a}"}
    resp = client.get("/weavers", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    assert isinstance(resp.json(), list)


def test_04_unauthorized_access(client):
    """Test 4: Missing or invalid token returns HTTP 401 Unauthorized."""
    # No header
    resp = client.get("/weavers")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    # Invalid header
    resp2 = client.get("/weavers", headers={"Authorization": "Bearer invalid.token.payload"})
    assert resp2.status_code == status.HTTP_401_UNAUTHORIZED


def test_05_role_based_access(client, token_seller, token_staff_a):
    """Test 5: Seller role cannot perform staff-only actions (e.g. tag generation)."""
    headers_seller = {"Authorization": f"Bearer {token_seller}"}
    resp = client.post("/tags/generate", json={"count": 54}, headers=headers_seller)
    assert resp.status_code == status.HTTP_403_FORBIDDEN

    # Staff can access
    headers_staff = {"Authorization": f"Bearer {token_staff_a}"}
    resp2 = client.post("/tags/generate", json={"count": 54}, headers=headers_staff)
    assert resp2.status_code == status.HTTP_200_OK
