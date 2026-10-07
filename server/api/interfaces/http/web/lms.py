"""Standalone React web LMS synchronization endpoints."""

from arq.jobs import Job, JobStatus
from fastapi import APIRouter, Depends, HTTPException, Request

from api.crypto import encrypt_secret
from api.deps import require_user
from api.jobs import get_arq_pool
from api.ratelimit import limiter, user_or_ip
from interfaces.http.schemas.lms import (
    LmsSyncStartRequest,
    LmsSyncStartResponse,
    LmsSyncStatusResponse,
)
from config import RATE_LIMIT_AUTH, RATE_LIMIT_POLL
from workers.arq_worker import step_key

router = APIRouter()


def _user_job_id(username: str) -> str:
    return f"lms-sync:{username}"


@router.post("/lms/sync/start", response_model=LmsSyncStartResponse, status_code=202)
@limiter.limit(RATE_LIMIT_AUTH, key_func=user_or_ip)
async def lms_sync_start(
    request: Request,
    req: LmsSyncStartRequest,
    username: str = Depends(require_user),
) -> LmsSyncStartResponse:
    pool = await get_arq_pool()
    job_id = _user_job_id(username)

    # dedup은 "진행 중"일 때만 — 완료된 이전 잡 결과가 남아 있으면 지우고 새로 실행한다.
    # (안 지우면 needs_reconnect 직후 비번 재제출이 stale 결과로 dedup돼 무한 반복)
    status = await Job(job_id, redis=pool).status()
    if status in (JobStatus.queued, JobStatus.deferred, JobStatus.in_progress):
        return LmsSyncStartResponse(job_id=job_id)
    await pool.delete(f"arq:result:{job_id}")

    # 비밀번호가 있으면 암호문으로만 전달, 없으면 None(세션 재사용 경로).
    enc_password = encrypt_secret(req.password) if req.password else None
    await pool.enqueue_job(
        "lms_sync", username, req.student_id, enc_password, _job_id=job_id
    )
    return LmsSyncStartResponse(job_id=job_id)


@router.get("/lms/sync/{job_id}", response_model=LmsSyncStatusResponse)
@limiter.limit(RATE_LIMIT_POLL, key_func=user_or_ip)
async def lms_sync_status(
    request: Request,
    job_id: str,
    username: str = Depends(require_user),
) -> LmsSyncStatusResponse:
    if job_id != _user_job_id(username):
        raise HTTPException(status_code=404, detail="진행 중인 동기화가 없습니다.")

    pool = await get_arq_pool()
    job = Job(job_id, redis=pool)
    status = await job.status()

    if status == JobStatus.not_found:
        raise HTTPException(status_code=404, detail="진행 중인 동기화가 없습니다.")
    if status in (JobStatus.deferred, JobStatus.queued):
        return LmsSyncStatusResponse(status="queued")
    if status == JobStatus.in_progress:
        raw_step = await pool.get(step_key(job_id))
        step = raw_step.decode() if isinstance(raw_step, bytes) else raw_step
        return LmsSyncStatusResponse(status="running", step=step)

    info = await job.result_info()
    if info is None or not info.success:
        return LmsSyncStatusResponse(
            status="failed",
            detail="동기화에 실패했습니다. 잠시 후 다시 시도해주세요.",
        )
    result = info.result
    # 세션 만료/없음 → done이지만 재연결 플래그를 올려 앱이 비밀번호 재제출하게 함
    if isinstance(result, dict) and result.get("needs_reconnect"):
        return LmsSyncStatusResponse(
            status="failed",
            needs_reconnect=True,
            detail=result.get("message", "포털 재연결이 필요합니다."),
        )
    return LmsSyncStatusResponse(status="done", result=result)
