"""RSS/free API sources: Remotive, We Work Remotely, Jobicy"""

import asyncio
import logging

import feedparser
import httpx

logger = logging.getLogger(__name__)


def _normalize(entry: dict, source: str) -> dict:
    return {
        "title": entry.get("title", ""),
        "company": entry.get("author", ""),
        "location": "Remote",
        "url": entry.get("link", ""),
        "description": entry.get("summary", "")[:500],
        "source": source,
        "salary_min": None,
        "salary_max": None,
        "date_posted": "",
    }


async def search_remotive(query: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://remotive.com/api/remote-jobs",
                params={"search": query, "limit": 20},
            )
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
        return [
            {
                "title": j.get("title", ""),
                "company": j.get("company_name", ""),
                "location": j.get("candidate_required_location", "Remote"),
                "url": j.get("url", ""),
                "description": j.get("description", "")[:500],
                "source": "remotive",
                "salary_min": None,
                "salary_max": None,
                "date_posted": j.get("publication_date", ""),
            }
            for j in jobs
        ]
    except Exception as e:
        logger.warning("remotive fetch failed: %s", type(e).__name__)
        return []


async def search_weworkremotely(query: str) -> list[dict]:
    try:
        loop = asyncio.get_running_loop()
        feed = await loop.run_in_executor(
            None,
            feedparser.parse,
            "https://weworkremotely.com/remote-jobs.rss",
        )
        q = query.lower()
        return [
            _normalize(e, "weworkremotely")
            for e in feed.entries
            if q in e.get("title", "").lower() or q in e.get("summary", "").lower()
        ][:20]
    except Exception as e:
        logger.warning("weworkremotely fetch failed: %s", type(e).__name__)
        return []


async def search_jobicy(query: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://jobicy.com/api/v2/remote-jobs",
                params={"tag": query, "count": 20},
            )
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
        return [
            {
                "title": j.get("jobTitle", ""),
                "company": j.get("companyName", ""),
                "location": j.get("jobGeo", "Remote"),
                "url": j.get("url", ""),
                "description": j.get("jobExcerpt", ""),
                "source": "jobicy",
                "salary_min": None,
                "salary_max": None,
                "date_posted": j.get("pubDate", ""),
            }
            for j in jobs
        ]
    except Exception as e:
        logger.warning("jobicy fetch failed: %s", type(e).__name__)
        return []
