"""
jobsearch-mcp: Multi-source job search MCP server
Transport: Streamable HTTP (FastMCP)
User context via X-User-ID header injected by LibreChat
"""

import os
from contextlib import asynccontextmanager
from fastmcp import FastMCP, Context

from .sources.adzuna import search_adzuna, get_salary_insights
from .sources.rss import search_remotive, search_weworkremotely, search_jobicy
from .sources.scraper import search_linkedin
from .db import (
    init_db, mark_job_seen, mark_job_applied, get_tracked_jobs,
    get_all_tracked_jobs, update_job_status, add_job_note, VALID_STATUSES,
)
from .enricher import enrich_job
from .vector import index_job as vector_index_job, search_by_text, get_index_count
from .scorer import score_fit as _score_fit, draft_cover_letter as _draft_cover_letter


@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield


mcp = FastMCP("jobsearch", lifespan=lifespan)


def get_user_id(ctx: Context) -> str:
    try:
        request = ctx.request_context.request
        return request.headers.get("X-User-ID", "anonymous")
    except Exception:
        return "anonymous"


@mcp.tool()
async def search_jobs(
    query: str,
    location: str = "",
    remote_only: bool = False,
    sources: list[str] = ["adzuna", "remotive", "weworkremotely", "jobicy"],
    ctx: Context = None,
) -> dict:
    """Search for jobs across multiple sources. Returns deduplicated results.
    Sources: adzuna, remotive, weworkremotely, jobicy, linkedin"""
    results = []
    if "adzuna" in sources:
        results += await search_adzuna(query, location, remote_only)
    if "remotive" in sources:
        results += await search_remotive(query)
    if "weworkremotely" in sources:
        results += await search_weworkremotely(query)
    if "jobicy" in sources:
        results += await search_jobicy(query)
    if "linkedin" in sources:
        results += await search_linkedin(query, location, remote_only)

    seen_urls: set[str] = set()
    deduped = []
    for job in results:
        if job["url"] not in seen_urls:
            seen_urls.add(job["url"])
            deduped.append(job)
    return {"count": len(deduped), "jobs": deduped}

@mcp.tool()
async def get_job_detail(url: str) -> dict:
    """Fetch a clean, full job description from a URL via Firecrawl."""
    return await enrich_job(url)


@mcp.tool()
async def index_job(url: str, title: str = "", company: str = "") -> dict:
    """Fetch a job via Firecrawl and store it in Qdrant for semantic search.
    Call this on listings you want findable via match_jobs."""
    enriched = await enrich_job(url)
    if enriched.get("error") or not enriched.get("content"):
        return {"status": "error", "url": url, "error": enriched.get("error", "no content")}
    resolved_title = title or enriched.get("title", "")
    point_id = await vector_index_job(
        url=url, title=resolved_title, company=company, content=enriched["content"]
    )
    return {"status": "indexed", "url": url, "title": resolved_title, "point_id": point_id}


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
        user_id = get_user_id(ctx)
        seen = await get_tracked_jobs(user_id, "seen")
        applied = await get_tracked_jobs(user_id, "applied")
        exclude_urls = [j["url"] for j in seen + applied]
    results = await search_by_text(resume_or_query, top_k=top_k, exclude_urls=exclude_urls)
    total_indexed = await get_index_count()
    return {"total_indexed": total_indexed, "count": len(results), "jobs": results}


@mcp.tool()
async def score_fit(url: str, resume: str) -> dict:
    """Score how well a resume matches a specific job posting.
    Fetches the full job description via Firecrawl, then uses Claude to produce
    a structured fit assessment including matched skills, gaps, seniority alignment,
    and an overall score (0-100) with an apply/maybe/skip recommendation."""
    enriched = await enrich_job(url)
    if enriched.get("error") or not enriched.get("content"):
        return {"status": "error", "url": url, "error": enriched.get("error", "no content")}
    try:
        result = await _score_fit(jd=enriched["content"], resume=resume)
        result["url"] = url
        result["title"] = enriched.get("title", "")
        return result
    except Exception as e:
        return {"status": "error", "url": url, "error": str(e)}


