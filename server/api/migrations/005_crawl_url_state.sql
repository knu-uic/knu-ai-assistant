-- 005_crawl_url_state: 페이지 번호가 아닌 고정 URL로 크롤링 완료·실패 상태를 관리한다.

CREATE TABLE IF NOT EXISTS crawl_url_state (
    url VARCHAR(800) PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL CHECK (status IN ('discovered', 'completed', 'failed')),
    posted_at DATE,
    is_pinned BOOLEAN NOT NULL DEFAULT false,
    extraction_version VARCHAR(40),
    first_discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    attempt_count INT NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_crawl_url_state_source_status
ON crawl_url_state(source_id, status);

CREATE INDEX IF NOT EXISTS idx_crawl_url_state_posted
ON crawl_url_state(posted_at DESC);

-- 이미 저장된 공지는 완료 URL로 승계한다.
INSERT INTO crawl_url_state (
    url, source_id, status, posted_at, is_pinned, extraction_version,
    first_discovered_at, last_seen_at, last_attempt_at, completed_at
)
SELECT
    url, source_id, 'completed', posted_at, is_pinned, extraction_version,
    crawled_at, updated_at, crawled_at, updated_at
FROM notice
ON CONFLICT (url) DO NOTHING;
