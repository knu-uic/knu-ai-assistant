"""Canvas API 기반 KNU LMS 할 일 동기화."""

from __future__ import annotations

import argparse
import json
import os
import requests
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin

from dotenv import load_dotenv
from playwright.sync_api import APIRequestContext, sync_playwright

from db import (
    delete_canvas_lecture_tasks,
    delete_canvas_notice_tasks,
    ensure_users_schema,
    get_user,
    set_favorite_courses,
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
    token = None
    token_path = state_path.parent / "lms_canvas_token.txt"
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
    if not token:
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


def _refresh_learningx_session_with_token(token: str, state_path: Path, lms_url: str) -> bool:
    """Canvas Access Token을 사용해 sessionless_launch API를 쏘고,
    Playwright headless로 해당 URL에 접속하여 LearningX 세션 쿠키(xn_api_token)를 백그라운드 갱신합니다.
    """
    print("[LMS Sync] Canvas 토큰을 사용해 LearningX 세션 쿠키 갱신을 시도합니다...", flush=True)
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
        
        # 1. 수강 중인 임의의 코스 ID 획득
        courses_url = urljoin(lms_url.rstrip("/") + "/", "/api/v1/courses")
        res = requests.get(courses_url, headers=headers, params={"enrollment_state": "active", "per_page": 1}, timeout=10)
        if not res.ok:
            print(f"[LMS Sync] 코스 조회 실패 (Token Invalid 가능성): {res.status_code}", flush=True)
            return False
            
        courses = res.json()
        if not isinstance(courses, list) or not courses:
            print("[LMS Sync] 활성화된 코스가 없어 갱신할 수 없습니다.", flush=True)
            return False
            
        course_id = courses[0]["id"]
        
        # 2. sessionless_launch API 호출
        launch_api_url = urljoin(lms_url.rstrip("/") + "/", f"/api/v1/courses/{course_id}/external_tools/sessionless_launch")
        launch_res = requests.get(
            launch_api_url,
            headers=headers,
            params={"url": urljoin(lms_url.rstrip("/") + "/", "/learningx/login")},
            timeout=10
        )
        if not launch_res.ok:
            print(f"[LMS Sync] sessionless_launch API 실패: {launch_res.status_code}", flush=True)
            return False
            
        launch_url = launch_res.json().get("url")
        if not launch_url:
            print("[LMS Sync] Launch URL을 획득하지 못했습니다.", flush=True)
            return False
            
        # 3. Playwright headless로 Launch URL 접속하여 쿠키 갱신
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context_opts = {}
            if state_path.exists():
                context_opts["storage_state"] = str(state_path)
            context = browser.new_context(**context_opts)
            page = context.new_page()
            
            page.goto(launch_url, wait_until="networkidle", timeout=20000)
            time.sleep(3)  # 쿠키 쓰기 대기
            
            context.storage_state(path=str(state_path))
            browser.close()
            
        print("[LMS Sync] Canvas 토큰 기반 LearningX 세션 쿠키 갱신 완료", flush=True)
        return True
    except Exception as e:
        print(f"[LMS Sync] 토큰 기반 세션 갱신 중 예외 발생: {e}", flush=True)
        return False


def _load_state_cookies(state_path: Path, domain: str) -> dict[str, str]:
    if not state_path.exists():
        return {}

    state = json.loads(state_path.read_text(encoding="utf-8"))
    cookies: dict[str, str] = {}
    for cookie in state.get("cookies", []):
        cookie_domain = (cookie.get("domain") or "").lstrip(".")
        if domain in cookie_domain:
            cookies[cookie["name"]] = cookie.get("value", "")
    return cookies


def _learningx_session(base_url: str, state_path: Path) -> requests.Session | None:
    cookies = _load_state_cookies(state_path, "knulms.kongju.ac.kr")
    token = cookies.get("xn_api_token")
    if not token:
        return None

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Referer": f"{base_url.rstrip('/')}/learningx/lti/modulebuilder",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
        }
    )
    for name, value in cookies.items():
        session.cookies.set(name, value, domain="knulms.kongju.ac.kr")
    return session


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


