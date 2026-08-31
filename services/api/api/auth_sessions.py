"""Revocable, non-expiring API sessions stored in Redis."""

import hashlib
import secrets

import redis as redis_sync

from config import REDIS_URL

_KEY_PREFIX = "auth-session:"


def _client() -> redis_sync.Redis:
    return redis_sync.from_url(REDIS_URL or "redis://localhost:6379")


def _key(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode()).hexdigest()
    return f"{_KEY_PREFIX}{digest}"


def create_auth_session(principal: str) -> str:
    session_id = secrets.token_urlsafe(32)
    client = _client()
    try:
        client.set(_key(session_id), principal)
    finally:
        client.close()
    return session_id


def is_auth_session_active(session_id: str, principal: str) -> bool:
    if not session_id:
        return False
    client = _client()
    try:
        stored = client.get(_key(session_id))
    finally:
        client.close()
    if isinstance(stored, bytes):
        stored = stored.decode()
    return stored == principal


def revoke_auth_session(session_id: str, principal: str) -> bool:
    if not is_auth_session_active(session_id, principal):
        return False
    client = _client()
    try:
        return bool(client.delete(_key(session_id)))
    finally:
        client.close()
