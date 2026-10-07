-- Chunking is part of an embedding dataset's identity. This permits a new
-- chunk layout to be built alongside the active dataset and switched atomically.
ALTER TABLE embedding_dataset
    ADD COLUMN IF NOT EXISTS chunk_size INT NOT NULL DEFAULT 280,
    ADD COLUMN IF NOT EXISTS chunk_overlap INT NOT NULL DEFAULT 80;

ALTER TABLE embedding_dataset
    DROP CONSTRAINT IF EXISTS embedding_dataset_provider_model_dimension_base_url_key;

ALTER TABLE embedding_dataset
    DROP CONSTRAINT IF EXISTS embedding_dataset_chunk_settings_check;

ALTER TABLE embedding_dataset
    ADD CONSTRAINT embedding_dataset_chunk_settings_check
    CHECK (
        chunk_size >= 64 AND chunk_size <= 4000
        AND chunk_overlap >= 0 AND chunk_overlap < chunk_size
    );

ALTER TABLE embedding_dataset
    ADD CONSTRAINT embedding_dataset_configuration_key
    UNIQUE (provider, model, dimension, base_url, chunk_size, chunk_overlap);
