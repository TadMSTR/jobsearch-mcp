"""Findwork source — developer/tech jobs (free API key, no scraping)."""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

FINDWORK_KEY = os.getenv("FINDWORK_API_KEY", "")
FINDWORK_BASE = "https://findwork.dev/api/jobs/"


async def search_findwork(query: str) -> list[dict]:
    if not FINDWORK_KEY:
        return []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                FINDWORK_BASE,
                headers={"Authorization": f"Token {FINDWORK_KEY}"},
                params={"search": query},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("findwork search failed: %s", type(e).__name__)
        return []

    jobs = []
    for r in data.get("results", []):
        jobs.append(
            {
                "title": r.get("role", ""),
                "company": r.get("company_name", ""),
                "location": r.get("location", "Remote"),
                "url": r.get("url", ""),
                "description": r.get("text", "")[:500],
                "source": "findwork",
                "salary_min": None,
                "salary_max": None,
                "date_posted": r.get("date_posted", ""),
            }
        )
    return jobs
