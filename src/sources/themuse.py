"""The Muse source — free API, no auth required. Includes company culture data."""

import logging

import httpx

logger = logging.getLogger(__name__)

THEMUSE_BASE = "https://www.themuse.com/api/public/jobs"


async def search_themuse(query: str, location: str = "") -> list[dict]:
    params: dict = {"descending": "true", "page": 0}

    # The Muse doesn't support keyword search — filter by location if provided
    if location:
        params["location"] = location

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(THEMUSE_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("themuse search failed: %s", type(e).__name__)
        return []

    q = query.lower()
    jobs = []
    for r in data.get("results", []):
        name = r.get("name", "")
        contents = r.get("contents", "")
        # Client-side filter since API doesn't support keyword search
        if q not in name.lower() and q not in contents.lower():
            continue
        company = r.get("company", {})
        locations = r.get("locations", [{}])
        loc_name = locations[0].get("name", "") if locations else ""
        jobs.append(
            {
                "title": name,
                "company": company.get("name", ""),
                "location": loc_name,
                "url": r.get("refs", {}).get("landing_page", ""),
                "description": contents[:500],
                "source": "themuse",
                "salary_min": None,
                "salary_max": None,
                "date_posted": r.get("publication_date", ""),
                "company_culture": company.get("description", "")[:300],
            }
        )
    return jobs[:20]
