---
sidebar_position: 1
---

# Machine Requirements

Cortex RAG is a fully local system — no cloud accounts, no API keys, no data leaving your machine. Everything runs on your hardware: the embedding model via Ollama, the reranker via HuggingFace, and the vector store via PostgreSQL. This page tells you what you need before running `make mac-setup` or `make linux-setup`.

---

## Hardware

| Resource | Minimum | Recommended | Notes |
|----------|---------|-------------|-------|
| RAM | 8 GB | 16 GB | The reranker and embedding model both load into memory; 8 GB works but leaves little headroom for the OS and browser |
| Disk | 10 GB free | 20 GB free | torch + sentence-transformers ~2 GB, Ollama models ~2 GB, Python venv + npm deps ~1 GB, PostgreSQL data grows with your corpus |
| CPU | Any modern x86_64 or ARM64 | Apple Silicon M-series or multi-core x86 | All inference runs on CPU by default; Apple Silicon gets Metal acceleration via Ollama automatically |
| GPU | Not required | Speeds up reranker | For small to medium corpora the reranker is fast enough on CPU (~50 ms per query); a CUDA GPU helps only if you are reranking thousands of chunks |

:::tip Apple Silicon
Apple Silicon (M1/M2/M3/M4) is the best-tested environment for Cortex RAG. Ollama uses Metal for embeddings and the unified memory architecture handles the reranker model efficiently without a discrete GPU.
:::

---

## Supported Operating Systems

| OS | Version | Notes |
|----|---------|-------|
| macOS | 13 Ventura or later | Primary development platform; `make mac-setup` handles everything via Homebrew |
| Ubuntu / Debian | Ubuntu 22.04 LTS or later | `make linux-setup` handles everything via apt; other Debian-based distros should work |
| Windows | Windows 10/11 via WSL2 | Run `make windows-setup` for printed instructions, then follow with `make linux-setup` inside WSL2 |

:::note Windows (WSL2)
Native Windows (PowerShell/CMD) is not supported. You must use WSL2 with an Ubuntu 22.04+ distribution. PostgreSQL, Ollama, and Python all run inside the WSL2 environment.
:::

---

## Required Software

These packages must be present before running `make setup`. The platform setup commands (`make mac-setup` / `make linux-setup`) install all of them automatically.

### Python 3.11+

The backend runs on Python. The project is developed against 3.12 but any 3.11+ release works.

```bash
# macOS
brew install python@3.12

# Ubuntu 22.04+
sudo apt update && sudo apt install -y python3 python3-pip python3-venv

# Verify
python3 --version   # must show 3.11 or higher
```

### Node.js 18+

Required for the Vite + React admin frontend and the Docusaurus documentation site.

```bash
# macOS
brew install node

# Ubuntu (via NodeSource)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Verify
node --version   # must show v18 or higher
npm --version
```

### PostgreSQL 16+

Cortex RAG uses PostgreSQL as its vector store (via the pgvector extension). Version 16 is recommended because the pgvector apt package is packaged against it on Ubuntu.

```bash
# macOS
brew install postgresql@16
brew services start postgresql@16

# Ubuntu
sudo apt install -y postgresql postgresql-contrib

# Verify
psql --version   # should show 16.x or higher
```

### pgvector Extension

pgvector adds a `vector` column type and approximate nearest-neighbour index support to PostgreSQL. It must be installed before the backend starts — the schema migration will fail without it.

```bash
# macOS
brew install pgvector

# Ubuntu (matches your PostgreSQL major version)
sudo apt install -y postgresql-16-pgvector

# Verify (run as the postgres superuser)
psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;" cortex_rag
```

The backend applies `CREATE EXTENSION IF NOT EXISTS vector` automatically on startup, but the shared library must already be present on the system.

### Ollama

Ollama is the local model runtime used to generate 768-dimensional embeddings with `nomic-embed-text`. It exposes a REST API at `http://localhost:11434` that the backend calls for every ingest and search operation.

```bash
# macOS
brew install ollama

# Linux (any distro)
curl -fsSL https://ollama.com/install.sh | sh

# Start the server
ollama serve   # runs in the foreground; open a new terminal for subsequent steps

# Verify
ollama list
```

---

## Required Ollama Model

After installing Ollama you must pull the embedding model:

```bash
ollama pull nomic-embed-text
```

`nomic-embed-text` produces 768-dimensional vectors. This dimensionality is hardcoded in the pgvector column definition (`vector(768)`) and in the embedder. Do not swap this model without also migrating the database schema and re-ingesting all documents.

The `make mac-setup` and `make linux-setup` commands pull this model automatically as their final step.

---

## Auto-Downloaded on First Run

You do not need to install these manually. They are fetched on first backend startup.

| Component | Source | Size | Cache location |
|-----------|--------|------|---------------|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | HuggingFace Hub (via sentence-transformers) | ~85 MB | `~/.cache/huggingface/hub/` |

The reranker model is loaded into memory the first time a search request arrives. Expect a 2–3 second pause on the first query; subsequent queries are fast. The model is not downloaded again after the initial cache is populated.

---

## Why Local-First?

Cortex RAG deliberately avoids cloud dependencies:

- **Embeddings** — Ollama runs `nomic-embed-text` locally. No text leaves your machine to generate vectors.
- **Reranking** — `cross-encoder/ms-marco-MiniLM-L-6-v2` runs via sentence-transformers on your CPU (or GPU). No inference API calls.
- **Vector storage** — pgvector inside your own PostgreSQL instance. No managed vector database subscription.
- **LLM** — Claude Desktop connects to the MCP server over stdio. The RAG layer only retrieves context; what you do with that context in Claude Desktop is your choice.

The trade-off is that you need a reasonably capable machine (see the hardware table above) and must manage the local services yourself. For personal or small-team use this is usually the right trade: full data ownership, no per-query cost, no internet dependency at query time.

---

## Quick Compatibility Check

Run this before `make setup` to confirm all prerequisites are present:

```bash
python3 --version   # 3.11+
node --version      # 18+
psql --version      # 16+
ollama list         # nomic-embed-text should appear
```

If any command fails or returns a version below the minimum, revisit the relevant section above or re-run `make mac-setup` / `make linux-setup`.