def _get_learningx_modules(
    session: requests.Session,
    base_url: str,
    course_id: int,
) -> list[dict[str, Any]]:
    url = (
        f"{base_url.rstrip('/')}/learningx/api/v1/courses/"
        f"{course_id}/modules?include_detail=true"
    )
    response = session.get(url, timeout=20)
    if not response.ok:
        body = response.text[:500]
        raise RuntimeError(
            f"LearningX API 요청 실패: GET {url} -> {response.status_code} {body}"
        )

    body = response.json()
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("modules", "data", "items", "result"):
            if isinstance(body.get(key), list):
                return body[key]
    return []


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
    return student_id, profile


def _sync_courses(student_id: str, courses: dict[int, str]) -> int:
    """`_course_map` 결과를 lms_courses 에 upsert. 학생-과목 매핑을 영구화."""
    for course_id, course_name in courses.items():
        upsert_lms_course(student_id, course_id, course_name)
    return len(courses)


def _sync_favorite_courses(request: APIRequestContext, student_id: str) -> None:
    """Canvas 즐겨찾기 과목을 동기화하여 users(favorite_courses) 에 갱신."""
    try:
        fav_courses = _get_json(request, "/api/v1/users/self/favorites/courses")
        if isinstance(fav_courses, list):
            names = []
            for c in fav_courses:
                name = c.get("name") or c.get("course_code")
                if name:
                    names.append(name.strip())
            set_favorite_courses(student_id, sorted(names))
            print(f"[fav sync] 즐겨찾기 과목 {len(names)}개 동기화 완료: {names}")
    except Exception as exc:
        print(f"Canvas 즐겨찾기 과목 동기화 실패: {exc}")


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
        plannable_type = (item.get("plannable_type") or "").lower()
        # 이미 _sync_announcements에서 공식 공지를 중복 없이 더 신뢰성 있게 긁어오므로 스킵
        if "announcement" in plannable_type:
            continue

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
        url = item.get("html_url") or plannable.get("html_url")
        if url and url.startswith("/"):
            url = urljoin(DEFAULT_LMS_URL, url)

        external_id = "planner:" + str(
            item.get("plannable_id")
            or item.get("id")
            or url
            or title
        )

        upsert_lms_task(
            student_id=student_id,
            task_type=_task_type_from_plannable(item),
            title=title,
            course_name=course_name,
            due_date=_parse_canvas_date(due),
            url=url,
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

        url = assignment.get("html_url") or item.get("html_url")
        if url and url.startswith("/"):
            url = urljoin(DEFAULT_LMS_URL, url)

        external_id = "todo:" + str(
            item.get("type")
            or assignment.get("id")
            or url
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
            url=url,
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
    delete_canvas_notice_tasks(student_id)
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
    learningx: requests.Session | None,
    base_url: str,
) -> int:
    """LearningX 기준 미시청 동영상 강의만 1행씩 upsert.

    sync 시작 시 학생의 canvas lecture task 전부 선제 DELETE → 완료된 영상은
    재삽입되지 않으므로 자연스럽게 사라짐. 이전 PR #25 의 `module:*` 행도
    같은 트랜잭션 안에서 정리됨.
    """
    delete_canvas_lecture_tasks(student_id)
    if not courses:
        return 0

    count = 0
    for course_id, course_name in courses.items():
        learningx_success = False
        if learningx is not None:
            try:
                modules = _get_learningx_modules(learningx, base_url, course_id)
                learningx_success = True
            except RuntimeError as exc:
                print(f"LearningX 강의 동기화 실패: course_{course_id} ({exc})", flush=True)
                
                # Canvas 토큰이 있으면 세션 쿠키 백그라운드 갱신 후 1회 재시도
                token_path = Path(DEFAULT_STATE_PATH).parent / "lms_canvas_token.txt"
                if token_path.exists():
                    token_val = token_path.read_text(encoding="utf-8").strip()
                    if token_val:
                        if _refresh_learningx_session_with_token(token_val, Path(DEFAULT_STATE_PATH), base_url):
                            # learningx 세션 객체 쿠키 갱신 및 재생성
                            new_learningx = _learningx_session(base_url, Path(DEFAULT_STATE_PATH))
                            if new_learningx is not None:
                                try:
                                    print(f"LearningX 강의 동기화 재시도 중: course_{course_id}", flush=True)
                                    modules = _get_learningx_modules(new_learningx, base_url, course_id)
                                    learningx_success = True
                                    # 갱신된 세션 정보를 원래 세션 변수에도 덮어씌워 다음 코스 조회 때 사용되도록 함
                                    learningx = new_learningx
                                except RuntimeError as retry_exc:
                                    print(f"LearningX 강의 동기화 재시도 실패: {retry_exc}", flush=True)
                
                if not learningx_success:
                    print(f"LearningX 강의 동기화 최종 실패(Canvas API 폴백 시도): course_{course_id}", flush=True)
                    learningx_success = False
                
            if learningx_success:
                for module in modules:
                    module_name = module.get("title") or ""
                    for item in module.get("module_items") or []:
                        if item.get("content_type") != "attendance_item":
                            continue
                        if item.get("completed") is True:
                            continue
                        if item.get("attendance_status") == "attendance":
                            continue

                        # content_type 이 mp4, movie 가 아닌 것은 스킵 (pdf, file 등 가짜 강의 필터링)
                        content_data = item.get("content_data") or {}
                        item_content_data = content_data.get("item_content_data") or {}
                        file_type = item_content_data.get("content_type")
                        if file_type not in ("mp4", "movie"):
                            continue

                        item_id = item.get("module_item_id")
                        if item_id is None:
                            continue

                        item_title = item.get("title") or "동영상 강의"
                        title = f"{module_name} · {item_title}" if module_name else item_title
                        url = f"{base_url.rstrip('/')}/courses/{course_id}/modules/items/{item_id}"
                        due_date = _parse_canvas_date(
                            item.get("content_data", {}).get("due_at")
                        )

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
                continue

        modules = None
        try:
            modules = _get_json_doseq(
                request,
                f"/api/v1/courses/{course_id}/modules",
                {
                    "include[]": ["items", "content_details"],
                    "student_id": "self",
                    "per_page": 100,
                },
            )
        except RuntimeError as exc:
            print(f"[lecture probe] {course_name!r} student_id=self 실패 → default로 재시도: {exc}")

        # 2차: 기본 호출(권한 401 등으로 1차 실패시).
        if modules is None:
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

        # 진단 로그: item type 분포 + ExternalTool 의 completion_requirement 통계.
        type_count: dict[str, int] = {}
        ext_total = 0
        ext_cr_dict = 0
        ext_cr_completed_true = 0
        for module in modules:
            for item in module.get("items") or []:
                t = item.get("type") or "?"
                type_count[t] = type_count.get(t, 0) + 1
                if t == "ExternalTool":
                    ext_total += 1
                    cr = item.get("completion_requirement")
                    if isinstance(cr, dict):
                        ext_cr_dict += 1
                        if cr.get("completed") is True:
                            ext_cr_completed_true += 1
        print(
            f"[lecture probe] {course_name!r} types={type_count} "
            f"ExternalTool={ext_total} cr_present={ext_cr_dict} "
            f"cr_completed_true={ext_cr_completed_true}"
        )

        for module in modules:
            module_name = module.get("name") or ""
            for item in module.get("items") or []:
                if item.get("type") != "ExternalTool":
                    continue
                cr = item.get("completion_requirement")
                # cr 미설정(None/dict 아님) 또는 이미 completed=True 면 skip.
                # cr 없는 영상은 Canvas로 시청 여부 확인 불가하므로 "남은 수강"에
                # 표시하지 않음 (가짜 남은 수강 방지).
                if not isinstance(cr, dict):
                    continue
                if cr.get("completed") is True:
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
        learningx = _learningx_session(args.url, state_path)
        courses = _course_map(request)
        student_id, profile = _sync_user_profile(request, args.student_id, courses)
        # lms_courses FK(student_id → users) 위반 방지: 기존 user row가 있으면 덮어쓰지 않고, 없을 때만 기본값으로 삽입
        if get_user(student_id) is None:
            upsert_user(
                student_id=student_id,
                name="이름 미설정",
                major="",
                year=None,
            )
        course_count = _sync_courses(student_id, courses)
        _sync_favorite_courses(request, student_id)
        planner_count = _sync_planner_items(request, student_id, courses, args.days)
        todo_count = _sync_todo_items(request, student_id, courses)
        announcement_count = _sync_announcements(
            request,
            student_id,
            courses,
            args.announcement_days,
        )
        lecture_count = _sync_lecture_items(
            request,
            student_id,
            courses,
            learningx,
            args.url,
        )
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
