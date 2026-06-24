---
sidebar_position: 2
---

# Architecture

Cortex RAG is a local Retrieval-Augmented Generation system. All components run on your own machine — no data leaves your network.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                                │
│                                                                     │
│   ┌──────────────────┐              ┌──────────────────────────┐   │
│   │  Claude Desktop  │              │  Admin UI (React/Vite)   │   │
│   │                  │              │       port :5173         │   │
│   └────────┬─────────┘              └────────────┬─────────────┘   │
│            │ stdio (MCP protocol)                │ HTTP/REST        │
└────────────┼────────────────────────────────────┼─────────────────-┘
             │                                    │
┌────────────▼────────────────────────────────────▼──────────────────┐
│                        SERVICE LAYER                                │
│                                                                     │
│   ┌──────────────────┐    HTTP      ┌──────────────────────────┐   │
│   │   MCP Server     │◄────────────►│   RAG Backend (FastAPI)  │   │
│   │   mcp/server.py  │              │       port :8002         │   │
│   └──────────────────┘              │                          │   │
│                                     │  ┌───────────────────┐   │   │
│                                     │  │  ARQ Worker       │   │   │
│                                     │  │  (separate proc)  │   │   │
│                                     │  └───────────────────┘   │   │
│                                     └────────────┬─────────────┘   │
│                                                  │                  │
│                                    ┌─────────────▼─────────────┐   │
│                                    │  Ollama (local inference)  │   │
│                                    │  nomic-embed-text :11434   │   │
│                                    └───────────────────────────-┘   │
└──────────────────────────────────────────────────┬─────────────────┘
                                                   │ SQL + pgvector
┌──────────────────────────────────────────────────▼─────────────────┐
│                         DATA LAYER                                  │
│                                                                     │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │               PostgreSQL 16 + pgvector                       │  │
│   │   documents       (metadata + raw_content)                   │  │
│   │   chunks          (content + embedding vector(768) + fts)    │  │
│   │   ingestion_jobs  (job audit log — status, progress, payload, result)│  │
│   │   job_logs        (per-file audit trail, cascades on delete)       │  │
│   │   search_logs     (query telemetry — latency, result_count)  │  │
│   └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

| Component | Role | Port / Transport |
|---|---|---|
| **RAG Backend** | FastAPI app — job queue, ingestion, search, document management | `:8002` (HTTP) |
| **ARQ Worker** | Standalone process — picks jobs from Redis, processes files, writes result + status back to DB. Run via `make rag-worker` | separate process |
| **MCP Server** | Exposes RAG tools to Claude Desktop via the Model Context Protocol | `stdio` |
| **Admin UI** | Vite + React panel — browse documents, monitor jobs, ingest files, run searches | `:5173` (HTTP) |
| **Redis** | ARQ job queue broker — jobs enqueued here, picked up by ARQ worker | `:6379` (TCP) |
| **PostgreSQL + pgvector** | Stores documents, chunks, job audit log, search telemetry | `:5432` (TCP) |
| **Ollama** | Local inference server — generates `nomic-embed-text` 768-dim embeddings | `:11434` (HTTP) |
| **Docusaurus** | This documentation site | `:3000` (HTTP) |

---

## Data Flow: Ingestion

When you ingest a document (via the Admin UI, MCP tool, or API), the following steps occur:

```
Input source
  │  (file upload, pasted text, folder path, or MCP ingest_document call)
  │
  ▼
┌─────────────────────────┐
│  Ingest Route           │
│  api/routes/documents.py│
│                         │
│  1. INSERT job row into │
│     ingestion_jobs (DB) │
│  2. arq.enqueue_job()   │
│     → push to Redis     │
│  Return 202 + job_id    │
└──────────┬──────────────┘
           │  (async, via Redis)
           ▼
┌─────────────────────────┐
│  ARQ Worker             │
│  workers/arq_worker.py  │
│                         │
│  Picks job from Redis;  │
│  crash-recovers orphaned│
│  'running' rows on      │
│  startup via re-enqueue │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  IngestController /     │
│  FolderIngestService    │
│                         │
│  1. Deduplicate via     │
│     SHA-256 file hash   │
│  2. Persist Document    │
│     row (metadata +     │
│     raw_content)        │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  Chunker                │
│  core/chunker.py        │
│                         │
│  Split on markdown      │
│  headings; max 400      │
│  tokens per chunk       │
│  (bert-base-uncased     │
│  tokenizer); ~50-word   │
│  overlap                │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  Text Normalizer        │
│  core/text_utils.py     │
│                         │
│  strip_markdown()       │
│  strips headings, bold, │
│  links, images;         │
│  stored content stays   │
│  original markdown.     │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  Embedder (async)       │
│  core/embedder.py       │
│                         │
│  async httpx POST       │
│  → Ollama :11434        │
│  Model: nomic-embed-text│
│  Output: vector(768)    │
│  1 retry, then 503      │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  PostgreSQL + pgvector  │
│                         │
│  INSERT INTO chunks     │
│  INSERT INTO job_logs   │
│  UPDATE ingestion_jobs  │
│  (progress + status)    │
│                         │
│  fts column is a        │
│  GENERATED tsvector     │
│  (auto-populated)       │
└─────────────────────────┘
```

