# CareLoop API Reference (frontend-consumed)

This document covers **only** the endpoints actually called by the CareLoop web frontend (`frontend/src/lib/api.ts` and consuming pages). Internal/integration endpoints (Twilio webhooks, Razorpay webhook, message simulator, email previews, healthz, separate doctor-escalation action route) are out of scope here.

**Base URLs**
- Local: `http://localhost:8000`
- Production: `https://www.careloops.tech`

All endpoints are mounted under `/api/*`. Default `Content-Type` is `application/json` for both request and response. Errors come back as `{ "detail": ... }` where `detail` is either a string or a structured object (noted per endpoint).

**Pages that consume each group**
| Section | Frontend pages |
|---|---|
| Patients | `OnboardPage`, `PatientsPage`, `PatientDetailPage` |
| Doctor escalations | `DashboardPage`, `DoctorInboxPage`, `EscalationDetailPage` |
| Booking | `DoctorInboxPage`, `EscalationDetailPage`, `PatientBookingPage` |
| Prompts | `PromptsPage` |
| Insights | `DashboardPage`, `InsightsPage` |

---

## 1. Patients

### 1.1 `POST /api/patients/onboard`
Run the full onboarding pipeline (Context Builder → Care Plan), send the welcome WhatsApp + caregiver email, and register check-in cron jobs.

**Used by:** `OnboardPage` (after Discharge + SDOH steps).

