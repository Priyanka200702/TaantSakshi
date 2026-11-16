"""
backend/scripts/seed_data.py
Initial database seeder for cooperatives, weavers, and users.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project path is accessible
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.auth import hash_pin
from backend.database import SessionLocal, init_db
from backend.models import Coop, User, Weaver


def seed_database():
    init_db()
    db = SessionLocal()

    try:
        # 1. Seed Cooperatives
        coop_dhaniakhali = db.query(Coop).filter(Coop.id == "COOP-DHANIAKHALI").first()
        if not coop_dhaniakhali:
            coop_dhaniakhali = Coop(
                id="COOP-DHANIAKHALI",
                name="Dhaniakhali Weavers Co-operative Society Ltd.",
                district="Hooghly",
            )
            db.add(coop_dhaniakhali)

        coop_santipur = db.query(Coop).filter(Coop.id == "COOP-SANTIPUR").first()
        if not coop_santipur:
            coop_santipur = Coop(
                id="COOP-SANTIPUR",
                name="Santipur Handloom Khadi Weavers Association",
                district="Nadia",
            )
            db.add(coop_santipur)

        db.commit()

        # 2. Seed Weavers
        weavers_data = [
            ("WVR-DH-01", "COOP-DHANIAKHALI", "Subimal Basak", True),
            ("WVR-DH-02", "COOP-DHANIAKHALI", "Gouranga Das", False),
            ("WVR-ST-01", "COOP-SANTIPUR", "Kartick Paul", True),
            ("WVR-ST-02", "COOP-SANTIPUR", "Prabhat Debnath", False),
        ]
        for wid, cid, name, show_pub in weavers_data:
            w = db.query(Weaver).filter(Weaver.id == wid).first()
            if not w:
                w = Weaver(id=wid, coop_id=cid, name=name, show_name_publicly=show_pub)
                db.add(w)

        db.commit()

        # 3. Seed Users (Phone + PIN = 1234)
        users_data = [
            ("USR-ADMIN", None, "Project Administrator", "9876543210", "1234", "admin"),
            ("USR-STAFF-DH", "COOP-DHANIAKHALI", "Animesh Mukherjee (Staff)", "9800000001", "1234", "staff"),
            ("USR-STAFF-ST", "COOP-SANTIPUR", "Debashis Roy (Staff)", "9800000002", "1234", "staff"),
            ("USR-SELLER", None, "Swapan Saha (Authorized Retailer)", "9800000003", "1234", "seller"),
        ]

        for uid, cid, name, phone, pin, role in users_data:
            u = db.query(User).filter(User.id == uid).first()
            if not u:
                u = User(
                    id=uid,
                    coop_id=cid,
                    name=name,
                    phone=phone,
                    pin_hash=hash_pin(pin),
                    role=role,
                )
                db.add(u)

        db.commit()
        print("Database successfully seeded with cooperatives, weavers, and users.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
