---
sidebar_position: 1
---

# Admin UI

The Cortex RAG Admin UI is a web panel for managing your local knowledge base. It lets you browse ingested documents, monitor background ingestion jobs, ingest new content, and run test searches — all without touching the command line or the API directly.

It is an admin and management tool. End-user querying happens in Claude Desktop via the MCP integration, not here.

**URL:** `http://localhost:5173`  
**Tech:** React 19, Vite 8, TypeScript (strict), Tailwind CSS, shadcn/ui, TanStack Query v5, react-router-dom v7, sonner

---

## Prerequisites

The backend must be running before you start the UI. The UI is a pure frontend — it has no server of its own and calls the FastAPI backend at `http://localhost:8002` (configured via `VITE_API_URL` in `rag-frontend/.env.local`).

Start the backend first:

```bash
make rag
```

---

## Starting the UI

```bash
make rag-ui
```

This runs `vite` in dev mode. Open `http://localhost:5173` in your browser. The page hot-reloads on file changes if you are doing frontend development.

---

## Navigation

The UI has four tabs in the top navigation bar: **Documents**, **Ingest**, **Search**, and **Jobs**. All four are deep-linkable — refreshing the page or sharing the URL preserves the active tab.

---

## Documents tab

![Documents tab](/img/screenshots/01-documents.png)

The Documents tab shows a paginated table of documents currently in the knowledge base. The frontend fetches 20 documents per page using the `skip` and `limit` parameters on `GET /documents/`. Use the **Previous** and **Next** buttons to navigate between pages.

Each row displays:

- Title
- Category
- Author
- Tags
- Ingestion date

Click any row to open the **Document Detail dialog**.

### Document Detail dialog

The dialog has three tabs:

#### Overview

Displays all metadata for the document:

| Field | Description |
|-------|-------------|
| Title | Document title |
| Author | Author name |
| Category | Category label |
| Tags | Tag list |
| Date | Document date (not ingestion date) |
| Source URL | Original source, if provided |
| File path | The logical path used during ingestion |

#### Content

Shows the raw content of the document exactly as it was ingested.

#### Chunks

Lists every chunk the document was split into. For each chunk you can see:

- Chunk index (position in the document)
- Heading the chunk falls under
- Token count
- The chunk text itself

This is useful for diagnosing retrieval issues — if a query is returning poor results, the Chunks tab lets you see exactly how the document was split and whether the relevant content ended up in a well-formed chunk.

### Deleting a document

Each row in the Documents table has a delete action. Deleting a document removes it and all its associated chunks from the database. This cannot be undone from the UI.

---

## Ingest tab

![Ingest tab](/img/screenshots/02-ingest.png)

The Ingest tab has three sub-tabs for adding content to the knowledge base. All three methods enqueue a background job and navigate to the **Jobs** tab so you can watch progress. No tab blocks waiting for ingestion to complete.

### Upload File tab

Upload a `.md` or `.txt` file from your local filesystem. The file is sent to `POST /documents/upload` as a multipart form upload. The backend enqueues a background job and returns `202 {job_id}` immediately. The UI navigates to `/jobs?highlight=<job_id>` so you can see the job's progress.

- `.md` files: YAML frontmatter is parsed automatically for metadata (title, author, category, tags, date, source)
- `.txt` files: the entire file is treated as the body; title is derived from the filename

### Folder tab

Ingest an entire folder of `.md` and `.txt` files. Enter the absolute path to the folder on the server's filesystem and click **Ingest Folder**. The backend enqueues a background job (kind `folder`) and returns immediately. The UI navigates to the Jobs page where you can track per-file progress.

Files with unchanged content (same SHA-256 hash) are automatically skipped. Re-running on the same folder is safe and idempotent.

### Paste Text tab

Paste text directly into a textarea and fill in the metadata form. All metadata fields are optional except file path and content.

