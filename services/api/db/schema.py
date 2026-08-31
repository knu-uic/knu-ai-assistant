from __future__ import annotations

import os
from datetime import date

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from psycopg import sql

from config import DB_HOST
from model import EMBEDDING_DIM

load_dotenv()

DB_URL = os.getenv("DATABASE_URL") or (
    f"postgresql://{os.getenv('DB_USER', 'knu-uic')}:"
    f"{os.getenv('DB_PASSWORD')}@{DB_HOST}:"
    f"{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'knu-uic')}"
)

_LEGACY_NOTICE_TABLES = (
    "document_scholarship_chunk",
    "document_academic_chunk",
    "document_career_chunk",
    "document_event_chunk",
    "document_etc_chunk",
    "document_scholarship",
    "document_academic",
    "document_career",
    "document_event",
    "document_etc",
    "document_chunk",
    "document_asset",
    "document",
)


def _connect_with_vector():
    conn = psycopg.connect(DB_URL)
    register_vector(conn)
    return conn


def _months_ago(today: date, months: int) -> date:
    month_index = today.month - 1 - months
    year = today.year + month_index // 12
    month = month_index % 12 + 1
    days_in_month = [
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ][month - 1]
    return date(year, month, min(today.day, days_in_month))


def reset_db():
    """개발용 공지 데이터 초기화. 사용자·학적·LMS 데이터는 보존한다."""
    init_db()
    with psycopg.connect(DB_URL) as conn:
        conn.execute("TRUNCATE TABLE notice RESTART IDENTITY CASCADE")
        for table in _LEGACY_NOTICE_TABLES:
            conn.execute(
                sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(table))
            )
        conn.commit()


def init_db():
    """마이그레이션과 환경별 임베딩 차원의 통합 notice_chunk를 준비한다."""
    from db.migrate import migrate

    migrate()
    with psycopg.connect(DB_URL) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS notice_chunk (
                    id BIGSERIAL PRIMARY KEY,
                    notice_id BIGINT NOT NULL REFERENCES notice(id) ON DELETE CASCADE,
                    chunk_idx INT NOT NULL,
                    content TEXT NOT NULL,
                    chunk_type VARCHAR(20) NOT NULL DEFAULT 'body',
                    attachment_name VARCHAR(500),
                    embedding vector({embedding_dim}) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE(notice_id, chunk_idx)
                )
                """
            ).format(embedding_dim=sql.SQL(str(EMBEDDING_DIM)))
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notice_chunk_notice ON notice_chunk(notice_id)"
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notice_chunk_embedding
            ON notice_chunk USING hnsw (embedding vector_cosine_ops)
            """
        )
        conn.commit()
    print("✅ 통합 notice v2 스키마 준비 완료")


__all__ = [
    "DB_URL",
    "_connect_with_vector",
    "_months_ago",
    "reset_db",
    "init_db",
]
