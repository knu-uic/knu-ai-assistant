"""Search transport schemas."""

from typing import List, Optional
from pydantic import BaseModel


class SearchResult(BaseModel):
    url: str
    title: str
    snippet: Optional[str] = None
    score: float
    posted_at: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    category: Optional[str] = None
    summary: Optional[str] = None


class SearchResponse(BaseModel):
    results: List[SearchResult] = []
