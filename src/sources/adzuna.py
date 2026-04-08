import logging
import os

import httpx

logger = logging.getLogger(__name__)

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs"


async def search_adzuna(query: str, location: str = "", remote_only: bool = False) -> list[dict]:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []

    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": 20,
        "what": query,
        "content-type": "application/json",
    }
    if location:
        params["where"] = location
    if remote_only:
        params["what"] = f"{query} remote"

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(f"{ADZUNA_BASE}/us/search/1", params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("adzuna search failed: %s", type(e).__name__)
            return []

    return [
        {
            "title": r.get("title", ""),
            "company": r.get("company", {}).get("display_name", ""),
            "location": r.get("location", {}).get("display_name", ""),
            "url": r.get("redirect_url", ""),
            "description": r.get("description", ""),
            "source": "adzuna",
            "salary_min": r.get("salary_min"),
            "salary_max": r.get("salary_max"),
            "salary_is_predicted": r.get("salary_is_predicted", 1),
            "date_posted": r.get("created", ""),
        }
        for r in data.get("results", [])
    ]


async def get_salary_insights(query: str, location: str = "") -> dict:
    """Fetch salary histogram + historical trend from Adzuna for a job title/query."""
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return {}

    base_params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "content-type": "application/json",
        "what": query,
    }
    if location:
        base_params["where"] = location

    async with httpx.AsyncClient(timeout=15) as client:
        histogram = {}
        try:
            r = await client.get(f"{ADZUNA_BASE}/us/histogram", params=base_params)
            r.raise_for_status()
            histogram = r.json().get("histogram", {})
        except Exception as e:
            logger.warning("adzuna histogram failed: %s", type(e).__name__)

        history = []
        try:
            r = await client.get(f"{ADZUNA_BASE}/us/history", params=base_params)
            r.raise_for_status()
            history = r.json().get("month", {})
        except Exception as e:
            logger.warning("adzuna history failed: %s", type(e).__name__)

    return {"histogram": histogram, "history": history}
