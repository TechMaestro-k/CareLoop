from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Optional

from app.config import settings

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str, html: Optional[str] = None) -> dict:

    if not settings.has_email:
        log.info("[EMAIL MOCK] to=%s subject=%s body=%s", to, subject, body[:200])
        return {"ok": True, "mock": True, "to": to, "subject": subject}

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f'"CareLoop Care Team" <{settings.gmail_user}>'
    msg["To"] = to
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
            smtp.login(settings.gmail_user, settings.gmail_app_password.replace(" ", ""))
            smtp.send_message(msg)
        return {"ok": True, "mock": False}
    except Exception as e:
        log.error("Email send failed: %s", e)
        return {"ok": False, "reason": str(e), "mock": False}
