"""
ai_provider.py
Handles all AI providers: Ollama, Claude, OpenAI, Gemini, DeepSeek.
Set AI_PROVIDER in .env to switch. No other file needs to change.

v1.5 IMPROVEMENTS:
- AI Cost Tracking: every ask_ai() call now records tokens used and USD cost
  in a SQLite cost log (aibridge_costs.db alongside the main DB), so the
  /cost/* endpoints can return per-call, per-pipeline, and total spend.
- DeepSeek peak/off-peak pricing: peak hours UTC 1-4 AM and 6-10 AM incur
  2x the regular rate (DeepSeek announcement, mid-July 2026).
- ask_ai() accepts optional pipeline_id and agent_name kwargs for attribution.
- Cache hits ($0 AI cost) are recorded with tokens=0, cost_usd=0.

v1.4 IMPROVEMENTS:
- Added DeepSeek V3 support (deepseek-chat model)
- DeepSeek uses OpenAI-compatible API — very cheap (~$0.002/design)

v1.3 IMPROVEMENTS:
- Claude: switched to claude-haiku-4-5 (fastest, cheapest)
- Claude: added system prompt for JSON-only responses

v1.2 IMPROVEMENTS:
- Gemini: max_output_tokens increased to 8192
- _parse(): added Strategy 5 — truncated JSON recovery
"""

import os
import re
import json
import time
import sqlite3
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

PROVIDER       = os.getenv("AI_PROVIDER",    "ollama").lower()
OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL",   "qwen2.5:3b")
OLLAMA_URL     = os.getenv("OLLAMA_URL",     "http://127.0.0.1:11434")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "600"))

def _display_model():
    if PROVIDER == "claude":    return "claude-haiku-4-5"
    if PROVIDER == "anthropic": return "claude-haiku-4-5"
    if PROVIDER == "gemini":    return "gemini-2.5-flash"
    if PROVIDER == "openai":    return "gpt-4o-mini"
    if PROVIDER == "deepseek":  return "deepseek-chat"
    return OLLAMA_MODEL

_model = _display_model()
print(f"╔════════════════════════════════════════════════╗")
print(f"║ [AI Provider] Active:  {PROVIDER:30s}║")
print(f"║ [AI Provider] Model:   {_model:30s}║")
print(f"║ [AI Provider] Timeout: {OLLAMA_TIMEOUT}s{' '*(30-len(str(OLLAMA_TIMEOUT))-1)}║")
print(f"╚════════════════════════════════════════════════╝")


# ── Cost tracking ─────────────────────────────────────────────────────────────
#
# Stored in a dedicated SQLite file (aibridge_costs.db) so cost data survives
# independently of the main application DB and doesn't require a migration.
# All writes are thread-safe via a module-level lock.

_COST_DB_PATH = os.getenv("COST_DB_PATH", "./aibridge_costs.db")
_cost_lock    = threading.Lock()

# DeepSeek V3 pricing (USD per 1M tokens) — peak/off-peak aware.
# Source: DeepSeek announcement, applicable mid-July 2026 onward.
# Peak hours in UTC: 01:00-04:00 and 06:00-10:00 (2× regular rate).
_PRICING = {
    "deepseek": {
        # Regular (off-peak) rates
        "input_per_m":        0.27,   # cache miss
        "input_cached_per_m": 0.07,   # cache hit (context caching)
        "output_per_m":       1.10,
        # Peak multiplier (applied during peak hours)
        "peak_multiplier":    2.0,
        # Peak windows in UTC: list of (start_hour, end_hour) half-open intervals
        "peak_windows":       [(1, 4), (6, 10)],
    },
    "claude": {
        # Claude Haiku 4.5 pricing (USD per 1M tokens)
        "input_per_m":        0.80,
        "input_cached_per_m": 0.08,
        "output_per_m":       4.00,
        "peak_multiplier":    1.0,
        "peak_windows":       [],
    },
    "openai": {
        # GPT-4o-mini pricing
        "input_per_m":        0.15,
        "input_cached_per_m": 0.075,
        "output_per_m":       0.60,
        "peak_multiplier":    1.0,
        "peak_windows":       [],
    },
    "gemini": {
        # Gemini 2.5 Flash pricing
        "input_per_m":        0.075,
        "input_cached_per_m": 0.0188,
        "output_per_m":       0.30,
        "peak_multiplier":    1.0,
        "peak_windows":       [],
    },
    "ollama": {
        # Local model — no cost
        "input_per_m":        0.0,
        "input_cached_per_m": 0.0,
        "output_per_m":       0.0,
        "peak_multiplier":    1.0,
        "peak_windows":       [],
    },
}


