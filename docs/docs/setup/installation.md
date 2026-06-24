---
sidebar_position: 2
---

# Installation Guide

> This guide walks you from a bare machine to a fully running Cortex RAG instance.
> For a quick command reference see [../make-commands.md](../make-commands.md) | Architecture: [../architecture.md](../architecture.md)

---

## Prerequisites

### Hardware

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| RAM | 8 GB | 16 GB |
| Disk | 10 GB free | 20 GB free |
| CPU | Any modern x86_64 / ARM | Apple Silicon or multi-core x86 |
| GPU | Not required | Speeds up reranker (optional) |

> The largest disk consumers are PyTorch + sentence-transformers (~3 GB) and the Ollama embedding model (~2 GB).

### Operating System

- macOS 13 or later
- Linux — Ubuntu 22.04 / Debian 12 or later
- Windows — via WSL2 (follow the Windows section below, then use the Linux path)

---

## Step 1 — One-command machine setup

This installs every system-level dependency: PostgreSQL 16, pgvector, Node.js, Ollama, pulls the `nomic-embed-text` embedding model, and creates the database and user.

Pick the command that matches your OS and run it once from the project root (`cortex/`).

### macOS

Requires [Homebrew](https://brew.sh). If you do not have it:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Then run:

```bash
make mac-setup
```

What `make mac-setup` does, in order:

1. `brew install postgresql@16` — installs PostgreSQL 16
2. `brew install pgvector` — installs the pgvector extension for PostgreSQL
3. `brew services start postgresql@16` — starts PostgreSQL and enables it at login
4. `brew install node` — installs Node.js (LTS)
5. `brew install ollama` — installs Ollama
6. `brew services start ollama` — starts the Ollama server on `http://localhost:11434`
7. `brew install redis` — installs Redis (ARQ job queue broker)
8. `brew services start redis` — starts Redis on `redis://localhost:6379`
9. `ollama pull nomic-embed-text` — downloads the 768-dim embedding model (~270 MB)
10. Creates the `cortex_rag` database and `raguser` role in PostgreSQL

### Linux (Ubuntu / Debian)

Requires `sudo` access.

```bash
make linux-setup
```

What `make linux-setup` does, in order:

1. `apt-get update` and installs `postgresql`, `postgresql-contrib`, `build-essential`, `git`, `curl`, `redis-server`
2. Builds and installs the pgvector extension from source
3. Installs Node.js 20 via NodeSource apt repository
4. Downloads and installs Ollama via its official install script
5. Starts PostgreSQL, Redis, and Ollama; pulls `nomic-embed-text`
6. Creates the `cortex_rag` database and `raguser` role via `psql`

### Windows (WSL2)

Windows is supported through WSL2. First, print the WSL2 setup instructions:

```bash
make windows-setup
```

Follow the printed steps to install and enter WSL2, then run the Linux setup from inside the WSL2 shell:

```bash
make linux-setup
```

All subsequent commands in this guide run inside WSL2.

---

## Step 2 — Configure environment

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

Open `.env` in your editor. The default values work if you ran `make mac-setup` or `make linux-setup` without customisation:

```bash
PGHOST=localhost       # PostgreSQL host
PGPORT=5432            # PostgreSQL port (default)
PGDATABASE=cortex_rag  # Database name created by the setup command
PGUSER=raguser         # DB role created by the setup command
PGPASSWORD=rag3214     # Password for raguser — change this if you set a different one
```

**Variable reference**

| Variable | Purpose | Default |
|----------|---------|---------|
| `PGHOST` | Hostname or IP of your PostgreSQL server | `localhost` |
| `PGPORT` | TCP port PostgreSQL listens on | `5432` |
| `PGDATABASE` | Name of the database Cortex RAG uses | `cortex_rag` |
| `PGUSER` | PostgreSQL role the backend authenticates as | `raguser` |
| `PGPASSWORD` | Password for `PGUSER` | `rag3214` |
| `REDIS_URL` | Redis connection URL for the ARQ job queue | `redis://localhost:6379` |
| `API_KEY` | Optional API key auth (leave empty to disable) | _(empty)_ |

> If you set a different password when creating the database manually, update `PGPASSWORD` to match.

---

## Step 3 — Install project dependencies

```bash
make setup
```

What `make setup` does:

1. Creates a Python virtual environment at `.cortex_venv/` in the project root
2. Installs all pinned Python packages from `requirements.txt` into the venv
   - Includes FastAPI, SQLAlchemy, psycopg3, pgvector, sentence-transformers, PyTorch, transformers (for the `bert-base-uncased` tokenizer), and the MCP SDK
   - First run takes 5–10 minutes; PyTorch alone is ~2 GB
3. Runs `npm install` inside `rag-frontend/` to install the React + Vite + shadcn/ui dependencies

> The reranker model (`cross-encoder/ms-marco-MiniLM-L-6-v2`, ~85 MB) is downloaded automatically from HuggingFace on the first backend start. It is cached at `~/.cache/huggingface/` for subsequent runs.

---

## Step 4 — Start services

Services must start in this order because each one depends on the previous.

### 1. PostgreSQL

**macOS:**
```bash
brew services start postgresql@16
```

**Linux:**
```bash
sudo systemctl start postgresql
```

Verify it is running:
```bash
psql -U raguser -d cortex_rag -c "SELECT 1;"
```

### 2. Redis

**macOS:**
```bash
brew services start redis
```

**Linux:**
```bash
sudo systemctl start redis-server
```

Verify it is running:
```bash
redis-cli ping   # should return PONG
```

### 3. Ollama

**macOS:**
```bash
brew services start ollama
```

**Linux / WSL2:**
```bash
ollama serve
```

Verify the embedding model is available:
```bash
ollama list   # should show nomic-embed-text in the list
```

If `nomic-embed-text` is missing:
```bash
ollama pull nomic-embed-text
```

### 4. Backend (RAG API)

Open a terminal and run from the project root:

```bash
make rag
```

This starts the FastAPI backend on `http://localhost:8002`. On first start it also applies the database schema (creates the `documents` and `chunks` tables and all indexes) and loads the reranker model into memory.

Expected output:

```
INFO:     Uvicorn running on http://0.0.0.0:8002 (Press CTRL+C to quit)
```

### 5. Admin panel (optional)

Open a second terminal:

```bash
make rag-ui
```

This starts the Vite dev server for the React admin panel on `http://localhost:5173`.

---

## Step 5 — Verify everything works

### Health check

```bash
curl http://localhost:8002/health
```

Expected response:

```json
{"status": "ok"}
```

### Admin panel

Open `http://localhost:5173` in your browser. You should see the Cortex RAG admin panel with three tabs: Documents, Ingest, and Search.

### End-to-end smoke test

Ingest a test document and run a search to confirm the full pipeline works:

```bash
# Ingest a document via the API
curl -X POST http://localhost:8002/documents/text \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Cortex RAG is a local retrieval-augmented generation system.",
    "file_path": "test/smoke-test.md",
    "title": "Smoke Test",
    "category": "test"
  }'

# Search for it
curl -X POST http://localhost:8002/search \
  -H "Content-Type: application/json" \
  -d '{"query": "what is Cortex RAG", "top_k": 3}'
```

The search response should return the ingested chunk with a relevance score.

---

## Claude Desktop integration (MCP)

To use Cortex RAG tools directly inside Claude Desktop, add the following to `~/.claude/claude_desktop_config.json` (replace `/path/to/cortex` with the absolute path to your project root):

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

Set `RAG_API_KEY` only if you have enabled `API_KEY` in `.env`. Leave it empty otherwise.

Restart Claude Desktop after saving the file. The following MCP tools become available:

| Tool | Description |
|------|-------------|
| `ingest_document` | Add a markdown document to the knowledge base |
| `retrieve` | Search the knowledge base with optional filters |
| `list_knowledge_base` | List all ingested documents |

> The backend (`make rag`) must be running for MCP tools to work.

---

## Updating dependencies

```bash
make install        # update Python packages from requirements.txt
make install-rag-ui # update frontend npm packages
```

---

## Troubleshooting

**Port already in use:**
```bash
make kill   # kills any processes on ports 8002 and 5173
```

**Backend fails to connect to Redis:**
- Confirm Redis is running: `redis-cli ping` should return `PONG`
- macOS: `brew services start redis`
- Linux: `sudo systemctl start redis-server`
- Check `REDIS_URL` in `.env` (default: `redis://localhost:6379`)

**Backend fails to connect to PostgreSQL:**
- Confirm PostgreSQL is running: `pg_isready -h localhost -p 5432`
- Check `.env` credentials match those used when creating the database

**Embedding errors — `connection refused`:**
Ollama is not running. Start it with `ollama serve` (Linux/WSL2) or `brew services start ollama` (macOS).

**`nomic-embed-text` model not found:**
```bash
ollama pull nomic-embed-text
```

**pgvector extension missing:**
```bash
psql -U raguser -d cortex_rag -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

**Reranker slow on first query:**
Normal behaviour — the cross-encoder loads into memory on first use (2–3 seconds). Subsequent queries are fast.

**API import errors:**
Always run `make rag` from the project root (`cortex/`), not from inside `rag-backend/`.

**`make setup` fails on PyTorch install:**
Ensure you have at least 10 GB of free disk space and a stable internet connection. PyTorch is ~2 GB.
