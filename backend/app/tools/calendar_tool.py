"""Auto-book telehealth slot using free, no-auth services.

- **Jitsi Meet** is used for the actual video room. Free, instant, no signup
  for either party — both doctor and patient just open the link in a browser.
- **Google Calendar TEMPLATE link** so the doctor (and caregiver, if attached)
  can one-click "Add to Calendar" without us holding any OAuth credentials.

Returned fields are deliberately self-contained so callers can drop them into
emails / WhatsApp / UIs without any further composition.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

IST = timezone(timedelta(hours=5, minutes=30))
SLOT_DURATION_MIN = 15


def propose_slots(urgency: str = "today", count: int = 4) -> list[dict]:
    """Generate `count` candidate slots in business hours (09:00–21:00 IST).

    - urgency='now' → starts in 15 min, slots every 30 min
    - urgency='today' → starts in 30 min, slots every 60 min
    - urgency='tomorrow' → next day 10:00 onward, slots every 60 min
    Skips past business hours by rolling to next business day.
    """
    now = datetime.now(IST)
    if urgency == "now":
        first = now + timedelta(minutes=15)
        step = timedelta(minutes=30)
    elif urgency == "tomorrow":
        first = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        step = timedelta(minutes=60)
    else:
        candidate = now + timedelta(minutes=30)
        minute = (candidate.minute // 30) * 30
        first = candidate.replace(minute=minute, second=0, microsecond=0)
        step = timedelta(minutes=60)

    slots: list[dict] = []
    cur = first
    safety = 0
    while len(slots) < count and safety < 50:
        safety += 1
        if cur.hour < 9:
            cur = cur.replace(hour=9, minute=0)
        if cur.hour >= 21:
            cur = (cur + timedelta(days=1)).replace(hour=9, minute=0)
        slots.append({
            "iso": cur.isoformat(),
            "human": cur.strftime("%a %d %b, %I:%M %p IST"),
            "duration_min": SLOT_DURATION_MIN,
        })
        cur = cur + step
    return slots


def build_jitsi_room(patient_id: str) -> str:
    room = f"CareLoop-{patient_id[:8]}-{secrets.token_hex(3)}"
    return room


def jitsi_link(room: str) -> str:
    # HARDCODED: meet.jit.si is the public Jitsi Meet instance we rely on for
    # this lightweight deployment. Swap to a self-hosted Jitsi or a
    # paid video provider in prod by replacing this base URL.
    return f"https://meet.jit.si/{room}#config.prejoinPageEnabled=false"


def confirm_booking(
    *,
    patient_id: str,
    chosen_slot: dict,
    doctor_email: str,
    patient_name: Optional[str] = None,
    headline: Optional[str] = None,
    caregiver_email: Optional[str] = None,
) -> dict:
    """Build the final, doctor-accepted booking artifacts (Jitsi + calendar URL)."""
    room = build_jitsi_room(patient_id)
    join_link = jitsi_link(room)
    start = datetime.fromisoformat(chosen_slot["iso"])
    end = start + timedelta(minutes=chosen_slot.get("duration_min", SLOT_DURATION_MIN))
    name = patient_name or "Patient"
    title = f"CareLoop telehealth: {name}"
    details = (
        f"Confirmed via CareLoop ({headline or 'post-discharge follow-up'}).\n\n"
        f"Patient: {name}\n"
        f"Join link: {join_link}\n\n"
        f"This is a video consult. No app install needed — open the link in any browser."
    )
    guests = [g for g in [doctor_email, caregiver_email] if g]
    cal = _gcal_template_url(title=title, start=start, end=end, details=details, guests=guests)
    return {
        "ok": True,
        "slot_iso": start.isoformat(),
        "slot_human": start.strftime("%a %d %b %Y, %I:%M %p IST"),
        "duration_min": chosen_slot.get("duration_min", SLOT_DURATION_MIN),
        "link": join_link,
        "calendar_link": cal,
        "room": room,
    }


def _next_slot(urgency: str) -> datetime:
    """Pick the next reasonable slot. Business hours window: 09:00–21:00 IST."""
    now = datetime.now(IST)
    if urgency == "now":
        return now + timedelta(minutes=15)
    if urgency == "today":
        candidate = now + timedelta(minutes=30)
        minute = (candidate.minute // 30) * 30
        slot = candidate.replace(minute=minute, second=0, microsecond=0)
        if slot.hour < 9:
            slot = slot.replace(hour=9, minute=0)
        elif slot.hour >= 21:
            slot = (slot + timedelta(days=1)).replace(hour=9, minute=0)
        return slot
    return (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)


def _gcal_template_url(
    *, title: str, start: datetime, end: datetime, details: str, guests: list[str]
) -> str:
    """Build a Google Calendar TEMPLATE URL.

    Clicking it opens Google Calendar's "Create event" form pre-filled. No
    OAuth required. The event lands on the clicker's primary calendar; guests
    receive the standard invite.
    """
    def fmt(d: datetime) -> str:
        return d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{fmt(start)}/{fmt(end)}",
        "details": details,
        "ctz": "Asia/Kolkata",
    }
    if guests:
        params["add"] = ",".join(guests)
    # HARDCODED: Google Calendar's public template URL. No OAuth needed; this
    # is a stable, documented endpoint. Replace only if migrating away from
    # Google Calendar entirely.
    return "https://calendar.google.com/calendar/render?" + urlencode(params)


def book_telehealth_slot(
    patient_id: str,
    doctor_email: str,
    urgency: str = "today",
    patient_name: Optional[str] = None,
    headline: Optional[str] = None,
    caregiver_email: Optional[str] = None,
) -> dict:
    """Book a telehealth slot. Returns dict with real, working links."""
    slot = _next_slot(urgency)
    end = slot + timedelta(minutes=SLOT_DURATION_MIN)

    # Jitsi room — namespaced + random suffix so old links stay valid but each
    # booking gets its own private room.
    room = f"CareLoop-{patient_id[:8]}-{secrets.token_hex(3)}"
    # HARDCODED: see jitsi_link() above — public meet.jit.si instance.
    join_link = f"https://meet.jit.si/{room}#config.prejoinPageEnabled=false"

    name = patient_name or "Patient"
    title = f"CareLoop telehealth: {name}"
    details = (
        f"Auto-booked via CareLoop ({headline or 'post-discharge follow-up'}).\n\n"
        f"Patient: {name}\n"
        f"Join link: {join_link}\n\n"
        f"This is a video consult. No app install needed — open the link in any browser."
    )
    guests = [g for g in [doctor_email, caregiver_email] if g]
    calendar_link = _gcal_template_url(
        title=title, start=slot, end=end, details=details, guests=guests
    )

    return {
        "ok": True,
        "slot_iso": slot.isoformat(),
        "slot_human": slot.strftime("%a %d %b %Y, %I:%M %p IST"),
        "duration_min": SLOT_DURATION_MIN,
        "link": join_link,
        "calendar_link": calendar_link,
        "room": room,
        "mock": False,
    }
