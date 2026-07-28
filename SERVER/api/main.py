from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from config import WEB_CORS_ORIGINS
from db.pool import pool
from api.deps import require_user
from api.mcp_server import _create_mcp_app, mcp_asgi_app
from api.ratelimit import limiter
from api.routers import auth, health, chat, codmes_surface, lms, me, notices, portal, search


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()
    try:
        mcp_app = _create_mcp_app()
        mcp_asgi_app.app = mcp_app
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
    finally:
        mcp_asgi_app.app = None
        await pool.close()


app = FastAPI(title="KNU AI Assistant API", lifespan=lifespan)
app.state.limiter = limiter

# 웹 SPA 오리진 허용. 개발은 vite proxy로 동일 오리진이라 불필요하나,
# prod에서 웹이 API를 다른 오리진으로 직접 호출하는 경우 대비.
if WEB_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=WEB_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    # dart _handleError는 top-level detail 문자열을 그대로 노출 → 유저용 한국어로.
    return JSONResponse(
        status_code=429,
        content={"detail": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."},
    )


app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(chat.router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(notices.router, prefix="/api")
app.include_router(codmes_surface.router, prefix="/api")
app.include_router(search.router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(portal.router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(lms.router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(me.router, prefix="/api", dependencies=[Depends(require_user)])
app.mount("/api/mcp", mcp_asgi_app)
