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

CATEGORY_SLUGS: dict[str, str] = {
    "장학": "scholarship",
    "수강": "academic",
    "취업(진로)": "career",
    "행사(공모전)": "event",
    "일반(기타)": "etc",
}
SLUG_TO_CATEGORY: dict[str, str] = {v: k for k, v in CATEGORY_SLUGS.items()}
SLUGS: list[str] = list(CATEGORY_SLUGS.values())


def _slug(category: str) -> str:
    s = CATEGORY_SLUGS.get(category)
    if not s:
        raise ValueError(f"Unknown category: {category!r}")
    return s


def _doc_ident(slug: str) -> sql.Identifier:
    return sql.Identifier(f"document_{slug}")


def _chunk_ident(slug: str) -> sql.Identifier:
    return sql.Identifier(f"document_{slug}_chunk")


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
    """개발용 전체 초기화. 모든 문서/청크/자산 테이블을 DROP한다."""
    with psycopg.connect(DB_URL) as conn:
        for legacy in ("notice_asset", "notice", "document_chunk", "document_asset", "document"):
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE;").format(sql.Identifier(legacy)))
        for slug in SLUGS:
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE;").format(_chunk_ident(slug)))
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE;").format(_doc_ident(slug)))
        conn.commit()
    init_db()


def init_db():
    """전체 스키마를 비파괴적으로 준비한다.

    고정 테이블(source, users, accounts 등)은 migrations/ 러너가 담당하고,
    여기서는 category별 동적 document/chunk 테이블만 만든다.
    """
    # 동적 테이블이 source(id)를 참조하므로 고정 테이블 먼저.
    # (함수 안 import: db.migrate가 이 모듈의 DB_URL을 쓰는 순환 참조 방지)
    from db.migrate import migrate

    migrate()
    with psycopg.connect(DB_URL) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        for slug in SLUGS:
            conn.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {doc} (
                    id BIGSERIAL PRIMARY KEY,
                    source_id BIGINT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
                    url VARCHAR(500) UNIQUE NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    content TEXT NOT NULL,
                    body_content TEXT,
                    attachment_names JSONB,
                    attachment_contents JSONB,
                    summary TEXT,
                    posted_at DATE,
                    start_date DATE,
                    end_date DATE,
                    is_pinned BOOLEAN NOT NULL DEFAULT false,
                    target VARCHAR(100)[],
                    keywords VARCHAR(50)[],
                    extra JSONB,
                    crawled_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ DEFAULT now()
                );
            """).format(doc=_doc_ident(slug)))
            conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {doc}(source_id);").format(
                idx=sql.Identifier(f"idx_document_{slug}_source"),
                doc=_doc_ident(slug),
            ))
            conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {doc}(end_date);").format(
                idx=sql.Identifier(f"idx_document_{slug}_end_date"),
                doc=_doc_ident(slug),
            ))
            conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {doc}(posted_at);").format(
                idx=sql.Identifier(f"idx_document_{slug}_posted_at"),
                doc=_doc_ident(slug),
            ))
            conn.execute(sql.SQL("ALTER TABLE {doc} ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT false;").format(
                doc=_doc_ident(slug),
            ))
            conn.execute(sql.SQL("ALTER TABLE {doc} ADD COLUMN IF NOT EXISTS summary TEXT;").format(
                doc=_doc_ident(slug),
            ))
            conn.execute(sql.SQL("ALTER TABLE {doc} ADD COLUMN IF NOT EXISTS body_content TEXT;").format(
                doc=_doc_ident(slug),
            ))
            conn.execute(sql.SQL("ALTER TABLE {doc} ADD COLUMN IF NOT EXISTS attachment_names JSONB;").format(
                doc=_doc_ident(slug),
            ))
            conn.execute(sql.SQL("ALTER TABLE {doc} ADD COLUMN IF NOT EXISTS attachment_contents JSONB;").format(
                doc=_doc_ident(slug),
            ))
            conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {doc}(is_pinned);").format(
                idx=sql.Identifier(f"idx_document_{slug}_is_pinned"),
                doc=_doc_ident(slug),
            ))

            conn.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {chunk} (
                    id BIGSERIAL PRIMARY KEY,
                    document_id BIGINT NOT NULL REFERENCES {doc}(id) ON DELETE CASCADE,
                    chunk_idx INT NOT NULL,
                    content TEXT NOT NULL,
                    chunk_type VARCHAR(20) NOT NULL DEFAULT 'body',
                    attachment_name VARCHAR(300),
                    embedding vector({embedding_dim}) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(document_id, chunk_idx)
                );
            """).format(
                chunk=_chunk_ident(slug),
                doc=_doc_ident(slug),
                embedding_dim=sql.SQL(str(EMBEDDING_DIM)),
            ))
            conn.execute(sql.SQL("ALTER TABLE {chunk} DROP COLUMN IF EXISTS source_asset_id;").format(
                chunk=_chunk_ident(slug),
            ))
            conn.execute(sql.SQL("ALTER TABLE {chunk} ADD COLUMN IF NOT EXISTS chunk_type VARCHAR(20) NOT NULL DEFAULT 'body';").format(
                chunk=_chunk_ident(slug),
            ))
            conn.execute(sql.SQL("ALTER TABLE {chunk} ADD COLUMN IF NOT EXISTS attachment_name VARCHAR(300);").format(
                chunk=_chunk_ident(slug),
            ))
            conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {chunk}(document_id);").format(
                idx=sql.Identifier(f"idx_document_{slug}_chunk_document"),
                chunk=_chunk_ident(slug),
            ))
            conn.execute(sql.SQL(
                "CREATE INDEX IF NOT EXISTS {idx} ON {chunk} USING hnsw (embedding vector_cosine_ops);"
            ).format(
                idx=sql.Identifier(f"idx_document_{slug}_chunk_embedding"),
                chunk=_chunk_ident(slug),
            ))

        conn.commit()
        print(f"✅ 고정 테이블(migrations) + {len(SLUGS)}개 category 테이블({', '.join(SLUGS)}) 준비 완료")


__all__ = [
    "DB_URL",
    "CATEGORY_SLUGS",
    "SLUG_TO_CATEGORY",
    "SLUGS",
    "_slug",
    "_doc_ident",
    "_chunk_ident",
    "_connect_with_vector",
    "_months_ago",
    "reset_db",
    "init_db",
]
