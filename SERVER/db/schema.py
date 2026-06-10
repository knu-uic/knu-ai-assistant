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
    """category별 document/chunk 스키마를 비파괴적으로 준비한다."""
    with psycopg.connect(DB_URL) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS source (
                id BIGSERIAL PRIMARY KEY,
                code VARCHAR(50) UNIQUE NOT NULL,
                name VARCHAR(100) NOT NULL,
                kind VARCHAR(20) NOT NULL CHECK (kind IN ('notice', 'academic')),
                department VARCHAR(100),
                base_url VARCHAR(500),
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)

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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS document_asset (
                id BIGSERIAL PRIMARY KEY,
                category VARCHAR(20) NOT NULL,
                document_id BIGINT NOT NULL,
                kind VARCHAR(30) NOT NULL,
                filename VARCHAR(300),
                source_url VARCHAR(800) NOT NULL,
                storage_path VARCHAR(800),
                mime_type VARCHAR(80),
                extracted_text TEXT,
                order_idx INT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_document_asset_doc  ON document_asset(category, document_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_document_asset_kind ON document_asset(kind);")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                student_id VARCHAR(20) PRIMARY KEY,
                major VARCHAR(50),
                name VARCHAR(50),
                year INT,
                interests TEXT,
                courses TEXT
            );
        """)
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS year INT;")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS favorite_courses TEXT;")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS graduation_credits JSONB;")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS timetable JSONB;")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS grade_distribution_json JSONB;")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS cumulative_grades_json JSONB;")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS lms_tasks (
                id BIGSERIAL PRIMARY KEY,
                student_id VARCHAR(20) NOT NULL REFERENCES users(student_id) ON DELETE CASCADE,
                task_type VARCHAR(20) NOT NULL CHECK (task_type IN ('lecture', 'assignment', 'notice')),
                title VARCHAR(255) NOT NULL,
                course_name VARCHAR(120),
                due_date DATE,
                progress INT CHECK (progress IS NULL OR (progress >= 0 AND progress <= 100)),
                url VARCHAR(800),
                is_done BOOLEAN NOT NULL DEFAULT false,
                source VARCHAR(30) NOT NULL DEFAULT 'manual',
                external_id VARCHAR(160),
                synced_at TIMESTAMPTZ,
                raw JSONB,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        conn.execute("ALTER TABLE lms_tasks ADD COLUMN IF NOT EXISTS source VARCHAR(30) NOT NULL DEFAULT 'manual';")
        conn.execute("ALTER TABLE lms_tasks ADD COLUMN IF NOT EXISTS external_id VARCHAR(160);")
        conn.execute("ALTER TABLE lms_tasks ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ;")
        conn.execute("ALTER TABLE lms_tasks ADD COLUMN IF NOT EXISTS raw JSONB;")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lms_tasks_student_done_due ON lms_tasks(student_id, is_done, due_date);")
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_lms_tasks_external
            ON lms_tasks(student_id, source, external_id)
            WHERE external_id IS NOT NULL;
        """)
        # 자체 웹 로그인 계정. student_id는 추후 포털 연동 시 users와 링크용(현재 미사용).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id BIGSERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email VARCHAR(100) UNIQUE,
                student_id VARCHAR(20),
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        conn.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS email VARCHAR(100) UNIQUE;")

        # 가입 인증 코드. 만료(expires_at) 지난 행은 검증에서 무시되고 다음 가입 때 삭제됨.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_verifications (
                id BIGSERIAL PRIMARY KEY,
                email VARCHAR(100) NOT NULL,
                code VARCHAR(6) NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_verifications_email ON email_verifications(email);")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS lms_courses (
                student_id VARCHAR(20) NOT NULL REFERENCES users(student_id) ON DELETE CASCADE,
                course_id BIGINT NOT NULL,
                course_name VARCHAR(200) NOT NULL,
                synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (student_id, course_id)
            );
        """)
        conn.commit()
        print(f"✅ source + {len(SLUGS)}개 category 테이블({', '.join(SLUGS)}) + asset/users 생성 완료")


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
