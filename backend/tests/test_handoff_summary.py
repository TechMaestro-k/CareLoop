"""Tests for the doctor handoff summary feature.

Covers:
- build_doctor_handoff_summary returns the deterministic fallback when
  chat_json returns {}
- normalize fills in missing fields from the fallback
- GET /api/booking/{id} returns doctor_handoff_summary
- GET /api/booking/{id} reuses an existing summary if already stored
- Doctor accept still blocks unpaid bookings (no summary side-effects)
- Doctor accept ensures + includes the summary in the doctor email when paid
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("USE_MOCK_WHATSAPP", "true")
os.environ.setdefault("USE_MOCK_EMAIL", "true")
os.environ.setdefault("USE_MOCK_RAZORPAY", "true")


PATIENT = {
    "id": "p1", "name": "Jane Doe", "age": 64,
    "phone": "+19998880000", "email": "jane@example.com",
    "caregiver_email": "cg@example.com", "caregiver_phone": "+19998881111",
}
CLINICAL = {
    "patient_id": "p1",
    "diagnosis": "Heart Failure",
    "comorbidities": ["T2DM"],
    "medications": [{"name": "Metoprolol", "dose": "25mg"}],
}
SDOH = {
    "patient_id": "p1",
    "housing_risk": "low", "transport_risk": "high", "caregiver_risk": "high",
    "literacy_level": "low", "digital_comfort": "low", "financial_risk": "high",
}
CARE_PLAN = {"plan_json": {"red_flag_symptoms": ["dyspnea", "weight gain"]}, "created_at": "2026-04-20T00:00:00Z"}
INTERACTIONS = [
    # newest-first as the DB returns
    {"direction": "inbound",  "content": "I missed my evening dose yesterday",   "timestamp": "2026-04-29T10:01:00Z"},
    {"direction": "outbound", "content": "Are you taking your meds on schedule?", "timestamp": "2026-04-29T10:00:00Z"},
    {"direction": "inbound",  "content": "I feel a bit short of breath today",    "timestamp": "2026-04-29T09:00:00Z"},
]
ESCALATIONS = [
    {"id": "e1", "severity": "amber", "status": "pending",
     "brief": "mild dyspnea + missed dose", "created_at": "2026-04-29T10:05:00Z"},
]


def _fake_select_factory(proposal=None):
    def fake_select(table, **kwargs):
        if table == "patients":
            return [PATIENT]
        if table == "clinical_data":
            return [CLINICAL]
        if table == "sdoh_profiles":
            return [SDOH]
        if table == "care_plans":
            return [CARE_PLAN]
        if table == "interactions":
            return INTERACTIONS
        if table == "escalations":
            return ESCALATIONS
        if table == "slot_proposals":
            return [proposal] if proposal else []
        return []
    return fake_select


# ============================================================
# Helper-level tests
# ============================================================

def test_handoff_fallback_when_llm_returns_empty(monkeypatch):
    """If chat_json returns {}, we still get a useful, well-shaped summary."""
    from app.tools import handoff_summary as hs

    monkeypatch.setattr(hs, "safe_select", _fake_select_factory())
    monkeypatch.setattr(hs, "chat_json", lambda *a, **kw: {})

    out = hs.build_doctor_handoff_summary("p1")

    # All required keys present and well-typed
    assert isinstance(out, dict)
    for key in (
        "summary", "symptoms_reported", "medication_adherence",
        "risk_signals", "sdoh_context", "agent_actions_so_far", "doctor_focus",
    ):
        assert key in out, f"missing field: {key}"
    assert isinstance(out["symptoms_reported"], list)
    assert isinstance(out["risk_signals"], list)
    assert isinstance(out["sdoh_context"], list)
    assert isinstance(out["agent_actions_so_far"], list)
    assert isinstance(out["doctor_focus"], list)
    assert out["medication_adherence"] in {"unknown", "adherent", "missed_doses", "concern"}
    # "missed my evening dose" should drive adherence inference
    assert out["medication_adherence"] == "missed_doses"
    # Should mention the patient name in the deterministic fallback
    assert "Jane Doe" in out["summary"]


def test_handoff_normalizes_partial_llm_response(monkeypatch):
    """Missing fields from the LLM should be filled in from the fallback."""
    from app.tools import handoff_summary as hs

    monkeypatch.setattr(hs, "safe_select", _fake_select_factory())
    monkeypatch.setattr(hs, "chat_json", lambda *a, **kw: {
        "summary": "Jane is stable but missed a dose.",
        "medication_adherence": "missed_doses",
        # purposely missing the list fields
    })

    out = hs.build_doctor_handoff_summary("p1")
    assert out["summary"] == "Jane is stable but missed a dose."
    assert out["medication_adherence"] == "missed_doses"
    # Required list fields are still present (filled from fallback)
    assert isinstance(out["symptoms_reported"], list)
    assert isinstance(out["doctor_focus"], list)
    assert len(out["doctor_focus"]) >= 1


def test_handoff_invalid_adherence_coerced_to_unknown(monkeypatch):
    from app.tools import handoff_summary as hs

    monkeypatch.setattr(hs, "safe_select", _fake_select_factory())
    monkeypatch.setattr(hs, "chat_json", lambda *a, **kw: {
        "summary": "x",
        "medication_adherence": "totally_made_up",
    })
    out = hs.build_doctor_handoff_summary("p1")
    # Falls back to inferred (missed_doses from interactions) or 'unknown'
    assert out["medication_adherence"] in {"missed_doses", "unknown"}


# ============================================================
# Endpoint-level tests
# ============================================================

def test_get_proposal_returns_handoff_summary(monkeypatch):
    """GET /api/booking/{id} attaches doctor_handoff_summary to the response."""
    from app.api import booking

    proposal = {
        "id": "prop_get1", "patient_id": "p1",
        "chosen_slot": {
            "iso": "2026-04-30T15:00:00Z", "human": "Tomorrow 3 PM", "duration_min": 20,
            "payment": {"status": "paid", "amount_usd": 100, "currency": "USD"},
        },
        "patient_status": "chosen", "doctor_status": "pending",
        # no doctor_handoff_summary yet
    }
    monkeypatch.setattr("app.api.booking.safe_select", _fake_select_factory(proposal))
    monkeypatch.setattr("app.api.booking.safe_update", lambda *a, **kw: [])
    monkeypatch.setattr(
        "app.api.booking.build_doctor_handoff_summary",
        lambda patient_id, proposal_id=None: {
            "summary": "Generated summary for tests.",
            "symptoms_reported": ["short of breath"],
            "medication_adherence": "missed_doses",
            "risk_signals": ["amber escalation"],
            "sdoh_context": ["transport_risk=high"],
            "agent_actions_so_far": ["engaged patient"],
            "doctor_focus": ["confirm dyspnea"],
        },
    )

    res = booking.get_proposal("prop_get1")
    assert "doctor_handoff_summary" in res
    s = res["doctor_handoff_summary"]
    assert s["summary"] == "Generated summary for tests."
    assert s["medication_adherence"] == "missed_doses"
    # Patient + proposal are still in the response
    assert res["patient"]["id"] == "p1"
    assert res["proposal"]["id"] == "prop_get1"


def test_get_proposal_reuses_existing_summary(monkeypatch):
    """If the row already has a summary, we don't regenerate it."""
    from app.api import booking

    cached = {
        "summary": "Cached summary",
        "symptoms_reported": ["x"],
        "medication_adherence": "adherent",
        "risk_signals": [],
        "sdoh_context": [],
        "agent_actions_so_far": [],
        "doctor_focus": ["check x"],
    }
    proposal = {
        "id": "prop_cache", "patient_id": "p1",
        "doctor_handoff_summary": cached,
        "chosen_slot": None,
        "patient_status": "chosen", "doctor_status": "pending",
    }
    monkeypatch.setattr("app.api.booking.safe_select", _fake_select_factory(proposal))
    monkeypatch.setattr("app.api.booking.safe_update", lambda *a, **kw: [])

    called = {"n": 0}
    def boom(*a, **kw):
        called["n"] += 1
        raise AssertionError("should not regenerate when summary already exists")
    monkeypatch.setattr("app.api.booking.build_doctor_handoff_summary", boom)

    res = booking.get_proposal("prop_cache")
    assert res["doctor_handoff_summary"] == cached
    assert called["n"] == 0


