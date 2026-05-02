# Prompt explanations

Six prompts power CareLoop. Each lives at `backend/app/prompts/templates/<key>.yaml` and is overridable from the `/prompts` UI (overrides are stored in the `prompts` Supabase table).

---

## 1. `clinical_ner` — discharge → structured

- **Model:** `llama-3.3-70b-versatile` · **Temp:** 0.1
- **Input:** `discharge_text` (free text from a hospital summary)
- **Output JSON:**

```json
{
  "diagnosis": "Heart Failure (HFrEF)",
  "icd_codes": ["I50.22", "I25.10"],
  "comorbidities": ["T2DM", "Stage-3 CKD", "HTN"],
  "medications": [{"name": "Metoprolol", "dose": "25 mg", "frequency": "OD", "duration_days": 30}],
  "discharge_date": "2026-04-25",
  "follow_up_date": "2026-05-09",
  "clinical_severity": 0.7
}
```

- **Why low temp:** factual extraction. We want the same input to map to the same JSON every time.

## 2. `sdoh_classifier` — narrative → 6 risk dimensions

- **Model:** `llama-3.1-8b-instant` · **Temp:** 0.2
- **Input:** `sdoh_responses` (a dict of plain-English answers to ~8 questions)
- **Output JSON:**

```json
{
  "housing_risk": "low",
  "transport_risk": "high",
  "caregiver_risk": "high",
  "literacy_level": "low",
  "digital_comfort": "low",
  "financial_risk": "high",
  "language": "hi",
  "sdoh_aggregate": 0.78
}
```

- **Why 8B:** the classification rules are simple; speed matters more than depth here.

## 3. `care_plan_generator` — KG + risk → tailored plan

- **Model:** `llama-3.3-70b-versatile` · **Temp:** 0.4
- **Inputs:** `diagnosis`, `medications`, `comorbidities`, `sdoh_profile`, `risk_score`, `kg_highlights`
- **Output JSON:**

```json
{
  "channel": "whatsapp_voice",
  "language": "hi",
  "simplification_level": "high",
  "check_in_cadence": "daily",
  "check_in_time": "09:00",
  "caregiver_loop_enabled": true,
  "red_flag_symptoms": ["weight gain >2kg in 3 days", "shortness of breath at rest", ...],
  "medication_schedule": [{"med": "Metoprolol", "time": "08:00", "instruction": "..."}],
  "reasoning": "<one short paragraph the agent wrote about why these choices>"
}
```

- **Why slightly higher temp:** the simplified Hindi/English copy benefits from a little flexibility; the structural fields are still constrained by the schema.

## 4. `nlu_symptom_classifier` — inbound message → severity

- **Model:** `llama-3.1-8b-instant` · **Temp:** 0.2
- **Inputs:** `diagnosis`, `red_flag_symptoms`, `message`
- **Output JSON:**

```json
{
  "severity": "red",
  "symptoms": ["dyspnea at rest", "weight gain"],
  "medication_adherence_signal": "unclear",
  "rationale": "Reports inability to lie flat + 3kg gain — both CHF red flags."
}
```

- **Why 8B:** every inbound WhatsApp goes through this. Latency is critical.

## 5. `escalation_brief` — RED → clinician summary

- **Model:** `llama-3.3-70b-versatile` · **Temp:** 0.3
- **Inputs:** patient + clinical context + the inbound message + recent trend + SDOH one-liner
- **Output JSON:**

```json
{
  "headline": "68F, post-CHF, NYHA II → III suspected. Worsening dyspnea + 3kg/3d.",
  "symptoms_today": ["orthopnea", "weight gain 3kg/3d", "ankle swelling"],
  "trend_vs_prior_checkins": "Yesterday GREEN, day before GREEN. Sudden worsening.",
  "relevant_meds": ["Furosemide 40 mg BD", "Spironolactone 25 mg OD"],
  "sdoh_factors_to_know": "Lives alone, low literacy, no transport. Daughter remote.",
  "suggested_action": "Telehealth in next 4h; consider escalating diuretic and same-day weight repeat.",
  "rationale": "Acute CHF decompensation pattern. SDOH precludes ER visit without caregiver coordination."
}
```

## 6. `pharmacy_order` — refill → patient-facing copy

- **Model:** `llama-3.3-70b-versatile` · **Temp:** 0.5
- **Inputs:** `patient_name`, `language`, `simplification_level`, `pharmacy_name`, `eta_hours`, `items_table`, `total`, `selection_reason`
- **Output JSON:**

```json
{
  "body": "नमस्ते Sharma ji 🙏 Metoprolol और Furosemide का refill तैयार है. कुल ₹420. 24 घंटे में Jan Aushadhi से घर पहुँच जाएगा. Payment के लिए: {PAY_LINK}",
  "caregiver_note": "Mom's monthly refill auto-arranged. Lower-cost generic via Jan Aushadhi (24h delivery)."
}
```

- The `{PAY_LINK}` placeholder is replaced server-side after the Razorpay link is created — never trust the LLM with the URL itself.

---

## Editing prompts safely

The `/prompts` page lets you edit only the **user template**. The system prompt and model are baked into the YAML and cannot be changed from the UI — this is intentional, to keep the JSON schema contract stable.

If you want to evolve the schema itself, edit the YAML file directly and bump the version note in `description:`.
