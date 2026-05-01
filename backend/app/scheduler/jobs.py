from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.client import safe_select

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_scheduler: BackgroundScheduler | None = None
_started = False


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    return _scheduler


def start_scheduler():
    global _started
    if _started:
        return
    sched = get_scheduler()
    if not sched.running:
        sched.start()
    _started = True
    log.info("APScheduler started.")


def shutdown_scheduler():
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)



def _distribute_checkin_times(base_time_hhmm: str, times_per_day: int) -> list[str]:
    times_per_day = max(1, min(6, times_per_day))
    try:
        hh, mm = map(int, base_time_hhmm.split(":"))
    except Exception:
        hh, mm = 9, 0
    start_minutes = hh * 60 + mm
    window_minutes = 12 * 60

    if times_per_day == 1:
        return [base_time_hhmm]

    interval = window_minutes // (times_per_day - 1)
    times = []
    for i in range(times_per_day):
        total = (start_minutes + i * interval) % (24 * 60)
        times.append(f"{total // 60:02d}:{total % 60:02d}")
    return times


def schedule_daily_checkin(patient_id: str, time_hhmm: str = "09:00", times_per_day: int = 3):
    cancel_patient_jobs(patient_id)
    times = _distribute_checkin_times(time_hhmm, times_per_day)
    sched = get_scheduler()
    registered = []
    for idx, t in enumerate(times):
        try:
            hh, mm = map(int, t.split(":"))
            job_id = f"checkin:{patient_id}:{idx}"
            sched.add_job(
                _run_checkin,
                CronTrigger(hour=hh, minute=mm, timezone="Asia/Kolkata"),
                args=[patient_id],
                id=job_id,
                replace_existing=True,
                misfire_grace_time=3600,
            )
            registered.append(t)
        except Exception as e:
            log.error("schedule_daily_checkin slot %s failed for %s: %s", t, patient_id, e)
    log.info(
        "Scheduled %d check-in(s) for %s @ %s IST",
        len(registered),
        patient_id,
        ", ".join(registered),
    )


def cancel_patient_jobs(patient_id: str):
    sched = get_scheduler()
    for idx in range(10):
        jid = f"checkin:{patient_id}:{idx}"
        try:
            sched.remove_job(jid)
        except Exception:
            pass
    try:
        sched.remove_job(f"checkin:{patient_id}")
    except Exception:
        pass


def _run_checkin(patient_id: str):
    from app.agents.graph import run_engagement
    from app.agents.state import empty_state

    state = empty_state()
    state["patient_id"] = patient_id
    state["triggered_by"] = "cron"
    log.info("[CRON] check-in firing for %s", patient_id)
    try:
        run_engagement(state)
    except Exception as e:
        log.error("Check-in run failed for %s: %s", patient_id, e)



def reschedule_active_patients() -> int:
    from datetime import date, timedelta

    rescheduled = 0
    skipped_expired = 0
    today = date.today()

    try:
        patients = safe_select("patients") or []
    except Exception as e:
        log.error("reschedule_active_patients: failed to load patients: %s", e)
        return 0

    for p in patients:
        pid = p.get("id")
        if not pid:
            continue
        try:
            clinical_rows = safe_select(
                "clinical_data",
                match={"patient_id": pid},
                limit=1,
            ) or []
            if clinical_rows:
                discharge_str = clinical_rows[0].get("discharge_date")
                if discharge_str:
                    try:
                        discharge = date.fromisoformat(str(discharge_str))
                        if today > discharge + timedelta(days=30):
                            skipped_expired += 1
                            continue
                    except Exception:
                        pass

            plans = safe_select(
                "care_plans",
                match={"patient_id": pid},
                order=("created_at", True),
                limit=1,
            ) or []
            if not plans:
                continue
            plan_json = plans[0].get("plan_json") or {}
            times_per_day = int(plan_json.get("check_in_times_per_day") or 3)
            check_in_time = plan_json.get("check_in_time") or "09:00"
            schedule_daily_checkin(pid, check_in_time, times_per_day)
            rescheduled += 1
        except Exception as e:
            log.error("reschedule_active_patients: failed for %s: %s", pid, e)

    log.info(
        "reschedule_active_patients: rescheduled=%d skipped_expired=%d",
        rescheduled, skipped_expired,
    )
    return rescheduled
