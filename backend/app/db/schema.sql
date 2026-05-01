-- CareLoop Supabase schema. Run once in Supabase SQL editor.

create extension if not exists "pgcrypto";

create table if not exists doctors (
  id uuid primary key default gen_random_uuid(),
  name text,
  email text,
  phone text
);

create table if not exists patients (
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

create table if not exists clinical_data (
  patient_id uuid primary key references patients(id) on delete cascade,
  diagnosis text,
  icd_codes text[],
  medications jsonb,
  comorbidities text[],
  discharge_date date,
  follow_up_date date
);

create table if not exists sdoh_profiles (
  patient_id uuid primary key references patients(id) on delete cascade,
  housing_risk text,
  transport_risk text,
  caregiver_risk text,
  literacy_level text,
  digital_comfort text,
  financial_risk text,
  language text
);

create table if not exists knowledge_graphs (
  patient_id uuid primary key references patients(id) on delete cascade,
  graph_json jsonb,
  created_at timestamptz default now()
);

create table if not exists care_plans (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id) on delete cascade,
  plan_json jsonb,
  reasoning_trace text,
  created_at timestamptz default now()
);

create table if not exists interactions (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id) on delete cascade,
  channel text,
  direction text,
  content text,
  classification text,
  agent_decision text,
  timestamp timestamptz default now()
);

create table if not exists escalations (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id) on delete cascade,
  severity text,
  brief text,
  status text default 'pending',
  doctor_action text,
  created_at timestamptz default now()
);

create table if not exists pharmacies (
  id uuid primary key default gen_random_uuid(),
  name text,
  distance_km numeric,
  eta_hours int,
  price_modifier numeric
);

create table if not exists medications_inventory (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id) on delete cascade,
  med_name text,
  count_remaining int,
  days_remaining int,
  last_refill_date date
);

create table if not exists pharmacy_orders (
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

create table if not exists prompts (
  key text primary key,
  version int default 1,
  template text,
  edited_by text,
  edited_at timestamptz default now()
);

create table if not exists reasoning_traces (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id) on delete cascade,
  agent_name text,
  observed jsonb,
  inferred jsonb,
  decided text,
  tools_called text[],
  timestamp timestamptz default now()
);

create index if not exists idx_interactions_patient on interactions(patient_id, timestamp desc);
create index if not exists idx_reasoning_patient on reasoning_traces(patient_id, timestamp desc);
create index if not exists idx_escalations_status on escalations(status, created_at desc);

-- Telehealth booking proposals: patient picks an open slot, doctor accepts/rejects.
create table if not exists slot_proposals (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid references patients(id) on delete cascade,
  escalation_id uuid references escalations(id) on delete set null,
  urgency text default 'today',
  proposed_slots jsonb,        -- [{iso, human, duration_min}, ...]
  chosen_slot jsonb,           -- {iso, human, duration_min} once patient picks
  jitsi_link text,
  calendar_link text,
  patient_status text default 'pending',   -- pending | chosen | cancelled
  doctor_status text default 'pending',    -- pending | accepted | rejected | rescheduled
  doctor_note text,
  -- AI handoff summary shown to the doctor before a paid telehealth consult.
  -- Built from the patient's structured records + latest 20 interactions.
  -- Stored separately on this row so the raw patient chat history stays clean.
  doctor_handoff_summary jsonb,
  created_at timestamptz default now(),
  patient_chose_at timestamptz,
  doctor_decided_at timestamptz
);

-- Idempotent column add for repos that already created slot_proposals.
alter table if exists slot_proposals
  add column if not exists doctor_handoff_summary jsonb;

create index if not exists idx_slot_proposals_patient on slot_proposals(patient_id, created_at desc);
create index if not exists idx_slot_proposals_doctor on slot_proposals(doctor_status, created_at desc);

-- 30-day post-discharge medication supply plan
create table if not exists medication_support_plans (
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

-- Phase-1 hot-path indexes (added for inbound message lookup + refill scans).
create index if not exists idx_patients_phone on patients(phone);
create index if not exists idx_pharmacy_orders_patient on pharmacy_orders(patient_id, created_at desc);
create index if not exists idx_med_supply_patient on medication_support_plans(patient_id, created_at desc);
create index if not exists idx_med_supply_status on medication_support_plans(status, next_refill_check_date);
create index if not exists idx_med_supply_program_end on medication_support_plans(program_end_date);

-- Idempotent column add for repos that already created pharmacy_orders without notes.
alter table if exists pharmacy_orders add column if not exists notes text;
-- Idempotent column add for delivery_status (separate from payment_status).
alter table if exists pharmacy_orders add column if not exists delivery_status text default 'pending';
