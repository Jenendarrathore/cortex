---
sidebar_position: 2
---

# API Reference

The Cortex RAG backend is a FastAPI application running on `http://localhost:8002`. All endpoints accept and return JSON unless otherwise noted.

An interactive Swagger UI with live try-it-out support is available at **[http://localhost:8002/docs](http://localhost:8002/docs)** whenever the backend is running (`make rag`). The OpenAPI schema is at `http://localhost:8002/openapi.json`.

---

## Base URL

```
http://localhost:8002
```

---

## Authentication

API key authentication is **optional**. It is disabled by default.

To enable it, set `API_KEY` in your `.env` file:

```dotenv
API_KEY=your_secret_key_here
```

When `API_KEY` is set, **all routes** require the following request header:

```
X-API-Key: your_secret_key_here
```

Requests without the header (or with a wrong key) receive `403 Forbidden`.

When `API_KEY` is empty or not set, no authentication is required on any route.

**MCP client:** set `RAG_API_KEY` in the MCP server environment to have the MCP client send the key automatically.

**Frontend:** set `VITE_API_KEY` in `rag-frontend/.env.local` (or leave it empty if auth is disabled).

---

## Health

### `GET /health`

Returns the running status of the backend. Use this to confirm the server is up before making other calls.

**Request**

No parameters.

**Response `200 OK`**

```json
{
  "status": "ok"
}
```

**Notes**
- This endpoint does not check database connectivity. A `200` only means the FastAPI process is alive.

---

## Documents

### `GET /documents/`

Returns metadata for ingested documents. Does not include `raw_content` or `chunks` — use `GET /documents/{id}` for the full record.

**Query parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | `int` | `0` | Number of records to skip (offset for pagination) |
| `limit` | `int` | `100` | Maximum number of records to return |

**Example using curl**

```bash
# First page of 20
curl "http://localhost:8002/documents/?skip=0&limit=20"

# Second page of 20
curl "http://localhost:8002/documents/?skip=20&limit=20"
```

**Response `200 OK`** — array of document objects

```json
[
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "file_path": "sample-docs/architecture.md",
    "file_hash": "a1b2c3d4e5f6...",
    "title": "System Architecture",
    "author": "Jenendar",
    "source_url": null,
    "category": "engineering",
    "tags": ["architecture", "backend"],
    "doc_date": "2024-11-01",
    "created_at": "2024-11-02T10:30:00Z",
    "updated_at": "2024-11-02T10:30:00Z"
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | `uuid` | Unique document identifier |
| `file_path` | `string` | Path used as the document's canonical identifier |
| `file_hash` | `string` | SHA hash of the file content (used to skip re-ingestion of unchanged files) |
| `title` | `string \| null` | Human-readable title |
| `author` | `string \| null` | Document author |
| `source_url` | `string \| null` | Original URL if the document came from the web |
| `category` | `string \| null` | Single category label (used as a search filter) |
| `tags` | `string[]` | List of tags (used as search filters) |
| `doc_date` | `string \| null` | Document date in `YYYY-MM-DD` format |
| `created_at` | `datetime \| null` | When the document was first ingested |
| `updated_at` | `datetime \| null` | When the document was last re-ingested |

**Error cases**

| Status | Cause |
|--------|-------|
| `500` | Database connection failure |

---

### `GET /documents/{id}`

Returns the full document record, including the original markdown (`raw_content`) and all stored chunks.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | `uuid` | Document ID from `GET /documents/` |

**Response `200 OK`**

All fields from `DocumentResponse` (see above), plus:

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "file_path": "sample-docs/architecture.md",
  "file_hash": "a1b2c3d4e5f6...",
  "title": "System Architecture",
  "author": "Jenendar",
  "source_url": null,
  "category": "engineering",
  "tags": ["architecture", "backend"],
  "doc_date": "2024-11-01",
  "created_at": "2024-11-02T10:30:00Z",
  "updated_at": "2024-11-02T10:30:00Z",
  "raw_content": "# System Architecture\n\nThis document describes...",
  "chunks": [
    {
      "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "chunk_index": 0,
      "heading": "System Architecture",
      "content": "This document describes the overall design of the Cortex RAG backend...",
      "token_count": 312
    }
  ]
}
```

**Additional fields**

| Field | Type | Description |
|-------|------|-------------|
| `raw_content` | `string \| null` | Full original content of the document |
| `chunks` | `ChunkInfo[]` | Array of chunks stored in the database |

**ChunkInfo fields**

| Field | Type | Description |
|-------|------|-------------|
| `id` | `uuid` | Chunk identifier |
| `chunk_index` | `int` | Zero-based position of this chunk within the document |
| `heading` | `string \| null` | Heading text that introduced this chunk (from the markdown structure) |
| `content` | `string` | Text content of the chunk (max 400 tokens) |
| `token_count` | `int \| null` | Token count for this chunk (measured with `bert-base-uncased` tokenizer) |

**Error cases**

| Status | Cause |
|--------|-------|
| `404` | No document found with the given ID |
| `500` | Database error |

---

### `POST /documents/upload`

Enqueues a background job to ingest a `.md` or `.txt` file. Returns `202 Accepted` immediately with a `job_id`. The file is base64-encoded in the job payload and processed by the async worker (chunk → embed → store). Track progress via `GET /jobs/{job_id}`.

For `.md` files, YAML frontmatter is parsed for metadata (`title`, `author`, `category`, `tags`, `date`, `source`). For `.txt` files, there is no frontmatter parsing — the entire file is treated as the body and the title is derived from the filename.

**Request**

Content-Type: `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | `file` | Yes | A `.md` or `.txt` file. Any other extension returns `400`. |

**Example using curl**

```bash
curl -X POST http://localhost:8002/documents/upload \
  -F "file=@sample-docs/architecture.md"
```

**Response `202 Accepted`**

```json
{
  "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "queued"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | `uuid` | ID of the created ingestion job. Use with `GET /jobs/{job_id}` to track progress. |
| `status` | `string` | Always `"queued"` — the job has been enqueued but not yet processed. |

**Error cases**

| Status | Cause |
|--------|-------|
| `400` | File is not a `.md` or `.txt` file |
| `500` | Database error enqueueing the job |

---

### `POST /documents/text`

Enqueues a background job to ingest a document supplied as a JSON body. Returns `202 Accepted` immediately with a `job_id`. Useful for programmatic ingestion from scripts or other tools, and for documents that do not exist as files on disk.

**Request**

Content-Type: `application/json`

```json
{
  "content": "# My Document\n\nThis is the full markdown content...",
  "file_path": "notes/my-document.md",
  "title": "My Document",
  "author": "Jenendar",
  "category": "notes",
  "tags": ["notes", "personal"],
  "date": "2024-11-01",
  "source_url": "https://example.com/original"
}
```

**Request fields**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | `string` | Yes | Full content to ingest |
| `file_path` | `string` | Yes | Logical path used as the document's unique key. Does not need to be a real file. |
| `title` | `string \| null` | No | Document title |
| `author` | `string \| null` | No | Author name |
| `category` | `string \| null` | No | Category label for filtering |
| `tags` | `string[]` | No | List of tags (default: empty list) |
| `date` | `string \| null` | No | Document date in `YYYY-MM-DD` format |
| `source_url` | `string \| null` | No | Original URL of the document |

**Response `202 Accepted`**

```json
{
  "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "queued"
}
```

**Error cases**

| Status | Cause |
|--------|-------|
| `422` | Missing required fields (`content` or `file_path`) or malformed JSON |
| `500` | Database error enqueueing the job |

---

### `POST /documents/folder`

Enqueues a background job to ingest all `.md` and `.txt` files found under a directory path accessible to the backend process. Returns `202 Accepted` immediately with a `job_id`. The worker walks subdirectories recursively and processes files one at a time, updating job progress and writing a `job_logs` row per file. Track progress via `GET /jobs/{job_id}` or stream it via `GET /jobs/{job_id}/stream`.

Files with unchanged content are automatically skipped. Re-running on the same folder is safe and idempotent.

**Request**

Content-Type: `application/x-www-form-urlencoded`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `folder_path` | `string` | Yes | Absolute path to the folder on the server's filesystem |

**Example using curl**

```bash
curl -X POST http://localhost:8002/documents/folder \
  -d "folder_path=/Users/yourname/Documents/cortex/sample-docs"
```

**Response `202 Accepted`**

```json
{
  "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "queued"
}
```

**Error cases**

| Status | Cause |
|--------|-------|
| `400` | `folder_path` is not a valid directory on the server |
| `422` | Missing `folder_path` form field |
| `500` | Database error enqueueing the job |

---

### `DELETE /documents/{id}`

Deletes a document and all of its associated chunks. The operation is permanent; there is no soft delete.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | `uuid` | Document ID to delete |

**Example using curl**

```bash
curl -X DELETE http://localhost:8002/documents/3fa85f64-5717-4562-b3fc-2c963f66afa6
```

**Response `200 OK`**

```json
{
  "status": "deleted",
  "document_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

**Error cases**

| Status | Cause |
|--------|-------|
| `404` | No document found with the given ID |
| `500` | Database error |

---

## Search

### `POST /search`

Runs the full hybrid search pipeline against the knowledge base and returns ranked result chunks. This is the primary query endpoint used by both the admin UI and the MCP server.

After the response is sent, a FastAPI `BackgroundTask` inserts a row into `search_logs` recording the query, filters, result count, latency, top chunk IDs, and whether reranking ran. This telemetry write has zero latency impact on the caller — the response is already on the wire before it runs.

**Pipeline**
1. Normalize query with `strip_markdown()` (removes markdown syntax)
2. Embed the normalized query string with `nomic-embed-text` via Ollama (768-dim vector, async httpx)
3. Vector search — cosine similarity on `chunks.embedding` (top 50 candidates; `ivfflat.probes=10`)
4. Full-text search — `plainto_tsquery` on `chunks.fts` (top 50 candidates)
5. Merge both result sets with Reciprocal Rank Fusion (RRF)
6. Rerank the top 20 merged candidates with `cross-encoder/ms-marco-MiniLM-L-6-v2` (via `anyio` thread)
7. Return the top `top_k` results
8. *(After response sent)* Insert row into `search_logs`

**Request**

Content-Type: `application/json`

```json
{
  "query": "How does the chunking algorithm handle large headings?",
  "top_k": 5,
  "rerank": true,
  "filters": {
    "tags": ["backend", "chunking"],
    "category": "engineering",
    "date_from": "2024-01-01",
    "date_to": "2024-12-31"
  }
}
```

**Request fields**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | `string` | Yes | — | Natural language query string |
| `top_k` | `int` | No | `5` | Number of results to return |
| `rerank` | `bool` | No | `true` | Whether to apply cross-encoder reranking. Set to `false` for faster but less precise results. |
| `filters` | `object \| null` | No | `null` | Optional pre-filters applied before search (see below) |

**Filter fields** (all optional, all combinable)

| Filter key | Type | Description |
|------------|------|-------------|
| `tags` | `string[]` | Return only chunks from documents that have **any** of the listed tags |
| `category` | `string` | Return only chunks from documents in this category (exact match) |
| `date_from` | `string` | ISO date (`YYYY-MM-DD`). Exclude documents dated before this date. |
| `date_to` | `string` | ISO date (`YYYY-MM-DD`). Exclude documents dated after this date. |

**Response `200 OK`**

```json
{
  "query": "How does the chunking algorithm handle large headings?",
  "results": [
    {
      "chunk_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "document_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "content": "The chunker splits markdown at heading boundaries (H1–H6). If a section exceeds 400 tokens, it is sub-split at paragraph boundaries...",
      "heading": "Chunking Algorithm",
      "score": 0.9231,
      "title": "System Architecture",
      "file_path": "sample-docs/architecture.md",
      "source_url": "https://example.com/architecture",
      "category": "engineering",
      "tags": ["backend", "chunking"],
      "doc_date": "2024-11-01"
    }
  ]
}
```

**Result object fields**

| Field | Type | Description |
|-------|------|-------------|
| `chunk_id` | `uuid` | Identifier of the matching chunk |
| `document_id` | `uuid` | Identifier of the parent document |
| `content` | `string` | Text content of the chunk |
| `heading` | `string \| null` | Markdown heading that introduced this chunk |
| `score` | `float` | Reranker score (higher is more relevant). When `rerank: false`, this reflects the RRF score instead. |
| `title` | `string \| null` | Title of the parent document |
| `file_path` | `string` | File path of the parent document |
| `source_url` | `string \| null` | Original source URL of the parent document |
| `category` | `string \| null` | Category of the parent document |
| `tags` | `string[]` | Tags of the parent document |
| `doc_date` | `string \| null` | Date of the parent document |

**Error cases**

| Status | Cause |
|--------|-------|
| `422` | Missing `query` field or malformed JSON |
| `503` | Ollama not reachable or embedding failed after retry |
| `500` | Database error |

**Notes**
- If no documents match the filters, `results` is an empty array — not an error.
- Filters narrow the candidate set before embedding and search run, so `top_k` is an upper bound on result count; fewer results may be returned if the filtered corpus is small.
- Setting `rerank: false` skips loading the cross-encoder model, which is useful if you want faster responses and are willing to accept RRF-ranked order instead.

---

## Jobs

All three ingest endpoints return a `job_id`. Use the `/jobs/*` endpoints to monitor and audit background ingestion jobs.

### `GET /jobs/`

Returns all ingestion jobs, newest first.

**Query parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | `int` | `0` | Number of records to skip |
| `limit` | `int` | `50` | Maximum number of records to return |

**Response `200 OK`** — array of job objects

```json
[
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "kind": "folder",
    "status": "running",
    "total": 14,
    "processed": 6,
    "added": 5,
    "updated": 1,
    "skipped": 0,
    "errors": 0,
    "error": null,
    "created_at": "2026-06-23T10:00:00Z",
    "updated_at": "2026-06-23T10:00:45Z"
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | `uuid` | Job identifier |
| `kind` | `string` | `"file"`, `"folder"`, or `"text"` |
| `status` | `string` | `"queued"`, `"running"`, `"done"`, or `"failed"` |
| `total` | `int` | Total files to process (0 until worker starts) |
| `processed` | `int` | Files processed so far |
| `added` | `int` | New files ingested |
| `updated` | `int` | Files re-ingested (content changed) |
| `skipped` | `int` | Files skipped (content unchanged) |
| `errors` | `int` | Files that failed during processing |
| `error` | `string \| null` | Top-level error message if the job itself failed |
| `created_at` | `datetime` | When the job was enqueued |
| `updated_at` | `datetime` | When the job was last updated by the worker |

---

### `GET /jobs/{id}`

Returns a single job with full detail including the `logs` array.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | `uuid` | Job ID from `POST /documents/*` or `GET /jobs/` |

**Response `200 OK`**

All fields from `JobResponse` (see above), plus:

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "kind": "folder",
  "status": "done",
  "total": 14,
  "processed": 14,
  "added": 12,
  "updated": 1,
  "skipped": 1,
  "errors": 0,
  "error": null,
  "created_at": "2026-06-23T10:00:00Z",
  "updated_at": "2026-06-23T10:01:30Z",
  "logs": [
    {
      "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "level": "info",
      "message": "ingested: docs/architecture.md (7 chunks)",
      "file": "docs/architecture.md",
      "created_at": "2026-06-23T10:00:05Z"
    }
  ]
}
```

**Additional fields**

| Field | Type | Description |
|-------|------|-------------|
| `logs` | `JobLog[]` | All log rows for the job, ordered by `created_at` ascending |

**JobLog fields**

| Field | Type | Description |
|-------|------|-------------|
| `id` | `uuid` | Log row identifier |
| `job_id` | `uuid` | Parent job ID |
| `level` | `string` | `"info"`, `"warn"`, or `"error"` |
| `message` | `string` | Human-readable log message |
| `file` | `string \| null` | File being processed when this was written, if applicable |
| `created_at` | `datetime` | When this log row was written |

**Error cases**

| Status | Cause |
|--------|-------|
| `404` | No job found with the given ID |
| `500` | Database error |

---

### `GET /jobs/{id}/logs`

Returns paginated log rows for a job. Useful for large jobs with many log entries.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | `uuid` | Job ID |

**Query parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | `int` | `0` | Number of log rows to skip |
| `limit` | `int` | `100` | Maximum number of rows to return |

**Response `200 OK`** — array of `JobLog` objects (same shape as in `GET /jobs/{id}`)

**Error cases**

| Status | Cause |
|--------|-------|
| `404` | No job found with the given ID |
| `500` | Database error |

---

### `GET /jobs/{id}/stream`

Streams live job progress as **Server-Sent Events (SSE)**. Useful for custom tooling or integrations that want live updates without polling. The Admin UI Jobs tab uses TanStack Query polling instead.

The stream polls the database every 1 second and emits an event whenever the job state or log rows change. It stops automatically when the job reaches `done` or `failed`.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | `uuid` | Job ID |

**Response**

Content-Type: `text/event-stream`

Each SSE event has a `data:` field containing a JSON object:

```
data: {"id": "...", "status": "running", "processed": 3, "total": 14, "logs": [...new log rows...]}

data: {"id": "...", "status": "done", "processed": 14, "total": 14, "logs": [...]}
```

The `logs` array in each event contains only log rows that are *new since the last event* — not the full history. To get the full log history, use `GET /jobs/{id}` or `GET /jobs/{id}/logs`.

**Error cases**

| Status | Cause |
|--------|-------|
| `404` | No job found with the given ID |

**Example using curl**

```bash
curl -N http://localhost:8002/jobs/3fa85f64-5717-4562-b3fc-2c963f66afa6/stream
```

---

## Data model summary

### Document

Stored in the `documents` table. One row per ingested file.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `uuid` | Primary key |
| `file_path` | `text` | Unique — re-ingesting the same path updates in place |
| `file_hash` | `text` | Content hash — unchanged files are skipped |
| `title` | `text` | Optional |
| `author` | `text` | Optional |
| `source_url` | `text` | Optional |
| `category` | `text` | Single label; indexed for filtering |
| `tags` | `text[]` | Multi-label; GIN-indexed for filtering |
| `doc_date` | `date` | Optional; indexed for date-range filtering |
| `raw_content` | `text` | Full original content |
| `created_at` | `timestamptz` | Set on first ingest |
| `updated_at` | `timestamptz` | Updated on re-ingest |

### Chunk

Stored in the `chunks` table. Many rows per document.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `uuid` | Primary key |
| `document_id` | `uuid` | FK → `documents.id` (cascade delete) |
| `content` | `text` | Chunk text (original markdown preserved) |
| `embedding` | `vector(768)` | nomic-embed-text embedding of stripped text; ivfflat cosine index |
| `chunk_index` | `int` | Position within the document (0-based) |
| `heading` | `text` | Markdown heading that introduced this chunk |
| `token_count` | `int` | Token count (max 400, measured with bert-base-uncased tokenizer) |
| `fts` | `tsvector` | Generated column; GIN-indexed for full-text search |
| `created_at` | `timestamptz` | Set on ingest |

### IngestionJob

Stored in the `ingestion_jobs` table. One row per enqueued ingest operation.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `uuid` | Primary key |
| `kind` | `text` | `'file'`, `'folder'`, or `'text'` |
| `status` | `text` | `'queued'` → `'running'` → `'done'` or `'failed'` |
| `payload` | `jsonb` | Kind-specific parameters for the worker |
| `total` | `int` | Total files in this job |
| `processed` | `int` | Files processed so far |
| `added` | `int` | Files newly ingested |
| `updated` | `int` | Files re-ingested (content changed) |
| `skipped` | `int` | Files skipped (unchanged) |
| `errors` | `int` | Files that errored |
| `error` | `text` | Top-level job error, if failed |
| `created_at` | `timestamptz` | Enqueue time |
| `updated_at` | `timestamptz` | Last worker update |

### JobLog

Stored in the `job_logs` table. Many rows per job. One row per file event.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `uuid` | Primary key |
| `job_id` | `uuid` | FK → `ingestion_jobs.id` (cascade delete) |
| `level` | `text` | `'info'`, `'warn'`, or `'error'` |
| `message` | `text` | Log message |
| `file` | `text` | File being processed (nullable) |
| `created_at` | `timestamptz` | When written |

### SearchLog

Stored in the `search_logs` table. One row per search request. Written post-response.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `uuid` | Primary key |
| `query` | `text` | The raw search query |
| `filters` | `jsonb` | Filters passed with the request (nullable) |
| `result_count` | `int` | Number of results returned |
| `latency_ms` | `int` | End-to-end search latency in milliseconds |
| `top_chunk_ids` | `uuid[]` | UUIDs of returned chunks, in result order |
| `reranked` | `bool` | Whether reranking ran |
| `created_at` | `timestamptz` | When the search was performed |

---

## Common errors

| Status | Meaning |
|--------|---------|
| `400 Bad Request` | Invalid input (wrong file type, invalid folder path) |
| `403 Forbidden` | Missing or incorrect `X-API-Key` header (only when `API_KEY` is set in `.env`) |
| `404 Not Found` | Document or job ID does not exist |
| `422 Unprocessable Entity` | Missing required field or JSON schema violation — FastAPI returns a detailed `detail` array |
| `500 Internal Server Error` | Database connection failure or unexpected server error |
| `503 Service Unavailable` | Ollama not reachable or embedding failed after retry |

For `422` errors, FastAPI returns a structured body identifying the exact field:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "query"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

For `RagError` subclasses (`DocumentNotFound`, `IngestError`, `UpstreamError`), the response body is:

```json
{
  "error": "UpstreamError",
  "detail": "Ollama embedding failed after 1 retry"
}
```

---

## Interactive docs

The backend auto-generates two documentation UIs from the OpenAPI schema:

| URL | UI |
|-----|----|
| `http://localhost:8002/docs` | Swagger UI — try endpoints live, inspect request/response schemas |
| `http://localhost:8002/redoc` | ReDoc — clean read-only reference view |
| `http://localhost:8002/openapi.json` | Raw OpenAPI 3.1 JSON schema |

These are only available while the backend is running (`make rag`).