**Key detail:** the `fts` column on the `chunks` table is a PostgreSQL `GENERATED` column — you never write to it directly. PostgreSQL recomputes it from `content` on every insert/update, keeping full-text search indexes always in sync with no application-level work.

**Job lifecycle:** `queued → running → done` (or `failed`). On worker startup, any jobs stuck in `running` state (from a prior crash) are re-queued automatically.

---

## Data Flow: Search

```
User query string
  │  (Admin UI Search page, POST /search, or MCP retrieve call)
  │
  ▼
┌──────────────────────────────────┐
│  Step 0 — Normalize query        │
│  core/text_utils.py              │
│  strip_markdown(query)           │
└─────────────────┬────────────────┘
                  │
                  ▼
┌──────────────────────────────────┐
│  Step 1 — Embed query (async)    │
│  Ollama nomic-embed-text         │
│  → 768-dim query vector          │
└─────────────────┬────────────────┘
                  │
        ┌─────────▼──────────┐
        │                    │
        ▼                    ▼
┌───────────────┐    ┌───────────────┐
│  Step 2a      │    │  Step 2b      │
│  Vector search│    │  FTS search   │
│               │    │               │
│  Cosine sim   │    │  plainto_     │
│  on embedding │    │  tsquery on   │
│  (top 50)     │    │  fts col      │
│               │    │  (top 50)     │
│  ivfflat idx  │    │  GIN index    │
│  probes=10    │    │               │
└───────┬───────┘    └───────┬───────┘
        │                    │
        └──────────┬─────────┘
                   ▼
┌──────────────────────────────────┐
│  Step 3 — RRF merge              │
│  Reciprocal Rank Fusion          │
│                                  │
│  score = Σ 1 / (k + rank_i)     │
│  Combines both result lists      │
│  into a single ranked set (top 20│
└──────────────────┬───────────────┘
                   ▼
┌──────────────────────────────────┐
│  Step 4 — Rerank (async thread)  │
│  cross-encoder/                  │
│  ms-marco-MiniLM-L-6-v2          │
│  via anyio.to_thread.run_sync    │
│                                  │
│  Scores each (query, chunk) pair │
│  as a classification problem     │
└──────────────────┬───────────────┘
                   ▼
           Return top_k results
           (default: 5)
           with score, heading,
           document metadata,
           source_url, file_path
                   │
                   ▼  BackgroundTask (post-response)
        INSERT INTO search_logs
        (query, latency_ms, result_count,
         top_chunk_ids, reranked, filters)
```

**Job lifecycle:** `queued → running → done` (or `failed`). Route writes job row to DB and pushes job_id to Redis. ARQ worker picks it up, processes, and writes `result` JSON + final status back to DB. On startup, jobs stuck in `running` are re-queued to Redis automatically.

**Scaling workers:** The worker is always a separate process (`make rag-worker`). For Docker, run it as a separate container pointing at the same Redis and Postgres. To scale throughput, run multiple worker containers — ARQ's Redis-backed queue handles concurrent workers safely.

### Why two retrieval methods?

Vector search excels at semantic similarity — it finds chunks that *mean* the same thing as the query even if they share no words. Full-text search excels at exact keyword recall and handles proper nouns, version numbers, and identifiers that embeddings can smear together. Running both and merging with RRF captures the strengths of each approach at low cost, since both indexes already exist on the `chunks` table.

