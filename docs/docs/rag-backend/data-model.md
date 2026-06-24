---
sidebar_position: 3
---

# Data Model

This page describes the five database tables in Cortex RAG — `documents`, `chunks`, `ingestion_jobs`, `job_logs`, and `search_logs` — along with their relationships, indexes, and the automatic deduplication mechanism. The schema is defined in `rag-backend/db/schema.sql` and applied idempotently on backend startup.

---

## Entity Relationship

```
documents (1) ──────< chunks (many)
  id (PK)                document_id (FK → documents.id, ON DELETE CASCADE)

ingestion_jobs (1) ─────< job_logs (many)
  id (PK)                  job_id (FK → ingestion_jobs.id, ON DELETE CASCADE)

search_logs (independent — no FK relationships)
```

A `Document` has zero or more `Chunk` records. Deleting a document cascades to all of its chunks at both the database level (`ON DELETE CASCADE`) and the ORM level (`cascade="all, delete-orphan"`).

An `IngestionJob` has zero or more `JobLog` records written by the worker as it processes files. Deleting a job cascades to all of its log rows.

`search_logs` records every search query independently for telemetry and has no foreign key relationships.

---

## Document

**Table:** `documents`  
**ORM model:** [rag-backend/models/document.py](../../../rag-backend/models/document.py) — `Document`  
**Pydantic schemas:** `DocumentResponse`, `DocumentDetail`

### Fields

| Field | DB Type | Python Type | Nullable | Description |
|---|---|---|---|---|
| `id` | `uuid` | `UUID` | No | Primary key, auto-generated via `uuid4`. |
| `file_path` | `text` | `str` | No | Logical path of the source file (e.g. `notes/setup.md`). Must be **unique** across all documents — this is the deduplication key. |
| `file_hash` | `text` | `str` | No | SHA-256 hex digest of the raw content at ingest time. Used to skip re-ingestion of unchanged files. |
| `title` | `text` | `str \| None` | Yes | Human-readable document title. Taken from metadata at ingest or derived from the filename. |
| `author` | `text` | `str \| None` | Yes | Free-form author name or identifier. |
| `source_url` | `text` | `str \| None` | Yes | Optional origin URL if the document came from the web. |
| `category` | `text` | `str \| None` | Yes | Single-value category label used for equality filtering during search. |
| `tags` | `text[]` | `list[str]` | Yes | Array of free-form tags. Defaults to an empty array. Supports array-containment filtering during search. |
| `doc_date` | `date` | `date \| None` | Yes | Logical date of the document (not the ingest date). Used for date-range filtering. |
| `raw_content` | `text` | `str \| None` | Yes | Full original markdown source. Stored for reference; not used in search. Returned only on the detail endpoint (`GET /documents/{id}`). |
| `created_at` | `timestamptz` | `datetime \| None` | Yes | Set by the database on insert (`server_default=func.now()`). |
| `updated_at` | `timestamptz` | `datetime \| None` | Yes | Set by the database on insert. Updated in application code on re-ingest. |

### Constraints

