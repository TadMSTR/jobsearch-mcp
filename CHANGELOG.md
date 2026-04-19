# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed
- `score_fit`, `build_profile`, `tailor_resume`, `cover_letter_brief` now return a readable error message when `ANTHROPIC_API_KEY` is not set, instead of a bare exception class name
- `index_job`, `match_jobs` now return a readable error message when `OLLAMA_HOST` is not set

### Changed
- README Prerequisites section restructured into required / feature-specific / optional tiers
- Added "What you need" capability matrix to README

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
