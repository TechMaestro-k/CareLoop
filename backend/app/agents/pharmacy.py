"""Agent 4: Pharmacy & Refill — autonomous pharmacy selection + Razorpay link."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.agents.state import PatientState
from app.config import settings
from app.db.client import safe_insert, safe_select
from app.tools.email_tool import send_email
from app.tools.llm import chat_json, chat_text
from app.tools.razorpay_tool import create_payment_link
from app.tools.whatsapp import send_whatsapp

log = logging.getLogger(__name__)

REFILL_COOLDOWN_DAYS = 7
INITIAL_SUPPLY_DAYS = 10
REFILL_TRIGGER_THRESHOLD_DAYS = 2


def _days_since(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        raw = str(date_str)
        if len(raw) == 10:
            return max(0, (date.today() - date.fromisoformat(raw)).days)
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - d).days)
    except Exception:
        return None


def effective_days_remaining(med: dict) -> int:
    """Compute remaining days from days_remaining + last_refill_date.

    days_remaining is treated as the supply at last_refill_date; we subtract
    elapsed days so the engagement agent doesn't keep re-triggering refills."""
    raw = med.get("days_remaining")
    if raw is None:
        return INITIAL_SUPPLY_DAYS
    elapsed = _days_since(med.get("last_refill_date")) or 0
    return max(0, int(raw) - int(elapsed))


def has_recent_refill(patient_id: str, within_days: int = REFILL_COOLDOWN_DAYS) -> bool:
    """Return True if a pharmacy_orders row exists for this patient within window."""
    rows = safe_select("pharmacy_orders", match={"patient_id": patient_id}, limit=20)
    if not rows:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    for row in rows:
        created = row.get("created_at")
        if not created:
            continue
        try:
            dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                return True
        except Exception:
            continue
    return False


# Reasonable mocked unit prices in INR for common cardiac meds
DEFAULT_UNIT_PRICES = {
    "metoprolol": 12.0,
    "ramipril": 8.0,
    "furosemide": 6.0,
    "spironolactone": 9.0,
    "atorvastatin": 14.0,
    "aspirin": 3.0,
    "clopidogrel": 18.0,
    "digoxin": 11.0,
    "amiodarone": 22.0,
    "metformin": 5.0,
    "insulin": 180.0,
}


def _persist_reasoning(patient_id, observed, inferred, decided, tools):
    safe_insert(
        "reasoning_traces",
        {
            "patient_id": patient_id,
            "agent_name": "pharmacy",
            "observed": observed,
            "inferred": inferred,
            "decided": decided,
            "tools_called": tools,
        },
    )


def _patient_record(patient_id):
    rows = safe_select("patients", match={"id": patient_id}, limit=1)
    return rows[0] if rows else {}


def _sdoh(patient_id):
    rows = safe_select("sdoh_profiles", match={"patient_id": patient_id}, limit=1)
    return rows[0] if rows else {}


def _unit_price(med_name: str) -> float:
    if not med_name:
        return 10.0
    key = med_name.lower().split()[0]
    return DEFAULT_UNIT_PRICES.get(key, 10.0)


