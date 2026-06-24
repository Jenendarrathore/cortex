---
sidebar_position: 2
---

# Searching the Knowledge Base

Cortex RAG provides three interfaces for querying your knowledge base: Claude Desktop (via MCP), the Admin UI Search tab, and the REST API directly. All three run the same search pipeline under the hood.

## How search works

Every query goes through the following pipeline:

```
Query text
    │
    ▼
strip_markdown() — normalize query (same space as chunk embeddings)
    │
    ▼
Embed with nomic-embed-text (Ollama, local, async httpx)
    │
    ▼
Vector search (cosine similarity, top 50 chunks)
    +
FTS search (plainto_tsquery on PostgreSQL tsvector, top 50 chunks)
    │
    ▼
RRF merge — Reciprocal Rank Fusion combines both result sets → top 20
    │
    ▼
Cross-encoder reranker (ms-marco-MiniLM-L-6-v2) scores top 20
    │
    ▼
Return top_k results (default: 5)
    │
    ▼ (after response is sent — BackgroundTask, zero latency impact)
search_logs INSERT (query, filters, latency_ms, result_count, top_chunk_ids, reranked)
```

### Query normalization

Before embedding, the query string is passed through `strip_markdown()` (from `core/text_utils.py`). This strips any markdown syntax from the query so it is represented in the same plain-text space as the chunk embeddings (which were also generated from stripped text). In practice, most queries are already plain text — this step ensures consistency when queries include markdown formatting.

### Why hybrid instead of vector-only

Vector search alone retrieves chunks that are *semantically similar* to your query — useful when you paraphrase or use synonyms. Full-text search retrieves chunks containing *exact tokens* — useful for proper nouns, version numbers, identifiers, and acronyms that embeddings might not distinguish.

Combining both via RRF means a chunk that ranks well in either dimension (or both) surfaces near the top. You get recall from semantics and precision from exact terms without having to choose one.

### What reranking adds

After RRF merges the candidate pool to 20 results, a cross-encoder model reads the query and each chunk together as a pair and scores them for relevance. Unlike the embedding step (which encodes query and chunk independently), the cross-encoder sees both at once, making it more accurate at judging whether a chunk actually answers the question. This step significantly improves result ordering — keep it enabled unless you are optimizing for raw speed on a large corpus.

### Search telemetry

After every search response is sent to the caller, a FastAPI `BackgroundTask` writes a row to the `search_logs` table:

| Field | What is recorded |
|-------|-----------------|
| `query` | The raw query string |
| `filters` | The filter object, if any |
| `result_count` | Number of results returned (after reranking and `top_k` truncation) |
| `latency_ms` | End-to-end search latency in milliseconds |
| `top_chunk_ids` | UUIDs of returned chunks, in result order |
| `reranked` | Whether the cross-encoder ran |

Because this runs after the response is already on the wire, it adds zero latency to the caller. A failure in the telemetry write (e.g. transient DB error) is silently swallowed — it never surfaces as a search error.

These rows are useful for understanding what your knowledge base is actually queried for, identifying zero-result queries (where `result_count = 0`), and seeing latency distribution over time.

---

## Searching via Claude Desktop (MCP)

Once the MCP server is configured (see [Setup](../setup/installation.md)), Claude Desktop has access to your knowledge base through three tools. You do not need to call them explicitly — Claude decides when to use `retrieve` based on your message.

### Natural language queries

Just ask Claude normally. It will call `retrieve` behind the scenes when it determines your question is relevant to the knowledge base.

```
What does the runbook say about rotating the API keys?
```

```
Summarize the architecture decisions from the design docs.
```

```
How do I configure the database connection?
```

Claude fetches the relevant chunks, reads them, and answers based on what it finds. If nothing useful comes back it will tell you.

### Explicit retrieval

You can make the retrieval intent explicit when you want Claude to prioritize the knowledge base rather than its general training:

```
Search my knowledge base for information about deployment rollbacks.
```

```
Look up in my docs how authentication is handled.
```

```
Retrieve everything in the knowledge base about rate limiting.
```

### Filtered queries

The `retrieve` tool accepts optional filters. Pass them in natural language and Claude will translate them into the appropriate filter parameters:

```
Find engineering docs tagged python from the last year.
```

```
Search for anything in the "infrastructure" category about load balancing.
```

```
Look up docs tagged "onboarding" added after January 2025.
```

Supported filters (which Claude maps automatically):

| Filter | What it does |
|--------|--------------|
| `tags` | Any-match against the document's tags array |
| `category` | Exact match on the document's category field |
| `date_from` | Only include documents with `doc_date` on or after this date |
| `date_to` | Only include documents with `doc_date` on or before this date |

### Listing the knowledge base

To see everything that has been ingested without running a search:

```
List everything in my knowledge base.
```

```
What documents do I have stored in Cortex?
```

Claude calls `list_knowledge_base()` and returns a summary of all documents with their metadata.

---

## Searching via the Admin UI

