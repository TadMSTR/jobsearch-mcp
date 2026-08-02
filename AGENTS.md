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
| Valkey | Enrichment cache (6h TTL) + Claude result cache (24h TTL) |

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

## Anthropic API cost

Every Claude call goes through `scorer._claude()`, which logs an `event=claude_usage`
line with token counts, the tool name and the user ID. `score_fit` and
`cover_letter_brief` results are cached in Valkey for 24h; a cache hit logs
`cached=True` with no token counts at all.

Three things that look like improvements but are not — all measured, not assumed:

1. **Do not add prompt caching.** Haiku 4.5 requires a 4,096-token minimum cacheable
   prefix. The largest prompt this server sends measures 2,375 at its truncation cap;
   the cacheable-prefix candidate is 1,162. `cache_control` would return
   `cache_creation_input_tokens: 0` forever — it no-ops silently rather than erroring,
   so it looks like it worked.
2. **Do not switch models to make caching viable.** A model with a 1,024-token minimum
   costs roughly 1.7x more per workflow at current pricing.
3. **Do not migrate FastMCP code.** 3.4.5 works. The pin has a `<4` ceiling; if you
   raise it, test `lifespan=`, `ctx.request_context.request.headers`, and the
   `host`/`port` kwargs to `mcp.run()`.

Haiku's input:output price ratio is 1:5, so output tokens dominate the bill.
Optimize call count first, then output size, then input size — not the reverse.

## URL safety

`enricher.py` blocks non-HTTPS URLs and any destination that is not globally routable. Do
not remove or weaken these checks — they prevent SSRF, and `url` is a caller-supplied
parameter on five tools (`get_job_detail`, `index_job`, `check_active`, `score_fit`,
`cover_letter_brief`), so anything reaching this code is attacker-influenceable.

Three parts, all load-bearing:

1. `_validate_url` resolves hostnames via `_resolve_host` and checks **every** returned
   address. Checking only literal-IP hosts (the pre-v2.2.0 behaviour) left
   `https://name-resolving-to-10.0.0.1/` wide open.
2. `_is_blocked_address` uses `is_global`, **not** `is_private` — the stdlib has reported
   CGNAT (100.64.0.0/10) as non-private since Python 3.12.4. Multicast and reserved are
   checked separately because they are absent from the IANA registry backing `is_global`.
3. `_fetch_raw` follows redirects manually and re-validates each hop. Do not "simplify" it
   back to `follow_redirects=True` — that reintroduces a bypass, since the original
   validation never sees the redirect target.

Residual, documented: DNS rebinding between validation and connection is not caught.

## Git workflow

Branch before editing — do not commit directly to `main`.
