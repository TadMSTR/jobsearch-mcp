# AGENTS.md — jobsearch-mcp

Self-hosted MCP server that turns a LibreChat agent into a full job search assistant — searching across multiple boards, building resume profiles, scoring fit, and tracking applications. Built with FastMCP for multi-user deployments.

## What it does

Exposes 18 MCP tools across five domains:

**Resume Profile:** `build_profile`, `save_profile`, `get_profile`, `delete_profile`, `tailor_resume`
**Search & Discovery:** `search_jobs`, `get_job_detail`, `check_active`, `salary_insights`
**Vector Search:** `index_job`, `match_jobs`
**Fit Scoring:** `score_fit`, `cover_letter_brief`
**Application Tracking:** `mark_seen`, `mark_applied`, `update_status`, `add_note`, `get_my_jobs`

Plus a background `job-watcher` service that polls for new matches and sends email alerts.

## Structure

```
pyproject.toml       # Packaging (hatchling), deps, ruff/pytest config
src/jobsearch_mcp/
  server.py          # FastMCP entry point — registers tool modules; main() console script
  db.py              # Postgres schema, pipeline tracking, profiles (asyncpg)
  enricher.py        # Multi-tier JD fetcher (Firecrawl → Crawl4AI → rawFetch) + Valkey cache
  vector.py          # Qdrant + Ollama bge-m3 embedding and search
  scorer.py          # Claude-powered fit scoring, profile parsing, resume tailoring
  usage.py           # Anthropic token-usage logging + Valkey result cache
  job_watcher.py     # Background poller — email alerts for new matches
  tools/
    jobs.py          # Search, discovery, enrichment tools
    profile.py       # Resume profile tools
    scoring.py       # Fit scoring and cover letter tools
    tracking.py      # Application pipeline tools
  sources/
    adzuna.py        # Adzuna API
    rss.py           # Remotive, WeWorkRemotely, Jobicy (RSS)
    usajobs.py       # USAJobs API
    findwork.py      # Findwork API (optional)
    themuse.py       # The Muse API (optional)
    jobspy.py        # Indeed, Glassdoor, ZipRecruiter (python-jobspy, opt-in)
tests/
  conftest.py        # Shared fixtures (mock httpx, sample jobs/resumes)
  test_db.py         # Database operations
  test_enricher.py   # URL validation, fetch cascade
  test_scorer.py     # Fit scoring logic
  test_sources.py    # Source API parsing
```

## Dependencies

Docker stack (included in docker-compose.yml):

| Service | Purpose |
|---|---|
| Postgres 16 | Per-user tracking, profiles, notes |
| Qdrant | Vector index for semantic job matching |
| Valkey | Enrichment cache (6h TTL) |

External services (configured via env vars):

| Service | Required | Purpose |
|---|---|---|
| Adzuna | Yes | Job search API + salary data |
| Anthropic (Haiku) | Yes | Profile parsing, fit scoring, resume tailoring |
| Firecrawl Simple | Yes | Primary JD extraction |
| Ollama (bge-m3) | Yes | Local embeddings |
| Crawl4AI | No | Fallback JD extraction |
| SMTP relay | No | Job watcher email alerts |
| USAJobs | No | Government job listings |

## Build and run

```bash
cp .env.example .env
# Fill in API keys
docker compose up -d
```

Transport: streamable-http on port 8383.

## Testing

```bash
pip install -e ".[dev]"
pytest -v
ruff check src/ tests/
ruff format --check src/ tests/
```

`ruff` is pinned to `0.16.0` with an explicit `select` in `pyproject.toml` — do not
rely on ruff's default rule set, which widens with each release. `E501` is waived for
`scorer.py` only, because its long lines are Claude prompt templates whose exact text
is measured for cost.

## URL safety

`enricher.py` blocks non-HTTPS URLs and private/internal IP ranges (RFC 1918, loopback, link-local, IPv6 ULA). Do not remove these checks — they prevent SSRF.

## Git workflow

Branch before editing — do not commit directly to `main`.
