from __future__ import annotations

import psycopg

from db.schema import DB_URL


def create_account(username: str, password_hash: str) -> bool:
    """계정 생성. username 중복이면 False를 반환한다."""
    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute(
            """
            INSERT INTO accounts (username, password_hash)
            VALUES (%s, %s)
            ON CONFLICT (username) DO NOTHING
            RETURNING id;
            """,
            (username, password_hash),
        )
        created = cur.fetchone() is not None
        conn.commit()
    return created


def get_account(username: str) -> dict | None:
    with psycopg.connect(DB_URL) as conn:
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


__all__ = ["create_account", "get_account"]
