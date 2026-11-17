"""
agent_router.py — Natural-language to agent router (FastAPI)

Routes plain-English requests to the right Data Team agent(s),
executes in sequence or parallel, streams live progress via WebSocket.

Mount in main.py:
    from agent_router import router as agent_router
    app.include_router(agent_router, prefix="/api/agent")
"""

import os
import uuid
import json
import asyncio
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, BackgroundTasks
from pydantic import BaseModel
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Unified LLM client — no hardcoded provider
from llm_client import chat

load_dotenv()
logger    = logging.getLogger(__name__)
router    = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ── Data Team agents ─────────────────────────────────────────────────────────
AGENTS = {
    "sarah":   {"emoji": "📊", "role": "Data Analyst",    "skills": ["analysis", "reporting", "trends", "metrics", "kpi"]},
    "marcus":  {"emoji": "🎯", "role": "Strategy Analyst","skills": ["strategy", "planning", "forecast", "decision", "risk"]},
    "dev_etl": {"emoji": "🔧", "role": "ETL Engineer",    "skills": ["pipeline", "etl", "data", "load", "transform", "schema"]},
    "quinn":   {"emoji": "🛡️", "role": "Data Quality",    "skills": ["quality", "validation", "dq", "anomaly", "check", "audit"]},
    "maya":    {"emoji": "📱", "role": "Communications",  "skills": ["report", "summary", "brief", "notification", "telegram"]},
}

ROUTER_SYSTEM = """You are the AIBridge agent router.
Given a natural-language request, decide which Data Team agent(s) should handle it.

Available agents:
- sarah (📊): Data analysis, reporting, trends, KPIs
- marcus (🎯): Strategy, planning, forecasting, decisions
- dev_etl (🔧): ETL pipelines, data loading, schema changes
- quinn (🛡️): Data quality, validation, anomaly detection
- maya (📱): Communications, summaries, notifications

Respond ONLY with valid JSON in this exact format:
{
  "agents": ["agent_name"],
  "mode": "sequential",
  "reasoning": "brief explanation"
}

Use "parallel" mode only when agents are truly independent.
Pick the fewest agents that can handle the request well."""


AGENT_SYSTEM_TEMPLATE = """You are {name} {emoji}, the {role} on the AIBridge Data Team.

Your task: {task}

Provide a concise, actionable response in your area of expertise.
Be specific, reference data where relevant, and suggest next steps.
Keep your response under 300 words."""


# ── DB helpers ───────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(DATABASE_URL)


def db_create_task(request: str, agents: list, mode: str) -> str:
    task_id = str(uuid.uuid4())
    if not DATABASE_URL:
        return task_id
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO agent_tasks (id, request, agents, mode, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'pending', NOW(), NOW())
        """, (task_id, request, agents, mode))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        logger.warning(f"db_create_task: {e}")
    return task_id


def db_update_task(task_id: str, status: str, result=None, error=None):
    if not DATABASE_URL:
        return
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            UPDATE agent_tasks
            SET status=%s, result=%s, error=%s, updated_at=NOW()
            WHERE id=%s
        """, (status, json.dumps(result) if result else None, error, task_id))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        logger.warning(f"db_update_task: {e}")


def db_get_task(task_id: str) -> Optional[dict]:
    if not DATABASE_URL:
        return None
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM agent_tasks WHERE id=%s", (task_id,))
        row = cur.fetchone()
        cur.close(); conn.close()
        return dict(row) if row else None
    except Exception as e:
        logger.warning(f"db_get_task: {e}")
        return None


def db_log_error(agent_name: str, error_type: str, error_msg: str):
    if not DATABASE_URL:
        return
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO agent_errors (id, agent_name, error_type, error_message, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (str(uuid.uuid4()), agent_name, error_type, error_msg))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        logger.warning(f"db_log_error: {e}")


# ── live progress broadcast ───────────────────────────────────────────────────
_ws_connections: dict[str, list[WebSocket]] = {}


async def broadcast(task_id: str, event: dict):
    conns = _ws_connections.get(task_id, [])
    dead  = []
    for ws in conns:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        conns.remove(ws)


# ── routing + execution ───────────────────────────────────────────────────────

def route_request(request: str) -> dict:
    """Ask LLM to pick which agent(s) handle this request."""
    result = chat(system=ROUTER_SYSTEM, user=request, max_tokens=256)
    try:
        # Strip markdown fences if present
        clean = result.strip().strip("```json").strip("```").strip()
        return json.loads(clean)
    except Exception:
        # Fallback: keyword-based routing
        req_lower = request.lower()
        for agent, info in AGENTS.items():
            if any(sk in req_lower for sk in info["skills"]):
                return {"agents": [agent], "mode": "sequential", "reasoning": "keyword match"}
        return {"agents": ["sarah"], "mode": "sequential", "reasoning": "default fallback"}


