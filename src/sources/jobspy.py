"""
JobSpy source — optional scraping-based source for Indeed, Glassdoor, ZipRecruiter.

Opt-in only: not included in default search_jobs sources.
Uses a global rate limiter + per-site exponential backoff to avoid blocks.
"""

import asyncio
import logging
import time
from functools import partial

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global rate limiter: caps total jobspy calls across all users
# ---------------------------------------------------------------------------
_GLOBAL_SEMAPHORE = asyncio.Semaphore(1)  # only 1 concurrent jobspy call
_MIN_INTERVAL_SECONDS = 12  # minimum gap between calls (~5/min)
_last_call_time: float = 0.0

# ---------------------------------------------------------------------------
# Per-site backoff tracker
# ---------------------------------------------------------------------------
_site_backoff: dict[str, dict] = {}
_BACKOFF_BASE = 60  # initial backoff: 60 seconds
_BACKOFF_MAX = 900  # max backoff: 15 minutes
_BACKOFF_RESET_AFTER = 300  # reset backoff after 5 minutes of success


def _is_site_backed_off(site: str) -> bool:
    """Check if a site is currently in backoff. Returns True if we should skip it."""
    info = _site_backoff.get(site)
    if not info:
        return False
    if time.monotonic() < info["until"]:
        return True
    return False


def _record_site_failure(site: str):
    """Record a failure for a site and apply exponential backoff."""
    info = _site_backoff.get(site, {"failures": 0, "until": 0})
    info["failures"] += 1
    backoff = min(_BACKOFF_BASE * (2 ** (info["failures"] - 1)), _BACKOFF_MAX)
    info["until"] = time.monotonic() + backoff
    _site_backoff[site] = info
    logger.warning(f"jobspy: {site} backed off for {backoff}s (failure #{info['failures']})")


def _record_site_success(site: str):
    """Record a success — reset backoff if enough time has passed."""
    info = _site_backoff.get(site)
    if info and time.monotonic() > info.get("last_success", 0) + _BACKOFF_RESET_AFTER:
        _site_backoff.pop(site, None)
    elif info:
        info["last_success"] = time.monotonic()


# ---------------------------------------------------------------------------
# Supported sites and their jobspy names
# ---------------------------------------------------------------------------
JOBSPY_SITES = {
    "indeed": "indeed",
    "glassdoor": "glassdoor",
    "ziprecruiter": "zip_recruiter",
}


def _normalize_job(row: dict, site: str) -> dict:
    """Convert a python-jobspy result row to our standard job dict shape."""
    return {
        "title": str(row.get("title", "")),
        "company": str(row.get("company", "")),
        "location": str(row.get("location", "")),
        "url": str(row.get("job_url", "")),
        "description": str(row.get("description", ""))[:500],
        "source": f"jobspy:{site}",
        "salary_min": row.get("min_amount"),
        "salary_max": row.get("max_amount"),
        "salary_is_predicted": 0,
    }


async def search_jobspy(
    query: str,
    location: str = "",
    remote_only: bool = False,
    sites: list[str] | None = None,
) -> dict:
    """Search via python-jobspy. Returns results dict with per-site status.

    Args:
        query: Search term
        location: Location string (e.g. "San Francisco, CA")
        remote_only: Filter remote jobs only
        sites: Which jobspy sites to query. Defaults to all available.
               Valid: "indeed", "glassdoor", "ziprecruiter"

    Returns:
        {
            "jobs": [...],
            "source_status": {
                "indeed": "ok" | "backed_off" | "error: ..." | "no_results",
                "glassdoor": ...,
                ...
            }
        }
    """
    global _last_call_time

    requested_sites = sites or list(JOBSPY_SITES.keys())
    source_status: dict[str, str] = {}
    all_jobs: list[dict] = []

    # Filter out backed-off sites before we even acquire the semaphore
    active_sites = []
    for site in requested_sites:
        if site not in JOBSPY_SITES:
            source_status[site] = f"error: unknown site '{site}'"
            continue
        if _is_site_backed_off(site):
            source_status[site] = "backed_off"
            continue
        active_sites.append(site)

    if not active_sites:
        return {"jobs": [], "source_status": source_status}

    # Global rate limiter: only one jobspy call at a time, with min interval
    async with _GLOBAL_SEMAPHORE:
        now = time.monotonic()
        wait = _MIN_INTERVAL_SECONDS - (now - _last_call_time)
        if wait > 0:
            logger.info(f"jobspy: rate limiting, waiting {wait:.1f}s")
            await asyncio.sleep(wait)

        # Run each site individually so we can track per-site success/failure
        for site in active_sites:
            jobspy_name = JOBSPY_SITES[site]
            try:
                loop = asyncio.get_event_loop()
                jobs_df = await loop.run_in_executor(
                    None,
                    partial(
                        _scrape_site,
                        site_name=jobspy_name,
                        search_term=query,
                        location=location,
                        is_remote=remote_only,
                    ),
                )
                if jobs_df is not None and len(jobs_df) > 0:
                    for _, row in jobs_df.iterrows():
                        normalized = _normalize_job(row.to_dict(), site)
                        if normalized["url"]:
                            all_jobs.append(normalized)
                    source_status[site] = "ok"
                    _record_site_success(site)
                else:
                    source_status[site] = "no_results"

            except Exception as e:
                error_msg = str(e)[:200]
                logger.warning(f"jobspy: {site} failed: {error_msg}")
                _record_site_failure(site)
                source_status[site] = f"error: {error_msg}"

        _last_call_time = time.monotonic()

    return {"jobs": all_jobs, "source_status": source_status}


def _scrape_site(
    site_name: str,
    search_term: str,
    location: str = "",
    is_remote: bool = False,
):
    """Synchronous wrapper for jobspy.scrape_jobs (runs in thread executor)."""
    from jobspy import scrape_jobs

    kwargs = {
        "site_name": [site_name],
        "search_term": search_term,
        "results_wanted": 15,
        "hours_old": 72,
        "country_indeed": "USA",
    }
    if location:
        kwargs["location"] = location
    if is_remote:
        kwargs["is_remote"] = True

    return scrape_jobs(**kwargs)
