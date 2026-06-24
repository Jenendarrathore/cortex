---
sidebar_position: 1
---

# rag-backend Overview

`rag-backend` is the Python API service at the heart of Cortex RAG. It exposes a REST API for ingesting markdown and text documents as background jobs, storing them as vector embeddings in PostgreSQL, and running hybrid semantic + full-text search with reranking. It is built on **FastAPI**, **SQLAlchemy 2.0**, and **pgvector**, following a conventional MVC layout.

---

## Directory structure

```
rag-backend/
├── db/
│   └── schema.sql          # canonical DDL — source of truth for all tables and indexes
├── core/
│   ├── config.py           # pydantic-settings Settings; reads .env
│   ├── database.py         # SQLAlchemy engine, SessionLocal, Base, get_db; sets ivfflat.probes=10
│   ├── embedder.py         # async httpx → Ollama nomic-embed-text → 768-dim float vectors; 1 retry
│   ├── chunker.py          # splits markdown on headings, max 400 tokens, ~50-word overlap
│   ├── reranker.py         # cross-encoder/ms-marco-MiniLM-L-6-v2; lazy load; anyio thread offload
│   ├── text_utils.py       # strip_markdown() and count_tokens() utilities
│   ├── logging.py          # configure_logging() (once) + get_logger(name)
│   ├── exceptions.py       # RagError, DocumentNotFound (404), IngestError (400), UpstreamError (503)
│   └── auth.py             # require_api_key FastAPI dependency (optional X-API-Key auth)
├── models/
│   ├── document.py         # SQLAlchemy ORM: Document, Chunk
│   └── job.py              # SQLAlchemy ORM: IngestionJob, JobLog
├── schemas/
│   ├── document.py         # Pydantic v2: DocumentResponse, SearchRequest, IngestResponse, etc.
│   └── job.py              # Pydantic v2: JobResponse, JobDetail, JobLogResponse, EnqueueResponse
├── controllers/
│   ├── ingest.py           # IngestController: list, ingest_text, ingest_file, get, delete
│   ├── folder_ingest.py    # FolderIngestService: single walk/stats/log impl; callback-based progress
│   ├── worker.py           # async worker loop: crash recovery, poll ingestion_jobs, process jobs
│   └── query.py            # QueryController: _vector_search, _fts_search, _fuse, _fetch, rerank
└── api/
    ├── server.py            # FastAPI app: lifespan (schema + Ollama check + worker task), CORS, exception handlers
    └── routes/
        ├── documents.py     # /documents/* endpoints (all ingest → 202 + job_id)
        ├── search.py        # POST /search with BackgroundTask search telemetry
        └── jobs.py          # /jobs/* endpoints (list, detail, logs, SSE stream)
```

### core/

Shared infrastructure that every other layer imports from.

