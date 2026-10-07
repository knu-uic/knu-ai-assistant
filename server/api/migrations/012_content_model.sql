-- 012_content_model: 통합 콘텐츠 상위 엔터티와 명시적인 도메인 PK를 도입한다.
-- 기존 데이터와 API 호환성을 유지하기 위해 이전 컬럼/테이블 이름은 생성 컬럼과
-- 단순 뷰로 제공한다. 새 SQL은 *_id와 content 계열 이름을 사용해야 한다.

ALTER TABLE source RENAME COLUMN id TO source_id;
ALTER TABLE source
    ADD COLUMN id BIGINT GENERATED ALWAYS AS (source_id) STORED UNIQUE;

ALTER TABLE notice RENAME TO content;
ALTER TABLE content RENAME COLUMN id TO content_id;
ALTER TABLE content
    ADD COLUMN id BIGINT GENERATED ALWAYS AS (content_id) STORED UNIQUE,
    ADD COLUMN content_type VARCHAR(20);

UPDATE content c
SET content_type = s.kind
FROM source s
WHERE s.source_id = c.source_id;

ALTER TABLE content
    ALTER COLUMN content_type SET NOT NULL,
    ADD CONSTRAINT content_type_check CHECK (content_type IN ('notice', 'academic'));

CREATE INDEX idx_content_type_posted ON content(content_type, posted_at DESC);

CREATE OR REPLACE FUNCTION sync_content_type() RETURNS trigger AS $$
BEGIN
    SELECT kind INTO NEW.content_type FROM public.source WHERE source_id = NEW.source_id;
    IF NEW.content_type IS NULL THEN
        RAISE EXCEPTION 'unknown content source: %', NEW.source_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_content_type
BEFORE INSERT OR UPDATE OF source_id ON content
FOR EACH ROW EXECUTE FUNCTION sync_content_type();

CREATE TABLE notice (
    notice_id BIGINT PRIMARY KEY REFERENCES content(content_id) ON DELETE CASCADE
);

CREATE TABLE academic_document (
    academic_document_id BIGINT PRIMARY KEY REFERENCES content(content_id) ON DELETE CASCADE,
    document_kind VARCHAR(40) NOT NULL DEFAULT 'general'
);

INSERT INTO notice(notice_id)
SELECT content_id FROM content WHERE content_type = 'notice';

INSERT INTO academic_document(academic_document_id)
SELECT content_id FROM content WHERE content_type = 'academic';

CREATE OR REPLACE FUNCTION sync_content_subtype() RETURNS trigger AS $$
BEGIN
    DELETE FROM public.notice WHERE notice_id = NEW.content_id;
    DELETE FROM public.academic_document WHERE academic_document_id = NEW.content_id;
    IF NEW.content_type = 'academic' THEN
        INSERT INTO public.academic_document(academic_document_id)
        VALUES (NEW.content_id);
    ELSE
        INSERT INTO public.notice(notice_id) VALUES (NEW.content_id);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_content_subtype
AFTER INSERT OR UPDATE OF source_id, content_type ON content
FOR EACH ROW EXECUTE FUNCTION sync_content_subtype();

ALTER TABLE notice_period RENAME COLUMN id TO period_id;
ALTER TABLE notice_period
    ADD COLUMN id BIGINT GENERATED ALWAYS AS (period_id) STORED UNIQUE;

ALTER TABLE notice_audience RENAME TO notice_target;
ALTER TABLE notice_target RENAME COLUMN id TO target_id;
ALTER TABLE notice_target
    ADD COLUMN id BIGINT GENERATED ALWAYS AS (target_id) STORED UNIQUE;

CREATE VIEW notice_audience AS
SELECT target_id AS id, notice_id, kind, value, source_text, confidence, order_idx
FROM notice_target;

ALTER TABLE notice_asset RENAME TO content_asset;
ALTER TABLE content_asset RENAME COLUMN id TO asset_id;
ALTER TABLE content_asset RENAME COLUMN notice_id TO content_id;
ALTER TABLE content_asset
    ADD COLUMN id BIGINT GENERATED ALWAYS AS (asset_id) STORED UNIQUE;