**Request body**
```json
{
  "name": "Mrs. Sharma",
  "age": 68,
  "phone": "+919876543210",
  "email": "sharma@example.com",
  "language": "en",
  "channel_pref": "whatsapp_text",
  "caregiver_phone": "+919876543211",
  "caregiver_email": "son@example.com",
  "discharge_text": "68F discharged after acute decompensated CHF, EF 35%...",
  "sdoh_responses": {
    "lives_alone": "yes",
    "transport": "depends on son",
    "literacy": "Hindi only, low literacy"
  },
  "check_in_times_per_day": 3
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | |
| `age` | integer | yes | Frontend coerces empty string to `0` before sending |
| `phone` | string | yes | E.164 format |
| `email` | string \| null | no | |
| `language` | string | no | `"en"`, `"hi"`, `"bn"`, `"ta"`, `"te"`, `"mr"`. Default `"en"` |
| `channel_pref` | string | no | `"whatsapp_text"` or `"whatsapp_voice"`. Default `"whatsapp_text"` |
| `caregiver_phone` | string \| null | no | |
| `caregiver_email` | string \| null | no | Falls back to server default if omitted |
| `discharge_text` | string | yes | Raw discharge note from the EMR |
| `sdoh_responses` | object | no | Plain-language SDOH answers; values are strings |
| `check_in_times_per_day` | integer | no | Default `3`. Server clamps to `[1, 10]` |

**Response — `200 OK`**
```json
{
  "patient_id": "uuid",
  "risk_score": 0.78,
  "care_plan": { "...": "..." },
  "knowledge_graph": { "nodes": [], "links": [] }
}
```

The frontend only reads `patient_id` and `risk_score`; the other fields are returned for completeness.

**Errors**
| Status | Body | When |
|---|---|---|
| `409` | `{ "detail": { "error": "duplicate_patient", "message": "...", "existing_patient_id": "uuid", "existing_name": "...", "existing_phone": "..." } }` | A patient with the same phone (or same case-insensitive name) already exists. The Onboard page surfaces an "Open existing patient" CTA using `existing_patient_id`. |
| `503` | `{ "detail": "Database not configured" }` | Supabase env vars missing |
| `500` | `{ "detail": "Failed to create patient row" }` | Insert failed |

---

### 1.2 `GET /api/patients`
List up to 100 patients with their latest risk score, diagnosis, and SDOH summary.

**Used by:** `PatientsPage`.

**Request:** no params, no body.

**Response — `200 OK`**
```json
{
  "patients": [
    {
      "id": "uuid",
      "name": "Mrs. Sharma",
      "age": 68,
      "phone": "+919876543210",
      "email": "sharma@example.com",
      "language": "en",
      "channel_pref": "whatsapp_text",
      "caregiver_phone": "+919876543211",
      "caregiver_email": "son@example.com",
      "created_at": "2026-04-30T10:00:00Z",
      "diagnosis": "CHF",
      "sdoh": {
        "patient_id": "uuid",
        "literacy_level": "low",
        "financial_risk": "high",
        "housing_risk": "low",
        "transport_risk": "high",
        "caregiver_risk": "high",
        "digital_comfort": "low"
      },
      "risk_score": 0.78
    }
  ]
}
```

`diagnosis`, `sdoh`, and `risk_score` may be `null` if the corresponding pipeline rows haven't landed yet. The patient cards on the Patients page render SDOH chips only when fields equal specific values (`financial_risk === "high"`, `caregiver_risk === "high"`, `transport_risk === "high"`, `digital_comfort === "low"`, `literacy_level === "low"`).

---

### 1.3 `GET /api/patients/{patient_id}`
Full patient detail: clinical, SDOH, knowledge graph, care plans, interactions, medication inventory, escalations.

**Used by:** `PatientDetailPage`.

**Path params**
- `patient_id` — UUID of the patient.

**Response — `200 OK`**
```json
{
  "patient": {
    "id": "uuid",
    "name": "Mrs. Sharma",
    "age": 68,
    "phone": "+91...",
    "email": "...",
    "language": "en",
    "channel_pref": "whatsapp_text",
    "caregiver_phone": "...",
    "caregiver_email": "...",
    "created_at": "...",
    "risk_score": 0.78
  },
  "clinical": {
    "patient_id": "uuid",
    "diagnosis": "CHF",
    "icd_codes": ["I50.9"],
    "medications": [{ "name": "Furosemide", "dose": "40mg", "frequency": "once daily" }],
    "...": "..."
  },
  "sdoh": {
    "patient_id": "uuid",
    "literacy_level": "low",
    "financial_risk": "high",
    "housing_risk": "low",
    "transport_risk": "high",
    "caregiver_risk": "high",
    "digital_comfort": "low"
  },
  "knowledge_graph": {
    "nodes": [{ "id": "...", "label": "...", "type": "..." }],
    "links": [{ "source": "...", "target": "...", "label": "..." }]
  },
  "care_plans": [
    {
      "id": "uuid",
      "patient_id": "uuid",
      "plan_json": { "channel": "whatsapp_text", "...": "..." },
      "created_at": "..."
    }
  ],
  "interactions": [
    {
      "id": "uuid",
      "patient_id": "uuid",
      "direction": "outbound",
      "content": "...",
      "classification": "green",
      "timestamp": "..."
    }
  ],
  "medications_inventory": [
    {
      "id": "uuid",
      "patient_id": "uuid",
      "med_name": "Furosemide",
      "days_remaining": 8
    }
  ],
  "escalations": [
    {
      "id": "uuid",
      "patient_id": "uuid",
      "severity": "amber",
      "status": "pending",
      "brief": "...",
      "created_at": "..."
    }
  ]
}
```

Any of `clinical`, `sdoh`, `knowledge_graph` may be `null` if the corresponding row hasn't been created. `care_plans`, `interactions`, `medications_inventory`, and `escalations` are always arrays (possibly empty).

The page consumes:
- `patient.name`, `patient.age`, `patient.risk_score`
- `care_plans[0].plan_json` for the latest plan
- `interactions[].classification` to derive the latest severity badge
- `escalations[].status === "pending"` for the open count

**Errors**
| Status | Body | When |
|---|---|---|
| `404` | `{ "detail": "Patient not found" }` | No row for that ID |

---

### 1.4 `DELETE /api/patients/{patient_id}`
Remove the patient and cancel any scheduled APScheduler check-in jobs.

**Used by:** `PatientDetailPage` (the trash button).

**Response — `200 OK`**
```json
{ "ok": true, "patient_id": "uuid" }
```

**Errors**
| Status | Body | When |
|---|---|---|
| `404` | `{ "detail": "Patient not found" }` | |
| `500` | `{ "detail": "Failed to remove patient" }` | Delete failed |

---

## 2. Doctor escalations

### 2.1 `GET /api/doctor/escalations`
List escalations, optionally filtered by status. The doctor inbox calls this with `status=pending`.

**Used by:** `DashboardPage`, `DoctorInboxPage`.

**Query params**
| Param | Type | Notes |
|---|---|---|
| `status` | string \| omitted | Typically `"pending"`. When omitted, returns all statuses. |

**Response — `200 OK`**
```json
{
  "escalations": [
    {
      "id": "uuid",
      "patient_id": "uuid",
      "severity": "red",
      "brief": "Patient: Mrs. Sharma\nSeverity: RED\nPatient message: \"...\"\n...",
      "status": "pending",
      "doctor_action": null,
      "created_at": "...",
      "patient": {
        "id": "uuid",
        "name": "Mrs. Sharma",
        "phone": "+91...",
        "...": "..."
      }
    }
  ]
}
```

`patient` is the joined patients row and may be `null` if the patient was deleted.

---

### 2.2 `GET /api/doctor/escalations/{esc_id}`
Full escalation detail with patient context.

**Used by:** `EscalationDetailPage`.

**Response — `200 OK`**
```json
{
  "escalation": {
    "id": "uuid",
    "patient_id": "uuid",
    "severity": "red",
    "brief": "...",
    "status": "pending",
    "doctor_action": null,
    "created_at": "..."
  },
  "patient": {
    "id": "uuid",
    "name": "Mrs. Sharma",
    "...": "..."
  },
  "clinical": { "...": "..." },
  "sdoh": { "...": "..." },
  "interactions": [
    {
      "id": "uuid",
      "direction": "outbound",
      "content": "...",
      "timestamp": "..."
    }
  ]
}
```

`patient`, `clinical`, `sdoh` may be `null` if the underlying row is missing. `interactions` is always an array.

**Errors**
| Status | Body | When |
|---|---|---|
| `404` | `{ "detail": "Not found" }` | |

---

## 3. Booking

The booking lifecycle the frontend drives:

```
agent creates proposal
    ↓
