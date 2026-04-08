"""Tests for scorer.py — output structure validation."""
import json
import pytest
import respx
import httpx
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")


def _mock_claude_response(payload: dict):
    return httpx.Response(
        200,
        json={
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "model": "claude-haiku-4-5-20251001",
            "usage": {"input_tokens": 10, "output_tokens": 50},
        },
    )


FIT_RESPONSE = {
    "overall_score": 82,
    "summary": "Strong match on core Python and API skills.",
    "matching_skills": ["Python", "FastAPI"],
    "missing_skills": ["Kubernetes"],
    "nice_to_have_met": ["Redis"],
    "seniority_fit": "strong — 7 years meets the 5-year requirement",
    "recommendation": "apply",
    "ats_score": 75,
    "ats_keywords_present": ["Python", "FastAPI", "PostgreSQL"],
    "ats_keywords_missing": ["Kubernetes"],
    "ats_formatting_notes": "",
    "ats_recommendation": "strong",
}

COVER_RESPONSE = {
    "opening_angle": "Strong Python developer with direct FastAPI experience.",
    "key_requirements_to_address": ["Python: 7 years daily use"],
    "experience_to_lead_with": "Acme Corp role — most relevant FastAPI project",
    "skills_to_emphasize": ["FastAPI", "PostgreSQL"],
    "gaps_to_acknowledge": "",
    "tone": "technical — engineering-focused role at a startup",
    "suggested_closing": "Excited to bring my API scaling experience to your team.",
}


@pytest.mark.asyncio
class TestScoreFit:
    async def test_returns_required_fields(self, sample_jd, sample_resume):
        with respx.mock() as mock:
            mock.post("https://api.anthropic.com/v1/messages").mock(
                return_value=_mock_claude_response(FIT_RESPONSE)
            )
            from src.scorer import score_fit
            result = await score_fit(sample_jd, sample_resume)

        assert "overall_score" in result
        assert "recommendation" in result
        assert "ats_score" in result
        assert "ats_recommendation" in result
        assert isinstance(result["matching_skills"], list)
        assert isinstance(result["missing_skills"], list)
        assert isinstance(result["ats_keywords_present"], list)
        assert isinstance(result["ats_keywords_missing"], list)

    async def test_overall_score_in_range(self, sample_jd, sample_resume):
        with respx.mock() as mock:
            mock.post("https://api.anthropic.com/v1/messages").mock(
                return_value=_mock_claude_response(FIT_RESPONSE)
            )
            from src.scorer import score_fit
            result = await score_fit(sample_jd, sample_resume)

        assert 0 <= result["overall_score"] <= 100
        assert 0 <= result["ats_score"] <= 100

    async def test_recommendation_valid_value(self, sample_jd, sample_resume):
        with respx.mock() as mock:
            mock.post("https://api.anthropic.com/v1/messages").mock(
                return_value=_mock_claude_response(FIT_RESPONSE)
            )
            from src.scorer import score_fit
            result = await score_fit(sample_jd, sample_resume)

        assert result["recommendation"] in ("apply", "maybe", "skip")
        assert result["ats_recommendation"] in ("strong", "moderate", "weak")


@pytest.mark.asyncio
class TestDraftCoverLetter:
    async def test_returns_required_fields(self, sample_jd, sample_resume):
        with respx.mock() as mock:
            mock.post("https://api.anthropic.com/v1/messages").mock(
                return_value=_mock_claude_response(COVER_RESPONSE)
            )
            from src.scorer import draft_cover_letter
            result = await draft_cover_letter(sample_jd, sample_resume)

        required = [
            "opening_angle", "key_requirements_to_address",
            "experience_to_lead_with", "skills_to_emphasize",
            "gaps_to_acknowledge", "tone", "suggested_closing",
        ]
        for field in required:
            assert field in result, f"Missing field: {field}"
