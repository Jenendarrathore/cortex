---
sidebar_position: 2
---

# MCP Tools

Cortex RAG exposes three tools to Claude Desktop via the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP). These tools let Claude read from and write to your local knowledge base without any copy-pasting — Claude calls them directly as part of answering your questions.

The MCP server (`mcp/server.py`) runs as a subprocess of Claude Desktop and communicates over `stdio`. It forwards all requests to the RAG backend running on `http://localhost:8002`. When `RAG_API_KEY` is set in the MCP server's environment, the client automatically includes the `X-API-Key` header on every request to the backend.

---

## How Claude uses these tools

### Automatically (no prompt needed)

Claude calls `retrieve` on its own whenever it judges that your question might be answered by your knowledge base. You do not need to say "search my knowledge base" — Claude sees the available tools and decides when to use them.

Examples of questions Claude will typically handle automatically:

- *"How do I configure the database connection?"*
- *"What does the chunker do?"*
- *"Walk me through the search pipeline."*

Claude embeds the retrieved passages into its reasoning before replying. If nothing relevant is found, it falls back to its own knowledge and tells you so.

### Explicitly (you direct Claude)

You can also instruct Claude to use a specific tool with a direct request:

- *"List everything in my knowledge base."* → Claude calls `list_knowledge_base`
- *"Add this document to Cortex RAG: ..."* → Claude calls `ingest_document`
- *"Search for the top 10 results about pgvector with the tag 'infrastructure'."* → Claude calls `retrieve` with your parameters

Explicit requests are useful when you want to control filters, ingest new content mid-conversation, or audit what is indexed.

---

## Tool reference

### `retrieve`

Search the knowledge base for passages relevant to a query. This is the primary tool Claude uses when you ask it a question. It runs the full hybrid search pipeline: vector similarity search + full-text search, merged via Reciprocal Rank Fusion, then reranked with a cross-encoder. The backend is at `http://localhost:8002`.

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | `string` | Yes | The question or topic to search for. Should be a natural language phrase or sentence, not just keywords. |
| `top_k` | `integer` | No | Number of passages to return. Default: `5`. Max: `20`. |
| `tags` | `string[]` | No | Restrict search to documents tagged with **any** of these values. Example: `["python", "setup"]`. |
| `category` | `string` | No | Restrict search to documents in this exact category. Example: `"engineering"`. |
| `date_from` | `string` | No | Only include documents dated on or after this date. Format: `YYYY-MM-DD`. |
| `date_to` | `string` | No | Only include documents dated on or before this date. Format: `YYYY-MM-DD`. |

#### Example usage

**Basic question — Claude calls this automatically:**
> *"How does the reranker work?"*

**Explicit search with filters:**
> *"Search my knowledge base for 'database setup' in the 'infrastructure' category, tagged 'postgres', and return the top 3 results."*

#### Example output

```
--- [1] Architecture Overview › Search Pipeline  [score: 0.921] ---
The cross-encoder reranker (cross-encoder/ms-marco-MiniLM-L-6-v2) scores each
(query, chunk) pair as a relevance classification problem. It sees the full pair
rather than independent embeddings, making it significantly more accurate than
bi-encoder vector search alone. It runs only on the top-20 RRF candidates to
keep latency low.

--- [2] RAG Backend › QueryController  [score: 0.874] ---
QueryController.search() runs vector cosine search and plainto_tsquery FTS in
parallel (top 50 each), merges results with Reciprocal Rank Fusion, then passes
the top 20 to the sentence-transformers cross-encoder before returning top_k.

--- [3] Configuration Guide › Reranker Settings  [score: 0.812] ---
The reranker model is loaded once at startup and cached in memory. On CPU it adds
roughly 200–400 ms to a search with 20 candidates. On Apple Silicon MPS it drops
to under 100 ms for typical corpus sizes.
```

Each result shows the document title, the nearest markdown heading above the passage, the cross-encoder relevance score (0–1, higher is better), and the passage text.

---

### `ingest_document`

Add a new document to the knowledge base, or update an existing one. The document is identified by `file_path` — if a document with that path already exists and the content is unchanged (same SHA-256 hash), the call is a no-op and returns `skipped`. If the content has changed, the old chunks are deleted and new ones are created. This tool calls `POST /documents/text` on the backend at `http://localhost:8002`.

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `content` | `string` | Yes | The full text to ingest. May include YAML frontmatter — it will be stored as-is in `raw_content`. |
| `file_path` | `string` | Yes | A unique identifier for this document. Acts as a stable key for deduplication and updates. Use a path-like string such as `"guides/setup.md"` or `"notes/2024-q3-retro.md"`. |
| `title` | `string` | No | Human-readable display title. Shown in search results and the admin UI. |
| `category` | `string` | No | A single category label for pre-filtering. Example: `"engineering"`, `"research"`, `"ops"`. |
| `tags` | `string[]` | No | List of tags for pre-filtering. Example: `["python", "fastapi", "setup"]`. |
| `author` | `string` | No | Author name. Stored as metadata; not used in search ranking. |
| `date` | `string` | No | Publication or effective date. Format: `YYYY-MM-DD`. Used for date-range filtering in `retrieve`. |
| `source_url` | `string` | No | Original URL or source reference. Stored as metadata only. |

