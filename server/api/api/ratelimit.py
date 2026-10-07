"""요청 레이트리밋 (slowapi).

키 전략:
- 공개 엔드포인트(auth): 클라이언트 IP — 토큰이 없으므로.
- 보호 엔드포인트(chat 등): JWT sub(유저) — 같은 유저가 IP를 바꿔도 상한 유지.
"""
import jwt
from fastapi import Request
from limits import parse_many
from slowapi import Limiter
from slowapi.util import get_remote_address

from config import REDIS_URL


def user_or_ip(request: Request) -> str:
    """JWT sub 기반 키. 보호 라우터는 require_user가 먼저 서명을 검증하므로
    여기서는 unverified decode로 충분하다(위조 토큰은 엔드포인트 도달 전 401)."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = jwt.decode(auth[7:], options={"verify_signature": False})
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except jwt.InvalidTokenError:
            pass
    return get_remote_address(request)


limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=REDIS_URL or "memory://",
)


def allow_rate_limited_request(key: str, limit_spec: str) -> bool:
    """Apply one or more SlowAPI/limits rules to a non-FastAPI interface."""
    limits = parse_many(limit_spec)
    return all(limiter._limiter.hit(item, key) for item in limits)
