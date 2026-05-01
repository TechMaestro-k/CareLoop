from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.api.booking import _mark_paid as mark_slot_paid
from app.db.client import safe_select
from app.tools.razorpay_tool import parse_payment_event, verify_webhook_signature

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

    # Slot consult fee — reference_id starts with "slot_<proposal_id>"
    if ref.startswith("slot_"):
        proposal_id = ref[len("slot_"):]
        rows = safe_select("slot_proposals", match={"id": proposal_id}, limit=1)
        if rows:
            res = mark_slot_paid(rows[0], payment_id=payment_id)
            return {"ok": True, "matched": "slot", "proposal_id": proposal_id, **res}

    return {"ok": True, "matched": None}
