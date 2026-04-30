"""Slot-booking flow with payment gating.

Booking lifecycle (English-only; per-consult fee is settings.consult_fee
in settings.consult_currency, defaulting to USD $100):

  agent (RED)        →  POST  proposal              creates row, gives patient a picker URL
  patient (clicks)   →  GET   /booking/{id}         sees open slots
  patient (picks)    →  POST  /booking/{id}/select  → CREATES Razorpay payment link
                                                       sends patient WhatsApp with link
                                                       (doctor is NOT notified yet)
  patient (pays)     →  Razorpay webhook OR
                         POST /booking/{id}/simulate-payment
                                                       → marks paid, notifies doctor
  doctor (decides)   →  POST  /booking/{id}/decision → on accept, finalises Jitsi+calendar

The payment fields live inside `chosen_slot.payment` so we don't require a
schema migration. Shape:

  chosen_slot = {
      iso, human, duration_min,
      payment: {
          status: "pending" | "paid" | "failed" | "refunded",
          amount_usd, currency, link, link_id, reference_id, payment_id?
      }
  }
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.db.client import safe_insert, safe_select, safe_update
from app.tools.calendar_tool import confirm_booking
from app.tools.email_tool import send_email
from app.tools.handoff_summary import build_doctor_handoff_summary
from app.tools.razorpay_tool import create_payment_link
from app.tools.whatsapp import send_whatsapp

router = APIRouter(prefix="/booking", tags=["booking"])
log = logging.getLogger(__name__)

# Backwards-compatible aliases. New code should read settings.consult_fee /
# settings.consult_currency directly so prices can be overridden per-deploy.
CONSULT_FEE_USD = settings.consult_fee
CONSULT_CURRENCY = settings.consult_currency


# ---------------- Public-base resolution ----------------

def _public_base() -> str:
    """Resolve the public HTTPS base URL the patient/doctor will see in links.

    Order:
      1. CARELOOP_PUBLIC_BASE        (explicit override)
      2. REPLIT_DEPLOYMENT_DOMAIN    (production deploy)
      3. REPLIT_DOMAINS              (dev / preview, comma-separated)
      4. REPLIT_DEV_DOMAIN           (legacy)
    """
    base = os.environ.get("CARELOOP_PUBLIC_BASE", "").strip()
    if base:
        return base.rstrip("/")
    for var in ("REPLIT_DEPLOYMENT_DOMAIN", "REPLIT_DOMAINS", "REPLIT_DEV_DOMAIN"):
        v = (os.environ.get(var) or "").strip()
        if v:
            v = v.split(",")[0].strip()
            return f"https://{v}"
    return ""


def _picker_url(proposal_id: str) -> str:
    base = _public_base()
    return f"{base}/booking/{proposal_id}" if base else f"/booking/{proposal_id}"


# ---------------- Schemas ----------------
class SelectSlotRequest(BaseModel):
    slot_iso: str  # must match one of the proposed_slots[].iso


class DecisionRequest(BaseModel):
    action: str  # accept | reject | reschedule
    note: Optional[str] = None


# ---------------- Helpers ----------------

def _patient_msg(body: str) -> str:
    return f"🩺 CareLoop\n{body.strip()}"


def _patient_phone_email(p: dict) -> tuple[str, str]:
    return p.get("phone", "") or "", p.get("email", "") or ""


def _ensure_handoff_summary(p: dict) -> dict:
    """Return the doctor handoff summary for this proposal.

    Persistence strategy:
      • Preferred: a top-level `doctor_handoff_summary` jsonb column on
        slot_proposals (added by reset_and_init.sql).
      • Fallback: nested under `chosen_slot.handoff_summary` so that when the
        column does not exist (older Supabase schemas), we still cache the
        summary inside an existing jsonb field instead of recomputing on
        every page view.

    If neither persistence path works the summary is computed in-memory and
    returned without caching. Never raises.

    Mutates `p` in-place so callers can use the value.
    """
    # 1. Already on the row? (top-level column)
    existing = p.get("doctor_handoff_summary")
    if isinstance(existing, dict) and existing:
        return existing
    # 2. Already nested in chosen_slot? (fallback location)
    chosen = p.get("chosen_slot") if isinstance(p.get("chosen_slot"), dict) else None
    if chosen:
        nested = chosen.get("handoff_summary")
        if isinstance(nested, dict) and nested:
            p["doctor_handoff_summary"] = nested
            return nested

    # 3. Build a fresh one.
    try:
        summary = build_doctor_handoff_summary(p["patient_id"], proposal_id=p.get("id"))
    except Exception as e:  # pragma: no cover - defensive
        log.error("handoff summary build failed for %s: %s", p.get("id"), e)
        summary = {
            "summary": "AI handoff summary unavailable.",
            "symptoms_reported": [],
            "medication_adherence": "unknown",
            "risk_signals": [],
            "sdoh_context": [],
            "agent_actions_so_far": [],
            "doctor_focus": ["review patient record manually"],
        }

    # 4. Try the top-level column first; if Supabase rejects it (PGRST204
    # column-missing), nest inside chosen_slot which is guaranteed to exist.
    persisted = False
    try:
        res = safe_update(
            "slot_proposals",
            match={"id": p["id"]},
            values={"doctor_handoff_summary": summary},
        )
        # safe_update returns None on failure (logged inside the helper),
        # [] when zero rows matched, list of rows on success.
        persisted = res is not None and len(res) > 0
    except Exception as e:  # pragma: no cover - defensive
        log.warning("persisting handoff summary (top-level) failed for %s: %s", p.get("id"), e)

    if not persisted and chosen is not None:
        new_chosen = {**chosen, "handoff_summary": summary}
        try:
            safe_update(
                "slot_proposals",
                match={"id": p["id"]},
                values={"chosen_slot": new_chosen},
            )
            p["chosen_slot"] = new_chosen
        except Exception as e:  # pragma: no cover - defensive
            log.warning("persisting handoff summary (chosen_slot fallback) failed for %s: %s", p.get("id"), e)

    p["doctor_handoff_summary"] = summary
    return summary


def _fmt_ts(ts: str) -> str:
    """Render an ISO timestamp in a doctor-friendly form (UTC)."""
    if not ts:
        return "unknown time"
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%a %d %b %Y, %H:%M UTC")
    except Exception:
        return str(ts)


def _last_inbound(interactions: list[dict] | None) -> dict:
    for r in interactions or []:
        if (r.get("direction") or "").startswith("inbound"):
            return r
    return {}


def _format_handoff_for_email(
    summary: dict,
    *,
    patient: dict | None = None,
    clinical: dict | None = None,
    interactions: list[dict] | None = None,
    escalations: list[dict] | None = None,
    chosen: dict | None = None,
) -> str:
    """Render a tight, doctor-focused plain-text block for the email.

    Sections (in order):
      1. When the problem came up        — timestamp of latest patient message / escalation
      2. What the patient is reporting   — LLM summary + symptoms + verbatim last message
      3. Patient background              — diagnosis, comorbidities, prior escalations
      4. Suggested focus for this call   — from the AI summary (kept short)

    Deliberately drops SDOH and CareLoop-agent action logs from the email —
    those still live in the on-screen handoff card for whoever wants them.
    """
    summary = summary if isinstance(summary, dict) else {}
    patient = patient or {}
    clinical = clinical or {}
    escalations = escalations or []
    chosen = chosen or {}

    last_in = _last_inbound(interactions)
    problem_ts = (
        last_in.get("timestamp")
        or (escalations[0].get("created_at") if escalations else None)
        or chosen.get("iso")
    )
    last_msg = (last_in.get("content") or "").strip()

    symptoms = summary.get("symptoms_reported") or []
    focus = summary.get("doctor_focus") or []

    diagnosis = clinical.get("diagnosis") or "unknown"
    comorbidities = clinical.get("comorbidities") or []
    if isinstance(comorbidities, str):
        comorbidities = [comorbidities]

    pat_name = patient.get("name") or "Patient"
    age = patient.get("age")
    header = f"{pat_name}" + (f", {age}y" if age else "")

    def _bullets(items, empty="(none)"):
        items = [str(x).strip() for x in (items or []) if str(x).strip()]
        if not items:
            return f"  {empty}"
        return "\n".join(f"  • {x}" for x in items)

    parts = [
        f"Patient: {header}",
        "",
        "WHEN THIS CAME UP",
        f"  {_fmt_ts(problem_ts)}",
        "",
        "WHAT THE PATIENT IS REPORTING",
        f"  {summary.get('summary') or '(no AI summary available)'}",
    ]
    if symptoms:
        parts += ["", "  Symptoms mentioned:", _bullets(symptoms)]
    if last_msg:
        snip = last_msg if len(last_msg) <= 400 else last_msg[:400] + "…"
        parts += ["", "  Patient's own words (latest message):", f'  "{snip}"']

    parts += [
        "",
        "PATIENT BACKGROUND",
        f"  Primary diagnosis: {diagnosis}",
        f"  Comorbidities: {', '.join(comorbidities) if comorbidities else 'none on file'}",
    ]
    if escalations:
        parts += ["", "  Recent escalations (newest first):"]
        for e in escalations[:5]:
            sev = (e.get("severity") or "?").upper()
            when = _fmt_ts(e.get("created_at") or "")
            brief = (e.get("brief") or "").strip().replace("\n", " ")
            if len(brief) > 160:
                brief = brief[:160] + "…"
            parts.append(f"  • [{sev}] {when} — {brief or '(no brief)'}")

    if focus:
        parts += ["", "SUGGESTED FOCUS FOR THIS CALL", _bullets(focus)]

    return "\n".join(parts)


# ---------------- Endpoints ----------------
@router.get("/{proposal_id}")
def get_proposal(proposal_id: str):
    rows = safe_select("slot_proposals", match={"id": proposal_id}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="proposal not found")
    p = rows[0]
    pat = safe_select("patients", match={"id": p["patient_id"]}, limit=1)
    summary = _ensure_handoff_summary(p)
    return {
        "proposal": p,
        "patient": pat[0] if pat else None,
        "doctor_handoff_summary": summary,
    }


@router.post("/{proposal_id}/select")
def patient_select(proposal_id: str, req: SelectSlotRequest):
    """Patient picks a slot → we create a Razorpay payment link and DM it.

    Doctor is intentionally NOT notified here. Doctor only sees the booking
    once payment lands.
    """
    rows = safe_select("slot_proposals", match={"id": proposal_id}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="proposal not found")
    p = rows[0]
    if p.get("patient_status") == "chosen" and (p.get("chosen_slot") or {}).get("payment", {}).get("status") == "paid":
        raise HTTPException(status_code=409, detail="slot already paid")

    slots = p.get("proposed_slots") or []
    chosen = next((s for s in slots if s.get("iso") == req.slot_iso), None)
    if not chosen:
        raise HTTPException(status_code=400, detail="slot_iso does not match a proposed slot")

    pat = safe_select("patients", match={"id": p["patient_id"]}, limit=1)
    pat_row = pat[0] if pat else {}
    pat_name = pat_row.get("name", "Patient")
    pat_phone, pat_email = _patient_phone_email(pat_row)

    # Create payment link for the consult fee
    pay = create_payment_link(
        amount_rupees=CONSULT_FEE_USD,           # major-unit value (USD)
        description=f"CareLoop telehealth consult — {pat_name} @ {chosen['human']}",
        customer_name=pat_name,
        customer_phone=pat_phone,
        customer_email=pat_email,
        notify=False,
        currency=CONSULT_CURRENCY,
        reference_id=f"slot_{proposal_id}",
    )

    chosen_with_pay = {
        **chosen,
        "payment": {
            "status": "pending" if pay.get("ok") else "failed",
            "amount_usd": CONSULT_FEE_USD,
            "currency": CONSULT_CURRENCY,
            "link": pay.get("link"),
            "link_id": pay.get("link_id"),
            "reference_id": pay.get("reference_id"),
            "mock": pay.get("mock", False),
        },
    }

    safe_update(
        "slot_proposals",
        match={"id": proposal_id},
        values={
            "chosen_slot": chosen_with_pay,
            "patient_status": "chosen",
            "patient_chose_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    # WhatsApp the patient with the payment link
    if pat_phone and pay.get("link"):
        msg = _patient_msg(
            f"You picked {chosen['human']}.\n\n"
            f"To confirm with the doctor, please pay the ${int(CONSULT_FEE_USD)} consult fee:\n"
            f"{pay['link']}\n\n"
            f"As soon as payment is received, the doctor will confirm and we'll send the video link."
        )
        send_whatsapp(pat_phone, msg)

    return {
        "ok": True,
        "chosen_slot": chosen_with_pay,
        "payment": chosen_with_pay["payment"],
    }


@router.post("/{proposal_id}/simulate-payment")
def simulate_payment(proposal_id: str):
    """Mark this booking as paid without going through Razorpay.

    Used by the demo UI's 'Pay (test mode)' button and by smoke tests.
    """
    rows = safe_select("slot_proposals", match={"id": proposal_id}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="proposal not found")
    p = rows[0]
    if not p.get("chosen_slot"):
        raise HTTPException(status_code=400, detail="no slot chosen yet")
    return _mark_paid(p, payment_id="pay_simulated")


def _mark_paid(p: dict, payment_id: str) -> dict:
    chosen = dict(p.get("chosen_slot") or {})
    payment = dict(chosen.get("payment") or {})
    if payment.get("status") == "paid":
        return {"ok": True, "already_paid": True, "proposal_id": p["id"]}
    payment["status"] = "paid"
    payment["payment_id"] = payment_id
    payment["paid_at"] = datetime.now(timezone.utc).isoformat()
    chosen["payment"] = payment

    safe_update(
        "slot_proposals",
        match={"id": p["id"]},
        values={"chosen_slot": chosen},
    )
    # Mirror the just-persisted chosen_slot back onto the in-memory row so
    # _ensure_handoff_summary's chosen_slot fallback path doesn't overwrite
    # our freshly-written payment dict.
    p["chosen_slot"] = chosen

    # Notify doctor + caregiver + patient that payment is received
    pat = safe_select("patients", match={"id": p["patient_id"]}, limit=1)
    pat_row = pat[0] if pat else {}
    pat_name = pat_row.get("name", "Patient")
    pat_phone, _ = _patient_phone_email(pat_row)
    accept_url = f"{_public_base()}/doctor/calendar"

    # Ensure the AI handoff summary exists before pinging the doctor — this
    # is what they'll see/receive when they open the calendar to accept.
    summary = _ensure_handoff_summary(p)

    # Pull the extra context the email body needs (diagnosis, comorbidities,
    # last patient message + timestamp, recent escalations).
    clinical_rows = safe_select("clinical_data", match={"patient_id": p["patient_id"]}, limit=1)
    clinical_row = clinical_rows[0] if clinical_rows else {}
    interactions = safe_select(
        "interactions", match={"patient_id": p["patient_id"]},
        order=("timestamp", True), limit=20,
    ) or []
    escalations = safe_select(
        "escalations", match={"patient_id": p["patient_id"]},
        order=("created_at", True), limit=5,
    ) or []

    body_text = (
        f"CareLoop: {pat_name} has paid for and chosen a telehealth slot.\n"
        f"Time: {chosen.get('human','?')}\n"
        f"Open the doctor inbox to accept or reschedule:\n{accept_url}\n\n"
        f"{_format_handoff_for_email(summary, patient=pat_row, clinical=clinical_row, interactions=interactions, escalations=escalations, chosen=chosen)}"
    )
    if settings.doctor_email:
        send_email(
            settings.doctor_email,
            f"[CareLoop] Paid booking by {pat_name} — {chosen.get('human','?')}",
            body_text,
        )
    if settings.doctor_phone:
        send_whatsapp(
            settings.doctor_phone,
            f"🩺 CareLoop\n"
            f"{pat_name} paid for a telehealth slot at {chosen.get('human','?')}.\n"
            f"AI handoff summary is ready in the doctor calendar:\n{accept_url}",
        )

    if pat_phone:
        send_whatsapp(
            pat_phone,
            _patient_msg(
                "Payment received — thank you. The doctor will confirm shortly and we'll send your video link."
            ),
        )

    return {"ok": True, "proposal_id": p["id"], "status": "paid"}


@router.post("/{proposal_id}/decision")
def doctor_decision(proposal_id: str, req: DecisionRequest):
    if req.action not in {"accept", "reject", "reschedule"}:
        raise HTTPException(status_code=400, detail="invalid action")

    rows = safe_select("slot_proposals", match={"id": proposal_id}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="proposal not found")
    p = rows[0]
    chosen = p.get("chosen_slot") or {}
    if not chosen:
        raise HTTPException(status_code=400, detail="patient has not chosen a slot yet")
    payment = chosen.get("payment") or {}

    pat = safe_select("patients", match={"id": p["patient_id"]}, limit=1)
    pat_row = pat[0] if pat else {}
    pat_name = pat_row.get("name", "Patient")
    pat_phone = pat_row.get("phone", "")
    caregiver_email = pat_row.get("caregiver_email") or settings.caregiver_email_default
    caregiver_phone = pat_row.get("caregiver_phone") or ""

    if req.action == "accept":
        if payment.get("status") != "paid":
            raise HTTPException(
                status_code=402,
                detail="cannot accept — patient has not paid the consult fee yet",
            )
        # Make sure the doctor confirmation email includes the AI handoff summary.
        summary = _ensure_handoff_summary(p)
        booking = confirm_booking(
            patient_id=p["patient_id"],
            chosen_slot=chosen,
            doctor_email=settings.doctor_email,
            patient_name=pat_name,
            headline="Telehealth follow-up",
            caregiver_email=caregiver_email,
        )
        safe_update(
            "slot_proposals",
            match={"id": proposal_id},
            values={
                "doctor_status": "accepted",
                "doctor_note": req.note or "",
                "doctor_decided_at": datetime.now(timezone.utc).isoformat(),
                "jitsi_link": booking["link"],
                "calendar_link": booking["calendar_link"],
            },
        )
        if pat_phone:
            send_whatsapp(
                pat_phone,
                _patient_msg(
                    f"Doctor confirmed your telehealth at {booking['slot_human']}.\n"
                    f"Join from any browser: {booking['link']}"
                ),
            )
        if caregiver_phone:
            send_whatsapp(
                caregiver_phone,
                _patient_msg(
                    f"{pat_name}'s telehealth confirmed for {booking['slot_human']}.\nJoin: {booking['link']}"
                ),
            )
        if caregiver_email:
            send_email(
                caregiver_email,
                f"[CareLoop] {pat_name} — telehealth confirmed {booking['slot_human']}",
                f"Doctor accepted {pat_name}'s slot.\n\n"
                f"When: {booking['slot_human']}\n"
                f"Join: {booking['link']}\n"
                f"Add to calendar: {booking['calendar_link']}",
            )
        if settings.doctor_email:
            clinical_rows = safe_select("clinical_data", match={"patient_id": p["patient_id"]}, limit=1)
            clinical_row = clinical_rows[0] if clinical_rows else {}
            interactions = safe_select(
                "interactions", match={"patient_id": p["patient_id"]},
                order=("timestamp", True), limit=20,
            ) or []
            escalations = safe_select(
                "escalations", match={"patient_id": p["patient_id"]},
                order=("created_at", True), limit=5,
            ) or []
            send_email(
                settings.doctor_email,
                f"[CareLoop] Confirmed: {pat_name} @ {booking['slot_human']}",
                (
                    f"You accepted this slot.\n\n"
                    f"Join: {booking['link']}\n"
                    f"Add to calendar: {booking['calendar_link']}\n\n"
                    f"{_format_handoff_for_email(summary, patient=pat_row, clinical=clinical_row, interactions=interactions, escalations=escalations, chosen=chosen)}"
                ),
            )
        return {
            "ok": True,
            "status": "accepted",
            "booking": booking,
            "doctor_handoff_summary": summary,
        }

    # reject / reschedule
    new_status = "rejected" if req.action == "reject" else "rescheduled"
    safe_update(
        "slot_proposals",
        match={"id": proposal_id},
        values={
            "doctor_status": new_status,
            "doctor_note": req.note or "",
            "doctor_decided_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if pat_phone:
        send_whatsapp(
            pat_phone,
            _patient_msg(
                f"Doctor cannot make {chosen.get('human','this time')}. "
                "We'll share new times shortly. Reply URGENT if you need help now."
            ),
        )
    return {"ok": True, "status": new_status}


@router.get("")
def list_proposals(
    patient_status: Optional[str] = None,
    doctor_status: Optional[str] = None,
    limit: int = 50,
):
    """For the doctor calendar / inbox views."""
    match: dict = {}
    if patient_status:
        match["patient_status"] = patient_status
    if doctor_status:
        match["doctor_status"] = doctor_status
    rows = safe_select(
        "slot_proposals",
        match=match or None,
        order=("created_at", True),
        limit=limit,
    )
    out = []
    for r in rows:
        pat = safe_select("patients", match={"id": r["patient_id"]}, limit=1)
        out.append({**r, "patient": pat[0] if pat else None})
    return {"proposals": out}


def create_proposal_from_agent(
    *,
    patient_id: str,
    escalation_id: Optional[str],
    urgency: str,
    proposed_slots: list[dict],
) -> Optional[dict]:
    """Helper used by the engagement agent to create a proposal row."""
    row = safe_insert(
        "slot_proposals",
        {
            "patient_id": patient_id,
            "escalation_id": escalation_id,
            "urgency": urgency,
            "proposed_slots": proposed_slots,
            "patient_status": "pending",
            "doctor_status": "pending",
        },
    )
    if not row:
        return None
    return {"proposal": row, "picker_url": _picker_url(row["id"])}
