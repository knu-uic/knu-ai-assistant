"""Service health contract shared by every client."""

from fastapi import APIRouter

from config import MIN_APP_VERSION

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Liveness 체크. dart는 HTTP 200만 본다(DB 의존 없음).
    min_app_version: 이 값 미만 앱은 시작 시 강제 업데이트 안내(APK 직배포 대응)."""
    return {"status": "ok", "min_app_version": MIN_APP_VERSION}
