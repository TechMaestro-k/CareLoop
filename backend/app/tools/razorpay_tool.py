from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from typing import Optional

from app.config import settings

log = logging.getLogger(__name__)

_client = None


def _client_singleton():
    global _client
    if _client is not None:
        return _client
    if not settings.has_razorpay:
        return None
    try:
        import razorpay

        _client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
        return _client
    except Exception as e:
        log.error("Razorpay init failed: %s", e)
        return None


def create_payment_link(
    amount_rupees: float,
    description: str,
    customer_name: str = "",
    customer_phone: str = "",
    customer_email: str = "",
    notify: bool = False,
    currency: str = "INR",
    reference_id: str | None = None,
) -> dict:
    client = _client_singleton()
    ref = reference_id or f"careloop_{uuid.uuid4().hex[:12]}_{int(time.time())}"
    if client is None:
        fake_id = f"plink_mock_{uuid.uuid4().hex[:10]}"
        link = f"https://rzp.io/i/MOCK{fake_id[-8:].upper()}"
        log.info(
            "[RAZORPAY MOCK] amount=%.2f %s desc=%s link=%s",
            amount_rupees, currency, description, link,
        )
        return {
            "ok": True, "link": link, "link_id": fake_id,
            "reference_id": ref, "mock": True,
        }

    try:
        amount_minor = int(round(amount_rupees * 100))
        payload = {
            "amount": amount_minor,
            "currency": currency,
            "accept_partial": False,
            "description": description[:200],
            "customer": {
                "name": customer_name or "Patient",
                "contact": customer_phone or "",
                "email": customer_email or "",
            },
            "notify": {"sms": notify, "email": notify},
            "reminder_enable": True,
            "reference_id": ref,
        }
        resp = client.payment_link.create(payload)
        return {
            "ok": True,
            "link": resp.get("short_url"),
            "link_id": resp.get("id"),
            "reference_id": ref,
            "mock": False,
        }
    except Exception as e:
        log.error("Razorpay create_payment_link failed: %s", e)
        return {"ok": False, "reason": str(e), "mock": False, "reference_id": ref}


def verify_webhook_signature(payload_body: bytes, signature_header: str) -> bool:
    secret = settings.razorpay_webhook_secret
    if not secret:
        log.warning("RAZORPAY_WEBHOOK_SECRET not set — accepting webhook in dev (DO NOT do this in prod).")
        return True
    expected = hmac.new(secret.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (signature_header or "").strip())


def parse_payment_event(event: dict) -> Optional[dict]:
    try:
        ev_type = event.get("event", "")
        payload = event.get("payload", {})
        plink = payload.get("payment_link", {}).get("entity", {})
        payment = payload.get("payment", {}).get("entity", {})
        return {
            "event": ev_type,
            "link_id": plink.get("id"),
            "reference_id": plink.get("reference_id"),
            "payment_id": payment.get("id"),
            "amount": (payment.get("amount") or 0) / 100.0,
            "status": payment.get("status") or plink.get("status"),
        }
    except Exception as e:
        log.error("parse_payment_event failed: %s", e)
        return None
