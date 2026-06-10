import anyio
from fastapi import APIRouter, Query

from db.documents import search_chunks
from embedding.embed import embed_query
from api.schemas.search import SearchResponse
from api.mappers import result_from_search_row

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1),
    major: str | None = Query(None),
    category: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
) -> SearchResponse:
    categories = [category] if category else None

    def _run():
        vec = embed_query(q)
        return search_chunks(vec, major=major, categories=categories, limit=limit)

    rows = await anyio.to_thread.run_sync(_run)
    return SearchResponse(results=[result_from_search_row(r) for r in rows])
