"""Job content enrichment — Firecrawl v1 → Crawl4AI → rawFetch fallback with Valkey cache."""
import asyncio
import ipaddress
import json
import logging
import os
from urllib.parse import urlparse

import httpx
import redis.asyncio as redis

logger = logging.getLogger(__name__)

FIRECRAWL_URL = os.getenv("FIRECRAWL_URL", "http://firecrawl-api:3002")
CRAWL4AI_URL = os.getenv("CRAWL4AI_URL", "http://host.docker.internal:11235")
VALKEY_URL = os.getenv("VALKEY_URL", "redis://jobsearch-valkey:6379")
ENRICH_TTL = 6 * 3600  # 6 hours

_redis = None

# RFC 1918 + loopback private ranges to block SSRF
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),   # IPv6 link-local
]


def _validate_url(url: str) -> None:
    """Reject non-https URLs and RFC 1918/loopback destinations."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"URL scheme '{parsed.scheme}' not allowed — must be https")
    host = parsed.hostname or ""
    try:
        addr = ipaddress.ip_address(host)
        for net in _PRIVATE_NETS:
            if addr in net:
                raise ValueError(f"URL resolves to private/loopback address: {host}")
    except ValueError as e:
        if "private" in str(e) or "loopback" in str(e):
            raise
        # hostname (not IP) — pass through; DNS resolution happens in the HTTP client


async def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(VALKEY_URL)
    return _redis


async def _fetch_firecrawl(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{FIRECRAWL_URL}/v1/scrape",
                json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
        content = data.get("markdown", "")
        title = data.get("metadata", {}).get("title", "")
        return {"content": content, "title": title}
    except Exception as e:
        logger.warning("firecrawl fetch failed for %s: %s", url, type(e).__name__)
        return {"content": "", "error": str(e)}


async def _fetch_crawl4ai(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{CRAWL4AI_URL}/crawl",
                json={"urls": [url], "priority": 10},
            )
            resp.raise_for_status()
            task_id = resp.json()["task_id"]
            for _ in range(10):
                await asyncio.sleep(2)
                r = await client.get(f"{CRAWL4AI_URL}/task/{task_id}")
                result = r.json()
                if result.get("status") == "completed":
                    content = result["results"][0].get("markdown_content", "")
                    return {"content": content, "title": ""}
        return {"content": "", "error": "crawl4ai timeout"}
    except Exception as e:
        logger.warning("crawl4ai fetch failed for %s: %s", url, type(e).__name__)
        return {"content": "", "error": str(e)}


async def _fetch_raw(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            return {"content": resp.text[:10000], "title": ""}
    except Exception as e:
        logger.warning("raw fetch failed for %s: %s", url, type(e).__name__)
        return {"content": "", "error": str(e)}


async def enrich_job(url: str) -> dict:
    """Enrich a job URL with full content. Firecrawl v1 → Crawl4AI → rawFetch fallback.
    Results are cached in Valkey for 6 hours."""
    try:
        _validate_url(url)
    except ValueError as e:
        return {"url": url, "content": "", "error": str(e)}

    r = await _get_redis()
    cache_key = f"job:enrich:{url}"
    try:
        cached = await r.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning("valkey get failed: %s", type(e).__name__)

    # Tier 1: Firecrawl v1
    result = await _fetch_firecrawl(url)
    if result.get("content"):
        result["url"] = url
        try:
            await r.setex(cache_key, ENRICH_TTL, json.dumps(result))
        except Exception as e:
            logger.warning("valkey set failed: %s", type(e).__name__)
        return result

    # Tier 2: Crawl4AI
    result = await _fetch_crawl4ai(url)
    if result.get("content"):
        result["url"] = url
        try:
            await r.setex(cache_key, ENRICH_TTL, json.dumps(result))
        except Exception as e:
            logger.warning("valkey set failed: %s", type(e).__name__)
        return result

    # Tier 3: rawFetch
    result = await _fetch_raw(url)
    result["url"] = url
    return result
