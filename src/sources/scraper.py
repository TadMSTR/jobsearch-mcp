"""Light Playwright scraping for LinkedIn job listings — low frequency only."""
from playwright.async_api import async_playwright


async def search_linkedin(query: str, location: str = "", remote_only: bool = False) -> list[dict]:
    results = []
    search_query = query.replace(" ", "%20")
    loc = location.replace(" ", "%20") if location else ""
    f_WT = "&f_WT=2" if remote_only else ""
    url = f"https://www.linkedin.com/jobs/search/?keywords={search_query}&location={loc}{f_WT}"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=20000)
            await page.wait_for_selector(".job-search-card", timeout=10000)

            cards = await page.query_selector_all(".job-search-card")
            for card in cards[:15]:
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
                    })

            await browser.close()
    except Exception:
        pass

    return results
