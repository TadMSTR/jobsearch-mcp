"""Resume/job fit scoring and cover letter scaffolding via Claude (haiku for speed and cost)."""
import os
import json
import httpx

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = "claude-haiku-4-5-20251001"

FIT_SYSTEM = """You are a job fit analyst. Given a job description and a resume or skills summary,
produce a structured fit assessment. Be direct and specific — cite actual requirements and skills by name.
Respond ONLY with a JSON object, no preamble or markdown fences."""

FIT_PROMPT = """Job Description:
{jd}

Resume / Skills Summary:
{resume}

Return a JSON object with exactly these fields:
{{
  "overall_score": <integer 0-100>,
  "summary": "<2-3 sentence plain-English verdict>",
  "matching_skills": ["<skill>", ...],
  "missing_skills": ["<skill>", ...],
  "nice_to_have_met": ["<skill>", ...],
  "seniority_fit": "<strong|moderate|weak> — <one sentence explanation>",
  "recommendation": "<apply|maybe|skip>"
}}"""

COVER_SYSTEM = """You are a career coach helping a job seeker prepare a cover letter.
Given a job description and a resume or skills summary, produce a structured brief
that the candidate will use to write their own cover letter.
Be specific — reference actual requirements and skills by name.
Respond ONLY with a JSON object, no preamble or markdown fences."""

COVER_PROMPT = """Job Description:
{jd}

Resume / Skills Summary:
{resume}

Return a JSON object with exactly these fields:
{{
  "opening_angle": "<1-2 sentence hook — the most compelling reason this candidate fits this role>",
  "key_requirements_to_address": ["<requirement>: <how resume addresses it>", ...],
  "experience_to_lead_with": "<which role or project from the resume to highlight first and why>",
  "skills_to_emphasize": ["<skill>", ...],
  "gaps_to_acknowledge": "<any significant gap worth briefly addressing or reframing — empty string if none>",
  "tone": "<formal|conversational|technical> — <one sentence explaining why based on the job/company>",
  "suggested_closing": "<1 sentence closing idea that reinforces fit without being generic>"
}}"""


async def _claude(system: str, prompt: str, max_tokens: int = 1024) -> dict:
    """Shared Claude API call — returns parsed JSON from model response."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    raw = data["content"][0]["text"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


async def score_fit(jd: str, resume: str) -> dict:
    """Score resume fit against a job description."""
    prompt = FIT_PROMPT.format(jd=jd[:6000], resume=resume[:3000])
    return await _claude(FIT_SYSTEM, prompt)


async def draft_cover_letter(jd: str, resume: str) -> dict:
    """Produce a structured cover letter brief from a JD and resume."""
    prompt = COVER_PROMPT.format(jd=jd[:6000], resume=resume[:3000])
    return await _claude(COVER_SYSTEM, prompt)
