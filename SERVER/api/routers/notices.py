from functools import partial

import anyio
from fastapi import APIRouter, Query

from db.documents import get_documents
from api.schemas.notices import NoticeListResponse
from api.mappers import notice_from_list_row

router = APIRouter()


@router.get("/notices", response_model=NoticeListResponse)
async def notices(
    category: str | None = Query(None),
    major: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> NoticeListResponse:
    rows = await anyio.to_thread.run_sync(
        partial(get_documents, category=category, major=major, limit=limit)
    )
    return NoticeListResponse(notices=[notice_from_list_row(r) for r in rows])
