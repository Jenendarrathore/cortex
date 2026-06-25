---
sidebar_position: 1
---

# What is Cortex RAG

Cortex RAG is a local Retrieval-Augmented Generation system built for personal or small-team use. You ingest markdown and text documents, which get chunked and stored as vector embeddings in a PostgreSQL database (via pgvector). When you ask a question, the system retrieves the most relevant chunks using a hybrid search pipeline and returns ranked results — either directly in Claude Desktop via MCP, or through a web admin panel.

Everything runs on your own machine. No third-party APIs are involved in retrieval or storage. Embeddings are generated locally via Ollama, the database is a local PostgreSQL instance, and the MCP server connects Claude Desktop to your knowledge base over localhost.

![Cortex Admin UI — hybrid search with ranked results](/img/screenshots/04-search-results.png)

## Key features

- **Local-first** — embeddings (Ollama `nomic-embed-text`), vector store (pgvector), and reranker (sentence-transformers) all run on your hardware. Nothing leaves your machine.
- **Markdown and text ingestion** — ingest `.md` and `.txt` files by upload, text paste, or folder path. Documents are chunked by heading boundaries at a max of 400 tokens per chunk.
- **Hybrid search** — combines vector similarity search (cosine on 768-dim embeddings) with PostgreSQL full-text search, merged via Reciprocal Rank Fusion (RRF).
- **Reranking** — top candidates are reranked with `cross-encoder/ms-marco-MiniLM-L-6-v2` before results are returned, improving precision without sacrificing recall.
- **Background ingestion jobs** — all ingest operations (upload, folder, text) are enqueued to Redis via ARQ and processed by a separate worker process (`make rag-worker`). The API returns immediately with a `job_id`. Per-job logs (file, status, chunks, result) are stored in `job_logs` and `ingestion_jobs` and viewable in the Admin UI Jobs tab.
- **Search telemetry** — every search query is logged post-response (query, filters, latency_ms, result_count, top chunk IDs) to `search_logs`. Zero latency impact; written via FastAPI `BackgroundTask`.
- **MCP integration** — exposes `retrieve`, `ingest_document`, and `list_knowledge_base` tools to Claude Desktop via the Model Context Protocol. Ask Claude questions and it queries your local knowledge base automatically.
- **Admin UI** — a React/shadcn web panel (port 5173) for browsing documents, monitoring ingestion jobs, and running searches with filters.
- **REST API** — a FastAPI backend (port 8002) you can call directly from scripts, other tools, or custom integrations.
- **Optional API key auth** — set `API_KEY` in `.env` to require `X-API-Key` on all routes. Disabled by default.

## How it works

```
.md / .txt files
    │
    ▼  (enqueued as background job — API returns 202 + job_id immediately)
ARQ Worker (workers/arq_worker.py) — run via `make rag-worker`
    │
    ▼
Chunker (split by headings, max 400 tokens, real tokenizer)
    │
    ▼
strip_markdown() — strips markdown syntax before embedding
    │
    ▼
Embedder (async httpx → Ollama nomic-embed-text → 768-dim vectors)
    │
    ▼
PostgreSQL + pgvector
  ├── documents          (metadata + raw_content)
  ├── chunks             (content + embedding vector(768) + fts tsvector)
  ├── ingestion_jobs     (job queue — status, progress, error)
  ├── job_logs           (per-file audit trail)
  └── search_logs        (query telemetry — latency, result_count)
    │
    ▼  at query time
strip_markdown(query) → embed query (async)
Vector search (top 50) + FTS search (top 50)
    │
    ▼
RRF merge → top 20 candidates
    │
    ▼
Cross-encoder reranker (anyio thread) → top_k results
    │
    ▼  BackgroundTask (after response sent)
search_logs INSERT (query, latency_ms, result_count, top_chunk_ids, reranked)
```

At ingest time, the API enqueues a job and returns immediately. The worker picks it up, chunks and embeds each document, and writes progress to `job_logs`. At query time, both vector and full-text search run, results are merged with RRF, and the top candidates are reranked before being returned. Search telemetry is written after the response, never blocking the caller.

## Four interfaces

### MCP — Claude Desktop

The MCP server runs as a subprocess of Claude Desktop and exposes three tools:

| Tool | What it does |
|------|--------------|
| `retrieve(query, top_k?, tags?, category?, date_from?, date_to?)` | Runs the full hybrid search pipeline and returns ranked chunks |
| `ingest_document(content, file_path, title?, ...)` | Adds a document to the knowledge base (enqueues a background job) |
| `list_knowledge_base()` | Returns all ingested documents with metadata |

Claude calls these tools automatically when it determines your question is relevant to the knowledge base. See [Setup](./setup/installation.md) for the Claude Desktop config.

### Admin UI

A Vite + React panel available at `http://localhost:5173`. Four pages:

- **Documents** — table of all ingested documents; click a row to see raw content and chunks.
- **Ingest** — three tabs: **Upload File** (`.md` and `.txt`), **Folder** (server-side path), **Paste Text** with metadata fields. All three submit as background jobs and redirect to the Jobs page.
- **Search** — search bar with tag, category, and date-range filters; results shown as ranked cards including `source_url` and `file_path`.
- **Jobs** — background ingestion job table with status badges, progress bars, result counts, and timestamps. Click any row to expand the per-file log table. Auto-refreshes while jobs are active.

Start it with `make rag-ui` (requires the backend to be running with `make rag`).

### REST API

The FastAPI backend runs on `http://localhost:8002`. Main endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/documents/` | List all documents (supports `skip` and `limit` pagination) |
| `GET` | `/documents/{id}` | Get document with chunks |
| `POST` | `/documents/upload` | Upload a `.md` or `.txt` file — returns `202 {job_id}` |
| `POST` | `/documents/text` | Ingest text via JSON body — returns `202 {job_id}` |
| `POST` | `/documents/folder` | Ingest all `.md` and `.txt` files from a server-side folder — returns `202 {job_id}` |
| `DELETE` | `/documents/{id}` | Delete document and all its chunks |
| `POST` | `/search` | Run hybrid search with optional filters |
| `GET` | `/jobs/` | List all ingestion jobs (newest first) |
| `GET` | `/jobs/{id}` | Job detail with progress and log entries |
| `GET` | `/jobs/{id}/logs` | Paginated log rows for a job |
| `GET` | `/jobs/{id}/stream` | SSE stream of live job progress |

Full schema details are available via the auto-generated docs at `http://localhost:8002/docs`.

## Quick start

See the **[Setup guide](./setup/installation.md)** for complete installation steps, including:

- System dependencies (PostgreSQL, Redis, Ollama, Python 3.11+)
- One-command setup with `make mac-setup` or `make linux-setup`
- Database initialization and pgvector extension
- Claude Desktop MCP configuration

**Minimum hardware:** 8 GB RAM, 10 GB free disk. No GPU required.