| File | Responsibility |
|---|---|
| `config.py` | Reads `.env` via `pydantic-settings`. Single `Settings` singleton gives typed access to `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `API_KEY`, `ollama_timeout`, `embed_max_retries`, `log_level`, `cors_origins`, and search tuning parameters. |
| `database.py` | Creates the SQLAlchemy `Engine` (psycopg3 driver), exposes `SessionLocal` and `get_db` as a FastAPI dependency, holds `Base` for all ORM models, reads `db/schema.sql` on startup via `init_db()`, and sets `ivfflat.probes = 10` on every connection via a SQLAlchemy event listener for better ANN recall. |
| `embedder.py` | Async httpx wrapper around the Ollama HTTP API. Sends text to the local `nomic-embed-text` model and returns a 768-dimensional float list. One retry then `UpstreamError` (503) — local Ollama won't self-heal under retry pressure. |
| `chunker.py` | Markdown-aware splitter (see [Chunking strategy](#chunking-strategy) below). |
| `reranker.py` | Loads `cross-encoder/ms-marco-MiniLM-L-6-v2` lazily on first search call (logs load time). Exposes `rerank_async(query, candidates, top_k)` which runs the CPU-bound cross-encoder in a thread via `anyio.to_thread.run_sync`, keeping the async event loop unblocked. |
| `text_utils.py` | `strip_markdown(text)` — strips headings, bold, links (keeps text), images; keeps code block content. Used before embedding to improve vector quality. `count_tokens(text)` — accurate token count using the `bert-base-uncased` tokenizer. |
| `logging.py` | `configure_logging(level)` sets up structured logging once at startup. `get_logger(name)` returns a named logger. Replaces all `print(..., file=sys.stderr)` with structured log records. |
| `exceptions.py` | Small exception hierarchy: `RagError` (500) → `DocumentNotFound` (404), `IngestError` (400), `UpstreamError` (503). A FastAPI exception handler in `server.py` maps these to clean `{error, detail}` JSON responses. |
| `auth.py` | `require_api_key` FastAPI dependency. When `API_KEY` is set in `.env`, this dependency is applied globally to the app and rejects requests missing the correct `X-API-Key` header. When `API_KEY` is empty (default), auth is disabled. |

### models/

SQLAlchemy ORM definitions. Four tables across two files:

- **`Document`** (`models/document.py`) — one row per ingested file. Stores metadata plus `raw_content` and `file_hash` for deduplication.
- **`Chunk`** (`models/document.py`) — one row per chunk produced from a document. Stores the chunk `content`, the pgvector `embedding` column (`vector(768)`), and the generated `fts` tsvector column.
- **`IngestionJob`** (`models/job.py`) — one row per enqueued ingest operation. Tracks `kind` (file/folder/text), `status` (queued/running/done/failed), `payload` (JSONB, kind-specific params), and progress counters.
- **`JobLog`** (`models/job.py`) — one row per file processed. Per-job audit trail written by the worker. Cascades on job delete.

### schemas/

Pydantic v2 models defining the exact JSON shapes accepted and returned by the API.

| Schema | Used by |
|---|---|
| `DocumentResponse` | `GET /documents/` list |
| `DocumentDetail` | `GET /documents/{id}` |
| `IngestTextRequest` | `POST /documents/text` request body |
| `EnqueueResponse` | All ingest endpoint responses (`{job_id, status}`) |
| `SearchRequest` | `POST /search` request body |
| `SearchResponse` | `POST /search` response |
| `JobResponse` | `GET /jobs/` list items |
| `JobDetail` | `GET /jobs/{id}` (includes `logs` array) |
| `JobLogResponse` | `GET /jobs/{id}/logs` items |

### controllers/

Business logic, decoupled from HTTP routing.

- **`IngestController`** (`ingest.py`) handles document write paths: parsing a raw text payload, reading an uploaded file (`.md` or `.txt`), deduplication, chunking, embedding, and storage. Also handles `get_document` and `delete_document`.
- **`FolderIngestService`** (`folder_ingest.py`) walks a server-side folder recursively. Single implementation shared by both folder job processing (via the worker) and any future direct routes. Accepts an optional `on_event` async callback for progress updates — the worker uses this to write `job_logs` rows and update counters.
- **`process_job`** (`controllers/worker.py`) is the core job processor — called by the ARQ worker task. Handles all three job kinds (`file`, `text`, `folder`), writes `result` JSON and final status back to `ingestion_jobs`, and writes per-file rows to `job_logs`. The ARQ worker (`workers/arq_worker.py`) wraps this in an ARQ task function (`ingest_job`) and adds crash recovery via `on_startup` (re-queues any `running` DB rows on worker boot). Run via `make rag-worker`.
- **`QueryController`** (`query.py`) owns the full search pipeline, decomposed into `_vector_search`, `_fts_search`, `_reciprocal_rank_fusion`, and `_fetch_candidates`. The top-level `search()` method is 10 lines.

### api/

FastAPI application and route definitions.

- `server.py` instantiates the `FastAPI` app, registers CORS middleware, applies `require_api_key` globally when `API_KEY` is set, registers a `RagError` exception handler, mounts the three routers, and manages the ARQ Redis pool in a `lifespan` context manager (creates pool on entry, closes on exit). Schema is applied idempotently on startup via `init_db()`. The worker is a separate process — the API only holds an ARQ pool for enqueueing.
- `routes/documents.py`, `routes/search.py`, `routes/jobs.py` are thin — they parse HTTP input, call a controller method or helper, and return a schema. No business logic lives here.

---

## Starting the backend

From the `cortex/` root directory:

```bash
make rag
```

This runs the equivalent of:

```bash
cd rag-backend && uvicorn api.server:app --host 0.0.0.0 --port 8002 --reload
```

The `cd rag-backend` is required because the source files use flat (non-package) imports (`from core.config import settings`). Running uvicorn from the repo root would make those imports fail.

The server starts on **http://localhost:8002**. Interactive API docs are available at http://localhost:8002/docs (Swagger UI) and http://localhost:8002/redoc.

On startup the server:
1. Applies `db/schema.sql` idempotently (warns and continues if the DB user lacks DDL rights — run `psql cortex_rag -f db/schema.sql` as an admin user in that case)
2. Checks Ollama reachability (warn only — never blocks startup)
3. Starts the background ingestion worker task; re-queues any orphaned `running` jobs

---

## Search pipeline

`POST /search` with body `{query, top_k, rerank, filters}` triggers the following pipeline inside `QueryController`:

### Step 0 — Query normalization

Before embedding, the query string is passed through `strip_markdown()` from `core/text_utils.py`. This removes any markdown syntax from the query so it is represented in the same plain-text space as the stripped chunk embeddings.

### Step 1 — Query embedding (async)

The normalized query string is sent to Ollama's local `nomic-embed-text` model via `core/embedder.py` using async httpx. The result is a 768-dimensional float vector. One retry on failure, then `UpstreamError` (503).

### Step 2 — Vector search (cosine similarity, top 50)

An IVFFlat index on `chunks.embedding` (cosine operator class) enables approximate nearest-neighbor search. `ivfflat.probes = 10` is set on the connection for better recall. Any active filters (`tags`, `category`, `date_from`, `date_to`) are applied as SQL `WHERE` clauses joined to the parent `documents` row.

### Step 3 — Full-text search (plainto_tsquery, top 50)

A standard PostgreSQL full-text search runs against the GIN-indexed `chunks.fts` tsvector column using `plainto_tsquery`. The same metadata filters apply. The top 50 FTS matches are collected.

### Step 4 — RRF merge

The two ranked lists are merged with **Reciprocal Rank Fusion** (`k = 60`). Chunks appearing in both lists receive a boosted combined score. The merged list is sorted descending and the top 20 candidates are forwarded to the reranker.

### Step 5 — Reranking (cross-encoder, via thread)

The cross-encoder model `cross-encoder/ms-marco-MiniLM-L-6-v2` is loaded lazily on first search call (load time logged). It scores each of the top-20 `(query, chunk_content)` pairs jointly. Runs via `anyio.to_thread.run_sync` so it never blocks the async event loop. Skipped if `rerank: false`.

### Step 6 — Return top_k + telemetry

The final sorted list is truncated to `top_k` (default 5) and returned. After the response is sent, a FastAPI `BackgroundTask` inserts a row into `search_logs` with the query, filters, latency, result count, top chunk IDs, and whether reranking was used.

---

## Chunking strategy

`core/chunker.py` splits ingested markdown into chunks before embedding:

- **Split on headings** — the text is first divided at every ATX heading (`#`, `##`, `###`, …). Each heading and its body become a candidate chunk.
- **Max 400 tokens** — if a section exceeds 400 tokens it is sub-split further using `_split_long()`, which uses a sliding word-window with real tokenizer checks (HuggingFace `bert-base-uncased` tokenizer) to count tokens accurately.
- **~50-word overlap** — adjacent chunks share approximately 50 words of overlap so that a sentence spanning a chunk boundary appears in both chunks.
- **Heading stored separately** — each chunk records the heading it was extracted from. The heading is prepended to the chunk text at embed time (improving retrieval) and returned in search results.