def pharmacy_node(state: PatientState) -> PatientState:
    """Run the pharmacy agent for one patient.

    Two trigger modes (set on `state`):
      • Auto-scan (default): only fires when at least one med is at/under
        REFILL_TRIGGER_THRESHOLD_DAYS, and only once per 7-day cooldown.
      • Explicit request (`state["force_refill"] = True`): bypasses both
        the cooldown and the threshold gate; if no med is "low enough" we
        refill *every* med the patient has on file. Used when the patient
        explicitly asks ("please send my refill") so we never tell a
        patient asking for medicine "you still have supply, no order".
    """
    patient_id = state["patient_id"]
    forced = bool(state.get("force_refill"))
    tools_called: list[str] = []
    patient = state.get("patient_record") or _patient_record(patient_id)
    sdoh = state.get("sdoh_profile") or _sdoh(patient_id)

    # 0. Cooldown guard — skipped on explicit requests.
    if not forced and has_recent_refill(patient_id):
        log.info("pharmacy_node: skip — recent refill exists for %s", patient_id)
        return state

    # 1. Find low-stock meds. On forced runs, fall back to refilling every
    # med on file when none are below the threshold.
    inv = safe_select("medications_inventory", match={"patient_id": patient_id})
    low = [m for m in inv if effective_days_remaining(m) <= REFILL_TRIGGER_THRESHOLD_DAYS]
    if not low and forced and inv:
        log.info("pharmacy_node: forced refill for %s — refilling all %d meds", patient_id, len(inv))
        low = list(inv)
    if not low:
        log.info("pharmacy_node: no low-stock meds for %s (forced=%s)", patient_id, forced)
        return state

    # 2. Pharmacy options
    pharmacies = safe_select("pharmacies")
    if not pharmacies:
        log.warning("No pharmacies seeded — skipping refill")
        return state

    # 3. Autonomous selection — Groq picks the best fit
    selection_prompt = _build_selection_prompt(sdoh, pharmacies)
    selection = chat_text_safe(selection_prompt)
    tools_called.append("llm:pharmacy_selection")

    # Parse the selection (id + reason). If parsing fails, fall back to cheapest * speed-weighted.
    selected_id, selection_reason = _parse_selection(selection, pharmacies, sdoh)
    selected = next((p for p in pharmacies if p.get("id") == selected_id), pharmacies[0])
    tools_called.append("kg:pharmacy_select_fallback" if not selected_id else "llm:parse_selection")

    # 4. Order math
    items = []
    base_total = 0.0
    for m in low:
        unit = _unit_price(m.get("med_name", ""))
        qty = max(int((m.get("count_remaining") or 0) + 30), 30)  # 30-day refill
        line_total = round(unit * qty, 2)
        base_total += line_total
        items.append(
            {
                "med": m.get("med_name"),
                "qty": qty,
                "unit_price_inr": unit,
                "line_total_inr": line_total,
            }
        )
    modifier = float(selected.get("price_modifier") or 1.0)
    total = round(base_total * modifier, 2)

    # 5. Razorpay payment link
    desc = f"CareLoop refill for {patient.get('name', 'patient')}"
    pay = create_payment_link(
        amount_rupees=total,
        description=desc,
        customer_name=patient.get("name", ""),
        customer_phone=patient.get("phone", ""),
        customer_email=patient.get("email", ""),
        notify=False,
    )
    tools_called.append(f"razorpay:create_link({'mock' if pay.get('mock') else 'live'})")
    pay_link = pay.get("link", "")

    # 6. Order summary copy
    summary = (
        chat_json(
            "pharmacy_order",
            patient_name=patient.get("name", "Patient"),
            patient_age=patient.get("age", ""),
            language=sdoh.get("language") or "hi",
            simplification_level="high" if sdoh.get("literacy_level") == "low" else "medium",
            pharmacy_name=selected.get("name"),
            eta_hours=selected.get("eta_hours"),
            items_table="\n".join(f"  - {i['med']} × {i['qty']} = ₹{i['line_total_inr']}" for i in items),
            total=total,
            selection_reason=selection_reason,
        )
        or {}
    )
    tools_called.append("llm:pharmacy_order")

    # 7. Send WhatsApp (route to caregiver if patient digital_comfort=low)
    body_template = summary.get("body") or _fallback_order_body(patient.get("name", ""), items, total, pay_link)
    body = body_template.replace("{PAY_LINK}", pay_link).replace("{{PAY_LINK}}", pay_link)
    if "{PAY_LINK}" not in body and pay_link not in body:
        body = body + f"\n\n{pay_link}"

    target_phone = patient.get("phone")
    routed_to = "patient"
    if sdoh.get("digital_comfort") == "low" and patient.get("caregiver_phone"):
        target_phone = patient["caregiver_phone"]
        routed_to = "caregiver"
    if target_phone:
        send_whatsapp(target_phone, body)
        tools_called.append(f"whatsapp:order_to_{routed_to}")

    # 8. CC caregiver via email
    caregiver_email = patient.get("caregiver_email") or settings.caregiver_email_default
    if caregiver_email:
        send_email(
            caregiver_email,
            f"CareLoop refill scheduled for {patient.get('name', 'patient')}",
            (summary.get("caregiver_note") or "")
            + f"\n\nPharmacy: {selected.get('name')} (ETA {selected.get('eta_hours')}h)\n"
            f"Total: ₹{total}\nPayment link: {pay_link}\n",
        )
        tools_called.append("email:caregiver_order")

    # 9. Persist order
    safe_insert(
        "pharmacy_orders",
        {
            "patient_id": patient_id,
            "pharmacy_id": selected.get("id"),
            "items": items,
            "total": total,
            "razorpay_link": pay_link,
            "payment_status": "pending",
            "eta_hours": selected.get("eta_hours"),
        },
    )
    tools_called.append("db:insert(pharmacy_orders)")

    decided = (
        f"Refill ordered: {len(items)} meds, total ₹{total} via {selected.get('name')} "
        f"(ETA {selected.get('eta_hours')}h). Routed to {routed_to}. Payment link sent."
    )
    _persist_reasoning(
        patient_id,
        observed={"low_stock_meds": [m.get("med_name") for m in low], "pharmacy_options": [p.get("name") for p in pharmacies]},
        inferred={"selected_pharmacy": selected.get("name"), "selection_reason": selection_reason, "items": items},
        decided=decided,
        tools=tools_called,
    )

    state.setdefault("tools_called", []).extend(tools_called)
    state.setdefault("reasoning_steps", []).append(
        {
            "agent": "pharmacy",
            "observed": {"low_stock_count": len(low)},
            "inferred": {"selected": selected.get("name"), "total": total},
            "decided": decided,
            "tools_called": tools_called,
        }
    )
    return state


