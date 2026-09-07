-- Additive migration: existing knowledge_base articles remain untouched.
-- Apply after 001_initial_schema.sql. Safe to reapply.
BEGIN;

CREATE TABLE IF NOT EXISTS knowledge_sources (
    source_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    chunking_version TEXT NOT NULL,
    chunk_size INTEGER NOT NULL CHECK (chunk_size >= 2),
    overlap INTEGER NOT NULL CHECK (overlap >= 0 AND overlap < chunk_size / 2),
    embedding_model TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions = 1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_chunk_provenance (
    chunk_id UUID PRIMARY KEY REFERENCES knowledge_base(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES knowledge_sources(source_id),
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK (end_offset > start_offset),
    UNIQUE (source_id, chunk_index)
);

COMMIT;