---

## Markdown normalization

`core/text_utils.py` provides `strip_markdown(text)`, applied to chunk text **before** sending to Ollama:

- Heading markers (`#`, `##`, etc.) are stripped (text is kept)
- Bold/italic markers (`**`, `*`, `_`) are stripped
- Links `[text](url)` → `text` (URL is dropped)
- Images `![alt](url)` are dropped entirely
- Code block fences are stripped but the code content is kept
- Inline code backticks are stripped

The **stored `content`** field in the `chunks` table always contains the original markdown — `strip_markdown` only affects what is sent to the embedder.

---

## File format support

| Format | Frontmatter parsing | Title fallback |
|--------|--------------------|----|
| `.md` | Yes — YAML frontmatter block parsed for `title`, `author`, `category`, `tags`, `date`, `source` | Filename (without extension) |
| `.txt` | No — entire file treated as body | Filename (without extension) |

Both formats go through the same chunker, text normalizer, embedder, and storage pipeline.

---

## Design decisions

### Async embeddings via httpx

The original `ollama` Python client uses blocking HTTP. Replaced with direct async `httpx.AsyncClient` calls to `POST /api/embed`. This means embedding during ingestion (in the worker) and at search time both run without blocking the event loop. One retry then fast-fail: a dead local Ollama won't recover under retry pressure.

