"""로그인 본인 데이터 읽기 (/api/me/*).

모든 엔드포인트는 JWT 유저 → accounts.student_id로만 조회한다.
경로에 학번을 받지 않으므로 타인 데이터 접근이 구조적으로 불가능(IDOR 차단).
"""
from functools import partial

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import portal_student_id, require_user
from api.ratelimit import limiter, user_or_ip
from api.recommend import build_home
from api.schemas.me import (
    FavoritesRequest,
    HomeResponse,
    InterestsRequest,
    LmsCoursesResponse,
    LmsTasksResponse,
    MeProfile,
    PortalDataResponse,
    TaskDoneRequest,
    TimetableResponse,
)
from config import HIDDEN_NOTICE_SOURCE_CODES, RATE_LIMIT_READ
from db.accounts import get_account
from db.documents import get_documents
from db.lms import delete_lms_task, get_lms_courses, get_lms_tasks, set_lms_task_done
from db.users import get_user, set_favorite_courses, set_interests

router = APIRouter()


async def _linked_student_id(username: str) -> str | None:
    if student_id := portal_student_id(username):
        return student_id
    account = await anyio.to_thread.run_sync(partial(get_account, username))
    return account.get("student_id") if account else None


def _iso(d) -> str | None:
    return d.isoformat() if d is not None and hasattr(d, "isoformat") else d


@router.get("/me", response_model=MeProfile)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def me(request: Request, username: str = Depends(require_user)) -> MeProfile:
    from sync.portal_auth import portal_sync_status

    student_id = await _linked_student_id(username)
    if not student_id:
        # 포털 미연결 — 빈 프로필 (앱은 "포털 연결" 유도)
        return MeProfile()
    user = await anyio.to_thread.run_sync(partial(get_user, student_id))
    if not user:
        sync_status = portal_sync_status(student_id)
        return MeProfile(
            student_id=student_id,
            portal_linked=True,
            portal_syncing=sync_status["syncing"],
            sync_stage=sync_status["stage"],
            lms_sync_error=sync_status["lms_error"],
        )
    sync_status = portal_sync_status(student_id)
    courses = await anyio.to_thread.run_sync(partial(get_lms_courses, student_id))
    return MeProfile(
        student_id=student_id,
        name=user.get("name"),
        major=user.get("major"),
        year=user.get("year"),
        interests=user.get("interests", []),
        favorite_courses=user.get("favorite_courses", []),
        portal_linked=bool(user.get("timetable") or user.get("grade_distribution")),
        portal_syncing=sync_status["syncing"],
        sync_stage=sync_status["stage"],
        lms_sync_error=sync_status["lms_error"],
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
        raise HTTPException(status_code=400, detail="포털을 먼저 연결해주세요.")
    await anyio.to_thread.run_sync(partial(set_interests, student_id, body.interests))
    return await me(request, username)


@router.post("/me/lms/favorites", response_model=MeProfile)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def update_favorites(
    request: Request,
    body: FavoritesRequest,
    username: str = Depends(require_user),
) -> MeProfile:
    student_id = await _linked_student_id(username)
    if not student_id:
        raise HTTPException(status_code=400, detail="포털을 먼저 연결해주세요.")
    await anyio.to_thread.run_sync(partial(set_favorite_courses, student_id, body.favorite_courses))
    return await me(request, username)


@router.post("/me/lms/tasks/{task_id}/done", status_code=204)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def mark_task_done(
    request: Request,
    task_id: int,
    body: TaskDoneRequest,
    username: str = Depends(require_user),
) -> None:
    student_id = await _linked_student_id(username)
    if not student_id:
        raise HTTPException(status_code=400, detail="포털을 먼저 연결해주세요.")
    # set_lms_task_done은 student_id로 소유권을 확인하므로 타인 task는 영향 없음
    await anyio.to_thread.run_sync(partial(set_lms_task_done, task_id, student_id, body.is_done))


@router.delete("/me/lms/tasks/{task_id}", status_code=204)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def remove_task(
    request: Request,
    task_id: int,
    username: str = Depends(require_user),
) -> None:
    student_id = await _linked_student_id(username)
    if not student_id:
        raise HTTPException(status_code=400, detail="포털을 먼저 연결해주세요.")
    await anyio.to_thread.run_sync(partial(delete_lms_task, task_id, student_id))


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
    # 완료분 포함 — 프론트의 "완료된 작업 표시" 토글이 필터한다
    rows = await anyio.to_thread.run_sync(partial(get_lms_tasks, student_id, True))
    for r in rows:
        r["due_date"] = _iso(r.get("due_date"))
    return LmsTasksResponse(tasks=rows)


@router.get("/me/home", response_model=HomeResponse)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def me_home(request: Request, username: str = Depends(require_user)) -> HomeResponse:
    # 비연동 유저는 관심사·학과 없음 → 마감·전체 기반으로 degrade (빈 화면 방지)
    student_id = await _linked_student_id(username)
    interests: list[str] = []
    major = year = None
    if student_id:
        user = await anyio.to_thread.run_sync(partial(get_user, student_id)) or {}
        interests = user.get("interests") or []
        major = user.get("major")
        year = user.get("year")
    rows = await anyio.to_thread.run_sync(
        partial(
            get_documents,
            major=major if major else None,
            limit=60,
            exclude_codes=HIDDEN_NOTICE_SOURCE_CODES,
        )
    )
    data = await anyio.to_thread.run_sync(
        partial(build_home, rows, interests, major, year)
    )
    return HomeResponse(**data)


@router.get("/me/lms/courses", response_model=LmsCoursesResponse)
@limiter.limit(RATE_LIMIT_READ, key_func=user_or_ip)
async def me_lms_courses(request: Request, username: str = Depends(require_user)) -> LmsCoursesResponse:
    student_id = await _linked_student_id(username)
    if not student_id:
        return LmsCoursesResponse()
    rows = await anyio.to_thread.run_sync(partial(get_lms_courses, student_id))
    return LmsCoursesResponse(courses=rows)
