"""Standalone React web search endpoint."""

import anyio
from fastapi import APIRouter, Query, Request

from db.documents import search_chunks
from embedding.embed import embed_query
from api.ratelimit import limiter, user_or_ip
from interfaces.http.schemas.search import SearchResponse
from api.mappers import result_from_search_row
from config import RATE_LIMIT_READ

router = APIRouter()


async def search_notice_results(
    q: str,
    major: str | None = None,
    category: str | None = None,
    limit: int = 10,
):
    categories = [category] if category else None

    def _run():
        vec = embed_query(q)
        return search_chunks(vec, major=major, categories=categories, limit=limit)

    rows = await anyio.to_thread.run_sync(_run)
    return [result_from_search_row(row) for row in rows]


@router.get("/search", response_model=SearchResponse)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def search(
    request: Request,
    q: str = Query(..., min_length=1),
    major: str | None = Query(None),
    category: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
) -> SearchResponse:
    return SearchResponse(
        results=await search_notice_results(q, major=major, category=category, limit=limit)
    )
