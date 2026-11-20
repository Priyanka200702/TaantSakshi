# TantSaakshi Backend

TantSaakshi (তাঁতসাক্ষী) is a digital authenticity, provenance, and thread-count traceability system for genuine handloom sarees.

The backend acts as the system's memory, rule-keeper, and verification orchestrator, bridging mobile registration clients, a read-only computer vision engine, public buyers, and cooperative administrators.

---

## Architecture Overview

```
                      +-----------------------------+
                      |   Mobile App (Staff/Seller) |
                      +--------------+--------------+
                                     |
                                     v [HTTP / REST]
+------------------------------------+------------------------------------+
|                         TantSaakshi Backend                             |
|                                                                         |
|  +--------------------+   +---------------------+   +----------------+  |
|  | Routers (FastAPI)  |   | Services            |   | Models (SQLA)  |  |
|  | - login            |   | - qr_service        |   | - coops        |  |
|  | - weavers          |   | - registration      |   | - users        |  |
|  | - tags             |   | - verification      |   | - weavers      |  |
|  | - batches          |   | - vision_adapter    |   | - tags         |  |
|  | - sarees           |   +----------+----------+   | - batches      |  |
|  | - verification     |              |              | - sarees       |  |
|  | - certificates     |              v              | - saree_photos |  |
|  | - admin            |   +---------------------+   | - verifications|  |
|  | - listings         |   | Background Worker   |   | - scans/logs   |  |
|  +--------------------+   | (polling loop)      |   +----------------+  |
+---------------------------------------+---------------------------------+
                                        |
                                        v [Calls in-process]
                     +---------------------------------------+
                     |  READ-ONLY Computer Vision Engine     |
                     |  - engine.analyze()                   |
                     |  - engine.make_fingerprint()          |
                     |  - engine.compat.match()              |
                     +---------------------------------------+
```

---

## Directory Structure

```
TantSaakshi/
├── backend/
│   ├── auth.py                  # JWT creation, bcrypt hashing, RBAC guards
│   ├── config.py                # Central configuration, paths, bilingual messages
│   ├── database.py              # SQLite engine with WAL mode & session factory
│   ├── main.py                  # Primary FastAPI application with CORS & bilingual errors
│   ├── models.py                # 10 SQLAlchemy ORM models
│   ├── schemas.py               # Pydantic schemas with bilingual error definitions
│   ├── routers/                 # Modular API endpoints
│   │   ├── admin.py             # Admin portal (GET /admin, GET /admin/export.csv)
│   │   ├── batches.py           # Saree batch creation (POST /batch)
│   │   ├── certificates.py      # Public certificate rendering (GET /c/{qr_id})
│   │   ├── listings.py          # E-commerce listing metadata (GET /listing/{design_id})
│   │   ├── login.py             # Authentication (POST /login)
│   │   ├── sarees.py            # Saree registration & status (POST /saree, GET /saree/{qr_id})
│   │   ├── tags.py              # QR tag generation & printable PDF (POST /tags/generate)
│   │   ├── verification.py      # Fabric authenticity verification (POST /verify/{qr_id})
│   │   └── weavers.py           # Cooperative weavers lookup (GET /weavers)
│   ├── services/
│   │   ├── qr_service.py        # Secure Crockford Base32 ID generation & 54-tag A4 PDF
│   │   ├── registration_service.py # Transactional registration, burst photos, idempotency
│   │   ├── verification_service.py # Verification workflow enforcing calibration rules
│   │   └── vision_adapter.py    # Zero-modification adapter for the read-only vision engine
│   ├── worker/
│   │   └── worker.py            # Perpetual background image processing loop
│   ├── scripts/
│   │   ├── seed_data.py         # Seeds default cooperatives, weavers, and staff accounts
│   │   ├── make_tags.py         # CLI tool to generate printable batch QR PDF sheets
│   │   └── backup.py            # SQLite online backup + photos & fingerprints tarball
│   ├── static/
│   │   └── style.css            # Stylesheet for certificate and admin views
│   ├── templates/
│   │   ├── certificate.html     # Responsive Bengali/English 4-state certificate
│   │   └── admin.html           # Admin metrics and quality dashboard
│   ├── storage/                 # Persistent local assets (git-ignored)
│   │   ├── backups/
│   │   ├── fingerprints/        # Strictly private fabric fingerprint files
│   │   ├── images/              # Original raw photo bursts
│   │   ├── tags_pdf/            # Generated printable 54-tag A4 PDFs
│   │   └── tantsaakshi.db       # SQLite database (WAL mode)
│   └── tests/                   # Complete automated test suite (30 tests / 49 requirements)
├── engine/                      # READ-ONLY computer vision engine (untouched)
└── requirements-backend.txt     # Python backend dependencies
```

