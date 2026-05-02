"""Per-agent unit tests.

Each agent gets one focused test that exercises its node with mocked
LLM + DB calls, so the suite stays fast and offline-safe.
"""
from __future__ import annotations

import os

os.environ.setdefault("USE_MOCK_WHATSAPP", "true")
os.environ.setdefault("USE_MOCK_EMAIL", "true")
os.environ.setdefault("USE_MOCK_RAZORPAY", "true")


# ============================================================
# Agent 1 — Context Builder
# ============================================================
def test_context_builder_agent_builds_kg_and_fuses_risk(monkeypatch):
    """Context builder must extract clinical entities, classify SDOH,
    build a KG, persist all three tables, and write a fused risk score
    onto the state."""
    from app.agents import context_builder as cb

    fake_clinical = {
        "diagnosis": "Heart Failure",
        "icd_codes": ["I50.9"],
        "medications": [{"name": "Metoprolol", "dose": "25mg"}],
        "comorbidities": ["T2DM"],
        "discharge_date": "2026-04-20",
        "follow_up_date": "2026-05-04",
        "clinical_severity": 0.8,
    }
    fake_sdoh = {
        "housing_risk": "low",
        "transport_risk": "high",
        "caregiver_risk": "medium",
        "literacy_level": "low",
        "digital_comfort": "low",
        "financial_risk": "high",
        "language": "hi",
    }

    def fake_chat_json(key, **_):
        return fake_clinical if key == "clinical_ner" else fake_sdoh

    upserts: list[tuple] = []
    monkeypatch.setattr(cb, "chat_json", fake_chat_json)
    monkeypatch.setattr(cb, "safe_upsert", lambda table, row, **kw: upserts.append((table, row)) or row)
    monkeypatch.setattr(cb, "safe_insert", lambda *a, **kw: None)

    state = {
        "patient_id": "p_ctx",
        "raw_discharge_text": "Discharge: HF.",
        "sdoh_responses": {"housing": "stable"},
    }
    out = cb.context_builder_node(state)

    tables = {t for t, _ in upserts}
    assert {"clinical_data", "sdoh_profiles", "knowledge_graphs"}.issubset(tables)
    assert out["clinical_extracted"]["diagnosis"] == "Heart Failure"
    assert out["sdoh_profile"]["financial_risk"] == "high"
    assert 0.0 < out["risk_score"] <= 1.0
    # Language must propagate from the SDOH profile onto state
    assert out["language"] == "hi"
    # KG must have been built
    assert out["knowledge_graph"].number_of_nodes() > 5
    assert "nodes" in out["knowledge_graph_json"]


# ============================================================
# Agent 2 — Care Plan
# ============================================================
def test_care_plan_agent_defaults_language_and_sends_welcome(monkeypatch):
    """Care plan node must default missing plan keys (language, channel,
    cadence, caregiver loop) and dispatch a WhatsApp welcome."""
    from app.agents import care_plan as cp

    sent: list[dict] = []
    monkeypatch.setattr(cp, "chat_json", lambda *a, **kw: {})  # empty plan → defaults kick in
    monkeypatch.setattr(cp, "safe_insert", lambda *a, **kw: {"id": "cp1"})
    monkeypatch.setattr(cp, "send_whatsapp",
                        lambda phone, text, media_url=None: sent.append({"phone": phone, "text": text}) or {"ok": True, "mock": True})
    monkeypatch.setattr(cp, "send_email", lambda *a, **kw: {"ok": True, "mock": True})
    monkeypatch.setattr(cp, "synthesize_sync", lambda *a, **kw: None)
    monkeypatch.setattr(cp, "public_audio_url", lambda *a, **kw: None)
    monkeypatch.setattr("app.scheduler.jobs.schedule_daily_checkin", lambda *a, **kw: None)

    state = {
        "patient_id": "p_cp",
        "patient_record": {"name": "Jane", "phone": "+19998880000", "caregiver_email": None},
        "clinical_extracted": {"diagnosis": "CHF", "medications": []},
        "sdoh_profile": {"literacy_level": "low", "language": "hi", "caregiver_risk": "low"},
        "risk_score": 0.6,
        "language": "hi",
        "channel": "whatsapp_text",
    }
    out = cp.care_plan_node(state)
    plan = out["care_plan"]

    assert plan["language"] == "hi"            # came from state.language
    assert plan["channel"] == "whatsapp_text"
    assert plan["check_in_cadence"] == "daily"
    assert plan["simplification_level"] == "high"  # because literacy_level=low
    assert sent and sent[0]["phone"] == "+19998880000"
    assert "Jane" in sent[0]["text"]


