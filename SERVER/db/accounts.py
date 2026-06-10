from __future__ import annotations

from datetime import datetime

import psycopg

from db.pool import sync_pool


def create_account(username: str, password_hash: str, email: str) -> bool:
    """계정 생성. username/email 중복이면 False를 반환한다."""
    try:
        with sync_pool.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO accounts (username, password_hash, email)
                VALUES (%s, %s, %s)
                ON CONFLICT (username) DO NOTHING
                RETURNING id;
                """,
                (username, password_hash, email),
            )
            created = cur.fetchone() is not None
            conn.commit()
    except psycopg.errors.UniqueViolation:
        # email UNIQUE 충돌 — username 충돌은 위 ON CONFLICT가 흡수한다.
        return False
    return created


def get_account(username: str) -> dict | None:
    with sync_pool.connection() as conn:
        cur = conn.execute(
            "SELECT id, username, password_hash, student_id FROM accounts WHERE username = %s;",
            (username,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "username": row[1],
        "password_hash": row[2],
        "student_id": row[3],
    }


def last_verification_at(email: str) -> datetime | None:
    """해당 메일의 마지막 인증 코드 발송 시각. 재발송 쿨다운 판정용."""
    with sync_pool.connection() as conn:
        cur = conn.execute(
            "SELECT created_at FROM email_verifications WHERE email = %s ORDER BY id DESC LIMIT 1;",
            (email,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def insert_verification(email: str, code: str, expires_at: datetime) -> None:
    with sync_pool.connection() as conn:
        conn.execute(
            "INSERT INTO email_verifications (email, code, expires_at) VALUES (%s, %s, %s);",
            (email, code, expires_at),
        )
        conn.commit()


def consume_verification(email: str, code: str) -> bool:
    """코드가 일치하고 미만료면 해당 메일의 코드를 전부 삭제하고 True."""
    with sync_pool.connection() as conn:
        cur = conn.execute(
            "SELECT 1 FROM email_verifications WHERE email = %s AND code = %s AND expires_at > now() LIMIT 1;",
            (email, code),
        )
        ok = cur.fetchone() is not None
        if ok:
            conn.execute("DELETE FROM email_verifications WHERE email = %s;", (email,))
        conn.commit()
    return ok


__all__ = [
    "create_account",
    "get_account",
    "last_verification_at",
    "insert_verification",
    "consume_verification",
]
