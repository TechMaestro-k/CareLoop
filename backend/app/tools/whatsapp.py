from __future__ import annotations

import logging
from typing import Optional

from app.config import settings

log = logging.getLogger(__name__)

_client = None


def _twilio_client():
    global _client
    if _client is not None:
        return _client
    if not settings.has_twilio:
        return None
    try:
        from twilio.rest import Client

        _client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        return _client
    except Exception as e:
        log.error("Twilio init failed: %s", e)
        return None


def _normalize(to: str) -> str:
    if not to:
        return to
    if to.startswith("whatsapp:"):
        return to
    return f"whatsapp:{to}"


def send_whatsapp(to: str, body: str, media_url: Optional[str] = None) -> dict:
    client = _twilio_client()
    if client is None:
        log.info("[WHATSAPP MOCK] to=%s body=%s media=%s", to, body, media_url)
        return {"ok": True, "sid": "MOCK_SID", "mock": True, "to": to, "body": body}

    try:
        kwargs = {
            "from_": settings.twilio_whatsapp_from,
            "to": _normalize(to),
            "body": body,
        }
        if media_url:
            kwargs["media_url"] = [media_url]
        msg = client.messages.create(**kwargs)
        return {"ok": True, "sid": msg.sid, "mock": False}
    except Exception as e:
        log.error("Twilio send failed: %s", e)
        return {"ok": False, "reason": str(e), "mock": False}
