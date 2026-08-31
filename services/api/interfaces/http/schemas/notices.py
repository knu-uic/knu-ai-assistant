"""Notice transport schemas."""

from typing import List, Optional
from pydantic import BaseModel, Field


class NoticeItem(BaseModel):
    url: str
    title: str
    content: Optional[str] = None
    summary: Optional[str] = None
    posted_at: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    category: Optional[str] = None
    target: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    source_name: Optional[str] = None
    department: Optional[str] = None
    deadline_label: Optional[str] = None
    deadline_tone: Optional[str] = None


class NoticeListResponse(BaseModel):
    notices: List[NoticeItem] = Field(default_factory=list)
    # 다음 페이지 커서. 마지막 페이지면 null. 기존 앱은 이 키를 몰라도 동작.
    next_cursor: Optional[str] = None
