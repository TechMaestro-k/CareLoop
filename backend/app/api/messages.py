"""Inbound message webhook + manual simulate endpoint."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.agents.graph import run_engagement
from app.agents.state import empty_state
from app.db.client import safe_select
from app.scheduler.jobs import trigger_refill_for_patient
from app.tools.transcription import transcribe_twilio_media

router = APIRouter(prefix="/messages", tags=["messages"])
log = logging.getLogger(__name__)


# Plain-English / Hindi / Hinglish refill cues. The pharmacy agent itself
# still gates on cooldown + actual low inventory, so a false positive here
# is a no-op.
_REFILL_KEYWORDS = (
    "refill", "re-fill", "re fill",
    "more medicine", "more meds", "more tablets", "out of meds",
    "running out", "ran out", "finished my medicine",
    "दवा", "दवाई", "गोली", "टैबलेट",
)


def _is_refill_request(message: str) -> bool:
    if not message:
        return False
    m = message.lower()
    return any(k in m for k in _REFILL_KEYWORDS)


# Empty TwiML — tells Twilio "we accepted the message, do NOT auto-reply".
# Our actual reply is sent out-of-band via the WhatsApp REST API inside
# run_engagement(). Returning a non-TwiML body is what causes the Twilio
# sandbox to fall back to "You said: ... Configure your WhatsApp Sandbox's
# Inbound URL to change this message" once the URL field is set.
_EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def _twiml(body: str = _EMPTY_TWIML) -> Response:
    return Response(content=body, media_type="application/xml")


class SimulateRequest(BaseModel):
    patient_id: str
    message: str


@router.post("/simulate")
def simulate(req: SimulateRequest, background_tasks: BackgroundTasks):
    """Bypass Twilio: pretend a patient sent us this WhatsApp text. For demo + testing."""
    rows = safe_select("patients", match={"id": req.patient_id}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="patient not found")
    state = empty_state()
    state["patient_id"] = req.patient_id
    state["current_message"] = req.message
    state["patient_record"] = rows[0]
    state["language"] = rows[0].get("language") or "en"
    state["channel"] = rows[0].get("channel_pref") or "whatsapp_text"
    state["triggered_by"] = "inbound"
    final = run_engagement(state)
    # Explicit refill ask → defer the pharmacy agent so the triage reply
    # has already gone out by the time we touch billing.
    refill_queued = False
    if _is_refill_request(req.message):
        background_tasks.add_task(trigger_refill_for_patient, req.patient_id)
        refill_queued = True
    return {
        "classification": final.get("classification"),
        "decision": final.get("decision"),
        "decision_summary": final.get("decision"),
        "whatsapp_sent": final.get("outgoing_messages", []),
        "emails_sent": final.get("outgoing_emails", []),
        "reasoning_steps": final.get("reasoning_steps", []),
        "refill_queued": refill_queued,
    }


@router.post("/inbound")
async def twilio_inbound(
    request: Request,
    background_tasks: BackgroundTasks,
    From: str = Form(""),
    Body: str = Form(""),
    To: str = Form(""),
    NumMedia: str = Form("0"),
    MediaUrl0: Optional[str] = Form(None),
    MediaContentType0: Optional[str] = Form(None),
):
    """Twilio webhook for inbound WhatsApp messages.

    Handles BOTH text and voice notes:
    - Voice note (audio/* MediaContentType) → download from Twilio + Groq Whisper transcribe
    - Text → use Body directly

    Maps the inbound `From` number to a patient row, then runs engagement.
    """
    sender = (From or "").replace("whatsapp:", "").strip()
    if not sender:
        log.warning("inbound webhook missing From")
        return _twiml()

    rows = safe_select("patients", match={"phone": sender}, limit=1)
    if not rows:
        log.warning("inbound from unknown number %s", sender)
        return _twiml()
    patient = rows[0]

    # Resolve message text — voice or text
    message_text = (Body or "").strip()
    transcribed = False
    try:
        n_media = int(NumMedia or "0")
    except ValueError:
        n_media = 0
    if n_media > 0 and MediaUrl0 and (MediaContentType0 or "").startswith("audio"):
        log.info("inbound voice note from %s, transcribing via Groq Whisper", sender)
        text = transcribe_twilio_media(MediaUrl0, language=patient.get("language") or "en")
        if text:
            message_text = text
            transcribed = True
        elif not message_text:
            log.warning("transcription failed and no Body fallback for %s", sender)
            return _twiml()

    if not message_text:
        log.warning("inbound empty body / no media from %s", sender)
        return _twiml()

    state = empty_state()
    state["patient_id"] = patient["id"]
    state["current_message"] = message_text
    state["patient_record"] = patient
    state["language"] = patient.get("language") or "en"
    state["channel"] = patient.get("channel_pref") or "whatsapp_text"
    state["triggered_by"] = "inbound_voice" if transcribed else "inbound"
    try:
        run_engagement(state)
    except Exception as e:
        log.error("inbound run_engagement failed: %s", e)
    # Refill keyword path: defer the pharmacy agent so triage stays snappy.
    if _is_refill_request(message_text):
        background_tasks.add_task(trigger_refill_for_patient, patient["id"])
    # Always 200 + empty TwiML so Twilio doesn't retry or echo a fallback.
    return _twiml()
