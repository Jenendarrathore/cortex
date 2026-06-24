---
sidebar_position: 3
---

# Make Commands

## What is Make?

`make` is a command runner. The `Makefile` at the project root defines named shortcuts (called **targets**). Instead of typing a long command, you type `make <target>`.

```bash
# Without make
/path/to/cortex/.cortex_venv/bin/python -m uvicorn api.server:app --reload --port 8002

# With make
make rag
```

Same result. Make just saves typing and ensures the right venv Python is used.

---

## How to Use

Always run from the `cortex/` root directory (where the `Makefile` lives):

```bash
cd /path/to/cortex
make rag        # start API backend
make rag-ui     # start admin frontend
make docs       # start documentation site
make mcp        # start MCP server
```

---

## Available Targets

### Machine setup (run once)

| Command | What it runs | When to use |
|---------|-------------|-------------|
| `make mac-setup` | Homebrew install + PostgreSQL + pgvector + Node + Ollama + DB init | First time on a Mac |
| `make linux-setup` | apt install + pgvector + Node 20 + Ollama + DB init | First time on Linux or WSL2 |
| `make windows-setup` | Prints WSL2 instructions | First time on Windows |

### Project setup

| Command | What it runs | When to use |
|---------|-------------|-------------|
| `make setup` | Creates `.cortex_venv`, installs Python deps, `rag-frontend` npm deps, and `docs` npm deps | After machine-setup, or first clone on an existing machine |
| `make install` | `pip install -r requirements.txt` | Updating Python deps only |
| `make install-rag-ui` | `npm install` in `rag-frontend/` | Updating frontend deps only |
| `make install-docs` | `npm install` in `docs/` | Updating Docusaurus deps only |

### Run services

| Command | Port | What it starts |
|---------|------|----------------|
| `make rag` | 8002 | RAG backend (FastAPI + uvicorn, auto-reload) — worker starts automatically |
| `make rag-worker` | — | ARQ ingestion worker as a standalone process (for Docker / separate scaling) |
| `make rag-ui` | 5173 | Admin UI (Vite dev server) |
| `make docs` | 3000 | Docusaurus documentation site |
| `make mcp` | stdio | MCP server (Claude Desktop spawns this automatically) |

### Helpers

| Command | What it does |
|---------|-------------|
| `make kill` | Kills any process on ports 8002, 5173, and 3000 |

---

## How the Makefile Works

```makefile
VENV_DIR := $(CURDIR)/.cortex_venv
PYTHON   := $(VENV_DIR)/bin/python

rag:
	cd rag-backend && $(PYTHON) -m uvicorn api.server:app --reload --port 8002
```

- `$(CURDIR)` — Make built-in that expands to the absolute path of wherever you ran `make` from. This makes the venv path portable — no hardcoded `/Users/yourname/...`.
- `PYTHON :=` — defines the venv Python path once, reused in every target.
- `rag:` — target name. `make rag` runs everything indented under it.
- Lines under a target **must be indented with a tab** (not spaces) — Make requirement.
- `$(PYTHON)` — expands the variable inline.
- `cd rag-backend &&` — changes directory first, then runs uvicorn. Required because `rag-backend` uses flat imports (`from core.config import settings`) that only resolve when run from inside that directory.

---

## Typical workflow

### First time on a new machine

```bash
# 1. Install system dependencies
make mac-setup      # or linux-setup / windows-setup

# 2. Install project dependencies
make setup

# 3. Copy and fill in environment config
cp .env.example .env
# Edit .env: set PGPASSWORD (and optionally API_KEY)

# 4. Start services
make rag            # terminal 1 — backend on :8002
make rag-worker     # terminal 2 — ingestion worker (required to process jobs)
make rag-ui         # terminal 3 — admin UI on :5173
make docs           # terminal 4 — docs on :3000 (optional)
```

### Day-to-day development

```bash
make rag            # start backend
make rag-worker     # start ingestion worker
make rag-ui         # start admin UI
make kill           # stop everything (backend + frontend + docs)
```

---

## Common Mistakes

**Wrong directory** — `make` must be run from `cortex/`, not from inside `rag-backend/`, `mcp/`, or any subdirectory.

**Port already in use** — if a previous server didn't stop cleanly, run:
```bash
make kill
```
This kills any process on ports 8002 (backend), 5173 (admin UI), and 3000 (docs).

Or kill individual ports manually:
```bash
lsof -ti:8002 | xargs kill   # backend
lsof -ti:5173 | xargs kill   # admin UI
lsof -ti:3000 | xargs kill   # docs
```

**Tab vs space** — if you edit the Makefile, indent target commands with a real tab character, not spaces. Make will error with `missing separator` otherwise.

**Venv not found** — if `make rag` fails with "No such file or directory", run `make setup` first to create the venv.
