"""Synthetic patients including the hero persona Mrs. Sharma."""
from __future__ import annotations

import logging
from typing import Any

from app.db.client import safe_insert, safe_select, safe_upsert

log = logging.getLogger(__name__)


HERO_PATIENT = {
    "name": "Mrs. Sharma",
    "age": 68,
    "phone": "+919999900001",
    "email": "sharma.ji.demo@example.com",
    "language": "hi",
    "channel_pref": "whatsapp_voice",
    "caregiver_phone": "+919999900002",
    "caregiver_email": "priya.daughter@example.com",
}

HERO_DISCHARGE_TEXT = """
Patient: Smt. Sharma, 68F, admitted 4 days for acute decompensated heart failure
on background of HFrEF (LVEF 32%). Diuretic optimization done. NYHA II at discharge.
ICD-10: I50.22, I25.10. Comorbidities: T2DM (HbA1c 7.8), Stage-3 CKD (eGFR 41), HTN.
Discharged on:
- Tab Metoprolol Succinate 25 mg OD x 30 days
- Tab Ramipril 2.5 mg OD x 30 days
- Tab Furosemide 40 mg BD x 30 days
- Tab Spironolactone 25 mg OD x 30 days
- Tab Atorvastatin 20 mg HS x 30 days
Discharge date: 2026-04-25. Follow-up cardiology OPD: 2026-05-09.
Daily weight monitoring; salt restriction 2g/day. Watch for >2 kg weight gain in 3 days,
worsening dyspnea, ankle edema, orthopnea.
""".strip()

HERO_SDOH = {
    "lives_alone": "yes, husband deceased, daughter Priya in Bangalore",
    "language": "Hindi only, comfortable speaking but reads slowly",
    "transport": "no own vehicle, depends on autorickshaw, finds long trips tiring",
    "literacy": "can sign her name, struggles with English prescriptions",
    "digital_comfort": "uses WhatsApp voice notes only, daughter set it up; cannot type comfortably",
    "income": "lives on late husband's pension, finds branded medicines expensive",
    "caregiver": "daughter calls every evening, no one in same city",
    "housing": "owns 2BHK flat ground floor, lift available, neighbour checks in twice a week",
}

ALT_PATIENT_2 = {
    "name": "Mr. Iyer",
    "age": 71,
    "phone": "+919999900011",
    "email": "iyer.demo@example.com",
    "language": "en",
    "channel_pref": "whatsapp_text",
    "caregiver_phone": "+919999900012",
    "caregiver_email": "iyer.son@example.com",
}
ALT_PATIENT_2_DISCHARGE = """
Patient: Mr. Iyer, 71M, admitted 3 days for COPD exacerbation. Nebulised bronchodilators,
short course oral steroids. Smoker, 30 pack-years. ICD-10: J44.1.
Discharged on:
- Tiotropium 18 mcg OD inhaler
- Salbutamol 100 mcg PRN inhaler
- Prednisolone 10 mg OD x 5 days taper
- Azithromycin 500 mg OD x 3 days
Follow-up pulmonology OPD: 2026-05-04.
""".strip()
ALT_PATIENT_2_SDOH = {
    "lives_alone": "no, lives with retired wife",
    "language": "English fluent",
    "transport": "owns car, son drives him",
    "literacy": "graduate, reads comfortably",
    "digital_comfort": "high, uses smartphone for banking",
    "income": "comfortable retirement",
    "caregiver": "wife at home, son nearby",
    "housing": "independent house, ground floor bedroom",
}

ALT_PATIENT_3 = {
    "name": "Mr. Khan",
    "age": 54,
    "phone": "+919999900021",
    "email": "khan.demo@example.com",
    "language": "hi",
    "channel_pref": "whatsapp_text",
    "caregiver_phone": "+919999900022",
    "caregiver_email": "khan.wife@example.com",
}
ALT_PATIENT_3_DISCHARGE = """
Patient: Mr. Khan, 54M, post-CABG day 5. Triple-vessel disease. Diabetic.
ICD-10: I25.10, Z95.1, E11.9.
Discharged on:
- Aspirin 75 mg OD
- Clopidogrel 75 mg OD x 6 months
- Atorvastatin 40 mg HS
- Metformin 500 mg BD
- Pantoprazole 40 mg OD
Follow-up CTVS OPD: 2026-05-12. Cardiac rehab to start week 3.
""".strip()
ALT_PATIENT_3_SDOH = {
    "lives_alone": "no, wife and two children",
    "language": "Hindi and basic English",
    "transport": "limited, uses bus",
    "literacy": "10th standard",
    "digital_comfort": "medium, uses WhatsApp text",
    "income": "tight budget after surgery, daily wage worker on rest",
    "caregiver": "wife full-time at home",
    "housing": "rented 1BHK third floor, no lift",
}


def _ensure_demo_doctor() -> str | None:
    rows = safe_select("doctors", match={"email": "doctor.demo@careloop.io"}, limit=1)
    if rows:
        return rows[0].get("id")
    inserted = safe_insert(
        "doctors",
        {"name": "Dr. Mehta (Demo)", "email": "doctor.demo@careloop.io", "phone": "+919999911111"},
    )
    return inserted.get("id") if inserted else None


def seed_inventory_low(patient_id: str):
    """Seed initial 10-day med supply for demo purposes (medications_inventory table)."""
    from datetime import date

    today = date.today().isoformat()
    for med in ["Metoprolol", "Furosemide"]:
        safe_insert(
            "medications_inventory",
            {
                "patient_id": patient_id,
                "med_name": med,
                "count_remaining": 10,
                "days_remaining": 10,
                "last_refill_date": today,
            },
        )


def run_seed() -> dict[str, Any]:
    """Idempotent seeding: creates demo doctor and 3 patients with discharge + SDOH."""
    from app.agents.graph import run_onboarding
    from app.agents.state import empty_state

    doctor_id = _ensure_demo_doctor()

    created = []
    for patient, discharge, sdoh in [
        (HERO_PATIENT, HERO_DISCHARGE_TEXT, HERO_SDOH),
        (ALT_PATIENT_2, ALT_PATIENT_2_DISCHARGE, ALT_PATIENT_2_SDOH),
        (ALT_PATIENT_3, ALT_PATIENT_3_DISCHARGE, ALT_PATIENT_3_SDOH),
    ]:
        existing = safe_select("patients", match={"phone": patient["phone"]}, limit=1)
        if existing:
            created.append({"id": existing[0].get("id"), "name": patient["name"], "skipped": True})
            continue
        row = safe_insert("patients", {**patient, "doctor_id": doctor_id})
        if not row:
            continue
        pid = row.get("id")
        if patient["name"].startswith("Mrs."):
            seed_inventory_low(pid)
        st = empty_state()
        st["patient_id"] = pid
        st["raw_discharge_text"] = discharge
        st["sdoh_responses"] = sdoh
        st["language"] = patient["language"]
        st["channel"] = patient["channel_pref"]
        st["patient_record"] = {**patient, "id": pid}
        st["triggered_by"] = "onboarding"
        try:
            run_onboarding(st)
        except Exception as e:
            log.error("Seed onboarding failed for %s: %s", patient["name"], e)
        created.append({"id": pid, "name": patient["name"], "skipped": False})

    return {"doctor_id": doctor_id, "patients": created}
