"""Tests for usage.py — cache keying, cache hit/miss behaviour, and usage logging.

These cover the Phase 3 cost work: a cache hit must make no API call at all, and
every real call must emit a usage line with token counts.
"""

import json
import logging
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from jobsearch_mcp.usage import (
    PROMPT_VERSION,
    build_cache_key,
    get_cached,
    log_usage,
    set_cached,
)

FIT_RESPONSE = {
    "overall_score": 82,
    "summary": "Strong match.",
    "matching_skills": ["Python"],
    "missing_skills": [],
    "nice_to_have_met": [],
    "seniority_fit": "strong — meets requirement",
    "recommendation": "apply",
    "ats_score": 75,
    "ats_keywords_present": ["Python"],
    "ats_keywords_missing": [],
    "ats_formatting_notes": "",
    "ats_recommendation": "strong",
}


def _claude_response(payload: dict, stop_reason: str = "end_turn"):
    return httpx.Response(
        200,
        json={
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "model": "claude-haiku-4-5-20251001",
            "stop_reason": stop_reason,
            "usage": {"input_tokens": 1379, "output_tokens": 548},
        },
    )


class TestCacheKey:
    def test_is_deterministic(self):
        assert build_cache_key("score_fit", "jd", "resume") == build_cache_key(
            "score_fit", "jd", "resume"
        )

    def test_differs_on_input(self):
        assert build_cache_key("score_fit", "jd-a", "resume") != build_cache_key(
            "score_fit", "jd-b", "resume"
        )

    def test_differs_on_kind(self):
        assert build_cache_key("score_fit", "jd", "r") != build_cache_key(
            "cover_letter_brief", "jd", "r"
        )

    def test_field_boundary_is_unambiguous(self):
        """('ab','c') and ('a','bc') must not collide."""
        assert build_cache_key("k", "ab", "c") != build_cache_key("k", "a", "bc")

    def test_includes_prompt_version(self):
        assert PROMPT_VERSION in build_cache_key("score_fit", "jd", "r")


@pytest.mark.asyncio
class TestCacheIO:
    async def test_get_returns_none_when_backend_unavailable(self):
        redis = AsyncMock()
        redis.get.side_effect = ConnectionError("valkey down")
        with patch("jobsearch_mcp.usage._get_redis", AsyncMock(return_value=redis)):
            assert await get_cached("k") is None

    async def test_set_swallows_backend_failure(self):
        redis = AsyncMock()
        redis.set.side_effect = ConnectionError("valkey down")
        with patch("jobsearch_mcp.usage._get_redis", AsyncMock(return_value=redis)):
            await set_cached("k", {"a": 1})  # must not raise

    async def test_roundtrip(self):
        redis = AsyncMock()
        redis.get.return_value = json.dumps({"overall_score": 82})
        with patch("jobsearch_mcp.usage._get_redis", AsyncMock(return_value=redis)):
            assert await get_cached("k") == {"overall_score": 82}


@pytest.mark.asyncio
class TestScoreFitCaching:
    async def test_cache_hit_makes_no_api_call(self, sample_jd, sample_resume):
        redis = AsyncMock()
        redis.get.return_value = json.dumps(FIT_RESPONSE)

        # assert_all_called=False: the route is registered precisely so we can
        # prove it is never hit.
        with respx.mock(assert_all_called=False) as mock:
            route = mock.post("https://api.anthropic.com/v1/messages").mock(
                return_value=_claude_response(FIT_RESPONSE)
            )
            with patch("jobsearch_mcp.usage._get_redis", AsyncMock(return_value=redis)):
                from jobsearch_mcp.scorer import score_fit

                result = await score_fit(sample_jd, sample_resume)

        assert result["overall_score"] == 82
        assert not route.called, "cache hit must not reach the Anthropic API"

    async def test_cache_miss_calls_api_and_stores(self, sample_jd, sample_resume):
        redis = AsyncMock()
        redis.get.return_value = None

        with respx.mock() as mock:
            route = mock.post("https://api.anthropic.com/v1/messages").mock(
                return_value=_claude_response(FIT_RESPONSE)
            )
            with patch("jobsearch_mcp.usage._get_redis", AsyncMock(return_value=redis)):
                from jobsearch_mcp.scorer import score_fit

                await score_fit(sample_jd, sample_resume)

        assert route.called
        assert redis.set.await_count == 1, "a miss must populate the cache"

    async def test_truncated_response_raises_clearly(self, sample_jd, sample_resume):
        redis = AsyncMock()
        redis.get.return_value = None

        with respx.mock() as mock:
            mock.post("https://api.anthropic.com/v1/messages").mock(
                return_value=_claude_response(FIT_RESPONSE, stop_reason="max_tokens")
            )
            with patch("jobsearch_mcp.usage._get_redis", AsyncMock(return_value=redis)):
                from jobsearch_mcp.scorer import score_fit

                with pytest.raises(ValueError, match="truncated"):
                    await score_fit(sample_jd, sample_resume)


@pytest.mark.asyncio
class TestUsageLogging:
    async def test_real_call_logs_token_counts(self, sample_jd, sample_resume, caplog):
        redis = AsyncMock()
        redis.get.return_value = None

        with (
            caplog.at_level(logging.INFO, logger="jobsearch_mcp.usage"),
            respx.mock() as mock,
        ):
            mock.post("https://api.anthropic.com/v1/messages").mock(
                return_value=_claude_response(FIT_RESPONSE)
            )
            with patch("jobsearch_mcp.usage._get_redis", AsyncMock(return_value=redis)):
                from jobsearch_mcp.scorer import score_fit

                await score_fit(sample_jd, sample_resume, user_id="u1")

        line = "\n".join(caplog.messages)
        assert "input_tokens=1379" in line
        assert "output_tokens=548" in line
        assert "tool=score_fit" in line
        assert "user_id=u1" in line
        assert "cached=False" in line

    async def test_cache_hit_logs_no_token_counts(self, sample_jd, sample_resume, caplog):
        redis = AsyncMock()
        redis.get.return_value = json.dumps(FIT_RESPONSE)

        with (
            caplog.at_level(logging.INFO, logger="jobsearch_mcp.usage"),
            patch("jobsearch_mcp.usage._get_redis", AsyncMock(return_value=redis)),
        ):
            from jobsearch_mcp.scorer import score_fit

            await score_fit(sample_jd, sample_resume, user_id="u1")

        line = "\n".join(caplog.messages)
        assert "cached=True" in line
        # The absence of token counts is the evidence no API call was made.
        assert "input_tokens" not in line

    async def test_log_usage_without_usage_object(self, caplog):
        with caplog.at_level(logging.INFO, logger="jobsearch_mcp.usage"):
            log_usage("score_fit", cached=True)
        assert "cached=True" in caplog.text
        assert "user_id=-" in caplog.text
