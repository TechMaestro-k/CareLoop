"""CareLoop FastAPI entrypoint."""
from __future__ import annotations

import logging

from pathlib import Path

from fastapi import FastAPI
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

# Serve generated TTS MP3s so Twilio can fetch them as WhatsApp media.
app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")


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
        "gmail_mock": not settings.has_email,
        "razorpay_mock": not settings.has_razorpay,
    }


@app.post("/api/admin/seed")
def admin_seed():
    """Run one-time seed of 3 demo patients including Mrs. Sharma."""
    from app.seed.synthetic_patients import run_seed
    return run_seed()


@app.get("/")
def root():
    return {"app": "CareLoop", "version": "0.1.0", "docs": "/docs"}
