from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from db.pool import pool
from api.deps import require_user
from api.ratelimit import limiter
from api.routers import auth, health, chat, lms, me, notices, portal, search


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="KNU AI Assistant API", lifespan=lifespan)
app.state.limiter = limiter


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
app.include_router(notices.router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(search.router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(portal.router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(lms.router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(me.router, prefix="/api", dependencies=[Depends(require_user)])
