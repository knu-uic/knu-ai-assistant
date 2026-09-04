"""KNU notice evidence tools exposed through the MCP interface."""

import secrets
from contextvars import ContextVar
from hashlib import sha256
from datetime import date, datetime
from math import isfinite
from typing import Annotated, Any, Literal

import anyio
from fastapi import HTTPException
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult
from pydantic import BeforeValidator, Field
from starlette.middleware import Middleware
from starlette.responses import JSONResponse

from api.deps import decode_access_token, portal_student_id
from api.ratelimit import allow_rate_limited_request
from config import MCP_AUTH_TOKEN, RATE_LIMIT_MCP
from db.accounts import get_account
from db.documents import get_document_content, list_notices_for_scan
from db.lms import get_lms_courses, get_lms_tasks
from db.users import get_user
from retrieval.graph import retrieve_mcp_evidence


_DETAIL_CONTENT_LIMIT = 12000
_EVIDENCE_TEXT_LIMIT = 6000
_MCP_PRINCIPAL: ContextVar[str | None] = ContextVar(
    "knu_mcp_principal",
    default=None,
)
_SCHOOL_DEPARTMENT_ALIASES = frozenset(
    {
        "knu",
        "kongju national university",
        "공주대",
        "공주대학교",
        "국립공주대",
        "국립공주대학교",
    }
)


