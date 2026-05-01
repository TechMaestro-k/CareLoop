-- =====================================================================
--  CareLoop  ·  HARD RESET + REINIT
--  Paste this whole file into Supabase SQL Editor and click "Run".
--  This will:
--    1. Drop every CareLoop table (data is wiped).
--    2. Recreate every table fresh from the canonical schema.
--    3. Add the doctor_handoff_summary column that was missing.
--    4. Recreate all indexes.
--  Idempotent: safe to run multiple times.
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---- 1. DROP everything (CASCADE handles foreign-key references) ----
drop table if exists medication_support_plans cascade;
drop table if exists slot_proposals          cascade;
drop table if exists reasoning_traces        cascade;
drop table if exists prompts                 cascade;
drop table if exists pharmacy_orders         cascade;
drop table if exists medications_inventory   cascade;
drop table if exists pharmacies              cascade;
drop table if exists escalations             cascade;
drop table if exists interactions            cascade;
drop table if exists care_plans              cascade;
drop table if exists knowledge_graphs        cascade;
drop table if exists sdoh_profiles           cascade;
drop table if exists clinical_data           cascade;
drop table if exists patients                cascade;
drop table if exists doctors                 cascade;

-- ---- 2. Recreate (mirrors backend/app/db/schema.sql exactly) ----
create table doctors (
  id uuid primary key default gen_random_uuid(),
  name text,
  email text,
  phone text
);

create table patients (
  id uuid primary key default gen_random_uuid(),
  name text,
  age int,
  phone text,
  email text,
  language text default 'en',
  channel_pref text default 'whatsapp_text',
  caregiver_phone text,
  caregiver_email text,
  doctor_id uuid references doctors(id),
  created_at timestamptz default now()
);

create table clinical_data (
  patient_id uuid primary key references patients(id) on delete cascade,
  diagnosis text,
  icd_codes text[],
  medications jsonb,
  comorbidities text[],
  discharge_date date,
  follow_up_date date
);

create table sdoh_profiles (
  patient_id uuid primary key references patients(id) on delete cascade,
  housing_risk text,
  transport_risk text,
  caregiver_risk text,
  literacy_level text,
  digital_comfort text,
  financial_risk text,
  language text
);

create table knowledge_graphs (
  patient_id uuid primary key references patients(id) on delete cascade,
  graph_json jsonb,
  created_at timestamptz default now()
);

create table care_plans (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id) on delete cascade,
  plan_json jsonb,
  reasoning_trace text,
  created_at timestamptz default now()
);

create table interactions (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id) on delete cascade,
  channel text,
  direction text,
  content text,
  classification text,
  agent_decision text,
  timestamp timestamptz default now()
);

create table escalations (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id) on delete cascade,
  severity text,
  brief text,
  status text default 'pending',
  doctor_action text,
  created_at timestamptz default now()
);

create table pharmacies (
  id uuid primary key default gen_random_uuid(),
  name text,
  distance_km numeric,
  eta_hours int,
  price_modifier numeric
);

create table medications_inventory (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id) on delete cascade,
  med_name text,
  count_remaining int,
  days_remaining int,
  last_refill_date date
);

create table pharmacy_orders (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id) on delete cascade,
  pharmacy_id uuid references pharmacies(id),
  items jsonb,
  total numeric,
  razorpay_link text,
  razorpay_payment_id text,
  payment_status text default 'pending',
  delivery_status text default 'pending',
  eta_hours int,
  notes text,
  created_at timestamptz default now(),
  delivered_at timestamptz
);

create table prompts (
  key text primary key,
  version int default 1,
  template text,
  edited_by text,
  edited_at timestamptz default now()
);

create table reasoning_traces (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id) on delete cascade,
  agent_name text,
  observed jsonb,
  inferred jsonb,
  decided text,
  tools_called text[],
  timestamp timestamptz default now()
);

-- Telehealth booking proposals
create table slot_proposals (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id) on delete cascade,
  escalation_id uuid references escalations(id) on delete set null,
  urgency text default 'today',
  proposed_slots jsonb,
  chosen_slot jsonb,
  jitsi_link text,
  calendar_link text,
  patient_status text default 'pending',
  doctor_status text default 'pending',
  doctor_note text,
  -- AI handoff summary shown to doctor before consult.
  doctor_handoff_summary jsonb,
  created_at timestamptz default now(),
  patient_chose_at timestamptz,
  doctor_decided_at timestamptz
);

-- 30-day post-discharge medication supply plan
create table medication_support_plans (
  id                      uuid primary key default gen_random_uuid(),
  patient_id              uuid references patients(id) on delete cascade,
  discharge_date          date not null,
  program_end_date        date not null,
  initial_supply_days     int,
  current_supply_end_date date,
  next_refill_check_date  date,
  auto_delivery_enabled   boolean default false,
  auto_delivery_consent   boolean default false,
  affordability_flag      boolean default false,
  supply_confidence       text default 'unknown',
  status                  text default 'setup_needed',
  created_at              timestamptz default now(),
  updated_at              timestamptz default now()
);

-- ---- 3. Indexes ----
create index idx_interactions_patient        on interactions(patient_id, timestamp desc);
create index idx_reasoning_patient           on reasoning_traces(patient_id, timestamp desc);
create index idx_escalations_status          on escalations(status, created_at desc);
create index idx_slot_proposals_patient      on slot_proposals(patient_id, created_at desc);
create index idx_slot_proposals_doctor       on slot_proposals(doctor_status, created_at desc);
create index idx_patients_phone              on patients(phone);
create index idx_pharmacy_orders_patient     on pharmacy_orders(patient_id, created_at desc);
create index idx_med_supply_patient          on medication_support_plans(patient_id, created_at desc);
create index idx_med_supply_status           on medication_support_plans(status, next_refill_check_date);
create index idx_med_supply_program_end      on medication_support_plans(program_end_date);

-- ---- 4. PostgREST schema cache reload (so the new column is visible immediately) ----
notify pgrst, 'reload schema';

-- Done. You should see "Success. No rows returned." Now hit POST /api/seed
-- (or use the reseed script) to populate demo data.
