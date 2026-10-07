"""Portable KNU PICK history contract; server owns identity and timestamps."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=100000)


class ConversationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=100)
    source: Literal["school", "personal"] = "personal"
    messages: list[HistoryMessage] = Field(max_length=10000)

    @model_validator(mode="after")
    def bounded_payload(self):
        if sum(len(message.content) for message in self.messages) > 1000000:
            raise ValueError("대화 기록은 100만 자 이하로 저장할 수 있습니다.")
        return self


class ConversationCreate(ConversationWrite):
    id: UUID | None = None


class ConversationUpdate(ConversationWrite):
    revision: int = Field(ge=1)


class ConversationSummary(BaseModel):
    id: UUID
    title: str
    source: Literal["school", "personal"]
    revision: int
    created_at: datetime
    updated_at: datetime


class Conversation(ConversationSummary):
    messages: list[HistoryMessage]


class ConversationPage(BaseModel):
    items: list[ConversationSummary]
    next_cursor: str | None = None


class LegacyConversation(ConversationWrite):
    legacy_key: str = Field(min_length=1, max_length=128)


class HistoryImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[LegacyConversation] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def bounded_import(self):
        if sum(len(message.content) for item in self.items for message in item.messages) > 1000000:
            raise ValueError("한 번에 가져올 대화 기록은 100만 자 이하입니다.")
        return self
