"""Resume profile management and tailoring tools."""

from fastmcp import Context

from ..db import upsert_user_profile, get_user_profile, delete_user_profile
from ..enricher import enrich_job
from ..scorer import tailor_resume_to_jd, build_profile_from_text


def _get_user_id(ctx: Context) -> str | None:
    """Extract user_id from X-User-ID header. Returns None if absent."""
    try:
        uid = ctx.request_context.request.headers.get("X-User-ID", "")
        return uid if uid else None
    except Exception:
        return None


def register_tools(mcp):
    @mcp.tool()
    async def save_profile(profile: dict, ctx: Context = None) -> dict:
        """Save your structured resume profile. All scoring and tailoring tools will use
        this profile automatically when no resume is passed explicitly.
        Required fields: name, email, skills, experience. See build_profile for the full schema."""
        user_id = _get_user_id(ctx) if ctx else None
        if not user_id:
            return {
                "status": "error",
                "error": "User identity required — X-User-ID header missing",
            }
        await upsert_user_profile(user_id, profile)
        return {
            "status": "ok",
            "user_id": user_id,
            "fields_saved": list(profile.keys()),
        }

    @mcp.tool()
    async def get_profile(ctx: Context = None) -> dict:
        """Retrieve your stored resume profile."""
        user_id = _get_user_id(ctx) if ctx else None
        if not user_id:
            return {
                "status": "error",
                "error": "User identity required — X-User-ID header missing",
            }
        profile = await get_user_profile(user_id)
        if not profile:
            return {
                "status": "not_found",
                "message": "No profile stored. Use build_profile or save_profile to create one.",
            }
        return {"status": "ok", "profile": profile}

    @mcp.tool()
    async def delete_profile(ctx: Context = None) -> dict:
        """Delete your stored resume profile and all associated data."""
        user_id = _get_user_id(ctx) if ctx else None
        if not user_id:
            return {
                "status": "error",
                "error": "User identity required — X-User-ID header missing",
            }
        found = await delete_user_profile(user_id)
        if not found:
            return {"status": "not_found", "message": "No profile to delete"}
        return {"status": "ok", "message": "Profile deleted"}

    @mcp.tool()
    async def build_profile(raw_text: str, ctx: Context = None) -> dict:
        """Parse a raw resume or bio text into a structured profile using Claude.
        Returns the parsed profile for your review — call save_profile to store it.
        Does NOT automatically save."""
        if not raw_text or not raw_text.strip():
            return {"status": "error", "error": "raw_text is required"}
        try:
            profile = await build_profile_from_text(raw_text)
            return {
                "status": "ok",
                "profile": profile,
                "message": "Review the profile above, then call save_profile to store it.",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @mcp.tool()
    async def tailor_resume(url: str, ctx: Context = None) -> dict:
        """Tailor your stored resume profile to a specific job posting.
        Fetches the full JD, then uses Claude to rewrite highlights and summary
        to match JD keywords and priorities.
        Returns the tailored profile for review — does NOT overwrite your stored profile."""
        user_id = _get_user_id(ctx) if ctx else None
        if not user_id:
            return {
                "status": "error",
                "error": "User identity required — X-User-ID header missing",
            }

        profile = await get_user_profile(user_id)
        if not profile:
            return {
                "status": "error",
                "error": "No stored profile found. Use build_profile or save_profile first.",
            }

        enriched = await enrich_job(url)
        if enriched.get("error") or not enriched.get("content"):
            return {
                "status": "error",
                "url": url,
                "error": enriched.get("error", "no content"),
            }

        try:
            result = await tailor_resume_to_jd(jd=enriched["content"], profile=profile)
            result["url"] = url
            result["title"] = enriched.get("title", "")
            result["message"] = (
                "Tailored profile above is for this job only — your stored profile is unchanged."
            )
            return result
        except Exception as e:
            return {"status": "error", "url": url, "error": str(e)}
