"""Portal transport schemas."""

from typing import Optional

from pydantic import BaseModel, Field


class PortalSyncStartRequest(BaseModel):
    student_id: str = Field(min_length=4, max_length=20)
    password: str = Field(min_length=1, max_length=128)


class PortalSyncStartResponse(BaseModel):
    job_id: str


class PortalSyncStatusResponse(BaseModel):
    # status: queued | running | done | failed
    status: str
    # 진행 단계 문구 (예: "시간표 가져오는 중"). 실행 전/후엔 null.
    step: Optional[str] = None
    # done일 때만 — dart PortalSyncResult 키 그대로.
    result: Optional[dict] = None
    # failed일 때 유저용 메시지.
    detail: Optional[str] = None
