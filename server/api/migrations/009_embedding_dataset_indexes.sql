-- Each index contains one dimension only. Datasets above pgvector's 2,000
-- dimension HNSW limit remain available through exact cosine search.
DO $$
DECLARE
    dataset RECORD;
BEGIN
    FOR dataset IN SELECT id, dimension FROM embedding_dataset WHERE dimension <= 2000
    LOOP
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON notice_chunk USING hnsw '
            '((embedding::vector(%s)) vector_cosine_ops) WHERE embedding_dataset_id = %s',
            'idx_notice_chunk_dataset_' || dataset.id || '_hnsw',
            dataset.dimension,
            dataset.id
        );
    END LOOP;
END $$;
