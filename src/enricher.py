"""Firecrawl enrichment — fetches clean full job description from a URL."""
import os
import httpx

FIRECRAWL_URL = os.getenv("FIRECRAWL_URL", "http://firecrawl-api:3002")


async def enrich_job(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{FIRECRAWL_URL}/v0/scrape",
                json={"url": url, "pageOptions": {"onlyMainContent": True}},
            )
            resp.raise_for_status()
            data = resp.json()
        return {
            "url": url,
            "content": data.get("data", {}).get("content", ""),
            "title": data.get("data", {}).get("metadata", {}).get("title", ""),
        }
    except Exception as e:
        return {"url": url, "content": "", "error": str(e)}
