<h1 align="center">Cortex</h1>

<p align="center">
  <b>Self-hosted, privacy-first RAG knowledge base.</b><br>
  Run the whole stack on your own box. Your documents never leave it.<br>
  Plugs into Claude Desktop / Cursor over MCP.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: AGPL-3.0" src="https://img.shields.io/badge/License-AGPL%20v3-blue.svg"></a>
  <img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-blue.svg">
  <img alt="Self-hosted" src="https://img.shields.io/badge/deploy-docker%20compose-2496ED.svg">
</p>

---

## What is Cortex?

Cortex is a single-tenant RAG (retrieval-augmented generation) system you host
yourself. Ingest your markdown and text documents; retrieve them with **hybrid
search** — dense vector similarity **+** full-text search, fused and **reranked**.
Embeddings run **locally via Ollama**, so no document or query ever leaves your
machine.

It exposes the same retrieval over an **MCP server**, so Claude Desktop, Cursor,
and other MCP clients can search your private knowledge base directly.

### Features

- 🔒 **Local-only embeddings** — Ollama (`nomic-embed-text`), no cloud provider.
- 🔎 **Hybrid retrieval** — pgvector ANN + Postgres FTS + cross-encoder rerank.
- 🧩 **MCP server** — query/ingest tools for Claude Desktop, Cursor, etc.
- 📥 **Async ingestion** — upload files, raw text, or a server folder; tracked jobs with live progress.
- 🖥️ **Admin UI** — React app to ingest, browse documents, and search.
- 📚 **Docs site** — bundled Docusaurus documentation.
- 🐳 **One command** — `docker compose up` brings up the entire stack.

## Architecture

| Service    | Image                    | Purpose                              | Port  |
|------------|--------------------------|--------------------------------------|-------|
| `postgres` | pgvector/pgvector:pg16   | documents, chunks, vectors, jobs     | 5432  |
| `redis`    | redis:7                  | ARQ job queue                        | 6379  |
| `ollama`   | ollama/ollama            | local embedding model                | 11434 |
| `backend`  | cortex-py                | FastAPI API + retrieval              | 8002  |
| `worker`   | cortex-py                | ARQ ingestion worker                 | —     |
| `mcp`      | cortex-py                | MCP server (streamable-http)         | 8001  |
| `frontend` | cortex-web               | React admin UI (nginx)               | 5173  |
| `docs`     | cortex-docs              | Docusaurus docs (nginx)              | 3000  |

The three Python services share one image (`cortex-py`), run with different commands.

## Quickstart (Docker)

The only prerequisite is **Docker + Docker Compose**. One command does everything —
creates `.env`, builds, starts the full stack, waits until it's healthy, and seeds
a sample document so search works immediately:

```bash
git clone <your-fork-url> cortex && cd cortex
make quickstart
```

> First build is large (torch + sentence-transformers) and can take 10–20 min.
> No `.env` editing needed for local use — sane defaults are baked in.

When it finishes it prints your URLs:

- **Admin UI** → http://localhost:5173
- **API docs** → http://localhost:8002/docs
- **Docs site** → http://localhost:3000
- **MCP** → http://localhost:8001/mcp

Useful follow-ups: `make logs` (tail everything) · `make seed` (re-seed sample) ·
`make down` (stop, keep data). Prefer raw compose? `docker compose up -d --build`
still works.

The seeded sample means search already returns results. Ingest your own from the
UI, or via the API:

```bash
curl -X POST http://localhost:8002/documents/text \
  -H 'Content-Type: application/json' \
  -d '{"content":"# Hello\nCortex stores this and makes it searchable.","title":"hello"}'

curl -X POST http://localhost:8002/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"what does cortex store?","top_k":5}'
```

## Connect Claude Desktop (MCP)

The stack runs an MCP server. Point Claude Desktop at the running container by
adding this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cortex": {
      "command": "docker",
      "args": ["exec", "-i", "cortex-mcp-1", "python", "/app/mcp/server.py"],
      "env": { "MCP_TRANSPORT": "stdio", "RAG_SERVER_URL": "http://backend:8002" }
    }
  }
}
```

Config file location:

- **macOS** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux** `~/.config/Claude/claude_desktop_config.json`
- **Windows** `%APPDATA%/Claude/claude_desktop_config.json`

Restart Claude Desktop to load it. (Confirm your container name with `docker ps`.)

## Bare-metal install (no Docker)

For contributors who want native hot-reload. Driven by the Makefile — installs
Postgres+pgvector, Redis, Ollama, Node:

```bash
make mac-setup      # or: make linux-setup  /  make windows-setup (WSL2)
make setup          # venv + python + frontend + docs deps
make dev            # API :8002 + worker + UI :5173, all hot-reload, Ctrl-C stops all
```

`make dev` auto-creates `.env` and runs the three core services together. Need them
separately (e.g. for the docs site)? Run individually:

```bash
make rag            # API      :8002
make rag-worker     # worker
make rag-ui         # UI       :5173
make docs           # docs     :3000
```

## Configuration

All config is environment variables (see [.env.example](.env.example)):

| Var               | Default                  | Notes                                            |
|-------------------|--------------------------|--------------------------------------------------|
| `PGPASSWORD`      | —                        | **Change before any non-local deploy.**          |
| `API_KEY`         | _(empty)_                | If set, all routes require `X-API-Key`.          |
| `CORS_ORIGINS`    | `http://localhost:5173`  | Comma-separated, or `*`.                          |
| `OLLAMA_URL`      | `http://localhost:11434` | Local embeddings endpoint.                        |
| `EMBED_MODEL`     | `nomic-embed-text`       | Ollama model pulled on first run.                 |
| `LICENSE_ENABLED` | `false`                  | Leave off — the OSS build needs no license.       |

> ⚠️ Defaults are tuned for local use. Before exposing Cortex to a network, read
> [SECURITY.md](SECURITY.md): set `API_KEY`, lock `CORS_ORIGINS`, change `PGPASSWORD`,
> and restrict the published DB/Redis/Ollama ports.

## Testing

```bash
make up && make test      # smoke round-trip: health → ingest → search
make lint                 # ruff (python)
```

## Project layout

```
rag-backend/   FastAPI API, ingestion worker, retrieval (vector + FTS + rerank)
  api/routes/    thin HTTP handlers
  services/      business logic (ingest, query, jobs, folder ingest)
  core/          infra (config, db, embedder, reranker, chunker, enums)
  models/        SQLAlchemy ORM   schemas/  Pydantic contracts
  db/schema.sql  source of truth for DDL (mirrored by models + enums)
mcp/           MCP server exposing retrieval/ingestion tools
rag-frontend/  React + Vite admin UI
docs/          Docusaurus documentation site
sample-docs/   Example markdown you can ingest to try Cortex
tests/         Smoke test (live stack) + schema-parity guard (no DB)
```

## Contributing

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, lint/test
commands, and the PR checklist. Be excellent to each other
([CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)).

## License

[AGPL-3.0](LICENSE). If you run a modified Cortex as a network service, the AGPL
requires you to offer your users its source. For a commercial license without that
obligation, contact the maintainers.
