from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.config import settings

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str, html: Optional[str] = None) -> dict:
    if not settings.has_email:
        log.info("[EMAIL MOCK] to=%s subject=%s body=%s", to, subject, body[:200])
        return {"ok": True, "mock": True, "to": to, "subject": subject}

    payload = {
        "from": settings.email_from,
        "to": [to],
        "subject": subject,
        "text": body,
    }
    if html:
        payload["html"] = html

    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if resp.status_code >= 400:
            log.error("Resend email failed: %s %s", resp.status_code, resp.text)
            return {"ok": False, "reason": resp.text, "mock": False}
        data = resp.json()
        return {"ok": True, "mock": False, "id": data.get("id")}
    except Exception as e:
        log.error("Email send failed: %s", e)
        return {"ok": False, "reason": str(e), "mock": False}

