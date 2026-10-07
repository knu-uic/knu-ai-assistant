-- 자동 품질 기준을 통과하지 못한 문서를 검색/답변 DB와 분리해 보관한다.
CREATE TABLE IF NOT EXISTS extraction_review (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    url VARCHAR(800) UNIQUE NOT NULL,
    title VARCHAR(500) NOT NULL,
    reason TEXT NOT NULL,
    quality JSONB NOT NULL DEFAULT '{}',
    artifact_path VARCHAR(1200),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_extraction_review_source
ON extraction_review(source_id, updated_at DESC);