---

## Getting Started

### 1. Requirements & Installation

Python 3.10+ is recommended. Install backend dependencies:

```bash
pip install -r requirements-backend.txt
```

### 2. Initialize and Seed the Database

```bash
python backend/scripts/seed_data.py
```

This creates the SQLite schema in `backend/storage/tantsaakshi.db` and populates:
- Cooperatives: Dhaniakhali and Santipur.
- Weavers: Subimal Basak, Gouranga Das, Kartick Paul, Prabhat Debnath.
- Default accounts (PIN: `1234`):
  - Admin: `9876543210` (Role: `admin`)
  - Staff Dhaniakhali: `9800000001` (Role: `staff`)
  - Staff Santipur: `9800000002` (Role: `staff`)
  - Seller: `9800000003` (Role: `seller`)

### 3. Generate Printable QR Tag Sheets

Generate a batch of 54 tags formatted as an A4 printable PDF:

```bash
python backend/scripts/make_tags.py --coop COOP-DHANIAKHALI --count 54
```

The resulting PDF will be saved in `backend/storage/tags_pdf/` ready for high-resolution printing.

### 4. Run the API Server

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### 5. Run the Background Worker

In a separate terminal process, run the perpetual background worker loop:

```bash
python backend/worker/worker.py
```

The worker continuously polls for `queued` saree registrations, executes the vision engine, updates fabric metrics (EPI, PPI, grade, defects, irregularity), saves the private fingerprint, and marks the registration `done`. If photo quality fails (e.g. `NO_CARD`, `TOO_TILTED`), it safely releases the QR tag back to `blank` status so the weaver/staff does not waste the physical tag.

### 6. Open the Front-End App

With the API server running, open `http://localhost:8000/app` on a phone or desktop browser. The app follows the front-end guide's seven screens: login, home, batch setup, camera capture, batch summary, verification, and the upload queue.

The app uses the existing `/login`, `/weavers`, `/batch`, `/saree`, and `/verify/{qr_id}` endpoints. Captured photos are saved in IndexedDB before upload, then sent as the connection allows. Supported browsers can also retry queued uploads in the background. Camera access and background sync require HTTPS on a deployed site; `localhost` is allowed for local development. The live QR scanner uses the browser's `BarcodeDetector` when available and provides a tag-ID entry fallback.

---

## Automated Test Suite

Run the full automated test suite covering all 49 backend requirements:

```bash
pytest backend/tests -v
```

All 30 test cases pass without warnings:
- Authentication & JWT validation (Tests 1–5)
- Cooperative isolation & security boundaries (Tests 6–8)
- Secure QR generation & A4 PDF layout (Tests 9–13)
- Saree registration, idempotency & burst handling (Tests 14–20)
- Background worker execution, quality rejection & tag release (Tests 21–27)
- Verification & strict calibration compliance (Tests 28–33)
- Public certificate 4-state rendering & scan anti-copy logs (Tests 34–41)
- Admin portal, basic auth & scientific CSV export (Tests 42–45)
- Persistence across server restarts & backup creation (Tests 46–49)

---

## Production Deployment Checklist

1. **Base URL Configuration**:
   Set `TANTSAAKSHI_BASE_URL` to your production domain before generating printed tags:
   ```bash
   export TANTSAAKSHI_BASE_URL="https://tantsaakshi.org"
   ```
2. **Secret Key**:
   Change the default secret key to a high-entropy string:
   ```bash
   export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
   ```
3. **HTTPS Enforcement**:
   Ensure TLS/HTTPS is terminated at your reverse proxy (Nginx, Caddy, or Cloudflare) so that mobile cameras can access the secure context required by mobile browsers for QR scanning.
4. **Process Supervision**:
   Use `systemd` or `supervisord` to manage both processes:
   - `uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 4`
   - `python backend/worker/worker.py`
5. **Periodic Backups**:
   Schedule `backend/scripts/backup.py` daily via cron:
   ```bash
   0 3 * * * /usr/bin/python /path/to/TantSaakshi/backend/scripts/backup.py
   ```
