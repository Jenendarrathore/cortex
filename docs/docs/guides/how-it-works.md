---
sidebar_position: 0
---

# How It Works — Technical Deep Dive

Complete reference covering every stage of the ingestion and retrieval pipelines. Written for a senior developer audience — exact implementation details, algorithms, SQL, and design rationale throughout.

---

## Ingestion Pipeline

The ingestion pipeline is the core data pathway of Cortex RAG — it accepts raw files and text from four distinct entry points, normalises and chunks the content, generates vector embeddings via a local Ollama instance, and persists everything to PostgreSQL in a form that the hybrid retrieval layer can query with sub-100ms latency. The pipeline is intentionally asynchronous and crash-resilient: every job is durably recorded in Postgres before it is dispatched to Redis, so no work is lost if either process dies.

---

### 1. Entry Points & API Layer

All ingestion requests enter through the FastAPI router at `api/routes/documents.py`, which is mounted under the `/documents` prefix. There are four distinct ingestion surfaces:

#### 1.1 File Upload — `POST /documents/upload`

Accepts a multipart form upload of a single `.md` or `.txt` file. The endpoint validates the extension immediately before reading any bytes:

```python
if Path(file.filename).suffix.lower() not in (".md", ".txt"):
    raise HTTPException(400, "Only .md and .txt files accepted")
raw = await file.read()
```

The entire file content is read into memory, base64-encoded, and packed into the job payload:

```json
{
  "filename": "my-article.md",
  "content_b64": "LS0tCnRpdGxlOiBFeGFtcGxlCi0tLQo..."
}
```

Base64 encoding is necessary because `payload` is stored as a JSONB column in Postgres — binary content cannot be stored directly in JSONB. The encoding is done inline with `base64.b64encode(raw).decode()`.

#### 1.2 Text Paste — `POST /documents/text`

Accepts a JSON body conforming to `IngestTextRequest`:

```python
class IngestTextRequest(BaseModel):
    content: str
    file_path: str | None = None
    title: str | None = None
    author: str | None = None
    category: str | None = None
    tags: list[str] = []
    date: str | None = None
    source_url: str | None = None
```

The entire request is serialised with `req.model_dump()` and stored verbatim as the job payload. No base64 encoding is needed because the content is already a UTF-8 string. This endpoint is the primary integration point for programmatic callers and the MCP tool.

#### 1.3 Folder Scan — `POST /documents/folder`

Accepts a `folder_path` form field pointing to a server-side filesystem path. The validation is immediate:

```python
if not Path(folder_path).is_dir():
    raise HTTPException(400, f"Not a directory: {folder_path}")
```

The payload stored in Postgres is minimal — just the absolute path:

```json
{ "folder_path": "/home/user/knowledge-base" }
```

The actual file discovery happens later inside the worker process, not in the API handler. This is deliberate: the API handler returns in microseconds regardless of how many files are in the folder.

#### 1.4 MCP Integration

The MCP surface uses the same `POST /documents/text` endpoint. The MCP tool serialises the document content and optional metadata into an `IngestTextRequest`-shaped JSON body and POSTs it. From the pipeline's perspective, MCP ingestion is identical to a text paste.

#### 1.5 The `_enqueue()` Function

Every ingestion path converges on a single private function:

```python
async def _enqueue(db: AsyncSession, arq: ArqRedis, kind: str, payload: dict) -> IngestionJob:
    job = IngestionJob(kind=kind, payload=payload)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await arq.enqueue_job("ingest_job", str(job.id))
    return job
```

The order of operations here is critical and intentional:

1. **Write to Postgres first** (`db.commit()`): The `IngestionJob` row is durably committed with `status='queued'` before anything is sent to Redis. If the process crashes between the Postgres commit and the Redis enqueue, the `on_startup` crash-recovery hook will find this row and re-enqueue it on the next worker start.

2. **Refresh the ORM object** (`db.refresh(job)`): After commit, the server-generated UUID (`DEFAULT gen_random_uuid()`) and timestamps are not populated on the Python object until explicitly refreshed. This ensures `job.id` is the real UUID.

3. **Enqueue to Redis** (`arq.enqueue_job("ingest_job", str(job.id))`): ARQ receives only the job's UUID as a string argument — not the full payload. The worker will load the job from Postgres using this ID. This keeps the Redis message small and ensures Postgres is always the authoritative source of the job's state.

The response to the client is immediate:

```json
{
  "job_id": "3f7a1c2d-9e4b-4f1a-8b5c-2a1d3e4f5678",
  "status": "queued"
}
```

#### 1.6 `file_path` Auto-Generation Logic

The `file_path` column is the deduplication key (it carries a `UNIQUE` constraint). For file uploads and folder scans, the path is supplied externally (the original filename or the relative path within the folder). For text pastes where no `file_path` is provided in the request, `IngestController` generates one:

```python
def _generate_file_path(title: str | None) -> str:
    if title:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        return f"paste/{slug}-{uuid.uuid4().hex[:8]}"
    return f"paste/{uuid.uuid4().hex}"
```

If a title is provided, the function:
1. Lowercases the title
2. Replaces any run of non-alphanumeric characters with a single hyphen (`re.sub(r"[^a-z0-9]+", "-", ...)`)
3. Strips leading/trailing hyphens (`.strip("-")`)
4. Truncates to 60 characters to stay within a safe column width
5. Appends 8 hex characters from a fresh UUID for uniqueness

Example: title `"Installing Rust on macOS (M2)"` → `paste/installing-rust-on-macos-m2-a3f9b1c2`

If no title is provided, the path is simply `paste/<32-hex-char-uuid>`.

---

### 2. Job Queue Architecture

#### 2.1 ARQ + Redis

