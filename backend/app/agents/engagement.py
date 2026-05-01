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
    rows = _recent_interactions(patient_id, limit=limit) or []
    if not rows:
        return "(no prior conversation)"

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
        lines = []
        for r in rows:
            content = (r.get("content") or "").strip()
            if not content:
                continue
            who = "Patient" if (r.get("direction") or "").startswith("inbound") else "CareLoop"
            lines.append(f"{who}: {content}")
        return "\n".join(lines) or "(no prior conversation)"



def _send_wa(state: PatientState, *, to: str, body: str, kind: str, media_url: Optional[str] = None) -> dict:
    res = send_whatsapp(to, body, media_url=media_url)
    entry: dict = {
        "to": kind,
        "phone": to,
        "text": body,
        "media_url": media_url,
        "ok": bool(res.get("ok")),
        "mock": bool(res.get("mock")),
    }
    if not res.get("ok") and res.get("reason"):
        entry["reason"] = str(res["reason"])
    state.setdefault("outgoing_messages", []).append(entry)
    return res


def _send_em(state: PatientState, *, to: str, subject: str, text: str, html: Optional[str], kind: str) -> dict:
    res = send_email(to, subject, text, html=html)
    entry: dict = {
        "to": kind,
        "address": to,
        "subject": subject,
        "ok": bool(res.get("ok")),
        "mock": bool(res.get("mock")),
    }
    if not res.get("ok") and res.get("reason"):
        entry["reason"] = str(res["reason"])
    state.setdefault("outgoing_emails", []).append(entry)
    return res



def _count_outbound_questions(patient_id: str, *, limit: int = 8) -> int:
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
    return (
        f"Hi {patient_name or 'there'} — checking in. How are you feeling today? "
        "Any breathing trouble, swelling, weight change, or missed doses?"
    )



def _patient_msg(body: str) -> str:
    return f"🩺 CareLoop\n{body.strip()}"


def _patient_red_picker(body_intro: str, picker_url: str, slots: list[dict]) -> str:
    sample = " · ".join(s["human"] for s in (slots or [])[:3])
    cta = f"Pick a time that works:\n{picker_url}" if picker_url else "Pick a time that works."
    suffix = f"\n\nAvailable: {sample}" if sample else ""
    return _patient_msg(f"{body_intro}\n\n{cta}{suffix}")


def _doctor_msg(*, name: str, severity: str, raw_message: str, symptoms_list: list[str], picker_url: str) -> str:
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



def _maybe_voice(text: str, *, plan: dict, patient: dict) -> Optional[str]:
    channel = (plan.get("channel") or patient.get("channel_pref") or "").strip()
    if channel != "whatsapp_voice":
        return None
    audio = synthesize_sync(text, language=plan.get("language") or "en")
    if not audio:
        return None
    url = public_audio_url(audio) or None
    if url:
        log.info("[voice] reply audio url=%s", url)
    return url



def _get_slot_label() -> str:
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(IST)
    h = now_ist.hour
    if 4 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    return "evening"


def _build_checkin_prompt(plan: dict, name: str, *, conversation_history: str = "(no prior conversation)", slot_label: str = "morning") -> str:
    try:
        text = chat_text(
            "daily_checkin",
            patient_name=name or "there",
            red_flag_symptoms=", ".join(plan.get("red_flag_symptoms", []) or []) or "none",
            conversation_history=conversation_history,
            slot_label=slot_label,
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



def engagement_node(state: PatientState) -> PatientState:
    patient_id = state["patient_id"]
    triggered_by = state.get("triggered_by", "inbound")
    patient = state.get("patient_record") or _patient_record(patient_id)
    plan = state.get("care_plan") or _latest_care_plan(patient_id)
    clinical = _latest_clinical(patient_id)
    state.setdefault("outgoing_messages", [])
    state.setdefault("outgoing_emails", [])
    tools_called: list[str] = []

    if triggered_by == "cron":
        slot_label = _get_slot_label()
        cron_history = _format_conversation_history(patient_id)
        msg = _patient_msg(
            _build_checkin_prompt(
                plan,
                patient.get("name", "there"),
                conversation_history=cron_history,
                slot_label=slot_label,
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
        decided = f"Sent scheduled check-in (slot {slot_label})."
        _persist_reasoning(patient_id, {"trigger": "cron", "slot": slot_label}, {}, decided, tools_called)
        state.setdefault("tools_called", []).extend(tools_called)
        state.setdefault("reasoning_steps", []).append(
            {"agent": "engagement", "observed": {"trigger": "cron"}, "inferred": {}, "decided": decided, "tools_called": tools_called}
        )
        return state

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

    red_flag_hits = []
    flags = plan.get("red_flag_symptoms", []) or kg_tools.diagnosis_red_flags(clinical.get("diagnosis", ""))
    msg_lower = message.lower()
    for flag in flags:
        if any(tok in msg_lower for tok in flag.lower().split() if len(tok) > 4):
            red_flag_hits.append(flag)
    if red_flag_hits and severity == "green":
        severity = "amber"

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

    if severity == "green":
        body = _patient_msg(reply_text)
        media_url = _maybe_voice(body, plan=plan, patient=patient)
        if patient.get("phone"):
            _send_wa(state, to=patient["phone"], body=body, kind="patient", media_url=media_url)
            tools_called.append("whatsapp:green_reply")
        decision_text = "GREEN — reinforcement / continued conversation. No escalation."

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

    else:
        slots = propose_slots(urgency="now", count=3)
        proposal = create_proposal_from_agent(
            patient_id=patient_id,
            escalation_id=None,
            urgency="now",
            proposed_slots=slots,
        )
        picker_url = (proposal or {}).get("picker_url", "")

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

        body = _patient_red_picker(reply_text, picker_url, slots)
        media_url = _maybe_voice(body, plan=plan, patient=patient)
        if patient.get("phone"):
            _send_wa(state, to=patient["phone"], body=body, kind="patient", media_url=media_url)
            tools_called.append("whatsapp:patient_red_ack")

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
