import secrets
from datetime import date, datetime
from math import isfinite
from typing import Any

import anyio
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult
from starlette.middleware import Middleware
from starlette.responses import JSONResponse

from config import MCP_AUTH_TOKEN
from db.documents import get_document_content
from retrieval.graph import retrieve_mcp_evidence


_DETAIL_CONTENT_LIMIT = 12000
_EVIDENCE_TEXT_LIMIT = 6000


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


def _build_evidence_package(retrieval: dict, limit: int) -> dict:
    query_mode = retrieval.get("query_mode") or "precise"
    if query_mode == "smalltalk":
        status = "search_not_required"
    else:
        status = "ok" if retrieval.get("contexts") else "no_results"

    body_remaining = int(_EVIDENCE_TEXT_LIMIT * 0.65)
    documents = []
    for context in (retrieval.get("contexts") or [])[:limit]:
        raw_body = str(context.get("body_content") or context.get("snippet") or "")
        body = raw_body[:body_remaining]
        body_remaining -= len(body)
        documents.append(
            {
                "url": context.get("url") or "",
                "title": context.get("title") or "",
                "category": context.get("category"),
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
        "routing_fallback": bool(retrieval.get("routing_fallback")),
        "documents": documents,
        "evidence_chunks": evidence_chunks,
    }


class _StaticBearerMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            authorization = headers.get(b"authorization", b"").decode()
            expected = f"Bearer {MCP_AUTH_TOKEN}" if MCP_AUTH_TOKEN else ""
            if not expected or not secrets.compare_digest(authorization, expected):
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "MCP 인증이 필요합니다."},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


mcp = FastMCP(
    "KNU Notice Evidence",
    instructions=(
        "Use these tools only to retrieve KNU notice evidence. "
        "If the evidence is insufficient, say so instead of making up an answer."
    ),
)


@mcp.tool
async def search_knu_notices(
    query: str,
    major: str | None = None,
    category: str | None = None,
    limit: int = 10,
) -> ToolResult:
    """Use for current 수강/학사/장학 공지, dates, procedures, or notice lists even when KNU is omitted. Cite returned URLs and do not exceed the evidence."""
    limit = max(1, min(limit, 10))
    retrieval = await anyio.to_thread.run_sync(
        retrieve_mcp_evidence,
        query,
        major,
        category,
    )
    package = _build_evidence_package(retrieval, limit)

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
                "summary": document["summary"],
            }
        )

    return ToolResult(
        content=legacy,
        structured_content=package,
    )


@mcp.tool
async def get_knu_notice_detail(category: str, url: str) -> dict:
    """Get the body of a notice returned by search_knu_notices for evidence."""
    content = await anyio.to_thread.run_sync(get_document_content, category, url)
    content = content or ""
    return {
        "content": content[:_DETAIL_CONTENT_LIMIT],
        "url": url,
        "truncated": len(content) > _DETAIL_CONTENT_LIMIT,
    }


def _create_mcp_app():
    return mcp.http_app(
        path="/",
        transport="streamable-http",
        json_response=True,
        stateless_http=True,
        middleware=[Middleware(_StaticBearerMiddleware)],
    )


class _MCPASGIApp:
    def __init__(self):
        self.app = None

    async def __call__(self, scope, receive, send):
        assert self.app is not None
        await self.app(scope, receive, send)


mcp_asgi_app = _MCPASGIApp()