def chat_text_safe(prompt: str) -> str:
    """Free-form text call to Groq for pharmacy selection (no template needed)."""
    try:
        from groq import Groq

        if not settings.groq_api_key:
            return ""
        client = Groq(api_key=settings.groq_api_key)
        resp = client.chat.completions.create(
            model=settings.groq_model_reasoning,
            temperature=0.2,
            max_tokens=512,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a clinical operations assistant. Pick exactly one pharmacy "
                        "from the options. Output STRICT JSON only with keys: pharmacy_id, reason. "
                        "Reason must cite at least one SDOH factor and one pharmacy attribute."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        log.error("pharmacy selection LLM call failed: %s", e)
        return ""


def _build_selection_prompt(sdoh: dict, pharmacies: list[dict]) -> str:
    options = "\n".join(
        f"- id={p.get('id')} name={p.get('name')} distance_km={p.get('distance_km')} "
        f"eta_hours={p.get('eta_hours')} price_modifier={p.get('price_modifier')}"
        for p in pharmacies
    )
    return (
        f"Patient SDOH:\n"
        f"- financial_risk: {sdoh.get('financial_risk')}\n"
        f"- literacy_level: {sdoh.get('literacy_level')}\n"
        f"- digital_comfort: {sdoh.get('digital_comfort')}\n"
        f"- transport_risk: {sdoh.get('transport_risk')}\n\n"
        f"Pharmacy options:\n{options}\n\n"
        f"Rules:\n"
        f"- If financial_risk=high, weight price_modifier heavily (lower is better).\n"
        f"- If transport_risk=high or patient is elderly, weight eta_hours heavily.\n"
        f"- If literacy_level=low, prefer pharmacies with simpler delivery flow (assume distance_km<5 = simpler).\n"
        f"Return JSON: {{\"pharmacy_id\": \"<id>\", \"reason\": \"<short>\"}}"
    )


def _parse_selection(raw: str, pharmacies: list[dict], sdoh: dict) -> tuple[str, str]:
    import json as _json

    try:
        parsed = _json.loads(raw or "{}")
        pid = parsed.get("pharmacy_id")
        reason = parsed.get("reason", "")
        if pid and any(p.get("id") == pid for p in pharmacies):
            return pid, reason
    except Exception:
        pass
    # Fallback: deterministic heuristic
    if sdoh.get("financial_risk") == "high":
        ranked = sorted(pharmacies, key=lambda p: float(p.get("price_modifier") or 1.0))
        return ranked[0].get("id"), "fallback: cheapest (financial_risk=high)"
    ranked = sorted(pharmacies, key=lambda p: int(p.get("eta_hours") or 99))
    return ranked[0].get("id"), "fallback: fastest ETA"


def _fallback_order_body(name: str, items: list[dict], total: float, link: str) -> str:
    lines = "\n".join(f"  - {i['med']} × {i['qty']}" for i in items)
    return (
        f"नमस्ते {name} ji 🙏\n"
        f"आपकी दवाई का refill तैयार है:\n{lines}\n"
        f"कुल: ₹{total}\n"
        f"नीचे लिंक से payment कीजिए — दवाई 24 घंटे में घर पहुँच जाएगी।\n\n"
        f"{link}"
    )