async def run_agent(agent_name: str, task: str) -> str:
    """Call the LLM as a specific agent persona."""
    info   = AGENTS.get(agent_name, {"emoji": "🤖", "role": "Agent"})
    system = AGENT_SYSTEM_TEMPLATE.format(
        name=agent_name,
        emoji=info["emoji"],
        role=info["role"],
        task=task,
    )
    return chat(system=system, user=task, max_tokens=512)


async def execute_task(task_id: str, request: str, agents: list, mode: str):
    """Background task: run agents, broadcast progress, persist result."""
    db_update_task(task_id, "running")
    await broadcast(task_id, {"event": "started", "task_id": task_id, "agents": agents})

    results = {}
    errors  = {}

    if mode == "parallel":
        async def _run(name):
            try:
                await broadcast(task_id, {"event": "agent_start", "agent": name})
                r = await asyncio.to_thread(run_agent, name, request)
                results[name] = r
                await broadcast(task_id, {"event": "agent_done", "agent": name, "result": r})
            except Exception as e:
                errors[name] = str(e)
                db_log_error(name, "agent_execution", str(e))
                await broadcast(task_id, {"event": "agent_error", "agent": name, "error": str(e)})

        await asyncio.gather(*[_run(a) for a in agents])
    else:
        for agent_name in agents:
            try:
                await broadcast(task_id, {"event": "agent_start", "agent": agent_name})
                r = await asyncio.to_thread(run_agent, agent_name, request)
                results[agent_name] = r
                await broadcast(task_id, {"event": "agent_done", "agent": agent_name, "result": r})
            except Exception as e:
                errors[agent_name] = str(e)
                db_log_error(agent_name, "agent_execution", str(e))
                await broadcast(task_id, {"event": "agent_error", "agent": agent_name, "error": str(e)})

    final = {"results": results, "errors": errors, "agents": agents, "mode": mode}
    db_update_task(task_id, "completed" if not errors else "partial", result=final)
    await broadcast(task_id, {"event": "completed", "task_id": task_id, "result": final})


# ── API ──────────────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    request: str
    agents: Optional[List[str]] = None   # override auto-routing
    mode:   Optional[str]        = None  # "sequential" | "parallel"


@router.post("/ask")
async def ask(req: AskRequest, background_tasks: BackgroundTasks):
    """Submit a natural-language request → agent routing → async execution."""
    if req.agents:
        routing = {"agents": req.agents, "mode": req.mode or "sequential", "reasoning": "user specified"}
    else:
        routing = route_request(req.request)

    agents  = routing.get("agents", ["sarah"])
    mode    = routing.get("mode", "sequential")
    task_id = db_create_task(req.request, agents, mode)

    background_tasks.add_task(execute_task, task_id, req.request, agents, mode)

    return {
        "task_id":   task_id,
        "agents":    agents,
        "mode":      mode,
        "reasoning": routing.get("reasoning", ""),
        "status":    "pending",
    }


@router.get("/task/{task_id}")
async def get_task(task_id: str):
    task = db_get_task(task_id)
    if not task:
        return {"error": "Task not found"}
    return task


@router.get("/tasks")
async def list_tasks(limit: int = 20):
    if not DATABASE_URL:
        return {"tasks": []}
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM agent_tasks ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()
        return {"tasks": rows}
    except Exception as e:
        return {"error": str(e)}


@router.websocket("/stream/{task_id}")
async def stream_task(websocket: WebSocket, task_id: str):
    """Live WebSocket stream of task progress events."""
    await websocket.accept()
    _ws_connections.setdefault(task_id, []).append(websocket)
    try:
        # Send current task state immediately
        task = db_get_task(task_id)
        if task:
            await websocket.send_json({"event": "current_state", "task": task})
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        conns = _ws_connections.get(task_id, [])
        if websocket in conns:
            conns.remove(websocket)


if __name__ == "__main__":
    print("""
-- agent_tasks migration SQL:
CREATE TABLE IF NOT EXISTS agent_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request TEXT NOT NULL,
    agents TEXT[],
    mode VARCHAR(20) DEFAULT 'sequential',
    status VARCHAR(20) DEFAULT 'pending',
    result JSONB,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
""")
