---
sidebar_position: 1
---

# Ingesting Documents

This guide covers everything you need to know to get documents into Cortex RAG — from how to format your files to all the available ingestion methods.

---

## Supported file formats

| Format | Frontmatter | Title fallback | Notes |
|--------|-------------|----------------|-------|
| `.md` | Yes — YAML frontmatter parsed | Filename (without extension) | Full metadata support |
| `.txt` | No — entire file is body | Filename (without extension) | No frontmatter parsing |

---

## Markdown format and YAML frontmatter

Cortex RAG ingests `.md` files with an optional YAML frontmatter block at the top, followed by the document body.

### Supported frontmatter fields

| Field | Type | Description |
|---|---|---|
| `title` | string | Human-readable title shown in the admin UI and returned in search results |
| `author` | string | Author name for attribution and filtering |
| `category` | string | Single category label (e.g. `engineering`, `product`, `legal`) — used for filtering |
| `tags` | list of strings | Topic tags for multi-label filtering (e.g. `[python, fastapi, auth]`) |
| `date` | string | Document date in `YYYY-MM-DD` format |
| `source` | string | Original URL or source reference |

All frontmatter fields are optional. If `title` is omitted, the filename is used as the title.

### Example document

```markdown
---
title: "Authentication Design"
author: "Jane Smith"
category: "engineering"
tags:
  - auth
  - jwt
  - security
date: 2025-03-15
source: "https://internal.example.com/docs/auth-design"
---

# Authentication Design

This document describes the token-based authentication flow used across all services.

## Token issuance

JWTs are issued by the auth service on successful login. Each token contains...

## Refresh strategy

Refresh tokens are stored in an HttpOnly cookie and rotated on every use...
```

### How the body is processed

