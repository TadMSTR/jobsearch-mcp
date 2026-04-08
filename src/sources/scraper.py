"""Light Playwright scraping for LinkedIn job listings — low frequency only."""
import asyncio
import logging
import random

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

_LINKEDIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


async def search_linkedin(query: str, location: str = "", remote_only: bool = False) -> list[dict]:
    results = []
    search_query = query.replace(" ", "%20")
    loc = location.replace(" ", "%20") if location else ""
    f_WT = "&f_WT=2" if remote_only else ""
    url = f"https://www.linkedin.com/jobs/search/?keywords={search_query}&location={loc}{f_WT}"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=_LINKEDIN_UA)
            page = await context.new_page()
            await page.goto(url, timeout=20000)
            await page.wait_for_selector(".job-search-card", timeout=10000)

            cards = await page.query_selector_all(".job-search-card")
            for card in cards[:10]:  # capped at 10 to reduce exposure
                title_el = await card.query_selector(".job-search-card__title")
                company_el = await card.query_selector(".job-search-card__company-name")
                location_el = await card.query_selector(".job-search-card__location")
                link_el = await card.query_selector("a.job-search-card__list-date")

                title = await title_el.inner_text() if title_el else ""
                company = await company_el.inner_text() if company_el else ""
                loc_text = await location_el.inner_text() if location_el else ""
                href = await link_el.get_attribute("href") if link_el else ""

                if title and href:
                    results.append({
                        "title": title.strip(),
                        "company": company.strip(),
                        "location": loc_text.strip(),
                        "url": href.split("?")[0],
                        "description": "",
                        "source": "linkedin",
                        "salary_min": None,
                        "salary_max": None,
                        "date_posted": "",
                    })
                    # 1-2s jitter between cards
                    await asyncio.sleep(random.uniform(1.0, 2.0))

            await browser.close()
    except Exception as e:
        logger.warning("linkedin scrape failed: %s", type(e).__name__)

    return results
