"""Notice transport schemas."""

from typing import List, Optional
from pydantic import BaseModel


class NoticeItem(BaseModel):
    url: str
    title: str
    content: Optional[str] = None
    summary: Optional[str] = None
    posted_at: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    category: Optional[str] = None
    target: List[str] = []
    keywords: List[str] = []
    source_name: Optional[str] = None


class NoticeListResponse(BaseModel):
    notices: List[NoticeItem] = []
    # 다음 페이지 커서. 마지막 페이지면 null. 기존 앱은 이 키를 몰라도 동작.
    next_cursor: Optional[str] = None
