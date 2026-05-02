"""End-to-end CareLoop scenario simulation.

Runs a battery of patient ↔ agent ↔ doctor scenarios against the *real*
Supabase database (so the DB shows the resulting rows for inspection),
but with WhatsApp / email / Razorpay forced into MOCK mode so no real
messages are sent during the run.

Each scenario:
  1. Picks a patient by phone.
  2. Calls /messages/simulate with a representative inbound text.
  3. (Optional) Drives the booking endpoints to simulate the patient
     picking a slot, paying, and the doctor accepting.
  4. Records what we observed and prints PASS/FAIL.

Usage:
    cd careloop/careloop/backend
    python -m scripts.simulate_scenarios
"""
from __future__ import annotations

# IMPORTANT: force mock toggles BEFORE importing the app so settings()
# is constructed with them on. This stops the script from accidentally
# blasting Twilio / Gmail / Razorpay during a verification run.
import os

os.environ.setdefault("USE_MOCK_WHATSAPP", "1")
os.environ.setdefault("USE_MOCK_EMAIL", "1")
os.environ.setdefault("USE_MOCK_RAZORPAY", "1")

import json
import logging
import sys
import time
from typing import Any

from fastapi.testclient import TestClient

# Rebuild settings with the mock env in effect.
from app.config import get_settings  # noqa: E402

get_settings.cache_clear()  # type: ignore[attr-defined]

from app.main import app  # noqa: E402  (imports must come AFTER env is set)
from app.db.client import safe_select  # noqa: E402

logging.basicConfig(
    level=logging.WARNING,  # quiet down httpx etc; we drive output ourselves
    format="%(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("simulate")
log.setLevel(logging.INFO)

client = TestClient(app)


# ---------- helpers ----------

def _patient_by_phone(phone: str) -> dict[str, Any] | None:
    rows = safe_select("patients", match={"phone": phone}, limit=1)
    return rows[0] if rows else None


def _pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)[:1500]


def _latest_escalation(patient_id: str) -> dict | None:
    rows = safe_select(
        "escalations",
        match={"patient_id": patient_id},
        order=("created_at", True),
        limit=1,
    )
    return rows[0] if rows else None


def _latest_proposal(patient_id: str) -> dict | None:
    rows = safe_select(
        "slot_proposals",
        match={"patient_id": patient_id},
        order=("created_at", True),
        limit=1,
    )
    return rows[0] if rows else None


# ---------- scenario runner ----------

class Result:
    def __init__(self, name: str):
        self.name = name
        self.steps: list[tuple[str, bool, str]] = []

    def expect(self, label: str, ok: bool, detail: str = "") -> bool:
        self.steps.append((label, ok, detail))
        return ok

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.steps)


def _send(patient_id: str, message: str) -> dict:
    """Drive the simulate endpoint and return its JSON."""
    r = client.post(
        "/api/messages/simulate",
        json={"patient_id": patient_id, "message": message},
    )
    r.raise_for_status()
    return r.json()


def _severity(out: dict) -> str:
    """Pull severity out of /messages/simulate response.

    `classification` is the full NLU dict; severity may also be reported
    as a string in `decision_summary` or `decision`. Always returns lowercase.
    """
    cls = out.get("classification")
    if isinstance(cls, dict):
        return (cls.get("severity") or "").lower()
    if isinstance(cls, str):
        return cls.lower()
    return ""


# ---------- scenarios ----------

def scenario_green_checkin(patient: dict) -> Result:
    r = Result("S1 · GREEN routine wellness reply")
    out = _send(patient["id"], "I'm feeling fine today, took my morning meds.")
    sev = _severity(out)
    r.expect("classification == green", sev == "green", f"got severity={sev!r}")
    msgs = out.get("whatsapp_sent") or []
    r.expect("≥1 WhatsApp reply queued", len(msgs) >= 1, f"sent={len(msgs)}")
    # No escalation row should be created for GREEN.
    esc = _latest_escalation(patient["id"])
    r.expect(
        "no NEW escalation row for green",
        esc is None or (esc.get("severity") or "").lower() != "green",
        f"latest_escalation={esc.get('severity') if esc else None}",
    )
    return r


def scenario_amber(patient: dict) -> Result:
    r = Result("S2 · AMBER mild dizziness — caregiver loop + escalation row")
    pre_count = len(safe_select("escalations", match={"patient_id": patient["id"]}))
    out = _send(
        patient["id"],
        "I feel a bit dizzy this morning and slept badly, but no chest pain.",
    )
    sev = _severity(out)
    r.expect("classification == amber", sev == "amber", f"got severity={sev!r}")
    post_count = len(safe_select("escalations", match={"patient_id": patient["id"]}))
    r.expect(
        "AMBER created an escalation row (insights fix)",
        post_count == pre_count + 1,
        f"pre={pre_count} post={post_count}",
    )
    esc = _latest_escalation(patient["id"])
    r.expect(
        "latest escalation severity == amber",
        bool(esc) and (esc.get("severity") or "").lower() == "amber",
        f"got={esc.get('severity') if esc else None}",
    )
    return r


