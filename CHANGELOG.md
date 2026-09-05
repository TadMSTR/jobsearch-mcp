# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed
- **`anthropic` gained an upper bound (`>=0.40.0,<1`) — without it the test suite's Claude mocks stop working silently.** `anthropic` 1.x moved its HTTP stack from `httpx` to `httpx2`. `respx` patches `httpx`, so it cannot see an `httpx2` transport: `respx.mock()` does not fail as an unmatched mock, it passes the request straight through to `https://api.anthropic.com`. On an unpinned install the 4 tests in `test_scorer.py` and 3 in `test_usage.py` were making real API calls and failing 401 on the dummy key the test modules set. Worse, a run with a *valid* key in the environment would have spent real tokens and passed, hiding the fact that transport-level mocking had stopped working at all. `0.x` is also what the deployed container runs (0.120.2), so this aligns CI with production rather than diverging from it. Suite goes from 58 passed / 7 failed to **65 passed**; runtime drops 4.24s to 0.48s, which is the absence of the network round-trips. Raising the ceiling to 1.x means first replacing respx for these tests — tracked in vikunja#651, deliberately not bundled here.

## [2.2.0] - 2026-08-01

Repo standardization, forge deployment fixes, and Anthropic API cost reduction.

### Security
- **Fixed an SSRF gap in `enricher.py` that allowed reaching internal services.** Two independent holes combined: `_validate_url` only checked the private-address blocklist when the URL's host was already a literal IP, so `https://a-name-that-resolves-to-10.0.0.1/` passed; and `_fetch_raw` used `follow_redirects=True`, so a public `https` URL could `302` to `http://192.168.1.x/` and the redirect target was never re-checked. Because `url` is a direct parameter on five tools (`get_job_detail`, `index_job`, `check_active`, `score_fit`, `cover_letter_brief`), any caller could reach an arbitrary address and have the response reflected back in the tool result.
  - Hostnames are now resolved with `socket.getaddrinfo` and **every** returned address is checked before the fetch — a single private address among several public ones is enough to reject.
  - Redirects are followed manually (maximum 5) with the full scheme and address check re-run against each hop.
  - The blocked set widened beyond RFC1918/loopback to everything not globally routable, plus multicast and reserved space — this closes `0.0.0.0` (which reaches localhost on Linux), `169.254.169.254` (cloud metadata), CGNAT, and IPv4-mapped IPv6 (`::ffff:10.0.0.1`). Note `is_global` is used rather than `is_private`: the stdlib has reported CGNAT as non-private since Python 3.12.4.
  - Known residual: this is a resolve-then-connect check, so DNS rebinding between validation and the HTTP client's own lookup is not caught. Closing that requires pinning the connection to the validated address.
  - 21 new tests in `tests/test_enricher.py` covering hostname resolution, redirect rejection, redirect-chain capping, and each non-public address class — including a regression test proving legitimate public redirects still work.

