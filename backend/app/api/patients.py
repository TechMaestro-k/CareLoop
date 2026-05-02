"""Patient onboarding + listing + detail endpoints."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.graph import run_onboarding
from app.agents.state import empty_state
from app.config import settings
from app.db.client import safe_delete, safe_insert, safe_select

router = APIRouter(prefix="/patients", tags=["patients"])


def _compute_risk_score(patient_id: str) -> Optional[float]:
    """Read the most recent context_builder trace and extract risk_score."""
    rows = safe_select(
        "reasoning_traces",
        match={"patient_id": patient_id, "agent_name": "context_builder"},
        order=("timestamp", True),
        limit=1,
    )
    if not rows:
        return None
    inferred = rows[0].get("inferred") or {}
    rs = inferred.get("risk_score")
    if rs is None:
        return None
    try:
        return round(float(rs), 3)
    except (TypeError, ValueError):
        return None


class OnboardRequest(BaseModel):
    name: str
    age: int
    phone: str
    email: Optional[str] = None
    language: str = "en"
    channel_pref: str = "whatsapp_text"
    caregiver_phone: Optional[str] = None
    caregiver_email: Optional[str] = None
    discharge_text: str
    sdoh_responses: dict[str, Any] = Field(default_factory=dict)
    check_in_times_per_day: int = 3


def _find_duplicate(name: str, phone: str) -> dict[str, Any] | None:
    norm_phone = (phone or "").strip()
    norm_name = (name or "").strip()
    if norm_phone:
        rows = safe_select("patients", match={"phone": norm_phone}, limit=1)
        if rows:
            return rows[0]
    if norm_name:
        all_rows = safe_select("patients", limit=200)
        for r in all_rows:
            if (r.get("name") or "").strip().lower() == norm_name.lower():
                return r
    return None


@router.post("/onboard")
def onboard(req: OnboardRequest):
    if not settings.has_supabase:
        raise HTTPException(status_code=503, detail="Database not configured")
    existing = _find_duplicate(req.name, req.phone)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "duplicate_patient",
                "message": (
                    f"A patient named '{existing.get('name')}' with phone "
                    f"{existing.get('phone')} already exists. Open the existing record "
                    f"instead of re-onboarding."
                ),
                "existing_patient_id": existing.get("id"),
                "existing_name": existing.get("name"),
                "existing_phone": existing.get("phone"),
            },
        )
    row = safe_insert(
        "patients",
        {
            "name": req.name,
            "age": req.age,
            "phone": req.phone,
            "email": req.email,
            "language": req.language,
            "channel_pref": req.channel_pref,
            "caregiver_phone": req.caregiver_phone,
            "caregiver_email": req.caregiver_email or settings.caregiver_email_default,
        },
    )
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create patient row")
    pid = row["id"]
    state = empty_state()
    state["patient_id"] = pid
    state["raw_discharge_text"] = req.discharge_text
    state["sdoh_responses"] = req.sdoh_responses
    state["language"] = req.language
    state["channel"] = req.channel_pref
    state["triggered_by"] = "onboarding"
    state["check_in_times_per_day"] = max(1, min(10, req.check_in_times_per_day))
    state["patient_record"] = {**row}

    final_state = run_onboarding(state)

    return {
        "patient_id": pid,
        "risk_score": final_state.get("risk_score"),
        "care_plan": final_state.get("care_plan"),
        "knowledge_graph": final_state.get("knowledge_graph_json"),
    }


@router.get("")
def list_patients():
    rows = safe_select("patients", order=("created_at", True), limit=100)
    out = []
    for r in rows:
        pid = r["id"]
        sdoh_rows = safe_select("sdoh_profiles", match={"patient_id": pid}, limit=1)
        clin_rows = safe_select("clinical_data", match={"patient_id": pid}, limit=1)
        out.append(
            {
                **r,
                "diagnosis": clin_rows[0].get("diagnosis") if clin_rows else None,
                "sdoh": sdoh_rows[0] if sdoh_rows else None,
                "risk_score": _compute_risk_score(pid),
            }
        )
    return {"patients": out}


@router.get("/{patient_id}")
def get_patient(patient_id: str):
    rows = safe_select("patients", match={"id": patient_id}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="Patient not found")
    patient = rows[0]
    clin = safe_select("clinical_data", match={"patient_id": patient_id}, limit=1)
    sdoh = safe_select("sdoh_profiles", match={"patient_id": patient_id}, limit=1)
    kg = safe_select("knowledge_graphs", match={"patient_id": patient_id}, limit=1)
    plans = safe_select(
        "care_plans", match={"patient_id": patient_id}, order=("created_at", True), limit=5
    )
    interactions = safe_select(
        "interactions", match={"patient_id": patient_id}, order=("timestamp", True), limit=20
    )
    inventory = safe_select("medications_inventory", match={"patient_id": patient_id})
    escalations = safe_select(
        "escalations", match={"patient_id": patient_id}, order=("created_at", True), limit=10
    )
    return {
        "patient": {**patient, "risk_score": _compute_risk_score(patient_id)},
        "clinical": clin[0] if clin else None,
        "sdoh": sdoh[0] if sdoh else None,
        "knowledge_graph": kg[0].get("graph_json") if kg else None,
        "care_plans": plans,
        "interactions": interactions,
        "medications_inventory": inventory,
        "escalations": escalations,
    }


@router.delete("/{patient_id}")
def delete_patient(patient_id: str):
    rows = safe_select("patients", match={"id": patient_id}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="Patient not found")

    try:
        from app.scheduler.jobs import cancel_patient_jobs

        cancel_patient_jobs(patient_id)
    except Exception:
        pass

    deleted = safe_delete("patients", match={"id": patient_id})
    if deleted is None:
        raise HTTPException(status_code=500, detail="Failed to remove patient")
    return {"ok": True, "patient_id": patient_id}
