"""Resume/job fit scoring, ATS analysis, and cover letter scaffolding via Claude."""
import json
import logging
import os

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"

_client: anthropic.AsyncAnthropic | None = None


def _check_env() -> None:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    assert key, "ANTHROPIC_API_KEY is required — set it in the environment"


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _check_env()
        _client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    return _client


FIT_SYSTEM = """You are a job fit analyst. Given a job description and a resume or skills summary,
produce a structured fit assessment and ATS compatibility analysis. Be direct and specific —
cite actual requirements and skills by name.
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
  "recommendation": "<apply|maybe|skip>",
  "ats_score": <integer 0-100>,
  "ats_keywords_present": ["<keyword>", ...],
  "ats_keywords_missing": ["<keyword>", ...],
  "ats_formatting_notes": "<brief note if resume format may cause ATS parse failures, empty string if none>",
  "ats_recommendation": "<strong|moderate|weak>"
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

TAILOR_SYSTEM = """You are a career coach who tailors resumes to specific job descriptions.
Given a structured resume profile and a job description, return a tailored version of the profile
optimized for that specific role. Do NOT invent experience or skills — only reorder, reframe,
and emphasize what is already present.
Respond ONLY with a JSON object, no preamble or markdown fences."""

TAILOR_PROMPT = """Job Description:
{jd}

Resume Profile (JSON):
{profile}

Return a JSON object with exactly these fields:
{{
  "tailored_profile": {{
    "summary": "<rewritten summary mirroring JD language where accurate>",
    "experience": [<reordered/rewritten experience entries — same structure as input, highlights rewritten>],
    "skills": [<reordered skills list — most relevant to JD first>]
  }},
  "changes_summary": "<2-4 sentence explanation of what changed and why — which JD priorities drove the rewrites>"
}}"""

BUILD_SYSTEM = """You are a career assistant that parses unstructured resume text into a structured profile.
Extract all available information and return it as a JSON object.
Respond ONLY with a JSON object, no preamble or markdown fences."""

BUILD_PROMPT = """Parse this resume or bio text into a structured profile:

{raw_text}

Return a JSON object with these fields (use empty string/list/null for missing data):
{{
  "name": "<full name>",
  "email": "<email address>",
  "location": "<city, state or remote>",
  "target_roles": ["<role>", ...],
  "remote_preference": "<remote_only|hybrid|onsite|any>",
  "experience": [
    {{
      "title": "<job title>",
      "company": "<company name>",
      "duration": "<e.g. Jan 2020 - Mar 2023>",
      "highlights": ["<achievement or responsibility>", ...]
    }}
  ],
  "skills": ["<skill>", ...],
  "education": [
    {{
      "degree": "<degree name>",
      "institution": "<school name>",
      "year": "<graduation year>"
    }}
  ],
  "certifications": ["<cert name>", ...],
  "summary": "<professional summary — 2-3 sentences>",
  "work_authorization": "<e.g. US Citizen, H1B, OPT, etc.>",
  "salary_min": <integer or null>,
  "salary_max": <integer or null>,
  "notification_email": "<email for job alerts, same as email if not specified>"
}}"""


async def _claude(system: str, prompt: str, max_tokens: int = 1024) -> dict:
    client = _get_client()
    message = await client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    return json.loads(raw)


async def score_fit(jd: str, resume: str) -> dict:
    """Score resume fit + ATS compatibility against a job description."""
    prompt = FIT_PROMPT.format(jd=jd[:6000], resume=resume[:3000])
    return await _claude(FIT_SYSTEM, prompt)


async def draft_cover_letter(jd: str, resume: str) -> dict:
    """Produce a structured cover letter brief from a JD and resume."""
    prompt = COVER_PROMPT.format(jd=jd[:6000], resume=resume[:3000])
    return await _claude(COVER_SYSTEM, prompt)


async def tailor_resume_to_jd(jd: str, profile: dict) -> dict:
    """Return a tailored profile + changes summary for a specific JD."""
    profile_json = json.dumps(profile, indent=2)
    prompt = TAILOR_PROMPT.format(jd=jd[:6000], profile=profile_json[:4000])
    return await _claude(TAILOR_SYSTEM, prompt, max_tokens=2048)


async def build_profile_from_text(raw_text: str) -> dict:
    """Parse unstructured resume/bio text into a structured ResumeProfile dict."""
    prompt = BUILD_PROMPT.format(raw_text=raw_text[:8000])
    return await _claude(BUILD_SYSTEM, prompt, max_tokens=2048)
