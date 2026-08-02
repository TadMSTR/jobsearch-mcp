"""Anthropic token-usage logging and Valkey-backed result caching.

Two responsibilities, both about cost:

1. `log_usage` records what every Claude call actually consumed. `scorer._claude`
   previously discarded `message.usage` entirely, so there was no way to verify a
   cost change had any effect. This is the measurement layer everything else in
   Phase 3 is verified against.

2. `get_cached` / `set_cached` memoise deterministic Claude results in Valkey.
   Re-scoring a job the user already looked at is a full API call today; cached it
   costs nothing. A cache hit is visible in the logs as a `cached=True` line with
   no token counts at all.

Note on prompt caching: Anthropic server-side prompt caching is deliberately NOT
used here. Haiku 4.5's minimum cacheable prefix is 4096 tokens and the largest
prompt this server sends measures 2,375 — `cache_control` would silently no-op
(`cache_creation_input_tokens: 0`) rather than error. See CHANGELOG 2.2.0.
"""

import hashlib
import json
import logging

from .enricher import _get_redis

logger = logging.getLogger(__name__)

# 24h — a fit score against a fixed JD+resume pair is far more stable than the
# page content enricher.py caches at 6h.
SCORE_TTL = 24 * 3600

# Bump when any prompt or response schema in scorer.py changes, so previously
# cached results (which have the old shape) are not served against new code.
PROMPT_VERSION = "v2"


def build_cache_key(kind: str, *parts: str) -> str:
    """Derive a Valkey key from the exact (already-truncated) prompt inputs."""
    digest = hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()
    return f"job:claude:{PROMPT_VERSION}:{kind}:{digest}"


async def get_cached(key: str) -> dict | None:
    """Return a cached result, or None on miss or any cache failure."""
    try:
        r = await _get_redis()
        cached = await r.get(key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning("valkey get failed: %s", type(e).__name__)
    return None


async def set_cached(key: str, value: dict, ttl: int = SCORE_TTL) -> None:
    """Store a result. Cache failures are logged and swallowed — never fatal."""
    try:
        r = await _get_redis()
        # `set(..., ex=)` rather than `setex` — the latter is deprecated in redis-py 8.
        await r.set(key, json.dumps(value), ex=ttl)
    except Exception as e:
        logger.warning("valkey set failed: %s", type(e).__name__)


def log_usage(tool: str, usage=None, user_id: str | None = None, cached: bool = False) -> None:
    """Emit one structured line per Claude call, or per cache hit.

    A cache hit logs `cached=true` with no token fields — the absence of token
    counts is the evidence that no API call was made.
    """
    fields = {
        "event": "claude_usage",
        "tool": tool,
        "user_id": user_id or "-",
        "cached": cached,
    }
    if usage is not None:
        fields.update(
            {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
                # Expected to stay 0 — see the module docstring on prompt caching.
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0)
                or 0,
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            }
        )
    logger.info(
        " ".join(f"{k}={v}" for k, v in fields.items()),
        extra={"claude_usage": fields},
    )