def _normalize_department_input(value: Any) -> Any:
    """Treat school-wide aliases as an omitted filter before enum validation."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in _SCHOOL_DEPARTMENT_ALIASES:
        return None
    return text


def _normalize_grade_input(value: Any) -> Any:
    """Recover common small-model spellings while keeping the public schema numeric."""
    if value is None or isinstance(value, int):
        return value
    text = str(value).strip()
    if text.endswith("학년"):
        text = text.removesuffix("학년").strip()
    if text in {"1", "2", "3", "4"}:
        return int(text)
    return value


DepartmentFilter = Annotated[
    Literal["컴퓨터공학과", "경영학과"] | None,
    BeforeValidator(_normalize_department_input),
    Field(description=(
        "사용자가 특정 학과를 명시한 경우에만 선택합니다. 생략하면 로그인 사용자의 "
        "학과와 학교 공통 공지를 자동 조회하며, 공주대처럼 학교 전체를 뜻하는 값도 생략합니다."
    )),
]
GradeFilter = Annotated[
    Literal[1, 2, 3, 4] | None,
    BeforeValidator(_normalize_grade_input),
    Field(description=(
        "사용자가 특정 학년을 명시한 경우에만 선택합니다. 생략하면 로그인 사용자의 "
        "학년을 적용하며, 학년 제한이 없는 공지는 어떤 선택에서도 포함됩니다."
    )),
]
YearFilter = Annotated[int | None, Field(ge=2000, le=2200)]


def _student_id_for_principal(principal: str | None) -> str | None:
    if not principal or principal == "internal-service":
        return None
    student_id = portal_student_id(principal)
    if student_id is None:
        account = get_account(principal)
        student_id = account.get("student_id") if account else None
    return str(student_id) if student_id else None


def _profile_for_principal(principal: str | None) -> dict:
    """인증 주체의 학적정보를 반환한다. 내부 점검 token에는 개인화를 적용하지 않는다."""
    student_id = _student_id_for_principal(principal)
    return (get_user(student_id) or {}) if student_id else {}


async def _personalization(
    requested_department: str | None,
    requested_grade: int | None = None,
) -> dict:
    principal = _MCP_PRINCIPAL.get()
    profile = await anyio.to_thread.run_sync(_profile_for_principal, principal)
    profile_department = str(profile.get("major") or "").strip() or None
    profile_grade = profile.get("year")
    # 사용자 session인데 학과 동기화가 끝나지 않았다면 다른 학과 공지가 섞이지
    # 않도록 학교 공통 공지만 조회한다. 내부 운영 token은 전체 범위를 유지한다.
    default_department = (
        profile_department
        if profile_department
        else ("공통" if principal and principal != "internal-service" else None)
    )
    return {
        "department": requested_department or default_department,
        "grade": requested_grade or profile_grade,
        "profile_department": profile_department,
        "profile_grade": profile_grade,
        "automatic_department": requested_department is None,
        "automatic_grade": requested_grade is None,
    }


def _date_text(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value) if value is not None else None


def _finite_score(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if isfinite(score) else None


def _build_evidence_package(retrieval: dict) -> dict:
    query_mode = retrieval.get("query_mode") or "precise"
    if query_mode == "smalltalk":
        status = "search_not_required"
    else:
        status = "ok" if retrieval.get("contexts") else "no_results"

    body_remaining = int(_EVIDENCE_TEXT_LIMIT * 0.65)
    documents = []
    for context in retrieval.get("contexts") or []:
        raw_body = str(context.get("body_content") or context.get("snippet") or "")
        body = raw_body[:body_remaining]
        body_remaining -= len(body)
        documents.append(
            {
                "url": context.get("url") or "",
                "title": context.get("title") or "",
                "category": context.get("category"),
                "source_name": context.get("source_name"),
                "source_department": context.get("source_department"),
                "posted_at": _date_text(context.get("posted_at")),
                "start_date": _date_text(context.get("start_date")),
                "end_date": _date_text(context.get("end_date")),
                "summary": context.get("summary"),
                "body_content": body or None,
                "attachment_names": [
                    str(name) for name in (context.get("attachment_names") or [])
                ],
                "related_images": context.get("related_images") or [],
                "truncated": len(body) < len(raw_body),
            }
        )

    evidence_rows = retrieval.get("evidence_chunks") or []
    if query_mode == "broad":
        evidence_rows = retrieval.get("contexts") or []

    chunk_remaining = _EVIDENCE_TEXT_LIMIT - int(_EVIDENCE_TEXT_LIMIT * 0.65)
    evidence_chunks = []
    for evidence in evidence_rows:
        raw_content = str(
            evidence.get("content")
            or evidence.get("chunk")
            or evidence.get("matched_chunk")
            or ""
        )
        content = raw_content[:chunk_remaining]
        chunk_remaining -= len(content)
        if not content:
            break
        evidence_chunks.append(
            {
                "url": evidence.get("url") or "",
                "title": evidence.get("title") or "",
                "category": evidence.get("category"),
                "source_name": evidence.get("source_name"),
                "source_department": evidence.get("source_department"),
                "content": content,
                "vector_score": _finite_score(evidence.get("vector_score")),
                "rerank_score": _finite_score(
                    evidence.get("rerank_score", evidence.get("score"))
                ),
                "related_images": evidence.get("related_images") or [],
            }
        )

    return {
        "schema_version": 2,
        "status": status,
        "query_mode": query_mode,
        "original_query": retrieval.get("original_query") or "",
        "expanded_query": retrieval.get("expanded_query") or "",
        "categories": list(retrieval.get("categories") or []),
        "department": retrieval.get("department"),
        "time_scope": retrieval.get("time_scope") or "current",
        "year": retrieval.get("year"),
        "notice_ids": list(retrieval.get("notice_ids") or []),
        "personalization": retrieval.get("personalization") or {},
        "routing_fallback": bool(retrieval.get("routing_fallback")),
        "documents": documents,
        "evidence_chunks": evidence_chunks,
    }


class _McpAuthenticationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            authorization = headers.get(b"authorization", b"").decode()
            token = authorization.removeprefix("Bearer ").strip()
            principal = None
            if token and MCP_AUTH_TOKEN and secrets.compare_digest(token, MCP_AUTH_TOKEN):
                principal = "internal-service"
            elif token:
                try:
                    principal = decode_access_token(token)
                except HTTPException:
                    principal = None
            if not principal:
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "MCP 인증이 필요합니다."},
                )
                await response(scope, receive, send)
                return
            rate_key = f"mcp:{sha256(principal.encode()).hexdigest()}"
            if not allow_rate_limited_request(rate_key, RATE_LIMIT_MCP):
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "MCP 요청이 너무 많습니다. 잠시 후 다시 시도해주세요."},
                    headers={"Retry-After": "60"},
                )
                await response(scope, receive, send)
                return
            scope.setdefault("state", {})["mcp_principal"] = principal
            context_token = _MCP_PRINCIPAL.set(principal)
            try:
                await self.app(scope, receive, send)
            finally:
                _MCP_PRINCIPAL.reset(context_token)
            return
        await self.app(scope, receive, send)


mcp = FastMCP(
    "KNU Notice Evidence",
    instructions=(
        "Use tool discovery groups knu.notices, knu.lms, knu.portal, and knu.account. "
        "Use knu_list_notices for counts, lists, filters, current/open status, and sorting. "
        "Omit department for a school-wide or personalized request; it only accepts a supported specific department. "
        "Use knu_search_notice_details for a specific notice's dates, requirements, procedures, "
        "or attachment evidence. Combine them for comparison questions. "
        "Use portal tools for the signed-in student's grades, timetable, graduation data, and profile. "
        "Use LMS tools for the signed-in student's courses and tasks. "
        "If the evidence is insufficient, say so instead of making up an answer."
    ),
)

_GROUP_DESCRIPTIONS = {
    "knu": "공주대학교 공지, LMS, 포털 학적정보와 계정 데이터를 조회합니다.",
    "knu.notices": "학교·학과 공지의 목록, 본문, 첨부 근거와 관련 그림을 검색합니다.",
    "knu.lms": "로그인한 학생의 LMS 과목과 학습활동을 조회합니다.",
    "knu.portal": "로그인한 학생의 학적, 시간표, 성적과 졸업 데이터를 조회합니다.",
    "knu.account": "KNU 계정의 학적정보와 동기화 상태를 조회합니다.",
}


def _codmes_tool_meta(name: str, group: str) -> dict[str, Any]:
    """Publish optional Codmes catalog hints without coupling standard MCP clients."""
    return {
        "com.codmes/tool": {
            "publicName": name,
            "group": group,
            "groupDescriptions": _GROUP_DESCRIPTIONS,
        }
    }


def _read_only_tool(name: str, group: str) -> dict[str, Any]:
    return {
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "meta": _codmes_tool_meta(name, group),
    }


@mcp.tool(**_read_only_tool("knu_list_notices", "knu.notices"))
async def knu_list_notices(
    category: Literal["장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)"] | None = None,
    status: Literal["any", "open", "upcoming", "closed"] = "any",
    time_scope: Literal["current", "historical", "all"] = "current",
    department: DepartmentFilter = None,
    grade: GradeFilter = None,
    year: YearFilter = None,
    topic: Annotated[str | None, Field(description="목록을 좁힐 선택적 주제어")] = None,
) -> dict:
    """공주대학교 공지의 목록·개수·마감 상태를 필터로 조회합니다. 절차, 본문, 첨부 근거나 그림에는 사용하지 않습니다. List or count only."""
    user_scope = await _personalization(department, grade)
    result = await anyio.to_thread.run_sync(
        list_notices_for_scan,
        category,
        status,
        date.today(),
        time_scope,
        user_scope["department"],
        user_scope["grade"],
        year,
        topic,
        "posted_at",
        0,
    )
    result["personalization"] = user_scope
    return result


@mcp.tool(**_read_only_tool("knu_search_notice_details", "knu.notices"))
async def knu_search_notice_details(
    query: Annotated[str, Field(description="찾으려는 구체적인 사실, 방법 또는 절차")],
    department: DepartmentFilter = None,
    category: Literal["장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)"] | None = None,
    time_scope: Literal["current", "historical", "all"] = "current",
    year: YearFilter = None,
    notice_ids: Annotated[
        list[int] | None,
        Field(description="목록 조회 결과에서 선택한 공지 ID"),
    ] = None,
) -> ToolResult:
    """특정 공지의 방법·절차·본문·첨부 근거와 관련 그림을 임베딩 및 reranking으로 상세 검색합니다. 반환된 안전한 그림 참조만 답변에 사용할 수 있습니다."""
    user_scope = await _personalization(department)
    retrieval = await anyio.to_thread.run_sync(
        retrieve_mcp_evidence,
        query,
        user_scope["department"],
        category,
        time_scope,
        year,
        notice_ids,
    )
    retrieval["personalization"] = user_scope
    package = _build_evidence_package(retrieval)

    evidence_by_url = {
        evidence["url"]: evidence for evidence in package["evidence_chunks"]
    }
    legacy = []
    for document in package["documents"]:
        evidence = evidence_by_url.get(document["url"])
        legacy.append(
            {
                "url": document["url"],
                "title": document["title"],
                "snippet": (
                    evidence["content"]
                    if evidence
                    else document["summary"] or document["body_content"]
                ),
                "score": (
                    evidence["rerank_score"]
                    if evidence and evidence["rerank_score"] is not None
                    else (
                        evidence["vector_score"]
                        if evidence and evidence["vector_score"] is not None
                        else 0.0
                    )
                ),
                "posted_at": document["posted_at"],
                "start_date": document["start_date"],
                "end_date": document["end_date"],
                "category": document["category"],
                "source_name": document["source_name"],
                "source_department": document["source_department"],
                "summary": document["summary"],
            }
        )

    return ToolResult(
        content=legacy,
        structured_content=package,
    )


@mcp.tool(**_read_only_tool("knu_get_notice_detail", "knu.notices"))
async def knu_get_notice_detail(
    url: Annotated[str, Field(description="검색 결과에 포함된 공지 원문 URL")],
) -> dict:
    """상세 검색 결과가 반환한 구체적인 공지 URL의 저장된 전체 본문을 조회합니다."""
    content = await anyio.to_thread.run_sync(get_document_content, url)
    content = content or ""
    return {
        "content": content[:_DETAIL_CONTENT_LIMIT],
        "url": url,
        "truncated": len(content) > _DETAIL_CONTENT_LIMIT,
    }


@mcp.tool(**_read_only_tool("knu_get_portal_academic_data", "knu.portal"))
async def knu_get_portal_academic_data(
    section: Literal[
        "profile",
        "timetable",
        "grade_distribution",
        "cumulative_grades",
        "graduation_credits",
    ],
) -> dict:
    """Read one section of the signed-in student's synchronized KNU portal academic data."""
    principal = _MCP_PRINCIPAL.get()
    profile = await anyio.to_thread.run_sync(_profile_for_principal, principal)
    if not profile:
        return {"status": "not_linked", "section": section, "data": None}
    if section == "profile":
        data = {
            "student_id": profile.get("student_id"),
            "name": profile.get("name"),
            "major": profile.get("major"),
            "year": profile.get("year"),
        }
    else:
        data = profile.get(section)
    return {
        "status": "ok" if data else "no_data",
        "section": section,
        "data": data,
    }


