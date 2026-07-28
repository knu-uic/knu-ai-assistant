from functools import partial
from hashlib import sha256

import anyio
from fastapi import APIRouter, Depends, HTTPException

from api.deps import optional_user, portal_student_id
from api.mappers import notice_from_list_row
from config import HIDDEN_NOTICE_SOURCE_CODES
from db.accounts import get_account
from db.documents import get_documents
from db.lms import get_lms_tasks
from db.users import get_user

router = APIRouter()

NOTICE_CATEGORIES = ["전체", "장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)"]


async def _notice_document() -> dict:
    """Codmes가 네이티브 UI로 렌더링할 KNU Surface 문서.

    HTML이나 JavaScript를 반환하지 않는다. KNU는 데이터와 허용된 action만
    선언하고, 실제 검색창·filter·list row는 각 Codmes client가 렌더링한다.
    """
    rows = await anyio.to_thread.run_sync(
        partial(
            get_documents,
            category=None,
            major=None,
            department="공통",
            limit=100,
            cursor_ts=None,
            cursor_url=None,
            exclude_codes=HIDDEN_NOTICE_SOURCE_CODES,
        )
    )
    notices = [notice_from_list_row(row) for row in rows]
    return {
        "schemaVersion": 1,
        "presentation": "collection",
        "title": "공지사항",
        "subtitle": "최신 학사·일반 공지를 확인하세요.",
        "search": {
            "placeholder": "제목·내용으로 검색",
            "fields": ["title", "body", "subtitle", "tags"],
        },
        "filters": [
            {
                "id": "category",
                "label": "카테고리",
                "style": "chips",
                "options": [
                    {
                        "value": "__all__" if category == "전체" else category,
                        "label": category,
                    }
                    for category in NOTICE_CATEGORIES
                ],
            }
        ],
        "emptyState": {
            "title": "표시할 공지사항이 없어요.",
            "systemImage": "doc.text.magnifyingglass",
        },
        "items": [
            {
                "id": sha256(notice.url.encode()).hexdigest()[:20],
                "title": notice.title,
                "subtitle": " · ".join(
                    value
                    for value in [notice.source_name, notice.posted_at]
                    if value
                ),
                "body": notice.summary or notice.content or "",
                "tags": [*(notice.target or []), *(notice.keywords or [])][:6],
                "filterValues": {
                    "category": notice.category or "일반(기타)",
                },
                "action": {
                    "type": "openURL",
                    "url": notice.url,
                },
            }
            for notice in notices
        ],
    }


async def _student_id(username: str) -> str | None:
    if student_id := portal_student_id(username):
        return student_id
    account = await anyio.to_thread.run_sync(partial(get_account, username))
    return account.get("student_id") if account else None


def _empty_document(title: str, subtitle: str, empty_title: str, icon: str) -> dict:
    return {
        "schemaVersion": 1,
        "presentation": "collection",
        "title": title,
        "subtitle": subtitle,
        "search": None,
        "filters": [],
        "emptyState": {"title": empty_title, "systemImage": icon},
        "items": [],
    }


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "예" if value else "아니요"
    return str(value)


def _table_section(
    section_id: str,
    title: str,
    columns: list,
    rows: list,
    *,
    system_image: str,
    subtitle: str | None = None,
) -> dict:
    width = len(columns)
    return {
        "id": section_id,
        "title": title,
        "subtitle": subtitle,
        "systemImage": system_image,
        "kind": "table",
        "columns": [_text(value) for value in columns],
        "rows": [
            [_text(value) for value in list(row)[:width]]
            + [""] * max(0, width - len(row))
            for row in rows
        ],
    }


