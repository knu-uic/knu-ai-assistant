-- 002_notice_v2: Scan/Deep 검색을 위한 통합 공지 메타데이터.
-- 임베딩 차원은 배포 환경마다 다르므로 notice_chunk는 db/schema.py가 생성한다.

CREATE TABLE IF NOT EXISTS notice (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    url VARCHAR(800) UNIQUE NOT NULL,
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    body_content TEXT,
    summary TEXT,
    category VARCHAR(20) NOT NULL CHECK (
        category IN ('장학', '수강', '취업(진로)', '행사(공모전)', '일반(기타)')
    ),
    topics TEXT[] NOT NULL DEFAULT '{}',
    series_key VARCHAR(160),
    posted_at DATE,
    source_updated_at TIMESTAMPTZ,
    is_pinned BOOLEAN NOT NULL DEFAULT false,
    preserve_forever BOOLEAN NOT NULL DEFAULT false,
    archived_at TIMESTAMPTZ,
    archive_reason VARCHAR(80),
    content_sha256 CHAR(64),
    extraction_version VARCHAR(40),
    extraction_confidence DOUBLE PRECISION CHECK (
        extraction_confidence IS NULL
        OR (extraction_confidence >= 0 AND extraction_confidence <= 1)
    ),
    extra JSONB,
    crawled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notice_source ON notice(source_id);
CREATE INDEX IF NOT EXISTS idx_notice_category_posted ON notice(category, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_notice_archive_posted ON notice(archived_at, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_notice_series_posted ON notice(series_key, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_notice_topics ON notice USING GIN(topics);
CREATE INDEX IF NOT EXISTS idx_notice_pinned ON notice(is_pinned);

CREATE TABLE IF NOT EXISTS notice_period (
    id BIGSERIAL PRIMARY KEY,
    notice_id BIGINT NOT NULL REFERENCES notice(id) ON DELETE CASCADE,
    kind VARCHAR(40) NOT NULL CHECK (
        kind IN (
            'application',
            'document_submission',
            'result_announcement',
            'event',
            'registration',
            'payment',
            'other'
        )
    ),
    starts_on DATE,
    ends_on DATE,
    source_text TEXT NOT NULL,
    confidence DOUBLE PRECISION CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    ),
    inferred_year BOOLEAN NOT NULL DEFAULT false,
    order_idx INT NOT NULL DEFAULT 0,
    CHECK (starts_on IS NOT NULL OR ends_on IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_notice_period_notice ON notice_period(notice_id);
CREATE INDEX IF NOT EXISTS idx_notice_period_kind_dates
ON notice_period(kind, starts_on, ends_on);

CREATE TABLE IF NOT EXISTS notice_audience (
    id BIGSERIAL PRIMARY KEY,
    notice_id BIGINT NOT NULL REFERENCES notice(id) ON DELETE CASCADE,
    kind VARCHAR(40) NOT NULL CHECK (
        kind IN ('department', 'grade', 'enrollment_status', 'eligibility')
    ),
    value TEXT NOT NULL,
    source_text TEXT NOT NULL,
    confidence DOUBLE PRECISION CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    ),
    order_idx INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_notice_audience_notice ON notice_audience(notice_id);
CREATE INDEX IF NOT EXISTS idx_notice_audience_kind_value
ON notice_audience(kind, value);

CREATE TABLE IF NOT EXISTS notice_application (
    notice_id BIGINT PRIMARY KEY REFERENCES notice(id) ON DELETE CASCADE,
    method TEXT,
    application_url VARCHAR(1200),
    required_documents TEXT[] NOT NULL DEFAULT '{}',
    contact TEXT,
    location TEXT,
    benefit TEXT,
    evidence JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS notice_asset (
    id BIGSERIAL PRIMARY KEY,
    notice_id BIGINT NOT NULL REFERENCES notice(id) ON DELETE CASCADE,
    kind VARCHAR(30) NOT NULL,
    filename VARCHAR(500),
    source_url VARCHAR(1200) NOT NULL,
    storage_path VARCHAR(1200),
    mime_type VARCHAR(120),
    extracted_text TEXT,
    order_idx INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notice_asset_notice ON notice_asset(notice_id);
CREATE INDEX IF NOT EXISTS idx_notice_asset_kind ON notice_asset(kind);