@mcp.tool(**_read_only_tool("knu_list_lms_tasks", "knu.lms"))
async def knu_list_lms_tasks(
    status: Literal["pending", "done", "all"] = "pending",
    course_name: str | None = None,
) -> dict:
    """List the signed-in student's synchronized KNU LMS assignments, lectures, and notices."""
    principal = _MCP_PRINCIPAL.get()
    student_id = await anyio.to_thread.run_sync(_student_id_for_principal, principal)
    if not student_id:
        return {"status": "not_linked", "tasks": []}
    rows = await anyio.to_thread.run_sync(get_lms_tasks, student_id, True)
    normalized_course = str(course_name or "").strip().casefold()
    tasks = []
    for row in rows:
        is_done = bool(row.get("is_done"))
        if status == "pending" and is_done:
            continue
        if status == "done" and not is_done:
            continue
        if normalized_course and normalized_course not in str(row.get("course_name") or "").casefold():
            continue
        item = dict(row)
        item["due_date"] = _date_text(item.get("due_date"))
        tasks.append(item)
    return {"status": "ok", "tasks": tasks[:100], "returned": min(len(tasks), 100)}


@mcp.tool(**_read_only_tool("knu_list_lms_courses", "knu.lms"))
async def knu_list_lms_courses() -> dict:
    """List the signed-in student's synchronized KNU LMS courses."""
    principal = _MCP_PRINCIPAL.get()
    student_id = await anyio.to_thread.run_sync(_student_id_for_principal, principal)
    if not student_id:
        return {"status": "not_linked", "courses": []}
    courses = await anyio.to_thread.run_sync(get_lms_courses, student_id)
    return {"status": "ok", "courses": courses}


