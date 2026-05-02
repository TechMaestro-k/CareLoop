"""Pharmacy refill agent."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.db.client import safe_insert, safe_select
from app.prompts.registry import render
from app.tools.llm import chat_json, chat_text
from app.tools.razorpay_tool import create_payment_link
from app.tools.whatsapp import format_whatsapp_message, send_whatsapp
from app.tools.email_tool import send_email

REFILL_TRIGGER_THRESHOLD_DAYS = 2
REFILL_COOLDOWN_DAYS = 7


def chat_text_safe(prompt: str) -> str:
    return chat_text("pharmacy_order", reason=prompt)


def effective_days_remaining(med: dict[str, Any]) -> int:
    days = int(med.get("days_remaining") or med.get("count_remaining") or 0)
    last = med.get("last_refill_date")
    if not last:
        return days
    try:
        last_day = date.fromisoformat(str(last)[:10])
    except ValueError:
        return days
    elapsed = (date.today() - last_day).days
    return max(0, days - max(0, elapsed))


def has_recent_refill(patient_id: str) -> bool:
    rows = safe_select(
        "pharmacy_orders",
        match={"patient_id": patient_id},
        order=("created_at", True),
        limit=1,
    ) or []
    if not rows:
        return False
    created_at = rows[0].get("created_at")
    if not created_at:
        return True
    try:
        created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    return created >= datetime.now(timezone.utc) - timedelta(days=REFILL_COOLDOWN_DAYS)


def _patient_record(patient_id: str) -> dict[str, Any]:
    rows = safe_select("patients", match={"id": patient_id}, limit=1) or []
    return rows[0] if rows else {}


def _sdoh(patient_id: str) -> dict[str, Any]:
    rows = safe_select("sdoh_profiles", match={"patient_id": patient_id}, limit=1) or []
    return rows[0] if rows else {}


def _persist_reasoning(state: dict[str, Any], step: dict[str, Any]) -> None:
    state.setdefault("reasoning_steps", []).append(step)


def _record_reasoning(state: dict[str, Any], step: dict[str, Any]) -> None:
    before = len(state.get("reasoning_steps", []))
    _persist_reasoning(state, step)
    if len(state.get("reasoning_steps", [])) == before:
        state.setdefault("reasoning_steps", []).append(step)


def _choose_pharmacy(pharmacies: list[dict[str, Any]], sdoh: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if not pharmacies:
        return {}, "no pharmacy available"
    prompt = (
        "Pick the best pharmacy id from this list for a patient. "
        f"SDOH={sdoh}. Pharmacies={pharmacies}. Return id|reason."
    )
    try:
        raw = chat_text_safe(prompt)
        picked_id, reason = [p.strip() for p in raw.split("|", 1)]
        for ph in pharmacies:
            if str(ph.get("id")) == picked_id:
                return ph, reason
    except Exception:
        pass
    return pharmacies[0], "default nearest available pharmacy"


def pharmacy_node(state: dict[str, Any]) -> dict[str, Any]:
    patient_id = state["patient_id"]
    if has_recent_refill(patient_id):
        _record_reasoning(state, {
            "agent": "pharmacy",
            "observed": {"recent_refill": True},
            "inferred": {"cooldown": True},
            "decided": "Skip refill because a recent order exists.",
            "tools_called": ["safe_select"],
        })
        return state

    patient = _patient_record(patient_id)
    sdoh = _sdoh(patient_id)
    inventory = safe_select("medications_inventory", match={"patient_id": patient_id}, limit=50) or []
    low_meds = [m for m in inventory if effective_days_remaining(m) <= REFILL_TRIGGER_THRESHOLD_DAYS]
    if not low_meds:
        _record_reasoning(state, {
            "agent": "pharmacy",
            "observed": {"low_meds": []},
            "inferred": {"needs_refill": False},
            "decided": "No refill needed.",
            "tools_called": ["safe_select"],
        })
        return state

    pharmacies = safe_select("pharmacies", limit=20) or []
    pharmacy, reason = _choose_pharmacy(pharmacies, sdoh)
    med = low_meds[0]
    amount = round(250.0 * float(pharmacy.get("price_modifier") or 1.0), 2)
    pay = create_payment_link(
        amount_rupees=amount,
        description=f"CareLoop refill - {med.get('med_name') or med.get('name') or 'medicine'}",
        customer_name=patient.get("name", "Patient"),
        customer_phone=patient.get("phone", ""),
        customer_email=patient.get("email", ""),
        reference_id=f"pharmacy_{patient_id}_{int(datetime.now(timezone.utc).timestamp())}",
    )
    body_data = chat_json(
        "pharmacy_order",
        patient_name=patient.get("name", "Patient"),
        medicine_name=med.get("med_name") or med.get("name") or "medicine",
        pharmacy_name=pharmacy.get("name", "your pharmacy"),
        reason=reason,
    )
    body = str(body_data.get("caregiver_note") or body_data.get("body") or "Your medicine refill is ready.")
    body = render(body, PAY_LINK="Pay now")
    email_body = body
    body = format_whatsapp_message(
        title="Medicine refill ready",
        body=body,
        cta_label="Pay now",
        cta_url=pay.get("link") or None,
    )

    route_to_caregiver = sdoh.get("digital_comfort") == "low" and patient.get("caregiver_phone")
    recipient_phone = patient.get("caregiver_phone") if route_to_caregiver else patient.get("phone")
    if recipient_phone:
        send_whatsapp(recipient_phone, body)
    if route_to_caregiver and patient.get("caregiver_email"):
        pay_link = pay.get("link") or ""
        html = (
            '<div style="font-family:Arial,sans-serif;color:#0f172a;line-height:1.6;">'
            "<h2 style=\"margin:0 0 12px;\">CareLoop medicine refill ready</h2>"
            f"<p>{email_body}</p>"
            f'<p><a href="{pay_link}" style="display:inline-block;background:#2563eb;color:#fff;'
            'padding:11px 18px;border-radius:8px;text-decoration:none;font-weight:700;">Pay now</a></p>'
            "</div>"
        )
        send_email(
            patient["caregiver_email"],
            "[CareLoop] Medicine refill ready",
            f"{email_body}\n\nUse the Pay now button in this email.",
            html=html,
        )

    safe_insert("pharmacy_orders", {
        "patient_id": patient_id,
        "medicine": med.get("med_name") or med.get("name"),
        "pharmacy_id": pharmacy.get("id"),
        "payment_link": pay.get("link"),
        "status": "pending",
    })
    _record_reasoning(state, {
        "agent": "pharmacy",
        "observed": {"low_meds": low_meds, "sdoh": sdoh},
        "inferred": {"recipient": "caregiver" if route_to_caregiver else "patient", "pharmacy": pharmacy},
        "decided": "Create refill order and send payment link.",
        "tools_called": ["safe_select", "create_payment_link", "send_whatsapp"],
    })
    return state