### Added
- `OLLAMA_API_KEY` env var support — when set, adds `Authorization: Bearer <key>` to Ollama embed requests. No behavior change when unset.
- `pyproject.toml` (hatchling). The project is now an installable package: `pip install -e ".[dev]"`, importable as `jobsearch_mcp`, with a `jobsearch-mcp` console script. Replaces `requirements.txt` / `requirements-dev.txt` / `pytest.ini`.
- `usage.py` — per-call Anthropic token-usage logging. Every Claude call emits a structured `event=claude_usage` line with `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, the tool name and the user ID. `message.usage` was previously discarded, so there was no cost instrumentation at all.
- Valkey result cache for `score_fit` and `cover_letter_brief` — 24h TTL, keyed on a hash of the truncated JD + resume actually sent. A repeat call on a job already scored costs zero tokens and logs `cached=True` with no token counts. Cache keys carry a prompt-version prefix so a future prompt change cannot serve stale-shaped results.
- `tests/test_usage.py` — 14 tests covering cache keying, hit/miss behaviour, backend-failure tolerance, truncation detection, and the usage log format.

### Changed
- **Package layout: `src/` → `src/jobsearch_mcp/`.** The old flat layout only ran as `python -m src.server` from the repo root. Dockerfile now installs the package and runs the console script; `job-watcher` runs `python -m jobsearch_mcp.job_watcher`.
- **`tailor_resume` returns only what changed** — `tailored_summary`, `skills_reordered`, `experience_changes` (per-role revised highlights) and `changes_summary`, instead of regenerating the whole profile. Unchanged roles, education, certifications and contact details are no longer echoed back. `max_tokens` reduced 2048 → 1536. **This is a tool-contract change** for anything consuming `tailored_profile`.
- Stored profiles are trimmed before being sent to the scoring prompts — only `summary`, `skills`, `experience`, `certifications` and `target_roles` are included. Measured: 1,121 → 1,013 input tokens (−9.6%) on a representative profile. As a side effect this stops sending `name`, `email`, `location`, `work_authorization`, `salary_min`/`salary_max`, `notification_email`, `remote_preference` and `education` to the Anthropic API on every scoring call — none were used by the rubric.
- `ruff` pinned to `0.16.0` with an explicit rule set (`E`, `F`, `W`, `I`, `UP`, `B`, `SIM`, `RUF`). CI was previously on `ruff>=0.11.0`; ruff 0.16.1's widened default select flagged 42 errors and would have failed the next push. `E501` is waived for `scorer.py` only, whose long lines are prompt templates with measured token counts.
- `fastmcp` gained an upper bound (`>=3.0,<4`). It previously pinned only `>=2.0.0` and resolved to 3.4.5 by luck. No code migration was needed — 3.4.5 works as-is.
- Compose: `jobsearch-mcp` and `job-watcher` now join the external `forge-net` alongside the private `jobsearch-net`, so Firecrawl, Crawl4AI and Ollama resolve by container name. `FIRECRAWL_URL` defaulted to `localhost:3002` (which resolves to the container itself) and `CRAWL4AI_URL` to `host.docker.internal` (with no `extra_hosts` declared) — both were wrong inside a container.
- Compose: MCP port now binds `127.0.0.1:8383` instead of `0.0.0.0`. The server has no built-in authentication.
- Compose: Qdrant image pinned to `v1.18.3` (was the floating `qdrant/qdrant`).
- CI installs via `pip install -e ".[dev]"`; the dependency audit runs against the installed environment rather than a `requirements.txt` that no longer exists. The `CVE-2025-46656` ignore is retained — `markdownify` is still capped by `python-jobspy`.
- README Prerequisites section restructured into required / feature-specific / optional tiers
- Added "What you need" capability matrix to README

### Fixed
- `score_fit`, `build_profile`, `tailor_resume`, `cover_letter_brief` now return a readable error message when `ANTHROPIC_API_KEY` is not set, instead of a bare exception class name
- `index_job`, `match_jobs` now return a readable error message when `OLLAMA_HOST` is not set
- A Claude response truncated by the `max_tokens` cap now raises a clear error naming the tool and the cap, instead of surfacing as an opaque JSON decode failure.
- `search_jobs` no longer uses a mutable list as a default argument (`B006`). Behaviour is unchanged — the defaults are documented in the tool description and applied when the argument is omitted.

### Notes
- **Anthropic prompt caching is deliberately not implemented.** Haiku 4.5's minimum cacheable prefix is 4,096 tokens; the largest prompt this server sends measures 2,375 at its truncation cap, and the cacheable-prefix candidate is 1,162. `cache_control` would silently no-op with `cache_creation_input_tokens: 0` rather than error. Verified against a live call: cache fields are 0.
- **The model stays `claude-haiku-4-5-20251001`.** Moving to a model with a 1,024-token cache minimum would make caching viable but costs roughly 1.7× more per workflow at current pricing. Because Haiku's input:output price ratio is 1:5, output tokens dominate the bill — which is why the result cache and the `tailor_resume` output reduction rank above input trimming.

## [2.1.0] - 2026-04-08

### Security
- Restricted `_validate_url` to HTTPS-only — blocks HTTP URLs to prevent cleartext credential exposure (audit finding M1)
- Applied security audit findings: input validation, URL allowlisting

### Changed
- Rewrote README for v2 architecture and tool documentation

## [2.0.0] - 2026-04-08

### Added
- Resume profile system — `build_profile`, `save_profile`, `get_profile`, `delete_profile`, `tailor_resume`
- `score_fit` uses stored profile automatically when no resume is passed
- `cover_letter_brief` — structured writing guide using stored profile
- `match_jobs` — semantic search against indexed jobs via Qdrant + Ollama bge-m3
- `index_job` — store jobs in vector index for semantic matching
- `check_active` — verify whether a listing is still live
- `salary_insights` — salary intelligence powered by Adzuna data
- Optional sources: Indeed, Glassdoor, ZipRecruiter via python-jobspy with rate limiting and per-site exponential backoff
- Findwork and The Muse as optional API-based sources
- Job watcher background service with SMTP email alerts for new matches
- Multi-tier JD enrichment: Firecrawl → Crawl4AI → raw HTTP fetch with Valkey caching
- Docker Compose stack: Postgres, Qdrant, Valkey on isolated bridge network
- Security hardening: `no-new-privileges`, `cap_drop: ALL`, `user: 1000:1000`

### Changed
- Replaced Voyage AI cloud embeddings with local Ollama bge-m3 — resume/profile data no longer leaves the host
- Switched from firecrawl to firecrawl-simple (trieve fork)

## [1.0.0] - 2026-03-11

### Added
- Initial job search MCP server with Adzuna integration
- `search_jobs`, `get_job_detail` tools
- Firecrawl integration for JD extraction
- Application tracking: `mark_seen`, `mark_applied`, `update_status`, `add_note`, `get_my_jobs`
- Postgres-backed per-user state partitioned by X-User-ID header

[Unreleased]: https://github.com/TadMSTR/jobsearch-mcp/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/TadMSTR/jobsearch-mcp/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/TadMSTR/jobsearch-mcp/releases/tag/v2.0.0
[1.0.0]: https://github.com/TadMSTR/jobsearch-mcp/releases/tag/v1.0.0
