"""Search transport schemas."""

from typing import List, Optional
from pydantic import BaseModel, Field


class RelatedImage(BaseModel):
    asset_id: int
    reference: str
    number: int
    label: str
    filename: Optional[str] = None
    description: Optional[str] = None
    context: Optional[str] = None
    url: str


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
    related_images: List[RelatedImage] = Field(default_factory=list)


class SearchResponse(BaseModel):
    results: List[SearchResult] = Field(default_factory=list)
