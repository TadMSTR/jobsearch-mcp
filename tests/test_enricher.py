"""Tests for enricher.py — SSRF validation and multi-tier fallback logic."""

import ipaddress
from unittest.mock import patch

import httpx
import pytest
import respx

from jobsearch_mcp.enricher import _fetch_firecrawl, _fetch_raw, _validate_url, enrich_job


def _resolves_to(*addresses: str):
    """Patch DNS so validation tests never depend on live resolution."""
    return patch(
        "jobsearch_mcp.enricher._resolve_host",
        return_value=[ipaddress.ip_address(a) for a in addresses],
    )


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
        with _resolves_to("93.184.216.34"):
            _validate_url("https://boards.greenhouse.io/company/jobs/12345")

    def test_rejects_http_public(self):
        # http is rejected — HTTPS-only policy applied in v2.1.0 security fix
        with pytest.raises(ValueError, match="scheme"):
            _validate_url("http://example.com/jobs/123")

    def test_accepts_hostname(self):
        with _resolves_to("93.184.216.34"):
            _validate_url("https://jobs.lever.co/company/role")

    # --- hostname resolution (SSRF-05) ---

    def test_rejects_hostname_resolving_to_private(self):
        """The core gap: a public-looking name pointing at RFC1918."""
        with _resolves_to("192.168.1.50"), pytest.raises(ValueError, match="private"):
            _validate_url("https://totally-legit.example.com/job")

    def test_rejects_hostname_resolving_to_loopback(self):
        with _resolves_to("127.0.0.1"), pytest.raises(ValueError, match="private"):
            _validate_url("https://localtest.me/job")

    def test_rejects_when_any_resolved_address_is_private(self):
        """A public A record does not excuse a private one alongside it."""
        with _resolves_to("93.184.216.34", "10.1.2.3"), pytest.raises(ValueError, match="private"):
            _validate_url("https://split-horizon.example.com/job")

    def test_rejects_unresolvable_host(self):
        with (
            patch("jobsearch_mcp.enricher._resolve_host", return_value=[]),
            pytest.raises(ValueError, match="resolve"),
        ):
            _validate_url("https://nx.example.com/job")

    def test_rejects_url_with_no_host(self):
        with pytest.raises(ValueError, match="no host"):
            _validate_url("https:///just-a-path")

    # --- address classes beyond RFC1918 ---

    @pytest.mark.parametrize(
        "addr",
        [
            "0.0.0.0",  # reaches localhost on Linux
            "169.254.169.254",  # cloud metadata
            "100.64.0.1",  # CGNAT
            "224.0.0.1",  # multicast
            "240.0.0.1",  # reserved
        ],
    )
    def test_rejects_non_public_ipv4_classes(self, addr):
        with pytest.raises(ValueError, match="private"):
            _validate_url(f"https://{addr}/job")

    @pytest.mark.parametrize("addr", ["[::1]", "[fc00::1]", "[fe80::1]"])
    def test_rejects_non_public_ipv6(self, addr):
        with pytest.raises(ValueError, match="private"):
            _validate_url(f"https://{addr}/job")

    def test_rejects_ipv4_mapped_ipv6(self):
        """::ffff:192.168.1.1 must be judged as the v4 address it wraps."""
        with pytest.raises(ValueError, match="private"):
            _validate_url("https://[::ffff:192.168.1.1]/job")

    def test_rejects_hostname_resolving_to_ipv4_mapped_private(self):
        with _resolves_to("::ffff:10.0.0.5"), pytest.raises(ValueError, match="private"):
            _validate_url("https://sneaky.example.com/job")


@pytest.mark.asyncio
class TestFetchFirecrawl:
    async def test_returns_content_on_success(self):
        with respx.mock() as mock:
            mock.post("http://firecrawl-api:3002/v1/scrape").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "data": {
                            "markdown": "Job description text",
                            "metadata": {"title": "Engineer"},
                        }
                    },
                )
            )
            result = await _fetch_firecrawl("https://example.com/job")
        assert result["content"] == "Job description text"
        assert result["title"] == "Engineer"

    async def test_returns_empty_on_failure(self):
        with respx.mock() as mock:
            mock.post("http://firecrawl-api:3002/v1/scrape").mock(return_value=httpx.Response(500))
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
            mock.get("https://example.com/job").mock(return_value=httpx.Response(404))
            result = await _fetch_raw("https://example.com/job")
        assert result["content"] == ""
        assert "error" in result

    async def test_blocks_redirect_to_private_ip(self):
        """SSRF-02: a public URL must not be able to 302 into RFC1918."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get("https://example.com/job").mock(
                return_value=httpx.Response(302, headers={"location": "http://192.168.1.1/admin"})
            )
            internal = mock.get("http://192.168.1.1/admin").mock(
                return_value=httpx.Response(200, text="SECRET")
            )
            result = await _fetch_raw("https://example.com/job")

        assert not internal.called, "redirect target was fetched despite being private"
        assert result["content"] == ""
        assert "error" in result

    async def test_blocks_redirect_downgrade_to_http(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get("https://example.com/job").mock(
                return_value=httpx.Response(302, headers={"location": "http://example.com/job"})
            )
            downgraded = mock.get("http://example.com/job").mock(
                return_value=httpx.Response(200, text="plaintext")
            )
            result = await _fetch_raw("https://example.com/job")

        assert not downgraded.called
        assert result["content"] == ""

    async def test_follows_legitimate_public_redirect(self):
        """Redirects still work when the target is public — this is not a blanket block."""
        with respx.mock() as mock:
            mock.get("https://example.com/job").mock(
                return_value=httpx.Response(301, headers={"location": "https://jobs.example.com/1"})
            )
            mock.get("https://jobs.example.com/1").mock(
                return_value=httpx.Response(200, text="<html>Apply now</html>")
            )
            with _resolves_to("93.184.216.34"):
                result = await _fetch_raw("https://example.com/job")

        assert "Apply now" in result["content"]

    async def test_caps_redirect_chain(self):
        with respx.mock(assert_all_called=False) as mock:
            # Self-redirect loop — must terminate rather than spin.
            mock.get("https://example.com/job").mock(
                return_value=httpx.Response(302, headers={"location": "https://example.com/job"})
            )
            with _resolves_to("93.184.216.34"):
                result = await _fetch_raw("https://example.com/job")

        assert result["content"] == ""
        assert "too many redirects" in result["error"]


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

    async def test_blocks_hostname_pointing_at_internal_service(self):
        """End-to-end: the caller-controlled hostname path, via the public tool entry."""
        with _resolves_to("10.10.1.9"):
            result = await enrich_job("https://looks-fine.example.com/job")
        assert result["content"] == ""
        assert "private" in result["error"].lower()

    async def test_blocks_cloud_metadata_endpoint(self):
        result = await enrich_job("https://169.254.169.254/latest/meta-data/")
        assert result["content"] == ""
        assert "private" in result["error"].lower()