def _is_peak_hour(provider: str) -> bool:
    """Check if the current UTC time falls within a peak billing window."""
    pricing = _PRICING.get(provider, {})
    windows = pricing.get("peak_windows", [])
    if not windows:
        return False
    utc_hour = datetime.now(timezone.utc).hour
    return any(start <= utc_hour < end for start, end in windows)


def _calculate_cost(provider: str, input_tokens: int, output_tokens: int,
                    cached_input_tokens: int = 0) -> float:
    """Calculate USD cost for a single API call."""
    pricing = _PRICING.get(provider, _PRICING["ollama"])
    multiplier = pricing["peak_multiplier"] if _is_peak_hour(provider) else 1.0

    cost = (
        (input_tokens - cached_input_tokens) / 1_000_000 * pricing["input_per_m"] +
        cached_input_tokens                  / 1_000_000 * pricing["input_cached_per_m"] +
        output_tokens                        / 1_000_000 * pricing["output_per_m"]
    ) * multiplier

    return round(cost, 8)


def _ensure_cost_db():
    """Create cost log table if it doesn't exist."""
    with _cost_lock:
        con = sqlite3.connect(_COST_DB_PATH)
        con.execute("""
            CREATE TABLE IF NOT EXISTS cost_log (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                ts                  TEXT    NOT NULL,
                provider            TEXT    NOT NULL,
                model               TEXT    NOT NULL,
                agent_name          TEXT,
                pipeline_id         TEXT,
                input_tokens        INTEGER DEFAULT 0,
                output_tokens       INTEGER DEFAULT 0,
                cached_input_tokens INTEGER DEFAULT 0,
                total_tokens        INTEGER DEFAULT 0,
                cost_usd            REAL    DEFAULT 0,
                is_peak             INTEGER DEFAULT 0,
                is_cache_hit        INTEGER DEFAULT 0,
                prompt_chars        INTEGER DEFAULT 0,
                response_chars      INTEGER DEFAULT 0,
                duration_s          REAL    DEFAULT 0
            )
        """)
        con.commit()
        con.close()