def _graduation_rows(value: dict, path: tuple[str, ...] = ()) -> list[list[str]]:
    rows = []
    for key, child in value.items():
        child_path = (*path, str(key))
        if not isinstance(child, dict):
            continue
        if "기준" in child or "취득" in child:
            standard = _text(child.get("기준"))
            taken = _text(child.get("취득"))
            try:
                deficit = max(0, float(standard or 0) - float(taken or 0))
                remaining = str(int(deficit)) if deficit.is_integer() else f"{deficit:g}"
            except (TypeError, ValueError):
                remaining = ""
            rows.append([" › ".join(child_path), standard, taken, remaining or "-"])
        else:
            rows.extend(_graduation_rows(child, child_path))
    return rows


def _grid_sections(prefix: str, title: str, value: dict, icon: str) -> list[dict]:
    sections = []
    summary = value.get("summary") if isinstance(value, dict) else None
    if summary:
        sections.append({
            "id": f"{prefix}-summary",
            "title": f"{title} 요약",
            "subtitle": None,
            "systemImage": icon,
            "kind": "keyValue",
            "fields": [
                {
                    "id": f"{prefix}-summary-{index}",
                    "label": _text(row[0]) if row else "",
                    "value": _text(row[1]) if len(row) > 1 else "",
                }
                for index, row in enumerate(summary)
            ],
        })
    grids = value.get("grids", {}) if isinstance(value, dict) else {}
    for index, (grid_id, grid) in enumerate(grids.items()):
        sections.append(_table_section(
            f"{prefix}-{grid_id}-{index}",
            grid.get("title") or title,
            grid.get("columns") or [],
            grid.get("rows") or [],
            system_image=icon,
        ))
    return sections


async def _lms_document(username: str) -> dict:
    student_id = await _student_id(username)
    document = _empty_document(
        "LMS",
        "과제와 학습 일정을 확인하세요.",
        "연결된 LMS 작업이 없어요.",
        "checklist",
    )
    if not student_id:
        document["subtitle"] = "설정에서 학교 포털과 LMS를 연결해주세요."
        return document
    rows = await anyio.to_thread.run_sync(partial(get_lms_tasks, student_id, True))
    from sync.portal_auth import portal_sync_status
    sync_status = portal_sync_status(student_id)
    if not rows and sync_status["syncing"]:
        document["subtitle"] = sync_status["stage"] or "LMS 데이터를 가져오는 중입니다."
    elif not rows and sync_status["lms_error"]:
        document["subtitle"] = f"LMS 동기화 실패: {sync_status['lms_error']}"
    document["search"] = {
        "placeholder": "과제 검색",
        "fields": ["title", "subtitle", "tags"],
    }
    document["filters"] = [{
        "id": "status",
        "label": "상태",
        "style": "chips",
        "options": [
            {"value": "__all__", "label": "전체"},
            {"value": "pending", "label": "진행 중"},
            {"value": "done", "label": "완료"},
        ],
    }]
    document["items"] = [
        {
            "id": f"lms-task-{row['id']}",
            "title": row.get("title") or "제목 없는 작업",
            "subtitle": " · ".join(
                str(value) for value in [row.get("course_name"), row.get("due_date")] if value
            ),
            "body": None,
            "tags": [row.get("task_type")] if row.get("task_type") else [],
            "filterValues": {"status": "done" if row.get("is_done") else "pending"},
            "action": (
                {"type": "openURL", "url": row["url"]} if row.get("url") else None
            ),
        }
        for row in rows
    ]
    return document


