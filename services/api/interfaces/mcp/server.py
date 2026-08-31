"""KNU notice evidence tools exposed through the MCP interface."""

import secrets
from contextvars import ContextVar
from hashlib import sha256
from datetime import date, datetime
from math import isfinite
from typing import Any, Literal

import anyio
from fastapi import HTTPException
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult
from starlette.middleware import Middleware
from starlette.responses import JSONResponse

from api.deps import decode_access_token, portal_student_id
from api.ratelimit import allow_rate_limited_request
from config import MCP_AUTH_TOKEN, RATE_LIMIT_MCP
from db.accounts import get_account
from db.documents import get_document_content, list_notices_for_scan
from db.users import get_user
from retrieval.graph import retrieve_mcp_evidence


_DETAIL_CONTENT_LIMIT = 12000
_EVIDENCE_TEXT_LIMIT = 6000
_MCP_PRINCIPAL: ContextVar[str | None] = ContextVar(
    "knu_mcp_principal",
    default=None,
)


def _profile_for_principal(principal: str | None) -> dict:
    """인증 주체의 학적정보를 반환한다. 내부 점검 token에는 개인화를 적용하지 않는다."""
    if not principal or principal == "internal-service":
        return {}
    student_id = portal_student_id(principal)
    if student_id is None:
        account = get_account(principal)
        student_id = account.get("student_id") if account else None
    if not student_id:
        return {}
    return get_user(student_id) or {}


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
        "Use knu_list_notices for counts, lists, filters, current/open status, and sorting. "
        "Use knu_search_notice_details for a specific notice's dates, requirements, procedures, "
        "or attachment evidence. Combine them for comparison questions. "
        "If the evidence is insufficient, say so instead of making up an answer."
    ),
)


@mcp.tool
async def knu_list_notices(
    category: Literal["장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)"] | None = None,
    status: Literal["any", "open", "upcoming", "closed"] = "any",
    time_scope: Literal["current", "historical", "all"] = "current",
    as_of: str | None = None,
    department: str | None = None,
    grade: int | None = None,
    year: int | None = None,
    topic: str | None = None,
    sort: Literal["posted_at", "start_date", "end_date"] = "posted_at",
    offset: int = 0,
) -> dict:
    """List, filter, sort, or count KNU notices from structured metadata. Use this for broad or current-status questions; total is the full matching count."""
    reference_date = date.fromisoformat(as_of) if as_of else date.today()
    user_scope = await _personalization(department, grade)
    result = await anyio.to_thread.run_sync(
        list_notices_for_scan,
        category,
        status,
        reference_date,
        time_scope,
        user_scope["department"],
        user_scope["grade"],
        year,
        topic,
        sort,
        offset,
    )
    result["personalization"] = user_scope
    return result


@mcp.tool
async def knu_search_notice_details(
    query: str,
    department: str | None = None,
    category: Literal["장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)"] | None = None,
    time_scope: Literal["current", "historical", "all"] = "current",
    year: int | None = None,
    notice_ids: list[int] | None = None,
) -> ToolResult:
    """Search notice body and attachment evidence with embeddings and reranking. Use for a specific notice's detailed dates, eligibility, documents, or procedures."""
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


@mcp.tool
async def knu_get_notice_detail(url: str) -> dict:
    """Get the body of a notice returned by knu_search_notice_details for evidence."""
    content = await anyio.to_thread.run_sync(get_document_content, url)
    content = content or ""
    return {
        "content": content[:_DETAIL_CONTENT_LIMIT],
        "url": url,
        "truncated": len(content) > _DETAIL_CONTENT_LIMIT,
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
