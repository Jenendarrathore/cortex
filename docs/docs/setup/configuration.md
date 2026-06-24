---
sidebar_position: 3
---

# Configuration Reference

All runtime behaviour of Cortex RAG is controlled by a single `.env` file and the
`Settings` class in `rag-backend/core/config.py`. This page covers every variable,
how they are loaded, and how to swap models or change service ports.

---

## `.env` file

The `.env` file lives at the **repository root** (`cortex/.env`). Copy `.env.example`
and edit it before first run:

```bash
cp .env.example .env
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `PGHOST` | `localhost` | PostgreSQL host |
| `PGPORT` | `5432` | PostgreSQL port |
| `PGDATABASE` | `cortex_rag` | Database name |
| `PGUSER` | `raguser` | Database user |
| `PGPASSWORD` | _(empty)_ | Database password — **always set this** |
| `OLLAMA_URL` | `http://localhost:11434` | Base URL for the local Ollama API |
| `EMBED_MODEL` | `nomic-embed-text` | Ollama model used to generate embeddings |
| `RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | sentence-transformers cross-encoder used to rerank results |
| `CHUNK_MAX_TOKENS` | `400` | Maximum token budget per chunk when splitting markdown |
| `CHUNK_OVERLAP_CHARS` | `200` | Character overlap carried over between adjacent chunks |
| `VECTOR_SEARCH_LIMIT` | `50` | Number of candidates returned by the vector (cosine) search stage |
| `FTS_SEARCH_LIMIT` | `50` | Number of candidates returned by the PostgreSQL full-text search stage |
| `RERANK_TOP_N` | `20` | Number of RRF-merged candidates passed to the cross-encoder reranker |
| `API_KEY` | _(empty)_ | Optional API key. When set, all routes require `X-API-Key: <value>` header. Empty string disables auth. |

A minimal working `.env` only needs the `PG*` variables if you accept all other
defaults:

```dotenv
PGHOST=localhost
PGPORT=5432
PGDATABASE=cortex_rag
PGUSER=raguser
PGPASSWORD=changeme
```

---

## API key authentication

Authentication is **disabled by default**. To enable it, set `API_KEY` in `.env`:

```dotenv
API_KEY=your_secret_key_here
```

When set, every request to the backend must include:

```
X-API-Key: your_secret_key_here
```

Requests without the header (or with a wrong key) receive `403 Forbidden`.

To disable auth again, set `API_KEY=` (empty string) or remove the variable.

### Propagating the key to other components

| Component | Variable | Where to set |
|-----------|----------|--------------|
| MCP client (`mcp/client.py`) | `RAG_API_KEY` | MCP server `env` block in `claude_desktop_config.json` |
| Admin UI (`rag-frontend`) | `VITE_API_KEY` | `rag-frontend/.env.local` |

**MCP config example:**

```json
{
  "mcpServers": {
    "cortex": {
      "command": "/path/to/cortex/.cortex_venv/bin/python",
      "args": ["/path/to/cortex/mcp/server.py"],
      "env": {
        "RAG_SERVER_URL": "http://localhost:8002",
        "RAG_API_KEY": "your_secret_key_here"
      }
    }
  }
}
```

**Frontend `.env.local` example:**

```dotenv
VITE_API_URL=http://localhost:8002
VITE_API_KEY=your_secret_key_here
```

Leave `VITE_API_KEY` empty (or omit it) when auth is disabled.

---

## How pydantic-settings loads configuration

`rag-backend/core/config.py` uses **pydantic-settings** (`BaseSettings`) to load
configuration. The env-file path is resolved relative to the `config.py` file
itself so it always points to `cortex/.env` regardless of which directory you
launch the backend from:

```python
# rag-backend/core/config.py
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"  # → cortex/.env

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")
    ...

settings = Settings()
```

**Resolution order** (highest priority first):

1. Real environment variables (e.g. exported in your shell or set by a process manager)
2. `.env` file values
3. Field defaults defined in `Settings`

This means you can override any value without touching the `.env` file by
exporting it in your shell before running `make rag`.

---

## `Settings` class properties

The `Settings` instance (`settings`) exposes the following computed properties in
addition to the raw fields listed above:

### `database_url`

Assembles the SQLAlchemy connection string from the `PG*` fields:

```
postgresql+psycopg://<pguser>:<pgpassword>@<pghost>:<pgport>/<pgdatabase>
```

This URL is passed directly to `create_async_engine` in `rag-backend/core/database.py`.
You never need to construct it manually.

---

## Service ports

| Service | Default port | Started by |
|---|---|---|
| RAG backend (FastAPI) | **8002** | `make rag` |
| Admin UI (Vite dev server) | **5173** | `make rag-ui` |
| Docusaurus docs site | **3000** | `make docs` |
| Ollama | **11434** | system / `ollama serve` |
| PostgreSQL | **5432** | system / Docker |

The MCP server uses **stdio** transport and has no listening port.

To change the backend port, pass `--port` to Uvicorn inside the `Makefile`:

```makefile
rag:
    .cortex_venv/bin/uvicorn rag-backend.api.server:app --reload --port 8003
