"""Tests for source normalizer output shape."""

import pytest
import respx
import httpx
from unittest.mock import patch, MagicMock

EXPECTED_FIELDS = {
    "title",
    "company",
    "location",
    "url",
    "description",
    "source",
    "salary_min",
    "salary_max",
    "date_posted",
}


def _check_job_shape(job: dict, source_name: str):
    for field in EXPECTED_FIELDS:
        assert field in job, f"Source '{source_name}' missing field: {field}"


@pytest.mark.asyncio
class TestAdzunaNormalizer:
    async def test_normalizer_output_shape(self):
        import os

        os.environ["ADZUNA_APP_ID"] = "test-id"
        os.environ["ADZUNA_APP_KEY"] = "test-key"

        mock_response = {
            "results": [
                {
                    "title": "Python Dev",
                    "company": {"display_name": "Acme"},
                    "location": {"display_name": "Remote"},
                    "redirect_url": "https://adzuna.com/job/1",
                    "description": "Great role",
                    "salary_min": 100000,
                    "salary_max": 130000,
                    "salary_is_predicted": 0,
                    "created": "2026-04-01T00:00:00Z",
                }
            ]
        }
        with respx.mock() as mock:
            mock.get(url__regex="api.adzuna.com").mock(
                return_value=httpx.Response(200, json=mock_response)
            )
            from src.sources.adzuna import search_adzuna

            jobs = await search_adzuna("python developer")

        assert len(jobs) == 1
        _check_job_shape(jobs[0], "adzuna")
        assert jobs[0]["date_posted"] == "2026-04-01T00:00:00Z"


@pytest.mark.asyncio
class TestRemotiveNormalizer:
    async def test_normalizer_output_shape(self):
        mock_response = {
            "jobs": [
                {
                    "title": "Backend Dev",
                    "company_name": "Remote Co",
                    "candidate_required_location": "Worldwide",
                    "url": "https://remotive.com/job/1",
                    "description": "Python role",
                    "publication_date": "2026-04-01",
                }
            ]
        }
        with respx.mock() as mock:
            mock.get("https://remotive.com/api/remote-jobs").mock(
                return_value=httpx.Response(200, json=mock_response)
            )
            from src.sources.rss import search_remotive

            jobs = await search_remotive("python")

        assert len(jobs) == 1
        _check_job_shape(jobs[0], "remotive")


@pytest.mark.asyncio
class TestWeworkremotelyNormalizer:
    async def test_normalizer_output_shape(self):
        mock_entry = MagicMock()
        mock_entry.get.side_effect = lambda key, default="": {
            "title": "Frontend Dev",
            "author": "Company",
            "link": "https://weworkremotely.com/job/1",
            "summary": "React role",
        }.get(key, default)

        mock_feed = MagicMock()
        mock_feed.entries = [mock_entry]

        with patch("src.sources.rss.feedparser.parse", return_value=mock_feed):
            from src.sources.rss import search_weworkremotely

            jobs = await search_weworkremotely("frontend")

        assert len(jobs) == 1
        _check_job_shape(jobs[0], "weworkremotely")


@pytest.mark.asyncio
class TestJobicyNormalizer:
    async def test_normalizer_output_shape(self):
        mock_response = {
            "jobs": [
                {
                    "jobTitle": "DevOps Eng",
                    "companyName": "Cloud Co",
                    "jobGeo": "US",
                    "url": "https://jobicy.com/job/1",
                    "jobExcerpt": "Terraform role",
                    "pubDate": "2026-04-01",
                }
            ]
        }
        with respx.mock() as mock:
            mock.get("https://jobicy.com/api/v2/remote-jobs").mock(
                return_value=httpx.Response(200, json=mock_response)
            )
            from src.sources.rss import search_jobicy

            jobs = await search_jobicy("devops")

        assert len(jobs) == 1
        _check_job_shape(jobs[0], "jobicy")