def test_doctor_accept_still_blocks_unpaid(monkeypatch):
    """Payment gating must not regress — accept on unpaid → 402."""
    from app.api import booking
    from fastapi import HTTPException

    proposal = {
        "id": "prop_unpaid", "patient_id": "p1",
        "chosen_slot": {
            "iso": "2026-04-30T15:00:00Z", "human": "Tomorrow 3 PM", "duration_min": 20,
            "payment": {"status": "pending", "amount_usd": 100, "currency": "USD"},
        },
        "patient_status": "chosen", "doctor_status": "pending",
    }
    monkeypatch.setattr("app.api.booking.safe_select", _fake_select_factory(proposal))
    monkeypatch.setattr("app.api.booking.safe_update", lambda *a, **kw: [])

    # Summary builder must NOT be called when we're going to 402.
    def boom(*a, **kw):
        raise AssertionError("should not build summary on unpaid accept")
    monkeypatch.setattr("app.api.booking.build_doctor_handoff_summary", boom)

    with pytest.raises(HTTPException) as exc:
        booking.doctor_decision("prop_unpaid", booking.DecisionRequest(action="accept"))
    assert exc.value.status_code == 402


def test_doctor_accept_includes_handoff_summary_in_email(monkeypatch):
    """When the booking is paid, accept ensures the summary and includes it
    in the doctor confirmation email."""
    from app.api import booking
    from app import config as cfg

    proposal = {
        "id": "prop_paid", "patient_id": "p1",
        "chosen_slot": {
            "iso": "2026-04-30T15:00:00Z", "human": "Tomorrow 3 PM", "duration_min": 20,
            "payment": {"status": "paid", "amount_usd": 100, "currency": "USD",
                        "payment_id": "pay_test"},
        },
        "patient_status": "chosen", "doctor_status": "pending",
    }
    monkeypatch.setattr("app.api.booking.safe_select", _fake_select_factory(proposal))
    monkeypatch.setattr("app.api.booking.safe_update", lambda *a, **kw: [])

    summary_payload = {
        "summary": "TESTSUMMARY-Jane is stable.",
        "symptoms_reported": ["dyspnea"],
        "medication_adherence": "missed_doses",
        "risk_signals": ["amber escalation"],
        "sdoh_context": ["transport_risk=high"],
        "agent_actions_so_far": ["engaged patient"],
        "doctor_focus": ["confirm dyspnea"],
    }
    monkeypatch.setattr(
        "app.api.booking.build_doctor_handoff_summary",
        lambda patient_id, proposal_id=None: summary_payload,
    )
    monkeypatch.setattr(
        "app.api.booking.confirm_booking",
        lambda **kw: {
            "link": "https://meet.jit.si/abc", "calendar_link": "https://cal/abc",
            "slot_human": kw["chosen_slot"]["human"],
        },
    )

    captured_emails: list[dict] = []
    def fake_send_email(to, subject, body, html=None):
        captured_emails.append({"to": to, "subject": subject, "body": body})
        return {"ok": True, "mock": True}
    monkeypatch.setattr("app.api.booking.send_email", fake_send_email)
    monkeypatch.setattr("app.api.booking.send_whatsapp", lambda *a, **kw: {"ok": True, "mock": True})
    # Force a doctor email config so the send path runs
    monkeypatch.setattr(cfg.settings, "doctor_email", "doc@example.com")
    monkeypatch.setattr(cfg.settings, "doctor_phone", "")
    monkeypatch.setattr(cfg.settings, "caregiver_email_default", "")

    res = booking.doctor_decision("prop_paid", booking.DecisionRequest(action="accept"))
    assert res["status"] == "accepted"
    assert res["doctor_handoff_summary"] == summary_payload

    # The doctor confirmation email must include the summary block.
    doctor_emails = [e for e in captured_emails if e["to"] == "doc@example.com"]
    assert doctor_emails, "no email sent to doctor"
    assert any("TESTSUMMARY-Jane is stable." in e["body"] for e in doctor_emails)
    assert any("WHAT THE PATIENT IS REPORTING" in e["body"] for e in doctor_emails)
