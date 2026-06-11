from arq.jobs import Job, JobStatus
from fastapi import APIRouter, Depends, HTTPException, Request

from api.crypto import encrypt_secret
from api.deps import require_user
from api.jobs import get_arq_pool
from api.ratelimit import limiter, user_or_ip
from api.schemas.portal import (
    PortalSyncStartRequest,
    PortalSyncStartResponse,
    PortalSyncStatusResponse,
)
from config import RATE_LIMIT_AUTH, RATE_LIMIT_POLL
from workers.arq_worker import step_key

router = APIRouter()


def _user_job_id(username: str) -> str:
    # 유저당 잡 1개(결정적 id) — 연타해도 같은 잡을 바라본다.
    # job_id가 추측 가능해도 status 조회는 JWT 유저 본인 잡만 허용되므로 안전.
    return f"portal-sync:{username}"


@router.post("/portal/sync/start", response_model=PortalSyncStartResponse, status_code=202)
@limiter.limit(RATE_LIMIT_AUTH, key_func=user_or_ip)
async def portal_sync_start(
    request: Request,
    req: PortalSyncStartRequest,
    username: str = Depends(require_user),
) -> PortalSyncStartResponse:
    pool = await get_arq_pool()
    job_id = _user_job_id(username)

    # dedup은 "진행 중"일 때만 — 완료된 이전 잡 결과가 남아 있으면 지우고 새로 실행한다.
    # (안 지우면 직전 동기화 결과가 keep_result 창 동안 재시도를 막는다. LMS와 동일 패턴)
    status = await Job(job_id, redis=pool).status()
    if status in (JobStatus.queued, JobStatus.deferred, JobStatus.in_progress):
        return PortalSyncStartResponse(job_id=job_id)
    await pool.delete(f"arq:result:{job_id}")

    # 비밀번호는 암호문으로만 잡 페이로드에 실린다 (저장·로그 없음).
    await pool.enqueue_job(
        "portal_sync",
        username,
        req.student_id,
        encrypt_secret(req.password),
        _job_id=job_id,
    )
    return PortalSyncStartResponse(job_id=job_id)


@router.get("/portal/sync/{job_id}", response_model=PortalSyncStatusResponse)
@limiter.limit(RATE_LIMIT_POLL, key_func=user_or_ip)
async def portal_sync_status(
    request: Request,
    job_id: str,
    username: str = Depends(require_user),
) -> PortalSyncStatusResponse:
    if job_id != _user_job_id(username):
        # 타인 잡 조회 차단 — 존재 여부도 노출하지 않음
        raise HTTPException(status_code=404, detail="진행 중인 동기화가 없습니다.")

    pool = await get_arq_pool()
    job = Job(job_id, redis=pool)
    status = await job.status()

    if status == JobStatus.not_found:
        raise HTTPException(status_code=404, detail="진행 중인 동기화가 없습니다.")
    if status in (JobStatus.deferred, JobStatus.queued):
        return PortalSyncStatusResponse(status="queued")
    if status == JobStatus.in_progress:
        raw_step = await pool.get(step_key(job_id))
        step = raw_step.decode() if isinstance(raw_step, bytes) else raw_step
        return PortalSyncStatusResponse(status="running", step=step)

    info = await job.result_info()
    if info is None or not info.success:
        # 잡 자체가 죽은 경우(타임아웃 등). 포털 로그인 실패는 result dict로 옴.
        return PortalSyncStatusResponse(
            status="failed",
            detail="동기화에 실패했습니다. 잠시 후 다시 시도해주세요.",
        )
    return PortalSyncStatusResponse(status="done", result=info.result)
