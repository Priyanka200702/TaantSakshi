"""
backend/main.py
Primary FastAPI application entry point for TantSaakshi.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import BACKEND_DIR, TAGS_PDF_DIR, get_message
from backend.database import init_db
from backend.routers import (
    admin,
    batches,
    certificates,
    listings,
    login,
    sarees,
    tags,
    verification,
    weavers,
)

logger = logging.getLogger("tantsaakshi.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: initialize database tables."""
    init_db()
    logger.info("TantSaakshi SQLite database initialized.")
    yield


app = FastAPI(
    title="TantSaakshi Handloom Authenticity Backend API",
    description="Digital authenticity, provenance, and thread-count traceability for genuine handloom sarees.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for phone app and web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static assets
static_dir = BACKEND_DIR / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Custom bilingual HTTPException handler
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    """
    Ensure every error response provides agreed bilingual fields:
    code, message_en, and message_bn.
    """
    if isinstance(exc.detail, dict):
        payload = exc.detail.copy()
        code = payload.get("code", "ERROR")
        if "message_en" not in payload:
            payload["message_en"] = get_message(code, "en", str(payload.get("detail", code)))
        if "message_bn" not in payload:
            payload["message_bn"] = get_message(code, "bn", payload["message_en"])
        return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)

    # String detail
    detail_str = str(exc.detail)
    if detail_str == "Wrong phone or PIN":
        code = "AUTH_FAILED"
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": "Wrong phone or PIN",
                "code": code,
                "message_en": "Wrong phone or PIN",
                "message_bn": "ভুল ফোন নম্বর বা পিন",
            },
            headers=exc.headers,
        )

    code = "ERROR"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": detail_str,
            "code": code,
            "message_en": detail_str,
            "message_bn": get_message(detail_str, "bn", detail_str),
        },
        headers=exc.headers,
    )


# Include API Routers in accordance with agreed contract
app.include_router(login.router)
app.include_router(weavers.router)
app.include_router(tags.router)
app.include_router(batches.router)
app.include_router(sarees.router)
app.include_router(verification.router)
app.include_router(certificates.router)
app.include_router(admin.router)
app.include_router(listings.router)


@app.get("/", include_in_schema=False)
def frontend_root():
    """Serve the cooperative and seller phone-first web app on root."""
    return FileResponse(str(static_dir / "app.html"), media_type="text/html")


@app.get("/api/health", tags=["System"])
def root():
    """Service health and index."""
    return {
        "service": "TantSaakshi Handloom Authenticity Backend",
        "status": "online",
        "app": "/app",
        "documentation": "/docs",
    }


@app.get("/app", include_in_schema=False)
def frontend_app():
    """Serve the cooperative and seller phone-first web app."""
    return FileResponse(str(static_dir / "app.html"), media_type="text/html")

@app.get("/studio", include_in_schema=False)
def frontend_studio():
    return FileResponse(str(static_dir / "app.html"), media_type="text/html")

@app.get("/verify", include_in_schema=False)
def frontend_verify():
    return FileResponse(str(static_dir / "app.html"), media_type="text/html")

@app.get("/catalogue", include_in_schema=False)
def frontend_catalogue():
    return FileResponse(str(static_dir / "app.html"), media_type="text/html")

@app.get("/login", include_in_schema=False)
def frontend_login():
    return FileResponse(str(static_dir / "app.html"), media_type="text/html")

@app.get("/register", include_in_schema=False)
def frontend_register():
    return FileResponse(str(static_dir / "app.html"), media_type="text/html")


@app.get("/service-worker.js", include_in_schema=False)
def frontend_service_worker():
    """Allow the app shell and queued uploads to work offline on supported browsers."""
    return FileResponse(
        str(static_dir / "sw.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )
