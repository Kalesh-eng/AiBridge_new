"""
agent_bus.py — Agent-to-agent message bus (FastAPI)

Agents send/receive typed messages through a shared bus backed by PostgreSQL.
Subscribers get live updates via WebSocket.

Mount in main.py:
    from agent_bus import router as bus_router, start_bus
    app.include_router(bus_router, prefix="/api/bus")

    @app.on_event("startup")
    async def startup():
        await start_bus()
"""

import os
import uuid
import json
import asyncio
import logging
from typing import Optional, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Unified LLM client — no hardcoded provider
from llm_client import chat

load_dotenv()
logger = logging.getLogger(__name__)
router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ── agent definitions ─────────────────────────────────────────────────────────
AGENTS = {
    "sarah":   {"emoji": "📊", "role": "Data Analyst"},
    "marcus":  {"emoji": "🎯", "role": "Strategy Analyst"},
    "dev_etl": {"emoji": "🔧", "role": "ETL Engineer"},
    "quinn":   {"emoji": "🛡️", "role": "Data Quality"},
    "maya":    {"emoji": "📱", "role": "Communications"},
}

AGENT_SYSTEM_TEMPLATE = """You are {name} {emoji}, the {role} on the AIBridge Data Team.

You have received a message from {from_agent}:
{message}

Respond helpfully in your area of expertise. Be concise (under 200 words).
If this requires another agent's expertise, mention who should handle it next."""

# ── live subscriptions ────────────────────────────────────────────────────────
_subscribers: dict[str, list[WebSocket]] = {}  # agent_name -> [websockets]


async def publish_to_agent(agent_name: str, event: dict):
    """Push event to all WebSocket subscribers for an agent."""
    conns = _subscribers.get(agent_name, [])
    dead  = []
    for ws in conns:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        conns.remove(ws)


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(DATABASE_URL)


def db_save_message(msg_id, thread_id, from_agent, to_agent,
                    msg_type, content, metadata, parent_id=None) -> bool:
    if not DATABASE_URL:
        return True
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO agent_messages
              (id, thread_id, from_agent, to_agent, message_type,
               content, metadata, status, parent_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'sent', %s, NOW())
        """, (msg_id, thread_id, from_agent, to_agent, msg_type,
              content, json.dumps(metadata or {}), parent_id))
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        logger.warning(f"db_save_message: {e}")
        return False


def db_get_thread(thread_id: str) -> list:
    if not DATABASE_URL:
        return []
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM agent_messages
            WHERE thread_id=%s
            ORDER BY created_at ASC
        """, (thread_id,))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()
        return rows
    except Exception as e:
        logger.warning(f"db_get_thread: {e}")
        return []


def db_get_inbox(agent_name: str, limit: int = 20) -> list:
    if not DATABASE_URL:
        return []
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM agent_messages
            WHERE to_agent=%s
            ORDER BY created_at DESC LIMIT %s
        """, (agent_name, limit))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()
        return rows
    except Exception as e:
        logger.warning(f"db_get_inbox: {e}")
        return []


# ── agent auto-reply ──────────────────────────────────────────────────────────

async def agent_auto_reply(to_agent: str, from_agent: str,
                           thread_id: str, original_msg: str):
    """Let the receiving agent generate a reply via LLM."""
    info = AGENTS.get(to_agent, {"emoji": "🤖", "role": "Agent"})
    system = AGENT_SYSTEM_TEMPLATE.format(
        name=to_agent,
        emoji=info["emoji"],
        role=info["role"],
        from_agent=from_agent,
        message=original_msg,
    )

    try:
        # Uses LLM_PROVIDER from .env — no hardcoded provider
        reply_text = await asyncio.to_thread(
            chat, system, original_msg, 400
        )

        reply_id = str(uuid.uuid4())
        db_save_message(
            msg_id=reply_id,
            thread_id=thread_id,
            from_agent=to_agent,
            to_agent=from_agent,
            msg_type="reply",
            content=reply_text,
            metadata={"auto_reply": True},
        )

        event = {
            "event":     "new_message",
            "id":        reply_id,
            "thread_id": thread_id,
            "from":      to_agent,
            "to":        from_agent,
            "content":   reply_text,
        }
        await publish_to_agent(from_agent, event)
        await publish_to_agent(to_agent,   event)

    except Exception as e:
        logger.error(f"[agent_bus] auto-reply failed for {to_agent}: {e}")


# ── API ───────────────────────────────────────────────────────────────────────

class SendRequest(BaseModel):
    from_agent:   str
    to_agent:     str
    content:      str
    message_type: str = "task"
    thread_id:    Optional[str] = None
    metadata:     Optional[dict] = None


@router.post("/send")
async def send_message(req: SendRequest):
    """Send a message between agents; triggers auto-reply if to_agent is known."""
    msg_id    = str(uuid.uuid4())
    thread_id = req.thread_id or str(uuid.uuid4())

    db_save_message(
        msg_id=msg_id,
        thread_id=thread_id,
        from_agent=req.from_agent,
        to_agent=req.to_agent,
        msg_type=req.message_type,
        content=req.content,
        metadata=req.metadata,
    )

    event = {
        "event":     "new_message",
        "id":        msg_id,
        "thread_id": thread_id,
        "from":      req.from_agent,
        "to":        req.to_agent,
        "content":   req.content,
    }
    await publish_to_agent(req.to_agent,   event)
    await publish_to_agent(req.from_agent, event)

    # Trigger auto-reply if to_agent is a known agent
    if req.to_agent in AGENTS:
        asyncio.create_task(
            agent_auto_reply(req.to_agent, req.from_agent, thread_id, req.content)
        )

    return {"message_id": msg_id, "thread_id": thread_id, "status": "sent"}


@router.get("/thread/{thread_id}")
async def get_thread(thread_id: str):
    return {"thread_id": thread_id, "messages": db_get_thread(thread_id)}


@router.get("/inbox/{agent_name}")
async def get_inbox(agent_name: str, limit: int = 20):
    return {"agent": agent_name, "messages": db_get_inbox(agent_name, limit)}


@router.get("/agents")
async def list_agents():
    return {"agents": AGENTS}


@router.websocket("/live/{agent_name}")
async def live_stream(websocket: WebSocket, agent_name: str):
    """WebSocket: subscribe to live messages for an agent."""
    await websocket.accept()
    _subscribers.setdefault(agent_name, []).append(websocket)
    try:
        # Send recent inbox on connect
        inbox = db_get_inbox(agent_name, limit=10)
        await websocket.send_json({"event": "inbox", "messages": inbox})
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        conns = _subscribers.get(agent_name, [])
        if websocket in conns:
            conns.remove(websocket)


# ── startup ───────────────────────────────────────────────────────────────────

async def start_bus():
    """Call from main.py startup event."""
    logger.info("[agent_bus] bus started — %d agents registered", len(AGENTS))


if __name__ == "__main__":
    print("""
-- agent_messages migration SQL:
CREATE TABLE IF NOT EXISTS agent_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID,
    from_agent VARCHAR(50),
    to_agent VARCHAR(50),
    message_type VARCHAR(20) DEFAULT 'task',
    content TEXT,
    metadata JSONB,
    status VARCHAR(20) DEFAULT 'sent',
    parent_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
""")


# ── legacy register() compat for main.py ws_agents ───────────────────────────
# Keeps main.py's direct agent_bus.register(websocket) calls working.
# Subscribes the websocket to the "broadcast" channel so it receives
# all agent message events.

_broadcast_sockets: list = []

def register(websocket):
    """Register a WebSocket for broadcast updates (called from main.py)."""
    _broadcast_sockets.append(websocket)


async def broadcast_to_all(event: dict):
    """Push event to all broadcast-registered sockets."""
    dead = []
    for ws in _broadcast_sockets:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _broadcast_sockets.remove(ws)
