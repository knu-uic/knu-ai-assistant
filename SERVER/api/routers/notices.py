from functools import partial

import anyio
from fastapi import APIRouter, Query, Request

from db.documents import get_documents
from api.ratelimit import limiter, user_or_ip
from api.schemas.notices import NoticeListResponse
from api.mappers import notice_from_list_row
from config import RATE_LIMIT_READ

router = APIRouter()


@router.get("/notices", response_model=NoticeListResponse)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def notices(
    request: Request,
    category: str | None = Query(None),
    major: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> NoticeListResponse:
    rows = await anyio.to_thread.run_sync(
        partial(get_documents, category=category, major=major, limit=limit)
    )
    return NoticeListResponse(notices=[notice_from_list_row(r) for r in rows])
