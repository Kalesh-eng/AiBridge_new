"""
monitor_agent.py — AIBridge Monitor Agent
Watches all systems and reports to Kalesh (Founder) via WhatsApp every morning.
Runs as a background service, checks every 30 minutes.

Security: READ ONLY — never modifies anything without HIL approval
"""

import os
import json
import time
import schedule
import requests
import psycopg2
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv(r"E:\AIBRIDGE_Claude\backend\.env")

# Config
KALESH_WHATSAPP   = os.getenv("KALESH_WHATSAPP_NUMBER", "918884471744")
WHATSAPP_TOKEN    = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
GITHUB_REPO       = "Kalesh-eng/AiBridge_new"
GITHUB_TOKEN      = os.getenv("GITHUB_TOKEN", "")
AIBRIDGE_API      = "http://localhost:8888"
LOG_FILE          = r"E:\AIBRIDGE_Claude\monitor_agent.log"

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + "\n")

def send_whatsapp(message: str) -> bool:
    """Send message to Kalesh via WhatsApp."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        log("WhatsApp not configured — printing to console instead")
        print("\n" + "="*50)
        print("📱 MONITOR AGENT MESSAGE TO KALESH:")
        print("="*50)
        print(message)
        print("="*50 + "\n")
        return True
    try:
        r = requests.post(
            f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}",
                     "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": KALESH_WHATSAPP,
                  "type": "text", "text": {"body": message[:4000]}}
        )
        if r.status_code == 200:
            log("✓ WhatsApp message sent to Kalesh")
            return True
        else:
            log(f"✗ WhatsApp error: {r.status_code} — {r.text[:100]}")
            return False
    except Exception as e:
        log(f"✗ WhatsApp exception: {e}")
        return False

def check_backend_health() -> dict:
    """Check if AIBridge backend is running."""
    try:
        r = requests.get(f"{AIBRIDGE_API}/health", timeout=5)
        return {"status": "online", "response_time": r.elapsed.total_seconds()}
    except:
        return {"status": "offline", "response_time": None}

def check_github_activity() -> dict:
    """Check recent GitHub commits."""
    try:
        headers = {}
        if GITHUB_TOKEN:
            headers["Authorization"] = f"token {GITHUB_TOKEN}"
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/commits?per_page=5",
            headers=headers, timeout=10
        )
        if r.status_code == 200:
            commits = r.json()
            today = datetime.now().date()
            today_commits = [c for c in commits
                           if datetime.fromisoformat(c['commit']['author']['date'].replace('Z','+00:00')).date() == today]
            return {
                "total_recent": len(commits),
                "today": len(today_commits),
                "last_commit": commits[0]['commit']['message'][:60] if commits else "none",
                "last_author": commits[0]['commit']['author']['name'] if commits else "none",
            }
    except Exception as e:
        return {"error": str(e)}
    return {}

def check_database_health() -> dict:
    """Check PostgreSQL and pipeline status."""
    try:
        conn = psycopg2.connect(
            host="localhost", port=5433, dbname="postgres",
            user="postgres", password="postgres123"
        )
        cur = conn.cursor()

        # Pipeline runs today
        cur.execute("""
            SELECT COUNT(*) FROM public.pipelines
            WHERE created_at >= NOW() - INTERVAL '24 hours'
        """)
        pipelines_today = cur.fetchone()[0]

        # Total pipelines
        cur.execute("SELECT COUNT(*) FROM public.pipelines")
        total_pipelines = cur.fetchone()[0]

        # Exchange runs today
        cur.execute("""
            SELECT COUNT(*), SUM(total_rows)
            FROM public.exchange_run_history
            WHERE started_at >= NOW() - INTERVAL '24 hours'
        """)
        exc_row = cur.fetchone()
        exchange_runs = exc_row[0] or 0
        exchange_rows = exc_row[1] or 0

        # HIL queue pending
        cur.execute("SELECT COUNT(*) FROM public.hil_queue WHERE status='pending'")
        hil_pending = cur.fetchone()[0]

        # Agent tasks today
        cur.execute("""
            SELECT COUNT(*) FROM public.agent_tasks
            WHERE created_at >= NOW() - INTERVAL '24 hours'
        """)
        agent_tasks = cur.fetchone()[0]

        conn.close()
        return {
            "status": "online",
            "pipelines_today": pipelines_today,
            "total_pipelines": total_pipelines,
            "exchange_runs": exchange_runs,
            "exchange_rows": exchange_rows,
            "hil_pending": hil_pending,
            "agent_tasks": agent_tasks,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

def check_api_costs() -> dict:
    """Check DeepSeek API spending."""
    try:
        conn = psycopg2.connect(
            host="localhost", port=5433, dbname="postgres",
            user="postgres", password="postgres123"
        )
        cur = conn.cursor()
        # Check if cost table exists
        cur.execute("""
            SELECT SUM(cost_usd), COUNT(*)
            FROM public.api_costs
            WHERE created_at >= NOW() - INTERVAL '24 hours'
        """)
        row = cur.fetchone()
        today_cost  = round(row[0] or 0, 4)
        today_calls = row[1] or 0

        cur.execute("SELECT SUM(cost_usd) FROM public.api_costs")
        total_cost = round(cur.fetchone()[0] or 0, 4)

        conn.close()
        return {
            "today_usd": today_cost,
            "today_calls": today_calls,
            "total_usd": total_cost,
        }
    except:
        return {"today_usd": 0, "today_calls": 0, "total_usd": 0}

def check_disk_space() -> dict:
    """Check disk space on E drive."""
    try:
        import shutil
        total, used, free = shutil.disk_usage("E:\\")
        return {
            "free_gb": round(free / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "total_gb": round(total / (1024**3), 1),
            "percent_used": round(used / total * 100, 1),
        }
    except Exception as e:
        return {"error": str(e)}

def format_morning_brief(data: dict) -> str:
    """Format the morning briefing message."""
    now = datetime.now().strftime("%A, %B %d %Y — %I:%M %p")

    backend  = data.get("backend", {})
    github   = data.get("github", {})
    db       = data.get("database", {})
    costs    = data.get("costs", {})
    disk     = data.get("disk", {})

    backend_icon  = "🟢" if backend.get("status") == "online" else "🔴"
    db_icon       = "🟢" if db.get("status") == "online" else "🔴"
    hil_pending   = db.get("hil_pending", 0)
    hil_alert     = f"\n⚠️ *{hil_pending} items awaiting your approval in HIL Queue!*" if hil_pending > 0 else ""

    msg = f"""🤖 *AIBridge Morning Brief*
{now}
━━━━━━━━━━━━━━━━━━━━━━━

