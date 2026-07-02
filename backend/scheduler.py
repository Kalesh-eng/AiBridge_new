"""
scheduler.py — AIBridge Pipeline Scheduler
v2.0: Custom time + quarterly/half-yearly/yearly schedule types.
      Parses schedule string format: daily_0615, weekly_1_0730, monthly_1_0600,
      quarterly_0600, halfyearly_0600, yearly_1_1_0600
v1.0: Basic hourly/daily/weekly/monthly support.
"""

import os
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron        import CronTrigger
from apscheduler.triggers.interval    import IntervalTrigger

scheduler = BackgroundScheduler()


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        print("[Scheduler] Started — APScheduler is running")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[Scheduler] Stopped")


def _parse_schedule(schedule: str) -> dict:
    """
    Parse schedule string into APScheduler trigger kwargs.

    Formats:
      manual            → None (no schedule)
      hourly            → interval hours=1
      daily_HHMM        → cron hour=HH, minute=MM
      weekly_DOW_HHMM   → cron day_of_week=DOW, hour=HH, minute=MM
      monthly_DOM_HHMM  → cron day=DOM, hour=HH, minute=MM
      quarterly_HHMM    → cron month=1/3, day=1, hour=HH, minute=MM
      halfyearly_HHMM   → cron month=1/6, day=1, hour=HH, minute=MM
      yearly_MON_DOM_HHMM → cron month=MON, day=DOM, hour=HH, minute=MM
    """
    if not schedule or schedule == 'manual':
        return None

    s = schedule.lower().strip()

    if s == 'hourly':
        return {"trigger": "interval", "hours": 1}

    if s.startswith('daily_'):
        hhmm = s[6:]  # e.g. "0615"
        hh, mm = hhmm[:2], hhmm[2:]
        return {"trigger": "cron", "hour": int(hh), "minute": int(mm)}

    if s.startswith('weekly_'):
        parts = s[7:].split('_')  # dow_HHMM → ['1', '0600']
        dow, hhmm = parts[0], parts[1] if len(parts) > 1 else '0600'
        hh, mm = hhmm[:2], hhmm[2:]
        return {"trigger": "cron", "day_of_week": int(dow),
                "hour": int(hh), "minute": int(mm)}

    if s.startswith('monthly_'):
        parts = s[8:].split('_')  # dom_HHMM
        dom, hhmm = parts[0], parts[1] if len(parts) > 1 else '0600'
        hh, mm = hhmm[:2], hhmm[2:]
        return {"trigger": "cron", "day": int(dom),
                "hour": int(hh), "minute": int(mm)}

    if s.startswith('quarterly_'):
        hhmm = s[10:]
        hh, mm = hhmm[:2], hhmm[2:]
        return {"trigger": "cron", "month": "1,4,7,10", "day": 1,
                "hour": int(hh), "minute": int(mm)}

    if s.startswith('halfyearly_'):
        hhmm = s[11:]
        hh, mm = hhmm[:2], hhmm[2:]
        return {"trigger": "cron", "month": "1,7", "day": 1,
                "hour": int(hh), "minute": int(mm)}

    if s.startswith('yearly_'):
        parts = s[7:].split('_')  # mon_dom_HHMM
        mon   = parts[0] if len(parts) > 0 else '1'
        dom   = parts[1] if len(parts) > 1 else '1'
        hhmm  = parts[2] if len(parts) > 2 else '0600'
        hh, mm = hhmm[:2], hhmm[2:]
        return {"trigger": "cron", "month": int(mon), "day": int(dom),
                "hour": int(hh), "minute": int(mm)}

    # Legacy formats — backward compatibility
    if s == 'daily':
        return {"trigger": "cron", "hour": 6, "minute": 0}
    if s == 'weekly':
        return {"trigger": "cron", "day_of_week": 0, "hour": 6, "minute": 0}
    if s == 'monthly':
        return {"trigger": "cron", "day": 1, "hour": 6, "minute": 0}

    return None


