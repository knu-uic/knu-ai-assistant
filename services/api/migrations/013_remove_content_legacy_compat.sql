-- 013_remove_content_legacy_compat: 정규화된 콘텐츠 모델을 유일한 저장 구조로 만든다.
-- 012에서 이전 코드의 점진적 전환을 위해 남긴 생성 컬럼, 호환 뷰, 비정규화
-- category/topics 컬럼을 제거한다. 이 마이그레이션 이후 모든 코드는 명시적인
-- 도메인 PK와 category/content_topic 관계를 사용해야 한다.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM notice_period p
        LEFT JOIN notice n ON n.notice_id = p.notice_id
        WHERE n.notice_id IS NULL
    ) OR EXISTS (
        SELECT 1
        FROM notice_target t
        LEFT JOIN notice n ON n.notice_id = t.notice_id
        WHERE n.notice_id IS NULL
    ) OR EXISTS (
        SELECT 1
        FROM notice_application a
        LEFT JOIN notice n ON n.notice_id = a.notice_id
        WHERE n.notice_id IS NULL
    ) THEN
        RAISE EXCEPTION 'notice metadata exists for non-notice content';
    END IF;
END $$;

ALTER TABLE notice_period
    DROP CONSTRAINT IF EXISTS notice_period_notice_id_fkey,
    ADD CONSTRAINT notice_period_notice_id_fkey
        FOREIGN KEY (notice_id) REFERENCES notice(notice_id) ON DELETE CASCADE;

ALTER TABLE notice_target
    DROP CONSTRAINT IF EXISTS notice_audience_notice_id_fkey,
    DROP CONSTRAINT IF EXISTS notice_target_notice_id_fkey,
    ADD CONSTRAINT notice_target_notice_id_fkey
        FOREIGN KEY (notice_id) REFERENCES notice(notice_id) ON DELETE CASCADE;

ALTER TABLE notice_application
    DROP CONSTRAINT IF EXISTS notice_application_notice_id_fkey,
    ADD CONSTRAINT notice_application_notice_id_fkey
        FOREIGN KEY (notice_id) REFERENCES notice(notice_id) ON DELETE CASCADE;

DROP VIEW IF EXISTS notice_audience;
DROP VIEW IF EXISTS notice_asset;
DROP VIEW IF EXISTS notice_chunk;

DROP TRIGGER IF EXISTS trg_content_category ON content;
DROP TRIGGER IF EXISTS trg_content_topics ON content;
DROP FUNCTION IF EXISTS sync_content_category();
DROP FUNCTION IF EXISTS sync_content_topics();

ALTER TABLE content DROP COLUMN category;
ALTER TABLE content DROP COLUMN topics;

ALTER TABLE source DROP COLUMN id;
ALTER TABLE content DROP COLUMN id;
ALTER TABLE notice_period DROP COLUMN id;
ALTER TABLE notice_target DROP COLUMN id;
ALTER TABLE content_asset DROP COLUMN id;
ALTER TABLE embedding_dataset DROP COLUMN id;

DO $$
BEGIN
    IF to_regclass('public.content_chunk') IS NOT NULL THEN
        ALTER TABLE content_chunk DROP COLUMN id;
    END IF;
END $$;
