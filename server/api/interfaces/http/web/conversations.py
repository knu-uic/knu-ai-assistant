"""KNU PICK web/mobile history. Not a Codmes conversation adapter."""
import base64
import binascii
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.deps import portal_student_id, require_user
from api.ratelimit import limiter, user_or_ip
from config import RATE_LIMIT_READ, RATE_LIMIT_POLL
from db import conversations as repository
from interfaces.http.schemas.conversations import (
    Conversation, ConversationCreate, ConversationPage, ConversationUpdate, HistoryImport,
)

router = APIRouter()


def student(principal: str = Depends(require_user)) -> str:
    identity = portal_student_id(principal)
    if not identity:
        raise HTTPException(403, "학생 계정이 필요합니다.")
    return identity


def _cursor(raw):
    if not raw:
        return None
    try:
        timestamp, identity = base64.urlsafe_b64decode(raw).decode().split("|", 1)
        parsed = datetime.fromisoformat(timestamp)
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed, UUID(identity)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise HTTPException(400, "잘못된 페이지 커서입니다.")


async def _guard(awaitable):
    try:
        return await awaitable
    except repository.ConversationMissing:
        raise HTTPException(404, "대화 기록을 찾을 수 없습니다.")
    except repository.ConversationConflict as error:
        raise HTTPException(409, str(error))


@router.get("/me/conversations", response_model=ConversationPage)
@limiter.limit(RATE_LIMIT_POLL, key_func=user_or_ip)
async def history(request: Request, student_id: str = Depends(student),
                  limit: int = Query(50, ge=1, le=100), cursor: str | None = Query(None, max_length=256)):
    rows = await repository.list_conversations(student_id, limit, _cursor(cursor))
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if more:
        raw = f'{rows[-1]["updated_at"].isoformat()}|{rows[-1]["id"]}'
        next_cursor = base64.urlsafe_b64encode(raw.encode()).decode()
    return {"items": rows, "next_cursor": next_cursor}


@router.post("/me/conversations", response_model=Conversation, status_code=201)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def create(request: Request, body: ConversationCreate, student_id: str = Depends(student)):
    return await _guard(repository.create_conversation(student_id, body))


@router.post("/me/conversations/import", response_model=list[Conversation])
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def import_history(request: Request, body: HistoryImport, student_id: str = Depends(student)):
    return await repository.import_conversations(student_id, body.items)


@router.get("/me/conversations/{identity}", response_model=Conversation)
@limiter.limit(RATE_LIMIT_POLL, key_func=user_or_ip)
async def read(request: Request, identity: UUID, student_id: str = Depends(student)):
    return await _guard(repository.get_conversation(student_id, identity))


@router.put("/me/conversations/{identity}", response_model=Conversation)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def update(request: Request, identity: UUID, body: ConversationUpdate, student_id: str = Depends(student)):
    return await _guard(repository.update_conversation(student_id, identity, body))


@router.delete("/me/conversations/{identity}", status_code=204)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def delete(request: Request, identity: UUID, revision: int = Query(ge=1), student_id: str = Depends(student)):
    await _guard(repository.delete_conversation(student_id, identity, revision))
