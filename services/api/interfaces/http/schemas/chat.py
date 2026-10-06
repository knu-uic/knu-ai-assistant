"""학생 개인 모델 대화 요청/응답 계약."""

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str = Field(max_length=10000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    source: Literal["school", "personal"] = "personal"


class ChatResponse(BaseModel):
    answer: str