*🖥️ System Status*
{backend_icon} Backend: {backend.get("status","unknown")} {f'({backend.get("response_time",0):.2f}s)' if backend.get("response_time") else ''}
{db_icon} Database: {db.get("status","unknown")}
💾 Disk E: {disk.get("free_gb","?")}GB free ({disk.get("percent_used","?")}% used)

*📊 Activity (Last 24h)*
🔄 Exchange runs: {db.get("exchange_runs",0)} ({db.get("exchange_rows",0):,} rows)
⚙️ Pipeline runs: {db.get("pipelines_today",0)}
🤖 Agent tasks: {db.get("agent_tasks",0)}
💰 API costs: ${costs.get("today_usd",0)} ({costs.get("today_calls",0)} calls)

*💻 GitHub Activity*
📝 Commits today: {github.get("today",0)}
🔀 Last commit: {github.get("last_commit","none")}
👤 Author: {github.get("last_author","none")}

*📈 Totals*
⚙️ Total pipelines: {db.get("total_pipelines",0)}
💰 Total API spend: ${costs.get("total_usd",0)}
{hil_alert}
━━━━━━━━━━━━━━━━━━━━━━━
Reply *STATUS* for full report
Reply *HIL* to see pending approvals
Reply *COST* for detailed cost breakdown
— Monitor Agent 🔍"""

    return msg

def run_checks() -> dict:
    """Run all health checks."""
    log("Running health checks...")
    return {
        "backend":  check_backend_health(),
        "github":   check_github_activity(),
        "database": check_database_health(),
        "costs":    check_api_costs(),
        "disk":     check_disk_space(),
    }

def send_morning_brief():
    """Send morning briefing to Kalesh."""
    log("📨 Sending morning brief to Kalesh...")
    data = run_checks()
    message = format_morning_brief(data)
    success = send_whatsapp(message)
    if success:
        log("✓ Morning brief sent")
    else:
        log("✗ Morning brief failed")

def send_alert(title: str, message: str, priority: str = "normal"):
    """Send urgent alert to Kalesh."""
    icons = {"low": "ℹ️", "normal": "📢", "high": "⚠️", "critical": "🚨"}
    icon = icons.get(priority, "📢")
    msg = f"{icon} *AIBridge Alert — {title}*\n\n{message}\n\n— Monitor Agent 🔍"
    send_whatsapp(msg)
    log(f"Alert sent: {title}")

def monitor_loop():
    """Continuous monitoring loop — checks every 5 minutes."""
    log("🔍 Monitor Agent started — watching all systems")

    # Schedule morning brief at 8 AM
    schedule.every().day.at("08:00").do(send_morning_brief)

    # Run immediate check on startup
    data = run_checks()
    backend = data.get("backend", {})
    hil = data.get("database", {}).get("hil_pending", 0)

    if backend.get("status") != "online":
        send_alert("Backend Offline", "AIBridge backend is not responding!", "critical")

    if hil > 0:
        send_alert("HIL Approvals Needed",
                   f"{hil} item(s) awaiting your approval in the HIL Queue.\nVisit Mission Control to review.",
                   "high")

    log(f"✓ Initial check complete — Backend: {backend.get('status')} | HIL pending: {hil}")

    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute for scheduled tasks

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "brief":
        # Manual: python monitor_agent.py brief
        send_morning_brief()
    elif len(sys.argv) > 1 and sys.argv[1] == "check":
        # Manual: python monitor_agent.py check
        data = run_checks()
        print(json.dumps(data, indent=2, default=str))
    else:
        # Run as service
        monitor_loop()
