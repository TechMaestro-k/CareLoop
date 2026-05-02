"""Email send tool. Resend HTTP API when configured, mock otherwise."""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.config import settings

log = logging.getLogger(__name__)


def _html_wrapper(title: str, body_html: str) -> str:
    """Wrap body HTML in a clean, mobile-friendly CareLoop email template."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#f4f7fb;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f7fb;padding:32px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:12px;overflow:hidden;
                      box-shadow:0 2px 12px rgba(0,0,0,0.08);max-width:600px;">
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#0ea5e9,#6366f1);
                       padding:28px 32px;text-align:center;">
              <span style="font-size:26px;font-weight:700;color:#ffffff;
                           letter-spacing:-0.5px;">🩺 CareLoop</span>
              <p style="margin:4px 0 0;color:rgba(255,255,255,0.85);font-size:13px;">
                Post-Discharge Care Companion
              </p>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:32px 36px;color:#1e293b;font-size:15px;line-height:1.7;">
              {body_html}
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background:#f8fafc;padding:18px 36px;border-top:1px solid #e2e8f0;
                       text-align:center;color:#94a3b8;font-size:12px;">
              CareLoop · Reducing hospital readmissions through AI-powered care<br/>
              <a href="https://www.careloops.tech" style="color:#0ea5e9;text-decoration:none;">
                www.careloops.tech
              </a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def build_patient_welcome_html(name: str, plan: dict) -> tuple[str, str]:
    """Return (subject, html) for the patient onboarding welcome email."""
    n = int(plan.get("check_in_times_per_day") or 3)
    time_ = plan.get("check_in_time", "09:00")
    channel = plan.get("channel", "whatsapp_text").replace("_", " ").title()

    meds = plan.get("medication_schedule", [])
    med_rows = ""
    for m in meds:
        med_rows += (
            f"<tr>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0;'>{m.get('med','')}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#64748b;'>{m.get('time','')}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#64748b;'>{m.get('instruction','')}</td>"
            f"</tr>"
        )
    if not med_rows:
        med_rows = "<tr><td colspan='3' style='padding:8px 12px;color:#94a3b8;'>No medication schedule generated</td></tr>"

    body_html = f"""
<h2 style="margin:0 0 8px;font-size:20px;color:#0f172a;">
  Welcome to CareLoop, {name}! 👋
</h2>
<p style="margin:0 0 20px;color:#475569;">
  You've been successfully enrolled in CareLoop's post-discharge monitoring programme.
  Here's everything you need to know.
</p>

<div style="background:#eff6ff;border-left:4px solid #3b82f6;padding:16px 20px;
            border-radius:0 8px 8px 0;margin-bottom:24px;">
  <strong style="color:#1d4ed8;">📅 Check-in Schedule</strong><br/>
  <span style="color:#1e40af;">
    {n} time{'s' if n > 1 else ''} a day at {time_} via {channel}
  </span>
</div>

<h3 style="margin:0 0 10px;font-size:15px;color:#0f172a;">💊 Medication Schedule</h3>
<table width="100%" cellpadding="0" cellspacing="0"
       style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;margin-bottom:24px;font-size:14px;">
  <thead>
    <tr style="background:#f1f5f9;">
      <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;">Medication</th>
      <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;">Time</th>
      <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;">Instruction</th>
    </tr>
  </thead>
  <tbody>
    {med_rows}
  </tbody>
</table>

<div style="background:#f0fdf4;border-left:4px solid #22c55e;padding:16px 20px;
            border-radius:0 8px 8px 0;margin-bottom:24px;">
  <strong style="color:#15803d;">💬 How it works</strong><br/>
  <span style="color:#166534;font-size:14px;">
    You'll receive check-in messages on WhatsApp. Simply reply to them — our AI monitors your
    responses and loops in your doctor if anything needs attention.
  </span>
</div>

<p style="color:#64748b;font-size:14px;margin:0;">
  Questions? Reply to this email or message us on WhatsApp anytime.<br/><br/>
  — The CareLoop Team