| Field | Description |
|-------|-------------|
| Content | Text to ingest (required) |
| File path | A logical identifier for the document (e.g. `notes/meeting-2025-01.md`) — required |
| Title | Human-readable title |
| Author | Author name |
| Category | Category label for filtering |
| Tags | Comma-separated tag list |
| Date | Document date in `YYYY-MM-DD` format |
| Source URL | Link to the original source |

This calls `POST /documents/text` and enqueues a background job.

---

## Search tab

![Search tab with ranked results](/img/screenshots/04-search-results.png)

The Search tab lets you run queries against the knowledge base using the full hybrid search pipeline — the same pipeline Claude Desktop uses when you ask it a question.

### Running a search

Type a query in the search bar and press Enter or click Search. Results appear as ranked cards below the search bar.

Each result card shows:

- The matching chunk text
- The document title it came from
- The heading the chunk falls under
- The relevance score (after reranking)
- Metadata: category, tags, date
- **Source URL** — link to the original source, if one was set on the document
- **File path** — the logical file path of the document

### Filters

You can narrow results before searching using these filters:

| Filter | Description |
|--------|-------------|
| Tags | Restrict results to documents with specific tags |
| Category | Restrict results to a specific category |
| Date from | Only include documents dated on or after this date |
| Date to | Only include documents dated on or before this date |

Filters are sent as part of the `POST /search` request body.

### Search pipeline (what happens behind the scenes)

1. The query is normalized with `strip_markdown()` (removes any markdown syntax)
2. The normalized query is embedded with `nomic-embed-text` via Ollama (768-dim vector, async httpx)
3. Vector search: cosine similarity against `chunks.embedding` — top 50 candidates (`ivfflat.probes=10`)
4. Full-text search: `plainto_tsquery` against `chunks.fts` — top 50 candidates
5. Results are merged with Reciprocal Rank Fusion (RRF)
6. Top 20 candidates are reranked with `cross-encoder/ms-marco-MiniLM-L-6-v2` (via thread pool)
7. The top `top_k` results are returned (default: 5)
8. After the response is sent: query, latency, result count, and top chunk IDs are written to `search_logs`

The Search tab is the fastest way to verify that a newly ingested document is retrievable before relying on it in Claude Desktop.

---

## Jobs tab

![Jobs tab](/img/screenshots/05-jobs.png)

The Jobs tab shows all background ingestion jobs, newest first. It is the primary way to monitor and audit ingestion progress.

### Job list

Each row in the jobs table shows:

| Column | Description |
|--------|-------------|
| Kind | `file`, `folder`, or `text` |
| Status | `queued`, `running`, `done`, or `failed` — with a color-coded badge; `running` shows a spinner |
| Progress | `processed / total` bar |
| Results | Added / updated / skipped / errors counts |
| Created | When the job was enqueued |
| Updated | When the job was last modified (i.e. when the worker last wrote progress) |

The Jobs tab auto-refetches every 2 seconds while any job is in `queued` or `running` state, and stops polling once all jobs are terminal (`done` or `failed`).

### Job detail (inline log table)

Click any row to expand an inline detail panel showing the `job_logs` table for that job:

| Column | Description |
|--------|-------------|
| Level | `info`, `warn`, or `error` — with a badge; error rows are highlighted |
| Message | Log message (e.g. `ingested: docs/setup.md (7 chunks)`) |
| File | The file being processed, if applicable |
| Time | Log entry timestamp |

Scrollable up to 500 log entries. Error rows are highlighted with a red background to make failures easy to spot.

If the job is still running when you expand it, the detail view refetches automatically so new log entries appear as they are written by the worker.

### Job error banner

If a job failed (`status: failed`), the expanded detail shows an error banner above the log table with the top-level error message.

---

## Relationship to other interfaces

| Interface | Purpose |
|-----------|---------|
| Admin UI (port 5173) | Browse, ingest, monitor jobs, delete, and test search — management only |
| Claude Desktop (MCP) | End-user querying — Claude calls `retrieve` automatically |
| REST API (port 8002) | Direct API access from scripts or other tools |

The Admin UI does not expose any querying interface intended for end users. Its Search tab exists to help you verify that retrieval is working correctly, not as a production search interface.
