-- KNU PICK 웹·모바일 전용 대화 기록. Codmes 세션과 연동하지 않는다.
CREATE TABLE IF NOT EXISTS student_chat_conversation (
    id UUID PRIMARY KEY,
    student_id VARCHAR(20) NOT NULL REFERENCES users(student_id) ON DELETE CASCADE,
    title VARCHAR(100) NOT NULL,
    source VARCHAR(16) NOT NULL DEFAULT 'personal' CHECK (source IN ('school', 'personal')),
    messages JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(messages) = 'array' AND jsonb_array_length(messages) <= 200),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    legacy_key VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (student_id, legacy_key)
);
CREATE INDEX IF NOT EXISTS student_chat_conversation_recent_idx
    ON student_chat_conversation(student_id, updated_at DESC, id DESC);
