from contextlib import asynccontextmanager

from fastapi import FastAPI

from db.pool import pool
from api.routers import health, chat, notices


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="KNU AI Assistant API", lifespan=lifespan)
app.include_router(health.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(notices.router, prefix="/api")
