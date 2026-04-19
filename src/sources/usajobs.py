"""USAJobs source — US federal government jobs (free, requires API key + email auth)."""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

USAJOBS_KEY = os.getenv("USAJOBS_API_KEY", "")
USAJOBS_EMAIL = os.getenv("USAJOBS_EMAIL", "")
USAJOBS_BASE = "https://data.usajobs.gov/api/search"


async def search_usajobs(query: str, location: str = "") -> list[dict]:
    if not USAJOBS_KEY or not USAJOBS_EMAIL:
        return []

    headers = {
        "Authorization-Key": USAJOBS_KEY,
        "User-Agent": USAJOBS_EMAIL,
        "Host": "data.usajobs.gov",
    }
    params: dict = {"Keyword": query, "ResultsPerPage": 25}
    if location:
        params["LocationName"] = location

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(USAJOBS_BASE, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("usajobs search failed: %s", type(e).__name__)
        return []

    jobs = []
    for item in data.get("SearchResult", {}).get("SearchResultItems", []):
        desc = item.get("MatchedObjectDescriptor", {})
        pos = desc.get("PositionLocation", [{}])[0]
        salary = desc.get("PositionRemuneration", [{}])[0]
        apply_uri = desc.get("ApplyURI", [""])[0]
        jobs.append(
            {
                "title": desc.get("PositionTitle", ""),
                "company": desc.get("OrganizationName", ""),
                "location": pos.get("LocationName", ""),
                "url": apply_uri or desc.get("PositionURI", ""),
                "description": desc.get("QualificationSummary", "")[:500],
                "source": "usajobs",
                "salary_min": _parse_salary(salary.get("MinimumRange")),
                "salary_max": _parse_salary(salary.get("MaximumRange")),
                "date_posted": desc.get("PublicationStartDate", ""),
            }
        )
    return jobs


def _parse_salary(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
