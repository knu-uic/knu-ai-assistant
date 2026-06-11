import base64
import binascii
from datetime import datetime
from functools import partial

import anyio
from fastapi import APIRouter, HTTPException, Query, Request

from db.documents import get_documents
from api.ratelimit import limiter, user_or_ip
from api.schemas.notices import NoticeListResponse
from api.mappers import notice_from_list_row
from config import HIDDEN_NOTICE_SOURCE_CODES, RATE_LIMIT_READ

router = APIRouter()


def _encode_cursor(sort_ts: datetime, url: str) -> str:
    raw = f"{sort_ts.isoformat()}|{url}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts, sep, url = raw.partition("|")
    if not sep or not url:
        raise ValueError("malformed cursor")
    return datetime.fromisoformat(ts), url


@router.get("/notices", response_model=NoticeListResponse)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def notices(
    request: Request,
    category: str | None = Query(None),
    major: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
) -> NoticeListResponse:
    cursor_ts, cursor_url = None, None
    if cursor:
        try:
            cursor_ts, cursor_url = _decode_cursor(cursor)
        except (ValueError, binascii.Error, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="잘못된 페이지 커서입니다.")

    # limit+1로 한 행 더 가져와 다음 페이지 존재 여부를 판정한다.
    rows = await anyio.to_thread.run_sync(
        partial(
            get_documents,
            category=category,
            major=major,
            limit=limit + 1,
            cursor_ts=cursor_ts,
            cursor_url=cursor_url,
            exclude_codes=HIDDEN_NOTICE_SOURCE_CODES,
        )
    )
    has_more = len(rows) > limit
    rows = rows[:limit]

    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        # row 구성: [0]=url, [-1]=sort_ts (documents.get_documents SELECT 순서)
        next_cursor = _encode_cursor(last[-1], last[0])

    return NoticeListResponse(
        notices=[notice_from_list_row(r) for r in rows],
        next_cursor=next_cursor,
    )