def _record_cost(provider: str, model: str, input_tokens: int, output_tokens: int,
                 cached_input_tokens: int = 0, agent_name: str = None,
                 pipeline_id: str = None, is_cache_hit: bool = False,
                 prompt_chars: int = 0, response_chars: int = 0,
                 duration_s: float = 0.0):
    """Write one cost record to the SQLite cost log. Thread-safe."""
    try:
        cost    = _calculate_cost(provider, input_tokens, output_tokens, cached_input_tokens)
        is_peak = _is_peak_hour(provider)
        ts      = datetime.now(timezone.utc).isoformat()

        with _cost_lock:
            con = sqlite3.connect(_COST_DB_PATH)
            con.execute("""
                INSERT INTO cost_log
                  (ts, provider, model, agent_name, pipeline_id,
                   input_tokens, output_tokens, cached_input_tokens, total_tokens,
                   cost_usd, is_peak, is_cache_hit, prompt_chars, response_chars, duration_s)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (ts, provider, model, agent_name, pipeline_id,
                  input_tokens, output_tokens, cached_input_tokens,
                  input_tokens + output_tokens,
                  cost, int(is_peak), int(is_cache_hit),
                  prompt_chars, response_chars, duration_s))
            con.commit()
            con.close()

        peak_tag = " [PEAK 2×]" if is_peak else ""
        print(f"[Cost] {provider} | {input_tokens}in + {output_tokens}out tokens "
              f"| ${cost:.6f}{peak_tag}"
              + (f" | {agent_name}" if agent_name else "")
              + (f" | pipeline={pipeline_id}" if pipeline_id else ""))
    except Exception as e:
        print(f"[Cost] Could not record cost: {e}")


def get_cost_summary(pipeline_id: str = None, days: int = 30) -> dict:
    """Return cost summary — optionally filtered by pipeline and time window."""
    try:
        _ensure_cost_db()
        with _cost_lock:
            con = sqlite3.connect(_COST_DB_PATH)
            cur = con.cursor()

            where_clauses = [f"ts >= datetime('now', '-{days} days')"]
            params = []
            if pipeline_id:
                where_clauses.append("pipeline_id = ?")
                params.append(pipeline_id)
            where = " AND ".join(where_clauses)

            cur.execute(f"""
                SELECT
                    COUNT(*)                          AS calls,
                    SUM(total_tokens)                 AS total_tokens,
                    SUM(input_tokens)                 AS input_tokens,
                    SUM(output_tokens)                AS output_tokens,
                    SUM(cost_usd)                     AS total_cost,
                    SUM(CASE WHEN is_peak=1 THEN cost_usd ELSE 0 END) AS peak_cost,
                    SUM(CASE WHEN is_cache_hit=1 THEN 1 ELSE 0 END)   AS cache_hits,
                    SUM(CASE WHEN is_cache_hit=0 THEN cost_usd ELSE 0 END) AS ai_cost
                FROM cost_log WHERE {where}
            """, params)
            row = cur.fetchone()

            # Per-agent breakdown
            cur.execute(f"""
                SELECT agent_name, COUNT(*), SUM(total_tokens), SUM(cost_usd)
                FROM cost_log WHERE {where} AND agent_name IS NOT NULL
                GROUP BY agent_name ORDER BY SUM(cost_usd) DESC
            """, params)
            agents = [{"agent": r[0], "calls": r[1], "tokens": r[2],
                       "cost_usd": round(r[3] or 0, 6)} for r in cur.fetchall()]

            # Per-provider breakdown
            cur.execute(f"""
                SELECT provider, COUNT(*), SUM(total_tokens), SUM(cost_usd)
                FROM cost_log WHERE {where}
                GROUP BY provider ORDER BY SUM(cost_usd) DESC
            """, params)
            providers = [{"provider": r[0], "calls": r[1], "tokens": r[2],
                          "cost_usd": round(r[3] or 0, 6)} for r in cur.fetchall()]

            # Daily trend (last 14 days)
            cur.execute(f"""
                SELECT date(ts) AS day, SUM(cost_usd), SUM(total_tokens), COUNT(*)
                FROM cost_log WHERE {where}
                GROUP BY day ORDER BY day DESC LIMIT 14
            """, params)
            daily = [{"date": r[0], "cost_usd": round(r[1] or 0, 6),
                      "tokens": r[2], "calls": r[3]} for r in cur.fetchall()]

            con.close()

        return {
            "calls":        row[0] or 0,
            "total_tokens": row[1] or 0,
            "input_tokens": row[2] or 0,
            "output_tokens":row[3] or 0,
            "total_cost":   round(row[4] or 0, 6),
            "peak_cost":    round(row[5] or 0, 6),
            "cache_hits":   row[6] or 0,
            "ai_cost":      round(row[7] or 0, 6),
            "by_agent":     agents,
            "by_provider":  providers,
            "daily_trend":  daily,
            "days":         days,
            "pipeline_id":  pipeline_id,
        }
    except Exception as e:
        print(f"[Cost] get_cost_summary error: {e}")
        return {"calls": 0, "total_tokens": 0, "total_cost": 0, "error": str(e)}


def get_recent_calls(limit: int = 50, pipeline_id: str = None) -> list:
    """Return the most recent individual AI calls for the cost log page."""
    try:
        _ensure_cost_db()
        with _cost_lock:
            con = sqlite3.connect(_COST_DB_PATH)
            cur = con.cursor()
            if pipeline_id:
                cur.execute("""
                    SELECT ts, provider, model, agent_name, pipeline_id,
                           input_tokens, output_tokens, total_tokens, cost_usd,
                           is_peak, is_cache_hit, duration_s
                    FROM cost_log WHERE pipeline_id = ?
                    ORDER BY id DESC LIMIT ?
                """, (pipeline_id, limit))
            else:
                cur.execute("""
                    SELECT ts, provider, model, agent_name, pipeline_id,
                           input_tokens, output_tokens, total_tokens, cost_usd,
                           is_peak, is_cache_hit, duration_s
                    FROM cost_log ORDER BY id DESC LIMIT ?
                """, (limit,))
            rows = cur.fetchall()
            con.close()
        return [
            {"ts": r[0], "provider": r[1], "model": r[2], "agent_name": r[3],
             "pipeline_id": r[4], "input_tokens": r[5], "output_tokens": r[6],
             "total_tokens": r[7], "cost_usd": round(r[8] or 0, 6),
             "is_peak": bool(r[9]), "is_cache_hit": bool(r[10]),
             "duration_s": round(r[11] or 0, 2)}
            for r in rows
        ]
    except Exception as e:
        print(f"[Cost] get_recent_calls error: {e}")
        return []


# Initialise DB on import
try:
    _ensure_cost_db()
except Exception:
    pass


def ask_ai(prompt: str, agent_name: str = None, pipeline_id: str = None) -> dict:
    """
    Send prompt to the configured AI provider. Returns parsed JSON dict.
    Automatically records token usage and USD cost to the cost log.
    Pass agent_name and pipeline_id for per-agent/per-pipeline attribution.
    """
    p = PROVIDER
    if p in ("claude", "anthropic"):
        return _ask_claude(prompt, agent_name=agent_name, pipeline_id=pipeline_id)
    elif p == "openai":
        return _ask_openai(prompt, agent_name=agent_name, pipeline_id=pipeline_id)
    elif p == "gemini":
        return _ask_gemini(prompt, agent_name=agent_name, pipeline_id=pipeline_id)
    elif p == "deepseek":
        return _ask_deepseek(prompt, agent_name=agent_name, pipeline_id=pipeline_id)
    elif p == "ollama":
        return _ask_ollama(prompt, agent_name=agent_name, pipeline_id=pipeline_id)
    else:
        raise ValueError(f"Unknown AI_PROVIDER: {PROVIDER}")


# ── Claude (Anthropic) ────────────────────────────────────────────────────────

def _ask_claude(prompt: str, agent_name: str = None, pipeline_id: str = None) -> dict:
    try:
        import anthropic
    except ImportError:
        print("[Claude] anthropic package not installed. Run: pip install anthropic")
        return _empty()

    start = time.time()
    print(f"[Claude] → Sending prompt ({len(prompt)} chars)...")

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    try:
        msg = client.messages.create(
            model      = "claude-haiku-4-5",
            max_tokens = 8000,
            system     = (
                "You are a JSON-only API. Always respond with ONE valid JSON object. "
                "Start your response with { and end with }. "
                "No markdown, no explanations, no extra text outside the JSON. "
                "Your entire response must be parseable by json.loads()."
            ),
            messages=[{"role": "user", "content": prompt}]
        )
        elapsed = time.time() - start
        text    = msg.content[0].text if msg.content else ""
        in_tok  = msg.usage.input_tokens  if msg.usage else 0
        out_tok = msg.usage.output_tokens if msg.usage else 0
        print(f"[Claude] ← Done in {elapsed:.1f}s ({len(text)} chars, {in_tok}in+{out_tok}out tokens)")
        _record_cost("claude", "claude-haiku-4-5", in_tok, out_tok,
                     agent_name=agent_name, pipeline_id=pipeline_id,
                     prompt_chars=len(prompt), response_chars=len(text), duration_s=elapsed)
        return _parse(text)

    except Exception as e:
        elapsed = time.time() - start
        print(f"[Claude] ✗ Error after {elapsed:.1f}s: {e}")
        return _empty()


# ── DeepSeek ──────────────────────────────────────────────────────────────────

def _ask_deepseek(prompt: str, agent_name: str = None, pipeline_id: str = None) -> dict:
    """
    DeepSeek V3 via OpenAI-compatible API.
    Peak/off-peak pricing: UTC 01-04 and 06-10 → 2× regular rate.
    """
    try:
        from openai import OpenAI
    except ImportError:
        print("[DeepSeek] openai package not installed. Run: pip install openai")
        return _empty()

    start = time.time()
    print(f"[DeepSeek] → Sending prompt ({len(prompt)} chars)...")

    client = OpenAI(
        api_key  = os.getenv("DEEPSEEK_API_KEY"),
        base_url = "https://api.deepseek.com"
    )

    try:
        response = client.chat.completions.create(
            model       = "deepseek-chat",
            max_tokens  = 8000,
            temperature = 0.1,
            messages    = [
                {
                    "role":    "system",
                    "content": (
                        "You are a JSON-only API. Always respond with ONE valid JSON object. "
                        "Start your response with { and end with }. "
                        "No markdown, no explanations, no extra text outside the JSON. "
                        "Your entire response must be parseable by json.loads()."
                    )
                },
                {
                    "role":    "user",
                    "content": prompt
                }
            ]
        )
        elapsed  = time.time() - start
        text     = response.choices[0].message.content or ""
        in_tok   = response.usage.prompt_tokens     if response.usage else 0
        out_tok  = response.usage.completion_tokens if response.usage else 0
        # DeepSeek returns cached_tokens inside prompt_tokens_details if available
        cached   = getattr(getattr(response.usage, 'prompt_tokens_details', None),
                           'cached_tokens', 0) or 0
        peak_tag = " [PEAK 2×]" if _is_peak_hour("deepseek") else ""
        print(f"[DeepSeek] ← Done in {elapsed:.1f}s "
              f"({len(text)} chars, {in_tok}in+{out_tok}out tokens{peak_tag})")
        _record_cost("deepseek", "deepseek-chat", in_tok, out_tok,
                     cached_input_tokens=cached,
                     agent_name=agent_name, pipeline_id=pipeline_id,
                     prompt_chars=len(prompt), response_chars=len(text), duration_s=elapsed)
        return _parse(text)

    except Exception as e:
        elapsed = time.time() - start
        print(f"[DeepSeek] ✗ Error after {elapsed:.1f}s: {e}")
        return _empty()


# ── Ollama (free, local) ──────────────────────────────────────────────────────

def _ask_ollama(prompt: str, agent_name: str = None, pipeline_id: str = None,
                max_retries: int = 2) -> dict:
    import requests as req

    system = (
        "You are a JSON-only API. Respond with ONE valid JSON object. "
        "Start with { and end with }. No markdown, no explanations, no extra text. "
        "Your entire response must be parseable by json.loads(). "
        "No trailing commas. Use double quotes for keys and strings."
    )

    print(f"[Ollama] → Sending prompt ({len(prompt)} chars) to {OLLAMA_MODEL}...")

    for attempt in range(max_retries + 1):
        start = time.time()
        try:
            response = req.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model":  OLLAMA_MODEL,
                    "prompt": f"{system}\n\n{prompt}",
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 3000,
                        "num_ctx":     8192,
                        "top_p":       0.9
                    }
                },
                timeout=OLLAMA_TIMEOUT
            )
            elapsed = time.time() - start
            response.raise_for_status()

            data     = response.json()
            text     = data.get("response", "")
            in_tok   = data.get("prompt_eval_count", 0)
            out_tok  = data.get("eval_count", 0)
            speed    = (out_tok / elapsed) if elapsed > 0 else 0
            print(f"[Ollama] ← Done in {elapsed:.1f}s ({in_tok}in+{out_tok}out tok, {speed:.1f} tok/s)")
            # Ollama is local — cost is $0 but we still record token usage
            _record_cost("ollama", OLLAMA_MODEL, in_tok, out_tok,
                         agent_name=agent_name, pipeline_id=pipeline_id,
                         prompt_chars=len(prompt), response_chars=len(text), duration_s=elapsed)

            parsed = _parse(text)

            if parsed and (parsed.get("entities") or parsed.get("fact_tables") or
                           parsed.get("mappings") or parsed.get("scripts") or
                           parsed.get("sql") or len(parsed) > 8):
                return parsed

            if attempt < max_retries:
                print(f"[Ollama] Empty/invalid response, retrying ({attempt + 2}/{max_retries + 1})...")
                prompt = "CRITICAL: Return only valid JSON. No other text.\n\n" + prompt
                continue

            return parsed

        except req.exceptions.Timeout:
            elapsed = time.time() - start
            print(f"[Ollama] ⚠ TIMEOUT after {elapsed:.0f}s (attempt {attempt + 1}/{max_retries + 1})")
            if attempt < max_retries:
                continue
            return _empty()
        except Exception as e:
            elapsed = time.time() - start
            print(f"[Ollama] ✗ Error after {elapsed:.1f}s: {e}")
            if attempt < max_retries:
                continue
            return _empty()

    return _empty()


# ── OpenAI ────────────────────────────────────────────────────────────────────

def _ask_openai(prompt: str, agent_name: str = None, pipeline_id: str = None) -> dict:
    from openai import OpenAI
    start = time.time()
    print(f"[OpenAI] → Sending prompt ({len(prompt)} chars)...")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=8000
    )
    elapsed = time.time() - start
    in_tok  = resp.usage.prompt_tokens     if resp.usage else 0
    out_tok = resp.usage.completion_tokens if resp.usage else 0
    print(f"[OpenAI] ← Done in {elapsed:.1f}s ({in_tok}in+{out_tok}out tokens)")
    _record_cost("openai", "gpt-4o-mini", in_tok, out_tok,
                 agent_name=agent_name, pipeline_id=pipeline_id,
                 prompt_chars=len(prompt), duration_s=elapsed)
    return _parse(resp.choices[0].message.content)


# ── Google Gemini ─────────────────────────────────────────────────────────────

def _ask_gemini(prompt: str, agent_name: str = None, pipeline_id: str = None) -> dict:
    from google import genai
    from google.genai import types
    start = time.time()
    print(f"[Gemini] → Sending prompt ({len(prompt)} chars)...")

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1, max_output_tokens=8192,
                response_mime_type="application/json",
            )
        )
    except Exception as e1:
        print(f"[Gemini] 2.5-flash failed ({e1}), trying 2.5-flash-lite...")
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1, max_output_tokens=8192,
                response_mime_type="application/json",
            )
        )

    elapsed  = time.time() - start
    text     = response.text if response.text else ""
    in_tok   = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
    out_tok  = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0
    print(f"[Gemini] ← Done in {elapsed:.1f}s ({in_tok}in+{out_tok}out tokens)")
    _record_cost("gemini", "gemini-2.5-flash", in_tok, out_tok,
                 agent_name=agent_name, pipeline_id=pipeline_id,
                 prompt_chars=len(prompt), response_chars=len(text), duration_s=elapsed)
    return _parse(text)


# ── JSON parser ───────────────────────────────────────────────────────────────

def _parse(text: str) -> dict:
    if not text:
        return _empty()

    text = text.strip()

    # Strategy 1: direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except Exception:
        pass

    # Strategy 2: strip markdown fences
    cleaned = text
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0]
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0]
    cleaned = cleaned.strip()

    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except Exception:
        pass

    # Strategy 3: find { ... }
    start = cleaned.find("{")
    end   = cleaned.rfind("}") + 1
    if start != -1 and end > start:
        candidate = cleaned[start:end]
        candidate = re.sub(r',\s*}', '}', candidate)
        candidate = re.sub(r',\s*]', ']', candidate)
        try:
            return json.loads(candidate)
        except Exception:
            pass
        try:
            candidate2 = candidate.replace("'", '"')
            return json.loads(candidate2)
        except Exception:
            pass

    # Strategy 5: truncated JSON recovery
    try:
        start_pos = cleaned.find("{")
        if start_pos != -1:
            partial       = cleaned[start_pos:]
            depth_brace   = 0
            last_good_pos = 0
            in_string     = False
            escape_next   = False

            for i, ch in enumerate(partial):
                if escape_next:
                    escape_next = False
                    continue
                if ch == '\\' and in_string:
                    escape_next = True
                    continue
                if ch == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == '{':
                    depth_brace += 1
                elif ch == '}':
                    depth_brace -= 1
                    if depth_brace == 0:
                        last_good_pos = i + 1

            if last_good_pos > 0:
                try:
                    result = json.loads(partial[:last_good_pos])
                    if isinstance(result, dict):
                        print(f"[AI Parser] ✓ Recovered truncated JSON ({last_good_pos} chars)")
                        return result
                except Exception:
                    pass
    except Exception:
        pass

    print(f"[AI Parser] Could not parse JSON. First 200 chars:")
    print(text[:200])
    return _empty()


def _empty() -> dict:
    return {
        "entities":           [],
        "relationships":      [],
        "notes":              "AI returned invalid JSON or timed out. Please try again.",
        "fact_tables":        [],
        "dimension_tables":   [],
        "modeling_decisions": [],
        "mappings":           [],
        "scripts":            [],
        "sql":                ""
    }


if __name__ == "__main__":
    print(f"\nTesting {PROVIDER} with model {_model}...")
    result = ask_ai('Return this JSON only: {"status": "working", "provider": "' + PROVIDER + '"}')
    print(f"Result: {result}")
    print(f"\nCost summary: {get_cost_summary()}")
