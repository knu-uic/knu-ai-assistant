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
    """마이그레이션과 모델별 임베딩 데이터셋을 준비한다."""
    from db.migrate import migrate

    migrate()
    with psycopg.connect(DB_URL) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_dataset (
                id BIGSERIAL PRIMARY KEY,
                provider VARCHAR(40) NOT NULL,
                model VARCHAR(255) NOT NULL,
                dimension INT NOT NULL CHECK (dimension > 0 AND dimension <= 4096),
                base_url VARCHAR(1000) NOT NULL DEFAULT '',
                status VARCHAR(20) NOT NULL DEFAULT 'ready',
                completed_notices INT NOT NULL DEFAULT 0,
                total_notices INT NOT NULL DEFAULT 0,
                total_chunks INT NOT NULL DEFAULT 0,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                completed_at TIMESTAMPTZ,
                last_synced_at TIMESTAMPTZ,
                UNIQUE(provider, model, dimension, base_url)
            )
            """
        )
        dataset_id = conn.execute(
            """
            INSERT INTO embedding_dataset(provider, model, dimension, base_url)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(provider, model, dimension, base_url) DO UPDATE
            SET updated_at = embedding_dataset.updated_at
            RETURNING id
            """,
            (
                "ollama",
                os.getenv("EMBEDDING_MODEL") or "bge-m3:latest",
                EMBEDDING_DIM,
                "http://127.0.0.1:11434/v1",
            ),
        ).fetchone()[0]
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
                    embedding vector NOT NULL,
                    embedding_provider VARCHAR(40) NOT NULL DEFAULT 'ollama',
                    embedding_model VARCHAR(255) NOT NULL DEFAULT 'bge-m3:latest',
                    embedding_dimension INT NOT NULL DEFAULT {embedding_dim},
                    embedding_dataset_id BIGINT NOT NULL
                        REFERENCES embedding_dataset(id) ON DELETE CASCADE
                        DEFAULT {dataset_id},
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE(embedding_dataset_id, notice_id, chunk_idx)
                )
                """
            ).format(
                embedding_dim=sql.SQL(str(EMBEDDING_DIM)),
                dataset_id=sql.SQL(str(dataset_id)),
            )
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notice_chunk_notice ON notice_chunk(notice_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notice_chunk_dataset_notice "
            "ON notice_chunk(embedding_dataset_id, notice_id)"
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