</p>
"""
    subject = f"Welcome to CareLoop, {name} — your care plan is ready"
    return subject, _html_wrapper(subject, body_html)


def build_caregiver_email_html(patient_name: str, plan: dict, clinical: dict, sdoh: dict) -> tuple[str, str]:
    """Return (subject, html) for the caregiver summary email."""
    n = int(plan.get("check_in_times_per_day") or 3)
    time_ = plan.get("check_in_time", "09:00")
    channel = plan.get("channel", "whatsapp_text").replace("_", " ").title()
    diagnosis = clinical.get("diagnosis", "Not specified")

    meds = plan.get("medication_schedule", [])
    med_rows = ""
    for m in meds:
        med_rows += (
            f"<tr>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0;'>{m.get('med','')}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#64748b;'>{m.get('time','')}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#64748b;'>{m.get('instruction','')}</td>"
            f"</tr>"
        )
    if not med_rows:
        med_rows = "<tr><td colspan='3' style='padding:8px 12px;color:#94a3b8;'>No medication schedule generated</td></tr>"

    body_html = f"""
<h2 style="margin:0 0 8px;font-size:20px;color:#0f172a;">
  Care Plan Summary for {patient_name}
</h2>
<p style="margin:0 0 20px;color:#475569;">
  CareLoop is now actively monitoring <strong>{patient_name}</strong> after discharge.
  Here is a summary of their care plan.
</p>

<div style="background:#fef9c3;border-left:4px solid #eab308;padding:16px 20px;
            border-radius:0 8px 8px 0;margin-bottom:24px;">
  <strong style="color:#92400e;">🏥 Diagnosis</strong><br/>
  <span style="color:#78350f;">{diagnosis}</span>
</div>

<div style="background:#eff6ff;border-left:4px solid #3b82f6;padding:16px 20px;
            border-radius:0 8px 8px 0;margin-bottom:24px;">
  <strong style="color:#1d4ed8;">📅 Check-in Schedule</strong><br/>
  <span style="color:#1e40af;">
    {n} time{'s' if n > 1 else ''} a day at {time_} via {channel}
  </span>
</div>

<h3 style="margin:0 0 10px;font-size:15px;color:#0f172a;">💊 Medication Schedule</h3>
<table width="100%" cellpadding="0" cellspacing="0"
       style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;margin-bottom:24px;font-size:14px;">
  <thead>
    <tr style="background:#f1f5f9;">
      <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;">Medication</th>
      <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;">Time</th>
      <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;">Instruction</th>
    </tr>
  </thead>
  <tbody>
    {med_rows}
  </tbody>
</table>

<div style="background:#fef2f2;border-left:4px solid #ef4444;padding:16px 20px;
            border-radius:0 8px 8px 0;margin-bottom:24px;">
  <strong style="color:#b91c1c;">📧 Escalation alerts</strong><br/>
  <span style="color:#991b1b;font-size:14px;">
    You will receive an email immediately if the patient's condition escalates or
    a doctor appointment is needed.
  </span>
</div>

<p style="color:#64748b;font-size:14px;margin:0;">
  — The CareLoop Team
</p>
"""
    subject = f"CareLoop care plan for {patient_name} — caregiver summary"
    return subject, _html_wrapper(subject, body_html)


def send_email(to: str, subject: str, body: str, html: Optional[str] = None) -> dict:
    """Send a plain-text (and optional HTML) email. Returns {ok, mock}."""
    if not settings.has_email:
        log.info("Email mock (no Resend key): to=%s subject=%s", to, subject)
        return {"ok": True, "mock": True, "to": to, "subject": subject}

    payload: dict = {
        "from": settings.email_from,
        "to": [to],
        "subject": subject,
        "text": body,
    }
    if html:
        payload["html"] = html

    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if resp.status_code >= 400:
            log.error("Resend email failed: %s %s", resp.status_code, resp.text)
            return {"ok": False, "reason": resp.text, "mock": False}
        data = resp.json()
        log.info("Email sent via Resend to %s  id=%s", to, data.get("id"))
        return {"ok": True, "mock": False, "id": data.get("id")}
    except Exception as e:
        log.error("Email send failed: %s", e)
        return {"ok": False, "reason": str(e), "mock": False}
