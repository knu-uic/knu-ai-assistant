"""로그인 본인 데이터 읽기 (/api/me/*).

모든 엔드포인트는 JWT 유저 → accounts.student_id로만 조회한다.
경로에 학번을 받지 않으므로 타인 데이터 접근이 구조적으로 불가능(IDOR 차단).
"""
from functools import partial

import anyio
from fastapi import APIRouter, Depends, Request

from api.deps import require_user
from api.ratelimit import limiter, user_or_ip
from api.schemas.me import (
    InterestsRequest,
    LmsCoursesResponse,
    LmsTasksResponse,
    MeProfile,
    PortalDataResponse,
    TimetableResponse,
)
from config import RATE_LIMIT_READ
from db.accounts import get_account
from db.lms import get_lms_courses, get_lms_tasks
from db.users import get_user, set_interests

router = APIRouter()


async def _linked_student_id(username: str) -> str | None:
    account = await anyio.to_thread.run_sync(partial(get_account, username))
    return account.get("student_id") if account else None


def _iso(d) -> str | None:
    return d.isoformat() if d is not None and hasattr(d, "isoformat") else d


@router.get("/me", response_model=MeProfile)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def me(request: Request, username: str = Depends(require_user)) -> MeProfile:
    student_id = await _linked_student_id(username)
    if not student_id:
        # 포털 미연결 — 빈 프로필 (앱은 "포털 연결" 유도)
        return MeProfile()
    user = await anyio.to_thread.run_sync(partial(get_user, student_id))
    if not user:
        return MeProfile(student_id=student_id, portal_linked=True)
    courses = await anyio.to_thread.run_sync(partial(get_lms_courses, student_id))
    return MeProfile(
        student_id=student_id,
        name=user.get("name"),
        major=user.get("major"),
        year=user.get("year"),
        interests=user.get("interests", []),
        portal_linked=bool(user.get("timetable") or user.get("grade_distribution")),
        lms_linked=len(courses) > 0,
    )


@router.post("/me/interests", response_model=MeProfile)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def update_interests(
    request: Request,
    body: InterestsRequest,
    username: str = Depends(require_user),
) -> MeProfile:
    student_id = await _linked_student_id(username)
    if not student_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="포털을 먼저 연결해주세요.")
    await anyio.to_thread.run_sync(partial(set_interests, student_id, body.interests))
    return await me(request, username)


@router.get("/me/timetable", response_model=TimetableResponse)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def me_timetable(request: Request, username: str = Depends(require_user)) -> TimetableResponse:
    student_id = await _linked_student_id(username)
    if not student_id:
        return TimetableResponse()
    user = await anyio.to_thread.run_sync(partial(get_user, student_id))
    return TimetableResponse(timetable=(user or {}).get("timetable"))


@router.get("/me/portal", response_model=PortalDataResponse)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def me_portal(request: Request, username: str = Depends(require_user)) -> PortalDataResponse:
    student_id = await _linked_student_id(username)
    if not student_id:
        return PortalDataResponse()
    user = await anyio.to_thread.run_sync(partial(get_user, student_id)) or {}
    return PortalDataResponse(
        grade_distribution=user.get("grade_distribution"),
        cumulative_grades=user.get("cumulative_grades"),
        graduation_credits=user.get("graduation_credits"),
    )


@router.get("/me/lms/tasks", response_model=LmsTasksResponse)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def me_lms_tasks(request: Request, username: str = Depends(require_user)) -> LmsTasksResponse:
    student_id = await _linked_student_id(username)
    if not student_id:
        return LmsTasksResponse()
    rows = await anyio.to_thread.run_sync(partial(get_lms_tasks, student_id))
    for r in rows:
        r["due_date"] = _iso(r.get("due_date"))
    return LmsTasksResponse(tasks=rows)


@router.get("/me/lms/courses", response_model=LmsCoursesResponse)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def me_lms_courses(request: Request, username: str = Depends(require_user)) -> LmsCoursesResponse:
    student_id = await _linked_student_id(username)
    if not student_id:
        return LmsCoursesResponse()
    rows = await anyio.to_thread.run_sync(partial(get_lms_courses, student_id))
    return LmsCoursesResponse(courses=rows)
