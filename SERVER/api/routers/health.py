from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Liveness 체크. dart는 HTTP 200만 본다(DB 의존 없음)."""
    return {"status": "ok"}