Start the UI with `make rag-ui` (backend must be running with `make rag`), then open `http://localhost:5173` and go to the **Search** tab.

### Search controls

| Control | Description |
|---------|-------------|
| Search bar | Your query in natural language |
| Top K | Number of results to return (slider). Higher values increase recall but slow down reranking. |
| Category | Filter to an exact category string |
| Tags | Filter to one or more tags (any-match) |
| Rerank toggle | Enable or disable cross-encoder reranking |

Type your query and press Enter or click Search. Results appear as ranked cards below.

### Result cards

Each card shows:

- **Title** — the document title the chunk belongs to
- **Heading** — the section heading within the document where the chunk was found
- **Rerank score** — the cross-encoder relevance logit — a raw unbounded float (e.g. `3.7`, `-1.2`). Higher is more relevant. Not a probability.
- **Content preview** — the beginning of the matching chunk text
- **Source URL** — link to the original source, if one was set on the document
- **File path** — the logical file path of the document

Click a result card to expand the full chunk content.

### Filtering in the UI

Use the Category and Tags fields to narrow the search before the semantic layer runs. Filters are applied at the database level (before embedding and RRF), so they constrain the candidate pool rather than just reordering results. This is the most efficient way to scope a broad knowledge base.

---

## Searching via the API

The backend exposes a single search endpoint at `POST /search`. You can call it from scripts, curl, or any HTTP client.

### Minimal request

```bash
curl -s -X POST http://localhost:8002/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "how to rotate API keys",
    "top_k": 5
  }'
```

### Full request with filters

```bash
curl -s -X POST http://localhost:8002/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "deployment rollback procedure",
    "top_k": 10,
    "rerank": true,
    "filters": {
      "tags": ["infrastructure", "ops"],
      "category": "runbooks",
      "date_from": "2025-01-01",
      "date_to": "2025-12-31"
    }
  }'
```

### Request schema

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | required | The search query |
| `top_k` | integer | `5` | Number of results to return |
| `rerank` | boolean | `true` | Whether to run cross-encoder reranking |
| `filters.tags` | string[] | — | Any-match tag filter |
| `filters.category` | string | — | Exact category match |
| `filters.date_from` | string (ISO date) | — | Lower bound on `doc_date` |
| `filters.date_to` | string (ISO date) | — | Upper bound on `doc_date` |

### Response shape

```json
{
  "query": "deployment rollback procedure",
  "results": [
    {
      "id": "3f8a1c...",
      "document_id": "a92b4d...",
      "title": "Deployment Runbook",
      "heading": "## Rolling Back a Release",
      "content": "To roll back to the previous release, run...",
      "rerank_score": 3.742,
      "file_path": "runbooks/deployment.md",
      "source_url": "https://internal.example.com/runbooks/deployment",
      "category": "runbooks",
      "tags": ["infrastructure", "ops"]
    }
  ]
}
```

Results are ordered by descending `rerank_score` when reranking is enabled. When reranking is disabled, results are ordered by RRF fusion rank (no score field is returned in that case).

**Result fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | uuid | Identifier of the matching chunk |
| `document_id` | uuid | Identifier of the parent document |
| `title` | string \| null | Title of the parent document |
| `heading` | string \| null | Markdown section heading for this chunk |
| `content` | string | Text content of the chunk |
| `rerank_score` | float | Raw cross-encoder logit — unbounded, higher is more relevant (only present when `rerank: true`) |
| `file_path` | string | Logical file path of the parent document |
| `source_url` | string \| null | Original source URL of the parent document |
| `category` | string \| null | Category of the parent document |
| `tags` | string[] | Tags of the parent document |

The interactive API docs at `http://localhost:8002/docs` let you run searches directly from the browser and inspect the full response schema.

---

## Tips for better results

**Use natural language queries, not keyword strings.**
The embedding model understands intent. "How do I restart the service after a config change?" will outperform "restart service config" because the query encodes richer semantic signal.

**Apply filters before searching when you know the scope.**
If you know the document is in the `engineering` category or tagged `python`, set those filters. They cut the candidate pool at the database level before any ML runs, improving both speed and precision.

**Raise `top_k` only when you need recall.**
The default of 5 is suitable for most queries. If you are summarizing a broad topic across many documents, raise it to 10–20. Keep in mind the cross-encoder scores all `top_k` candidates, so higher values mean slower responses.

**Keep reranking enabled.**
The cross-encoder adds latency (roughly 50–200 ms on CPU for 20 candidates) but meaningfully improves the ordering of results. Disable it only when you are scripting bulk queries where ordering matters less than throughput.

**Break vague questions into focused ones.**
"Tell me everything about the API" retrieves a wide mix of chunks. "What authentication scheme does the API use?" and "What are the API rate limits?" each return tighter, more relevant results.

**Check the heading and source_url fields in results.**
The `heading` on each result tells you which section of the source document matched. The `source_url` links back to the original source. If the preview is truncated, use `GET /documents/{id}` to fetch the full document and navigate to that section.