CREATE VIEW notice_asset AS
SELECT asset_id AS id, content_id AS notice_id, kind, filename, source_url,
       storage_path, mime_type, extracted_text, order_idx, created_at, extra
FROM content_asset;

ALTER TABLE embedding_dataset RENAME COLUMN id TO embedding_dataset_id;
ALTER TABLE embedding_dataset
    ADD COLUMN id BIGINT GENERATED ALWAYS AS (embedding_dataset_id) STORED UNIQUE;

DO $$
BEGIN
    IF to_regclass('public.notice_chunk') IS NOT NULL THEN
        ALTER TABLE notice_chunk RENAME TO content_chunk;
        ALTER TABLE content_chunk RENAME COLUMN id TO chunk_id;
        ALTER TABLE content_chunk RENAME COLUMN notice_id TO content_id;
        ALTER TABLE content_chunk
            ADD COLUMN id BIGINT GENERATED ALWAYS AS (chunk_id) STORED UNIQUE;

        EXECUTE $view$
            CREATE VIEW notice_chunk AS
            SELECT chunk_id AS id, content_id AS notice_id, chunk_idx, content,
                   chunk_type, attachment_name, embedding, embedding_provider,
                   embedding_model, embedding_dimension, embedding_dataset_id,
                   created_at
            FROM content_chunk
        $view$;
    END IF;
END $$;

CREATE TABLE category (
    category_id BIGSERIAL PRIMARY KEY,
    name VARCHAR(20) UNIQUE NOT NULL
);

INSERT INTO category(name) VALUES
    ('장학'), ('수강'), ('취업(진로)'), ('행사(공모전)'), ('일반(기타)')
ON CONFLICT (name) DO NOTHING;

ALTER TABLE content ADD COLUMN category_id BIGINT REFERENCES category(category_id);
UPDATE content c
SET category_id = category.category_id
FROM category
WHERE category.name = c.category;
ALTER TABLE content ALTER COLUMN category_id SET NOT NULL;
CREATE INDEX idx_content_category_id_posted ON content(category_id, posted_at DESC);

CREATE OR REPLACE FUNCTION sync_content_category() RETURNS trigger AS $$
BEGIN
    SELECT category_id INTO NEW.category_id FROM category WHERE name = NEW.category;
    IF NEW.category_id IS NULL THEN
        RAISE EXCEPTION 'unknown content category: %', NEW.category;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_content_category
BEFORE INSERT OR UPDATE OF category ON content
FOR EACH ROW EXECUTE FUNCTION sync_content_category();

CREATE TABLE topic (
    topic_id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE content_topic (
    content_id BIGINT NOT NULL REFERENCES content(content_id) ON DELETE CASCADE,
    topic_id BIGINT NOT NULL REFERENCES topic(topic_id) ON DELETE CASCADE,
    PRIMARY KEY (content_id, topic_id)
);

INSERT INTO topic(name)
SELECT DISTINCT value
FROM content CROSS JOIN LATERAL unnest(topics) AS value
WHERE btrim(value) <> ''
ON CONFLICT (name) DO NOTHING;

INSERT INTO content_topic(content_id, topic_id)
SELECT c.content_id, t.topic_id
FROM content c
CROSS JOIN LATERAL unnest(c.topics) AS value
JOIN topic t ON t.name = value
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION sync_content_topics() RETURNS trigger AS $$
BEGIN
    DELETE FROM content_topic WHERE content_id = NEW.content_id;
    INSERT INTO topic(name)
    SELECT DISTINCT value FROM unnest(NEW.topics) AS value
    WHERE btrim(value) <> ''
    ON CONFLICT (name) DO NOTHING;
    INSERT INTO content_topic(content_id, topic_id)
    SELECT NEW.content_id, topic_id
    FROM topic
    WHERE name = ANY(NEW.topics)
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_content_topics
AFTER INSERT OR UPDATE OF topics ON content
FOR EACH ROW EXECUTE FUNCTION sync_content_topics();
