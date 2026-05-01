from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.client import safe_select, safe_update

router = APIRouter(prefix="/doctor", tags=["doctor"])


@router.get("/escalations")
def list_escalations(status: str | None = None):
    match = {"status": status} if status else None
    rows = safe_select(
        "escalations", match=match, order=("created_at", True), limit=100
    )
    enriched = []
    for e in rows:
        prows = safe_select("patients", match={"id": e["patient_id"]}, limit=1)
        enriched.append({**e, "patient": prows[0] if prows else None})
    return {"escalations": enriched}


@router.get("/escalations/{esc_id}")
def get_escalation(esc_id: str):
    rows = safe_select("escalations", match={"id": esc_id}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="Not found")
    esc = rows[0]
    pid = esc["patient_id"]
    patient = safe_select("patients", match={"id": pid}, limit=1)
    clin = safe_select("clinical_data", match={"patient_id": pid}, limit=1)
    sdoh = safe_select("sdoh_profiles", match={"patient_id": pid}, limit=1)
    interactions = safe_select(
        "interactions", match={"patient_id": pid}, order=("timestamp", True), limit=15
    )
    traces = safe_select(
        "reasoning_traces", match={"patient_id": pid}, order=("timestamp", True), limit=10
    )
    return {
        "escalation": esc,
        "patient": patient[0] if patient else None,
        "clinical": clin[0] if clin else None,
        "sdoh": sdoh[0] if sdoh else None,
        "interactions": interactions,
        "reasoning_traces": traces,
    }


class ActionRequest(BaseModel):
    action: str
    note: str | None = None


@router.post("/escalations/{esc_id}/action")
def take_action(esc_id: str, req: ActionRequest):
    if req.action not in {"accept", "reject", "reschedule"}:
        raise HTTPException(status_code=400, detail="invalid action")
    status = "accepted" if req.action == "accept" else ("rejected" if req.action == "reject" else "rescheduled")
    res = safe_update(
        "escalations",
        match={"id": esc_id},
        values={"status": status, "doctor_action": req.note or req.action},
    )
    return {"ok": True, "status": status, "rows": res}
