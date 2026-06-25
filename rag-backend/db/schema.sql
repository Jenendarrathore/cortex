-- Cortex RAG — canonical schema (source of truth for DDL + indexes).
-- Idempotent: safe to run on every startup and via `make init-db`.
-- The ORM (models/document.py) mirrors these tables for typed queries, but THIS
-- file owns the DDL — especially chunks.fts and the indexes retrieval depends on.

CREATE EXTENSION IF NOT EXISTS vector;

-- ── documents ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_path   TEXT UNIQUE NOT NULL,
    file_hash   TEXT NOT NULL,
    title       TEXT,
    author      TEXT,
    source_url  TEXT,
    category    TEXT,
    tags        TEXT[] DEFAULT '{}',
    doc_date    DATE,
    raw_content TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── chunks ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chunks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    embedding   vector(768),
    chunk_index INTEGER NOT NULL,
    heading     TEXT,
    token_count INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Full-text search vector — generated, always in sync with content.
-- Retrieval's FTS branch (c.fts @@ plainto_tsquery) depends on this column.
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS fts tsvector
    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;

-- ── indexes ──────────────────────────────────────────────────────────────────
-- Vector ANN: cosine ops to match the `<=>` / `1 - distance` used in query.py.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_chunks_fts         ON chunks USING gin (fts);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks (document_id);

CREATE INDEX IF NOT EXISTS idx_documents_tags       ON documents USING gin (tags);
CREATE INDEX IF NOT EXISTS idx_documents_category   ON documents (category);
CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents (updated_at DESC);

-- ── ingestion_jobs ───────────────────────────────────────────────────────────
-- The kind/status/level CHECK values below are mirrored by the StrEnums in
-- rag-backend/core/enums.py (JobKind/JobStatus/LogLevel). Change both together.
-- Postgres-backed job queue. Worker polls for status='queued', processes, updates.
-- SINGLE PROCESS WARNING: worker is intentionally started once in lifespan.
-- With uvicorn --workers N or multiple replicas, N workers will all drain the
-- queue → double-processing. Fix: isolate worker process or add FOR UPDATE SKIP LOCKED.
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind        TEXT NOT NULL CHECK (kind IN ('file', 'folder', 'text')),
    status      TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    payload     JSONB NOT NULL DEFAULT '{}',
    total       INTEGER NOT NULL DEFAULT 0,
    processed   INTEGER NOT NULL DEFAULT 0,
    added       INTEGER NOT NULL DEFAULT 0,
    updated     INTEGER NOT NULL DEFAULT 0,
    skipped     INTEGER NOT NULL DEFAULT 0,
    errors      INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    result      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS result JSONB;

CREATE INDEX IF NOT EXISTS idx_jobs_status     ON ingestion_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON ingestion_jobs (created_at DESC);

-- ── job_logs ─────────────────────────────────────────────────────────────────
-- Per-file audit trail for each ingestion job. Replaces print(stderr).
CREATE TABLE IF NOT EXISTS job_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id      UUID NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
    level       TEXT NOT NULL DEFAULT 'info' CHECK (level IN ('info', 'warn', 'error')),
    message     TEXT NOT NULL,
    file        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_job_logs_job_id ON job_logs (job_id, created_at);

-- ── search_logs ──────────────────────────────────────────────────────────────
-- Written post-response via BackgroundTask — never adds latency to searches.
CREATE TABLE IF NOT EXISTS search_logs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id     UUID,
    query          TEXT NOT NULL,       -- the retrieval query that hit search (may be agent-rewritten)
    user_query     TEXT,                -- the verbatim user question, when the agent supplies it
    filters        JSONB,
    result_count   INTEGER NOT NULL DEFAULT 0,
    latency_ms     INTEGER,
    top_chunk_ids  UUID[],
    reranked       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_search_logs_created_at ON search_logs (created_at DESC);
-- Group all searches from one client session (e.g. one MCP conversation) to
-- audit multi-call reasoning ("was retrieve called twice for this question?").
CREATE INDEX IF NOT EXISTS idx_search_logs_session_id ON search_logs (session_id);
