"""Job search, enrichment, indexing, and matching tools."""

import asyncio
import math
from datetime import datetime, timezone

from fastmcp import Context

from ..db import get_tracked_jobs
from ..enricher import enrich_job
from ..sources.adzuna import search_adzuna, get_salary_insights
from ..sources.rss import search_remotive, search_weworkremotely, search_jobicy
from ..sources.jobspy import search_jobspy, JOBSPY_SITES
from ..sources.usajobs import search_usajobs
from ..sources.findwork import search_findwork
from ..sources.themuse import search_themuse
from ..vector import index_job as vector_index_job, search_by_text, get_index_count


def _get_user_id(ctx: Context) -> str:
    try:
        return ctx.request_context.request.headers.get("X-User-ID", "anonymous")
    except Exception:
        return "anonymous"


def _recency_score(date_posted: str) -> float:
    if not date_posted:
        return 0.0
    try:
        dt = datetime.fromisoformat(date_posted.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - dt).days
        return math.exp(-age_days / 30)  # 30-day half-life
    except Exception:
        return 0.0


def register_tools(mcp):
    @mcp.tool()
    async def search_jobs(
        query: str,
        location: str = "",
        remote_only: bool = False,
        sources: list[str] = [
            "adzuna",
            "remotive",
            "weworkremotely",
            "jobicy",
            "usajobs",
        ],
        ctx: Context = None,
    ) -> dict:
        """Search for jobs across multiple sources. Returns deduplicated results sorted by recency.
        Default sources: adzuna, remotive, weworkremotely, jobicy, usajobs.
        Optional: findwork, themuse (tech/culture focus).
        Slow opt-in scrapers: indeed, glassdoor, ziprecruiter."""
        results = []
        source_status: dict[str, str] = {}

        async def _run(name: str, coro):
            items = await coro
            source_status[name] = "ok" if items else "no_results"
            results.extend(items)

        tasks = []
        if "adzuna" in sources:
            tasks.append(_run("adzuna", search_adzuna(query, location, remote_only)))
        if "remotive" in sources:
            tasks.append(_run("remotive", search_remotive(query)))
        if "weworkremotely" in sources:
            tasks.append(_run("weworkremotely", search_weworkremotely(query)))
        if "jobicy" in sources:
            tasks.append(_run("jobicy", search_jobicy(query)))
        if "usajobs" in sources:
            tasks.append(_run("usajobs", search_usajobs(query, location)))
        if "findwork" in sources:
            tasks.append(_run("findwork", search_findwork(query)))
        if "themuse" in sources:
            tasks.append(_run("themuse", search_themuse(query, location)))

        await asyncio.gather(*tasks)

        # Handle jobspy sources (indeed, glassdoor, ziprecruiter) — opt-in only
        jobspy_requested = [s for s in sources if s in JOBSPY_SITES]
        if jobspy_requested:
            jobspy_result = await search_jobspy(
                query=query,
                location=location,
                remote_only=remote_only,
                sites=jobspy_requested,
            )
            results.extend(jobspy_result["jobs"])
            source_status.update(jobspy_result["source_status"])

        seen_urls: set[str] = set()
        deduped = []
        for job in results:
            if job["url"] not in seen_urls:
                seen_urls.add(job["url"])
                deduped.append(job)

        # Secondary sort by recency — only reorders when date_posted is present
        has_dates = any(j.get("date_posted") for j in deduped)
        if has_dates:
            deduped.sort(
                key=lambda j: _recency_score(j.get("date_posted", "")), reverse=True
            )

        return {"count": len(deduped), "source_status": source_status, "jobs": deduped}

    @mcp.tool()
    async def get_job_detail(url: str) -> dict:
        """Fetch a clean, full job description from a URL.
        Uses Firecrawl v1 → Crawl4AI → rawFetch fallback. Results cached 6h."""
        return await enrich_job(url)

    @mcp.tool()
    async def index_job(url: str, title: str = "", company: str = "") -> dict:
        """Fetch a job and store it in Qdrant for semantic search.
        Call this on listings you want findable via match_jobs."""
        enriched = await enrich_job(url)
        if enriched.get("error") or not enriched.get("content"):
            return {
                "status": "error",
                "url": url,
                "error": enriched.get("error", "no content"),
            }
        resolved_title = title or enriched.get("title", "")
        point_id = await vector_index_job(
            url=url, title=resolved_title, company=company, content=enriched["content"]
        )
        return {
            "status": "indexed",
            "url": url,
            "title": resolved_title,
            "point_id": point_id,
        }

    @mcp.tool()
    async def match_jobs(
        resume_or_query: str,
        top_k: int = 10,
        exclude_seen: bool = False,
        ctx: Context = None,
    ) -> dict:
        """Find indexed jobs semantically similar to a resume or free-text description.
        Set exclude_seen=True to filter out jobs already marked as seen or applied."""
        exclude_urls: list[str] = []
        if exclude_seen and ctx:
            user_id = _get_user_id(ctx)
            seen = await get_tracked_jobs(user_id, "seen")
            applied = await get_tracked_jobs(user_id, "applied")
            exclude_urls = [j["url"] for j in seen + applied]
        results = await search_by_text(
            resume_or_query, top_k=top_k, exclude_urls=exclude_urls
        )
        total_indexed = await get_index_count()
        return {"total_indexed": total_indexed, "count": len(results), "jobs": results}

    @mcp.tool()
    async def check_active(url: str) -> dict:
        """Check whether a job listing is still active by fetching the page and scanning for
        common 'no longer available' signals. Returns active=True/False/None (None means
        the page loaded but no clear signal was found — treat as probably active)."""
        STALE_PATTERNS = [
            "this job is no longer available",
            "this position has been filled",
            "this listing has expired",
            "job listing is no longer active",
            "this job has been closed",
            "position is no longer open",
            "this role has been filled",
            "no longer accepting applications",
            "posting has been removed",
            "this posting has expired",
            "job is closed",
            "requisition is closed",
            "position has been closed",
        ]
        ACTIVE_PATTERNS = [
            "apply now",
            "apply for this job",
            "submit your application",
            "easy apply",
        ]

        enriched = await enrich_job(url)
        if enriched.get("error"):
            return {
                "url": url,
                "active": None,
                "error": enriched["error"],
                "signal": "fetch_failed",
            }

        content = enriched.get("content", "").lower()
        if not content:
            return {"url": url, "active": None, "signal": "no_content"}

        for pattern in STALE_PATTERNS:
            if pattern in content:
                return {"url": url, "active": False, "signal": pattern}

        for pattern in ACTIVE_PATTERNS:
            if pattern in content:
                return {"url": url, "active": True, "signal": pattern}

        return {"url": url, "active": None, "signal": "no_clear_signal"}

    @mcp.tool()
    async def salary_insights(query: str, location: str = "") -> dict:
        """Get salary intelligence for a job title or query via Adzuna.
        Returns three views:
        - summary: min/max/avg/median from current live listings with posted salaries
        - histogram: distribution across salary bands
        - trend: average salary per month over recent history"""
        results, adzuna_data = await asyncio.gather(
            search_adzuna(query, location),
            get_salary_insights(query, location),
        )

        salaries = []
        for r in results:
            s_min = r.get("salary_min")
            s_max = r.get("salary_max")
            if r.get("salary_is_predicted", 1):
                continue
            if s_min and s_max:
                salaries.append((s_min + s_max) / 2)
            elif s_min:
                salaries.append(s_min)
            elif s_max:
                salaries.append(s_max)

        summary = {}
        if salaries:
            salaries.sort()
            n = len(salaries)
            summary = {
                "sample_size": n,
                "min": round(min(salaries)),
                "max": round(max(salaries)),
                "avg": round(sum(salaries) / n),
                "median": round(
                    salaries[n // 2]
                    if n % 2
                    else (salaries[n // 2 - 1] + salaries[n // 2]) / 2
                ),
                "note": "computed from listings with non-predicted salary data only",
            }

        return {
            "query": query,
            "location": location or "us",
            "summary": summary,
            "histogram": adzuna_data.get("histogram", {}),
            "trend": adzuna_data.get("history", {}),
        }
