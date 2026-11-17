"""
morning_brief.py — Daily 7am IST Telegram brief daemon
Sends a morning summary to configured Telegram chats.

Usage:
    python morning_brief.py           # starts scheduler, fires daily at 7am IST
    python morning_brief.py --now     # send brief immediately
    python morning_brief.py --dry-run # print brief, don't send to Telegram
"""

import os
import sys
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv

# APScheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Telegram
from telegram import Bot

# DB
import psycopg2
import psycopg2.extras

# Unified LLM client — no hardcoded provider
from llm_client import chat

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── config ──────────────────────────────────────────────────────────────────
DATABASE_URL       = os.getenv("DATABASE_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS  = [
    cid.strip()
    for cid in os.getenv("TELEGRAM_CHAT_IDS", "").split(",")
    if cid.strip()
]

SYSTEM_PROMPT = """You are Maya 📱, the AIBridge morning brief assistant.
Your job is to generate a concise, actionable daily morning brief for the Data Team.
Focus on: overnight pipeline status, pending agent tasks, data quality issues,
and what needs attention today. Be crisp and use emojis for quick scanning.
Format with clear sections. Keep it under 400 words."""


def get_db():
    return psycopg2.connect(DATABASE_URL)


def gather_overnight_data() -> dict:
    """Pull last 12h of agent/pipeline activity from DB."""
    data = {
        "pending_tasks": [],
        "recent_errors": [],
        "pipeline_incidents": [],
        "hil_pending": [],
    }
    if not DATABASE_URL:
        return data

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT id, request, agents, status, created_at
            FROM agent_tasks
            WHERE status IN ('pending', 'running')
              AND created_at > NOW() - INTERVAL '12 hours'
            ORDER BY created_at DESC LIMIT 10
        """)
        data["pending_tasks"] = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT agent_name, error_type, error_message, created_at
            FROM agent_errors
            WHERE created_at > NOW() - INTERVAL '12 hours'
            ORDER BY created_at DESC LIMIT 10
        """)
        data["recent_errors"] = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT pipeline_name, incident_type, description, resolved, created_at
            FROM pipeline_incidents
            WHERE created_at > NOW() - INTERVAL '12 hours'
            ORDER BY created_at DESC LIMIT 10
        """)
        data["pipeline_incidents"] = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT agent_name, task_description, priority, created_at
            FROM agent_hil_queue
            WHERE status = 'pending'
            ORDER BY priority DESC, created_at ASC LIMIT 5
        """)
        data["hil_pending"] = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"DB gather failed: {e}")

    return data


def build_brief_prompt(data: dict) -> str:
    now = datetime.now().strftime("%A, %d %B %Y — %I:%M %p IST")
    lines = [f"Today is {now}.", "", "Overnight activity summary:"]

    if data["pipeline_incidents"]:
        lines.append(f"\nPipeline incidents ({len(data['pipeline_incidents'])}):")
        for inc in data["pipeline_incidents"]:
            status = "✅ resolved" if inc.get("resolved") else "❌ open"
            lines.append(f"  - {inc['pipeline_name']}: {inc['incident_type']} — {status}")
    else:
        lines.append("\nPipeline incidents: none overnight ✅")

    if data["pending_tasks"]:
        lines.append(f"\nAgent tasks still pending ({len(data['pending_tasks'])}):")
        for t in data["pending_tasks"]:
            agents = ", ".join(t.get("agents") or [])
            lines.append(f"  - [{t['status']}] {t['request'][:80]} (agents: {agents})")
    else:
        lines.append("\nAgent tasks: all clear ✅")

    if data["recent_errors"]:
        lines.append(f"\nAgent errors ({len(data['recent_errors'])}):")
        for e in data["recent_errors"]:
            lines.append(f"  - {e['agent_name']}: {e['error_type']} — {e['error_message'][:60]}")

    if data["hil_pending"]:
        lines.append(f"\n⚠️  Human-in-loop approvals waiting ({len(data['hil_pending'])}):")
        for h in data["hil_pending"]:
            lines.append(f"  - [{h['agent_name']}] {h['task_description'][:80]}")

    lines.append("\nGenerate the morning brief now.")
    return "\n".join(lines)


async def generate_brief() -> str:
    data   = gather_overnight_data()
    prompt = build_brief_prompt(data)
    logger.info(f"[morning_brief] calling LLM for brief...")
    # Uses LLM_PROVIDER from .env — no hardcoded provider
    brief = chat(system=SYSTEM_PROMPT, user=prompt, max_tokens=600)
    return brief


async def send_brief(dry_run: bool = False):
    logger.info("[morning_brief] generating brief...")
    brief = await generate_brief()

    if dry_run:
        print("\n" + "=" * 60)
        print("MORNING BRIEF (dry run — not sent)")
        print("=" * 60)
        print(brief)
        print("=" * 60)
        return

    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    if not TELEGRAM_CHAT_IDS:
        logger.error("TELEGRAM_CHAT_IDS not set")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=brief,
                parse_mode="HTML",
            )
            logger.info(f"[morning_brief] sent to chat_id={chat_id}")
        except Exception as e:
            logger.error(f"[morning_brief] Telegram send failed for {chat_id}: {e}")


async def main():
    args     = sys.argv[1:]
    dry_run  = "--dry-run" in args
    send_now = "--now" in args or dry_run

    if send_now:
        await send_brief(dry_run=dry_run)
        return

    # Scheduler mode — fires daily at 7am IST (UTC+5:30 = 01:30 UTC)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_brief,
        trigger=CronTrigger(hour=1, minute=30, timezone="UTC"),  # 7am IST
        id="morning_brief",
        name="Morning Brief",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[morning_brief] scheduler started — brief fires daily at 7:00 AM IST")
    logger.info("  Use --now to send immediately, --dry-run to preview")

    try:
        await asyncio.Event().wait()  # run forever
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("[morning_brief] scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