@mcp.tool(**_read_only_tool("knu_get_student_profile", "knu.account"))
async def knu_get_student_profile() -> dict:
    """Read the signed-in student's synchronized KNU account profile."""
    principal = _MCP_PRINCIPAL.get()
    profile = await anyio.to_thread.run_sync(_profile_for_principal, principal)
    if not profile:
        return {"status": "not_linked", "profile": None}
    return {
        "status": "ok",
        "profile": {
            "student_id": profile.get("student_id"),
            "name": profile.get("name"),
            "major": profile.get("major"),
            "year": profile.get("year"),
        },
    }


async def get_public_tool_catalog() -> dict[str, Any]:
    """Return the live MCP catalog used by every client, without duplicating it."""
    tools = await mcp.get_tools()
    items: list[dict[str, Any]] = []
    for tool in tools.values():
        codmes_meta = (tool.meta or {}).get("com.codmes/tool", {})
        annotations = tool.annotations.model_dump(by_alias=True) if tool.annotations else {}
        items.append(
            {
                "name": tool.name,
                "public_name": codmes_meta.get("publicName", tool.name),
                "description": tool.description or "",
                "group": codmes_meta.get("group", "knu"),
                "enabled": bool(tool.enabled),
                "input_schema": tool.parameters,
                "annotations": annotations,
            }
        )
    items.sort(key=lambda item: (item["group"], item["name"]))
    return {
        "server": mcp.name,
        "count": len(items),
        "group_descriptions": _GROUP_DESCRIPTIONS,
        "items": items,
    }


def create_mcp_app():
    return mcp.http_app(
        path="/",
        transport="streamable-http",
        json_response=True,
        stateless_http=True,
        middleware=[Middleware(_McpAuthenticationMiddleware)],
    )


class _MCPASGIApp:
    def __init__(self):
        self.app = None

    async def __call__(self, scope, receive, send):
        assert self.app is not None
        await self.app(scope, receive, send)


mcp_asgi_app = _MCPASGIApp()
