"""Razorpay webhook handler for payment events.

Two payment kinds in CareLoop:
  - pharmacy_orders : medication refill payment
  - slot_proposals  : telehealth consult fee (gates doctor confirmation)

The webhook matches by `reference_id` first (we always set it when creating
the link), and falls back to amount-matching for legacy orders.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.api.booking import _mark_paid as mark_slot_paid
from app.db.client import safe_select, safe_update
from app.tools.razorpay_tool import parse_payment_event, verify_webhook_signature
from app.tools.whatsapp import send_whatsapp

router = APIRouter(prefix="/razorpay", tags=["razorpay"])
log = logging.getLogger(__name__)


@router.post("/webhook")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None, alias="X-Razorpay-Signature"),
):
    body = await request.body()
    if not verify_webhook_signature(body, x_razorpay_signature or ""):
        raise HTTPException(status_code=401, detail="invalid signature")
    try:
        event = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid json")

    info = parse_payment_event(event)
    if not info:
        return {"ok": True, "ignored": True}

    ref = (info.get("reference_id") or "").strip()
    payment_id = info.get("payment_id") or "pay_webhook"

    # 1. Slot consult fee — reference_id starts with "slot_<proposal_id>"
    if ref.startswith("slot_"):
        proposal_id = ref[len("slot_"):]
        rows = safe_select("slot_proposals", match={"id": proposal_id}, limit=1)
        if rows:
            res = mark_slot_paid(rows[0], payment_id=payment_id)
            return {"ok": True, "matched": "slot", "proposal_id": proposal_id, **res}

    # 2. Pharmacy refill — best-effort amount match (legacy)
    pending = safe_select("pharmacy_orders", match={"payment_status": "pending"}, limit=50)
    matched = None
    for o in pending:
        if abs(float(o.get("total") or 0) - float(info.get("amount") or 0)) < 0.5:
            matched = o
            break
    if matched:
        safe_update(
            "pharmacy_orders",
            match={"id": matched["id"]},
            values={"payment_status": "paid", "razorpay_payment_id": payment_id},
        )
        prows = safe_select("patients", match={"id": matched["patient_id"]}, limit=1)
        if prows and prows[0].get("phone"):
            send_whatsapp(
                prows[0]["phone"],
                f"🩺 CareLoop\nPayment received — thank you. Your medication will arrive in {matched.get('eta_hours', 24)} hours.",
            )
        return {"ok": True, "matched": "pharmacy", "order_id": matched["id"]}

    return {"ok": True, "matched": None}


@router.post("/simulate-payment/{order_id}")
def simulate_payment(order_id: str):
    """Local helper to mark a pharmacy order as paid without going through Razorpay."""
    rows = safe_select("pharmacy_orders", match={"id": order_id}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="order not found")
    safe_update(
        "pharmacy_orders",
        match={"id": order_id},
        values={"payment_status": "paid", "razorpay_payment_id": "pay_simulated"},
    )
    o = rows[0]
    prows = safe_select("patients", match={"id": o["patient_id"]}, limit=1)
    if prows and prows[0].get("phone"):
        send_whatsapp(
            prows[0]["phone"],
            f"🩺 CareLoop\nPayment received — thank you. Your medication will arrive in {o.get('eta_hours', 24)} hours.",
        )
    return {"ok": True, "order_id": order_id, "status": "paid"}
