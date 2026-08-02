"""Job content enrichment — Firecrawl v1 → Crawl4AI → rawFetch fallback with Valkey cache."""

import asyncio
import ipaddress
import json
import logging
import os
import socket
from urllib.parse import urlparse

import httpx
import redis.asyncio as redis

logger = logging.getLogger(__name__)

FIRECRAWL_URL = os.getenv("FIRECRAWL_URL", "http://firecrawl-api:3002")
CRAWL4AI_URL = os.getenv("CRAWL4AI_URL", "http://host.docker.internal:11235")
VALKEY_URL = os.getenv("VALKEY_URL", "redis://jobsearch-valkey:6379")
ENRICH_TTL = 6 * 3600  # 6 hours

# Redirect chains are followed manually so every hop can be re-validated.
MAX_REDIRECTS = 5

_redis = None

# RFC 1918 + loopback private ranges to block SSRF
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),  # 0.0.0.0 reaches localhost on Linux
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT / Shared Address Space
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


def _is_blocked_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if an address is anything other than a routable public destination.

    The explicit `_PRIVATE_NETS` list is kept for readability, but the stdlib
    properties are the real gate — they also cover 0.0.0.0/8 (which reaches
    localhost on Linux), CGNAT, benchmark, multicast and reserved space.
    """
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        # ::ffff:192.168.1.1 must be judged as the v4 address it wraps.
        addr = addr.ipv4_mapped
    if any(addr in net for net in _PRIVATE_NETS):
        return True
    # `is_global` is the precise question being asked — is this routable on the
    # public internet. Do not swap it for `is_private`: the stdlib deliberately
    # reports 100.64.0.0/10 (CGNAT) as non-private since 3.12.4, so `is_private`
    # alone lets Shared Address Space through. Multicast and reserved space are
    # checked separately because they are absent from the IANA special registry
    # that backs `is_global`, which therefore reports them as global.
    return not addr.is_global or addr.is_multicast or addr.is_reserved


def _resolve_host(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a hostname to every address it maps to.

    Separated out so tests can patch it without needing live DNS.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"could not resolve host: {host}") from e

    addrs = []
    for info in infos:
        # Strip any IPv6 scope id (fe80::1%eth0) before parsing.
        raw = info[4][0].split("%")[0]
        try:
            addrs.append(ipaddress.ip_address(raw))
        except ValueError:
            continue
    return addrs


def _validate_url(url: str) -> None:
    """Reject non-https URLs and any destination that is not a public address.

    A hostname is resolved and *every* address it maps to is checked — checking
    only literal-IP hosts leaves `https://name-that-resolves-to-10.0.0.1/` wide
    open. Callers must re-run this against each redirect target as well; see
    `_fetch_raw`.

    Residual risk: this is a resolve-then-connect check, so a DNS entry that
    changes between validation and the HTTP client's own lookup (DNS rebinding)
    is not caught. Closing that fully requires pinning the connection to the
    validated address; not done here.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"URL scheme '{parsed.scheme}' not allowed — must be https")

    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL has no host")

    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        addrs = _resolve_host(host)

    if not addrs:
        raise ValueError(f"could not resolve host: {host}")

    for addr in addrs:
        if _is_blocked_address(addr):
            raise ValueError(f"URL resolves to private/loopback address: {addr}")


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
    """Fetch a URL directly, re-validating every redirect hop.

    `follow_redirects=True` would let a public https URL 302 to
    http://192.168.1.x and bypass the checks entirely, since validation only
    ever ran against the URL originally supplied.
    """
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                resp = await client.get(current, headers={"User-Agent": "Mozilla/5.0"})
                if not resp.is_redirect:
                    resp.raise_for_status()
                    return {"content": resp.text[:10000], "title": ""}

                location = resp.headers.get("location", "")
                if not location:
                    return {"content": "", "error": "redirect with no Location header"}

                # Resolve relative redirects against the current URL, then apply
                # the full scheme + address check to the target before following.
                current = str(httpx.URL(current).join(location))
                await asyncio.to_thread(_validate_url, current)

            return {"content": "", "error": f"too many redirects (>{MAX_REDIRECTS})"}
    except Exception as e:
        logger.warning("raw fetch failed for %s: %s", url, type(e).__name__)
        return {"content": "", "error": str(e)}


async def enrich_job(url: str) -> dict:
    """Enrich a job URL with full content. Firecrawl v1 → Crawl4AI → rawFetch fallback.
    Results are cached in Valkey for 6 hours."""
    try:
        # to_thread: _validate_url now performs a DNS lookup, which would
        # otherwise block the event loop.
        await asyncio.to_thread(_validate_url, url)
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
