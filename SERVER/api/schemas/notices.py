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
