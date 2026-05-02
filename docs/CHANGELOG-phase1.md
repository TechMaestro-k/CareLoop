# Phase-1 Hardening Changelog

Eight sequential tasks executed against the `careloop/` MVP. After every task the
backend test suite (`cd careloop/careloop/backend && python3 -m pytest -q`) was
re-run. Tests started at **28 passing** and ended at **33 passing** (one new
agent-test file, no regressions).

## 1. DB indexes on hot lookups
- Added `idx_patients_phone` (covers Twilio inbound webhook lookup) and
  `idx_pharmacy_orders_patient` (covers refill cooldown check) to
  `app/db/schema.sql`.
- Pure schema change; no app-code edits, no test impact.

## 2. Voice synthesis honours the patient's language
- `care_plan_node` now defaults `plan["language"]` from
  `state["language"]` → `sdoh_profile["language"]` → `"en"` instead of
  silently defaulting to English.
- The `synthesize_sync(...)` call in `care_plan.py` and the `_maybe_voice`
  helper in `engagement.py` now both read `plan.get("language")` so Hindi,
  Tamil, Bengali patients actually hear their language back.

## 3. Single-page Doctor view with escalation deeplinks
- Collapsed the four doctor nav entries into a single **Doctor** link →
  `/doctor/calendar`. `/doctor` now redirects there.
- The calendar page gained a **Recent escalations** section that loads
  `listEscalations()` + `listProposals()` in parallel and links each row
  to `/booking/{id}` (if a slot proposal exists for that patient) or
  the legacy `/doctor/{id}` brief.

## 4. Demo cohort trimmed to 3 patients
- Removed `ALT_PATIENT_4` (Mrs. Iyer / Tamil) and `ALT_PATIENT_5`
  (Mr. Kumar) constants and their loop entries from the seed script.
  The demo now ships with exactly the three patients the script walks
  through — no orphan rows clutter the dashboard.

## 5. Refill flow moved off the hot path
- Removed the inline `pharmacy_node(...)` call that used to run on every
  inbound WhatsApp message. The same removal also dropped the dangling
  `low_meds` reference in `_persist_reasoning`.
- `app/scheduler/jobs.py` now exposes `schedule_refill_scan()`,
  `check_refills_for_all_patients()`, and `trigger_refill_for_patient()`.
  `main.py` startup wires the cron scan.
- `app/api/messages.py` accepts a `BackgroundTasks` argument, detects
  refill keywords (`refill`, `medicine`, `meds`, `prescription`) via
  `_is_refill_request`, and queues a single background refill check —
  returning `refill_queued: true` in the response so the UI can show a
  toast. The simulate-shape test was updated to pass a `BackgroundTasks()`.

## 6. Live prompt cache + force-reload
- `app/prompts/registry.py` gained two small in-process dicts
  (`_yaml_cache`, `_resolved_cache`) plus `clear_prompt_cache()`. YAML
  files are now read at most once per process; saves through
  `save_prompt_override` invalidate the resolved entry automatically.
- New endpoint `POST /api/prompts/_reload` busts both caches and re-lists.
- The `/prompts` page got a **Force-reload cache** button (top-right)
  that calls the new endpoint and surfaces a status line ("Cache cleared
  (N YAML, M resolved). Next agent call re-reads from disk.").
- Documented in `docs/demo-script.md`.

## 7. Insights dashboard
- Added `app/api/insights.py` with `GET /api/insights/summary` returning
  rolling 7-day counters (patients enrolled, escalations by severity,
  open escalations, refills sent, refills paid) plus chart data for
  severity and high-risk SDOH dimensions. Computed in-process from
  `safe_select` so an unreachable Supabase yields zeros instead of 500s.
- Wired through `main.py`.
- New `/insights` page (Next.js client component) with four stat cards
  and two `recharts` `BarChart`s (severity, SDOH dimensions). Refresh
  button re-pulls the summary.
- Added `recharts@2.12.7` to `frontend/package.json`. Added `Insights`
  to the top nav with the `BarChart3` icon.

## 8. Per-agent test coverage
- New file `backend/tests/test_agents.py` with five focused, offline
  tests — one per agent — using `monkeypatch` to stub LLM and DB calls:
  - `test_context_builder_agent_builds_kg_and_fuses_risk` — verifies KG
    construction, risk-score fusion, language propagation, and that all
    three upsert tables are written.
  - `test_care_plan_agent_defaults_language_and_sends_welcome` — verifies
    plan-key defaults (channel, cadence, simplification) and that the
    welcome WhatsApp is dispatched.
  - `test_engagement_agent_green_path_does_not_escalate` — verifies a
    GREEN classification produces a patient reply but never creates a
    slot proposal nor pings caregiver/doctor.
  - `test_pharmacy_agent_routes_to_caregiver_when_digital_comfort_low` —
    verifies the digital-comfort-aware routing rule.
  - `test_orchestrator_runs_onboarding_then_care_plan_in_order` —
    rebuilds the onboarding LangGraph with stub nodes and asserts the
    `ctx → cp` execution order.

## Final state
- Backend tests: **33 passed, 0 failed** (was 28 at baseline).
- Frontend deps: `recharts` added; nav now has six entries
  (Home / Onboard / Patients / Doctor / Chat Sim / Insights / Prompts).
- Out of scope and explicitly NOT touched: gTTS swap to edge-tts,
  LangGraph wiring shape, YAML prompt content, `reasoning_traces` table,
  Docker/containerization.
