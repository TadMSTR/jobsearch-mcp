"""Qdrant vector storage with Ollama bge-m3 embeddings for job matching."""

import logging
import os
import uuid

import httpx
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

logger = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://jobsearch-qdrant:6333")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")
COLLECTION = "jobs"
VECTOR_DIM = 1024  # bge-m3 output dimension — matches voyage-3, no schema change needed

_qdrant: AsyncQdrantClient | None = None


async def get_qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(url=QDRANT_URL)
        existing = await _qdrant.get_collections()
        names = [c.name for c in existing.collections]
        if COLLECTION not in names:
            await _qdrant.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
    return _qdrant


async def _embed(texts: list[str]) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{OLLAMA_HOST}/api/embed",
            json={"model": EMBED_MODEL, "input": texts},
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]


async def embed_document(text: str) -> list[float]:
    return (await _embed([text]))[0]


async def embed_query(text: str) -> list[float]:
    # bge-m3 is symmetric — no input_type distinction unlike Voyage AI
    return (await _embed([text]))[0]


async def index_job(url: str, title: str, company: str, content: str) -> str:
    """Embed and upsert a job into Qdrant. Returns stable point ID."""
    qdrant = await get_qdrant()
    text = f"{title} at {company}\n\n{content}"
    vector = await embed_document(text)
    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, url))
    await qdrant.upsert(
        collection_name=COLLECTION,
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload={"url": url, "title": title, "company": company},
            )
        ],
    )
    return point_id


async def search_by_text(
    query_text: str,
    top_k: int = 10,
    exclude_urls: list[str] | None = None,
) -> list[dict]:
    """Find jobs semantically similar to query_text."""
    qdrant = await get_qdrant()
    query_vector = await embed_query(query_text)
    hits = await qdrant.search(
        collection_name=COLLECTION,
        query_vector=query_vector,
        limit=top_k + len(exclude_urls or []),
        with_payload=True,
    )
    exclude_set = set(exclude_urls or [])
    results = []
    for hit in hits:
        payload = hit.payload or {}
        if payload.get("url") in exclude_set:
            continue
        results.append(
            {
                "url": payload.get("url"),
                "title": payload.get("title"),
                "company": payload.get("company"),
                "score": round(hit.score, 4),
            }
        )
        if len(results) >= top_k:
            break
    return results


async def get_index_count() -> int:
    qdrant = await get_qdrant()
    info = await qdrant.get_collection(COLLECTION)
    return info.points_count or 0
