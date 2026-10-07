"""학생 개인 모델 대화 요청/응답 계약."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from interfaces.http.schemas.conversations import Conversation


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=10000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    source: Literal["school", "personal"] = "personal"
    conversation_id: UUID | None = None
    revision: int = Field(default=0, ge=0)
    request_id: UUID | None = None

    @model_validator(mode="after")
    def server_history_contract(self):
        if self.conversation_id is not None and (self.history or self.request_id is None):
            raise ValueError("서버 대화에는 request_id가 필요하며 history를 직접 전달할 수 없습니다.")
        return self


class ChatResponse(BaseModel):
    answer: str
    conversation: Conversation | None = None
    context: dict | None = None
