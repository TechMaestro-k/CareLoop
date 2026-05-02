# CareLoop

> An SDOH-aware agentic AI for post-discharge readmission prevention. Built for the Veersa hackathon, April 2026.

CareLoop monitors patients for 30 days after they leave the hospital — in their own language, on their own phone — and routes the right action to the right person at the right time. It treats social determinants of health (transport, literacy, digital comfort, finances, caregiver presence) as first-class inputs alongside the clinical picture.

Hero persona: **Mrs. Sharma**, 68, Jaipur, Hindi-only, post-CHF discharge.

---

## Stack (locked)

| Layer        | Tech                                                    |
| ------------ | ------------------------------------------------------- |
| Backend      | FastAPI · Python 3.11.9                                 |
| Orchestration| LangGraph + NetworkX                                    |
| LLM          | Groq — Llama 3.3 70B (reasoning) + Llama 3.1 8B (NLU)   |
| Frontend     | Next.js 14 · shadcn/ui · Tailwind                       |
| DB           | Supabase Postgres                                       |
| Voice (Hi)   | edge-tts                                                |
| Messaging    | Twilio WhatsApp Sandbox (mock-first)                    |
| Email        | Gmail SMTP via app password (mock-first)                |
| Payments     | Razorpay test mode (mock-first)                         |
| Scheduling   | APScheduler                                             |
| Deploy       | Vercel (frontend) · Render free (backend) · Supabase    |

No Docker. No Streamlit.

---

## The four agents

1. **Context Builder** — extracts ICD codes, meds, comorbidities from a free-text discharge note; classifies SDOH responses into 6 risk dimensions; assembles a per-patient knowledge graph (NetworkX) and computes a fused risk score.
2. **Care Plan** — generates a tailored, simplified plan in the patient's language; sends a welcome WhatsApp; emails caregiver if loop is enabled; schedules daily APScheduler check-in.
3. **Engagement & Escalation** — daily prompt + inbound triage. Classifies green / amber / red. On red: drafts a clinical brief, books telehealth, alerts doctor + caregiver, replies to the patient.
4. **Pharmacy** — detects low refills, picks a pharmacy weighted by SDOH (financial vs. transport vs. literacy), creates a Razorpay link, routes to patient or caregiver depending on digital comfort.

---

## Quickstart

### 1. Database

Open Supabase SQL editor → paste `backend/app/db/schema.sql` → run.

### 2. Secrets

Copy `.env.example` → `.env` and fill the values, OR set them as environment variables in Replit/Render.

```
GROQ_API_KEY=...
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_KEY=...
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
GMAIL_USER=...
GMAIL_APP_PASSWORD=...
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
DOCTOR_EMAIL=...
CAREGIVER_EMAIL_DEFAULT=...
```

Anything missing flips that integration into mock mode (still produces realistic output).

### 3. Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Health check: <http://localhost:8000/api/healthz>
Interactive docs: <http://localhost:8000/docs>

### 4. Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

By default the Next.js dev server proxies `/api/*` → `http://localhost:8000`. To point at a different backend:

```bash
NEXT_PUBLIC_API_BASE=https://your-render.onrender.com npm run dev
```

### 5. Seed the demo

Click **Load demo (Mrs. Sharma + 2 more)** on the home page, or `POST /api/admin/seed`.

---

## 60-second demo path

1. **Home** → click "Load demo". Three patients are created and onboarded.
2. **Patients → Mrs. Sharma**. Open the **Knowledge Graph** tab — show how SDOH nodes link to routing decisions (voice channel, caregiver loop, low-cost pharmacy).
3. Open the **Reasoning Trace** tab — explain how every decision is observed → inferred → decided → tools called.
4. Open the **Chat Simulator** tab — click *"Red: worsening"*. Watch the agent classify, draft a brief, book telehealth, and alert the caregiver.
5. **Doctor Inbox** — show the new escalation. Click in, accept it.
6. **Pharmacy** tab back on Mrs. Sharma — show the auto-generated refill order and Razorpay link. Click *Mark paid (sim)* and watch the patient get a thank-you note.
7. **Prompts** page — open `escalation_brief`, edit one line, save. Run the chat sim again — note the new tone.

---

## Deploying

### Backend → Render free tier

- New Web Service → connect repo → root `backend/`.
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Set env vars from `.env.example`.

### Frontend → Vercel

- Import repo → root `frontend/`.
- Set env var `NEXT_PUBLIC_API_BASE=https://<render-url>`.

### Twilio + Razorpay webhooks

- **Twilio Sandbox**: set inbound webhook to `https://<render-url>/api/messages/inbound`.
- **Razorpay**: in dashboard set webhook to `https://<render-url>/api/razorpay/webhook` and reuse the `RAZORPAY_WEBHOOK_SECRET` value.

---

## Project layout

```
careloop/
├── backend/
│   ├── app/
│   │   ├── agents/        # context_builder, care_plan, engagement, pharmacy, graph
│   │   ├── api/           # FastAPI routers
│   │   ├── db/            # Supabase client + schema.sql
│   │   ├── prompts/       # YAML templates + DB-overridable registry
│   │   ├── scheduler/     # APScheduler daily check-ins
│   │   ├── seed/          # Mrs. Sharma + 2 more, 3 pharmacies
│   │   ├── tools/         # llm, whatsapp, email, voice, razorpay, calendar, kg
│   │   ├── config.py
│   │   └── main.py
│   ├── tests/             # pytest smoke tests
│   ├── requirements.txt
│   ├── runtime.txt
│   └── Procfile
├── frontend/
│   ├── app/               # Next.js App Router pages
│   ├── components/        # KGViewer, ReasoningTrace, SDOHForm, DischargeForm, ChatPreview, ui/*
│   ├── lib/               # api.ts, utils.ts
│   ├── package.json
│   ├── next.config.js
│   ├── tailwind.config.ts
│   └── tsconfig.json
└── docs/
    ├── ARCHITECTURE.md
    ├── demo-script.md
    └── prompt-explanations.md
```

---

## Tests

```bash
cd backend
pytest -q
```

Smoke tests verify config loads, all 6 prompts parse, KG builds, and every external tool's mock returns a sane shape.

---

## License

MIT — for hackathon use. Not a medical device.
