-- 010_crawl_checkpoints: 공지별 수집 단계와 UI 진행 목록을 강제 종료 후에도 복원한다.

ALTER TABLE crawl_url_state
    DROP CONSTRAINT IF EXISTS crawl_url_state_status_check;

ALTER TABLE crawl_url_state
    ADD CONSTRAINT crawl_url_state_status_check CHECK (
        status IN ('discovered', 'collecting', 'collected', 'refining', 'completed', 'failed')
    ),
    ADD COLUMN IF NOT EXISTS title TEXT,
    ADD COLUMN IF NOT EXISTS page_number INT,
    ADD COLUMN IF NOT EXISTS stage VARCHAR(80),
    ADD COLUMN IF NOT EXISTS checkpoint JSONB,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS crawl_run_state (
    singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK (singleton),
    snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

