"""유저별 LMS 세션을 Redis에 암호화 보관.

세션 = Playwright storage_state(쿠키) + Canvas 토큰. 비밀번호가 아니라
시한부 출입증이며, TTL 만료 후 죽는다. 유출돼도 비밀번호 복원 불가.
암호화는 비밀번호 잡 페이로드와 같은 Fernet 키를 쓴다(api/crypto).
"""
import json

import redis as redis_sync

from api.crypto import decrypt_secret, encrypt_secret
from config import LMS_SESSION_TTL_DAYS, REDIS_URL

_KEY_PREFIX = "lms-session:"


def _client() -> redis_sync.Redis:
    return redis_sync.from_url(REDIS_URL or "redis://localhost:6379")


def _key(username: str) -> str:
    return f"{_KEY_PREFIX}{username}"


def load_session(username: str) -> dict | None:
    """{"storage_state": str, "canvas_token": str|None} 또는 없으면 None."""
    r = _client()
    try:
        raw = r.get(_key(username))
    finally:
        r.close()
    if not raw:
        return None
    token = raw.decode() if isinstance(raw, bytes) else raw
    return json.loads(decrypt_secret(token))


def save_session(username: str, storage_state: str, canvas_token: str | None) -> None:
    payload = json.dumps({"storage_state": storage_state, "canvas_token": canvas_token})
    r = _client()
    try:
        r.set(
            _key(username),
            encrypt_secret(payload),
            ex=LMS_SESSION_TTL_DAYS * 24 * 3600,
        )
    finally:
        r.close()