@mcp.tool()
async def cover_letter_brief(url: str, resume: str) -> dict:
    """Generate a structured cover letter brief for a job posting.
    Fetches the full JD via Firecrawl, then uses Claude to produce a brief covering:
    opening angle, key requirements to address with how your resume meets them,
    which experience to lead with, skills to emphasize, any gaps to acknowledge,
    recommended tone, and a suggested closing. Use this as a writing guide —
    the brief tells you what to say, you write the actual letter."""
    enriched = await enrich_job(url)
    if enriched.get("error") or not enriched.get("content"):
        return {"status": "error", "url": url, "error": enriched.get("error", "no content")}
    try:
        result = await _draft_cover_letter(jd=enriched["content"], resume=resume)
        result["url"] = url
        result["title"] = enriched.get("title", "")
        return result
    except Exception as e:
        return {"status": "error", "url": url, "error": str(e)}


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
        return {"url": url, "active": None, "error": enriched["error"], "signal": "fetch_failed"}

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
    - summary: min/max/avg/median computed from current live listings with posted salaries
    - histogram: distribution of salaries across salary bands (from Adzuna histogram endpoint)
    - trend: average salary per month over recent history (from Adzuna history endpoint)
    Use this before applying to understand market rates and to inform salary negotiation."""
    # Run search + Adzuna analytics endpoints concurrently
    import asyncio
    results, adzuna_data = await asyncio.gather(
        search_adzuna(query, location),
        get_salary_insights(query, location),
    )

    # Aggregate salary data from search results (skip predicted/nulls)
    salaries = []
    for r in results:
        s_min = r.get("salary_min")
        s_max = r.get("salary_max")
        predicted = r.get("salary_is_predicted", 1)
        if predicted:
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
            "median": round(salaries[n // 2] if n % 2 else (salaries[n // 2 - 1] + salaries[n // 2]) / 2),
            "note": "computed from listings with non-predicted salary data only",
        }

    return {
        "query": query,
        "location": location or "us",
        "summary": summary,
        "histogram": adzuna_data.get("histogram", {}),
        "trend": adzuna_data.get("history", {}),
    }


@mcp.tool()
async def mark_seen(url: str, title: str = "", company: str = "", ctx: Context = None) -> dict:
    """Mark a job as seen for the current user."""
    user_id = get_user_id(ctx) if ctx else "anonymous"
    await mark_job_seen(user_id, url, title, company)
    return {"status": "ok", "url": url, "user_id": user_id}


@mcp.tool()
async def mark_applied(url: str, title: str = "", company: str = "", ctx: Context = None) -> dict:
    """Mark a job as applied for the current user."""
    user_id = get_user_id(ctx) if ctx else "anonymous"
    await mark_job_applied(user_id, url, title, company)
    return {"status": "ok", "url": url, "user_id": user_id}


@mcp.tool()
async def get_my_jobs(status: str = "all", ctx: Context = None) -> dict:
    """Get tracked jobs for the current user.
    Status options: 'all', 'seen', 'applied', 'interviewing', 'offered', 'rejected', 'closed'.
    Defaults to 'all' — returns full pipeline ordered by stage."""
    user_id = get_user_id(ctx) if ctx else "anonymous"
    if status == "all":
        jobs = await get_all_tracked_jobs(user_id)
    else:
        jobs = await get_tracked_jobs(user_id, status)
    # Serialize datetimes
    for job in jobs:
        for k in ("updated_at", "created_at"):
            if job.get(k):
                job[k] = job[k].isoformat()
    return {"count": len(jobs), "jobs": jobs}


@mcp.tool()
async def update_status(
    url: str,
    status: str,
    ctx: Context = None,
) -> dict:
    """Update the pipeline status of a tracked job.
    Valid statuses: seen, applied, interviewing, offered, rejected, closed."""
    if status not in VALID_STATUSES:
        return {"status": "error", "error": f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}"}
    user_id = get_user_id(ctx) if ctx else "anonymous"
    found = await update_job_status(user_id, url, status)
    if not found:
        return {"status": "error", "error": "Job not found — mark it as seen or applied first"}
    return {"status": "ok", "url": url, "new_status": status}


@mcp.tool()
async def add_note(
    url: str,
    note: str,
    ctx: Context = None,
) -> dict:
    """Add a note to a tracked job (appended, not replaced).
    Useful for recording recruiter contacts, interview feedback, referrals, etc."""
    user_id = get_user_id(ctx) if ctx else "anonymous"
    found = await add_job_note(user_id, url, note)
    if not found:
        return {"status": "error", "error": "Job not found — mark it as seen or applied first"}
    return {"status": "ok", "url": url, "note": note}


if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "8383"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
