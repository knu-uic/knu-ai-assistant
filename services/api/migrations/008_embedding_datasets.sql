-- Model-specific embedding datasets. Vectors no longer share one fixed
-- dimension, so complete datasets can be retained and activated independently.
CREATE TABLE IF NOT EXISTS embedding_dataset (
    id BIGSERIAL PRIMARY KEY,
    provider VARCHAR(40) NOT NULL,
    model VARCHAR(255) NOT NULL,
    dimension INT NOT NULL CHECK (dimension > 0 AND dimension <= 4096),
    base_url VARCHAR(1000) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'ready'
        CHECK (status IN ('ready', 'building', 'stale', 'failed')),
    completed_notices INT NOT NULL DEFAULT 0,
    total_notices INT NOT NULL DEFAULT 0,
    total_chunks INT NOT NULL DEFAULT 0,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    last_synced_at TIMESTAMPTZ,
    UNIQUE(provider, model, dimension, base_url)
);

DO $$
DECLARE
    dataset RECORD;
BEGIN
    IF to_regclass('public.notice_chunk') IS NULL THEN
        RETURN;
    END IF;

    -- A typeless vector column can contain datasets with different dimensions.
    DROP INDEX IF EXISTS idx_notice_chunk_embedding;
    ALTER TABLE notice_chunk ALTER COLUMN embedding TYPE vector USING embedding::vector;
    ALTER TABLE notice_chunk ADD COLUMN IF NOT EXISTS embedding_dataset_id BIGINT;

    FOR dataset IN
        SELECT embedding_provider AS provider,
               embedding_model AS model,
               embedding_dimension AS dimension,
               count(DISTINCT notice_id)::int AS completed_notices,
               count(*)::int AS total_chunks
        FROM notice_chunk
        GROUP BY embedding_provider, embedding_model, embedding_dimension
    LOOP
        INSERT INTO embedding_dataset (
            provider, model, dimension, base_url, status,
            completed_notices, total_notices, total_chunks,
            completed_at, last_synced_at
        ) VALUES (
            dataset.provider, dataset.model, dataset.dimension,
            CASE WHEN dataset.provider = 'ollama' THEN 'http://127.0.0.1:11434/v1'
                 WHEN dataset.provider = 'lmstudio' THEN 'http://127.0.0.1:1234/v1'
                 ELSE '' END,
            'ready', dataset.completed_notices, dataset.completed_notices,
            dataset.total_chunks, now(), now()
        )
        ON CONFLICT (provider, model, dimension, base_url) DO UPDATE SET
            completed_notices = EXCLUDED.completed_notices,
            total_notices = EXCLUDED.total_notices,
            total_chunks = EXCLUDED.total_chunks,
            status = 'ready',
            updated_at = now();
    END LOOP;

    UPDATE notice_chunk nc
    SET embedding_dataset_id = ed.id
    FROM embedding_dataset ed
    WHERE nc.embedding_dataset_id IS NULL
      AND ed.provider = nc.embedding_provider
      AND ed.model = nc.embedding_model
      AND ed.dimension = nc.embedding_dimension;

    ALTER TABLE notice_chunk ALTER COLUMN embedding_dataset_id SET NOT NULL;
    ALTER TABLE notice_chunk
        ADD CONSTRAINT notice_chunk_embedding_dataset_fk
        FOREIGN KEY (embedding_dataset_id) REFERENCES embedding_dataset(id) ON DELETE CASCADE;
    ALTER TABLE notice_chunk DROP CONSTRAINT IF EXISTS notice_chunk_notice_model_chunk_key;
    ALTER TABLE notice_chunk DROP CONSTRAINT IF EXISTS notice_chunk_notice_id_chunk_idx_key;
    ALTER TABLE notice_chunk
        ADD CONSTRAINT notice_chunk_dataset_notice_chunk_key
        UNIQUE (embedding_dataset_id, notice_id, chunk_idx);
END $$;

CREATE INDEX IF NOT EXISTS idx_notice_chunk_dataset_notice
ON notice_chunk(embedding_dataset_id, notice_id);

