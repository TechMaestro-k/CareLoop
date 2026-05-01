from __future__ import annotations

from pathlib import Path
import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import (
    booking,
    doctor,
    insights,
    messages,
    patients,
    prompts,
    razorpay_webhook,
    reasoning,
)
from app.config import settings
from app.scheduler.jobs import (
    reschedule_active_patients,
    shutdown_scheduler,
    start_scheduler,
)
from app.tools.voice import AUDIO_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("careloop")

app = FastAPI(title="CareLoop API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(patients.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(doctor.router, prefix="/api")
app.include_router(prompts.router, prefix="/api")
app.include_router(razorpay_webhook.router, prefix="/api")
app.include_router(reasoning.router, prefix="/api")
app.include_router(booking.router, prefix="/api")
app.include_router(insights.router, prefix="/api")

app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST_CANDIDATES = (
    BACKEND_ROOT / "frontend_dist",
    REPO_ROOT / "frontend_dist",
)
FRONTEND_DIST = next(
    (path for path in FRONTEND_DIST_CANDIDATES if (path / "index.html").exists()),
    FRONTEND_DIST_CANDIDATES[0],
)
INDEX_HTML = FRONTEND_DIST / "index.html"

if FRONTEND_DIST.exists() and INDEX_HTML.exists():
    log.info("Serving frontend from %s", FRONTEND_DIST)
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="frontend-assets",
    )
else:
    log.warning("No frontend dist mounted at %s", FRONTEND_DIST)


@app.on_event("startup")
def on_startup():
    log.info("CareLoop starting (supabase=%s, groq=%s)",
             settings.has_supabase, bool(settings.groq_api_key))
    start_scheduler()
    reschedule_active_patients()


@app.on_event("shutdown")
def on_shutdown():
    shutdown_scheduler()


@app.get("/api/healthz")
def healthz():
    return {
        "ok": True,
        "supabase": settings.has_supabase,
        "groq": bool(settings.groq_api_key),
        "twilio_mock": not settings.has_twilio,
        "email_mock": not settings.has_email,
        "gmail_mock": not settings.has_email,
        "razorpay_mock": not settings.has_razorpay,
    }


@app.post("/api/admin/seed")
def admin_seed():
    from app.seed.synthetic_patients import run_seed
    return run_seed()


@app.get("/")
def root():
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    return {"app": "CareLoop", "version": "0.1.0", "docs": "/docs"}


@app.get("/favicon.svg")
def favicon():
    favicon_path = FRONTEND_DIST / "favicon.svg"
    if favicon_path.exists():
        return FileResponse(favicon_path)
    return {"app": "CareLoop", "version": "0.1.0", "docs": "/docs"}


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    return {"app": "CareLoop", "version": "0.1.0", "docs": "/docs", "path": full_path}