async def _portal_document(username: str) -> dict:
    student_id = await _student_id(username)
    document = {
        "schemaVersion": 1,
        "presentation": "dashboard",
        "title": "포털",
        "subtitle": "통합정보시스템에서 동기화한 시간표·학점·성적 정보입니다.",
        "search": None,
        "filters": [],
        "emptyState": {
            "title": "연결된 포털 정보가 없어요.",
            "systemImage": "person.text.rectangle",
        },
        "items": [],
        "sections": [],
    }
    if not student_id:
        document["subtitle"] = "설정에서 학교 포털을 연결해주세요."
        return document
    user = await anyio.to_thread.run_sync(partial(get_user, student_id)) or {}
    profile_values = [
        ("학번", student_id),
        ("이름", user.get("name")),
        ("학과", user.get("major")),
        ("학년", f"{user['year']}학년" if user.get("year") else None),
    ]
    document["sections"].append({
        "id": "profile",
        "title": "학적 정보",
        "subtitle": None,
        "systemImage": "person.text.rectangle",
        "kind": "keyValue",
        "fields": [
            {
                "id": f"profile-{index}",
                "label": label,
                "value": _text(value),
            }
            for index, (label, value) in enumerate(profile_values)
            if value
        ],
    })

    timetable = user.get("timetable") or []
    if timetable and timetable[0].get("rows"):
        timetable_rows = timetable[0]["rows"]
        columns = timetable_rows[0]
        active_rows = [
            row for row in timetable_rows[1:]
            if any(_text(cell).strip() for cell in row[1:])
        ]
        document["sections"].append(_table_section(
            "timetable",
            "주간 시간표",
            columns,
            active_rows,
            system_image="calendar",
            subtitle="수업이 있는 교시만 표시합니다.",
        ))

    graduation = user.get("graduation_credits")
    if graduation:
        document["sections"].append(_table_section(
            "graduation",
            "취득학점 현황",
            ["영역", "기준", "취득", "부족"],
            _graduation_rows(graduation),
            system_image="graduationcap",
        ))

    grade_distribution = user.get("grade_distribution")
    if grade_distribution:
        document["sections"].extend(_grid_sections(
            "grade-distribution",
            "나의 성적분포",
            grade_distribution,
            "chart.bar",
        ))

    cumulative_grades = user.get("cumulative_grades")
    if cumulative_grades:
        document["sections"].extend(_grid_sections(
            "cumulative-grades",
            "누적 성적",
            cumulative_grades,
            "book.closed",
        ))

    has_synced_data = any([
        timetable,
        graduation,
        grade_distribution,
        cumulative_grades,
    ])
    if not has_synced_data:
        document["subtitle"] = "포털 데이터를 가져오는 중입니다. 잠시 후 당겨서 새로고침해주세요."
    return document


async def _settings_document(username: str) -> dict:
    student_id = await _student_id(username)
    account_label = student_id or username
    document = _empty_document(
        "KNU 설정",
        f"{account_label} 학번으로 포털에 연결했습니다.",
        "설정할 항목이 없어요.",
        "gearshape",
    )
    document["items"] = [
        {
            "id": "account",
            "title": "공주대 포털 계정",
            "subtitle": account_label,
            "body": "포털 인증 토큰은 Codmes 서버에만 저장되며 비밀번호는 저장하지 않습니다.",
            "tags": ["로그인됨"],
            "filterValues": {},
            "action": None,
        },
        {
            "id": "student",
            "title": "학교 서비스",
            "subtitle": student_id or "연결되지 않음",
            "body": "검증된 학번으로 포털 및 LMS 데이터를 사용합니다.",
            "tags": ["연결됨" if student_id else "미연결"],
            "filterValues": {},
            "action": None,
        },
    ]
    return document


@router.get("/codmes/surface")
@router.get("/codmes/surface/notices")
async def codmes_surface() -> dict:
    """Public notice route kept as the default declarative Surface document."""
    return await _notice_document()


@router.get("/codmes/surface/{route_id}")
async def codmes_surface_route(
    route_id: str,
    username: str | None = Depends(optional_user),
) -> dict:
    if route_id == "notices":
        return await _notice_document()
    if not username:
        raise HTTPException(status_code=401, detail="KNU 로그인이 필요합니다.")
    if route_id == "lms":
        return await _lms_document(username)
    if route_id == "portal":
        return await _portal_document(username)
    if route_id == "settings":
        return await _settings_document(username)
    raise HTTPException(status_code=404, detail="존재하지 않는 KNU 섹션입니다.")