- `file_path` has a `UNIQUE` constraint. Attempting to ingest a document with a duplicate path triggers the deduplication check rather than a constraint error (see [Deduplication](#deduplication) below).
- `file_hash` and `file_path` are both `NOT NULL`.

---

## Chunk

**Table:** `chunks`  
**ORM model:** [rag-backend/models/document.py](../../../rag-backend/models/document.py) — `Chunk`  
**Pydantic schema:** `ChunkInfo`

Each document is split into chunks by the chunker (`rag-backend/core/chunker.py`), which splits on markdown headings with a maximum of 400 tokens per chunk. Every chunk gets its own 768-dimensional embedding vector produced by the Ollama `nomic-embed-text` model.

### Fields

| Field | DB Type | Python Type | Nullable | Description |
|---|---|---|---|---|
| `id` | `uuid` | `UUID` | No | Primary key, auto-generated via `uuid4`. |
| `document_id` | `uuid` | `UUID` | No | Foreign key → `documents.id`. `ON DELETE CASCADE` ensures chunks are removed when their parent document is deleted. |
| `content` | `text` | `str` | No | The raw text of this chunk. Used in full-text search and returned in search results. |
| `embedding` | `vector(768)` | `list[float]` | Yes | 768-dimensional float vector produced by `nomic-embed-text` via Ollama. The primary artifact for semantic search. |
| `chunk_index` | `integer` | `int` | No | Zero-based position of this chunk within its parent document. Used to reconstruct reading order. |
| `heading` | `text` | `str \| None` | Yes | The nearest markdown heading above this chunk's content, if any. Surfaced in search result cards to give context. |
| `token_count` | `integer` | `int \| None` | Yes | Approximate token count of `content`. Recorded at chunking time; the chunker caps each chunk at 400 tokens. |
| `fts` | `tsvector` | *(not in ORM)* | — | **Generated column** — see below. |
| `created_at` | `timestamptz` | `datetime \| None` | Yes | Set by the database on insert. |

### The `fts` Generated Column

The `fts` column is a PostgreSQL [generated column](https://www.postgresql.org/docs/current/ddl-generated-columns.html) created directly in `db/schema.sql`. It is not declared in the SQLAlchemy ORM model because SQLAlchemy writes never touch it — PostgreSQL maintains it automatically.

```sql
fts tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
```

Whenever `content` is inserted or updated, PostgreSQL re-computes the `tsvector` representation using the `english` text search configuration (stemming, stop-words). The GIN index on `fts` makes full-text queries fast.

---

## IngestionJob

**Table:** `ingestion_jobs`  
**ORM model:** [rag-backend/models/job.py](../../../rag-backend/models/job.py) — `IngestionJob`  
**Pydantic schemas:** `JobResponse`, `JobDetail`, `EnqueueResponse`

One row per enqueued ingest operation. The async worker picks up `queued` rows and updates progress in place.

### Fields

| Field | DB Type | Python Type | Nullable | Description |
|---|---|---|---|---|
| `id` | `uuid` | `UUID` | No | Primary key, auto-generated via `uuid4`. |
| `kind` | `text` | `str` | No | Job type: `'file'`, `'folder'`, or `'text'`. Determines which worker handler runs. Enforced by `CHECK` constraint. |
| `status` | `text` | `str` | No | Lifecycle state: `'queued'` → `'running'` → `'done'` or `'failed'`. Enforced by `CHECK` constraint. Default `'queued'`. |
| `payload` | `jsonb` | `dict` | No | Kind-specific parameters. `file` → `{filename, content_b64}`; `folder` → `{folder_path}`; `text` → `IngestTextRequest` dict. |
| `total` | `integer` | `int` | No | Total number of files to process. Updated by the worker at job start. Default `0`. |
| `processed` | `integer` | `int` | No | Number of files processed so far. Incremented by the worker after each file. Default `0`. |
| `added` | `integer` | `int` | No | Files newly ingested (new document created). Default `0`. |
| `updated` | `integer` | `int` | No | Files re-ingested because content changed. Default `0`. |
| `skipped` | `integer` | `int` | No | Files skipped because content was unchanged (same hash). Default `0`. |
| `errors` | `integer` | `int` | No | Files that failed with an error during processing. Default `0`. |
| `error` | `text` | `str \| None` | Yes | Top-level error message if the job itself failed (e.g. folder path not found). Distinct from per-file errors in `job_logs`. |
| `created_at` | `timestamptz` | `datetime \| None` | Yes | Set by the database on insert. |
| `updated_at` | `timestamptz` | `datetime \| None` | Yes | Updated by the database whenever the row changes (`DEFAULT now()` + `onupdate` in ORM). |

### Job lifecycle

```
enqueue endpoint called
        │
        ▼
 status = 'queued'
        │
        ▼ (worker picks it up, next poll)
 status = 'running'
   total, processed, added/updated/skipped/errors updated per file
   job_logs rows appended
        │
        ▼
 status = 'done'   OR   status = 'failed'  (error field set)
```

On worker startup, any jobs left in `'running'` state from a previous crash are reset to `'queued'` and will be reprocessed from scratch.

---

## JobLog

**Table:** `job_logs`  
**ORM model:** [rag-backend/models/job.py](../../../rag-backend/models/job.py) — `JobLog`  
**Pydantic schema:** `JobLogResponse`

One row per significant event during job processing — one per file processed, per file skipped, per error. The per-job audit trail. Cascades on job delete.

### Fields

| Field | DB Type | Python Type | Nullable | Description |
|---|---|---|---|---|
| `id` | `uuid` | `UUID` | No | Primary key, auto-generated via `uuid4`. |
| `job_id` | `uuid` | `UUID` | No | Foreign key → `ingestion_jobs.id`. `ON DELETE CASCADE`. |
| `level` | `text` | `str` | No | Severity: `'info'`, `'warn'`, or `'error'`. Enforced by `CHECK` constraint. Default `'info'`. |
| `message` | `text` | `str` | No | Human-readable description (e.g. `ingested: docs/setup.md (7 chunks)`). |
| `file` | `text` | `str \| None` | Yes | The specific file being processed when this log entry was written, if applicable. |
| `created_at` | `timestamptz` | `datetime \| None` | Yes | Set by the database on insert. |

---

## SearchLog

**Table:** `search_logs`  
**ORM model:** none (raw SQL insert via `db.execute(text(...))`)  
**Pydantic schema:** none (write-only from the backend's perspective)

One row per search request. Written by a FastAPI `BackgroundTask` after the response is sent — zero latency impact on the caller. Useful for understanding query patterns, latency distribution, zero-result queries, and which content is most retrieved.

### Fields

| Field | DB Type | Python Type | Nullable | Description |
|---|---|---|---|---|
| `id` | `uuid` | `UUID` | No | Primary key, auto-generated via `gen_random_uuid()`. |
| `query` | `text` | `str` | No | The raw query string as submitted by the caller. |
| `filters` | `jsonb` | `dict \| None` | Yes | The filters object from the search request, if any. |
| `result_count` | `integer` | `int` | No | Number of results returned (after reranking and `top_k` truncation). Default `0`. |
| `latency_ms` | `integer` | `int \| None` | Yes | End-to-end search latency in milliseconds (from FastAPI handler entry to result list ready, before background task runs). |
| `top_chunk_ids` | `uuid[]` | `list[UUID] \| None` | Yes | UUIDs of the returned chunks, in result order. Useful for joining back to `chunks` to see what was retrieved. |
| `reranked` | `boolean` | `bool` | No | Whether the cross-encoder reranker ran for this query. Default `false`. |
| `created_at` | `timestamptz` | `datetime \| None` | Yes | Set by the database on insert. |

---

## Indexes

| Index | Type | Column(s) | Purpose |
|---|---|---|---|
| `chunks_embedding_idx` | `ivfflat` (cosine) | `chunks.embedding` | Approximate nearest-neighbor (ANN) vector search. Powers the semantic search leg of the hybrid pipeline. IVFFlat partitions the vector space into lists; cosine distance is the similarity metric used by `nomic-embed-text`. |
| `chunks_fts_idx` | `GIN` | `chunks.fts` | Full-text search via `plainto_tsquery`. GIN indexes are the standard PostgreSQL index type for `tsvector` columns and support fast word-presence queries. |
| `documents_tags_idx` | `GIN` | `documents.tags` | Array containment filtering (`tags @> ARRAY[...]`). GIN indexes natively support PostgreSQL array operators. |
| `documents_category_idx` | `btree` | `documents.category` | Equality filtering on `category` (`category = 'engineering'`). A standard B-tree index is optimal for single-value text equality. |
| `documents_doc_date_idx` | `btree` | `documents.doc_date` | Date-range filtering (`doc_date BETWEEN date_from AND date_to`). B-tree indexes support range scans efficiently. |
| `job_logs_job_id_idx` | `btree` | `job_logs.job_id` | Fast lookup of all log rows for a given job. Used by `GET /jobs/{id}` and `GET /jobs/{id}/logs`. |
| `ingestion_jobs_status_idx` | `btree` | `ingestion_jobs.status` | Crash recovery query on worker startup (`WHERE status = 'running'`). |
| `search_logs_created_at_idx` | `btree` | `search_logs.created_at` | Time-range queries over telemetry (if you build an admin view later). |

---

## Deduplication

When a document is ingested (via file upload, text POST, or folder scan), the backend computes a **SHA-256** hash of the raw content before writing to the database:

1. **New document** (`file_path` not found): insert the document and all its chunks. Record `file_hash`.
2. **Existing document, same hash**: skip. The content has not changed; no work is done.
3. **Existing document, different hash**: delete the old document and all its chunks (cascade), then re-ingest with the new content and a fresh `file_hash`.

This logic lives in `rag-backend/controllers/ingest.py` and means that re-running `make rag` against a folder of markdown files is always safe — unchanged files are skipped in milliseconds, and only modified or new files are re-embedded.

---

## Schema Initialization

The schema is defined in `rag-backend/db/schema.sql` and applied idempotently on backend startup via `init_db()` in `rag-backend/core/database.py`. The file uses `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, and `ADD COLUMN IF NOT EXISTS` throughout — running it against an existing database is safe and leaves existing data untouched.

```bash
# Applied automatically on startup, or run manually:
psql cortex_rag -f rag-backend/db/schema.sql
```

If the backend's database user lacks DDL rights, `init_db()` logs a warning and continues — the tables must then be created by running `db/schema.sql` as a superuser once before starting the backend.

There is no migration framework (e.g. Alembic). To make schema changes, update `db/schema.sql` with idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements and re-run it. For destructive changes (drop column, rename), apply them manually and update the file to match.

The `pgvector` extension must already be installed in PostgreSQL before the backend starts:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

This is handled automatically by the `make mac-setup` / `make linux-setup` targets.