def scenario_red_with_booking(patient: dict) -> Result:
    r = Result("S3 · RED chest pain — escalation, slot proposal, payment, doctor accept")
    out = _send(
        patient["id"],
        "I have heavy chest pain since morning and I cannot breathe properly.",
    )
    sev = _severity(out)
    r.expect("classification == red", sev == "red", f"got severity={sev!r}")
    esc = _latest_escalation(patient["id"])
    r.expect(
        "RED created an escalation row",
        bool(esc) and (esc.get("severity") or "").lower() == "red",
        f"esc={esc.get('severity') if esc else None}",
    )
    prop = _latest_proposal(patient["id"])
    r.expect(
        "RED created a slot proposal",
        bool(prop) and bool(prop.get("proposed_slots")),
        f"proposal_id={prop.get('id') if prop else None}",
    )
    if not prop:
        return r
    # Simulate the patient picking the first slot.
    first_slot = (prop.get("proposed_slots") or [{}])[0]
    sel = client.post(
        f"/api/booking/{prop['id']}/select",
        json={"slot_iso": first_slot.get("iso")},
    )
    r.expect(
        "patient slot-pick endpoint 200",
        sel.status_code == 200,
        f"http={sel.status_code} body={sel.text[:200]}",
    )
    # Simulate the payment (mock razorpay → mark paid).
    pay = client.post(f"/api/booking/{prop['id']}/simulate-payment")
    r.expect(
        "simulate-payment endpoint 200",
        pay.status_code == 200,
        f"http={pay.status_code} body={pay.text[:200]}",
    )
    # Doctor accepts.
    dec = client.post(
        f"/api/booking/{prop['id']}/decision",
        json={"action": "accept", "note": "Joining the call now."},
    )
    r.expect(
        "doctor accept endpoint 200",
        dec.status_code == 200,
        f"http={dec.status_code} body={dec.text[:200]}",
    )
    final = _latest_proposal(patient["id"])
    chosen = (final or {}).get("chosen_slot") or {}
    r.expect(
        "chosen_slot persisted with payment.status=paid",
        (chosen.get("payment") or {}).get("status") == "paid",
        f"payment={chosen.get('payment')}",
    )
    r.expect(
        "doctor_status == accepted",
        (final or {}).get("doctor_status") == "accepted",
        f"doctor_status={(final or {}).get('doctor_status')}",
    )
    # Handoff summary fallback path (chosen_slot.handoff_summary OR top-level)
    has_summary = bool((final or {}).get("doctor_handoff_summary")) or bool(
        (chosen.get("handoff_summary") or {})
    )
    r.expect("doctor handoff summary present", has_summary, "")
    return r


def scenario_clarify(patient: dict) -> Result:
    r = Result("S4 · vague message → CLARIFY (asks one short question)")
    out = _send(patient["id"], "not good today")
    sev = _severity(out)
    decision = (out.get("decision") or "").lower()
    r.expect(
        "severity is clarify or amber (LLM may pick either)",
        sev in {"clarify", "amber"},
        f"got severity={sev!r}",
    )
    r.expect(
        "decision string mentions clarify or safe-steps",
        any(k in decision for k in ("clarify", "amber", "safe steps", "concrete")),
        f"decision={decision[:120]}",
    )
    return r


def scenario_doctor_reject(patient: dict) -> Result:
    """Patient asks for a slot, pays, but the doctor reschedules."""
    r = Result("S6 · doctor reschedules an already-paid slot")
    out = _send(patient["id"], "Bad chest pressure and difficulty breathing right now.")
    if _severity(out) != "red":
        r.expect("RED triage required for this scenario", False, f"got={out.get('classification')}")
        return r
    prop = _latest_proposal(patient["id"])
    if not prop:
        r.expect("proposal must exist", False)
        return r
    slot_iso = (prop.get("proposed_slots") or [{}])[0].get("iso")
    client.post(f"/api/booking/{prop['id']}/select", json={"slot_iso": slot_iso})
    client.post(f"/api/booking/{prop['id']}/simulate-payment")
    dec = client.post(
        f"/api/booking/{prop['id']}/decision",
        json={"action": "reschedule", "note": "Stuck in a procedure — propose a new time."},
    )
    r.expect("reschedule decision 200", dec.status_code == 200, f"http={dec.status_code}")
    final = _latest_proposal(patient["id"])
    r.expect(
        "doctor_status == rescheduled",
        (final or {}).get("doctor_status") == "rescheduled",
        f"got={(final or {}).get('doctor_status')}",
    )
    return r


# ---------- main ----------

def main() -> int:
    print("\n=== CareLoop end-to-end scenario simulation ===\n")
    print("Mock toggles: WhatsApp=ON  Email=ON  Razorpay=ON")
    print("Database:    LIVE Supabase (rows will be created)\n")

    sharma = _patient_by_phone("+919999900001")
    iyer = _patient_by_phone("+919999900011")
    khan = _patient_by_phone("+919999900021")

    if not all([sharma, iyer, khan]):
        print("ERROR: demo cohort missing. Run `python -m scripts.reset_demo` first.")
        return 1

    results: list[Result] = []
    results.append(scenario_green_checkin(iyer))
    results.append(scenario_amber(khan))
    results.append(scenario_red_with_booking(sharma))
    results.append(scenario_clarify(iyer))
    results.append(scenario_doctor_reject(khan))

    # ---- report ----
    pass_n = sum(1 for r in results if r.passed)
    fail_n = len(results) - pass_n
    print("\n----- Scenario report -----")
    for r in results:
        icon = "PASS" if r.passed else "FAIL"
        print(f"\n[{icon}] {r.name}")
        for label, ok, detail in r.steps:
            mark = "  ✓" if ok else "  ✗"
            print(f"   {mark} {label}" + (f"   ← {detail}" if (not ok and detail) else ""))
    print(f"\nTotal: {pass_n}/{len(results)} scenarios passed.\n")
    return 0 if fail_n == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