Cortex RAG uses [ARQ](https://arq-docs.helpmanual.io/) as its task queue, backed by Redis. ARQ is an asyncio-native task queue that stores task state in Redis sorted sets and executes tasks in a standalone worker process. It was chosen over Celery for its asyncio-first design — the entire ingestion pipeline is `async/await` throughout, and ARQ integrates without any thread pool overhead.

The system has two separate OS processes:

| Process | Role |
|---|---|
| FastAPI / uvicorn | Handles HTTP requests, writes jobs to Postgres, enqueues job IDs to Redis, returns 202 immediately |
| ARQ worker | Reads job IDs from Redis, loads full job state from Postgres, executes ingestion (parse → chunk → embed → store) |

This separation is fundamental to the design. Embedding generation via Ollama can take anywhere from 100ms (short document) to several minutes (large folder), and the HTTP request/response cycle cannot block for that long. The API process returns a `202 Accepted` with a job ID, and the client is expected to poll.

#### 2.2 `WorkerSettings` Configuration

```python
class WorkerSettings:
    functions = [ingest_job]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 600  # 10 min hard limit per job
    keep_result = 3600  # keep ARQ result in Redis for 1h
```

| Setting | Value | Meaning |
|---|---|---|
| `functions` | `[ingest_job]` | Only one registered task type — all ingestion jobs route through `ingest_job` regardless of kind |
| `on_startup` | `startup` | Hook called once when the worker process starts; executes crash recovery (see §3) |
| `max_jobs` | `10` | Up to 10 jobs may run concurrently within the single worker process. Since all I/O is async (Postgres, HTTP to Ollama), this is CPU-idle concurrency and does not block |
| `job_timeout` | `600` | ARQ will hard-kill any job that runs longer than 600 seconds (10 minutes). This is the outer safety net for a hung Ollama connection |
| `keep_result` | `3600` | ARQ's own Redis result record is kept for 1 hour. The durable result is in Postgres `ingestion_jobs.result` JSONB; this is just for ARQ-level introspection |

#### 2.3 The `ingest_job` Task

```python
async def ingest_job(ctx: dict, job_id: str) -> dict:
    logger.info("ARQ: starting job %s", job_id)
    await process_job(uuid.UUID(job_id))
    logger.info("ARQ: finished job %s", job_id)
    return {"job_id": job_id}
```

ARQ passes `ctx` (a dict containing `ctx["redis"]` and other worker-level state) and the positional argument `job_id` which was passed to `arq.enqueue_job("ingest_job", str(job.id))` in the API layer. The task converts the string UUID to a `uuid.UUID` object and delegates to `controllers/worker.py:process_job()`, which is responsible for all actual work.

Inside `process_job()`, the first thing the worker does is open a fresh `AsyncSession` and load the job from Postgres by UUID:

```python
async def process_job(job_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(IngestionJob).filter(IngestionJob.id == job_id)
        )
        job = result.scalars().first()
        if not job:
            logger.warning("Worker: job %s not found", job_id)
            return
        if job.kind == "file":
            await _process_file_job(db, job)
        elif job.kind == "text":
            await _process_text_job(db, job)
        elif job.kind == "folder":
            await _process_folder_job(db, job)
```

This pattern — load from Postgres, not from the Redis payload — ensures the worker always has the most current state of the job row.

---

### 3. Crash Recovery

#### 3.1 The `on_startup` Hook

When the ARQ worker process starts (or restarts after a crash), ARQ calls the `on_startup` coroutine before processing any queued jobs:

```python
async def startup(ctx: dict) -> None:
    arq: ArqRedis = ctx["redis"]
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                text(
                    "UPDATE ingestion_jobs SET status='queued', updated_at=now() "
                    "WHERE status='running' RETURNING id"
                )
            )
            rows = result.fetchall()
            await db.commit()
            if rows:
                logger.info("Crash recovery: re-queuing %d orphaned job(s)", len(rows))
                for row in rows:
                    await arq.enqueue_job("ingest_job", str(row[0]))
        except Exception as e:
            logger.warning("Crash recovery failed: %s", e)
```

#### 3.2 Exact SQL

```sql
UPDATE ingestion_jobs
SET status = 'queued', updated_at = now()
WHERE status = 'running'
RETURNING id
```

This single atomic UPDATE finds all jobs with `status='running'` — meaning they were being processed when the worker was killed — resets them to `status='queued'`, and returns their UUIDs. Each returned UUID is then re-enqueued into Redis.

#### 3.3 Why Postgres-backed Retry Beats Redis-only Retry

A purely Redis-based approach would lose all job state if Redis is flushed, restarted without persistence enabled, or if the worker process dies after dequeuing from Redis but before writing any result. With Cortex RAG's approach:

- The job is committed to Postgres **before** being enqueued in Redis
- If the Redis enqueue fails after the Postgres commit, the job row sits at `status='queued'` and will be found by startup recovery
- If the worker dequeues from Redis and the process is killed mid-job, the job row sits at `status='running'` and will be reset and re-enqueued on next startup
- If Redis is completely wiped, the `on_startup` hook re-populates it from the ground truth in Postgres

Postgres is the durable audit log and source of truth; Redis is an ephemeral dispatch mechanism.

#### 3.4 The `job_timeout` Safety Net

ARQ's `job_timeout = 600` provides a second layer of protection. If a job is dequeued and processing starts, but Ollama hangs indefinitely (network partition, OOM, unresponsive endpoint), ARQ will hard-cancel the task coroutine after 600 seconds. At that point the job row in Postgres remains at `status='running'`. On the next worker restart, `on_startup` will find it and re-enqueue it. This means no job can be permanently stuck in `running` state as long as the worker eventually restarts.

---

### 4. File Type Support & Parsing

#### 4.1 Markdown with YAML Frontmatter

Markdown files (`.md`) are parsed using the `python-frontmatter` library:

```python
post = frontmatter.loads(text_content)
meta = dict(post.metadata)
```

`python-frontmatter` splits the file at the `---` delimiter boundaries: everything between the first `---` and the second `---` is parsed as YAML into `post.metadata`; everything after the closing `---` is the body, available as `post.content`. This means the markdown body passed to the chunker never contains the frontmatter YAML block.

The following frontmatter fields are extracted and mapped to document metadata:

| Frontmatter Key | Maps To | Notes |
|---|---|---|
| `title` | `title` | Direct mapping |
| `author` | `author` | Direct mapping |
| `category` | `category` | Direct mapping |
| `tags` | `tags` | Accepts YAML list or comma-separated string |
| `date` | `date` | If it's a Python `date`/`datetime` object (PyYAML auto-parses dates), `.isoformat()` is called; otherwise stored as-is |
| `source` | `source_url` | Primary alias |
| `url` | `source_url` | Fallback alias |
| `source_url` | `source_url` | Tertiary alias |

The `source_url` field accepts three key aliases because different knowledge-base publishing tools use different conventions. The resolution order is:

```python
source_url=meta.get("source") or meta.get("url") or meta.get("source_url"),
```

Any frontmatter keys not in this list are silently ignored.

#### 4.2 Plain Text Files

Plain text files (`.txt`) bypass frontmatter parsing entirely:

```python
if suffix == ".txt":
    req = IngestTextRequest(
        content=text_content,
        file_path=filename,
        title=Path(filename).stem.replace("-", " ").replace("_", " ").title(),
    )
```

Title derivation: the file stem (filename without extension) has hyphens and underscores replaced with spaces, then `.title()` is applied for title case. For example, `getting-started-with-rust_2024.txt` → `Getting Started With Rust 2024`. No author, category, tags, date, or source_url are populated for plain text files.

#### 4.3 Folder Walk

`FolderIngestService.list_files()` discovers all eligible files in a folder:

```python
@staticmethod
def list_files(folder: Path) -> list[Path]:
    return sorted(list(folder.glob("**/*.md")) + list(folder.glob("**/*.txt")))
```

Key behaviours:

- **Glob patterns**: `**/*.md` and `**/*.txt` — both use the `**` recursive wildcard, so the scan is fully recursive into all subdirectories regardless of depth. Only `.md` and `.txt` extensions are matched; other file types (`.pdf`, `.docx`, `.rst`, `.html`) are silently ignored.
- **Sorting**: The two glob results are concatenated and then sorted lexicographically via `sorted()`. This produces a deterministic, alphabetically ordered processing sequence, which makes the job logs and chunk indices reproducible across re-runs.
- **Relative path storage**: Inside `FolderIngestService.run()`, each file's `file_path` is computed as its path relative to the folder root: `rel_path = str(file.relative_to(folder))`. This means `file_path` values look like `subdir/article.md`, not `/absolute/path/to/subdir/article.md`. This makes the knowledge base portable — if the folder is moved, only the `folder_path` argument to the API needs to change, not the stored document paths.
- **Per-file error isolation**: Each file is processed inside a `try/except Exception` block. If one file fails (e.g., unreadable bytes, malformed frontmatter, Ollama timeout), the error is logged to `job_logs` and `stats["errors"]` is incremented, but the remaining files continue to be processed. A single bad file cannot abort the entire batch.
- **The `on_event` async callback pattern**: `FolderIngestService.run()` accepts an optional `on_event: Callable[[dict], Awaitable[None]]` parameter. This callback is invoked once at the start, once per file, and once at the end. In the worker context, the callback writes a `JobLog` row and flushes updated progress counters to the `ingestion_jobs` row after every file — not just at the end — so that polling clients get live progress.

---

### 5. Deduplication

#### 5.1 The SHA-256 Hash

Every ingest call computes a SHA-256 hash of the raw content string:

```python
file_hash = hashlib.sha256(req.content.encode()).hexdigest()
```

The hash is over the raw content bytes (UTF-8 encoded), not the normalised or stripped version. This ensures that any change to the source document — even adding a trailing newline — produces a different hash and triggers a re-index.

#### 5.2 The `file_path` UNIQUE Constraint

The `documents` table has:

```sql
file_path TEXT UNIQUE NOT NULL,
```

`file_path` is the identity key for a document across its entire lifetime. The deduplication lookup queries on this field:

```python
result = await self.db.execute(
    select(Document).filter(Document.file_path == file_path)
)
existing = result.scalars().first()
```

#### 5.3 The Three Cases

| Case | Condition | Action |
|---|---|---|
| **New document** | No row with this `file_path` | Insert new `Document` row, chunk, embed, insert `Chunk` rows |
| **Unchanged document** | Row exists, `file_hash` matches | Return `status="skipped"` immediately, no embedding work |
| **Changed document** | Row exists, `file_hash` differs | Update metadata on existing `Document` row, delete all old `Chunk` rows, re-chunk, re-embed, insert new `Chunk` rows |

The "unchanged" fast path is particularly important for folder scans — re-indexing a 1,000-file knowledge base where only 3 files changed should result in 997 `skipped` responses and only 3 actual Ollama embedding calls.

#### 5.4 Old Chunk Deletion on Update

When a document has changed, old chunks are explicitly deleted before new ones are inserted:

```python
await self.db.execute(
    delete(Chunk).where(Chunk.document_id == doc.id)
)
```

This is a targeted `DELETE` on the `Chunk` model (not on `Document`), which avoids triggering the cascade delete on the parent row. The `Document` row is **updated in place** — its UUID does not change. This means any external references to `documents.id` (search logs, bookmarks, etc.) remain valid across re-indexing.

---

### 6. Text Normalisation

`core/text_utils.py` exposes two functions: `strip_markdown()` and `count_tokens()`. Understanding precisely what each regex in `strip_markdown()` does — and where it is applied — is essential for understanding why search quality is not degraded by preprocessing.

#### 6.1 Every Regex in `strip_markdown()`

The function applies transformations in a fixed order. Order matters: fenced blocks must be handled before inline code, and images before links.

**Step 1 — Fenced code blocks**
```python
text = re.sub(r'```[^\n]*\n([\s\S]*?)```', r'\1', text)
```
Matches a triple-backtick fence opening (optionally followed by a language identifier on the same line: `[^\n]*`), any content across multiple lines (`[\s\S]*?` with non-greedy matching), and the closing fence. The fence markers and language tag are dropped; the code content is kept. `[\s\S]` is used instead of `.` because `.` does not match `\n` by default. Applied first because inline-code handling in step 2 could incorrectly match backticks inside a fenced block.

**Step 2 — Inline code**
```python
text = re.sub(r'`([^`]+)`', r'\1', text)
```
Matches a single backtick, one or more non-backtick characters, and the closing backtick. The backticks are stripped; the code content is kept.

**Step 3 — Images**
```python
text = re.sub(r'!\[[^\]]*\]\([^\)]*\)', '', text)
```
Matches the full Markdown image syntax `![alt text](url)`. The entire match is replaced with the empty string — images have no textual content useful for embedding.

**Step 4 — Hyperlinks**
```python
text = re.sub(r'\[([^\]]+)\]\([^\)]*\)', r'\1', text)
```
Matches Markdown link syntax `[link text](url)`. The URL is dropped; the link text is kept. Runs after image removal (step 3) to avoid accidentally matching the `[alt]` part of image syntax.

**Step 5 — Headings**
```python
text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
```
Matches 1–6 `#` characters at the start of a line (enforced by `re.MULTILINE`) followed by mandatory whitespace. The `#` prefix and space are stripped; the heading text is kept.

**Step 6 — Bold and italic (asterisk variants)**
```python
text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)
```
Matches 1–3 asterisks on each side of the emphasised content. Covers `*italic*`, `**bold**`, and `***bold-italic***`.

**Step 7 — Bold and italic (underscore variants)**
```python
text = re.sub(r'_{1,3}([^_\n]+)_{1,3}', r'\1', text)
```
Same structure as step 6 but for underscore markup: `_italic_`, `__bold__`, `___bold-italic___`.

**Step 8 — Blockquotes**
```python
text = re.sub(r'^>\s?', '', text, flags=re.MULTILINE)
```
Matches a `>` at the start of a line optionally followed by a single space. The `>` prefix is stripped; the quoted content is kept.

**Step 9 — Horizontal rules**
```python
text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
```
Matches a line consisting entirely of 3 or more `-`, `*`, or `_` characters. These are section dividers with no semantic content and are removed entirely.

**Step 10 — HTML tags**
```python
text = re.sub(r'<[^>]+>', '', text)
```
Matches any `<...>` construct. Handles common inline HTML found in Markdown files (`<br>`, `<span style="...">`, `<details>`, `<summary>`, etc.).

**Step 11 — Excessive blank lines**
```python
text = re.sub(r'\n{3,}', '\n\n', text)
```
Collapses any run of 3 or more consecutive newlines to exactly 2 newlines. Produces clean paragraph spacing after the previous transformations have removed headings, fences, etc., which often leave behind blank lines.

#### 6.2 Where `strip_markdown()` Is Applied

| Location | Applied? | Why |
|---|---|---|
| Before embedding (`embed_batch` call in ingest) | **Yes** | The embedding model receives clean plaintext, not raw markdown syntax |
| Inside `count_tokens()` calls (chunker) | **Yes** | Token counts reflect actual semantic content, not markdown syntax characters |
| `chunks.content` stored in DB | **No** | Raw markdown is stored — the FTS tsvector and any future rendering layer need the original markup |
| FTS query at retrieval time | **No** | `plainto_tsquery` treats markdown syntax as punctuation and discards it; stripping is redundant |

---

### 7. Chunking Strategy

Chunking is implemented in `core/chunker.py` (`chunk_by_headings`). The algorithm is a two-phase process: first split on structural heading boundaries, then apply a sliding-window sub-split to any section that exceeds the token budget.

#### 7.1 Heading Pattern

```python
heading_pattern = re.compile(r'^(#{1,3} .+)$', re.MULTILINE)
```

Only `#`, `##`, and `###` headings (H1, H2, H3) are treated as chunk boundaries. H4–H6 (`####` through `######`) are intentionally not split on. H4–H6 sections are typically too granular to constitute independently useful retrieval units — splitting on them would produce many tiny chunks that would be better merged.

The pattern requires:
- `^` — start of line (with `re.MULTILINE`)
- `#{1,3}` — exactly 1, 2, or 3 `#` characters
- ` ` — a mandatory space after the `#` run
- `.+` — at least one character of heading text
- The entire heading line is captured in group 1 due to the outer `(...)`

#### 7.2 `re.split()` with Capture Group — Alternating Segments

```python
parts = heading_pattern.split(content)
```

`re.split()` with a pattern that contains a capturing group includes the captured text in the output list. For a document like:

```
Preamble text

# First Section
Section content

## Subsection
Subsection content
```

`parts` will be:
```python
["Preamble text\n\n", "# First Section", "\nSection content\n\n", "## Subsection", "\nSubsection content"]
```

The list alternates between non-heading segments (indices 0, 2, 4, …) and captured heading strings (indices 1, 3, …). The assembly loop identifies headings by re-matching `heading_pattern.match(part)`, collects text into a buffer until the next heading is encountered, then emits a `(heading, body)` tuple.

#### 7.3 Token Counting: `len(text) // 4`

```python
def count_tokens(text: str) -> int:
    return max(1, len(text) // 4)
```

Token count is approximated as character length divided by 4. This is a deliberate engineering trade-off:

- **Not BERT**: `nomic-embed-text` uses a LLaMA BPE tokenizer, not the WordPiece tokenizer used by `bert-base-uncased`. Loading BERT's tokenizer and running it on every chunk during ingestion would produce systematically incorrect counts because BPE and WordPiece tokenise differently, especially for code, URLs, and CamelCase identifiers.
- **Not tiktoken**: Loading tiktoken adds a dependency and ~50ms of initialisation per process. For chunking purposes, precision is not required — the goal is to avoid grossly over- or under-sized chunks, not to hit an exact token boundary.
- **`len(text) // 4` is conservative**: The actual BPE token count for English prose is typically `len / 3.5` to `len / 4`. Using `// 4` slightly overestimates token count, which means chunks will be slightly smaller than `chunk_max_tokens` in practice. This is the safe direction.
- **`max(1, ...)`**: Prevents returning 0 for very short strings, which would cause edge cases downstream.

#### 7.4 Tiny-Section Merge Threshold (50 Tokens)

```python
if _token_count(text) < 50:
    pending_heading = pending_heading or heading
    pending_text += f"\n\n{heading or ''}\n{text}" if heading else f"\n\n{text}"
    continue
```

Any section with fewer than 50 tokens (~200 characters) is not emitted as a standalone chunk. Instead, it is accumulated in `pending_text` with its heading appended inline. The `pending_heading` captures the first heading of the accumulated group. This buffer is flushed when the next non-tiny section is encountered, or at the end of the document.

The 50-token threshold ensures that stub sections like `## See Also` with a short bullet list are merged with adjacent content rather than becoming isolated chunks that flood retrieval results with low-information matches.

#### 7.5 `_split_long()` — Sliding Window Algorithm

When a section exceeds `chunk_max_tokens` (default: 400), `_split_long()` is called:

```python
def _split_long(text: str, heading: str, start_index: int) -> list:
    max_tokens = settings.chunk_max_tokens
    words = text.split(" ")
    word_lens = [len(w) for w in words]
    chunks = []
    sub_idx = 0
    lo = 0

    while lo < len(words):
        char_count = 0
        hi = lo
        while hi < len(words):
            next_chars = word_lens[hi] + (1 if hi > lo else 0)
            if (char_count + next_chars) // 4 > max_tokens:
                break
            char_count += next_chars
            hi += 1

        hi = max(lo + 1, hi)  # always advance at least one word
        chunk_text = " ".join(words[lo:hi]).strip()
        if heading:
            chunk_text = f"{heading}\n\n{chunk_text}"
        if chunk_text:
            chunks.append({
                "text": chunk_text,
                "heading": heading,
                "chunk_index": start_index + sub_idx,
                "token_count": _token_count(chunk_text),
            })
            sub_idx += 1
        if hi >= len(words):
            break
        overlap_words = max(1, settings.chunk_overlap_chars // 4)
        lo = hi - overlap_words
    return chunks
```

The exact algorithm step-by-step:

1. **Tokenise to words**: `words = text.split(" ")` — simple space splitting. This is intentional; splitting on all whitespace would lose paragraph structure.
2. **Pre-compute word lengths**: `word_lens = [len(w) for w in words]` — computed once upfront so the inner loop does not repeatedly call `len()` on substrings.
3. **Inner window loop**: Starting from `lo`, advance `hi` word by word. For each word, compute `next_chars = word_lens[hi] + (1 if hi > lo else 0)` — the word length plus the space that precedes it (but not before the first word). Add to `char_count`. When `(char_count + next_chars) // 4 > max_tokens`, stop advancing.
4. **Safety guard**: `hi = max(lo + 1, hi)` ensures at least one word is always consumed, preventing an infinite loop if a single word is longer than `max_tokens * 4` characters.
5. **Emit chunk**: Join `words[lo:hi]`, prepend the heading if present, and append to results.
6. **Overlap step-back**: `overlap_words = max(1, settings.chunk_overlap_chars // 4)`. With `chunk_overlap_chars = 200` (default), `overlap_words = 200 // 4 = 50`. The next window starts at `lo = hi - 50`, so 50 words from the end of the previous chunk are repeated at the start of the next chunk.
7. **Heading prepended to every sub-chunk**: Every sub-chunk emitted by `_split_long` gets the section heading prepended. This means every chunk is self-contained — when a retrieval result returns chunk 3 of a long section, the heading context is preserved.

The overlap strategy ensures that sentences split across a chunk boundary appear in both chunks, so queries that match words near that boundary can still retrieve the relevant content.

#### 7.6 Chunk Data Structure

Every element in the returned list has this shape:

```python
{
    "text": str,           # Full chunk text, including heading if present
    "heading": str | None, # The section heading (e.g., "## Installation"), or None
    "chunk_index": int,    # Zero-based index within the document
    "token_count": int,    # Estimated token count of the text field (after strip_markdown)
}
```

---

### 8. Embedding Generation

#### 8.1 Singleton `httpx.AsyncClient`

```python
_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=settings.ollama_timeout)
    return _client
```

A single `httpx.AsyncClient` instance is created lazily on the first embed call and reused for all subsequent requests within the worker process. This is critical for performance: `httpx.AsyncClient` maintains a connection pool, and reusing it avoids TCP handshake overhead on every embedding request. The timeout is set from `settings.ollama_timeout` (default: `60.0` seconds), which applies to the full request-response cycle including the Ollama inference time.

#### 8.2 Batch Size 10

```python
_BATCH_SIZE = 10

async def embed_batch(texts: list[str]) -> list[list[float]]:
    results: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        vecs = await _embed_request(batch)
        if vecs:
            _check_dim(vecs[0])
        results.extend(vecs)
    return results
```

Chunks are sent to Ollama in batches of at most 10. The rationale is twofold:

1. **OOM prevention**: Ollama loads the model into VRAM and runs inference for all inputs in a batch in a single forward pass. Very large batches (50+ chunks of 400 tokens each) can exceed available VRAM on consumer GPUs (8–16GB), causing Ollama to OOM-kill the embedding request.
2. **Timeout avoidance**: Larger batches take longer per-request. A batch of 10 × 400-token chunks completes within the 60-second timeout on typical hardware; a batch of 100 might not.

The tradeoff is more HTTP round trips per document. For a document with 50 chunks, this is 5 round trips instead of 1, but the latency penalty of each empty round trip is negligible compared to Ollama inference time.

#### 8.3 Exact Retry Logic

```python
for attempt in range(settings.embed_max_retries + 1):
    try:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()["embeddings"]
    except Exception as e:
        last_exc = e
        if attempt < settings.embed_max_retries:
            logger.warning("Embedding attempt %s failed, retrying: %s", attempt + 1, e)

raise UpstreamError(f"Embedding failed via Ollama ({settings.embed_model}): {last_exc}")
```

With `embed_max_retries = 1` (default), the loop runs for `range(2)` — attempts 0 and 1. On attempt 0: if it fails, log a warning and proceed to attempt 1. On attempt 1: if it fails, exit the loop and raise `UpstreamError`. There is no sleep between retries. A brief transient failure (Ollama momentarily busy) may be recovered by one immediate retry; a structural failure (Ollama crashed, out of VRAM) will not recover with additional retries, so failing fast is the right behaviour.

#### 8.4 Dimension Validation

```python
_EXPECTED_DIM = 768

def _check_dim(vec: list[float]) -> None:
    if len(vec) != _EXPECTED_DIM:
        raise UpstreamError(
            f"Expected {_EXPECTED_DIM}-dim embedding from {settings.embed_model}, got {len(vec)}. "
            "Check embed_model in config matches the vector(768) in schema.sql."
        )
```

After every embedding request (checked on the first vector in each batch), the dimension is validated against `_EXPECTED_DIM = 768`. If the configured `embed_model` is changed to one with a different output dimension (e.g., `mxbai-embed-large` which produces 1024-dim vectors), this check fails loudly before any data is written, with an explicit pointer to the schema mismatch.

#### 8.5 `nomic-embed-text` Model Details

- **Architecture**: Modified BERT (encoder-only) with Rotary Position Embeddings (RoPE), trained by Nomic AI
- **Context window**: 8192 tokens — vastly larger than standard BERT's 512-token limit, so even long chunks are never silently truncated
- **Output dimension**: 768
- **Tokenizer**: LLaMA-family BPE (not WordPiece — which is why `bert-base-uncased` token counts would be wrong)
- **Why chosen**: Runs locally via Ollama (no API key or egress), 8192-token context window, 768-dim output compact enough for fast ANN search, strong MTEB retrieval benchmark scores for English technical content

Before sending text to Ollama, `strip_markdown` is applied (`texts = [strip_markdown(c["text"]) for c in chunks]`). The model receives clean plaintext rather than markdown syntax. This improves embedding quality because the model's training corpus was predominantly plaintext, and markdown punctuation (`##`, `**`, `[]()`) adds noise to the semantic signal.

---

### 9. Storage

#### 9.1 `documents` Table

```sql
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
```

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | Stable identifier; never changes across re-indexing |
| `file_path` | `TEXT UNIQUE NOT NULL` | Deduplication key; the logical identity of the document |
| `file_hash` | `TEXT NOT NULL` | SHA-256 hex digest; determines if content has changed |
| `title` | `TEXT` | Display name; from frontmatter or filename derivation |
| `author` | `TEXT` | Provenance metadata |
| `source_url` | `TEXT` | Original URL if document was fetched from the web |
| `category` | `TEXT` | Single categorical label for filtering |
| `tags` | `TEXT[]` | Native Postgres array; supports GIN-indexed `&&` overlap queries |
| `doc_date` | `DATE` | Publication/creation date from frontmatter |
| `raw_content` | `TEXT` | The full original document text (with markdown intact) |
| `created_at` | `TIMESTAMPTZ` | Set once at insert |
| `updated_at` | `TIMESTAMPTZ` | Updated on re-index |

#### 9.2 `chunks` Table

```sql
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

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS fts tsvector
    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;
```

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | New UUID generated for each chunk on each ingest (even for re-indexed documents) |
| `document_id` | `UUID REFERENCES documents(id) ON DELETE CASCADE` | Cascades deletion to all chunks when parent document is deleted |
| `content` | `TEXT NOT NULL` | Raw markdown chunk text as produced by the chunker — not stripped |
| `embedding` | `vector(768)` | 768-dimensional float vector from `nomic-embed-text`; used for ANN cosine similarity search |
| `chunk_index` | `INTEGER NOT NULL` | Zero-based ordering within document |
| `heading` | `TEXT` | The section heading for this chunk, stored separately for display |
| `token_count` | `INTEGER` | Estimated token count as computed during chunking |
| `fts` | `tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED` | See §9.3 |

#### 9.3 The `fts` Generated Column

```sql
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS fts tsvector
    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;
```

This is a `GENERATED ALWAYS AS ... STORED` column — Postgres computes and stores the value automatically whenever `content` is inserted or updated. The application never needs to compute or write this column; it is always in sync with `content`.

`to_tsvector('english', content)` applies Postgres's `english` text search configuration:

1. **Tokenisation**: The content is split into lexemes. Punctuation and markdown characters remaining in `content` are treated as token delimiters.
2. **Stop word removal**: Common English stop words (`the`, `is`, `at`, `which`, `on`, etc.) are removed. The `english` dictionary includes ~571 stop words.
3. **Porter stemming**: Each remaining token is reduced to its stem. For example: `running` → `run`, `embeddings` → `embed`, `installation` → `instal`. This means a query for `install` will match chunks containing `installation`, `installing`, or `installed`.

The resulting `tsvector` is a sorted list of lexemes with their positions, stored in a compact binary format. The GIN index on `fts` allows `@@` operator queries to run in O(log N) time.

**No application sync code is needed.** Insert a chunk, the `fts` column updates. Update the content, `fts` updates. This eliminates an entire class of bug (stale search index) that plagues dual-write approaches.

#### 9.4 Indexes

```sql
-- Vector ANN: cosine ops, 100 Voronoi cells
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Full-text search
CREATE INDEX IF NOT EXISTS idx_chunks_fts         ON chunks USING gin (fts);

-- FK lookup (for cascade deletes and per-document chunk retrieval)
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks (document_id);

-- Metadata filtering on documents
CREATE INDEX IF NOT EXISTS idx_documents_tags       ON documents USING gin (tags);
CREATE INDEX IF NOT EXISTS idx_documents_category   ON documents (category);
CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents (updated_at DESC);
```

| Index | Type | Purpose |
|---|---|---|
| `idx_chunks_embedding` | `ivfflat` with `vector_cosine_ops`, `lists=100` | ANN cosine similarity search. `lists=100` means 100 Voronoi cells; at query time `ivfflat.probes=10` cells are searched |
| `idx_chunks_fts` | `GIN` on `tsvector` | Full-text search using `@@` and `plainto_tsquery` |
| `idx_chunks_document_id` | `btree` on `UUID` | Fast FK lookups for cascade deletes and per-document chunk retrieval |
| `idx_documents_tags` | `GIN` on `TEXT[]` | Supports `tags && ARRAY['rust']::text[]` overlap queries for filtering |
| `idx_documents_category` | `btree` | Equality filter `WHERE category = 'tutorials'` |
| `idx_documents_updated_at` | `btree DESC` | Efficient `ORDER BY updated_at DESC` for the `list_documents` endpoint |

#### 9.5 `ivfflat.probes=10` Per-Connection Setting

The `ivfflat.probes` GUC controls how many of the 100 Voronoi cells are scanned during a vector query:

- `probes=1` (pgvector default): Only the nearest cell is searched — fastest but lowest recall.
- `probes=10`: 10% of cells are searched — good recall/speed trade-off for a 100-list index. This is `sqrt(lists)`, the heuristic from the pgvector documentation.
- `probes=100`: All cells searched — equivalent to exact search, maximum recall but slower.

With `lists=100` and `probes=10`, the expected recall is approximately 95–98% for typical English text embeddings, with a 10× speedup over exact search.

---

### 10. Job Lifecycle & Audit Log

#### 10.1 Status Transitions

```
queued → running → done
                 → failed
```

| Status | Set By | Meaning |
|---|---|---|
| `queued` | `_enqueue()` in `documents.py` (initial insert) | Job has been committed to Postgres and sent to Redis; not yet started by a worker |
| `queued` | `on_startup` crash recovery | Job was previously `running` but the worker was killed; reset for retry |
| `running` | Worker's `_update_stats(status="running")` | Worker has loaded the job and begun processing |
| `done` | Worker's `_update_stats(status="done", result=...)` | All processing completed successfully |
| `failed` | Worker's `_update_stats(status="failed", error=...)` | An unrecoverable error occurred |

The `status` column has a `CHECK` constraint:

```sql
status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed'))
```

#### 10.2 `result` JSONB Column — Shape Per Job Kind

On completion, the `result` JSONB column is populated with a summary of what the job accomplished:

**File job** (`kind='file'`):
```json
{
  "status": "ok",
  "document_id": "3f7a1c2d-9e4b-4f1a-8b5c-2a1d3e4f5678",
  "file": "my-article.md",
  "chunks": 12,
  "title": "My Article Title"
}
```

**Folder job** (`kind='folder'`):
```json
{
  "added": 47,
  "updated": 3,
  "skipped": 12,
  "errors": 1,
  "total": 63
}
```

#### 10.3 Progress Counters

Beyond the final `result` JSONB, the `ingestion_jobs` table carries live progress counters that are updated after every file (for folder jobs) or once on completion (for file/text jobs):

```sql
total       INTEGER NOT NULL DEFAULT 0,  -- total files to process
processed   INTEGER NOT NULL DEFAULT 0,  -- files completed (any outcome)
added       INTEGER NOT NULL DEFAULT 0,  -- new documents inserted
updated     INTEGER NOT NULL DEFAULT 0,  -- existing documents re-indexed
skipped     INTEGER NOT NULL DEFAULT 0,  -- unchanged documents (dedup hit)
errors      INTEGER NOT NULL DEFAULT 0,  -- files that failed
```

These allow a polling client (`GET /jobs/{job_id}`) to display a real-time progress bar without waiting for the full job to complete.

#### 10.4 `job_logs` Rows — Per-File Audit Trail

Every file processed by the worker generates at least one `job_logs` row:

```sql
CREATE TABLE IF NOT EXISTS job_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id      UUID NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
    level       TEXT NOT NULL DEFAULT 'info' CHECK (level IN ('info', 'warn', 'error')),
    message     TEXT NOT NULL,
    file        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Example log messages written during a folder job:

| Level | Message | File |
|---|---|---|
| `info` | `added: docs/getting-started.md (8 chunks)` | `docs/getting-started.md` |
| `info` | `skipped (unchanged): docs/faq.md` | `docs/faq.md` |
| `info` | `updated: docs/api-reference.md (23 chunks)` | `docs/api-reference.md` |
| `error` | `error: docs/broken.md — 'utf-8' codec can't decode byte 0xff` | `docs/broken.md` |

Logs cascade-delete when the parent `ingestion_jobs` row is deleted.

#### 10.5 Why Postgres Is the Durable Audit Log, Not Redis

ARQ stores its own result record in Redis with `keep_result = 3600` (1 hour). This is ephemeral and minimal. The full audit trail is in Postgres because:

1. **Durability**: Redis without AOF/RDB persistence loses all data on restart. Postgres is ACID-transactional and WAL-replicated.
2. **Queryability**: SQL queries on `job_logs` can answer questions like "which files in the last folder job failed?" — Redis cannot express these queries.
3. **Long-term retention**: `keep_result = 3600` means ARQ's Redis record expires after 1 hour. The Postgres job row and its logs are retained indefinitely.
4. **Crash recovery dependency**: The crash recovery mechanism in `on_startup` depends on reading job status from Postgres. If job state were Redis-only, a Redis restart would erase all knowledge of in-progress jobs with no recovery path.

---

## Retrieval Pipeline

The retrieval pipeline is the core of Cortex RAG's search capability. Every call to `POST /search` passes through a deterministic sequence of stages: query normalisation, hybrid retrieval (vector + full-text), reciprocal rank fusion, optional cross-encoder reranking, and result serialisation. The entire pipeline is implemented in `controllers/query.py` (`QueryController`), with the HTTP layer in `api/routes/search.py`.

---

### 1. Search Request and Query Normalisation

#### The `SearchRequest` Schema

All search traffic enters through `POST /search`, whose body is validated by the `SearchRequest` Pydantic model:

```python
class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=100)
    rerank: bool = True
    filters: dict[str, Any] | None = None
```

| Field | Type | Default | Constraint | Semantics |
|---|---|---|---|---|
| `query` | `str` | required | 1–2000 chars | The natural-language question or passage to retrieve against |
| `top_k` | `int` | `5` | 1–100 | Final number of chunks to return to the caller |
| `rerank` | `bool` | `True` | — | Whether to run the cross-encoder reranker on the RRF candidates |
| `filters` | `dict \| None` | `None` | see §2 | Optional metadata pre-filters applied to both retrieval branches |

Pydantic enforces these constraints before any pipeline logic runs. A `query` that exceeds 2000 characters is rejected at the schema layer with a 422 before a single database round-trip occurs.

#### Two Versions of the Query

The very first statements inside `QueryController.search()` produce two derived forms of the input query:

```python
async def search(self, req: SearchRequest) -> list[dict]:
    where_sql, where_params = self._build_filter(req.filters)
    embedding = await embed(strip_markdown(req.query))

    vec_rows, fts_rows = (
        await self._vector_search(embedding, where_sql, where_params),
        await self._fts_search(req.query, where_sql, where_params),
    )
```

The pipeline never uses `req.query` directly for the vector branch. Instead it calls `strip_markdown(req.query)` before passing it to the embedder. For the full-text search branch, it passes `req.query` unmodified.

**Why two forms?**

The embedding model (`nomic-embed-text`) was trained on plain prose. When it encounters Markdown syntax — `##`, `**bold**`, `` `code` ``, `![image](url)` — those tokens dilute the semantic signal. A query like `## How does authentication work?` would produce a vector biased by the heading marker rather than by the semantic content of the question. `strip_markdown` removes all such noise before the text is handed to the embedder.

The FTS branch, by contrast, operates on PostgreSQL `tsvector`/`tsquery` machinery that natively ignores stop words and applies stemming. `plainto_tsquery('english', ...)` does not interpret `#` or `*` as special characters — they are treated as plain text and discarded as punctuation during lexeme extraction. Passing the original query to FTS preserves any technical terms exactly as the user typed them.

---

### 2. Metadata Filters

Filters allow callers to narrow the retrieval corpus before any similarity computation occurs. If you know you want only documents in `category = "engineering"` from the last 90 days, constraining the ANN search to that sub-population eliminates both irrelevant results and wasted index traversal.

#### Filter Builder — Exact Code

```python
def _build_filter(self, filters: dict | None) -> tuple[str, dict]:
    if not filters:
        return "", {}

    clauses = []
    params = {}

    if filters.get("tags"):
        clauses.append("d.tags && :tags")
        params["tags"] = filters["tags"]
    if filters.get("category"):
        clauses.append("d.category = :category")
        params["category"] = filters["category"]
    if filters.get("date_from"):
        clauses.append("d.doc_date >= :date_from")
        params["date_from"] = filters["date_from"]
    if filters.get("date_to"):
        clauses.append("d.doc_date <= :date_to")
        params["date_to"] = filters["date_to"]

    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where_sql, params
```

The method returns a 2-tuple of a raw SQL fragment and a named-parameter dict. Both are passed into both `_vector_search` and `_fts_search` identically, meaning filters apply to both retrieval branches with zero risk of drift.

#### Filter Semantics

**`tags` — Array Overlap (`&&`)**

```sql
d.tags && :tags
```

The `&&` operator is the PostgreSQL array overlap operator: it returns `TRUE` if the left array and the right array share at least one element. `d.tags` is a `TEXT[]` column on the `documents` table. This is an ANY-match (union), not an ALL-match (intersection). The `idx_documents_tags` index is a GIN index, which builds an inverted index from array elements to row pointers, making `&&` capable of index-only scans rather than sequential array comparisons.

**`category` — Equality**

```sql
d.category = :category
```

A plain B-tree equality match. Because `category` is a low-cardinality column (typically a small set of strings like `"engineering"`, `"product"`, `"legal"`), the planner may choose a bitmap index scan or even a sequential scan if the selectivity is low.

**`date_from` / `date_to` — Range on `doc_date`**

```sql
d.doc_date >= :date_from
d.doc_date <= :date_to
```

Both bounds are inclusive. Both conditions are added independently: you can supply either bound alone or both together.

#### SQL JOIN to `documents`

All filters reference `d.*` columns, which means both the vector search and FTS search must JOIN to `documents`:

```sql
FROM chunks c
JOIN documents d ON d.id = c.document_id
{where_sql}
```

`c.document_id` is indexed with a dedicated B-tree index (`idx_chunks_document_id`), making this join efficient.

---

### 3. Vector Search

Vector search finds the `chunks` whose stored embeddings are most semantically similar to the query embedding. The similarity metric is cosine similarity, which measures the angle between two vectors in 768-dimensional space, making it invariant to embedding magnitude.

#### Exact SQL

```python
async def _vector_search(self, embedding: list[float], where_sql: str, where_params: dict) -> list:
    sql = text(f"""
        SELECT c.id, c.content, c.heading, c.document_id,
               1 - (c.embedding <=> CAST(:embedding AS vector)) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        {where_sql}
        ORDER BY c.embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
    """)
    params = {"embedding": str(embedding), "limit": settings.vector_search_limit}
    params.update(where_params)
    result = await self.db.execute(sql, params)
    return result.fetchall()
```

Breaking down every element:

**`c.embedding <=> CAST(:embedding AS vector)`**

`<=>` is the pgvector cosine distance operator. It computes `1 - cosine_similarity(a, b)`, so a distance of `0.0` means identical vectors and a distance of `2.0` means opposite directions. The `CAST(:embedding AS vector)` is necessary because SQLAlchemy passes the embedding as a Python string (via `str(embedding)`, which serialises the Python list as `[0.123, -0.456, ...]`) and PostgreSQL needs to cast that text literal to the `vector` type before the operator can be applied.

**`1 - (c.embedding <=> ...) AS score`**

The distance is subtracted from 1 to produce a similarity score in the range `[-1, 1]`, where values closer to `1` indicate higher similarity. This `score` is carried through for debugging, but the RRF step cares only about rank position, not the raw score value.

**`ORDER BY c.embedding <=> CAST(:embedding AS vector)`**

The `ORDER BY` is on the raw distance (ascending). PostgreSQL requires that the indexed expression matches the ORDER BY expression exactly for the IVFFlat index to be invoked.

**`LIMIT :limit` — `vector_search_limit = 50`**

The pipeline retrieves up to 50 candidates from the vector branch before fusion. This is deliberate over-retrieval: the final `top_k` is typically 5–20, but pulling 50 candidates gives the RRF and reranker enough material to surface relevant chunks that a pure top-5 cutoff might miss.

#### IVFFlat Index

```sql
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

The index type is IVFFlat (Inverted File with Flat quantisation):

1. **Training phase**: k-means clustering of all stored embeddings into `lists = 100` Voronoi cells (centroids). This happens at `CREATE INDEX` time and is recomputed on `REINDEX`.
2. **Query phase**: Given a query vector, the index identifies the `probes` nearest centroids and scans only the embeddings assigned to those cells. The full 768-dimension cosine distance is computed for candidates within the selected cells.

`vector_cosine_ops` tells the index to use cosine distance, which must match the `<=>` operator used in queries.

**Practical effect of `probes=10` with `lists=100`**: With `probes = 1` (pgvector default), each query inspects only 1% of all stored embeddings. With `probes = 10`, it inspects 10%. For a 100,000-chunk corpus, the difference is scanning ~1,000 vs ~10,000 vectors — still far faster than a full sequential scan of 100,000 vectors. Expected recall at probes=10 is approximately 95–98%.

#### Embedding Generation at Query Time

Before the SQL executes, the query text must be embedded. The `embed()` function in `core/embedder.py` calls Ollama's `/api/embed` endpoint and validates the dimension:

```python
async def embed(text: str) -> list[float]:
    vec = (await _embed_request(text))[0]
    _check_dim(vec)   # must be exactly 768
    return vec
```

The connection pool uses `settings.ollama_timeout = 60.0` seconds and `settings.embed_max_retries = 1`: a single retry on transient failure, then a clean `503 UpstreamError`.

---

### 4. Full-Text Search

The FTS branch retrieves chunks using PostgreSQL's native lexeme-matching machinery. Unlike vector search, which captures semantic proximity, FTS captures exact or stemmed term overlap. A query for "PostgreSQL JSONB" will always score chunks that contain those exact tokens highly, regardless of whether the embedding model considers them semantically distant from other paraphrases. The two branches fail differently and are therefore genuinely complementary.

#### The `fts` Generated Column

As described in the ingestion section (§9.3), the `fts` column is:

```sql
fts tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
```

`GENERATED ALWAYS AS ... STORED` means PostgreSQL computes and stores the `tsvector` at insert/update time. The `fts` column is always in sync with `content` — there is no risk of stale search index data. No application-level sync code is required.

#### Exact SQL

```python
async def _fts_search(self, query_text: str, where_sql: str, where_params: dict) -> list:
    fts_where = (
        where_sql + " AND c.fts @@ plainto_tsquery('english', :query_text)"
        if where_sql
        else "WHERE c.fts @@ plainto_tsquery('english', :query_text)"
    )
    sql = text(f"""
        SELECT c.id, c.content, c.heading, c.document_id,
               ts_rank(c.fts, plainto_tsquery('english', :query_text)) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        {fts_where}
        ORDER BY score DESC
        LIMIT :limit
    """)
    params = {"query_text": query_text, "limit": settings.fts_search_limit}
    params.update(where_params)
    result = await self.db.execute(sql, params)
    return result.fetchall()
```

**FTS WHERE clause construction**

The FTS predicate `c.fts @@ plainto_tsquery(...)` must be ANDed onto the existing WHERE clause if metadata filters are active, or must introduce its own `WHERE` keyword if no metadata filters are active. The ternary handles both cases, producing either:
- `WHERE d.category = :category AND c.fts @@ plainto_tsquery('english', :query_text)` (filters active), or
- `WHERE c.fts @@ plainto_tsquery('english', :query_text)` (no filters)

**`plainto_tsquery` vs `to_tsquery`**

- `to_tsquery('english', 'authentication & tokens')` requires the caller to supply `tsquery` syntax (`&` for AND, `|` for OR, `!` for NOT). Passing a natural-language sentence to `to_tsquery` will raise a PostgreSQL error if it encounters stop words or punctuation in invalid positions.
- `plainto_tsquery('english', 'how does authentication work with tokens')` accepts arbitrary natural language. It extracts the non-stop-word lexemes, applies stemming, and ANDs them together automatically.

For a system whose queries come from either a human typing a question or from Claude generating a search call, `plainto_tsquery` is the correct choice.

**`@@` — The Match Operator**

The `@@` operator tests whether a `tsvector` matches a `tsquery`. The GIN index on `fts` makes this a set-intersection lookup rather than a row-by-row scan.

**`ts_rank(c.fts, plainto_tsquery('english', :query_text)) AS score`**

`ts_rank` produces a floating-point relevance score combining:
1. **Term frequency**: how many times the query lexemes appear in the document.
2. **Lexeme position**: whether query terms appear in early positions (positional weighting).
3. **Cover density**: how close together the query terms appear for multi-term queries.

The result is a non-standardised float. Scores from `ts_rank` are meaningful only within a single query's result set. This is why the pipeline uses RRF for fusion rather than summing or averaging the raw scores.

**Why the original query (not stripped) is used for FTS**

`plainto_tsquery` treats Markdown syntax as punctuation and discards it during lexeme extraction. Passing the original query preserves technical tokens like function names, version strings, and other identifiers that the user typed. Stripping Markdown before FTS would be redundant.

---

### 5. Reciprocal Rank Fusion

After the vector and FTS branches each return up to 50 rows, the pipeline must merge them into a single ranked list. Reciprocal Rank Fusion (RRF) is the algorithm used.

#### Exact Python Implementation

```python
@staticmethod
def _reciprocal_rank_fusion(vector_rows: list, fts_rows: list, k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for rank, row in enumerate(vector_rows):
        cid = str(row.id)
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    for rank, row in enumerate(fts_rows):
        cid = str(row.id)
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return [cid for cid, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]
```

#### Score Formula

For a chunk `c` appearing at 0-based rank `r` in one result list, its RRF contribution is:

```
RRF_score(c, r) = 1 / (k + r + 1)
```

where `k = 60`. The `+1` in the denominator converts from 0-based rank to 1-based rank. If `c` appears in both the vector list (rank `r_v`) and the FTS list (rank `r_f`), its total score is:

```
RRF_total(c) = 1/(k + r_v + 1) + 1/(k + r_f + 1)
```

This additive property is the key feature of RRF: a chunk that ranks well in both retrieval systems scores higher than one that excels in only one, without requiring the individual scores to be on the same scale.

#### The Smoothing Constant `k = 60`

The constant `k = 60` comes directly from the original RRF paper by Cormack, Clarke, and Buettcher (SIGIR 2009). Its purpose is to prevent the formula from becoming too sensitive to the difference between rank 1 and rank 2 at the very top of the lists:

- Without `k`: rank 1 scores `1/1 = 1.000`, rank 2 scores `1/2 = 0.500` — a 2× gap.
- With `k = 60`: rank 1 scores `1/61 ≈ 0.01639`, rank 2 scores `1/62 ≈ 0.01613` — a tiny gap.

| Rank | `1/(60 + rank + 1)` |
|---|---|
| 0 (1st) | 0.016393 |
| 4 (5th) | 0.015385 |
| 9 (10th) | 0.014286 |
| 19 (20th) | 0.012500 |
| 49 (50th) | 0.009091 |

The difference between 1st and 50th place is a factor of only 1.8×, whereas raw similarity scores might differ by an order of magnitude. This compression makes the fusion outcome stable even when one retrieval branch is noisier than the other. A chunk that ranks 1st in one list and 20th in the other will still beat a chunk that ranks 5th in only one list.

#### Why RRF Over Learned Fusion

An alternative to RRF is a learned fusion model (e.g., a linear combination of the two scores with weights trained on labelled query-document pairs). RRF is preferred here for three reasons:

1. **No labelled data available**: Learning optimal fusion weights requires thousands of human-annotated `(query, relevant_chunks)` pairs. A local knowledge base does not have this. RRF requires zero training data.
2. **Parameter-free across domains**: The `k = 60` constant was validated across 11 different TREC datasets in the original paper and proved robust. It does not need to be tuned per-corpus.
3. **Score-free input**: RRF requires only the ranked ordering from each system, not the raw similarity scores. This means `ts_rank` values (which are not normalised) and cosine distances (which are bounded differently) can be combined without any normalisation step.

#### Truncation to `rerank_top_n = 20`

After sorting the merged `scores` dict by value descending:

```python
merged_ids = self._reciprocal_rank_fusion(vec_rows, fts_rows)
top_ids = merged_ids[:settings.rerank_top_n]
```

`settings.rerank_top_n = 20`. At most 20 chunk IDs are passed to `_fetch_candidates()` and subsequently to the cross-encoder reranker. The 20-candidate limit is the latency/accuracy tradeoff knob: more candidates increase the chance of surfacing a highly relevant chunk, but also increase reranker inference time linearly.

---

### 6. Cross-Encoder Reranking

The cross-encoder reranker is a neural model that takes a `(query, passage)` pair and produces a single relevance score. Unlike the bi-encoder used for vector retrieval (which encodes query and passage separately), the cross-encoder sees both texts jointly, allowing full attention between query and passage tokens. This produces significantly higher-quality relevance judgements at the cost of being too slow for retrieval-stage use.

#### Lazy Singleton Pattern

The model is loaded on first use, not at server startup:

```python
_model = None

def _get_model() -> CrossEncoder:
    global _model
    if _model is None:
        t0 = time.perf_counter()
        _model = CrossEncoder(settings.rerank_model)
        logger.info("Reranker loaded (%s) in %.2fs", settings.rerank_model, time.perf_counter() - t0)
    return _model
```

Loading the model involves downloading from Hugging Face Hub (first run only), deserialising the PyTorch checkpoint, and initialising the `CrossEncoder` wrapper from `sentence-transformers`. The lazy pattern means the first search request that includes `rerank: true` will experience extra latency (typically 1–3 seconds), but subsequent requests pay only inference time. The `logger.info` call records the load time, giving operators visibility into this one-time cost.

#### Model Details: `cross-encoder/ms-marco-MiniLM-L-6-v2`

| Property | Value |
|---|---|
| Architecture | MiniLM-L-6 (6 Transformer layers, 12 attention heads per layer) |
| Parameters | ~22 million |
| Model size on disk | ~85 MB |
| Training dataset | MS MARCO Passage Ranking (~8.8M passages from Bing search click-through data) |
| Task | Binary relevance classification (relevant / not relevant) |
| Input format | `[CLS] query [SEP] passage [SEP]` |
| Max input length | 512 tokens (tokenised with MiniLM WordPiece tokeniser) |
| Output | Single raw logit — higher = more relevant |

The input format `[CLS] query [SEP] passage [SEP]` is the BERT cross-encoder convention: the query and passage are concatenated with the separator token, allowing every attention head to attend to every token in both the query and the passage simultaneously. This joint attention is why cross-encoders are more accurate than bi-encoders for relevance scoring: the model can explicitly compute "does the phrase 'connection pool' in the passage match the implied intent of the query 'how does the database handle concurrent requests'?" Bi-encoders cannot do this because the query and passage embeddings are computed independently and compared only via a dot product.

#### `anyio.to_thread.run_sync` — Async Safety

The cross-encoder calls PyTorch's `model.predict()`, which is CPU-bound computation. If this were called directly in an `async` function, it would block the asyncio event loop for the entire inference duration (~50–200ms), preventing the server from handling any other requests during that time:

```python
async def rerank_async(query: str, candidates: list[dict], top_n: int) -> list[dict]:
    return await anyio.to_thread.run_sync(rerank, query, candidates, top_n)
```

`anyio.to_thread.run_sync` submits the synchronous `rerank` function to the default thread pool executor, `await`s the result, and returns it. The event loop is free to handle other requests while the worker thread runs PyTorch inference. `anyio` is used here rather than `asyncio.get_event_loop().run_in_executor()` because `anyio` is the async compatibility layer that Starlette/FastAPI use internally.

#### `model.predict(pairs)` — Inference

```python
def rerank(query: str, candidates: list[dict], top_n: int) -> list[dict]:
    if not candidates:
        return []
    model = _get_model()
    pairs = [(query, c["content"]) for c in candidates]
    scores = model.predict(pairs)
    ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
    return [{"rerank_score": float(s), **c} for s, c in ranked[:top_n]]
```

`pairs` is a list of `(query_string, passage_string)` tuples, one per candidate. `model.predict(pairs)` tokenises each pair, pads or truncates to 512 tokens, runs a forward pass through the 6-layer Transformer, and returns the logit from the CLS head as a NumPy array of shape `(len(pairs),)`. The result is sorted descending (highest logit = most relevant first), and only the top `top_n` are returned.

#### Bi-encoder vs Cross-encoder: Why Not Use Cross-encoder for Retrieval

A cross-encoder cannot be used at retrieval time because it requires the query to be known before scoring begins. To find the top-20 chunks from a corpus of 100,000 using a cross-encoder, you would need to run 100,000 inference passes — at 2ms per inference, that is 200 seconds. The bi-encoder used for vector search avoids this by pre-computing all passage embeddings offline and using an ANN index for sub-second lookup. The cross-encoder is then applied only to the 20 candidates that survived the fast first-stage retrieval, making the total inference cost 20 × 2ms = 40ms instead of 200,000ms.

#### Rerank-Disabled Path

When `req.rerank = False`, the pipeline skips the reranker entirely:

```python
if req.rerank and candidates:
    return await rerank_async(req.query, candidates, req.top_k)
return candidates[:req.top_k]
```

The `candidates` list is already ordered by RRF score (the `_fetch_candidates` call preserves RRF order via an explicit sort), and the first `top_k` are returned directly. None of the result dicts contain a `rerank_score` key in this path.

---

### 7. Result Construction

#### Candidate Fetch Query

After RRF produces an ordered list of chunk UUIDs (`top_ids`), a second database round-trip fetches the full data for those chunks:

```python
async def _fetch_candidates(self, chunk_ids: list[str]) -> list[dict]:
    sql = text("""
        SELECT c.id, c.content, c.heading, c.document_id,
               d.title, d.tags, d.category, d.source_url, d.file_path
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.id = ANY(CAST(:ids AS uuid[]))
    """)
    result = await self.db.execute(sql, {"ids": chunk_ids})
    rows = result.fetchall()
    candidates = [dict(r._mapping) for r in rows]

    # Preserve RRF order
    id_order = {cid: i for i, cid in enumerate(chunk_ids)}
    candidates.sort(key=lambda r: id_order.get(str(r["id"]), 999))

    for c in candidates:
        c["id"] = str(c["id"])
        c["document_id"] = str(c["document_id"])
        if c.get("tags"):
            c["tags"] = list(c["tags"])
    return candidates
```

The `WHERE c.id = ANY(CAST(:ids AS uuid[]))` clause fetches all candidates in a single query rather than N individual lookups. The `:ids` parameter is a Python list of UUID strings; the `CAST(... AS uuid[])` converts the PostgreSQL array literal to the `uuid[]` type.

**RRF Order Preservation**: The database does not guarantee that rows are returned in the order the UUID array was provided to `ANY`. The explicit re-sort rebuilds the RRF ordering. Chunks not found in the database (e.g., if deleted between the RRF step and this fetch) receive position `999` and sink to the bottom.

**Post-fetch coercions**: UUIDs are converted from `uuid.UUID` objects to strings (FastAPI's JSON serialiser requires serialisable types). PostgreSQL `TEXT[]` columns are returned by psycopg as tuples; `list(c["tags"])` converts them to Python lists.

#### Fields in Each Result Object

| Field | Source | Type | Notes |
|---|---|---|---|
| `id` | `chunks.id` | `str` (UUID) | Chunk identifier |
| `content` | `chunks.content` | `str` | The raw chunk text (original markdown, not stripped) |
| `heading` | `chunks.heading` | `str \| None` | Section heading extracted at ingest time |
| `document_id` | `chunks.document_id` | `str` (UUID) | Foreign key to `documents` |
| `title` | `documents.title` | `str \| None` | Document title |
| `file_path` | `documents.file_path` | `str` | Unique path identifier |
| `source_url` | `documents.source_url` | `str \| None` | Original URL or reference |
| `tags` | `documents.tags` | `list[str]` | Tag array (empty list if none) |
| `category` | `documents.category` | `str \| None` | Category string |
| `rerank_score` | computed by reranker | `float \| None` | Raw cross-encoder logit; absent if `rerank=False` |

#### `rerank_score` Semantics

`rerank_score` is the raw logit output from the cross-encoder's CLS head — a single float with no bound. Values are meaningful only in relative order within a single query's result set. A score of `4.2` does not mean "92% relevant"; it means "this chunk is ranked higher than a chunk scoring `3.8` for this specific query." Scores should not be compared across queries or across different `top_k` values.

---

### 8. Search Telemetry

#### `BackgroundTask` Pattern

The HTTP route logs search telemetry using FastAPI's `BackgroundTasks` mechanism:

```python
@router.post("/search", response_model=SearchResponse)
async def search_endpoint(req: SearchRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    ctrl = QueryController(db)
    t0 = time.perf_counter()
    results = await ctrl.search(req)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    background_tasks.add_task(
        _log_search,
        query=req.query,
        filters=req.filters,
        result_count=len(results),
        latency_ms=latency_ms,
        top_chunk_ids=[r["id"] for r in results],
        reranked=req.rerank,
    )

    return SearchResponse(query=req.query, results=results)
```

`background_tasks.add_task()` registers the `_log_search` coroutine to run after the HTTP response has been sent to the client. This means telemetry logging has **zero impact on search response latency** as experienced by the caller.

#### Latency Measurement

```python
t0 = time.perf_counter()
results = await ctrl.search(req)
latency_ms = int((time.perf_counter() - t0) * 1000)
```

The measured window covers: embed call → vector search → FTS search → RRF → `_fetch_candidates` → optional reranker. It does not include request parsing/validation or response serialisation.

#### `_log_search` — Exact Insert

```python
async def _log_search(...) -> None:
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                text("""
                    INSERT INTO search_logs (query, filters, result_count, latency_ms, top_chunk_ids, reranked)
                    VALUES (:query, CAST(:filters AS jsonb), :result_count, :latency_ms,
                            CAST(:chunk_ids AS uuid[]), :reranked)
                """),
                {
                    "query": query,
                    "filters": json.dumps(filters) if filters else "null",
                    "result_count": result_count,
                    "latency_ms": latency_ms,
                    "chunk_ids": "{" + ",".join(top_chunk_ids) + "}" if top_chunk_ids else "{}",
                    "reranked": reranked,
                },
            )
            await db.commit()
        except Exception:
            pass  # telemetry failure must never affect the caller
```

`_log_search` opens its own `AsyncSessionLocal()` session rather than reusing the request's `db` session. The request session is scoped to the request lifetime and would be closed before the background task runs. The bare `except Exception: pass` is intentional: a telemetry write failure must never propagate to the caller.

#### `search_logs` Table

```sql
CREATE TABLE IF NOT EXISTS search_logs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query          TEXT NOT NULL,
    filters        JSONB,
    result_count   INTEGER NOT NULL DEFAULT 0,
    latency_ms     INTEGER,
    top_chunk_ids  UUID[],
    reranked       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_search_logs_created_at ON search_logs (created_at DESC);
```

`search_logs` has no foreign key relationships to `chunks` or `documents`. This is intentional: if a chunk or document is deleted, the historical log entry remains intact. The `idx_search_logs_created_at DESC` index supports time-range analytics queries such as "what queries ran in the last hour" or "what is the 95th percentile latency over the last 7 days."

---

### 9. MCP Integration

#### Overview

The MCP (Model Context Protocol) layer exposes the retrieval pipeline to Claude Desktop and other MCP clients without requiring any changes to the core RAG server. The MCP server is a separate process (`mcp/server.py`) that communicates with the RAG backend over HTTP and exposes tools to Claude over stdio.

#### Transport and Process Model

The transport is controlled by the `MCP_TRANSPORT` environment variable:

```python
transport = os.getenv("MCP_TRANSPORT", "stdio")
_mcp.run(transport=transport)
```

- `stdio` (default): reads JSON-RPC messages from stdin, writes responses to stdout. Claude Desktop spawns the process and owns its stdin/stdout pipes.
- `streamable-http`: binds to `MCP_HOST:MCP_PORT` and accepts HTTP connections for remote or multi-client deployments.

Claude Desktop configuration (`~/.claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "cortex": {
      "command": "/path/to/.cortex_venv/bin/python",
      "args":    ["/path/to/cortex/mcp/server.py"],
      "env":     { "RAG_SERVER_URL": "http://localhost:8002" }
    }
  }
}
```

Claude Desktop spawns this process on startup, maintains the stdio pipe for the session lifetime, and uses the MCP protocol to discover available tools.

#### `retrieve` Tool

```python
def retrieve(
    query: str,
    top_k: int = 5,
    tags: list[str] | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
```

Before the function body executes, middleware runs:

1. `_log`: logs `tool=retrieve args={...}` to the MCP server's logger.
2. `_validate_query`: rejects queries shorter than 3 characters or longer than 2000 characters.
3. `_validate_top_k`: rejects `top_k` outside `[1, 20]`. The MCP layer caps `top_k` at 20, stricter than the REST API's cap of 100.
4. `_validate_date`: validates `date_from` and `date_to` against the regex `^\d{4}-\d{2}-\d{2}$`.

The MCP layer always passes `rerank: True` to the backend. The reasoning is that the MCP consumer (Claude) is an LLM that will use the retrieved passages as context — quality matters more than the ~50–200ms reranker latency.

The response is formatted as a human-readable string that Claude reads and synthesises into an answer:

```
--- [1] Document Title › Section Heading  [score: 3.742] ---
The passage text...

--- [2] Another Document › intro  [score: 2.891] ---
...
```

#### `list_knowledge_base` Tool

Exposes `GET /documents` and formats the result as a bulleted list of document titles, categories, tags, and dates. Claude can call this before calling `retrieve` to understand what knowledge is available, or when the user asks "what do you know about X?"

#### `ingest_document` Tool

Allows Claude to ingest new documents into the knowledge base at runtime via `POST /documents/text`. The `file_path` is used as a unique identifier: re-ingesting the same `file_path` with identical content will return "Document unchanged, skipped" (the backend computes a file hash and skips re-processing if nothing changed).

#### How Claude Decides When to Call `retrieve`

Claude Desktop does not have any automatic trigger for calling `retrieve`. Claude reads the tool descriptions from the MCP server's tool manifest during the capabilities handshake and decides autonomously, based on the conversation context, whether a retrieval call would be useful. When a user asks a question that Claude judges as potentially being answered by locally stored knowledge, Claude will call `retrieve` with an appropriate `query` and, if context clues are available (e.g., "find engineering docs from last month"), will also set `category` and/or `date_from`/`date_to`. Claude constructs the filter arguments based on natural-language context without the user needing to know filter syntax.

---

### 10. End-to-End Latency Breakdown

For a typical request with `rerank: true`, `top_k: 5`, no filters, and a corpus of ~10,000 chunks:

#### Stage-by-Stage Timing

| Stage | Typical Duration | Notes |
|---|---|---|
| Request parsing and validation (Pydantic) | < 1 ms | Excluded from `latency_ms` measurement |
| `strip_markdown(req.query)` | < 0.1 ms | Pure CPU regex, negligible |
| `embed(stripped_query)` — Ollama HTTP round-trip | 50–100 ms | Dominant contributor; nomic-embed-text on CPU. On GPU: 5–15 ms |
| `_vector_search()` — IVFFlat ANN query | 5–20 ms | Depends on corpus size and `ivfflat.probes`. At 10k chunks: ~5 ms; at 1M chunks with probes=10: ~20 ms |
| `_fts_search()` — GIN-accelerated tsvector scan | 5–15 ms | GIN index makes this sub-linear in corpus size |
| Note: vector and FTS run sequentially | — | Two `await` calls in the same coroutine; not concurrent |
| `_reciprocal_rank_fusion()` — pure Python dict ops | < 0.5 ms | 50+50 items, O(n) with hash map; effectively free |
| `_fetch_candidates()` — single SQL ANY() query | 2–5 ms | Primary key scan over ≤20 UUIDs |
| `rerank_async()` — cross-encoder on 20 pairs (CPU) | 50–200 ms | MiniLM-L-6, 6 layers, 20 pairs. On CPU: ~10 ms/pair. On GPU: ~2 ms/pair |
| Response serialisation (Pydantic → JSON) | < 2 ms | Excluded from `latency_ms`; happens after measurement |
| **Total `latency_ms` (typical, CPU-only)** | **~150–350 ms** | Embed + rerank are the dominant terms |
| **Total `latency_ms` (typical, GPU available)** | **~30–80 ms** | GPU accelerates both embed and rerank |
| `_log_search()` background task | 5–20 ms | Runs after response; zero impact on P99 |

#### What Dominates Latency

Two stages account for ~90% of the measured `latency_ms`:

1. **Embedding (`embed()`)**: The `nomic-embed-text` model running inside Ollama on CPU takes 50–100ms per inference. This is a fixed cost per query regardless of corpus size. On machines with Apple Silicon, Ollama can use Metal acceleration, reducing this to ~10–20ms.

2. **Cross-encoder reranking (`rerank_async()`)**: Scoring 20 `(query, passage)` pairs through 6 Transformer layers on CPU is the most computationally intensive step. At ~5–10ms per pair, 20 pairs takes 100–200ms. On GPU, the same batch runs in ~2–4ms total because all 20 pairs can be batched into a single forward pass.

The database operations (vector ANN and FTS) are both sub-20ms even at non-trivial corpus sizes, because they both have appropriate indexes and operate on indexed structures that do not require full table scans.

#### Vector Search and FTS are Sequential, Not Concurrent

The current implementation runs vector search and FTS sequentially in the same coroutine. Making them truly concurrent would require `asyncio.gather()`:

```python
# Current (sequential):
vec_rows, fts_rows = (
    await self._vector_search(...),
    await self._fts_search(...),
)

# Potential optimisation (concurrent):
vec_rows, fts_rows = await asyncio.gather(
    self._vector_search(...),
    self._fts_search(...),
)
```

With a connection pool large enough to satisfy two simultaneous queries, `asyncio.gather` would reduce the combined database time from (vector + FTS) to max(vector, FTS) — saving 5–15ms. At current corpus sizes this is below the noise floor relative to the embed + rerank cost.

#### Latency vs Recall Knobs

| Setting | Current Value | Effect of Increasing |
|---|---|---|
| `vector_search_limit` | 50 | More candidates → higher recall, more RRF work |
| `fts_search_limit` | 50 | Same as above for FTS branch |
| `rerank_top_n` | 20 | More pairs scored by cross-encoder → higher reranker latency, potentially higher quality |
| `ivfflat.probes` | 1 (pgvector default) | More cells probed → higher ANN recall, higher vector search latency |
| `top_k` | caller-controlled, default 5 | Does not affect pipeline latency; only affects slice of final result |

The most impactful single change for latency reduction is enabling GPU acceleration for Ollama and PyTorch. The most impactful change for recall improvement is setting `ivfflat.probes = 10` in a session-level GUC or SQLAlchemy event listener.

---

## Configuration Reference

Every setting in `rag-backend/core/config.py` is read from `cortex/.env` via `pydantic-settings`. All keys are lowercase in the `.env` file. The `Settings` singleton is imported as `from core.config import settings` throughout the codebase.

### Database

| `.env` key | Default | Notes |
|---|---|---|
| `pghost` | `localhost` | PostgreSQL host |
| `pgport` | `5432` | PostgreSQL port |
| `pgdatabase` | `cortex_rag` | Database name — must match the DB you created |
| `pguser` | `raguser` | Database user |
| `pgpassword` | `""` | Database password — empty means trust auth (fine for local) |

The connection URL is assembled by `settings.database_url` as `postgresql+psycopg://{user}:{password}@{host}:{port}/{database}`. The `psycopg` driver (v3, async) is used by SQLAlchemy.

### Ollama / Embedding Model

| `.env` key | Default | Notes |
|---|---|---|
| `ollama_url` | `http://localhost:11434` | Base URL of the Ollama HTTP API. Change if Ollama runs on a different host or port. |
| `embed_model` | `nomic-embed-text` | The Ollama model name passed to `/api/embed`. Must match a model you have pulled (`ollama pull <name>`). |
| `ollama_timeout` | `60.0` | HTTP timeout in seconds for embedding requests. Increase for very large batches or slow hardware. |
| `embed_max_retries` | `1` | Number of retries on embedding failure. One retry, then `UpstreamError`. Increasing this does not help if Ollama is OOM-killed — it just delays the failure. |

**Changing `embed_model`**: If you change this, you **must** also migrate the `chunks.embedding` column to match the new model's output dimension. The column is declared as `vector(768)` — changing to a 1024-dim model (e.g., `mxbai-embed-large`) requires `ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024)` and rebuilding the IVFFlat index and re-ingesting all documents. There is no partial migration path.

### Chunking

| `.env` key | Default | Tuning guidance |
|---|---|---|
| `chunk_max_tokens` | `400` | Maximum estimated tokens per chunk (`len(text) // 4`). Increase → fewer, larger chunks (better for long-answer retrieval). Decrease → more, smaller chunks (better for precise fact retrieval). The embed model's context window is 8192 tokens, so values up to ~1600 are safe, but chunks above 600 tokens start to embed semantic mixtures of multiple concepts. |
| `chunk_overlap_chars` | `200` | Characters of overlap between adjacent chunks in `_split_long()`. Overlap in words = `chunk_overlap_chars // 4 = 50`. Increase → more context preserved at boundaries, more redundant storage. Decrease → sharper splits, risk of losing context at boundaries. Set to `0` to disable overlap entirely. |

### Search & Retrieval

| `.env` key | Default | Tuning guidance |
|---|---|---|
| `vector_search_limit` | `50` | Candidates retrieved from the vector ANN branch before RRF. Increasing beyond 50 gives marginal recall improvement for most corpora; the RRF+reranker pipeline is the primary recall lever. |
| `fts_search_limit` | `50` | Candidates retrieved from the FTS branch before RRF. Same trade-off as above. |
| `rerank_top_n` | `20` | How many RRF-fused candidates are passed to the cross-encoder. The cross-encoder scores these pairs. Increase → higher reranker recall, higher latency (linear: 30 candidates ≈ 1.5× latency of 20). Decrease → lower latency, risk of missing relevant chunks that ranked poorly in both retrieval branches. |

### Reranking

| `.env` key | Default | Notes |
|---|---|---|
| `rerank_model` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | HuggingFace model ID passed to `sentence-transformers.CrossEncoder`. Downloaded on first use and cached in `~/.cache/huggingface/`. |

**Changing `rerank_model`**: Drop-in replaceable. Any `CrossEncoder`-compatible model works. Change the `.env` value, restart the server, and the new model loads on first search. No schema migration required — reranking does not touch the database. See §Alternative Models below.

### Operational

| `.env` key | Default | Notes |
|---|---|---|
| `redis_url` | `redis://localhost:6379` | ARQ uses this for the job queue. Standard Redis URL format: `redis://[:password@]host[:port][/db]`. |
| `log_level` | `INFO` | Python logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`. `DEBUG` logs every SQL query and embedding request. |
| `cors_origins` | `http://localhost:5173` | Comma-separated list of allowed CORS origins. Set to `*` to allow all (not recommended in production). |
| `api_key` | `""` | When non-empty, all API routes require the `X-API-Key` header with this value. Empty = auth disabled. The MCP server reads `RAG_API_KEY` from its own env and forwards it as this header. |

### Example `.env`

```env
# Database
pghost=localhost
pgport=5432
pgdatabase=cortex_rag
pguser=raguser
pgpassword=

# Ollama
ollama_url=http://localhost:11434
embed_model=nomic-embed-text
ollama_timeout=60.0
embed_max_retries=1

# Chunking
chunk_max_tokens=400
chunk_overlap_chars=200

# Search
vector_search_limit=50
fts_search_limit=50
rerank_top_n=20
rerank_model=cross-encoder/ms-marco-MiniLM-L-6-v2

# Infrastructure
redis_url=redis://localhost:6379
log_level=INFO
cors_origins=http://localhost:5173
api_key=
```

---

## Dependencies & Packages

All dependencies are pinned in `requirements.txt` (root — used by `make setup`) and declared in `rag-backend/pyproject.toml` (used by Poetry for development).

### Core Backend

| Package | Version | Used For |
|---|---|---|
| `fastapi` | 0.138.0 | HTTP framework — routes, dependency injection, background tasks, middleware |
| `uvicorn` | 0.49.0 | ASGI server — runs the FastAPI app |
| `sqlalchemy` | 2.0.51 | ORM (async 2.0 style) — `AsyncSession`, `select()`, model definitions, event listeners |
| `psycopg[binary]` | 3.3.4 | PostgreSQL driver (v3, async) — used by SQLAlchemy. The `[binary]` extra links against compiled libpq for performance. |
| `pgvector` | 0.4.2 | SQLAlchemy integration for the `vector(768)` column type and the `<=>` operator |
| `pydantic` | 2.13.4 | Request/response schema validation — `BaseModel`, `Field`, `field_validator`, `ConfigDict` |
| `pydantic-settings` | 2.14.2 | `.env` file loading into `Settings` via `BaseSettings` |
| `python-multipart` | 0.0.32 | Multipart form parsing for file upload (`/documents/upload`) |
| `python-dotenv` | 1.2.2 | `.env` file loading (used by pydantic-settings internally) |
| `python-frontmatter` | 1.3.0 | YAML frontmatter parsing for `.md` files — `frontmatter.loads(text)` returns `post.metadata` and `post.content` |

### Job Queue

| Package | Version | Used For |
|---|---|---|
| `arq` | 0.28.0 | Async Redis queue — `WorkerSettings`, `create_pool`, `enqueue_job`, `on_startup` hook |
| `redis` | 5.3.1 | Redis client — used by ARQ internally; also imported for `RedisSettings` and `ArqRedis` type |

### Embeddings & Reranking

| Package | Version | Used For |
|---|---|---|
| `httpx` | 0.28.1 | Async HTTP client for Ollama embedding API (`POST /api/embed`). Used directly (not via the `ollama` package) for async compatibility. |
| `ollama` | 0.6.2 | Ollama Python client — installed but **not used** for embeddings (httpx is used instead for async). Present as a dependency of other packages. |
| `sentence-transformers` | 5.6.0 | Provides `CrossEncoder` for reranking. Handles model download from HuggingFace Hub, tokenisation, and inference. |
| `torch` | 2.12.1 | PyTorch — the execution engine for `CrossEncoder.predict()`. CPU by default; automatically uses CUDA if a compatible GPU is present. On Apple Silicon, uses MPS (Metal Performance Shaders) if `torch.backends.mps.is_available()`. |
| `scikit-learn` | 1.9.0 | Required by sentence-transformers for some preprocessing utilities. Not used directly by application code. |
| `numpy` | 2.4.6 | `CrossEncoder.predict()` returns a NumPy array of logit scores. Also used by pgvector internally. Pinned `<2.5.0` because PyTorch 2.x requires `numpy < 2.5`. |

### MCP Server

| Package | Version | Used For |
|---|---|---|
| `mcp` | 1.28.0 | Model Context Protocol SDK — `FastMCP`, tool registration, stdio/HTTP transport |
| `httpx` | 0.28.1 | Shared with the backend — MCP server uses it to call the RAG backend REST API |

---

## Alternative Models

### Embedding Models (swap via `embed_model` in `.env`)

All models below are available via Ollama (`ollama pull <name>`). After changing `embed_model`, you must re-ingest all documents (the stored vectors are incompatible across models) and update the `vector(768)` column dimension if the new model outputs a different dimension.

| Model | Ollama name | Dim | Context | Size | Notes |
|---|---|---|---|---|---|
| **nomic-embed-text** (default) | `nomic-embed-text` | 768 | 8192 | ~270 MB | Strong retrieval scores, large context window, Apache 2.0 |
| nomic-embed-text v1.5 | `nomic-embed-text:v1.5` | 768 | 8192 | ~270 MB | Same architecture with Matryoshka training — can truncate to smaller dims if needed |
| mxbai-embed-large | `mxbai-embed-large` | **1024** | 512 | ~670 MB | Strong on MTEB. Requires schema change: `ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024)` and `lists` re-tuning |
| all-minilm | `all-minilm` | **384** | 256 | ~45 MB | Very fast, small. Schema change required. Lower quality but good for resource-constrained hardware |
| bge-m3 | `bge-m3` | **1024** | 8192 | ~1.2 GB | Best multilingual support. Schema change required. |

**Schema migration checklist when changing embedding model:**
1. Update `embed_model` in `.env`
2. `ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(<new_dim>);`
3. `DROP INDEX idx_chunks_embedding;`
4. `CREATE INDEX idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);`
5. Re-ingest all documents (the old vectors in `chunks.embedding` are meaningless for the new model)

### Reranking Models (swap via `rerank_model` in `.env`)

Any HuggingFace model loadable by `sentence-transformers.CrossEncoder` works. No schema migration required — the reranker has no database footprint.

| Model | HuggingFace ID | Size | Notes |
|---|---|---|---|
| **MiniLM-L-6** (default) | `cross-encoder/ms-marco-MiniLM-L-6-v2` | ~85 MB | Good balance of speed and quality. 6 layers, 22M params. |
| MiniLM-L-12 | `cross-encoder/ms-marco-MiniLM-L-12-v2` | ~130 MB | 12 layers — higher quality, ~1.8× slower inference than L-6 |
| TinyBERT | `cross-encoder/ms-marco-TinyBERT-L-2-v2` | ~17 MB | 2 layers — fastest inference, lower quality. Good for latency-critical deployments. |
| MiniLM multilingual | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | ~120 MB | Multilingual. Use when your knowledge base is not English-only. |
| BGE reranker | `BAAI/bge-reranker-base` | ~280 MB | Strong on Chinese and English corpora. Good alternative if MS MARCO domain doesn't match your content. |

**Latency comparison** (20 pairs, CPU, M2 MacBook):

| Model | Avg inference |
|---|---|
| TinyBERT-L-2 | ~15 ms |
| MiniLM-L-6 (default) | ~60 ms |
| MiniLM-L-12 | ~110 ms |
| BGE reranker base | ~180 ms |

---

## IVFFlat Tuning Guide

The vector index has two parameters that interact: `lists` (set at `CREATE INDEX` time) and `probes` (set at query time).

### `lists` — Number of Voronoi Cells

```sql
CREATE INDEX idx_chunks_embedding
    ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

The pgvector recommendation: `lists = max(1, round(sqrt(num_chunks)))`.

| Corpus size | Recommended `lists` |
|---|---|
| < 1,000 chunks | 1 (exact search — don't bother with IVFFlat) |
| 1,000–10,000 | 32 |
| 10,000–100,000 | 100 (current default) |
| 100,000–1,000,000 | 316 |
| > 1,000,000 | 1000 |

To change `lists`, drop and recreate the index:
```sql
DROP INDEX idx_chunks_embedding;
CREATE INDEX idx_chunks_embedding
    ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = <new_value>);
```

This requires a table scan and can take minutes on large corpora. Do it during a maintenance window.

### `probes` — Cells to Search at Query Time

`probes` is a session-level GUC — it can be changed without rebuilding the index:

```sql
SET ivfflat.probes = 10;
```

Recommended: `probes = round(sqrt(lists))`. For `lists = 100` → `probes = 10`.

| `probes` | Recall (approx) | Latency impact |
|---|---|---|
| 1 (default) | ~70–80% | Fastest |
| 10 | ~95–98% | ~10× scan size |
| 100 | ~100% (exact) | Same as no index |

To apply `probes = 10` for all queries in Cortex RAG, add this to the SQLAlchemy connection event listener in `core/database.py`:

```python
from sqlalchemy import event

@event.listens_for(engine.sync_engine, "connect")
def set_search_path(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("SET ivfflat.probes = 10")
    cursor.close()
```

Or set it globally in `postgresql.conf`:
```
ivfflat.probes = 10
```

The most impactful single change for latency reduction is enabling GPU acceleration for Ollama and PyTorch. The most impactful change for recall improvement is setting `ivfflat.probes = 10` (matching the `sqrt(lists)` heuristic for `lists = 100`) in a session-level GUC or SQLAlchemy event listener.
