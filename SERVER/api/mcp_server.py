import secrets

import anyio
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.responses import JSONResponse

from api.routers.search import search_notice_results
from config import MCP_AUTH_TOKEN
from db.documents import get_document_content


_DETAIL_CONTENT_LIMIT = 12000


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
) -> list[dict]:
    """Search KNU notices for evidence. Use only returned evidence in your final answer."""
    results = await search_notice_results(
        q=query,
        major=major,
        category=category,
        limit=max(1, min(limit, 10)),
    )
    return [result.model_dump() for result in results]


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
