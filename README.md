# jobsearch-mcp

A self-hosted MCP server that turns a LibreChat agent into a full job search assistant — from finding listings across multiple boards, to scoring resume fit, to tracking applications through a pipeline. Built with FastMCP for multi-user LibreChat deployments.

**Search** across Adzuna, Remotive, WeWorkRemotely, Jobicy, and LinkedIn from a single tool call. **Enrich** listings with full job descriptions via Firecrawl. **Score** resume fit with a structured Claude-powered breakdown. **Match** jobs semantically against your resume using vector search. **Track** applications through a full pipeline with notes and status updates — per user, persisted in Postgres.

Most job search MCP tools do one thing — scrape listings or generate cover letters. This one connects the entire workflow so an agent can drive it end-to-end.

## Screenshots

<!-- TODO: Add screenshots of a LibreChat agent session showing the workflow -->
<!-- Suggested screenshots:
  1. Agent searching for jobs and returning results
  2. score_fit output showing the structured breakdown
  3. get_my_jobs showing the application pipeline
-->

*Screenshots coming soon — showing an agent driving the full search → score → track workflow in LibreChat.*

---

## How It Works

```
search_jobs ──→ check_active ──→ get_job_detail ──→ index_job
                                       │                 │
                               salary_insights      match_jobs (semantic search)
                                       │                 │
                                   score_fit ◄───────────┘
                                       │
                               cover_letter_brief
                                       │
                              mark_applied + add_note
                                       │
                                  update_status
                              (interviewing → offered → ...)
```

You don't have to use every tool — an agent can search and score without ever touching the tracker, or use the tracker standalone for jobs found elsewhere.

---

## Tools

### Search & Discovery

| Tool | Description |
|------|-------------|
| `search_jobs` | Search across Adzuna, Remotive, WeWorkRemotely, Jobicy, and LinkedIn. Returns deduplicated results. Supports `query`, `location`, `remote_only`, and `sources` params. |
| `get_job_detail` | Fetch a clean, full job description from a URL via Firecrawl. |
| `check_active` | Check whether a listing is still active. Returns `active=True/False/None` and the signal that triggered the result. |
| `salary_insights` | Get salary intelligence for a job title or query. Returns a summary (min/max/avg/median from live listings), a histogram of salary distribution bands, and a monthly trend — all via Adzuna. |

### Vector Search & Matching

| Tool | Description |
|------|-------------|
| `index_job` | Fetch a job via Firecrawl and store it in Qdrant for semantic search. Call this on listings worth tracking. |
| `match_jobs` | Find indexed jobs semantically similar to a resume or free-text description. Supports `top_k` and `exclude_seen` params. |

### Fit Scoring & Application Prep

| Tool | Description |
|------|-------------|
| `score_fit` | Score how well a resume matches a job. Fetches the full JD, then uses Claude to return a structured breakdown: matched skills, missing skills, nice-to-haves met, seniority fit, overall score (0–100), and an `apply/maybe/skip` recommendation. |
| `cover_letter_brief` | Generate a structured cover letter writing brief — opening angle, requirements mapped to your resume, experience to lead with, gaps to acknowledge, recommended tone. A writing guide, not a finished letter. |

### Application Tracking

| Tool | Description |
|------|-------------|
| `mark_seen` | Mark a job as seen for the current user. |
| `mark_applied` | Mark a job as applied. |
| `update_status` | Move a job through the pipeline: `seen` → `applied` → `interviewing` → `offered` → `rejected` → `closed`. |
| `add_note` | Append a note to a tracked job (recruiter contacts, interview feedback, referrals, etc.). Notes accumulate — they are not replaced. |
| `get_my_jobs` | Get tracked jobs for the current user. Defaults to all — returns the full pipeline ordered by stage. Filter by status with the `status` param. |

---

## Prerequisites

You'll need accounts/keys for the following services before deploying:

