from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from db.pool import pool
from api.deps import require_user
from api.routers import auth, health, chat, notices, search


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="KNU AI Assistant API", lifespan=lifespan)
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(chat.router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(notices.router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(search.router, prefix="/api", dependencies=[Depends(require_user)])
