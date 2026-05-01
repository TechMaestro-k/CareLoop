from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.agents.graph import run_engagement
from app.agents.state import empty_state
from app.db.client import safe_select
from app.tools.transcription import transcribe_twilio_media

router = APIRouter(prefix="/messages", tags=["messages"])
log = logging.getLogger(__name__)


_EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def _twiml(body: str = _EMPTY_TWIML) -> Response:
    return Response(content=body, media_type="application/xml")


class SimulateRequest(BaseModel):
    patient_id: str
    message: str


@router.post("/simulate")
def simulate(req: SimulateRequest):
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
    return {
        "classification": final.get("classification"),
        "decision": final.get("decision"),
        "decision_summary": final.get("decision"),
        "whatsapp_sent": final.get("outgoing_messages", []),
        "emails_sent": final.get("outgoing_emails", []),
        "reasoning_steps": final.get("reasoning_steps", []),
    }


@router.post("/inbound")
async def twilio_inbound(
    request: Request,
    From: str = Form(""),
    Body: str = Form(""),
    To: str = Form(""),
    NumMedia: str = Form("0"),
    MediaUrl0: Optional[str] = Form(None),
    MediaContentType0: Optional[str] = Form(None),
):
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

    return _twiml()