---

## Database Schema

```sql
-- One row per ingested file
CREATE TABLE documents (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    file_path   text UNIQUE NOT NULL,
    file_hash   text NOT NULL,          -- SHA-256; blocks duplicate ingestion
    title       text,
    author      text,
    source_url  text,
    category    text,
    tags        text[] DEFAULT '{}',
    doc_date    date,
    raw_content text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- One row per chunk derived from a document
CREATE TABLE chunks (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content      text NOT NULL,
    embedding    vector(768),             -- nomic-embed-text output
    chunk_index  int NOT NULL,
    heading      text,                   -- nearest markdown heading above chunk
    token_count  int,
    fts          tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Background job queue — one row per ingest operation
CREATE TABLE ingestion_jobs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind        text NOT NULL CHECK (kind IN ('file', 'folder', 'text')),
    status      text NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'running', 'done', 'failed')),
    payload     jsonb NOT NULL DEFAULT '{}',  -- kind-specific params
    total       int NOT NULL DEFAULT 0,
    processed   int NOT NULL DEFAULT 0,
    added       int NOT NULL DEFAULT 0,
    updated     int NOT NULL DEFAULT 0,
    skipped     int NOT NULL DEFAULT 0,
    errors      int NOT NULL DEFAULT 0,
    error       text,
    result      jsonb,                  -- job output (document_id, chunks, status)
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Per-file audit log for each job
CREATE TABLE job_logs (
    id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id   uuid NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
    level    text NOT NULL DEFAULT 'info' CHECK (level IN ('info', 'warn', 'error')),
    message  text NOT NULL,
    file     text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Search telemetry — written post-response via BackgroundTask
CREATE TABLE search_logs (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    query          text NOT NULL,
    filters        jsonb,
    result_count   int NOT NULL DEFAULT 0,
    latency_ms     int,
    top_chunk_ids  uuid[],
    reranked       boolean NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX ON chunks USING gin (fts);
CREATE INDEX ON chunks (document_id);
CREATE INDEX ON documents USING gin (tags);
CREATE INDEX ON documents (category);
CREATE INDEX ON documents (updated_at DESC);
CREATE INDEX ON ingestion_jobs (status, created_at);
CREATE INDEX ON ingestion_jobs (created_at DESC);
CREATE INDEX ON job_logs (job_id, created_at);
CREATE INDEX ON search_logs (created_at DESC);
```

Schema is applied idempotently on every backend startup from `rag-backend/db/schema.sql`. Run `psql cortex_rag -f rag-backend/db/schema.sql` as a privileged user to apply it manually.

**`ivfflat.probes = 10`** is set on every database connection via a SQLAlchemy event listener in `core/database.py`. This improves ANN recall at a slight cost to query time (the PostgreSQL default of `probes=1` is too low for good recall on typical corpus sizes).

---

## API Reference

| Method | Path | Description | Notes |
|---|---|---|---|
| `GET` | `/health` | Liveness check | |
| `GET` | `/documents/` | List all documents (metadata only) | `skip` and `limit` query params |
| `GET` | `/documents/{id}` | Single document with `raw_content` + `chunks` array | |
| `POST` | `/documents/upload` | Multipart `.md` or `.txt` file upload | Returns `202 {job_id}` |
| `POST` | `/documents/text` | JSON body with `content` + metadata fields | Returns `202 {job_id}` |
| `POST` | `/documents/folder` | Server-side folder ingestion via `folder_path` form field | Returns `202 {job_id}` |
| `DELETE` | `/documents/{id}` | Delete document and all its chunks (cascade) | |
| `POST` | `/search` | Hybrid search — see body schema below | Logs to `search_logs` post-response |
| `GET` | `/jobs/` | List all ingestion jobs newest-first | `skip` / `limit` |
| `GET` | `/jobs/{id}` | Job detail with progress + log entries | |
| `GET` | `/jobs/{id}/logs` | Paginated log rows for a job | |
| `GET` | `/jobs/{id}/stream` | SSE stream of live job progress | `text/event-stream` |

When `API_KEY` is set in `.env`, all routes require the header `X-API-Key: <your-key>`.