GET /api/booking/{id}                ← PatientBookingPage loads
POST /api/booking/{id}/select        ← patient picks a slot, gets payment link
POST /api/booking/{id}/mark-paid     ← demo bypass (or Razorpay webhook in prod)
POST /api/booking/{id}/decision      ← doctor accepts; gated on payment.status === "paid"
POST /api/booking/{id}/complete      ← doctor marks confirmed booking complete
```

### 3.1 `GET /api/booking`
List slot proposals — used to drive the doctor inbox queues (awaiting decision, confirmed, awaiting patient).

**Used by:** `DoctorInboxPage`, `EscalationDetailPage`.

**Query params**
| Param | Type | Notes |
|---|---|---|
| `patient_status` | string \| omitted | e.g. `"pending"`, `"chosen"` |
| `doctor_status` | string \| omitted | e.g. `"pending"`, `"accepted"`, `"completed"`, `"rejected"`, `"rescheduled"` |
| `limit` | integer \| omitted | Default `50` |

The frontend always calls this with no params.

**Response — `200 OK`**
```json
{
  "proposals": [
    {
      "id": "uuid",
      "patient_id": "uuid",
      "escalation_id": "uuid",
      "urgency": "red",
      "proposed_slots": [
        { "iso": "2026-04-30T15:00:00Z", "human": "Tomorrow 3 PM", "duration_min": 20 }
      ],
      "chosen_slot": null,
      "patient_status": "pending",
      "doctor_status": "pending",
      "patient_chose_at": null,
      "doctor_decided_at": null,
      "doctor_note": null,
      "jitsi_link": null,
      "calendar_link": null,
      "created_at": "...",
      "patient": {
        "id": "uuid",
        "name": "Mrs. Sharma",
        "phone": "+91...",
        "caregiver_phone": "+91...",
        "caregiver_email": "..."
      }
    }
  ]
}
```

`patient_status` values seen by the UI: `"pending"`, `"chosen"`. `doctor_status` values: `"pending"`, `"accepted"`, `"rejected"`, `"rescheduled"`, `"completed"`. Once the patient has picked a slot, `chosen_slot` becomes a populated object — see `chosen_slot` shape in 3.3.

---

### 3.2 `GET /api/booking/{proposal_id}`
Patient-facing slot picker data. Lazily generates and caches a doctor handoff summary.

**Used by:** `PatientBookingPage` (initial load) and `DoctorInboxPage` (to fetch the AI handoff summary for cards that don't already have one inline).

**Response — `200 OK`**
```json
{
  "proposal": {
    "id": "uuid",
    "patient_id": "uuid",
    "proposed_slots": [
      { "iso": "2026-04-30T15:00:00Z", "human": "Tomorrow 3 PM", "duration_min": 20 }
    ],
    "chosen_slot": null,
    "patient_status": "pending",
    "doctor_status": "pending",
    "jitsi_link": null,
    "calendar_link": null,
    "...": "(same shape as in 3.1)"
  },
  "patient": {
    "id": "uuid",
    "name": "Mrs. Sharma",
    "...": "..."
  },
  "doctor_handoff_summary": {
    "summary": "Short paragraph summarising the case for the doctor.",
    "symptoms_reported": ["dyspnea", "leg swelling"],
    "medication_adherence": "good",
    "risk_signals": ["..."],
    "sdoh_context": ["lives alone", "low digital comfort"],
    "agent_actions_so_far": ["..."],
    "doctor_focus": ["..."]
  }
}
```

`doctor_handoff_summary` may be `null` if the summary hasn't been generated yet. `patient` may be `null` if the patient was deleted.

**Errors**
| Status | Body | When |
|---|---|---|
| `404` | `{ "detail": "proposal not found" }` | |

---

### 3.3 `POST /api/booking/{proposal_id}/select`
Patient picks one of the proposed slots. Server creates a Razorpay payment link, stores it on `chosen_slot.payment`, WhatsApps the link to the patient. **The doctor is not notified yet** — only after payment lands.

**Used by:** `PatientBookingPage` (the "Pick" buttons).

**Request body**
```json
{ "slot_iso": "2026-04-30T15:00:00Z" }
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `slot_iso` | string | yes | Must exactly match an `iso` value from `proposed_slots` |

