"""Canvas API 기반 KNU LMS 할 일 동기화."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin

from dotenv import load_dotenv
from playwright.sync_api import APIRequestContext, sync_playwright

from db import (
    delete_canvas_lecture_tasks,
    ensure_users_schema,
    get_user,
    upsert_lms_course,
    upsert_lms_task,
    upsert_user,
)
from ui import DEFAULT_STUDENT_ID, MAJORS

DEFAULT_LMS_URL = "https://knulms.kongju.ac.kr"
DEFAULT_STATE_PATH = ".secrets/lms_storage_state.json"
DEFAULT_CURRENT_USER_PATH = ".secrets/lms_current_user.json"


def _parse_canvas_date(value: str | None) -> date | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def _request_context(playwright, base_url: str, state_path: Path) -> APIRequestContext:
    token = os.getenv("CANVAS_ACCESS_TOKEN") or os.getenv("KNU_LMS_TOKEN")
    headers = {"Accept": "application/json"}
    storage_state = str(state_path) if state_path.exists() else None

    if token:
        headers["Authorization"] = f"Bearer {token}"

    return playwright.request.new_context(
        base_url=base_url.rstrip("/"),
        extra_http_headers=headers,
        storage_state=storage_state,
    )


def _get_json(
    request: APIRequestContext,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    response = request.get(path, params=params or {})
    if not response.ok:
        body = response.text()[:500]
        raise RuntimeError(f"Canvas API 요청 실패: GET {path} -> {response.status} {body}")
    return response.json()


def _get_json_doseq(
    request: APIRequestContext,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    """리스트 파라미터를 Canvas가 기대하는 반복 쿼리 형식으로 보낸다."""
    query = urlencode(params or {}, doseq=True)
    target = f"{path}?{query}" if query else path
    response = request.get(target)
    if not response.ok:
        body = response.text()[:500]
        raise RuntimeError(f"Canvas API 요청 실패: GET {path} -> {response.status} {body}")
    return response.json()


def _course_map(request: APIRequestContext) -> dict[int, str]:
    courses = _get_json(
        request,
        "/api/v1/courses",
        {
            "enrollment_state": "active",
            "per_page": 100,
            "include[]": "term",
        },
    )
    if not isinstance(courses, list):
        return {}
    return {
        int(course["id"]): course.get("name") or course.get("course_code") or f"course_{course['id']}"
        for course in courses
        if course.get("id") is not None
    }


def _extract_student_id(profile: dict[str, Any], fallback: str) -> str:
    for key in ("login_id", "sis_user_id", "integration_id"):
        value = str(profile.get(key) or "").strip()
        if value:
            return value
    return fallback


def _extract_name(profile: dict[str, Any]) -> str | None:
    for key in ("name", "short_name", "sortable_name"):
        value = str(profile.get(key) or "").strip()
        if value:
            return value
    return None


def _infer_major(profile: dict[str, Any], courses: dict[int, str]) -> str | None:
    haystack = " ".join(
        str(value)
        for value in list(profile.values()) + list(courses.values())
        if value is not None
    )
    for major in MAJORS:
        if major != "전체" and major in haystack:
            return major
    return None


def _infer_year(student_id: str) -> int | None:
    if len(student_id) < 4 or not student_id[:4].isdigit():
        return None

    admission_year = int(student_id[:4])
    current_year = date.today().year
    if admission_year < 2000 or admission_year > current_year:
        return None

    return max(1, min(6, current_year - admission_year + 1))


def _sync_user_profile(
    request: APIRequestContext,
    fallback_student_id: str,
    courses: dict[int, str],
) -> tuple[str, dict[str, Any]]:
    profile = _get_json(request, "/api/v1/users/self/profile")
    if not isinstance(profile, dict):
        profile = {}

    student_id = _extract_student_id(profile, fallback_student_id)
    existing = get_user(student_id) or get_user(fallback_student_id) or {}
    name = _extract_name(profile) or existing.get("name") or "이름 미설정"
    major = _infer_major(profile, courses) or existing.get("major") or "컴퓨터공학과"
    year = _infer_year(student_id) or existing.get("year") or 1
    interests = existing.get("interests") or []
    favorite_courses = existing.get("favorite_courses") or []

    upsert_user(
        student_id=student_id,
        name=name,
        major=major,
        year=year,
        interests=interests,
        favorite_courses=favorite_courses,
    )
    return student_id, profile


def _sync_courses(student_id: str, courses: dict[int, str]) -> int:
    """`_course_map` 결과를 lms_courses 에 upsert. 학생-과목 매핑을 영구화."""
    for course_id, course_name in courses.items():
        upsert_lms_course(student_id, course_id, course_name)
    return len(courses)


def _is_done_from_planner(item: dict[str, Any]) -> bool:
    override = item.get("planner_override") or {}
    submissions = item.get("submissions") or {}
    return bool(
        override.get("marked_complete")
        or submissions.get("submitted")
        or submissions.get("excused")
    )


def _task_type_from_plannable(item: dict[str, Any]) -> str:
    plannable_type = (item.get("plannable_type") or "").lower()
    if "announcement" in plannable_type or "discussion" in plannable_type:
        return "notice"
    return "assignment"


def _sync_planner_items(
    request: APIRequestContext,
    student_id: str,
    courses: dict[int, str],
    days: int,
) -> int:
    start = datetime.now(timezone.utc) - timedelta(days=7)
    end = datetime.now(timezone.utc) + timedelta(days=days)
    items = _get_json(
        request,
        "/api/v1/planner/items",
        {
            "start_date": start.isoformat().replace("+00:00", "Z"),
            "end_date": end.isoformat().replace("+00:00", "Z"),
            "per_page": 100,
        },
    )
    if not isinstance(items, list):
        return 0

    count = 0
    for item in items:
        plannable = item.get("plannable") or {}
        title = (
            item.get("title")
            or plannable.get("title")
            or plannable.get("name")
            or "LMS 항목"
        )
        course_id = item.get("course_id") or plannable.get("course_id")
        course_name = item.get("context_name")
        if not course_name and course_id is not None:
            course_name = courses.get(int(course_id))

        due = (
            plannable.get("due_at")
            or item.get("plannable_date")
            or item.get("todo_date")
        )
        external_id = "planner:" + str(
            item.get("plannable_id")
            or item.get("id")
            or item.get("html_url")
            or title
        )

        upsert_lms_task(
            student_id=student_id,
            task_type=_task_type_from_plannable(item),
            title=title,
            course_name=course_name,
            due_date=_parse_canvas_date(due),
            url=item.get("html_url") or plannable.get("html_url"),
            is_done=_is_done_from_planner(item),
            source="canvas",
            external_id=external_id,
            raw=item,
        )
        count += 1
    return count


def _sync_todo_items(
    request: APIRequestContext,
    student_id: str,
    courses: dict[int, str],
) -> int:
    items = _get_json(request, "/api/v1/users/self/todo", {"per_page": 100})
    if not isinstance(items, list):
        return 0

    count = 0
    for item in items:
        assignment = item.get("assignment") or {}
        course = item.get("course") or {}
        title = assignment.get("name") or item.get("title") or "LMS 할 일"
        course_id = course.get("id") or assignment.get("course_id")
        course_name = course.get("name")
        if not course_name and course_id is not None:
            course_name = courses.get(int(course_id))

        external_id = "todo:" + str(
            item.get("type")
            or assignment.get("id")
            or item.get("html_url")
            or title
        )
        if assignment.get("id") is not None:
            external_id += f":{assignment['id']}"

        upsert_lms_task(
            student_id=student_id,
            task_type="assignment",
            title=title,
            course_name=course_name,
            due_date=_parse_canvas_date(assignment.get("due_at")),
            url=assignment.get("html_url") or item.get("html_url"),
            is_done=False,
            source="canvas",
            external_id=external_id,
            raw=item,
        )
        count += 1
    return count


def _sync_announcements(
    request: APIRequestContext,
    student_id: str,
    courses: dict[int, str],
    days: int,
) -> int:
    if not courses:
        return 0

    start = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    count = 0
    for course_id, fallback_course_name in courses.items():
        try:
            items = _get_json_doseq(
                request,
                "/api/v1/announcements",
                {
                    "context_codes[]": [f"course_{course_id}"],
                    "start_date": start,
                    "per_page": 100,
                },
            )
        except RuntimeError as exc:
            print(f"공지 동기화 건너뜀: course_{course_id} ({exc})")
            continue

        if not isinstance(items, list):
            continue

        for item in items:
            context_course_id = item.get("context_code", "").replace("course_", "")
            course_name = (
                courses.get(int(context_course_id))
                if context_course_id.isdigit()
                else fallback_course_name
            )
            title = item.get("title") or "LMS 공지"
            url = item.get("html_url")
            if url and url.startswith("/"):
                url = urljoin(DEFAULT_LMS_URL, url)

            upsert_lms_task(
                student_id=student_id,
                task_type="notice",
                title=title,
                course_name=course_name,
                due_date=_parse_canvas_date(item.get("posted_at")),
                url=url,
                is_done=False,
                source="canvas",
                external_id="announcement:" + str(item.get("id") or url or title),
                raw=item,
            )
            count += 1
    return count


def _sync_lecture_items(
    request: APIRequestContext,
    student_id: str,
    courses: dict[int, str],
) -> int:
    """미완료 동영상 강의(ExternalTool item) 만 1행씩 upsert.

    sync 시작 시 학생의 canvas lecture task 전부 선제 DELETE → 완료된 영상은
    재삽입되지 않으므로 자연스럽게 사라짐. 이전 PR #25 의 `module:*` 행도
    같은 트랜잭션 안에서 정리됨.
    """
    delete_canvas_lecture_tasks(student_id)
    if not courses:
        return 0

    count = 0
    for course_id, course_name in courses.items():
        try:
            modules = _get_json_doseq(
                request,
                f"/api/v1/courses/{course_id}/modules",
                {
                    "include[]": ["items", "content_details"],
                    "per_page": 100,
                },
            )
        except RuntimeError as exc:
            print(f"강의 동기화 건너뜀: course_{course_id} ({exc})")
            continue

        if not isinstance(modules, list):
            continue

        for module in modules:
            # KNU LMS는 ExternalTool item에 completion_requirement를 안 박고
            # module-level state로만 사용자별 완료/출석을 반영한다 (probe 결과).
            if module.get("state") == "completed":
                continue
            module_name = module.get("name") or ""
            for item in module.get("items") or []:
                if item.get("type") != "ExternalTool":
                    continue
                if (item.get("completion_requirement") or {}).get("completed"):
                    continue
                item_id = item.get("id")
                if item_id is None:
                    continue

                item_title = item.get("title") or item.get("name") or "강의 영상"
                title = f"{module_name} · {item_title}" if module_name else item_title
                due_date = _parse_canvas_date(
                    (item.get("content_details") or {}).get("due_at")
                )
                url = item.get("html_url") or f"{DEFAULT_LMS_URL}/courses/{course_id}/modules"

                upsert_lms_task(
                    student_id=student_id,
                    task_type="lecture",
                    title=title,
                    course_name=course_name,
                    due_date=due_date,
                    progress=None,
                    url=url,
                    is_done=False,
                    source="canvas",
                    external_id=f"lecture_item:{course_id}:{item_id}",
                    raw=item,
                )
                count += 1
    return count


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Canvas API 기반 LMS 할 일 동기화")
    parser.add_argument("--student-id", default=DEFAULT_STUDENT_ID)
    parser.add_argument("--url", default=os.getenv("KNU_LMS_URL", DEFAULT_LMS_URL))
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    parser.add_argument("--current-user-file", default=DEFAULT_CURRENT_USER_PATH)
    parser.add_argument("--days", type=int, default=45, help="앞으로 동기화할 일수")
    parser.add_argument("--announcement-days", type=int, default=14, help="최근 공지 조회 일수")
    args = parser.parse_args()

    state_path = Path(args.state)
    if not state_path.exists() and not (os.getenv("CANVAS_ACCESS_TOKEN") or os.getenv("KNU_LMS_TOKEN")):
        raise SystemExit(
            "저장된 LMS 세션이나 Canvas 토큰이 없습니다. "
            "먼저 `python3 lms_login.py`로 로그인하거나 CANVAS_ACCESS_TOKEN을 설정하세요."
        )

    ensure_users_schema()
    with sync_playwright() as p:
        request = _request_context(p, args.url, state_path)
        courses = _course_map(request)
        student_id, profile = _sync_user_profile(request, args.student_id, courses)
        course_count = _sync_courses(student_id, courses)
        planner_count = _sync_planner_items(request, student_id, courses, args.days)
        todo_count = _sync_todo_items(request, student_id, courses)
        announcement_count = _sync_announcements(
            request,
            student_id,
            courses,
            args.announcement_days,
        )
        lecture_count = _sync_lecture_items(request, student_id, courses)
        request.dispose()

    current_user_path = Path(args.current_user_file)
    current_user_path.parent.mkdir(parents=True, exist_ok=True)
    current_user_path.write_text(
        json.dumps(
            {
                "student_id": student_id,
                "name": profile.get("name"),
                "login_id": profile.get("login_id"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "LMS 동기화 완료: "
        f"{profile.get('name') or student_id} · "
        f"과목 {course_count}개, planner {planner_count}건, todo {todo_count}건, "
        f"공지 {announcement_count}건, 남은 강의 {lecture_count}건"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
