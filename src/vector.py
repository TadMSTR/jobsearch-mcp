"""Qdrant vector storage with Voyage AI embeddings for job matching."""
import os
import uuid
import voyageai
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

QDRANT_URL = os.getenv("QDRANT_URL", "http://jobsearch-qdrant:6333")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
COLLECTION = "jobs"
EMBEDDING_MODEL = "voyage-3"
VECTOR_DIM = 1024  # voyage-3 output dimension

_qdrant: AsyncQdrantClient | None = None
_voyage: voyageai.AsyncClient | None = None


def _get_voyage() -> voyageai.AsyncClient:
    global _voyage
    if _voyage is None:
        _voyage = voyageai.AsyncClient(api_key=VOYAGE_API_KEY)
    return _voyage


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

async def embed_document(text: str) -> list[float]:
    voyage = _get_voyage()
    result = await voyage.embed([text], model=EMBEDDING_MODEL, input_type="document")
    return result.embeddings[0]


async def embed_query(text: str) -> list[float]:
    voyage = _get_voyage()
    result = await voyage.embed([text], model=EMBEDDING_MODEL, input_type="query")
    return result.embeddings[0]


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
        results.append({
            "url": payload.get("url"),
            "title": payload.get("title"),
            "company": payload.get("company"),
            "score": round(hit.score, 4),
        })
        if len(results) >= top_k:
            break
    return results


async def get_index_count() -> int:
    qdrant = await get_qdrant()
    info = await qdrant.get_collection(COLLECTION)
    return info.points_count or 0
