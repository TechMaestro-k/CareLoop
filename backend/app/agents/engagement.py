"""Agent 3: Engagement & Escalation.

Inbound flow:
  patient sends WhatsApp text or voice → /messages/inbound (or /simulate)
  → engagement_node:
       1. NLU classify (severity / confidence / needs_clarification)
       2. If needs_clarification or low confidence → ask back, exit
       3. If RED → create slot proposal (no payment yet),
                   send patient picker URL,
                   send doctor a redacted heads-up (severity + raw symptoms only,
                   NO disease name, NO suggested clinical action),
                   send caregiver an urgent heads-up.
       4. If AMBER → give 1-2 concrete safe steps via LLM, alert caregiver.
       5. If GREEN → light reinforcement via LLM (only if patient actually
                     reported wellness; otherwise the LLM continues the
                     conversation naturally).
       6. Always: every send_whatsapp / send_email also gets appended to
                  state["outgoing_messages"] / state["outgoing_emails"] so the
                  /simulate endpoint can return the actual transcript to the UI.

Outbound voice: when the patient's channel_pref is "whatsapp_voice", the
reply text is also synthesized via gTTS and attached as media so the patient
hears the message — same as the cron daily check-in path.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.agents.state import PatientState
from app.api.booking import create_proposal_from_agent
from app.config import settings
from app.db.client import safe_insert, safe_select
from app.tools import kg as kg_tools
from app.tools.calendar_tool import propose_slots
from app.tools.email_tool import send_email
from app.tools.llm import chat_json, chat_text
from app.tools.voice import public_audio_url, synthesize_sync
from app.tools.whatsapp import send_whatsapp

log = logging.getLogger(__name__)


# ---------------- DB helpers ----------------

def _persist_reasoning(patient_id, observed, inferred, decided, tools):
    safe_insert(
        "reasoning_traces",
        {
            "patient_id": patient_id,
            "agent_name": "engagement",
            "observed": observed,
            "inferred": inferred,
            "decided": decided,
            "tools_called": tools,
        },
    )


def _patient_record(patient_id):
    rows = safe_select("patients", match={"id": patient_id}, limit=1)
    return rows[0] if rows else {}


def _latest_care_plan(patient_id):
    rows = safe_select("care_plans", match={"patient_id": patient_id}, order=("created_at", True), limit=1)
    return rows[0].get("plan_json", {}) if rows else {}


def _latest_clinical(patient_id):
    rows = safe_select("clinical_data", match={"patient_id": patient_id}, limit=1)
    return rows[0] if rows else {}


def _recent_interactions(patient_id, limit=8):
    return safe_select("interactions", match={"patient_id": patient_id}, order=("timestamp", True), limit=limit)


def _format_conversation_history(patient_id: str, *, limit: int = 8) -> str:
    """Build a short transcript of the last few WhatsApp turns for this
    patient and format it as `langchain_core` messages, then render it
    as a flat string the prompt template can consume.

    This is the chat-memory layer: every LLM call (NLU classifier + reply
    writer) sees the recent dialogue so a "no" answer to "any breathing
    trouble?" is interpreted as a denial, not as a new symptom.
    """
    rows = _recent_interactions(patient_id, limit=limit) or []
    if not rows:
        return "(no prior conversation)"

    # rows come back newest-first because of `order=(timestamp, True)`;
    # we want oldest-first for the LLM to read the conversation top-down.
    rows = list(reversed(rows))

    try:
        from langchain_core.messages import AIMessage, HumanMessage
        msgs = []
        for r in rows:
            content = (r.get("content") or "").strip()
            if not content:
                continue
            direction = r.get("direction") or ""
            if direction.startswith("inbound"):
                msgs.append(HumanMessage(content=content))
            else:
                msgs.append(AIMessage(content=content))
        return "\n".join(
            f"{'Patient' if m.__class__.__name__ == 'HumanMessage' else 'CareLoop'}: {m.content}"
            for m in msgs
        ) or "(no prior conversation)"
    except Exception as e:
        log.warning("history formatting fallback: %s", e)
        # Fallback formatting if langchain_core import fails for any reason
        lines = []
        for r in rows:
            content = (r.get("content") or "").strip()
            if not content:
                continue
            who = "Patient" if (r.get("direction") or "").startswith("inbound") else "CareLoop"
            lines.append(f"{who}: {content}")
        return "\n".join(lines) or "(no prior conversation)"


# ---------------- Outgoing collectors ----------------
# Every WhatsApp / email send also goes into state so the simulate endpoint
# can echo back exactly what was sent. The chat-simulator UI uses this to
# render the real conversation instead of a debug string.

def _send_wa(state: PatientState, *, to: str, body: str, kind: str, media_url: Optional[str] = None) -> dict:
    res = send_whatsapp(to, body, media_url=media_url)
    state.setdefault("outgoing_messages", []).append({
        "to": kind,                # "patient" | "doctor" | "caregiver"
        "phone": to,
        "text": body,
        "media_url": media_url,
        "ok": bool(res.get("ok")),
        "mock": bool(res.get("mock")),
    })
    return res


def _send_em(state: PatientState, *, to: str, subject: str, text: str, html: Optional[str], kind: str) -> dict:
    res = send_email(to, subject, text, html=html)
    state.setdefault("outgoing_emails", []).append({
        "to": kind,
        "address": to,
        "subject": subject,
        "ok": bool(res.get("ok")),
        "mock": bool(res.get("mock")),
    })
    return res


# ---------------- Reply generation (LLM) ----------------

def _count_outbound_questions(patient_id: str, *, limit: int = 8) -> int:
    """Count how many follow-up questions CareLoop has already asked the
    patient in the recent conversation. Used to stop the LLM from asking
    a question on every single turn — past 1–2 questions, we wrap up.
    """
    rows = _recent_interactions(patient_id, limit=limit) or []
    n = 0
    for r in rows:
        if (r.get("direction") or "").startswith("outbound"):
            content = r.get("content") or ""
            if "?" in content:
                n += 1
    return n


def _llm_reply(
    *,
    patient_name: str,
    message: str,
    severity: str,
    classification: dict,
    plan: dict,
    conversation_history: str = "(no prior conversation)",
    prior_questions_asked: int = 0,
) -> str:
    """Ask the LLM for a contextual WhatsApp reply. Falls back to a safe
    minimal English line if the LLM is unavailable."""
    text = chat_text(
        "engagement_reply",
        patient_name=patient_name or "there",
        message=message,
        severity=severity,
        confidence=classification.get("confidence", ""),
        symptoms=", ".join(classification.get("symptoms", []) or []) or "none reported",
        needs_clarification=classification.get("needs_clarification", False),
        clarifying_question=classification.get("clarifying_question") or "",
        red_flag_symptoms=", ".join(plan.get("red_flag_symptoms", []) or []) or "none",
        conversation_history=conversation_history,
        prior_questions_asked=prior_questions_asked,
    )
    text = (text or "").strip().strip('"').strip()
    if text:
        return text
    # Safe English fallback per severity
    if severity == "red":
        return (
            "Thanks for letting me know — I've shared this with your doctor and "
            "we're arranging a video visit. You'll get a link shortly. If "
            "breathing gets very hard or chest pain worsens, call 911 immediately."
        )
    if severity == "amber":
        return (
            "Got it — I've noted what you said. Please rest, sip water, and take "
            "your next dose on time. If anything gets worse, message me right away."
        )
    if severity == "clarify":
        q = classification.get("clarifying_question") or "Can you tell me a little more about how you're feeling?"
        return q
    # green / unknown
    return (
        f"Hi {patient_name or 'there'} — checking in. How are you feeling today? "
        "Any breathing trouble, swelling, weight change, or missed doses?"
    )


# ---------------- Standardized WhatsApp formatting ----------------

def _patient_msg(body: str) -> str:
    """One consistent envelope for everything we send the patient."""
    return f"🩺 CareLoop\n{body.strip()}"


def _patient_red_picker(body_intro: str, picker_url: str, slots: list[dict]) -> str:
    sample = " · ".join(s["human"] for s in (slots or [])[:3])
    cta = f"Pick a time that works:\n{picker_url}" if picker_url else "Pick a time that works."
    suffix = f"\n\nAvailable: {sample}" if sample else ""
    return _patient_msg(f"{body_intro}\n\n{cta}{suffix}")


def _doctor_msg(*, name: str, severity: str, raw_message: str, symptoms_list: list[str], picker_url: str) -> str:
    """REDACTED doctor heads-up.

    Per the user's instruction: do NOT name a disease, do NOT push a
    clinical action label. Show the doctor only:
      - severity bucket
      - patient identifier
      - exactly what the patient said
      - the symptoms NLU detected (their own descriptive words)
      - the slot picker URL so the doctor knows where to confirm later
    """
    sym = ", ".join(symptoms_list or []) or "(none specifically labelled)"
    sev_tag = {"red": "🚨 RED", "amber": "🟠 AMBER", "green": "🟢 GREEN"}.get(severity, severity.upper())
    body = (
        f"Patient: {name}\n"
        f"Severity (auto-triage only): {sev_tag}\n\n"
        f"Patient message: \"{raw_message}\"\n"
        f"Symptoms reported: {sym}\n\n"
        f"Patient is choosing a video slot. You confirm at:\n{picker_url}"
    )
    return f"🩺 CareLoop · {sev_tag}\n{body}"


def _caregiver_red_msg(name: str, raw_message: str, picker_url: str) -> str:
    return _patient_msg(
        f"Urgent — {name} just messaged us with something we want you to know about.\n"
        f"What they said: \"{raw_message}\"\n\n"
        f"A doctor has been notified and {name} is choosing a video slot now.\n"
        f"Please call {name} and stay close to your phone."
    )


def _amber_caregiver_msg(name: str, raw_message: str, symptoms: list[str]) -> str:
    sym = ", ".join(symptoms or []) or "(unspecified)"
    return _patient_msg(
        f"AMBER alert for {name}.\n"
        f"What they said: \"{raw_message}\"\n"
        f"Symptoms: {sym}\n\n"
        f"We're checking in twice today. Please give {name} a call when you can."
    )


# ---------------- Email rendering (English only, no diagnosis names) ----------------

_BTN_PRIMARY = (
    "background:#dc2626;color:#ffffff;padding:12px 22px;border-radius:8px;"
    "text-decoration:none;font-weight:600;display:inline-block;font-family:Arial,sans-serif;"
)
_BADGE = {
    "red": "background:#dc2626;color:#fff;",
    "amber": "background:#d97706;color:#fff;",
    "green": "background:#059669;color:#fff;",
}


def _badge_html(severity: str) -> str:
    style = _BADGE.get(severity, _BADGE["amber"])
    return (
        f'<span style="{style}padding:4px 10px;border-radius:999px;'
        f'font-size:11px;font-weight:700;letter-spacing:0.06em;'
        f'text-transform:uppercase;font-family:Arial,sans-serif;">{severity}</span>'
    )


def _shell_html(*, title: str, severity: str, body_html: str) -> str:
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;color:#0f172a;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(15,23,42,0.08);">
        <tr><td style="padding:20px 24px;border-bottom:1px solid #e2e8f0;">
          <table width="100%"><tr>
            <td style="font-size:14px;color:#64748b;font-weight:700;letter-spacing:0.04em;">CARELOOP</td>
            <td align="right">{_badge_html(severity)}</td>
          </tr></table>
          <div style="margin-top:10px;font-size:18px;font-weight:700;line-height:1.3;">{title}</div>
        </td></tr>
        <tr><td style="padding:20px 24px;font-size:14px;line-height:1.55;">{body_html}</td></tr>
        <tr><td style="padding:14px 24px;background:#f8fafc;border-top:1px solid #e2e8f0;font-size:11px;color:#64748b;">
          Sent automatically by CareLoop &middot; post-discharge care companion.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _doctor_email(*, name: str, severity: str, raw_message: str, symptoms: list[str], picker_url: str) -> dict:
    """Doctor email — REDACTED. Severity + the patient's own words only.
    No disease label, no AI-suggested clinical action.
    """
    sym = ", ".join(symptoms or []) or "(none specifically labelled)"
    text = (
        f"CareLoop heads-up — severity {severity.upper()}.\n\n"
        f"Patient: {name}\n"
        f"Patient message: \"{raw_message}\"\n"
        f"Symptoms (auto-extracted from their words): {sym}\n\n"
        f"Patient is choosing a video slot. Confirm here:\n{picker_url}\n"
    )
    body_html = (
        f'<p style="margin:0 0 14px;">Severity: {_badge_html(severity)}</p>'
        f'<p style="margin:0 0 6px;color:#64748b;">{name}</p>'
        f'<blockquote style="margin:0 0 16px;padding:10px 14px;background:#fee2e2;'
        f'border-left:3px solid #dc2626;font-style:italic;">"{raw_message}"</blockquote>'
        f'<p style="margin:0 0 6px;"><strong>Symptoms reported:</strong> {sym}</p>'
        f'<p style="margin:14px 0 0;color:#64748b;font-size:12px;">'
        f'No diagnosis or clinical action is suggested by CareLoop — this is a triage heads-up only.</p>'
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:18px 0;"><tr>'
        f'<td><a href="{picker_url}" style="{_BTN_PRIMARY}">Open booking page</a></td>'
        f'</tr></table>'
    )
    html = _shell_html(title=f"Patient escalation · {severity.upper()}", severity=severity, body_html=body_html)
    return {"text": text, "html": html}


def _caregiver_red_email(*, name: str, raw_message: str, picker_url: str) -> dict:
    text = (
        f"Urgent — CareLoop has flagged {name} to a doctor.\n\n"
        f"What they said: \"{raw_message}\"\n\n"
        f"{name} is choosing a video slot now. Once they pick and pay the consult fee, "
        f"the doctor confirms and we send the video link.\n"
        f"Please call {name} and stay close to your phone.\n"
    )
    body_html = (
        f'<p style="margin:0 0 14px;font-size:15px;">'
        f'CareLoop has just flagged <strong>{name}</strong> to the doctor.</p>'
        f'<blockquote style="margin:0 0 16px;padding:10px 14px;background:#fee2e2;'
        f'border-left:3px solid #dc2626;font-style:italic;">"{raw_message}"</blockquote>'
        f'<p>{name} is choosing a video slot now. Please call them and stay close to your phone.</p>'
    )
    html = _shell_html(title=f"Urgent — {name}", severity="red", body_html=body_html)
    return {"text": text, "html": html}


def _amber_caregiver_email(*, name: str, raw_message: str, symptoms: list[str]) -> dict:
    sym = ", ".join(symptoms or []) or "(unspecified)"
    text = (
        f"AMBER alert from CareLoop.\n\n"
        f"{name} reported: \"{raw_message}\"\n"
        f"Symptoms: {sym}\n\n"
        f"We've doubled the check-in cadence for today. Please call when you can.\n"
    )
    body_html = (
        f'<p style="margin:0 0 12px;">{name} sent us a message we want you to know about.</p>'
        f'<blockquote style="margin:0 0 16px;padding:10px 14px;background:#fef3c7;'
        f'border-left:3px solid #d97706;font-style:italic;">"{raw_message}"</blockquote>'
        f'<p><strong>Symptoms detected:</strong> {sym}</p>'
        f'<p style="margin:16px 0 0;">We\'ve <strong>doubled the check-in frequency</strong> for today. '
        f'Please give {name} a call when you have a moment.</p>'
    )
    html = _shell_html(title=f"AMBER alert · {name}", severity="amber", body_html=body_html)
    return {"text": text, "html": html}


# ---------------- Voice helper ----------------

def _maybe_voice(text: str, *, plan: dict, patient: dict) -> Optional[str]:
    """Return a public audio URL if the patient prefers voice WhatsApp, else None."""
    channel = (plan.get("channel") or patient.get("channel_pref") or "").strip()
    if channel != "whatsapp_voice":
        return None
    # Honor the care plan's language code so the voice note actually
    # matches the patient's preferred language (Hindi, Tamil, Bengali…).
    audio = synthesize_sync(text, language=plan.get("language") or "en")
    if not audio:
        return None
    url = public_audio_url(audio) or None
    if url:
        log.info("[voice] reply audio url=%s", url)
    return url


# ---------------- Outbound English check-in (cron) ----------------

def _build_checkin_prompt(plan: dict, name: str, *, conversation_history: str = "(no prior conversation)") -> str:
    """LLM-driven, memory-aware morning check-in.

    Pulls the last day or two of WhatsApp turns out of the patient's
    interactions table and asks the LLM to write a short, varied morning
    ping that references whatever the patient told us yesterday — instead
    of asking the same generic three-symptom question every single day.
    Falls back to the safe generic line if the LLM is unavailable.
    """
    try:
        text = chat_text(
            "daily_checkin",
            patient_name=name or "there",
            red_flag_symptoms=", ".join(plan.get("red_flag_symptoms", []) or []) or "none",
            conversation_history=conversation_history,
        )
        text = (text or "").strip().strip('"').strip()
        if text:
            return text
    except Exception as e:
        log.warning("daily_checkin LLM failed, using fallback: %s", e)
    return (
        f"Hi {name}, how are you feeling today? Any new symptoms — breathlessness, "
        f"swelling, weight gain — and did you take all your meds? A simple yes/no "
        f"reply is fine."
    )


# ---------------- Main node ----------------

def engagement_node(state: PatientState) -> PatientState:
    """Handle a check-in cycle.

    Two trigger modes:
    - state['triggered_by'] == 'cron'    → outbound daily check-in
    - state['triggered_by'] in ('inbound', 'inbound_voice') → triage + reply
    """
    patient_id = state["patient_id"]
    triggered_by = state.get("triggered_by", "inbound")
    patient = state.get("patient_record") or _patient_record(patient_id)
    plan = state.get("care_plan") or _latest_care_plan(patient_id)
    clinical = _latest_clinical(patient_id)
    state.setdefault("outgoing_messages", [])
    state.setdefault("outgoing_emails", [])
    tools_called: list[str] = []

    # --- CRON: daily check-in ---
    if triggered_by == "cron":
        # Pull yesterday's WhatsApp transcript so the morning ping can
        # reference what the patient actually told us — not a stock line.
        cron_history = _format_conversation_history(patient_id)
        msg = _patient_msg(
            _build_checkin_prompt(
                plan,
                patient.get("name", "there"),
                conversation_history=cron_history,
            )
        )
        media_url = _maybe_voice(msg, plan=plan, patient=patient)
        if patient.get("phone"):
            _send_wa(state, to=patient["phone"], body=msg, kind="patient", media_url=media_url)
            tools_called.append("whatsapp:checkin" + (" + voice" if media_url else ""))
            safe_insert(
                "interactions",
                {
                    "patient_id": patient_id,
                    "channel": "whatsapp",
                    "direction": "outbound",
                    "content": msg,
                    "classification": "checkin_prompt",
                    "agent_decision": "send_checkin",
                },
            )
        decided = "Sent daily check-in."
        _persist_reasoning(patient_id, {"trigger": "cron"}, {}, decided, tools_called)
        state.setdefault("tools_called", []).extend(tools_called)
        state.setdefault("reasoning_steps", []).append(
            {"agent": "engagement", "observed": {"trigger": "cron"}, "inferred": {}, "decided": decided, "tools_called": tools_called}
        )
        return state

    # --- INBOUND: triage ---
    message = state.get("current_message", "")
    if not message:
        log.warning("engagement_node inbound with empty message")
        return state

    safe_insert(
        "interactions",
        {
            "patient_id": patient_id,
            "channel": "whatsapp",
            "direction": "inbound",
            "content": message,
            "classification": None,
            "agent_decision": None,
        },
    )

    # Build chat memory ONCE per inbound — this is what stops the model
    # from re-asking the same question and from misclassifying short
    # context-dependent answers like "no" / "fine".
    convo_history = _format_conversation_history(patient_id)
    prior_qs = _count_outbound_questions(patient_id)

    classification = (
        chat_json(
            "nlu_symptom_classifier",
            diagnosis=clinical.get("diagnosis", ""),
            red_flag_symptoms=plan.get("red_flag_symptoms", []),
            message=message,
            conversation_history=convo_history,
        )
        or {}
    )
    tools_called.append("llm:nlu_symptom_classifier")

    severity = (classification.get("severity") or "green").lower()
    confidence = float(classification.get("confidence") or 0.0)
    needs_clarification = bool(classification.get("needs_clarification"))

    # --- CLARIFY: low confidence or NLU explicitly unsure → ask back, exit ---
    if severity != "red" and (needs_clarification or confidence < 0.5):
        severity = "clarify"
        ask = _llm_reply(
            patient_name=patient.get("name", "there"),
            message=message,
            severity="clarify",
            classification=classification,
            plan=plan,
            conversation_history=convo_history,
            prior_questions_asked=prior_qs,
        )
        ask_msg = _patient_msg(ask)
        media_url = _maybe_voice(ask_msg, plan=plan, patient=patient)
        if patient.get("phone"):
            _send_wa(state, to=patient["phone"], body=ask_msg, kind="patient", media_url=media_url)
            tools_called.append("whatsapp:clarify_question")
        decision_text = "CLARIFY — too vague to triage, asked patient to elaborate."
        safe_insert(
            "interactions",
            {
                "patient_id": patient_id,
                "channel": "whatsapp",
                "direction": "inbound_classified",
                "content": message,
                "classification": severity,
                "agent_decision": decision_text,
            },
        )
        _persist_reasoning(
            patient_id,
            observed={"message": message, "confidence": confidence},
            inferred={"classification": classification, "reason": "asked back due to low confidence"},
            decided=decision_text,
            tools=tools_called,
        )
        state["classification"] = classification
        state["decision"] = decision_text
        state.setdefault("tools_called", []).extend(tools_called)
        state.setdefault("reasoning_steps", []).append({
            "agent": "engagement",
            "observed": {"message_excerpt": message[:140], "confidence": confidence},
            "inferred": {"severity": severity},
            "decided": decision_text,
            "tools_called": tools_called,
        })
        return state

    # KG red-flag cross-reference (still a useful belt-and-braces nudge AMBER)
    red_flag_hits = []
    flags = plan.get("red_flag_symptoms", []) or kg_tools.diagnosis_red_flags(clinical.get("diagnosis", ""))
    msg_lower = message.lower()
    for flag in flags:
        if any(tok in msg_lower for tok in flag.lower().split() if len(tok) > 4):
            red_flag_hits.append(flag)
    if red_flag_hits and severity == "green":
        severity = "amber"

    # NOTE: The pharmacy refill agent used to run inline here on every
    # inbound message. That coupled triage to billing and meant a single
    # patient text could fan out to three agents. Refills are now driven
    # by the periodic scheduler job (`check_refills_for_all_patients`)
    # and by an explicit, BackgroundTasks-deferred trigger raised from
    # the inbound webhook when the patient asks for a refill in plain
    # words. The triage path stays clean.

    # Build the LLM reply once — used for every severity
    reply_text = _llm_reply(
        patient_name=patient.get("name", "there"),
        message=message,
        severity=severity,
        classification=classification,
        plan=plan,
        conversation_history=convo_history,
        prior_questions_asked=prior_qs,
    )

    decision_text = ""
    caregiver_email = patient.get("caregiver_email") or settings.caregiver_email_default
    caregiver_phone = patient.get("caregiver_phone") or ""
    doctor_email = settings.doctor_email
    name = patient.get("name", "Patient")
    symptoms = classification.get("symptoms", []) or []

    # --- GREEN ---
    if severity == "green":
        body = _patient_msg(reply_text)
        media_url = _maybe_voice(body, plan=plan, patient=patient)
        if patient.get("phone"):
            _send_wa(state, to=patient["phone"], body=body, kind="patient", media_url=media_url)
            tools_called.append("whatsapp:green_reply")
        decision_text = "GREEN — reinforcement / continued conversation. No escalation."

    # --- AMBER ---
    elif severity == "amber":
        body = _patient_msg(reply_text)
        media_url = _maybe_voice(body, plan=plan, patient=patient)
        if patient.get("phone"):
            _send_wa(state, to=patient["phone"], body=body, kind="patient", media_url=media_url)
            tools_called.append("whatsapp:amber_reply")
        if caregiver_email:
            mail = _amber_caregiver_email(name=name, raw_message=message, symptoms=symptoms)
            _send_em(
                state,
                to=caregiver_email,
                subject=f"CareLoop AMBER alert for {name}",
                text=mail["text"],
                html=mail["html"],
                kind="caregiver",
            )
            tools_called.append("email:caregiver_amber")
        if caregiver_phone:
            cg_wa = _amber_caregiver_msg(name=name, raw_message=message, symptoms=symptoms)
            _send_wa(state, to=caregiver_phone, body=cg_wa, kind="caregiver")
            tools_called.append("whatsapp:caregiver_amber")
        # Persist a non-urgent escalation row so the doctor queue and the
        # Insights dashboard reflect the event. Status defaults to 'pending';
        # the doctor can dismiss it without taking a slot action.
        amber_brief = (
            f"Patient: {name}\n"
            f"Severity: AMBER\n"
            f"Patient message: \"{message}\"\n"
            f"Symptoms (NLU-extracted): {', '.join(symptoms) or '(none labelled)'}\n"
            f"Action: caregiver alerted, patient given safe-steps reply (no doctor booking)."
        )
        safe_insert(
            "escalations",
            {
                "patient_id": patient_id,
                "severity": "amber",
                "brief": amber_brief,
                "status": "pending",
            },
        )
        tools_called.append("db:insert(escalations:amber)")
        decision_text = "AMBER — concrete safe steps sent to patient, caregiver alerted."

    # --- RED ---
    else:
        # Propose 3 candidate slots; patient picks via the booking link.
        slots = propose_slots(urgency="now", count=3)
        proposal = create_proposal_from_agent(
            patient_id=patient_id,
            escalation_id=None,  # set below after escalation row created
            urgency="now",
            proposed_slots=slots,
        )
        picker_url = (proposal or {}).get("picker_url", "")

        # Escalation row — REDACTED brief (no AI diagnosis text).
        esc_brief = (
            f"Patient: {name}\n"
            f"Severity: RED\n"
            f"Patient message: \"{message}\"\n"
            f"Symptoms (NLU-extracted): {', '.join(symptoms) or '(none labelled)'}\n"
            f"Booking link: {picker_url}"
        )
        safe_insert(
            "escalations",
            {
                "patient_id": patient_id,
                "severity": "red",
                "brief": esc_brief,
                "status": "pending",
            },
        )
        tools_called.append("calendar:propose_slots")
        tools_called.append("db:insert(slot_proposals,escalations)")

        # Patient acknowledgement with picker link
        body = _patient_red_picker(reply_text, picker_url, slots)
        media_url = _maybe_voice(body, plan=plan, patient=patient)
        if patient.get("phone"):
            _send_wa(state, to=patient["phone"], body=body, kind="patient", media_url=media_url)
            tools_called.append("whatsapp:patient_red_ack")

        # Doctor heads-up — REDACTED, no diagnosis, no suggested action
        if doctor_email:
            mail = _doctor_email(
                name=name,
                severity="red",
                raw_message=message,
                symptoms=symptoms,
                picker_url=picker_url,
            )
            _send_em(
                state,
                to=doctor_email,
                subject=f"[CareLoop RED] {name} — patient escalation",
                text=mail["text"],
                html=mail["html"],
                kind="doctor",
            )
            tools_called.append("email:doctor_alert")
        if settings.doctor_phone:
            doc_wa = _doctor_msg(
                name=name,
                severity="red",
                raw_message=message,
                symptoms_list=symptoms,
                picker_url=picker_url,
            )
            _send_wa(state, to=settings.doctor_phone, body=doc_wa, kind="doctor")
            tools_called.append("whatsapp:doctor_alert")

        # Caregiver heads-up
        if caregiver_email:
            mail = _caregiver_red_email(name=name, raw_message=message, picker_url=picker_url)
            _send_em(
                state,
                to=caregiver_email,
                subject=f"URGENT — CareLoop alert for {name}",
                text=mail["text"],
                html=mail["html"],
                kind="caregiver",
            )
            tools_called.append("email:caregiver_red")
        if caregiver_phone:
            cg_wa = _caregiver_red_msg(name=name, raw_message=message, picker_url=picker_url)
            _send_wa(state, to=caregiver_phone, body=cg_wa, kind="caregiver")
            tools_called.append("whatsapp:caregiver_red")

        decision_text = (
            f"RED — slot picker sent to patient ({len(slots)} slots). "
            f"Doctor + caregiver notified. Booking confirms only after patient pays."
        )

    # Persist classified inbound row
    safe_insert(
        "interactions",
        {
            "patient_id": patient_id,
            "channel": "whatsapp",
            "direction": "inbound_classified",
            "content": message,
            "classification": severity,
            "agent_decision": decision_text,
        },
    )

    _persist_reasoning(
        patient_id,
        observed={
            "message": message,
            "kg_red_flags": red_flag_hits,
            "confidence": confidence,
        },
        inferred={"classification": classification},
        decided=decision_text,
        tools=tools_called,
    )

    state["classification"] = classification
    state["decision"] = decision_text
    state.setdefault("tools_called", []).extend(tools_called)
    state.setdefault("reasoning_steps", []).append(
        {
            "agent": "engagement",
            "observed": {"message_excerpt": message[:140], "confidence": confidence},
            "inferred": {"severity": severity, "kg_hits": red_flag_hits},
            "decided": decision_text,
            "tools_called": tools_called,
        }
    )
    return state


# ---------------- SDOH one-liner (kept for reasoning, not used in doctor mail) ----------------

def _sdoh_one_liner(patient_id) -> str:
    rows = safe_select("sdoh_profiles", match={"patient_id": patient_id}, limit=1)
    if not rows:
        return ""
    p = rows[0]
    bits = []
    for dim in ("housing_risk", "transport_risk", "caregiver_risk", "literacy_level", "digital_comfort", "financial_risk"):
        v = p.get(dim)
        if v in ("medium", "high"):
            bits.append(f"{dim}={v}")
    return ", ".join(bits) or "no flagged SDOH risks"
