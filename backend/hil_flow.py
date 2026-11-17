"""
hil_flow.py — Human-in-the-loop approval flow (FastAPI + Telegram)

Agents queue tasks requiring human judgment. Telegram buttons let the
operator approve or reject. Decisions are persisted and callbacks returned
to the requesting agent.

Mount in main.py:
    from hil_flow import router as hil_router, start_hil_bot
    app.include_router(hil_router, prefix="/api/hil")

    @app.on_event("startup")
    async def startup():
        await start_hil_bot()
"""

import os
import sys
import uuid
import json
import asyncio
import logging
from typing import Optional, Callable, Awaitable
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Unified LLM client — no hardcoded provider
from llm_client import chat

load_dotenv()
logger = logging.getLogger(__name__)
router = APIRouter()

DATABASE_URL       = os.getenv("DATABASE_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS  = [
    cid.strip()
    for cid in os.getenv("TELEGRAM_CHAT_IDS", "").split(",")
    if cid.strip()
]

HIL_SYSTEM = """You are maya 📱, the AIBridge Communications agent.
Summarize this task approval request in 2-3 crisp sentences suitable for
a Telegram notification. Include: what the agent wants to do, why it needs
human approval, and any risk or impact. Be direct and clear."""

# ── in-memory callbacks ───────────────────────────────────────────────────────
# Maps hil_id -> callback(decision: str, note: str) -> None
_pending_callbacks: dict[str, Callable[[str, str], Awaitable[None]]] = {}

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(DATABASE_URL)


def db_create_hil(agent_name: str, task_id: Optional[str],
                  task_description: str, reason: str,
                  priority: int = 5) -> str:
    hil_id = str(uuid.uuid4())
    if not DATABASE_URL:
        return hil_id
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO agent_hil_queue
              (id, agent_name, task_id, task_description, reason,
               priority, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', NOW())
        """, (hil_id, agent_name, task_id, task_description, reason, priority))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        logger.warning(f"db_create_hil: {e}")
    return hil_id


def db_record_decision(hil_id: str, decision: str,
                       decision_by: str, decision_note: str,
                       telegram_msg_id: Optional[int] = None):
    if not DATABASE_URL:
        return
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            UPDATE agent_hil_queue
            SET status=%s, decision_by=%s, decision_note=%s,
                telegram_msg_id=%s, decided_at=NOW()
            WHERE id=%s
        """, (decision, decision_by, decision_note, telegram_msg_id, hil_id))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        logger.warning(f"db_record_decision: {e}")


def db_update_telegram_msg_id(hil_id: str, msg_id: int):
    if not DATABASE_URL:
        return
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            "UPDATE agent_hil_queue SET telegram_msg_id=%s WHERE id=%s",
            (msg_id, hil_id)
        )
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        logger.warning(f"db_update_telegram_msg_id: {e}")


def db_get_pending() -> list:
    if not DATABASE_URL:
        return []
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM agent_hil_queue
            WHERE status='pending'
            ORDER BY priority DESC, created_at ASC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()
        return rows
    except Exception as e:
        logger.warning(f"db_get_pending: {e}")
        return []


def db_get_history(limit: int = 20) -> list:
    if not DATABASE_URL:
        return []
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM agent_hil_queue
            WHERE status IN ('approved', 'rejected')
            ORDER BY decided_at DESC LIMIT %s
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()
        return rows
    except Exception as e:
        logger.warning(f"db_get_history: {e}")
        return []


# ── Telegram bot ──────────────────────────────────────────────────────────────
_bot_app: Optional[Application] = None