| Service | What it does here | How to get credentials |
|---------|------------------|----------------------|
| **Adzuna** | Job search API + salary data | Free API key at [developer.adzuna.com](https://developer.adzuna.com/) |
| **Firecrawl** | Extracts clean text from job listing URLs | Self-host via Docker ([github.com/mendableai/firecrawl](https://github.com/mendableai/firecrawl)) or use the hosted API |
| **Voyage AI** | Generates embeddings for semantic job matching | API key at [dash.voyageai.com](https://dash.voyageai.com/) |
| **Anthropic** | Powers the `score_fit` resume analysis (uses Haiku) | API key at [console.anthropic.com](https://console.anthropic.com/) |

Postgres and Qdrant are included in the Docker stack — no external setup needed for those.

---

## Stack

| Component | Purpose |
|-----------|---------|
| FastMCP (streamable-http) | MCP server transport |
| Postgres 16 | Per-user job tracking and pipeline state |
| Qdrant | Vector index for semantic job matching |
| Voyage AI (`voyage-3`) | Job and resume embeddings |
| Firecrawl | Full job description extraction |
| Claude (`claude-haiku-4-5`) | Resume/JD fit scoring |

---

## Deployment

### Docker Stack

The project ships as a Docker Compose stack with three containers:

| Container | Image | Exposed Port |
|-----------|-------|-------------|
| jobsearch-mcp | Local build from `Dockerfile` | 8383 (MCP endpoint) |
| jobsearch-postgres | postgres:16 | Internal only |
| jobsearch-qdrant | qdrant/qdrant | Internal only |

### Setup

1. **Clone the repo:**

   ```bash
   git clone https://github.com/TadMSTR/jobsearch-mcp.git
   cd jobsearch-mcp
   ```

2. **Create your `.env` file** (in the same directory as `docker-compose.yml`):

   ```env
   # Postgres
   POSTGRES_USER=jobsearch
   POSTGRES_PASSWORD=<your-password>

   # Adzuna API
   ADZUNA_APP_ID=
   ADZUNA_APP_KEY=

   # Firecrawl — URL to your Firecrawl instance
   FIRECRAWL_URL=http://localhost:3002

   # Voyage AI
   VOYAGE_API_KEY=

   # Anthropic — used by score_fit
   ANTHROPIC_API_KEY=
   ```

3. **Start the stack:**

   ```bash
   docker compose up -d
   ```

4. **Verify it's running:**

   ```bash
   docker logs jobsearch-mcp --tail 20
   ```

   You should see the FastMCP server start on port 8383.

### Rebuilding after code changes

```bash
docker compose build jobsearch-mcp
docker compose up -d jobsearch-mcp
```

---

## Wiring to LibreChat

Add the following to your `librechat.yaml` under `mcpServers`:

```yaml
mcpServers:
  jobsearch:
    type: streamable-http
    url: http://host.docker.internal:8383/mcp
    headers:
      X-User-ID: "{{LIBRECHAT_USER_ID}}"
      X-User-Email: "{{LIBRECHAT_USER_EMAIL}}"
      X-User-Username: "{{LIBRECHAT_USER_USERNAME}}"
```

The server uses `X-User-ID` to partition all tracking data per LibreChat user. Each user gets their own pipeline, notes, and seen/applied state.

**Important:** If LibreChat runs in Docker, you need `host.docker.internal` to reach the MCP server on the host. Make sure your LibreChat compose file includes:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Restart LibreChat after any `librechat.yaml` change:

```bash
docker compose restart librechat
```

---

## Project Structure

```
jobsearch-mcp/
├── Dockerfile
├── requirements.txt
├── docker-compose.yml
└── src/
    ├── __init__.py
    ├── server.py        # FastMCP instance and all tool definitions
    ├── db.py            # Postgres schema, pipeline tracking, notes (asyncpg)
    ├── enricher.py      # Firecrawl job description fetcher
    ├── vector.py        # Qdrant + Voyage AI embedding and search
    ├── scorer.py        # Claude-powered resume/JD fit analysis
    └── sources/
        ├── __init__.py
        ├── adzuna.py    # Adzuna API
        ├── rss.py       # Remotive, WeWorkRemotely, Jobicy (RSS)
        └── scraper.py   # LinkedIn (Playwright scraper)
```

---

## Notes

- **LinkedIn scraping** uses Playwright/Chromium. Results depend on LinkedIn's current page structure and may break without notice. The other sources (Adzuna API, RSS feeds) are stable.
- **Qdrant collection** (`jobs`) is created automatically on first use. No manual setup needed.
- **Voyage AI** uses separate `document`/`query` input types — jobs are indexed as documents, resume/query text is embedded as a query. This asymmetric approach produces better match quality than symmetric embedding.
- **`score_fit`** uses `claude-haiku-4-5` for speed and cost. JD is truncated to 6000 chars, resume to 3000 chars.
- **`check_active`** returns `active=None` when the page loads but no clear signal is found — treat as probably active.
- **Postgres schema** migrates automatically on startup (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`). No manual migrations needed.
- **Multi-user** — all tracking state is partitioned by the `X-User-ID` header. Multiple LibreChat users can use the same server instance without seeing each other's data.

---

## License

MIT