```

Update `RAG_SERVER_URL` in the MCP server config and `VITE_API_URL` in the frontend
`.env.local` to match the new port.

---

## Frontend environment variables

The frontend reads its own environment from `rag-frontend/.env.local`. Create this
file if it does not exist:

```dotenv
VITE_API_URL=http://localhost:8002
VITE_API_KEY=
```

| Variable | Description |
|----------|-------------|
| `VITE_API_URL` | Base URL of the RAG backend. Must match the port the backend is running on. |
| `VITE_API_KEY` | API key sent as `X-API-Key` on every request. Leave empty when auth is disabled. |

---

## Changing the embedding model

The default embedding model is `nomic-embed-text` (768-dimensional vectors via
Ollama). Chunks are stored with `vector(768)` in PostgreSQL, so **the replacement
model must also produce 768-dimensional vectors** or you must drop and recreate the
`chunks` table.

**Steps to swap the model:**

1. Pull the new model with Ollama:

   ```bash
   ollama pull <new-model>
   ```

2. Set `EMBED_MODEL` in `.env`:

   ```dotenv
   EMBED_MODEL=mxbai-embed-large
   ```

3. If the new model has a **different vector dimension**, update the `chunks` table:

   ```sql
   ALTER TABLE chunks DROP COLUMN embedding;
   ALTER TABLE chunks ADD COLUMN embedding vector(<new-dim>);
   ```

   And update the index:

   ```sql
   DROP INDEX IF EXISTS chunks_embedding_idx;
   CREATE INDEX chunks_embedding_idx ON chunks
       USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
   ```

4. Re-ingest all documents so embeddings are regenerated with the new model:

   ```bash
   # Delete all documents via the admin UI or the API, then re-ingest
   make rag-ui
   ```

:::caution
Mixing embeddings from different models in the same `chunks` table will produce
meaningless similarity scores. Always re-ingest everything when changing
`EMBED_MODEL`.
:::

---

## Changing the reranker

The default cross-encoder is `cross-encoder/ms-marco-MiniLM-L-6-v2`, loaded at
startup by `rag-backend/core/reranker.py` via **sentence-transformers**. The
reranker operates on raw text and is model-agnostic — no schema changes are needed
when swapping it.

**Steps to swap the reranker:**

1. Set `RERANK_MODEL` in `.env`:

   ```dotenv
   RERANK_MODEL=cross-encoder/ms-marco-TinyBERT-L-2-v2
   ```

2. Restart the backend:

   ```bash
   make rag
   ```

sentence-transformers downloads the model from Hugging Face on first load
(cached to `~/.cache/huggingface/hub`). No re-ingestion is required.

To **disable reranking** entirely, pass `"rerank": false` in the search request
body:

```json
{
  "query": "...",
  "top_k": 10,
  "rerank": false
}
```

---

## Tuning search parameters

These settings balance recall quality against latency. The defaults work well for
corpora up to a few thousand chunks.

| Setting | What it controls | Increase when… |
|---|---|---|
| `VECTOR_SEARCH_LIMIT` | Cosine-similarity candidates before RRF | recall feels low |
| `FTS_SEARCH_LIMIT` | Full-text candidates before RRF | keyword results feel incomplete |
| `RERANK_TOP_N` | Merged candidates sent to the cross-encoder | top results feel misordered |
| `CHUNK_MAX_TOKENS` | Chunk size during ingestion | documents are long-form prose |
| `CHUNK_OVERLAP_CHARS` | Overlap between adjacent chunks | context feels cut off at chunk boundaries |

Larger values for `VECTOR_SEARCH_LIMIT`, `FTS_SEARCH_LIMIT`, and `RERANK_TOP_N`
increase latency roughly linearly. The cross-encoder is the dominant cost — keep
`RERANK_TOP_N` at 20 or below on CPU-only hardware.

`ivfflat.probes = 10` is set automatically on every database connection by
`core/database.py`. This improves ANN recall at a small query time cost. The
PostgreSQL default (`probes=1`) is too low for typical use.