async def send_hil_notification(hil_id: str, agent_name: str,
                                 task_description: str, reason: str,
                                 summary: str):
    """Send Telegram message with Approve/Reject inline keyboard."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_IDS:
        logger.warning("[hil] Telegram not configured")
        return

    text = (
        f"🔔 <b>Approval Needed</b>\n"
        f"Agent: <b>{agent_name}</b>\n\n"
        f"{summary}\n\n"
        f"<i>Reason: {reason}</i>"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"hil:approve:{hil_id}"),
            InlineKeyboardButton("❌ Reject",  callback_data=f"hil:reject:{hil_id}"),
        ]
    ])

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            db_update_telegram_msg_id(hil_id, msg.message_id)
            logger.info(f"[hil] notification sent to chat_id={chat_id}, msg_id={msg.message_id}")
        except Exception as e:
            logger.error(f"[hil] Telegram send failed for {chat_id}: {e}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Approve/Reject button presses."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if not data.startswith("hil:"):
        return

    parts    = data.split(":")
    action   = parts[1]           # "approve" or "reject"
    hil_id   = parts[2] if len(parts) > 2 else ""
    user     = query.from_user
    operator = f"{user.full_name} (@{user.username})" if user else "unknown"
    decision = "approved" if action == "approve" else "rejected"

    db_record_decision(
        hil_id=hil_id,
        decision=decision,
        decision_by=operator,
        decision_note="",
        telegram_msg_id=query.message.message_id if query.message else None,
    )

    emoji = "✅" if decision == "approved" else "❌"
    try:
        await query.edit_message_text(
            text=f"{emoji} <b>{decision.upper()}</b> by {operator}\n\n"
                 f"{query.message.text if query.message else ''}",
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Fire callback if waiting
    cb = _pending_callbacks.pop(hil_id, None)
    if cb:
        try:
            await cb(decision, operator)
        except Exception as e:
            logger.error(f"[hil] callback error for {hil_id}: {e}")

    logger.info(f"[hil] {hil_id} → {decision} by {operator}")


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help command — show bot capabilities."""
    text = (
        "🤖 <b>AIBridge HIL Bot</b>\n\n"
        "I notify you when an AI agent needs human approval.\n\n"
        "<b>Commands:</b>\n"
        "/status — show pending approvals\n"
        "/help — show this message\n\n"
        "<b>How to use:</b>\n"
        "• Tap ✅ <b>Approve</b> or ❌ <b>Reject</b> on a notification\n"
        "• Reply to any notification with a question or comment — it will be forwarded to the team\n\n"
        "<i>Powered by AIBridge Data Team</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status command — show pending HIL requests."""
    pending = db_get_pending()
    if not pending:
        await update.message.reply_text("✅ No pending approvals right now.")
        return

    lines = [f"🔔 <b>{len(pending)} pending approval(s):</b>\n"]
    for i, item in enumerate(pending[:5], 1):
        desc = (item.get("task_description") or "")[:80]
        agent = item.get("agent_name", "unknown")
        lines.append(f"{i}. <b>{agent}</b>: {desc}")

    if len(pending) > 5:
        lines.append(f"\n…and {len(pending) - 5} more.")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages — route to AI agent and reply in Telegram."""
    if not update.message or not update.message.text:
        return

    user    = update.message.from_user
    sender  = f"{user.full_name} (@{user.username})" if user else "unknown"
    question = update.message.text

    logger.info(f"[hil] question from {sender}: {question}")

    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    try:
        # Import agent routing — lazy to avoid circular imports at module load
        from agent_router import route_request, run_agent, AGENTS

        # Route to the right agent
        routing    = await asyncio.to_thread(route_request, question)
        agents     = routing.get("agents", ["sarah"])
        agent_name = agents[0]
        reasoning  = routing.get("reasoning", "")
        info       = AGENTS.get(agent_name, {"emoji": "🤖", "role": "Agent"})

        # Get the agent's answer
        answer = await asyncio.to_thread(run_agent, agent_name, question)

        # Format the reply
        reply = (
            f"{info['emoji']} <b>{agent_name.upper()}</b> — {info['role']}\n\n"
            f"{answer}\n\n"
            f"<i>— routed by AIBridge ({reasoning})</i>"
        )

        await update.message.reply_text(reply, parse_mode="HTML")
        logger.info(f"[hil] answered via {agent_name} for {sender}")

    except Exception as e:
        logger.error(f"[hil] agent routing failed: {e}")
        await update.message.reply_text(
            "⚠️ Sorry, I couldn't process that right now. Please try again.",
            parse_mode="HTML",
        )


async def start_hil_bot():
    """Start the Telegram polling bot. Call from main.py startup."""
    global _bot_app
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("[hil] TELEGRAM_BOT_TOKEN not set — HIL bot disabled")
        return

    _bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    _bot_app.add_handler(CallbackQueryHandler(handle_callback))
    _bot_app.add_handler(CommandHandler("help",   handle_help))
    _bot_app.add_handler(CommandHandler("start",  handle_help))   # /start → same as /help
    _bot_app.add_handler(CommandHandler("status", handle_status))
    _bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))

    await _bot_app.initialize()
    await _bot_app.start()
    await _bot_app.updater.start_polling(drop_pending_updates=True)
    logger.info("[hil] Telegram HIL bot started (commands: /help /status, free-text forwarding enabled)")


# ── API ───────────────────────────────────────────────────────────────────────

class HILRequest(BaseModel):
    agent_name:       str
    task_description: str
    reason:           str
    task_id:          Optional[str] = None
    priority:         int = 5


class RespondRequest(BaseModel):
    hil_id:    str
    decision:  str    # "approved" | "rejected"
    note:      Optional[str] = ""
    operator:  Optional[str] = "api"


@router.post("/request")
async def create_hil_request(req: HILRequest):
    """Create a human-in-the-loop approval request."""
    # Uses LLM to summarize for Telegram — no hardcoded provider
    prompt  = f"Agent: {req.agent_name}\nTask: {req.task_description}\nReason: {req.reason}"
    summary = chat(system=HIL_SYSTEM, user=prompt, max_tokens=150)

    hil_id = db_create_hil(
        agent_name=req.agent_name,
        task_id=req.task_id,
        task_description=req.task_description,
        reason=req.reason,
        priority=req.priority,
    )

    asyncio.create_task(
        send_hil_notification(hil_id, req.agent_name, req.task_description, req.reason, summary)
    )

    return {"hil_id": hil_id, "status": "pending", "summary": summary}


@router.get("/pending")
async def get_pending():
    return {"pending": db_get_pending()}


@router.post("/respond")
async def respond(req: RespondRequest):
    """Manually respond to a pending HIL request (without Telegram)."""
    if req.decision not in ("approved", "rejected"):
        return {"error": "decision must be 'approved' or 'rejected'"}

    db_record_decision(
        hil_id=req.hil_id,
        decision=req.decision,
        decision_by=req.operator or "api",
        decision_note=req.note or "",
    )

    cb = _pending_callbacks.pop(req.hil_id, None)
    if cb:
        asyncio.create_task(cb(req.decision, req.note or ""))

    return {"hil_id": req.hil_id, "decision": req.decision}


@router.get("/history")
async def get_history(limit: int = 20):
    return {"history": db_get_history(limit)}


# ── standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--migrate" in args:
        print("""
-- agent_hil_queue migration SQL:
CREATE TABLE IF NOT EXISTS agent_hil_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name VARCHAR(50),
    task_id UUID,
    task_description TEXT,
    reason TEXT,
    priority INT DEFAULT 5,
    status VARCHAR(20) DEFAULT 'pending',
    decision_by VARCHAR(100),
    decision_note TEXT,
    telegram_msg_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    decided_at TIMESTAMPTZ
);
""")

    elif "--test" in args:
        async def _test():
            logging.basicConfig(level=logging.INFO)
            print("[hil] sending test approval request...")
            from llm_client import active_provider
            print(f"[hil] using LLM provider: {active_provider()}")

            prompt  = "Agent: dev_etl\nTask: Drop and recreate the sales_staging table\nReason: Schema migration required for Q4 data model"
            summary = chat(
                system=HIL_SYSTEM,
                user=prompt,
                max_tokens=150,
            )
            print(f"\nSummary:\n{summary}")

        asyncio.run(_test())
    else:
        print("Usage: python hil_flow.py [--migrate | --test]")