#### Example usage

**Ingest a short note:**
> *"Add this to my knowledge base with the title 'Deploy Checklist', category 'ops', and tags 'deploy', 'checklist':"*
> *(paste markdown content)*

**Ingest with full metadata:**
> *"Ingest the following markdown as 'runbooks/postgres-backup.md', title 'PostgreSQL Backup Runbook', category 'infrastructure', tags ['postgres', 'backup', 'runbook'], author 'Jenendar', date '2025-06-01':"*
> *(paste markdown content)*

**Update an existing document:**
> *"Update 'guides/setup.md' in the knowledge base with this revised content:"*
> *(paste updated markdown)*

#### Example output

When a new document is ingested successfully:
```
Ingested: guides/setup.md
document_id: 3f7a1c2e-84b9-4d01-a6f5-29e0c3d18b44
chunks: 12
```

When the content is identical to what is already stored (deduplication hit):
```
Document unchanged, skipped: guides/setup.md
```

---

### `list_knowledge_base`

Return a flat list of all documents currently indexed in the knowledge base. Shows each document's title, category, tags, date, and UUID. Takes no parameters. Calls `GET /documents/` on the backend at `http://localhost:8002`.

Use this tool to understand what knowledge is available before formulating a query, to verify a document was ingested, or to find a document's UUID for direct API operations.

#### Parameters

None.

#### Example usage

**Audit what is indexed:**
> *"What documents are in my knowledge base?"*

**Check if a document was ingested:**
> *"List my knowledge base and tell me if there's anything about pgvector setup."*

#### Example output

```
• Architecture Overview  |  category: engineering  |  tags: architecture, overview  |  date: 2025-05-10  |  id: 3f7a1c2e-84b9-4d01-a6f5-29e0c3d18b44
• PostgreSQL Backup Runbook  |  category: infrastructure  |  tags: postgres, backup, runbook  |  date: 2025-06-01  |  id: 91c4d2f0-3b7e-4a88-b519-7f6082c1a3d9
• Deploy Checklist  |  category: ops  |  tags: deploy, checklist  |  date: —  |  id: b82e5a17-0c3d-4f91-8d24-1a503ef79c62
```

If the knowledge base is empty:
```
Knowledge base is empty.
```

---

## Search pipeline (what `retrieve` runs under the hood)

```
query string
    │
    ▼
strip_markdown(query) — normalize query text
    │
    ▼
Embed with nomic-embed-text (Ollama :11434)
→ 768-dim query vector
    │
    ├──────────────────────────────────┐
    ▼                                  ▼
Vector search                     FTS search
cosine similarity on              plainto_tsquery on
chunks.embedding                  chunks.fts (tsvector)
ivfflat index (probes=10)         GIN index, top 50
top 50
    │                                  │
    └──────────────┬───────────────────┘
                   ▼
        Reciprocal Rank Fusion (RRF)
        score = Σ 1 / (k + rank_i)
        → top 20 merged candidates
                   │
                   ▼
        Cross-encoder reranker
        cross-encoder/ms-marco-MiniLM-L-6-v2
        scores each (query, chunk) pair
        → top_k results returned
```

Filters (`tags`, `category`, `date_from`, `date_to`) are applied as SQL `WHERE` clauses before both the vector and FTS searches run, so they reduce the candidate pool rather than post-filtering results.

---

## Deduplication behaviour

`ingest_document` computes a SHA-256 hash of the document content before writing to the database. If a document with the same `file_path` already exists and the hash matches, the ingestion is skipped and the tool returns `skipped`. If the hash differs (content has changed), the existing document row and all its chunk rows are deleted and replaced with the new content re-chunked and re-embedded.

This means:

- Re-ingesting an unchanged document is safe and cheap — no embeddings are recomputed.
- Updating a document always results in a full re-chunk and re-embed of the new content.
- The `file_path` is the stable identity key, not the title or any other metadata field.

---

## Configuring the MCP server

Add the following to `~/.claude/claude_desktop_config.json` (create the file if it does not exist). Replace `/path/to/cortex` with the absolute path to your Cortex RAG directory.

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

Set `RAG_API_KEY` to your key value if you have enabled `API_KEY` in the backend's `.env`. Leave it empty when auth is disabled.

The RAG backend must be running (`make rag`) before Claude Desktop can call any of these tools. The MCP server itself starts automatically as a subprocess when Claude Desktop launches — you do not run it manually.

:::tip Starting the backend
Run `make rag` in the `cortex/` directory to start the FastAPI backend on port 8002. Keep this terminal session alive while you use Claude Desktop.
:::

:::note Transport mode
The default transport is `stdio` (local, subprocess). For remote or multi-client setups, set `MCP_TRANSPORT=streamable-http` and `MCP_PORT=8001` when launching `mcp/server.py` manually. The Claude Desktop config above uses `stdio` only.
:::
