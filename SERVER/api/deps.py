"""API 인증 의존성 — 자체 계정(JWT Bearer) 검증."""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import AUTH_JWT_SECRET, AUTH_TOKEN_TTL_DAYS

_bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    # 서버 기동은 막지 않되, 인증 기능 사용 시점에 .env 누락을 명확히 알린다.
    if not AUTH_JWT_SECRET:
        raise RuntimeError(
            "AUTH_JWT_SECRET 환경변수가 설정되지 않았습니다. "
            ".env에 충분히 긴 무작위 문자열로 설정하세요."
        )
    return AUTH_JWT_SECRET


def create_access_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(days=AUTH_TOKEN_TTL_DAYS),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Bearer 토큰을 검증하고 username을 반환한다. 보호 라우터 공용 의존성."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="인증 토큰이 필요합니다.")
    try:
        payload = jwt.decode(credentials.credentials, _secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="토큰이 만료되었습니다.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
    return payload["sub"]
