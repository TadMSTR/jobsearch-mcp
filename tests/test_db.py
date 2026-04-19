"""Tests for db.py — profile and job tracking functions (unit tests with mocked pool)."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_pool():
    """Provide a mock asyncpg pool for db tests."""
    conn = AsyncMock()
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = pool_ctx
    return pool, conn


@pytest.mark.asyncio
class TestGetUserProfile:
    async def test_returns_none_when_not_found(self, mock_pool):
        pool, conn = mock_pool
        conn.fetchrow.return_value = None

        with patch("src.db._pool", pool):
            from src.db import get_user_profile

            result = await get_user_profile("user123")

        assert result is None

    async def test_returns_dict_when_found(self, mock_pool, sample_profile):
        pool, conn = mock_pool
        row = MagicMock()
        row.__getitem__ = MagicMock(return_value=json.dumps(sample_profile))
        conn.fetchrow.return_value = row

        with patch("src.db._pool", pool):
            from src.db import get_user_profile

            result = await get_user_profile("user123")

        assert result is not None
        assert result["name"] == sample_profile["name"]


@pytest.mark.asyncio
class TestUpsertUserProfile:
    async def test_calls_execute_with_user_id(self, mock_pool, sample_profile):
        pool, conn = mock_pool
        conn.execute.return_value = None

        with patch("src.db._pool", pool):
            from src.db import upsert_user_profile

            await upsert_user_profile("user123", sample_profile)

        conn.execute.assert_called_once()
        call_args = conn.execute.call_args[0]
        assert "user123" in call_args


@pytest.mark.asyncio
class TestDeleteUserProfile:
    async def test_returns_false_when_not_found(self, mock_pool):
        pool, conn = mock_pool
        conn.execute.return_value = "DELETE 0"

        with patch("src.db._pool", pool):
            from src.db import delete_user_profile

            result = await delete_user_profile("user123")

        assert result is False

    async def test_returns_true_when_deleted(self, mock_pool):
        pool, conn = mock_pool
        conn.execute.return_value = "DELETE 1"

        with patch("src.db._pool", pool):
            from src.db import delete_user_profile

            result = await delete_user_profile("user123")

        assert result is True


@pytest.mark.asyncio
class TestMarkJobSeen:
    async def test_calls_insert(self, mock_pool):
        pool, conn = mock_pool
        conn.execute.return_value = None

        with patch("src.db._pool", pool):
            from src.db import mark_job_seen

            await mark_job_seen(
                "user123", "https://example.com/job", "Engineer", "Acme"
            )

        conn.execute.assert_called_once()

    async def test_passes_correct_args(self, mock_pool):
        pool, conn = mock_pool
        conn.execute.return_value = None

        with patch("src.db._pool", pool):
            from src.db import mark_job_seen

            await mark_job_seen(
                "user123", "https://example.com/job", "Engineer", "Acme"
            )

        args = conn.execute.call_args[0]
        assert "user123" in args
        assert "https://example.com/job" in args


@pytest.mark.asyncio
class TestGetAllTrackedJobs:
    async def test_returns_list(self, mock_pool):
        pool, conn = mock_pool
        conn.fetch.return_value = []

        with patch("src.db._pool", pool):
            from src.db import get_all_tracked_jobs

            result = await get_all_tracked_jobs("user123")

        assert isinstance(result, list)
