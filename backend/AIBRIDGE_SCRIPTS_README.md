# AIBridge Backend Scripts

Drop these files into your `backend/` folder.

---

## Files

| File | What it does |
|------|-------------|
| `morning_brief.py` | Daily 7am IST Telegram brief with overnight stats |
| `agent_router.py` | FastAPI router — natural language → right agent |
| `agent_bus.py` | Agent-to-agent message bus with WS streaming |
| `pipeline_monitor.py` | Self-healing monitor — detects & auto-fixes failures |
| `hil_flow.py` | Telegram HIL approval with Approve/Reject buttons |
| `requirements_aibridge.txt` | All Python dependencies |

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements_aibridge.txt --break-system-packages
```

### 2. .env file (add to your existing .env)
```env
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_IDS=chat_id_1,chat_id_2

# Anthropic
ANTHROPIC_API_KEY=your_key

# PostgreSQL (if different from defaults)
PG_HOST=localhost
PG_PORT=5432
PG_DB=aibridge
PG_USER=bhaskerbobby
PG_PASSWORD=

# Optional tuning
BRIEF_HOUR_IST=7
BRIEF_MINUTE=0
MONITOR_INTERVAL_MIN=5
STALL_THRESHOLD_MIN=30
MAX_AUTO_RETRIES=3
```

### 3. Wire into main.py
```python
from agent_router import router as agent_router
from agent_bus    import router as bus_router, start_bus
from hil_flow     import router as hil_router, start_hil_bot

app.include_router(agent_router, prefix="/api/agent")
app.include_router(bus_router,   prefix="/api/bus")
app.include_router(hil_router,   prefix="/api/hil")

@app.on_event("startup")
async def startup():
    await start_bus()
    await start_hil_bot()
```

### 4. Run background daemons (separate terminals or systemd services)
```bash
# Morning brief daemon
python morning_brief.py

# Pipeline monitor daemon  
python pipeline_monitor.py

# HIL Telegram bot (if NOT wired into main.py startup)
python hil_flow.py
```

---

## DB migrations
Run in psql before first use:
```sql
-- From agent_router.py (print it with: python agent_router.py)
ALTER TABLE agent_tasks
    ADD COLUMN IF NOT EXISTS id             VARCHAR(36) DEFAULT gen_random_uuid()::text,
    ADD COLUMN IF NOT EXISTS parent_task_id VARCHAR(36),
    ADD COLUMN IF NOT EXISTS task_type      VARCHAR(50) DEFAULT 'general',
    ADD COLUMN IF NOT EXISTS records_processed BIGINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS result         TEXT,
    ADD COLUMN IF NOT EXISTS error_message  TEXT,
    ADD COLUMN IF NOT EXISTS completed_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at     TIMESTAMPTZ DEFAULT NOW();

CREATE TABLE IF NOT EXISTS agent_anomalies (
    id SERIAL PRIMARY KEY, agent_name VARCHAR(100),
    description TEXT, severity VARCHAR(20) DEFAULT 'medium',
    resolved BOOLEAN DEFAULT FALSE, created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_errors (
    id SERIAL PRIMARY KEY, agent_name VARCHAR(100),
    error_message TEXT, task_id VARCHAR(36),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- agent_bus creates agent_messages on startup
-- hil_flow creates agent_hil_queue on startup
-- pipeline_monitor creates pipeline_incidents on startup
```

---

## Quick tests

```bash
# Test morning brief (dry run — prints without sending)
python morning_brief.py --dry-run

# Test pipeline monitor (one check)
python pipeline_monitor.py --check

# Test HIL flow (sends a test Telegram message)
python hil_flow.py --test

# Test NL router (see the migration SQL)
python agent_router.py
```

---

## API endpoints summary

```
POST /api/agent/ask              Natural language → agent routing
GET  /api/agent/task/{id}        Poll task status
GET  /api/agent/tasks            List recent tasks
WS   /api/agent/stream/{id}      Live task updates

POST /api/bus/send               Agent sends message to another agent
GET  /api/bus/thread/{id}        Full collaboration thread
GET  /api/bus/inbox/{agent}      Pending messages for an agent
WS   /api/bus/live/{agent}       Live message stream for an agent

POST /api/hil/request            Request human approval
GET  /api/hil/pending            All pending approvals
POST /api/hil/respond            Programmatic approve/reject (testing)
GET  /api/hil/history            Approval history
```
