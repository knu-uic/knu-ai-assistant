"""LMS transport schemas."""

from typing import Optional

from pydantic import BaseModel, Field


class LmsSyncStartRequest(BaseModel):
    student_id: str = Field(min_length=4, max_length=20)
    # 비밀번호는 선택 — 저장된 세션이 살아있으면 없이도 동기화된다.
    password: Optional[str] = Field(default=None, max_length=128)


class LmsSyncStartResponse(BaseModel):
    job_id: str


class LmsSyncStatusResponse(BaseModel):
    # status: queued | running | done | failed
    status: str
    step: Optional[str] = None
    result: Optional[dict] = None
    detail: Optional[str] = None
    # 세션 만료/없음 → 앱이 비밀번호 재제출해야 함
    needs_reconnect: bool = False
