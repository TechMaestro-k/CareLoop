# CareLoop — 5-minute demo script

## Setup (do this before demo)

1. Make sure both servers are running.
2. Open the home page → click **Load demo (Mrs. Sharma + 2 more)**. Wait ~30 seconds for all 3 patients to onboard (3 × Context Builder + 3 × Care Plan).
3. Refresh until you see all 3 in `/patients`.

## Demo — 5 minutes flat

### 0:00 — The problem (30 sec)

> "Hospitals lose ~20% of CHF patients to readmission within 30 days. The clinical advice isn't usually wrong — the *delivery* doesn't fit the patient. Mrs. Sharma is 68, lives alone in Jaipur, only speaks Hindi, and only uses WhatsApp voice. She just left the hospital after a heart-failure admit. Email reminders won't work. PDFs won't work. Apps won't work."

### 0:30 — Onboarding (1 min)

Click **Onboard** in the nav. The hero patient is pre-filled.

> "We feed two things: the discharge summary as free text, and her social context in plain language. The Context Builder agent extracts the clinical entities, classifies the SDOH risks, and builds her personal knowledge graph. The fused risk score is the join of clinical severity and SDOH burden."

(You don't need to actually re-onboard — point at the prefilled forms.)

### 1:30 — The knowledge graph (1 min)

Open `Patients → Mrs. Sharma → Knowledge Graph`.

> "Diagnosis on the left. Comorbidities and medications branch off. The orange nodes are her SDOH facts — `digital_comfort=low`, `caregiver_risk=high`, `financial_risk=high`. Watch how those edges land on routing decisions: `channel:whatsapp_voice`, `simplification:high`, `caregiver_loop:enabled`, `pharmacy:price_weighted`. The agent doesn't pick voice because we hardcoded it — it picks voice because the graph said so."

### 2:30 — The reasoning trace (45 sec)

Switch to **Reasoning Trace** tab.

> "Every agent step writes one of these: what it observed, what it inferred, what it decided, which tools it called. No black box — a doctor or auditor can replay every decision."

### 3:15 — Engagement live (1 min)

Switch to **Chat Simulator** tab.

Click *"Red: worsening"*.

> "She just sent: 'I can't breathe lying down, gained 3 kg.' Watch what happens." (Wait ~3 seconds.)
>
> The NLU model classifies it as RED. The KG cross-references CHF red flags. The Escalation agent drafts a clinical brief, books a telehealth slot, sends an email to the doctor, sends an email to her daughter, and replies to her in Hindi with the appointment link. All of this just happened — no human in the loop yet."

Show the chat reply with the RED badge.

### 4:15 — Doctor inbox (30 sec)

Click **Doctor Inbox** in nav.

> "Her case is at the top. Pre-summarized brief — symptoms, trend, relevant meds, SDOH context, suggested action, rationale. Doctor accepts in one click."

Click into it, hit **Accept**.

### 4:45 — Pharmacy + prompts (15 sec)

Open `Patients → Mrs. Sharma → Pharmacy`.

> "Separately, the Pharmacy agent saw two of her meds were running low. It picked Jan Aushadhi over Apollo because her financial_risk is high — and routed the payment link to her daughter, not her, because her digital_comfort is low. Razorpay test mode."

Open **Prompts** in nav. Pick `escalation_brief`.

> "And every prompt is editable from the UI. Saves go to the database, override the YAML, and take effect on the next call. Non-engineers can iterate on tone in seconds."

If you edit a YAML file on disk between runs, click **Force-reload cache**
in the top-right of the prompts page — that clears the in-process YAML +
resolved cache so the next agent call re-reads from disk without bouncing
the API.

## End

> "That's CareLoop. Four agents, one knowledge graph per patient, six editable prompts, every action explainable, and built around the social reality of the person — not just their diagnosis."