**Response — `200 OK`**
```json
{
  "ok": true,
  "chosen_slot": {
    "iso": "2026-04-30T15:00:00Z",
    "human": "Tomorrow 3 PM",
    "duration_min": 20,
    "payment": {
      "status": "pending",
      "amount_usd": 100,
      "currency": "USD",
      "link": "https://rzp.io/i/abc",
      "link_id": "plink_...",
      "reference_id": "slot_<proposal_id>",
      "mock": false
    }
  },
  "payment": {
    "status": "pending",
    "amount_usd": 100,
    "currency": "USD",
    "link": "https://rzp.io/i/abc",
    "link_id": "plink_...",
    "reference_id": "slot_<proposal_id>",
    "mock": false
  }
}
```

`payment.status` values: `"pending"`, `"paid"`, `"failed"`, `"refunded"`. `payment.mock === true` indicates Razorpay is not actually connected (demo/dev environments) — the patient page surfaces a "Mark payment received" button in that case. `amount_usd` is a misnamed field that holds the configured fee in whatever `currency` is set (defaults: `100` and `"USD"`).

The frontend ignores the response body after a successful call and re-fetches via `GET /api/booking/{id}` to render the updated state.

**Errors**
| Status | Body | When |
|---|---|---|
| `400` | `{ "detail": "slot_iso does not match a proposed slot" }` | |
| `404` | `{ "detail": "proposal not found" }` | |
| `409` | `{ "detail": "slot already paid" }` | The patient has already picked and paid |

---

### 3.4 `POST /api/booking/{proposal_id}/mark-paid`
Manual payment confirmation. The Razorpay webhook is the production path; this is the demo bypass and is exposed in the UI as a "Mark payment received" button.

**Used by:** `PatientBookingPage` (when `payment.mock === true`), `DoctorInboxPage` (admin escape hatch).

**Request:** no body.

**Response — `200 OK`**
```json
{ "ok": true, "proposal_id": "uuid", "status": "paid" }
```

If the booking was already paid:
```json
{ "ok": true, "already_paid": true, "proposal_id": "uuid" }
```

The frontend ignores the body and re-fetches.

**Errors**
| Status | Body | When |
|---|---|---|
| `400` | `{ "detail": "no slot chosen yet" }` | Patient hasn't picked a slot |
| `404` | `{ "detail": "proposal not found" }` | |

