"""
llm_client.py — Unified LLM provider for AIBridge
Reads LLM_PROVIDER from .env and routes accordingly.
No hardcoded provider — just set .env and it works.

Supported providers (set LLM_PROVIDER in .env):
  - slm       → local SLM via nlm_engine.py
  - deepseek  → DeepSeek API (OpenAI-compatible)
  - anthropic → Anthropic Claude
  - openai    → OpenAI GPT

.env example:
  LLM_PROVIDER=slm                          # use local SLM (default if set)
  LLM_PROVIDER=deepseek
  DEEPSEEK_API_KEY=sk-...
  DEEPSEEK_MODEL=deepseek-chat              # optional, defaults below
  LLM_PROVIDER=anthropic
  ANTHROPIC_API_KEY=sk-ant-...
  ANTHROPIC_MODEL=claude-haiku-4-5-20251001
  LLM_PROVIDER=openai
  OPENAI_API_KEY=sk-...
  OPENAI_MODEL=gpt-4o-mini

Fallback chain (if primary fails):
  LLM_FALLBACK=deepseek                     # optional fallback provider
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── provider config from .env ──────────────────────────────────────────────
PRIMARY   = (os.getenv("LLM_PROVIDER", "slm")).lower().strip()
FALLBACK  = (os.getenv("LLM_FALLBACK", "")).lower().strip()

DEEPSEEK_KEY   = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE  = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

ANTHROPIC_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

OPENAI_KEY   = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

SLM_MODEL = os.getenv("SLM_MODEL", "")   # passed to nlm_engine if set


# ── per-provider call functions ────────────────────────────────────────────

def _call_slm(system: str, user: str, max_tokens: int) -> str:
    """Route through your existing nlm_engine.py"""
    try:
        from nlm_engine import generate  # your local SLM entry point
        return generate(system_prompt=system, user_prompt=user,
                        max_tokens=max_tokens, model=SLM_MODEL or None)
    except ImportError:
        raise RuntimeError("nlm_engine.py not found — is it in the same directory?")


def _call_deepseek(system: str, user: str, max_tokens: int) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_BASE)
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user",   "content": user}],
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


def _call_anthropic(system: str, user: str, max_tokens: int) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text.strip()


def _call_openai(system: str, user: str, max_tokens: int) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_KEY)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user",   "content": user}],
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


_PROVIDERS = {
    "slm":       _call_slm,
    "deepseek":  _call_deepseek,
    "anthropic": _call_anthropic,
    "openai":    _call_openai,
}


# ── public API ─────────────────────────────────────────────────────────────

def chat(system: str, user: str, max_tokens: int = 1024,
         provider: Optional[str] = None) -> str:
    """
    Call the configured LLM provider.

    Args:
        system:     system prompt
        user:       user message
        max_tokens: response length cap
        provider:   override LLM_PROVIDER for this call only
                    (useful for forcing deepseek on complex tasks)

    Returns:
        response text string

    Raises:
        RuntimeError if all providers fail
    """
    target = (provider or PRIMARY).lower()
    fn = _PROVIDERS.get(target)
    if not fn:
        raise RuntimeError(f"Unknown LLM provider: '{target}'. "
                           f"Set LLM_PROVIDER to one of: {list(_PROVIDERS)}")

    try:
        logger.debug(f"[llm_client] calling provider={target}")
        return fn(system, user, max_tokens)

    except Exception as e:
        logger.warning(f"[llm_client] {target} failed: {e}")

        if FALLBACK and FALLBACK != target:
            fallback_fn = _PROVIDERS.get(FALLBACK)
            if fallback_fn:
                logger.info(f"[llm_client] falling back to {FALLBACK}")
                try:
                    return fallback_fn(system, user, max_tokens)
                except Exception as fe:
                    logger.error(f"[llm_client] fallback {FALLBACK} also failed: {fe}")

        raise RuntimeError(f"LLM call failed (provider={target}): {e}") from e


def active_provider() -> str:
    """Return the active provider name (for logging/debug)."""
    return PRIMARY
