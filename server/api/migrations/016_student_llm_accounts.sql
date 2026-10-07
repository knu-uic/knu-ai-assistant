-- 학생의 대화용 자격증명. 학교 공용 크롤링/정제 설정과 분리한다.
CREATE TABLE IF NOT EXISTS student_llm_account (
    id UUID PRIMARY KEY,
    student_id VARCHAR(20) NOT NULL REFERENCES users(student_id) ON DELETE CASCADE,
    provider VARCHAR(24) NOT NULL CHECK (provider IN ('openai', 'openai-codex')),
    label VARCHAR(255) NOT NULL DEFAULT '',
    encrypted_secret TEXT NOT NULL,
    credential_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    model VARCHAR(255) NOT NULL DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS student_llm_account_student_idx ON student_llm_account(student_id);
CREATE UNIQUE INDEX IF NOT EXISTS student_llm_account_active_idx
    ON student_llm_account(student_id) WHERE active;
