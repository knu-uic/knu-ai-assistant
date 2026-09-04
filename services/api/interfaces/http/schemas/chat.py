"""Chat transport schemas."""

from typing import List, Optional

from pydantic import BaseModel, Field
from interfaces.http.schemas.search import RelatedImage


class ChatRequest(BaseModel):
    question: str
    major: Optional[str] = None


class ChatResponse(BaseModel):
    # api_service.dart ChatResult와 1:1 (flat 키). 없는 값은 null.
    answer: str
    grounded: Optional[bool] = None
    fidelity: Optional[float] = None
    verifier_note: Optional[str] = None
    categories: List[str] = Field(default_factory=list)
    expanded_query: Optional[str] = None
    related_images: List[RelatedImage] = Field(default_factory=list)
