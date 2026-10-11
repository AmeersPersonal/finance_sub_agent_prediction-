-- Which chunk/instrument pairs the batch job has copied to the Snowflake RAG
-- index, per embedding model. Snowflake only ranks chunk IDs; the chunks,
-- evidence and availability rules stay here. A new embedding model re-syncs.
CREATE TABLE snowflake_synced_chunks (
    chunk_id BIGINT NOT NULL REFERENCES document_chunks(id),
    instrument_id BIGINT NOT NULL REFERENCES instruments(id),
    embedding_model TEXT NOT NULL CHECK (length(trim(embedding_model)) > 0),
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chunk_id, instrument_id, embedding_model)
);
