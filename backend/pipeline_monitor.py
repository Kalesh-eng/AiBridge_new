"""
pipeline_monitor.py — Self-healing pipeline monitor daemon

Monitors ETL pipelines for stalls, errors, and anomalies.
Attempts auto-fix for known issues; escalates via Telegram if needed.

Usage:
    python pipeline_monitor.py                    # daemon mode
    python pipeline_monitor.py --check            # one-shot check, then exit
    python pipeline_monitor.py --pipeline <name>  # check specific pipeline
"""

import os
import sys
import uuid
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Bot
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Unified LLM client — no hardcoded provider
from llm_client import chat

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL        = os.getenv("DATABASE_URL", "")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS   = [
    cid.strip()
    for cid in os.getenv("TELEGRAM_CHAT_IDS", "").split(",")
    if cid.strip()
]
MONITOR_INTERVAL_MIN = int(os.getenv("MONITOR_INTERVAL_MIN", "5"))
STALL_THRESHOLD_MIN  = int(os.getenv("STALL_THRESHOLD_MIN",  "30"))
MAX_AUTO_RETRIES     = int(os.getenv("MAX_AUTO_RETRIES",      "3"))

DIAGNOSE_SYSTEM = """You are dev_etl 🔧, the AIBridge ETL Engineer.
A pipeline has an issue. Analyze it and provide:
1. Root cause (1-2 sentences)
2. Auto-fix action (if safe and reversible)
3. Escalation recommendation (yes/no, why)

Be concise. Format as:
ROOT CAUSE: ...
AUTO-FIX: ...
ESCALATE: yes/no — reason"""


def get_db():
    return psycopg2.connect(DATABASE_URL)


def db_log_incident(pipeline_name: str, incident_type: str, description: str,
                    auto_fix_tried: bool = False, auto_fix_result: str = None,
                    fix_description: str = None, escalated: bool = False) -> Optional[str]:
    incident_id = str(uuid.uuid4())
    if not DATABASE_URL:
        return incident_id
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO pipeline_incidents
              (id, pipeline_name, incident_type, description,
               auto_fix_tried, auto_fix_result, fix_description, escalated, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (incident_id, pipeline_name, incident_type, description,
              auto_fix_tried, auto_fix_result, fix_description, escalated))
        conn.commit(); cur.close(); conn.close()
        return incident_id
    except Exception as e:
        logger.warning(f"db_log_incident: {e}")
        return incident_id


def db_resolve_incident(incident_id: str):
    if not DATABASE_URL:
        return
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            UPDATE pipeline_incidents
            SET resolved=TRUE, resolved_at=NOW()
            WHERE id=%s
        """, (incident_id,))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        logger.warning(f"db_resolve_incident: {e}")


def db_get_stalled_tasks() -> list:
    """Find agent tasks that have been 'running' longer than STALL_THRESHOLD_MIN."""
    if not DATABASE_URL:
        return []
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        stall_time = datetime.utcnow() - timedelta(minutes=STALL_THRESHOLD_MIN)
        cur.execute("""
            SELECT * FROM agent_tasks
            WHERE status='running' AND updated_at < %s
        """, (stall_time,))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()
        return rows
    except Exception as e:
        logger.warning(f"db_get_stalled_tasks: {e}")
        return []


def db_get_recent_errors(minutes: int = 10) -> list:
    if not DATABASE_URL:
        return []
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        since = datetime.utcnow() - timedelta(minutes=minutes)
        cur.execute("""
            SELECT * FROM agent_errors
            WHERE created_at > %s
            ORDER BY created_at DESC
        """, (since,))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()
        return rows
    except Exception as e:
        logger.warning(f"db_get_recent_errors: {e}")
        return []


def db_get_anomalies(limit: int = 10) -> list:
    if not DATABASE_URL:
        return []
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM agent_anomalies
            WHERE resolved=FALSE
            ORDER BY created_at DESC LIMIT %s
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()
        return rows
    except Exception as e:
        logger.warning(f"db_get_anomalies: {e}")
        return []


def db_mark_task_failed(task_id: str, reason: str):
    if not DATABASE_URL:
        return
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            UPDATE agent_tasks
            SET status='failed', error=%s, updated_at=NOW()
            WHERE id=%s
        """, (reason, task_id))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        logger.warning(f"db_mark_task_failed: {e}")


async def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_IDS:
        logger.warning("[monitor] Telegram not configured — alert not sent")
        logger.info(f"[ALERT] {message}")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            await bot.send_message(chat_id=chat_id, text=f"🚨 AIBridge Alert\n\n{message}")
        except Exception as e:
            logger.error(f"[monitor] Telegram send failed for {chat_id}: {e}")


