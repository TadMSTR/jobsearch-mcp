"""Job pipeline tracking tools — mark seen/applied, get status, add notes."""
from fastmcp import Context

from ..db import (
    mark_job_seen, mark_job_applied, get_tracked_jobs,
    get_all_tracked_jobs, update_job_status, add_job_note, VALID_STATUSES,
)


def _get_user_id(ctx: Context) -> str | None:
    try:
        uid = ctx.request_context.request.headers.get("X-User-ID", "")
        return uid if uid else None
    except Exception:
        return None


def register_tools(mcp):
    @mcp.tool()
    async def mark_seen(
        url: str, title: str = "", company: str = "", ctx: Context = None
    ) -> dict:
        """Mark a job as seen for the current user."""
        user_id = _get_user_id(ctx) if ctx else None
        if not user_id:
            return {"status": "error", "error": "User identity required — X-User-ID header missing"}
        await mark_job_seen(user_id, url, title, company)
        return {"status": "ok", "url": url, "user_id": user_id}

    @mcp.tool()
    async def mark_applied(
        url: str, title: str = "", company: str = "", ctx: Context = None
    ) -> dict:
        """Mark a job as applied for the current user."""
        user_id = _get_user_id(ctx) if ctx else None
        if not user_id:
            return {"status": "error", "error": "User identity required — X-User-ID header missing"}
        await mark_job_applied(user_id, url, title, company)
        return {"status": "ok", "url": url, "user_id": user_id}

    @mcp.tool()
    async def get_my_jobs(status: str = "all", ctx: Context = None) -> dict:
        """Get tracked jobs for the current user.
        Status options: 'all', 'seen', 'applied', 'interviewing', 'offered', 'rejected', 'closed'.
        Defaults to 'all' — returns full pipeline ordered by stage."""
        user_id = _get_user_id(ctx) if ctx else None
        if not user_id:
            return {"status": "error", "error": "User identity required — X-User-ID header missing"}
        if status == "all":
            jobs = await get_all_tracked_jobs(user_id)
        else:
            jobs = await get_tracked_jobs(user_id, status)
        for job in jobs:
            for k in ("updated_at", "created_at"):
                if job.get(k):
                    job[k] = job[k].isoformat()
        return {"count": len(jobs), "jobs": jobs}

    @mcp.tool()
    async def update_status(url: str, status: str, ctx: Context = None) -> dict:
        """Update the pipeline status of a tracked job.
        Valid statuses: seen, applied, interviewing, offered, rejected, closed."""
        if status not in VALID_STATUSES:
            return {
                "status": "error",
                "error": f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
            }
        user_id = _get_user_id(ctx) if ctx else None
        if not user_id:
            return {"status": "error", "error": "User identity required — X-User-ID header missing"}
        found = await update_job_status(user_id, url, status)
        if not found:
            return {"status": "error", "error": "Job not found — mark it as seen or applied first"}
        return {"status": "ok", "url": url, "new_status": status}

    @mcp.tool()
    async def add_note(url: str, note: str, ctx: Context = None) -> dict:
        """Add a note to a tracked job (appended, not replaced).
        Useful for recording recruiter contacts, interview feedback, referrals, etc."""
        user_id = _get_user_id(ctx) if ctx else None
        if not user_id:
            return {"status": "error", "error": "User identity required — X-User-ID header missing"}
        found = await add_job_note(user_id, url, note)
        if not found:
            return {"status": "error", "error": "Job not found — mark it as seen or applied first"}
        return {"status": "ok", "url": url, "note": note}
