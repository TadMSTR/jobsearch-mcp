"""Tests for enricher.py — SSRF validation and multi-tier fallback logic."""
import pytest
import respx
import httpx

from src.enricher import _validate_url, _fetch_firecrawl, _fetch_raw, enrich_job


class TestValidateUrl:
    def test_rejects_non_https_scheme(self):
        with pytest.raises(ValueError, match="scheme"):
            _validate_url("ftp://example.com/job")

    def test_rejects_private_ipv4_10(self):
        with pytest.raises(ValueError, match="private"):
            _validate_url("https://10.0.0.1/job")

    def test_rejects_private_ipv4_172(self):
        with pytest.raises(ValueError, match="private"):
            _validate_url("https://172.20.0.1/job")

    def test_rejects_private_ipv4_192_168(self):
        with pytest.raises(ValueError, match="private"):
            _validate_url("https://192.168.1.100/job")

    def test_rejects_loopback(self):
        with pytest.raises(ValueError, match="private"):
            _validate_url("https://127.0.0.1/job")

    def test_accepts_public_https(self):
        # Should not raise
        _validate_url("https://boards.greenhouse.io/company/jobs/12345")

    def test_accepts_http_public(self):
        # http scheme also accepted (for job boards that don't redirect)
        _validate_url("http://example.com/jobs/123")

    def test_accepts_hostname(self):
        # Hostname (non-IP) passes validation
        _validate_url("https://jobs.lever.co/company/role")


@pytest.mark.asyncio
class TestFetchFirecrawl:
    async def test_returns_content_on_success(self):
        with respx.mock() as mock:
            mock.post("http://firecrawl-api:3002/v1/scrape").mock(
                return_value=httpx.Response(
                    200,
                    json={"data": {"markdown": "Job description text", "metadata": {"title": "Engineer"}}},
                )
            )
            result = await _fetch_firecrawl("https://example.com/job")
        assert result["content"] == "Job description text"
        assert result["title"] == "Engineer"

    async def test_returns_empty_on_failure(self):
        with respx.mock() as mock:
            mock.post("http://firecrawl-api:3002/v1/scrape").mock(
                return_value=httpx.Response(500)
            )
            result = await _fetch_firecrawl("https://example.com/job")
        assert result["content"] == ""
        assert "error" in result


@pytest.mark.asyncio
class TestFetchRaw:
    async def test_returns_content_on_success(self):
        with respx.mock() as mock:
            mock.get("https://example.com/job").mock(
                return_value=httpx.Response(200, text="<html>Apply now</html>")
            )
            result = await _fetch_raw("https://example.com/job")
        assert "Apply now" in result["content"]

    async def test_returns_empty_on_failure(self):
        with respx.mock() as mock:
            mock.get("https://example.com/job").mock(
                return_value=httpx.Response(404)
            )
            result = await _fetch_raw("https://example.com/job")
        assert result["content"] == ""
        assert "error" in result


@pytest.mark.asyncio
class TestEnrichJobSsrf:
    async def test_blocks_private_ip(self):
        result = await enrich_job("https://192.168.1.1/admin")
        assert result["content"] == ""
        assert "private" in result["error"].lower() or "private" in result.get("error", "").lower()

    async def test_blocks_loopback(self):
        result = await enrich_job("https://127.0.0.1/internal")
        assert result["content"] == ""
        assert result.get("error")