Everything after the closing `---` of the frontmatter block is treated as the document body. The body is split into chunks by the chunker (see [Chunking](#chunking) below). The raw content is also stored in full so you can retrieve the original document at any time.

---

## Chunking

When a document is ingested, the body is split into chunks before embeddings are generated. Understanding how chunking works helps you write documents that produce clean, semantically focused chunks.

**How chunks are created:**

- The chunker splits on markdown headings (`#`, `##`, `###`)
- Each chunk has a maximum size of 400 tokens (estimated as `len(text) // 4` characters — a conservative approximation; `nomic-embed-text` uses a LLaMA BPE tokenizer, not BERT, so loading `bert-base-uncased` would produce wrong counts)
- When a section exceeds 400 tokens, `_split_long()` uses a sliding word-window to keep each piece within the limit, with approximately 50 words of overlap between adjacent chunks to preserve context at boundaries
- The heading that introduces each section is stored alongside the chunk (the `heading` field in the database)

**Practical implications:**

- A document with no headings becomes a single chunk (or several, if the body is long)
- A document with clear H1/H2/H3 structure produces one chunk per section, each focused on that topic
- Short sections (under 400 tokens) are never split — they become exactly one chunk

---

## Markdown stripping before embedding

Before chunk text is sent to Ollama for embedding, `strip_markdown()` removes markdown syntax:

- Heading markers (`#`, `##`, etc.) are stripped — text is kept
- Bold/italic markers (`**`, `*`, `_`) are stripped
- Links `[text](url)` → `text` (URL is dropped)
- Images `![alt](url)` are dropped entirely
- Code block fences are stripped; code content is kept

The **stored chunk content** in the database always contains the original markdown — stripping only affects what goes to the embedder. Search result previews and the admin UI show the original formatted content.

The same `strip_markdown()` normalization is applied to the query string at search time, keeping query and chunk representations in the same plain-text space.

---

## Five ways to ingest

All ingest methods are **asynchronous** — they enqueue a background job and return immediately with a `job_id`. The actual chunking, embedding, and storage happens in the background worker. Use the **Jobs** page or `GET /jobs/{job_id}` to track progress.

### 1. Admin UI — Upload a file

The fastest path for a file already on disk.

1. Open the admin panel at `http://localhost:5173`
2. Click **Ingest** in the sidebar
3. Select the **Upload File** tab
4. Drag a `.md` or `.txt` file onto the drop zone, or click to open a file picker
5. Click **Ingest**

The backend enqueues a background job and returns immediately. The UI navigates to **Jobs → `/jobs?highlight=<job_id>`** so you can watch processing progress in real time.

**What gets extracted automatically:** for `.md` files, frontmatter fields (`title`, `author`, `category`, `tags`, `date`, `source`) are parsed from the file. For `.txt` files, the title is derived from the filename.

### 2. Admin UI — Folder

Ingest an entire folder of `.md` and `.txt` files. The backend enqueues a background job (kind `folder`) and returns immediately.

1. Open the admin panel at `http://localhost:5173`
2. Click **Ingest** in the sidebar
3. Select the **Folder** tab
4. Enter the absolute path to the folder on the server's filesystem
5. Click **Ingest Folder**

The UI navigates to the **Jobs** page where you can track per-file progress. The expanded job detail shows a log table with one row per file processed:

| Column | Description |
|--------|-------------|
| Level | `info`, `warn`, or `error` — error rows are highlighted |
| Message | e.g. `ingested: docs/setup.md (7 chunks)` |
| File | The specific file |
| Time | When it was processed |

Files with unchanged content (same SHA-256 hash) are automatically skipped. Re-running on the same folder is safe and idempotent.

### 3. Admin UI — Paste text

Use this when you want to ingest content that is not saved as a file, or when you want to set metadata manually without editing a file.

1. Open the admin panel at `http://localhost:5173`
2. Click **Ingest** in the sidebar
3. Select the **Paste Text** tab
4. Fill in the metadata fields:
   - **File path** — optional. A logical path used as a unique identifier, e.g. `notes/auth-design.md`. If omitted, the backend auto-generates one as `paste/<title-slug>-<8hex>` (or `paste/<uuid>` when no title is set).
   - **Title**, **Author**, **Category**, **Tags** (comma-separated), **Date**, **Source URL** (all optional)
5. Paste your content into the **Content** textarea
6. Click **Ingest**

The backend enqueues a job and navigates to the Jobs page. The `file_path` acts as the unique key for deduplication — if you ingest again with the same path and different content, the old document is replaced (see [Deduplication and re-ingestion](#deduplication-and-re-ingestion)). Auto-generated paths are random, so pasting the same content twice without a `file_path` creates two separate documents.

### 4. Via MCP in Claude Desktop

If the MCP server is configured and running, you can ingest documents directly from a Claude Desktop conversation without opening a browser.

**Example conversation:**

> You: Please ingest this document into the knowledge base.
>
> ```markdown
> ---
> title: "Deployment Checklist"
> category: "ops"
> tags: [deploy, checklist, prod]
> date: 2025-06-01
> ---
>
> # Deployment Checklist
>
> ## Pre-deploy
> - Run the full test suite
> - Check migration scripts
>
> ## Post-deploy
> - Verify health endpoint
> - Check error rates for 15 minutes
> ```

Claude will call the `ingest_document` MCP tool on your behalf. You can also pass metadata explicitly:

> You: Ingest the following content with title "Q2 Retrospective", category "management", and tags "retrospective, q2, 2025".

**MCP tool signature:**

```
ingest_document(
  content,         # required — the document body (without frontmatter)
  file_path?,      # optional — logical path used as unique key; auto-generated if omitted
  title?,          # optional
  category?,       # optional
  tags?,           # optional — comma-separated string
  author?,         # optional
  date?,           # optional — YYYY-MM-DD
  source_url?      # optional
)
```

**Prerequisite:** the backend must be running (`make rag`) and the MCP server must be configured in `~/.claude/claude_desktop_config.json`. See [Claude Desktop MCP setup](/mcp/claude-desktop-setup) for the full configuration.

### 5. API directly

Use the REST API when ingesting from a script, a CI pipeline, or any custom tooling.

All three ingest endpoints return `202 Accepted` with a `job_id` immediately. Poll `GET /jobs/{job_id}` to check progress.

#### Upload a file

```bash
curl -X POST http://localhost:8002/documents/upload \
  -F "file=@/path/to/your-document.md"
```

Response:

```json
{ "job_id": "3fa85f64-...", "status": "queued" }
```

#### Ingest text with metadata

```bash
curl -X POST http://localhost:8002/documents/text \
  -H "Content-Type: application/json" \
  -d '{
    "content": "# My Document\n\nBody content here.",
    "file_path": "notes/my-document.md",
    "title": "My Document",
    "author": "Jane Smith",
    "category": "engineering",
    "tags": ["python", "api"],
    "date": "2025-06-23",
    "source_url": "https://example.com/source"
  }'
```

Response:

```json
{ "job_id": "3fa85f64-...", "status": "queued" }
```

#### Ingest an entire folder

```bash
curl -X POST http://localhost:8002/documents/folder \
  -d "folder_path=/absolute/path/to/sample-docs"
```

Response:

```json
{ "job_id": "3fa85f64-...", "status": "queued" }
```

#### Polling job progress

```bash
# Check status
curl http://localhost:8002/jobs/3fa85f64-...

# Stream live SSE updates (stops when done/failed)
curl -N http://localhost:8002/jobs/3fa85f64-.../stream

# Paginated log rows
curl "http://localhost:8002/jobs/3fa85f64-.../logs?limit=50"
```

---

## Deduplication and re-ingestion

### How deduplication works

Every document is identified by its `file_path`. Before storing, the backend computes a SHA-256 hash of the raw content (`file_hash`).

- **Same path, same content** — the request is a no-op. The existing document is left unchanged. No new chunks are created, no embeddings are recomputed.
- **Same path, different content** — the old document and all its chunks are deleted, then the new version is ingested from scratch. This ensures the chunk store never contains stale embeddings.
- **New path** — a new document record and its chunks are created regardless of content.

This means re-ingesting an unchanged file is safe and cheap — you can do it idempotently from a script without worrying about duplicate chunks accumulating.

### Deleting a document

To remove a document and all its associated chunks:

```bash
curl -X DELETE http://localhost:8002/documents/{id}
```

You can find the document `id` from the `GET /documents/` list or the admin UI Documents page. Deletion cascades to all chunks automatically.

---

## Best practices

### Use descriptive titles and categories

Titles and categories are surfaced in search results and filter dropdowns. A title like `"Auth Service Design v2"` is more useful than `"notes"`. Categories should be consistent across your corpus — decide on a fixed set (e.g. `engineering`, `product`, `ops`, `legal`) and stick to it.

### Use meaningful tags

Tags are the primary tool for topic-based filtering. When querying via MCP or the admin UI Search page, you can narrow results to specific tags. Invest a few seconds per document to pick 2–5 precise tags. Avoid very broad tags like `misc` or `notes` that add no filtering value.

### Structure content with headings

The chunker splits on `#`, `##`, and `###` headings. A document with clear heading structure produces one semantically focused chunk per section, which dramatically improves retrieval precision. A document that is one large unbroken block will either become a single chunk (if under 400 tokens) or be split at arbitrary token boundaries, which reduces coherence.

**Prefer this:**

```markdown
## Token issuance

JWTs are issued on login. Each token has a 15-minute expiry...

## Refresh strategy

Refresh tokens are rotated on every use and stored in an HttpOnly cookie...
```

**Over this:**

```markdown
JWTs are issued on login with a 15-minute expiry. Refresh tokens are rotated
on every use and stored in an HttpOnly cookie. The auth service validates...
(continues for 600 tokens with no headings)
```

### Keep sections focused

Each heading-delimited section should cover one concept. If a section runs longer than 400 tokens and covers multiple sub-topics, split it with sub-headings. This keeps each chunk self-contained and improves the relevance of retrieved results.

### Set the `date` field for time-sensitive content

The search API supports `date_from` and `date_to` filters. If your corpus includes content that becomes outdated (meeting notes, quarterly plans, changelogs), always set the `date` frontmatter field. This lets you filter to recent documents when querying.

### Use `file_path` as a stable logical identifier

When ingesting via the API or MCP, choose a `file_path` that reflects the content's logical location in your knowledge base — for example `engineering/auth/design.md` rather than an absolute filesystem path. This makes re-ingestion idempotent and keeps your document list organized.

---

## What happens during ingestion (end-to-end)

For reference, here is the full sequence of operations the backend performs when you ingest a document:

1. **Enqueue** — the ingest endpoint writes a row to `ingestion_jobs` with `status='queued'` and returns `202 {job_id}` immediately. No chunking or embedding happens yet.
2. **Worker picks up the job** — the ARQ worker process (`make rag-worker`) dequeues the job from Redis and sets `status='running'` in the DB.
3. **Parse** — for `.md` files, frontmatter fields are extracted and the body is separated. For `.txt` files, the entire file is treated as the body.
4. **Hash** — SHA-256 is computed on the raw content.
5. **Deduplicate** — if a document with the same `file_path` and `file_hash` already exists, skip (log row written, `skipped` counter incremented).
6. **Replace** — if the `file_path` exists with a different hash, delete the old document and all its chunks.
7. **Store document** — insert a row into `documents` with metadata and raw content.
8. **Chunk** — split the body on markdown headings, enforcing a 400-token max per chunk with approximately 50 words of overlap (real tokenizer used throughout).
9. **Normalize** — `strip_markdown()` is applied to each chunk's text to remove markdown syntax before embedding (stored content remains original markdown).
10. **Embed** — call Ollama `nomic-embed-text` via async httpx to generate a 768-dimensional vector for each stripped chunk text. One retry on failure, then the file is marked errored.
11. **Store chunks** — insert rows into `chunks` with content (original markdown), embedding, heading, token count, and a generated `tsvector` column for full-text search.
12. **Log** — a `job_logs` row is written for the file (`info` on success, `error` on failure).
13. **Update job stats** — `processed`, `added`/`updated`/`skipped`/`errors` counters are incremented on the job row.
14. **Complete** — after all files are processed, the job is updated to `status='done'` (or `'failed'` if a top-level error occurred).
