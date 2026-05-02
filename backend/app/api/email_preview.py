"""Email preview & test-send endpoints."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.config import settings
from app.tools.email_tool import (
    build_caregiver_email_html,
    build_patient_welcome_html,
    send_email,
)

router = APIRouter(prefix="/email", tags=["email"])

_DEMO_PLAN = {
    "channel": "whatsapp_text",
    "check_in_times_per_day": 3,
    "check_in_time": "09:00",
    "caregiver_loop_enabled": True,
    "medication_schedule": [
        {"med": "Metformin 500mg", "time": "08:00 AM", "instruction": "After breakfast"},
        {"med": "Amlodipine 5mg", "time": "08:00 AM", "instruction": "After breakfast"},
        {"med": "Aspirin 75mg", "time": "01:00 PM", "instruction": "After lunch"},
    ],
    "red_flag_symptoms": [
        "Chest pain or tightness",
        "Sudden shortness of breath",
        "Severe dizziness or fainting",
        "Blood glucose below 60 or above 300",
    ],
}

_DEMO_CLINICAL = {"diagnosis": "Type 2 Diabetes with Hypertension"}
_DEMO_SDOH: dict = {}


@router.get("/preview/patient", response_class=HTMLResponse)
def preview_patient_email(name: str = "Ramesh Kumar"):
    """Open in browser to preview the patient welcome email."""
    _, html = build_patient_welcome_html(name, _DEMO_PLAN)
    return HTMLResponse(content=html)


@router.get("/preview/caregiver", response_class=HTMLResponse)
def preview_caregiver_email(name: str = "Ramesh Kumar"):
    """Open in browser to preview the caregiver summary email."""
    _, html = build_caregiver_email_html(name, _DEMO_PLAN, _DEMO_CLINICAL, _DEMO_SDOH)
    return HTMLResponse(content=html)


class TestSendRequest(BaseModel):
    to: str
    type: str = "patient"
    name: str = "Test Patient"


@router.post("/test-send")
def test_send_email(req: TestSendRequest):
    """Send a test email to verify Resend is working."""
    if req.type == "caregiver":
        subj, html = build_caregiver_email_html(req.name, _DEMO_PLAN, _DEMO_CLINICAL, _DEMO_SDOH)
        body = f"CareLoop care plan for {req.name} — caregiver summary"
    else:
        subj, html = build_patient_welcome_html(req.name, _DEMO_PLAN)
        body = f"Welcome to CareLoop, {req.name}!"

    result = send_email(req.to, subj, body, html=html)
    return {
        "sent": result.get("ok"),
        "mock": result.get("mock"),
        "id": result.get("id"),
        "reason": result.get("reason"),
        "email_configured": settings.has_email,
        "resend_key_set": bool(settings.resend_api_key),
        "use_mock_email": settings.use_mock_email,
        "email_from": settings.email_from,
    }


@router.get("/status")
def email_status():
    """Check current email configuration status."""
    return {
        "email_configured": settings.has_email,
        "resend_key_set": bool(settings.resend_api_key),
        "use_mock_email": settings.use_mock_email,
        "email_from": settings.email_from,
        "preview_patient": "/api/email/preview/patient",
        "preview_caregiver": "/api/email/preview/caregiver",
        "test_send_endpoint": "POST /api/email/test-send  body: {to, type, name}",
        "twilio_webhook_url": "https://www.careloops.com/api/messages/inbound",
        "twilio_note": "Set this URL in Twilio sandbox: Messaging > Sandbox > 'When a message comes in'",
    }