---

### 3.5 `POST /api/booking/{proposal_id}/decision`
Doctor accepts, rejects, or reschedules. **Accept is gated on `chosen_slot.payment.status === "paid"`.**

**Used by:** `DoctorInboxPage`.

**Request body**
```json
{ "action": "accept", "note": "optional doctor note" }
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `action` | string | yes | `"accept"`, `"reject"`, or `"reschedule"` |
| `note` | string \| null | no | |

**Response — `200 OK` (accept, success)**

On accept, the server generates a Jitsi link + calendar invite via `confirm_booking`, WhatsApps the join link to patient + caregiver, emails doctor + caregiver with the join link / calendar invite / handoff summary, and resolves all of the patient's pending escalations as `accepted`.

```json
{
  "ok": true,
  "status": "accepted",
  "booking": {
    "link": "https://meet.jit.si/...",
    "calendar_link": "https://calendar.google.com/...",
    "slot_human": "Tomorrow 3 PM"
  },
  "doctor_handoff_summary": {
    "summary": "...",
    "symptoms_reported": ["..."],
    "medication_adherence": "good",
    "risk_signals": ["..."],
    "sdoh_context": ["..."],
    "agent_actions_so_far": ["..."],
    "doctor_focus": ["..."]
  }
}
```

**Response — `200 OK` (reject / reschedule)**
```json
{ "ok": true, "status": "rejected" }
```
or
```json
{ "ok": true, "status": "rescheduled" }
```

**Errors**
| Status | Body | When |
|---|---|---|
| `400` | `{ "detail": "invalid action" }` | `action` not in the allowed set |
| `400` | `{ "detail": "patient has not chosen a slot yet" }` | `chosen_slot` is null |
| `402` | `{ "detail": { "message": "Patient has not paid the consult fee yet.", "hint": "Mark payment as received once it has been verified.", "payment_status": "pending" } }` | Accept attempted before payment |
| `404` | `{ "detail": "proposal not found" }` | |

The Doctor Inbox specifically reads `body.detail.message` and `body.detail.hint` from the `402` response and shows them inline.

---

### 3.6 `POST /api/booking/{proposal_id}/complete`
Mark a previously-accepted booking as completed (removes it from the active inbox).

**Used by:** `DoctorInboxPage`.

**Request:** no body.

**Response — `200 OK`**
```json
{ "ok": true, "proposal_id": "uuid", "status": "completed" }
```

**Errors**
| Status | Body | When |
|---|---|---|
| `400` | `{ "detail": "only accepted bookings can be marked complete" }` | `doctor_status` is not `"accepted"` |
| `404` | `{ "detail": "proposal not found" }` | |

---

## 4. Prompts

### 4.1 `GET /api/prompts`
List all 9 agent prompt templates with their resolved metadata. The registry checks the `prompts` Postgres table first — if a row exists for a key, it overrides the YAML user template (system prompt and model are not editable).

**Used by:** `PromptsPage`.

**Response — `200 OK`**
```json
{
  "prompts": [
    {
      "key": "engagement_reply",
      "model": "llama-3.1-8b-instant",
      "temperature": 0.4,
      "system": "You are CareLoop's engagement agent...",
      "user": "Patient said: {{message}}\n...",
      "description": "Generate a calm, on-brand reply...",
      "overridden": false
    }
  ]
}
```

| Field | Notes |
|---|---|
| `key` | Stable identifier — one of: `clinical_ner`, `sdoh_classifier`, `care_plan_generator`, `nlu_symptom_classifier`, `engagement_reply`, `daily_checkin`, `escalation_brief`, `pharmacy_order`, `doctor_handoff_summary` |
| `system` | Read-only; rendered as `<pre>` |
| `user` | The editable user template — what the textarea binds to |
| `overridden` | `true` when the row in Postgres has replaced the YAML's user template |

---

### 4.2 `GET /api/prompts/{key}`
Read one prompt with full resolved values (DB override merged on top of YAML).

**Used by:** the `api.getPrompt` helper (defined in `api.ts`; not currently called from any page, but exposed for future use).

**Response — `200 OK`**
```json
{
  "system": "...",
  "user": "...",
  "model": "llama-3.1-8b-instant",
  "temperature": 0.4,
  "response_format": null,
  "description": "...",
  "_overridden": false
}
```

**Errors**
| Status | Body | When |
|---|---|---|
| `404` | `{ "detail": "prompt not found" }` | Unknown key |

---

### 4.3 `PUT /api/prompts/{key}`
Save an override for the user template. The system prompt and model are not editable.

**Used by:** `PromptsPage` (Save button).

**Request body**
```json
{ "template": "Patient said: {{message}}\n...", "edited_by": "ui" }
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `template` | string | yes | Replaces the YAML user template |
| `edited_by` | string | no | The frontend always sends `"ui"` |