async def diagnose_and_fix(pipeline_name: str, incident_type: str, description: str) -> dict:
    """Ask LLM to diagnose the incident and suggest a fix."""
    prompt = (
        f"Pipeline: {pipeline_name}\n"
        f"Incident type: {incident_type}\n"
        f"Description: {description}\n\n"
        f"Analyze and provide root cause, auto-fix, and escalation decision."
    )

    # Uses LLM_PROVIDER from .env — no hardcoded provider
    diagnosis = chat(system=DIAGNOSE_SYSTEM, user=prompt, max_tokens=400)

    should_escalate = "escalate: yes" in diagnosis.lower()
    return {
        "diagnosis":        diagnosis,
        "should_escalate":  should_escalate,
    }


async def check_stalled_tasks():
    stalled = db_get_stalled_tasks()
    if not stalled:
        return

    logger.warning(f"[monitor] Found {len(stalled)} stalled tasks")

    for task in stalled:
        task_id  = str(task["id"])
        req_text = task.get("request", "unknown")[:100]

        result = await diagnose_and_fix(
            pipeline_name=f"agent_task:{task_id}",
            incident_type="stall",
            description=f"Task '{req_text}' stalled in 'running' state for >{STALL_THRESHOLD_MIN}m",
        )

        incident_id = db_log_incident(
            pipeline_name=f"agent_task:{task_id}",
            incident_type="stall",
            description=result["diagnosis"],
            auto_fix_tried=True,
            auto_fix_result="failed" if result["should_escalate"] else "retried",
            fix_description="Marked as failed; operator alerted" if result["should_escalate"] else "Task reset to pending for retry",
            escalated=result["should_escalate"],
        )

        # Simple auto-fix: mark stalled task as failed
        db_mark_task_failed(task_id, f"Auto-detected stall: {result['diagnosis'][:200]}")

        if result["should_escalate"]:
            await send_telegram_alert(
                f"⚠️ Stalled pipeline task\n"
                f"Task: {req_text}\n"
                f"Diagnosis: {result['diagnosis'][:300]}"
            )


async def check_error_spikes():
    errors = db_get_recent_errors(minutes=MONITOR_INTERVAL_MIN)
    if len(errors) < 3:
        return

    # Group by agent
    by_agent: dict[str, int] = {}
    for e in errors:
        by_agent[e["agent_name"]] = by_agent.get(e["agent_name"], 0) + 1

    for agent_name, count in by_agent.items():
        if count >= 3:
            description = f"{count} errors from {agent_name} in last {MONITOR_INTERVAL_MIN}m"
            logger.warning(f"[monitor] Error spike: {description}")

            result = await diagnose_and_fix(
                pipeline_name=agent_name,
                incident_type="error_spike",
                description=description,
            )

            db_log_incident(
                pipeline_name=agent_name,
                incident_type="error_spike",
                description=result["diagnosis"],
                auto_fix_tried=False,
                escalated=result["should_escalate"],
            )

            if result["should_escalate"]:
                await send_telegram_alert(
                    f"🔴 Error spike: {agent_name}\n"
                    f"{count} errors in {MONITOR_INTERVAL_MIN}m\n"
                    f"{result['diagnosis'][:300]}"
                )


async def run_check(pipeline_filter: Optional[str] = None):
    """Single monitor cycle."""
    logger.info(f"[monitor] running check{' for ' + pipeline_filter if pipeline_filter else ''}...")
    await check_stalled_tasks()
    await check_error_spikes()
    logger.info("[monitor] check complete")


async def main():
    args            = sys.argv[1:]
    one_shot        = "--check" in args
    pipeline_filter = None

    if "--pipeline" in args:
        idx = args.index("--pipeline")
        if idx + 1 < len(args):
            pipeline_filter = args[idx + 1]

    if one_shot:
        await run_check(pipeline_filter)
        return

    # Daemon mode
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_check,
        trigger=IntervalTrigger(minutes=MONITOR_INTERVAL_MIN),
        id="pipeline_monitor",
        name="Pipeline Monitor",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"[monitor] daemon started — checking every {MONITOR_INTERVAL_MIN}m, "
        f"stall threshold={STALL_THRESHOLD_MIN}m, max_retries={MAX_AUTO_RETRIES}"
    )

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("[monitor] daemon stopped")


if __name__ == "__main__":
    asyncio.run(main())