def add_pipeline_job(pipeline_id: str, pipeline_name: str,
                     sql_scripts: list, schedule: str,
                     workspace_id: str = "") -> dict:
    """Add or update a scheduled pipeline job."""

    # Remove existing job if any
    try:
        scheduler.remove_job(pipeline_id)
    except Exception:
        pass

    if not schedule or schedule == 'manual':
        return {"success": True, "message": f"'{pipeline_name}' set to manual only",
                "schedule": "manual"}

    trigger_kwargs = _parse_schedule(schedule)
    if not trigger_kwargs:
        return {"success": False, "message": f"Unknown schedule format: {schedule}"}

    trigger_type = trigger_kwargs.pop("trigger")

    def run_job():
        print(f"[Scheduler] Running pipeline: {pipeline_name} ({pipeline_id})")
        try:
            import requests
            base_url = os.getenv("API_BASE_URL", "http://localhost:8888")
            r = requests.post(
                f"{base_url}/pipeline/execute/{pipeline_id}",
                json={}, timeout=600,
                headers={"Authorization": f"Bearer {_get_system_token()}"}
            )
            if r.status_code == 200:
                data = r.json()
                rows = data.get("warehouse", {}).get("total_rows", 0)
                print(f"[Scheduler] ✓ {pipeline_name} complete — {rows} rows")
            else:
                print(f"[Scheduler] ✗ {pipeline_name} failed — HTTP {r.status_code}")
        except Exception as e:
            print(f"[Scheduler] ✗ {pipeline_name} error: {e}")

    try:
        if trigger_type == "interval":
            trigger = IntervalTrigger(**trigger_kwargs)
        else:
            trigger = CronTrigger(**trigger_kwargs)

        scheduler.add_job(
            run_job,
            trigger=trigger,
            id=pipeline_id,
            name=pipeline_name,
            replace_existing=True,
            misfire_grace_time=3600
        )

        job = scheduler.get_job(pipeline_id)
        next_run = str(job.next_run_time) if job else "unknown"
        print(f"[Scheduler] ✓ '{pipeline_name}' scheduled: {schedule} | next: {next_run}")

        return {
            "success":       True,
            "pipeline_id":   pipeline_id,
            "pipeline_name": pipeline_name,
            "schedule":      schedule,
            "next_run_time": next_run,
            "message":       f"'{pipeline_name}' scheduled successfully"
        }

    except Exception as e:
        print(f"[Scheduler] ✗ Could not schedule '{pipeline_name}': {e}")
        return {"success": False, "message": str(e)}


def remove_pipeline_job(pipeline_id: str) -> dict:
    """Remove a scheduled job."""
    try:
        scheduler.remove_job(pipeline_id)
        print(f"[Scheduler] Removed job: {pipeline_id}")
        return {"success": True, "message": "Schedule removed"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def list_jobs() -> list:
    """List all scheduled jobs with next run time."""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id":            job.id,
            "pipeline_id":   job.id,
            "name":          job.name,
            "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            "trigger":       str(job.trigger),
        })
    return jobs


def run_pipeline_now(pipeline_id: str, pipeline_name: str,
                     sql_scripts: list, workspace_id: str = "") -> dict:
    """Trigger a pipeline immediately."""
    try:
        import requests
        base_url = os.getenv("API_BASE_URL", "http://localhost:8888")
        r = requests.post(
            f"{base_url}/pipeline/execute/{pipeline_id}",
            json={}, timeout=600,
            headers={"Authorization": f"Bearer {_get_system_token()}"}
        )
        if r.status_code == 200:
            return {"success": True, "message": f"'{pipeline_name}' executed successfully",
                    "result": r.json()}
        return {"success": False, "message": f"Pipeline failed: HTTP {r.status_code}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def _get_system_token() -> str:
    """Get a system token for internal API calls."""
    return os.getenv("SYSTEM_TOKEN", "")
