-- Keep embeddings from multiple models side by side so a replacement can be
-- built completely before search switches to it.
DO $$
BEGIN
    IF to_regclass('public.notice_chunk') IS NOT NULL THEN
        ALTER TABLE notice_chunk
            ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR(40),
            ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(255),
            ADD COLUMN IF NOT EXISTS embedding_dimension INT;

        UPDATE notice_chunk
        SET embedding_provider = COALESCE(embedding_provider, 'ollama'),
            embedding_model = COALESCE(embedding_model, 'bge-m3:latest'),
            embedding_dimension = COALESCE(embedding_dimension, vector_dims(embedding));

        ALTER TABLE notice_chunk
            ALTER COLUMN embedding_provider SET NOT NULL,
            ALTER COLUMN embedding_model SET NOT NULL,
            ALTER COLUMN embedding_dimension SET NOT NULL;

        ALTER TABLE notice_chunk
            DROP CONSTRAINT IF EXISTS notice_chunk_notice_id_chunk_idx_key;
        ALTER TABLE notice_chunk
            ADD CONSTRAINT notice_chunk_notice_model_chunk_key
            UNIQUE (notice_id, embedding_provider, embedding_model, chunk_idx);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_notice_chunk_embedding_model
ON notice_chunk(embedding_provider, embedding_model, notice_id);
