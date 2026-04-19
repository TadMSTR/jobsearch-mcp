"""Background job watcher — polls for new listings matching user profiles, sends email alerts.
Deployed as a separate Docker service (not PM2). Runs on a configurable interval.
Logs to stdout with ISO timestamps — captured by Docker and Alloy pipeline."""

import asyncio
import logging
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .db import init_db, get_all_profiles_with_roles, mark_job_seen, get_tracked_jobs
from .sources.adzuna import search_adzuna
from .sources.rss import search_remotive, search_weworkremotely
from .sources.usajobs import search_usajobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("job_watcher")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp-relay.brevo.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")


def _check_smtp_env() -> None:
    missing = [
        v
        for v in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")
        if not os.getenv(v)
    ]
    if missing:
        logger.error(
            "Required SMTP env vars missing: %s — job_watcher cannot send alerts",
            missing,
        )
        sys.exit(1)


def _send_smtp(msg: MIMEMultipart, to_address: str) -> None:
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, to_address, msg.as_string())


async def _send_email(to_address: str, jobs: list[dict]) -> None:
    if not to_address or not jobs:
        return
    subject = f"{len(jobs)} new job match(es) found — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    lines = []
    for j in jobs[:10]:
        lines.append(f"{j.get('title', 'Unknown')} at {j.get('company', 'Unknown')}")
        if j.get("location"):
            lines.append(f"  Location: {j['location']}")
        lines.append(f"  {j['url']}")
        lines.append("")
    body = "\n".join(lines)

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _send_smtp, msg, to_address)
        logger.info("sent %d job alert(s) to %s", len(jobs), to_address)
    except Exception as e:
        logger.warning("email send failed for %s: %s", to_address, type(e).__name__)


async def _search_for_roles(roles: list[str], location: str = "") -> list[dict]:
    """Run concurrent searches for all target roles across default sources."""
    tasks = []
    for role in roles[:3]:  # cap to 3 roles to avoid excessive API calls
        tasks.extend(
            [
                search_adzuna(role, location),
                search_remotive(role),
                search_weworkremotely(role),
                search_usajobs(role, location),
            ]
        )
    results = await asyncio.gather(*tasks, return_exceptions=True)
    jobs = []
    seen_urls: set[str] = set()
    for batch in results:
        if isinstance(batch, Exception):
            continue
        for job in batch:
            url = job.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                jobs.append(job)
    return jobs


async def _process_user(user_id: str, profile: dict) -> None:
    """Check for new jobs for one user and notify if new matches found."""
    roles = profile.get("target_roles", [])
    if not roles:
        return

    notification_email = profile.get("notification_email", "")
    if not notification_email:
        logger.info("user %s has no notification_email — skipping", user_id)
        return

    location = profile.get("location", "")
    remote_pref = profile.get("remote_preference", "any")
    if remote_pref == "remote_only":
        location = ""  # don't filter by location for remote-only users

    logger.info("checking jobs for user %s (roles: %s)", user_id, roles)

    all_jobs = await _search_for_roles(roles, location)
    if not all_jobs:
        logger.info("no results for user %s", user_id)
        return

    # Filter out already-tracked jobs
    seen = await get_tracked_jobs(user_id, "seen")
    applied = await get_tracked_jobs(user_id, "applied")
    tracked_urls = {j["url"] for j in seen + applied}

    new_jobs = [j for j in all_jobs if j.get("url") and j["url"] not in tracked_urls]
    if not new_jobs:
        logger.info(
            "no new jobs for user %s (all %d results already tracked)",
            user_id,
            len(all_jobs),
        )
        return

    logger.info("found %d new jobs for user %s", len(new_jobs), user_id)

    # Mark new jobs as seen before notifying
    for job in new_jobs[:20]:
        try:
            await mark_job_seen(
                user_id, job["url"], job.get("title", ""), job.get("company", "")
            )
        except Exception as e:
            logger.warning(
                "mark_job_seen failed for %s: %s", job["url"], type(e).__name__
            )

    await _send_email(notification_email, new_jobs[:10])


async def run_once() -> None:
    """Run one watcher cycle — check all users with profiles."""
    logger.info("watcher cycle start")
    try:
        users = await get_all_profiles_with_roles()
    except Exception as e:
        logger.error("failed to load user profiles: %s", type(e).__name__)
        return

    if not users:
        logger.info("no users with target_roles configured")
        return

    logger.info("processing %d user(s)", len(users))
    for entry in users:
        try:
            await _process_user(entry["user_id"], entry["profile"])
        except Exception as e:
            logger.error(
                "error processing user %s: %s", entry["user_id"], type(e).__name__
            )

    logger.info("watcher cycle complete")


async def main() -> None:
    _check_smtp_env()
    await init_db()
    await run_once()


if __name__ == "__main__":
    asyncio.run(main())