**Response — `200 OK`**
```json
{ "ok": true, "key": "engagement_reply" }
```

**Errors**
| Status | Body | When |
|---|---|---|
| `404` | `{ "detail": "prompt not found" }` | Unknown key |
| `500` | `{ "detail": "save failed" }` | DB write failed |

---

### 4.4 `POST /api/prompts/_reload`
Force-clear the in-process prompt cache (YAML and resolved layers) and re-list everything. Used after editing YAML on disk or pasting a DB override directly.

**Used by:** `PromptsPage` ("Force-reload cache" button).

**Request:** no body.

**Response — `200 OK`**
```json
{
  "ok": true,
  "cleared": {
    "yaml_cleared": 9,
    "resolved_cleared": 9
  },
  "prompts": [
    { "key": "...", "model": "...", "temperature": 0.4, "system": "...", "user": "...", "description": "...", "overridden": false }
  ]
}
```

`cleared.yaml_cleared` and `cleared.resolved_cleared` are how many entries each cache had before being purged. The Prompts page surfaces both numbers in a status toast.

---

## 5. Insights

### 5.1 `GET /api/insights/summary`
7-day rollup for the dashboard: total patients, escalations this week, open escalations, severity distribution, top SDOH risks. Computed in-process from `safe_select`; returns zeros when Supabase is unreachable instead of erroring.

**Used by:** `DashboardPage`, `InsightsPage`.

**Response — `200 OK`**
```json
{
  "window_days": 7,
  "generated_at": "2026-04-30T12:00:00+00:00",
  "totals": {
    "patients": 12,
    "escalations_week": 5,
    "escalations_open": 2
  },
  "severity_chart": [
    { "severity": "RED", "count": 1 },
    { "severity": "AMBER", "count": 3 },
    { "severity": "GREEN", "count": 1 }
  ],
  "sdoh_chart": [
    { "dimension": "financial_risk", "count": 6 },
    { "dimension": "digital_comfort_low", "count": 4 },
    { "dimension": "transport_risk", "count": 3 },
    { "dimension": "caregiver_risk", "count": 2 },
    { "dimension": "housing_risk", "count": 0 }
  ]
}
```

| Field | Notes |
|---|---|
| `severity_chart` | Always 3 entries in the order RED → AMBER → GREEN. Frontend filters out zero-count rows before plotting. |
| `sdoh_chart` | Sorted by `count` descending. `dimension` is one of: `financial_risk`, `housing_risk`, `transport_risk`, `caregiver_risk`, `digital_comfort_low`. The frontend maps these keys to human labels before display. |

No error path — always returns `200`.

---

## Appendix — request/response conventions

- **Empty bodies on POST.** `mark-paid` and `complete` accept no body. Sending `{}` is safe; sending nothing is also safe. The frontend's `http()` helper sets `Content-Type: application/json` even for body-less POSTs — this is fine for FastAPI.
- **Error shape.** All errors come back as `{ "detail": ... }`. `detail` is sometimes a string (`"Patient not found"`), sometimes an object (`409 duplicate_patient`, `402 payment required`). The frontend's `ApiError` class extracts `body.detail.message || body.detail` for the human-readable message.
- **Auth.** None. The current frontend does not send any auth headers. (When auth is added, `frontend/src/lib/api.ts` is the single place to wire it in.)
- **CORS / base URL.** Configured via `VITE_API_BASE` at build time. Empty string means "same origin" (default for the bundled SPA served by FastAPI).
