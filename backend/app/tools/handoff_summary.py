"""Build the AI doctor handoff summary shown before a telehealth consult.

Pulled from the patient's structured records (clinical, SDOH, care plan,
escalations) plus the latest 20 CareLoop interactions. The result is stored
separately on `slot_proposals.doctor_handoff_summary` so the raw patient
chat history stays clean — we never insert this summary back into the
interactions table as a fake message.

Public API:
    build_doctor_handoff_summary(patient_id, proposal_id=None) -> dict

This function never raises on normal failures. If the LLM call returns {}
or the prompt is missing, it falls back to a deterministic, factual
summary built from the same source data.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.db.client import safe_select
from app.tools.llm import chat_json

log = logging.getLogger(__name__)

INTERACTIONS_LIMIT = 20
ESCALATIONS_LIMIT = 5

REQUIRED_FIELDS: dict[str, Any] = {
    "summary": "",
    "symptoms_reported": [],
    "medication_adherence": "unknown",
    "risk_signals": [],
    "sdoh_context": [],
    "agent_actions_so_far": [],
    "doctor_focus": [],
}

ADHERENCE_VALUES = {"unknown", "adherent", "missed_doses", "concern"}


# ---------------- Loaders ----------------

def _load_patient(patient_id: str) -> dict:
    rows = safe_select("patients", match={"id": patient_id}, limit=1)
    return rows[0] if rows else {}


def _load_clinical(patient_id: str) -> dict:
    rows = safe_select("clinical_data", match={"patient_id": patient_id}, limit=1)
    return rows[0] if rows else {}


def _load_sdoh(patient_id: str) -> dict:
    rows = safe_select("sdoh_profiles", match={"patient_id": patient_id}, limit=1)
    return rows[0] if rows else {}


def _load_latest_care_plan(patient_id: str) -> dict:
    rows = safe_select(
        "care_plans",
        match={"patient_id": patient_id},
        order=("created_at", True),
        limit=1,
    )
    if not rows:
        return {}
    row = rows[0]
    # Schema column is `plan_json`; some test fixtures use `plan_data`. Accept either.
    return row.get("plan_json") or row.get("plan_data") or {}


def _load_latest_interactions(patient_id: str, limit: int = INTERACTIONS_LIMIT) -> list[dict]:
    return safe_select(
        "interactions",
        match={"patient_id": patient_id},
        order=("timestamp", True),
        limit=limit,
    ) or []


def _load_recent_escalations(patient_id: str, limit: int = ESCALATIONS_LIMIT) -> list[dict]:
    return safe_select(
        "escalations",
        match={"patient_id": patient_id},
        order=("created_at", True),
        limit=limit,
    ) or []


def _load_slot_proposal(proposal_id: str) -> dict:
    rows = safe_select("slot_proposals", match={"id": proposal_id}, limit=1)
    return rows[0] if rows else {}


# ---------------- Formatting ----------------

def _format_transcript(interactions: list[dict]) -> str:
    """Format interactions oldest-first, labelled Patient: / CareLoop: ."""
    if not interactions:
        return "(no prior conversation)"
    rows = list(reversed(interactions))  # DB is newest-first → flip to oldest-first
    lines: list[str] = []
    for r in rows:
        content = (r.get("content") or "").strip()
        if not content:
            continue
        who = "Patient" if (r.get("direction") or "").startswith("inbound") else "CareLoop"
        lines.append(f"{who}: {content}")
    return "\n".join(lines) or "(no prior conversation)"


def _summarize_sdoh(sdoh: dict) -> str:
    if not sdoh:
        return "unknown"
    keys = (
        "housing_risk", "transport_risk", "caregiver_risk",
        "literacy_level", "digital_comfort", "financial_risk",
    )
    parts = [f"{k}={sdoh.get(k)}" for k in keys if sdoh.get(k)]
    return ", ".join(parts) or "unknown"


def _summarize_meds(clinical: dict) -> str:
    meds = clinical.get("medications") or []
    if isinstance(meds, str):
        return meds
    if not meds:
        return "unknown"
    out: list[str] = []
    for m in meds:
        if isinstance(m, dict):
            name = m.get("name") or m.get("drug") or ""
            dose = m.get("dose") or m.get("dosage") or ""
            out.append(f"{name} {dose}".strip() or json.dumps(m))
        else:
            out.append(str(m))
    return ", ".join(out) or "unknown"


def _summarize_escalations(escalations: list[dict]) -> str:
    if not escalations:
        return "(none)"
    out: list[str] = []
    for e in escalations:
        sev = (e.get("severity") or "?").upper()
        status = e.get("status") or "?"
        when = e.get("created_at") or ""
        brief = (e.get("brief") or "").strip().replace("\n", " ")
        if len(brief) > 200:
            brief = brief[:200] + "…"
        out.append(f"- [{sev}/{status}] {when}: {brief}")
    return "\n".join(out)


def _summarize_booking(proposal: dict) -> str:
    if not proposal:
        return "(no booking context)"
    chosen = proposal.get("chosen_slot") or {}
    payment = (chosen.get("payment") or {}) if isinstance(chosen, dict) else {}
    parts = [
        f"urgency={proposal.get('urgency') or 'unknown'}",
        f"chosen={chosen.get('human') or 'not yet picked'}",
        f"payment_status={payment.get('status') or 'n/a'}",
        f"doctor_status={proposal.get('doctor_status') or 'pending'}",
    ]
    return ", ".join(parts)


# ---------------- Heuristics for fallback ----------------

def _infer_adherence(interactions: list[dict]) -> str:
    """Cheap keyword scan; safe default is 'unknown'."""
    text = " ".join(((r.get("content") or "") for r in interactions)).lower()
    if not text:
        return "unknown"
    miss_kw = ("missed", "forgot", "didn't take", "didnt take", "skipped", "ran out", "out of pills")
    ok_kw = ("took my", "taken my", "took it", "took meds", "taking my")
    if any(k in text for k in miss_kw):
        return "missed_doses"
    if any(k in text for k in ok_kw):
        return "adherent"
    return "unknown"


def _infer_symptoms(interactions: list[dict]) -> list[str]:
    """Best-effort symptom scrape from inbound messages."""
    keywords = [
        "breath", "dyspnea", "chest pain", "weight gain", "swelling", "edema",
        "cough", "dizzy", "dizziness", "nausea", "vomit", "fever", "fatigue",
        "tired", "headache", "blood pressure", "sugar", "hypoglycemia",
    ]
    found: list[str] = []
    for r in interactions:
        if not (r.get("direction") or "").startswith("inbound"):
            continue
        content = (r.get("content") or "").lower()
        for kw in keywords:
            if kw in content and kw not in found:
                found.append(kw)
    return found[:6]


def _build_fallback(
    *,
    patient: dict,
    clinical: dict,
    sdoh: dict,
    care_plan: dict,
    interactions: list[dict],
    escalations: list[dict],
    proposal: dict,
) -> dict:
    name = patient.get("name") or "Patient"
    age = patient.get("age")
    dx = clinical.get("diagnosis") or "unknown diagnosis"
    n_inter = len(interactions)
    n_esc = len(escalations)
    last_msg = ""
    for r in interactions:
        if (r.get("direction") or "").startswith("inbound"):
            last_msg = (r.get("content") or "").strip()
            break

    summary_bits = [
        f"{name}{f', {age}y' if age else ''} — {dx}.",
        f"{n_inter} recent CareLoop interactions on file.",
    ]
    if n_esc:
        sev_top = (escalations[0].get("severity") or "").upper()
        if sev_top:
            summary_bits.append(f"Most recent escalation severity: {sev_top}.")
    if last_msg:
        snip = last_msg if len(last_msg) <= 140 else last_msg[:140] + "…"
        summary_bits.append(f'Last patient message: "{snip}"')

    symptoms = _infer_symptoms(interactions)
    adherence = _infer_adherence(interactions)

    risk_signals: list[str] = []
    for e in escalations:
        sev = (e.get("severity") or "").lower()
        if sev in ("red", "amber"):
            risk_signals.append(f"{sev} escalation on {e.get('created_at','')}")
    risk_flags = (care_plan.get("red_flag_symptoms") or []) if isinstance(care_plan, dict) else []
    for f in risk_flags[:3]:
        risk_signals.append(f"watch: {f}")

    sdoh_context: list[str] = []
    for k in ("housing_risk", "transport_risk", "caregiver_risk", "financial_risk", "digital_comfort", "literacy_level"):
        v = sdoh.get(k)
        if v and str(v).lower() in ("high", "low"):
            sdoh_context.append(f"{k}={v}")

    agent_actions: list[str] = []
    if n_inter:
        agent_actions.append(f"engaged patient via CareLoop ({n_inter} recent turns)")
    if proposal:
        chosen = proposal.get("chosen_slot") or {}
        if chosen.get("human"):
            agent_actions.append(f"booked slot: {chosen['human']}")
        payment = (chosen.get("payment") or {}) if isinstance(chosen, dict) else {}
        if payment.get("status") == "paid":
            agent_actions.append("consult fee paid")

    doctor_focus: list[str] = []
    if symptoms:
        doctor_focus.append(f"confirm current symptoms: {', '.join(symptoms[:3])}")
    if adherence in ("missed_doses", "concern"):
        doctor_focus.append("review medication adherence")
    if risk_flags:
        doctor_focus.append(f"check care-plan red flags: {', '.join(risk_flags[:2])}")
    if not doctor_focus:
        doctor_focus.append("general check-in; no specific red flags surfaced by CareLoop")

    return {
        "summary": " ".join(summary_bits),
        "symptoms_reported": symptoms,
        "medication_adherence": adherence,
        "risk_signals": risk_signals,
        "sdoh_context": sdoh_context or ["unknown"],
        "agent_actions_so_far": agent_actions or ["no recorded CareLoop actions"],
        "doctor_focus": doctor_focus,
    }


# ---------------- Normalization ----------------

def _coerce_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        s = v.strip()
        return [s] if s else []
    return [str(v)]


def _normalize(raw: dict, fallback: dict) -> dict:
    """Make sure every required field is present and well-typed."""
    if not isinstance(raw, dict):
        raw = {}
    out: dict[str, Any] = {}
    for key, default in REQUIRED_FIELDS.items():
        if key not in raw or raw.get(key) in (None, "", []):
            out[key] = fallback.get(key, default)
            continue
        if isinstance(default, list):
            out[key] = _coerce_list(raw.get(key)) or fallback.get(key, [])
        else:
            out[key] = str(raw.get(key)).strip() or fallback.get(key, default)

    # Constrain adherence enum
    if out["medication_adherence"] not in ADHERENCE_VALUES:
        out["medication_adherence"] = fallback.get("medication_adherence", "unknown")
        if out["medication_adherence"] not in ADHERENCE_VALUES:
            out["medication_adherence"] = "unknown"

    return out


# ---------------- Public API ----------------

def build_doctor_handoff_summary(
    patient_id: str,
    proposal_id: Optional[str] = None,
) -> dict:
    """Return a doctor-facing handoff summary dict.

    Always returns a dict with the required keys. Never raises on normal
    failures (missing data, LLM unavailable, malformed JSON) — falls back
    to a deterministic summary built from the same source data.
    """
    try:
        patient = _load_patient(patient_id)
        clinical = _load_clinical(patient_id)
        sdoh = _load_sdoh(patient_id)
        care_plan = _load_latest_care_plan(patient_id)
        interactions = _load_latest_interactions(patient_id, limit=INTERACTIONS_LIMIT)
        escalations = _load_recent_escalations(patient_id, limit=ESCALATIONS_LIMIT)
        proposal = _load_slot_proposal(proposal_id) if proposal_id else {}
    except Exception as e:  # pragma: no cover - defensive
        log.error("handoff_summary: data load failed for %s: %s", patient_id, e)
        return _normalize({}, _build_fallback(
            patient={}, clinical={}, sdoh={}, care_plan={},
            interactions=[], escalations=[], proposal={},
        ))

    fallback = _build_fallback(
        patient=patient,
        clinical=clinical,
        sdoh=sdoh,
        care_plan=care_plan,
        interactions=interactions,
        escalations=escalations,
        proposal=proposal,
    )

    transcript = _format_transcript(interactions)
    care_plan_str = json.dumps(care_plan, default=str) if care_plan else "(none)"

    try:
        raw = chat_json(
            "doctor_handoff_summary",
            patient_name=patient.get("name") or "Patient",
            patient_age=patient.get("age") or "unknown",
            diagnosis=clinical.get("diagnosis") or "unknown",
            comorbidities=", ".join(clinical.get("comorbidities") or []) or "unknown",
            medications=_summarize_meds(clinical),
            sdoh_summary=_summarize_sdoh(sdoh),
            care_plan=care_plan_str,
            escalations=_summarize_escalations(escalations),
            booking_context=_summarize_booking(proposal),
            conversation_history=transcript,
        )
    except Exception as e:
        log.error("handoff_summary: chat_json raised for %s: %s", patient_id, e)
        raw = {}

    if not isinstance(raw, dict) or not raw:
        log.info("handoff_summary: using deterministic fallback for %s", patient_id)
        return _normalize({}, fallback)

    return _normalize(raw, fallback)
