"""
backend/tests/conftest.py
Pytest fixtures with isolated test database, storage, and authentication tokens.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Ensure test SECRET_KEY is set before importing backend modules
os.environ.setdefault("SECRET_KEY", "test-secret-key-tantsaakshi-pytest-suite-2026")
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.auth import create_access_token, hash_pin
from backend.database import Base, get_db
from backend.main import app
from backend.models import Batch, Coop, Saree, Tag, User, Weaver


@pytest.fixture(scope="session")
def sample_image_bytes():
    """Load sample test image from eval directory."""
    img_path = PROJECT_DIR / "eval" / "sample_input" / "saree_01_clean.png"
    if not img_path.exists():
        pytest.skip("Sample test image saree_01_clean.png not found")
    with open(img_path, "rb") as f:
        return f.read()


@pytest.fixture(scope="session")
def sample_tilted_image_bytes():
    """Load tilted test image from eval directory."""
    img_path = PROJECT_DIR / "eval" / "sample_input" / "saree_03_tilted.png"
    if not img_path.exists():
        pytest.skip("Sample test image saree_03_tilted.png not found")
    with open(img_path, "rb") as f:
        return f.read()


@pytest.fixture
def test_env(tmp_path):
    """Create isolated SQLite database and storage directories for each test."""
    db_file = tmp_path / "test_tantsaakshi.db"
    test_db_url = f"sqlite:///{db_file}"

    engine = create_engine(test_db_url, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()

    # Seed cooperatives
    coop_a = Coop(id="COOP-A", name="Dhaniakhali Weavers Society", district="Hooghly")
    coop_b = Coop(id="COOP-B", name="Santipur Khadi Association", district="Nadia")
    session.add_all([coop_a, coop_b])

    # Seed weavers
    weaver_a1 = Weaver(id="WVR-A1", coop_id="COOP-A", name="Amiya Basak", show_name_publicly=True)
    weaver_a2 = Weaver(id="WVR-A2", coop_id="COOP-A", name="Private Weaver", show_name_publicly=False)
    weaver_b1 = Weaver(id="WVR-B1", coop_id="COOP-B", name="Bimal Paul", show_name_publicly=True)
    session.add_all([weaver_a1, weaver_a2, weaver_b1])

    # Seed users
    admin_user = User(id="USR-ADMIN", coop_id=None, name="Admin User", phone="9000000000", pin_hash=hash_pin("1234"), role="admin")
    staff_a = User(id="USR-STAFF-A", coop_id="COOP-A", name="Staff A", phone="9000000001", pin_hash=hash_pin("1234"), role="staff")
    staff_b = User(id="USR-STAFF-B", coop_id="COOP-B", name="Staff B", phone="9000000002", pin_hash=hash_pin("1234"), role="staff")
    seller_user = User(id="USR-SELLER", coop_id=None, name="Seller User", phone="9000000003", pin_hash=hash_pin("1234"), role="seller")
    session.add_all([admin_user, staff_a, staff_b, seller_user])

    # Seed a batch for Coop A
    batch_a = Batch(id="BATCH-A-01", coop_id="COOP-A", weaver_id="WVR-A1", saree_type="Dhaniakhali Cotton", started_by="USR-STAFF-A")
    session.add(batch_a)

    # Seed a blank tag for Coop A and one for Coop B
    tag_a = Tag(qr_id="TS-COOPA001", coop_id="COOP-A", batch_no="BATCH-A-01", status="blank")
    tag_b = Tag(qr_id="TS-COOPB001", coop_id="COOP-B", batch_no="BATCH-B-01", status="blank")
    session.add_all([tag_a, tag_b])

    session.commit()

    # Override get_db dependency
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield {
        "session": session,
        "engine": engine,
        "SessionLocal": TestingSessionLocal,
        "db_file": db_file,
    }

    session.close()
    app.dependency_overrides.clear()


@pytest.fixture
def client(test_env):
    """TestClient bound to isolated test database."""
    return TestClient(app)


@pytest.fixture
def token_admin():
    return create_access_token({"sub": "USR-ADMIN", "role": "admin", "coop_id": None, "name": "Admin User"})


@pytest.fixture
def token_staff_a():
    return create_access_token({"sub": "USR-STAFF-A", "role": "staff", "coop_id": "COOP-A", "name": "Staff A"})


@pytest.fixture
def token_staff_b():
    return create_access_token({"sub": "USR-STAFF-B", "role": "staff", "coop_id": "COOP-B", "name": "Staff B"})


@pytest.fixture
def token_seller():
    return create_access_token({"sub": "USR-SELLER", "role": "seller", "coop_id": None, "name": "Seller User"})
