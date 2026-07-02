"""
run_registry.py — In-memory tracking for background pipeline executions.

Supports:
  - Background execution (pipeline runs in a thread, HTTP request returns
    immediately with a run_id instead of blocking until completion)
  - Live log streaming (SSE endpoint polls each run's log buffer)
  - Stop (finish current step cleanly, then halt)
  - Abort (kill immediately, rollback partial warehouse writes)
  - Restart (re-run from scratch after completion/failure)
"""

import threading
import time
import uuid
from datetime import datetime, timezone

_lock = threading.Lock()
_runs = {}  # run_id -> run dict


def create_run(pipeline_id: str, pipeline_name: str = "") -> str:
    """Create a new tracked run and return its run_id."""
    run_id = f"{pipeline_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    with _lock:
        _runs[run_id] = {
            "run_id":           run_id,
            "pipeline_id":      pipeline_id,
            "pipeline_name":    pipeline_name,
            "status":           "running",   # running | stopping | aborting | stopped | aborted | success | failed
            "logs":             [],
            "cancel_requested": False,
            "abort_requested":  False,
            "result":           None,
            "error":            None,
            "started_at":       datetime.now(timezone.utc).isoformat(),
            "ended_at":         None,
        }
    return run_id


def get_run(run_id: str) -> dict | None:
    with _lock:
        run = _runs.get(run_id)
        return dict(run) if run else None


def append_log(run_id: str, line: str) -> None:
    """Thread-safe log append. Each line is timestamped for the stream."""
    ts = datetime.now().strftime("%H:%M:%S")
    with _lock:
        run = _runs.get(run_id)
        if run is not None:
            run["logs"].append(f"[{ts}] {line}")


def get_logs_since(run_id: str, offset: int) -> tuple[list, int]:
    """Return (new_log_lines, new_offset) for incremental SSE polling."""
    with _lock:
        run = _runs.get(run_id)
        if run is None:
            return [], offset
        logs = run["logs"]
        new_lines = logs[offset:]
        return new_lines, len(logs)


def request_stop(run_id: str) -> bool:
    """Signal a running execution to stop cleanly at its next checkpoint."""
    with _lock:
        run = _runs.get(run_id)
        if run is None:
            return False
        if run["status"] not in ("running",):
            return False
        run["cancel_requested"] = True
        run["status"] = "stopping"
        return True


def request_abort(run_id: str) -> bool:
    """Signal a running execution to abort immediately and rollback warehouse writes."""
    with _lock:
        run = _runs.get(run_id)
        if run is None:
            return False
        if run["status"] not in ("running", "stopping"):
            return False
        run["abort_requested"]  = True
        run["cancel_requested"] = True  # also set stop so all checkpoints fire
        run["status"] = "aborting"
        return True


def should_stop(run_id: str) -> bool:
    """Checked by the execution loop between scripts/chunks."""
    with _lock:
        run = _runs.get(run_id)
        return bool(run and run.get("cancel_requested"))


def should_abort(run_id: str) -> bool:
    """Checked to determine if a full rollback is needed."""
    with _lock:
        run = _runs.get(run_id)
        return bool(run and run.get("abort_requested"))


def finish_run(run_id: str, status: str, result: dict = None, error: str = None) -> None:
    """Mark a run as finished — status is one of success | failed | stopped | aborted."""
    with _lock:
        run = _runs.get(run_id)
        if run is not None:
            run["status"]   = status
            run["result"]   = result
            run["error"]    = error
            run["ended_at"] = datetime.now(timezone.utc).isoformat()


def cleanup_old_runs(max_age_seconds: int = 3600) -> None:
    """Drop finished runs older than max_age_seconds to bound memory growth."""
    now = time.time()
    with _lock:
        to_remove = []
        for run_id, run in _runs.items():
            if run["status"] in ("success", "failed", "stopped", "aborted") and run["ended_at"]:
                try:
                    ended = datetime.fromisoformat(run["ended_at"]).timestamp()
                    if now - ended > max_age_seconds:
                        to_remove.append(run_id)
                except Exception:
                    pass
        for run_id in to_remove:
            del _runs[run_id]