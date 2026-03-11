"""Postgres persistence — job tracking and user preferences."""
import os
import asyncpg

_pool = None
POSTGRES_URL = os.getenv("POSTGRES_URL", "")

# Valid statuses in pipeline order
VALID_STATUSES = {"seen", "applied", "interviewing", "offered", "rejected", "closed"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracked_jobs (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    company TEXT,
    status TEXT NOT NULL DEFAULT 'seen',
    notes TEXT,
    updated_at TIMESTAMPTZ DEFAULT now(),
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, url)
);

-- Migrate existing rows: add columns if they don't exist yet
ALTER TABLE tracked_jobs ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE tracked_jobs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

CREATE TABLE IF NOT EXISTS user_prefs (
    user_id TEXT PRIMARY KEY,
    preferred_roles TEXT[],
    preferred_locations TEXT[],
    remote_only BOOLEAN DEFAULT false,
    updated_at TIMESTAMPTZ DEFAULT now()
);
"""


async def init_db():
    global _pool
    _pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=10)
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA)

async def mark_job_seen(user_id: str, url: str, title: str = "", company: str = ""):
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO tracked_jobs (user_id, url, title, company, status)
            VALUES ($1, $2, $3, $4, 'seen')
            ON CONFLICT (user_id, url) DO NOTHING
            """,
            user_id, url, title, company,
        )


async def mark_job_applied(user_id: str, url: str, title: str = "", company: str = ""):
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO tracked_jobs (user_id, url, title, company, status)
            VALUES ($1, $2, $3, $4, 'applied')
            ON CONFLICT (user_id, url) DO UPDATE
                SET status = 'applied', updated_at = now()
            """,
            user_id, url, title, company,
        )


async def update_job_status(user_id: str, url: str, status: str) -> bool:
    """Update status for a tracked job. Returns False if job not found."""
    async with _pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE tracked_jobs SET status = $1, updated_at = now()
            WHERE user_id = $2 AND url = $3
            """,
            status, user_id, url,
        )
    return result != "UPDATE 0"


async def add_job_note(user_id: str, url: str, note: str) -> bool:
    """Append a timestamped note to a tracked job. Returns False if job not found."""
    async with _pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE tracked_jobs
            SET notes = CASE
                WHEN notes IS NULL THEN $1
                ELSE notes || E'\n' || $1
            END,
            updated_at = now()
            WHERE user_id = $2 AND url = $3
            """,
            note, user_id, url,
        )
    return result != "UPDATE 0"

async def get_tracked_jobs(user_id: str, status: str = "applied") -> list[dict]:
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT url, title, company, status, notes, updated_at, created_at
            FROM tracked_jobs
            WHERE user_id = $1 AND status = $2
            ORDER BY updated_at DESC
            """,
            user_id, status,
        )
    return [dict(r) for r in rows]


async def get_all_tracked_jobs(user_id: str) -> list[dict]:
    """Get all tracked jobs for a user regardless of status, ordered by pipeline stage."""
    status_order = "ARRAY['offered','interviewing','applied','seen','rejected','closed']"
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT url, title, company, status, notes, updated_at, created_at
            FROM tracked_jobs
            WHERE user_id = $1
            ORDER BY array_position({status_order}::text[], status), updated_at DESC
            """,
            user_id,
        )
    return [dict(r) for r in rows]


async def get_user_prefs(user_id: str) -> dict:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM user_prefs WHERE user_id=$1", user_id)
    return dict(row) if row else {}
