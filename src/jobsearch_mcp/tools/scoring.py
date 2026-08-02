"""Fit scoring, ATS analysis, and cover letter tools."""

import json

from fastmcp import Context

from ..db import get_user_profile
from ..enricher import enrich_job
from ..scorer import draft_cover_letter as _draft_cover_letter
from ..scorer import score_fit as _score_fit


def _get_user_id(ctx: Context) -> str | None:
    try:
        uid = ctx.request_context.request.headers.get("X-User-ID", "")
        return uid if uid else None
    except Exception:
        return None


# Fields the fit/ATS rubric and the cover-letter brief actually reason over.
# Everything else in a stored profile (notification_email, work_authorization,
# salary_min/max, education, contact details) is dead weight in the prompt — it
# costs input tokens on every call and the rubric never cites it.
_SCORING_FIELDS = (
    "summary",
    "skills",
    "experience",
    "certifications",
    "target_roles",
)


def _trim_profile(profile: dict) -> dict:
    """Keep only the profile fields the scoring prompts use."""
    return {k: profile[k] for k in _SCORING_FIELDS if profile.get(k)}


async def _resolve_resume(resume: str | None, ctx: Context | None) -> str | None:
    """Return resume string: explicit arg takes priority, then stored profile summary."""
    if resume:
        return resume
    if ctx:
        user_id = _get_user_id(ctx)
        profile = await get_user_profile(user_id)
        if profile:
            return json.dumps(_trim_profile(profile))
    return None


def register_tools(mcp):
    @mcp.tool()
    async def score_fit(url: str, resume: str = "", ctx: Context = None) -> dict:
        """Score how well a resume matches a specific job posting.
        Fetches the full JD, then uses Claude to produce a fit assessment including
        matched skills, gaps, seniority alignment, ATS score, and a recommendation.
        If resume is omitted, uses your stored profile (set it with save_profile)."""
        resolved = await _resolve_resume(resume or None, ctx)
        if not resolved:
            return {
                "status": "error",
                "error": "No resume provided and no stored profile found. Use save_profile first.",
            }
        enriched = await enrich_job(url)
        if enriched.get("error") or not enriched.get("content"):
            return {
                "status": "error",
                "url": url,
                "error": enriched.get("error", "no content"),
            }
        try:
            result = await _score_fit(
                jd=enriched["content"],
                resume=resolved,
                user_id=_get_user_id(ctx) if ctx else None,
            )
            result["url"] = url
            result["title"] = enriched.get("title", "")
            return result
        except Exception as e:
            return {"status": "error", "url": url, "error": str(e)}

    @mcp.tool()
    async def cover_letter_brief(url: str, resume: str = "", ctx: Context = None) -> dict:
        """Generate a structured cover letter brief for a job posting.
        Fetches the full JD, then uses Claude to produce a brief covering: opening angle,
        key requirements to address, which experience to lead with, skills to emphasize,
        gaps to acknowledge, recommended tone, and a suggested closing.
        If resume is omitted, uses your stored profile."""
        resolved = await _resolve_resume(resume or None, ctx)
        if not resolved:
            return {
                "status": "error",
                "error": "No resume provided and no stored profile found. Use save_profile first.",
            }
        enriched = await enrich_job(url)
        if enriched.get("error") or not enriched.get("content"):
            return {
                "status": "error",
                "url": url,
                "error": enriched.get("error", "no content"),
            }
        try:
            result = await _draft_cover_letter(
                jd=enriched["content"],
                resume=resolved,
                user_id=_get_user_id(ctx) if ctx else None,
            )
            result["url"] = url
            result["title"] = enriched.get("title", "")
            return result
        except Exception as e:
            return {"status": "error", "url": url, "error": str(e)}