### Lazy reranker with load-time logging

The cross-encoder model (~85 MB) is loaded on first use, not at startup. Load time is logged via `time.perf_counter()`. On this machine first-load takes ~8.7 seconds. Loading at startup would delay the server's readiness; lazy loading pushes this cost to the first search request only.

### ARQ + Redis job queue

Jobs are enqueued to Redis via ARQ (`arq.enqueue_job`). The worker is a **separate process** (`make rag-worker` / `python -m arq workers.arq_worker.WorkerSettings`), completely decoupled from the API. Multiple worker processes can safely drain the same Redis queue without duplicate processing — ARQ's Redis-backed locking handles concurrent workers. The `ingestion_jobs` DB table serves as the durable audit log (payload, result, per-file logs, final status).

### Crash recovery

On worker startup (`on_startup` hook): `UPDATE ingestion_jobs SET status='queued' WHERE status='running'` — any jobs interrupted mid-flight are reset and re-enqueued to Redis. ARQ's `job_timeout` (600 s) provides a second safety net for jobs that hang.

### Small exception hierarchy

`RagError` (base, 500) with three subclasses: `DocumentNotFound` (404), `IngestError` (400), `UpstreamError` (503). The FastAPI exception handler converts these to `{error: "<ClassName>", detail: "<message>"}` JSON. No per-cause sub-subclasses — the extra granularity isn't worth the maintenance cost.

### Why SQLAlchemy 2.0?

The 2.0 style `Session` API is explicit about transactions, works synchronously with psycopg3, and handles the `pgvector` column type through the `pgvector-python` extension. The ORM relationship between `Document` and `Chunk` keeps cascade deletes and eager loading declarative rather than manual.

### Why Pydantic v2?

v2 (Rust-backed) is significantly faster than v1 for validation and serialization. The `model_config = ConfigDict(from_attributes=True)` setting allows direct construction from SQLAlchemy ORM objects without manual field mapping.

---

## API reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/documents/` | List all documents (metadata only); supports `skip` / `limit` |
| `GET` | `/documents/{id}` | Single document with `raw_content` and `chunks` array |
| `POST` | `/documents/upload` | Multipart upload of a `.md` or `.txt` file — returns `202 {job_id}` |
| `POST` | `/documents/text` | Ingest raw text with metadata via JSON body — returns `202 {job_id}` |
| `POST` | `/documents/folder` | Ingest all `.md` and `.txt` files under a server-side folder path — returns `202 {job_id}` |
| `DELETE` | `/documents/{id}` | Delete document and all its chunks (cascades in DB) |
| `POST` | `/search` | Hybrid search with optional reranking and metadata filters; logs telemetry post-response |
| `GET` | `/jobs/` | List all ingestion jobs (newest first); `skip` / `limit` |
| `GET` | `/jobs/{id}` | Job detail with progress counters and full `logs` array |
| `GET` | `/jobs/{id}/logs` | Paginated log rows for a job |
| `GET` | `/jobs/{id}/stream` | SSE stream of live job progress (`text/event-stream`) |