# ============================================================
# Agent 3 — Engagement (router decision)
# ============================================================
def test_engagement_agent_green_path_does_not_escalate(monkeypatch):
    """A GREEN classification must NOT create a slot proposal or page
    the doctor — only a reassuring patient reply goes out."""
    from app.agents import engagement as eng

    patient = {
        "id": "p_green", "name": "Mrs. Sharma", "phone": "+911234567890",
        "language": "en", "caregiver_email": None, "caregiver_phone": None,
    }

    def fake_select(table, **kw):
        if table == "patients":
            return [patient]
        if table == "clinical_data":
            return [{"diagnosis": "CHF", "discharge_date": "2026-04-20"}]
        if table == "care_plans":
            return [{"plan_data": {"red_flag_symptoms": ["dyspnea"]}}]
        return []

    proposals_made: list = []
    monkeypatch.setattr(eng, "safe_select", fake_select)
    monkeypatch.setattr(eng, "safe_insert", lambda *a, **kw: None)
    monkeypatch.setattr(eng, "_persist_reasoning", lambda *a, **kw: None)
    monkeypatch.setattr(eng, "chat_json", lambda *a, **kw: {
        "severity": "green", "confidence": 0.95, "symptoms": [],
        "needs_clarification": False, "clarifying_question": "",
    })
    monkeypatch.setattr(eng, "chat_text", lambda *a, **kw: "Glad to hear it — keep up your daily walk.")
    monkeypatch.setattr(eng, "_maybe_voice", lambda *a, **kw: None)
    monkeypatch.setattr(eng, "create_proposal_from_agent",
                        lambda **kw: proposals_made.append(kw) or {"picker_url": "x"})

    out = eng.engagement_node({
        "patient_id": "p_green", "current_message": "feeling fine today",
        "patient_record": patient, "language": "en", "channel": "whatsapp_text",
        "triggered_by": "inbound",
    })

    assert proposals_made == [], "GREEN must not create a slot proposal"
    sends = out.get("outgoing_messages", [])
    assert any(s["to"] == "patient" for s in sends), "patient must get a reply"
    assert not any(s["to"] in {"caregiver", "doctor"} for s in sends), \
        "GREEN must not page caregiver/doctor"


# ============================================================
# Agent 4 — Pharmacy
# ============================================================
def test_pharmacy_agent_routes_to_caregiver_when_digital_comfort_low(monkeypatch):
    """When sdoh.digital_comfort == 'low' AND a caregiver phone exists,
    the refill WhatsApp must go to the caregiver, not the patient."""
    from app.agents import pharmacy as pharm

    patient = {
        "id": "p_pharm", "name": "Mrs. Sharma",
        "phone": "+911111111111", "caregiver_phone": "+919876500000",
        "caregiver_email": "cg@x.com", "email": "p@x.com",
    }
    sdoh = {"digital_comfort": "low", "literacy_level": "low", "language": "hi"}
    inv = [{"med_name": "Metoprolol", "count_remaining": 1, "days_remaining": 1, "last_refill_date": None}]
    pharmacies = [
        {"id": "ph_jan", "name": "Jan Aushadhi", "eta_hours": 24, "price_modifier": 0.6, "distance_km": 2},
        {"id": "ph_apo", "name": "Apollo",       "eta_hours": 2,  "price_modifier": 1.0, "distance_km": 1},
    ]

    sends: list[dict] = []
    monkeypatch.setattr(pharm, "has_recent_refill", lambda *a, **kw: False)
    monkeypatch.setattr(pharm, "_patient_record", lambda pid: patient)
    monkeypatch.setattr(pharm, "_sdoh", lambda pid: sdoh)
    monkeypatch.setattr(pharm, "safe_select",
                        lambda table, **kw: inv if table == "medications_inventory"
                        else (pharmacies if table == "pharmacies" else []))
    monkeypatch.setattr(pharm, "safe_insert", lambda *a, **kw: None)
    monkeypatch.setattr(pharm, "_persist_reasoning", lambda *a, **kw: None)
    monkeypatch.setattr(pharm, "chat_text_safe", lambda prompt: "ph_jan|cheaper for high financial risk")
    monkeypatch.setattr(pharm, "chat_json", lambda *a, **kw: {
        "body": "Refill ready — pay here {PAY_LINK}",
        "caregiver_note": "Mrs. Sharma's refill is ready.",
    })
    monkeypatch.setattr(pharm, "create_payment_link", lambda **kw: {"ok": True, "mock": True, "link": "https://rzp.io/i/X"})
    monkeypatch.setattr(pharm, "send_whatsapp",
                        lambda phone, body, **kw: sends.append({"phone": phone, "body": body}) or {"ok": True})
    monkeypatch.setattr(pharm, "send_email", lambda *a, **kw: {"ok": True})

    out = pharm.pharmacy_node({"patient_id": "p_pharm"})

    assert sends, "pharmacy must send the order WhatsApp"
    assert sends[0]["phone"] == "+919876500000", \
        f"low digital_comfort → must route to caregiver, got {sends[0]['phone']}"
    assert "https://rzp.io/i/X" in sends[0]["body"]
    # And the agent must have recorded its trace on the state
    assert any(s["agent"] == "pharmacy" for s in out.get("reasoning_steps", []))


# ============================================================
# Agent 5 — Orchestrator (LangGraph wiring)
# ============================================================
def test_orchestrator_runs_onboarding_then_care_plan_in_order(monkeypatch):
    """run_onboarding must invoke the LangGraph that walks
    context_builder → care_plan in that order."""
    from app.agents import graph as graph_mod

    calls: list[str] = []

    def fake_ctx(state):
        calls.append("ctx")
        state["clinical_extracted"] = {"diagnosis": "CHF"}
        state["sdoh_profile"] = {"language": "en"}
        state["risk_score"] = 0.5
        return state

    def fake_cp(state):
        calls.append("cp")
        state["care_plan"] = {"channel": "whatsapp_text", "language": "en"}
        return state

    # Rebuild the compiled graph with our fakes wired into the nodes the
    # graph captured at import time. Easiest route: monkeypatch the
    # underlying node functions and re-compile a fresh onboarding graph.
    monkeypatch.setattr(graph_mod, "context_builder_node", fake_ctx)
    monkeypatch.setattr(graph_mod, "care_plan_node", fake_cp)
    fresh = graph_mod._build_onboarding_graph()
    out = fresh.invoke({"patient_id": "p_orch"})

    assert calls == ["ctx", "cp"], f"expected ctx → cp, got {calls}"
    assert out["clinical_extracted"]["diagnosis"] == "CHF"
    assert out["care_plan"]["channel"] == "whatsapp_text"