**POST /search body:**
```json
{
  "query": "how do I configure pgvector",
  "top_k": 5,
  "rerank": true,
  "filters": {
    "tags": ["postgres", "setup"],
    "category": "infrastructure",
    "date_from": "2024-01-01",
    "date_to": "2025-12-31"
  }
}
```

---

## MCP Tools (Claude Desktop)

The MCP server wraps the RAG backend and exposes three tools to Claude Desktop over `stdio`:

| Tool | Signature | Description |
|---|---|---|
| `ingest_document` | `(content, file_path, title?, category?, tags?, author?, date?, source_url?)` | Ingest a document directly from a Claude Desktop conversation |
| `retrieve` | `(query, top_k?, tags?, category?, date_from?, date_to?)` | Hybrid search with optional filters; returns ranked chunks |
| `list_knowledge_base` | `()` | List all ingested documents with metadata |

**Claude Desktop config** (`~/.claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "cortex": {
      "command": "/path/to/cortex/.cortex_venv/bin/python",
      "args": ["/path/to/cortex/mcp/server.py"],
      "env": {
        "RAG_SERVER_URL": "http://localhost:8002",
        "RAG_API_KEY": ""
      }
    }
  }
}
```

`RAG_API_KEY` is optional — only set it if you have enabled `API_KEY` in `.env`.

---

## Technology Choices

| Technology | Why it was chosen |
|---|---|
| **Ollama + nomic-embed-text** | Runs entirely offline on CPU. No API keys, no egress, no cost per embedding. nomic-embed-text produces high-quality 768-dim vectors competitive with hosted models on retrieval benchmarks. |
| **async httpx for embeddings** | Replaces the sync `ollama` client. Async HTTP calls never block the event loop during ingestion or search. One retry, then fast-fail — local Ollama won't self-heal under retry pressure. |
| **PostgreSQL + pgvector** | No extra infrastructure. Relational storage and approximate nearest-neighbor vector search in one place. The job queue and search telemetry also live here — no separate queue service. |
| **ARQ + Redis job queue** | ARQ is an async-native Python task queue built for asyncio. Redis is the broker — trivial to add to Docker Compose for production. `ingestion_jobs` DB table stays as a durable audit log (payload, result, logs, status) so jobs are inspectable via SQL and the Jobs UI even after Redis forgets them. Crash recovery re-enqueues orphaned `running` DB rows to Redis on startup. |
| **Hybrid search (vector + FTS + RRF)** | Neither vector search nor BM25/FTS alone is best in all cases. RRF fusion is parameter-free and consistently beats either method alone without requiring training data. |
| **cross-encoder reranker** | Bi-encoder vector search is fast but approximate. A cross-encoder sees the full (query, passage) pair and produces a much more accurate relevance score. Running it only on the top-20 candidates keeps latency low. Loaded lazily on first query; load time logged. |
| **anyio.to_thread.run_sync** | The cross-encoder is CPU-bound (PyTorch). Running it in a thread pool via anyio keeps the async event loop unblocked while reranking. |
| **MCP (Model Context Protocol)** | Claude Desktop's native tool-calling protocol. Gives Claude persistent, structured access to the knowledge base without copy-pasting content into the context window. |
| **FastAPI + SQLAlchemy 2.0** | Async-capable, typed, and well-documented. Pydantic v2 integration means request/response validation is handled at the framework level. Lifespan context manager for worker startup/shutdown. |
| **TanStack Query v5** | Eliminates the hand-rolled `loading/error/data` useState triads in the frontend. Auto-refetch on active jobs, cache invalidation on delete, no stale-closure bugs. |
| **React Router v7** | Deep-linkable tabs (`/documents`, `/ingest`, `/search`, `/jobs`). State survives page refresh. |

---

## Hardware Requirements

| Resource | Minimum | Recommended |
|---|---|---|
| RAM | 8 GB | 16 GB |
| Disk | 10 GB free | 20 GB free |
| CPU | Any modern x86\_64 or ARM | Apple Silicon (M-series) |
| GPU | Not required | Speeds up reranker inference; negligible benefit for small corpora |

**Disk breakdown:** PyTorch (~2 GB), Ollama + nomic-embed-text model (~2 GB), Python venv + npm deps (~1–2 GB), PostgreSQL data (scales with corpus size).

Apple Silicon Macs run all components natively — Ollama uses the Metal backend, and PyTorch uses MPS for the reranker.
