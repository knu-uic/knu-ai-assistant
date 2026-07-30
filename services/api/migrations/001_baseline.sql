-- 001_baseline: 기존 init_db()가 만들던 고정 테이블 이관.
-- 전부 IF NOT EXISTS라 새 DB·기존 DB 어느 쪽에 돌려도 안전하다.
-- 동적 분할 테이블(document_<slug>, *_chunk)은 대상 아님 — db/schema.py init_db()가 담당.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS source (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    kind VARCHAR(20) NOT NULL CHECK (kind IN ('notice', 'academic')),
    department VARCHAR(100),
    base_url VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT now()
);

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
CREATE INDEX IF NOT EXISTS idx_document_asset_doc  ON document_asset(category, document_id);
CREATE INDEX IF NOT EXISTS idx_document_asset_kind ON document_asset(kind);

CREATE TABLE IF NOT EXISTS users (
    student_id VARCHAR(20) PRIMARY KEY,
    major VARCHAR(50),
    name VARCHAR(50),
    year INT,
    interests TEXT,
    courses TEXT,
    favorite_courses TEXT,
    graduation_credits JSONB,
    timetable JSONB,
    grade_distribution_json JSONB,
    cumulative_grades_json JSONB
);
-- 과거 init_db가 ALTER로 추가하던 컬럼 — 아주 오래된 DB 대비 유지(전부 멱등)
ALTER TABLE users ADD COLUMN IF NOT EXISTS year INT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS favorite_courses TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS graduation_credits JSONB;
ALTER TABLE users ADD COLUMN IF NOT EXISTS timetable JSONB;
ALTER TABLE users ADD COLUMN IF NOT EXISTS grade_distribution_json JSONB;
ALTER TABLE users ADD COLUMN IF NOT EXISTS cumulative_grades_json JSONB;

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
ALTER TABLE lms_tasks ADD COLUMN IF NOT EXISTS source VARCHAR(30) NOT NULL DEFAULT 'manual';
ALTER TABLE lms_tasks ADD COLUMN IF NOT EXISTS external_id VARCHAR(160);
ALTER TABLE lms_tasks ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ;
ALTER TABLE lms_tasks ADD COLUMN IF NOT EXISTS raw JSONB;
CREATE INDEX IF NOT EXISTS idx_lms_tasks_student_done_due ON lms_tasks(student_id, is_done, due_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_lms_tasks_external
ON lms_tasks(student_id, source, external_id)
WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS lms_courses (
    student_id VARCHAR(20) NOT NULL REFERENCES users(student_id) ON DELETE CASCADE,
    course_id BIGINT NOT NULL,
    course_name VARCHAR(200) NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (student_id, course_id)
);

-- 자체 웹 로그인 계정. student_id는 추후 포털 연동 시 users와 링크용(현재 미사용).
CREATE TABLE IF NOT EXISTS accounts (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email VARCHAR(100) UNIQUE,
    student_id VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS email VARCHAR(100) UNIQUE;

-- 가입 인증 코드. 만료(expires_at) 지난 행은 검증에서 무시된다.
CREATE TABLE IF NOT EXISTS email_verifications (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(100) NOT NULL,
    code VARCHAR(6) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_email_verifications_email ON email_verifications(email);
