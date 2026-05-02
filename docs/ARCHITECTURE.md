# CareLoop — Architecture

## 1. Why agentic + SDOH

Most readmission prevention pilots fail not because the clinical advice is wrong, but because the *delivery* doesn't match the patient. A 68-year-old who only uses WhatsApp voice notes won't read an email. A daily-wage worker won't pay for branded medicines. CareLoop treats those facts (Social Determinants of Health) as routing inputs, not afterthoughts.

The system has four cooperating agents, each with its own prompt, model temperature, and tools — orchestrated through LangGraph but autonomous within their nodes.

## 2. Data model

13 Postgres tables in Supabase. Important ones:

- `patients` — demographics + channel preference + caregiver contacts.
- `clinical_data` — extracted diagnosis, ICD codes, meds, comorbidities, follow-up date.
- `sdoh_profiles` — 6 risk dimensions (housing / transport / caregiver / literacy / digital / financial) + language.
- `knowledge_graphs` — JSON serialization of the per-patient NetworkX DiGraph.
- `care_plans` — versioned care plan JSON + reasoning trace.
- `interactions` — every inbound + outbound message with classification.
- `medications_inventory` — running count for each med.
- `pharmacy_orders` — refill orders + Razorpay link + payment status.
- `escalations` — pending / accepted / rejected items in the doctor's inbox.
- `reasoning_traces` — every agent step (observed → inferred → decided → tools called).
- `prompts` — DB-overridable prompt templates (UI saves go here).
- `pharmacies` — three seeded options trading off price, ETA, and distance.
- `doctors` — minimal record per onboarding clinician.

All schemas live in `backend/app/db/schema.sql`.

## 3. Agent flow

```
                 ┌─────────────────────┐
discharge text ──▶│  Context Builder    │── builds KG, fused risk score
SDOH free-text   │  (Llama 3.3 70B)    │
                 └──────────┬──────────┘
                            ▼
                 ┌─────────────────────┐
                 │     Care Plan       │── welcome WhatsApp + caregiver email +
                 │  (Llama 3.3 70B)    │   APScheduler daily cron @ 09:00 IST
                 └──────────┬──────────┘
                            ▼
                 ┌─────────────────────┐         ┌─────────────────┐
   inbound msg ──▶│ Engagement (NLU)   │────────▶│   Pharmacy       │
                 │ (Llama 3.1 8B Inst) │  low    │  (Llama 3.3 70B) │
                 │ → green/amber/red   │  stock  │  Razorpay link   │
                 └────┬─────┬─────┬───┘         └─────────────────┘
                      │     │     │
                      │     │     └── RED: brief + telehealth + doctor email + caregiver
                      │     └──────── AMBER: caregiver email + 2x/day frequency
                      └────────────── GREEN: reinforcement only
```

LangGraph wraps the four nodes; the conditional flows live inside each node so the graph stays declarative.

## 4. Knowledge graph

`backend/app/tools/kg.py` builds a per-patient `nx.DiGraph` with five node kinds: `diagnosis`, `comorbidity`, `medication`, `sdoh`, `red_flag`, plus seven `route` decision nodes (channel:whatsapp_voice, simplification:high, caregiver_loop:enabled, telehealth:preferred, pharmacy:price_weighted, etc.).

Edges are weighted (0–1) and labelled (`treated_with`, `watch_for`, `comorbid_with`, plus 7 SDOH→route rules like `lives_alone`, `low_income`, `voice_for_literacy`).

The graph is serialized to JSON and stored, then rendered on the frontend with `react-force-graph-2d`. The same JSON is fed back into prompts as `kg_highlights` (red flags + preferred routes + node/edge counts) so the LLM gets a structured view without re-reading the whole graph.

## 5. Prompt registry

Six prompts in `backend/app/prompts/templates/`:

| Key                       | Model            | Temp | Output            |
| ------------------------- | ---------------- | ---- | ----------------- |
| `clinical_ner`            | llama-3.3-70b    | 0.1  | JSON object       |
| `sdoh_classifier`         | llama-3.1-8b     | 0.2  | JSON object       |
| `care_plan_generator`     | llama-3.3-70b    | 0.4  | JSON object       |
| `nlu_symptom_classifier`  | llama-3.1-8b     | 0.2  | JSON object       |
| `escalation_brief`        | llama-3.3-70b    | 0.3  | JSON object       |
| `pharmacy_order`          | llama-3.3-70b    | 0.5  | JSON object       |

The registry first looks for a row in the `prompts` table — if found, that template overrides the YAML. The /prompts UI saves to that table, so non-engineers can iterate live.

All Groq calls go through `chat_json()` which sets `response_format={"type": "json_object"}` and returns `{}` on any failure (callers degrade gracefully).

## 6. Mock-first integrations

`whatsapp.py`, `email_tool.py`, `razorpay_tool.py`, `voice.py` — each is **one function** with the same signature in mock and live mode. Setting `USE_MOCK_*=true` (or simply leaving the credentials blank) flips the tool into mock mode while keeping the call site unchanged. Mocks log realistic-looking payloads so the demo still demonstrates flow.

## 7. Reasoning trace

Every agent persists a `reasoning_traces` row with four fields: `observed` (raw inputs), `inferred` (LLM outputs + KG hits), `decided` (one-line summary), `tools_called` (every tool invoked). This is what the doctor inbox and patient detail page render — no black boxes.

## 8. Scheduler

APScheduler runs in-process inside FastAPI. `schedule_daily_checkin(patient_id, time)` registers a cron job per patient at the time set in their care plan. Render's free tier sleeps after 15 min of inactivity, so for production we'd move to a stateful host or a separate worker; for the hackathon we accept that limitation.

## 9. Why these specific models

- **Llama 3.3 70B Versatile** for reasoning (care plan, escalation brief, pharmacy selection) — best Groq option for structured medical reasoning under cost.
- **Llama 3.1 8B Instant** for NLU (symptom classification, SDOH categorization) — sub-second responses for the inbound triage path.

Both are accessible through Groq's hosted endpoint with one API key.

## 10. Trade-offs we made

- **No vector store / no RAG.** All clinical knowledge is encoded in the prompt templates and a tiny in-code red-flag dictionary. For a 30-day post-discharge window this is enough; adding RAG would slow demos and add ops surface.
- **No HIPAA / DPDP.** Demo only. Production would need encryption at rest, audit logging, RBAC, and a BAA with each vendor.
- **No retraining loop.** Doctor accept/reject actions are stored but not yet fed back into prompts or a fine-tuning loop.
