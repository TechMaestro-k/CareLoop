"""Insights endpoint — small read-only aggregates for the dashboard.

Everything is computed in-process from `safe_select` so it stays honest
when Supabase is unreachable (returns zeros instead of crashing).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter

from app.db.client import safe_select

router = APIRouter(prefix="/insights", tags=["insights"])


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


@router.get("/summary")
def summary() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    patients = safe_select("patients", columns="id,name")
    escalations = safe_select(
        "escalations",
        columns="id,severity,status,created_at",
        order=("created_at", True),
        limit=500,
    )
    sdoh = safe_select(
        "sdoh_profiles",
        columns="financial_risk,housing_risk,transport_risk,caregiver_risk,digital_comfort",
    )

    sev_week: Counter[str] = Counter()
    open_escalations = 0
    for row in escalations:
        ts = _parse_ts(row.get("created_at"))
        sev = (row.get("severity") or "").upper()
        if ts and ts >= week_ago and sev in {"RED", "AMBER", "GREEN"}:
            sev_week[sev] += 1
        if (row.get("status") or "").lower() == "pending":
            open_escalations += 1

    sdoh_high: Counter[str] = Counter()
    for row in sdoh:
        for dim in (
            "financial_risk",
            "housing_risk",
            "transport_risk",
            "caregiver_risk",
        ):
            if (row.get(dim) or "").lower() == "high":
                sdoh_high[dim] += 1
        if (row.get("digital_comfort") or "").lower() == "low":
            sdoh_high["digital_comfort_low"] += 1

    severity_chart = [
        {"severity": "RED", "count": sev_week.get("RED", 0)},
        {"severity": "AMBER", "count": sev_week.get("AMBER", 0)},
        {"severity": "GREEN", "count": sev_week.get("GREEN", 0)},
    ]
    sdoh_chart = [
        {"dimension": k, "count": v}
        for k, v in sorted(sdoh_high.items(), key=lambda kv: -kv[1])
    ]

    return {
        "window_days": 7,
        "generated_at": now.isoformat(),
        "totals": {
            "patients": len(patients),
            "escalations_week": sum(sev_week.values()),
            "escalations_open": open_escalations,
        },
        "severity_chart": severity_chart,
        "sdoh_chart": sdoh_chart,
    }
