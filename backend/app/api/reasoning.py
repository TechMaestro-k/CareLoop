from __future__ import annotations

from fastapi import APIRouter

from app.db.client import safe_select

router = APIRouter(prefix="/reasoning", tags=["reasoning"])


@router.get("/patient/{patient_id}")
def patient_traces(patient_id: str, limit: int = 25):
    rows = safe_select(
        "reasoning_traces",
        match={"patient_id": patient_id},
        order=("timestamp", True),
        limit=limit,
    )
    return {"traces": rows}


@router.get("/recent")
def recent_traces(limit: int = 50):
    rows = safe_select(
        "reasoning_traces", order=("timestamp", True), limit=limit
    )
    return {"traces": rows}
