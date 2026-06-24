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

Requires Docker + Docker Compose. First build is large (~torch + sentence-transformers).

```bash
git clone <your-fork-url> cortex && cd cortex
cp .env.example .env          # set PGPASSWORD
docker compose up             # or: make up   (detached)
```

Then open:

- **Admin UI** → http://localhost:5173
- **API docs** → http://localhost:8002/docs
- **Docs site** → http://localhost:3000

Ingest your first document from the UI, or via the API:

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

Driven by the Makefile — installs Postgres+pgvector, Redis, Ollama, Node:

```bash
make mac-setup      # or: make linux-setup  /  make windows-setup (WSL2)
make setup          # venv + python + frontend + docs deps
cp .env.example .env
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
mcp/           MCP server exposing retrieval/ingestion tools
rag-frontend/  React + Vite admin UI
docs/          Docusaurus documentation site
tests/         Deploy-proving smoke test
```

## Contributing

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, lint/test
commands, and the PR checklist. Be excellent to each other
([CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)).

## License

[AGPL-3.0](LICENSE). If you run a modified Cortex as a network service, the AGPL
requires you to offer your users its source. For a commercial license without that
obligation, contact the maintainers.
