"""Inbound message webhook + Twilio status callback."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.agents.graph import run_engagement
from app.agents.state import empty_state
from app.db.client import safe_select
from app.tools.transcription import transcribe_twilio_media

router = APIRouter(prefix="/messages", tags=["messages"])
log = logging.getLogger(__name__)


class SimulateRequest(BaseModel):
    patient_id: str
    message: str


# Empty TwiML — tells Twilio "we accepted the message, do NOT auto-reply".
# Our actual reply is sent out-of-band via the WhatsApp REST API inside
# run_engagement().
_EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def _twiml(body: str = _EMPTY_TWIML) -> Response:
    return Response(content=body, media_type="application/xml")


def _process_inbound(patient: dict, message_text: str, transcribed: bool) -> None:
    """Heavy engagement work — runs in BackgroundTasks AFTER we 200 to Twilio."""
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


@router.post("/simulate")
def simulate(req: SimulateRequest, background_tasks: BackgroundTasks):
    rows = safe_select("patients", match={"id": req.patient_id}, limit=1)
    if not rows:
        return {"ok": False, "error": "patient not found", "whatsapp_sent": [], "emails_sent": []}
    patient = rows[0]
    state = empty_state()
    state["patient_id"] = patient["id"]
    state["current_message"] = req.message
    state["patient_record"] = patient
    state["language"] = patient.get("language") or "en"
    state["channel"] = patient.get("channel_pref") or "whatsapp_text"
    state["triggered_by"] = "simulate"
    out = run_engagement(state)
    return {
        "ok": True,
        "classification": out.get("classification"),
        "decision": out.get("decision"),
        "whatsapp_sent": out.get("outgoing_messages", []),
        "emails_sent": out.get("outgoing_emails", []),
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

    Handles BOTH text and voice notes. Returns 200 immediately and runs the
    engagement pipeline in BackgroundTasks so Twilio never sees a 502 from a
    long-running request.
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

    # Defer the slow engagement pipeline so Twilio gets its 200 immediately.
    background_tasks.add_task(_process_inbound, patient, message_text, transcribed)
    return _twiml()


@router.post("/status")
async def twilio_status_callback(
    MessageSid: str = Form(""),
    MessageStatus: str = Form(""),
    ErrorCode: str = Form(""),
    ErrorMessage: str = Form(""),
    To: str = Form(""),
    From: str = Form(""),
):
    """Twilio StatusCallback receiver.

    Separate endpoint from /inbound. Twilio posts delivery status updates
    (queued / sent / delivered / failed / undelivered) here. We just log and
    return 204.

    Configure this URL in Twilio Console as the StatusCallback for your
    WhatsApp sender:
        https://www.careloops.com/api/messages/status
    """
    if ErrorCode:
        log.warning(
            "twilio status: sid=%s status=%s error=%s msg=%s to=%s",
            MessageSid, MessageStatus, ErrorCode, ErrorMessage, To,
        )
    else:
        log.info("twilio status: sid=%s status=%s to=%s", MessageSid, MessageStatus, To)
    return Response(status_code=204)


@router.get("/status")
@router.get("/inbound")
async def twilio_health_get():
    """Allow GET so you can curl these URLs to confirm reachability.
    Twilio always POSTs; this just helps you debug 502 vs 404 vs 405.
    """
    return {"ok": True}
