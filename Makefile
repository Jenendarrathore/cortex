# Interpreter used to build the venv. Project targets Python 3.12.
# Override if your 3.12 lives elsewhere:  make setup PY=/path/to/python3.12
PY        ?= python3.12
VENV_DIR  := $(CURDIR)/.cortex_venv
PYTHON    := $(VENV_DIR)/bin/python

# ── Machine setup (run once on a new machine) ─────────────────────────────────

# macOS — requires Homebrew (https://brew.sh)
mac-setup:
	@echo "==> Checking Homebrew..."
	@which brew > /dev/null || (echo "ERROR: Install Homebrew first: https://brew.sh" && exit 1)

	@echo "==> Installing system packages..."
	brew install postgresql@16 pgvector node ollama redis || true

	@echo "==> Starting services..."
	brew services start postgresql@16
	brew services start ollama
	brew services start redis
	@sleep 3

	@echo "==> Pulling Ollama embedding model..."
	ollama pull nomic-embed-text

	@echo "==> Creating database..."
	psql postgres -c "CREATE DATABASE cortex_rag;" 2>/dev/null || true
	psql postgres -c "CREATE USER raguser WITH PASSWORD 'rag3214';" 2>/dev/null || true
	psql postgres -c "GRANT ALL PRIVILEGES ON DATABASE cortex_rag TO raguser;" 2>/dev/null || true
	psql cortex_rag -c "GRANT ALL ON SCHEMA public TO raguser;" 2>/dev/null || true
	psql cortex_rag -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null || true

	@echo ""
	@echo "==> Mac setup done. Now run: make setup"

# Linux — Ubuntu/Debian (requires sudo)
linux-setup:
	@echo "==> Installing system packages..."
	sudo apt-get update -q
	sudo apt-get install -y postgresql postgresql-contrib build-essential git curl redis-server

	@echo "==> Installing pgvector..."
	sudo apt-get install -y postgresql-16-pgvector 2>/dev/null || \
		(git clone --branch v0.7.0 https://github.com/pgvector/pgvector.git /tmp/pgvector && \
		 cd /tmp/pgvector && make && sudo make install)

	@echo "==> Installing Node.js 20 via NodeSource..."
	curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
	sudo apt-get install -y nodejs

	@echo "==> Installing Ollama..."
	curl -fsSL https://ollama.com/install.sh | sh

	@echo "==> Starting PostgreSQL..."
	sudo systemctl enable postgresql
	sudo systemctl start postgresql
	@sleep 2

	@echo "==> Starting Redis..."
	sudo systemctl enable redis-server
	sudo systemctl start redis-server

	@echo "==> Starting Ollama (background)..."
	ollama serve &
	@sleep 3

	@echo "==> Pulling Ollama embedding model..."
	ollama pull nomic-embed-text

	@echo "==> Creating database..."
	sudo -u postgres psql -c "CREATE DATABASE cortex_rag;" 2>/dev/null || true
	sudo -u postgres psql -c "CREATE USER raguser WITH PASSWORD 'rag3214';" 2>/dev/null || true
	sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE cortex_rag TO raguser;" 2>/dev/null || true
	sudo -u postgres psql -d cortex_rag -c "GRANT ALL ON SCHEMA public TO raguser;" 2>/dev/null || true
	sudo -u postgres psql -d cortex_rag -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null || true

	@echo ""
	@echo "==> Linux setup done. Now run: make setup"

# Windows — WSL2 required (run this inside WSL2 terminal)
windows-setup:
	@echo ""
	@echo "Windows: Make runs inside WSL2 only."
	@echo ""
	@echo "Steps:"
	@echo "  1. Install WSL2: open PowerShell as Admin and run:"
	@echo "       wsl --install"
	@echo "  2. Open the WSL2 Ubuntu terminal"
	@echo "  3. Navigate to this project folder"
	@echo "  4. Run: make linux-setup"
	@echo ""
	@echo "Ollama native Windows installer also available at https://ollama.com"
	@echo ""

# ── Project setup ─────────────────────────────────────────────────────────────

# Create venv, install all Python + frontend + docs deps
setup:
	$(PY) -m venv $(VENV_DIR)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	cd rag-frontend && npm install
	cd docs && npm install
	@echo ""
	@echo "Setup complete."
	@echo "Activate the venv:  source $(VENV_DIR)/bin/activate"
	@echo "(make targets use it automatically; activate only for manual python/pytest.)"
	@echo "Copy .env.example to .env and fill in credentials."
	@echo "Then run: make rag  |  make rag-ui"

# Install / update Python deps only
install:
	$(PYTHON) -m pip install -r requirements.txt

# Install / update RAG UI deps only
install-rag-ui:
	cd rag-frontend && npm install

# Install / update Docusaurus docs deps only
install-docs:
	cd docs && npm install

# Apply the canonical DB schema (db/schema.sql) — idempotent
init-db:
	cd rag-backend && $(PYTHON) -c "import asyncio; from core.database import init_db; asyncio.run(init_db()); print('schema applied')"

# ── Run ───────────────────────────────────────────────────────────────────────

# Start the RAG HTTP API (port 8002, auto-reload on file changes)
rag:
	cd rag-backend && $(PYTHON) -m uvicorn api.server:app --reload --port 8002

# Start the MCP server (stdio transport — Claude Desktop spawns this)
mcp:
	$(PYTHON) mcp/server.py

# Start the MCP server over HTTP (streamable-http — for remote/multi-client or interactive testing)
mcp-http:
	MCP_TRANSPORT=streamable-http MCP_PORT=$(or $(MCP_PORT),8001) $(PYTHON) mcp/server.py

# Register the running HTTP MCP server (make mcp-http) with the various clients.
# Override target/url with: MCP_NAME=cortex MCP_URL=http://localhost:8001/mcp
mcp-connect-claude-cli:
	scripts/mcp-connect-claude-cli.sh

mcp-connect-claude-desktop:
	scripts/mcp-connect-claude-desktop.sh

mcp-connect-codex:
	scripts/mcp-connect-codex.sh

# Register with all clients at once
mcp-connect: mcp-connect-claude-cli mcp-connect-claude-desktop mcp-connect-codex

# Start the ARQ ingestion worker as a standalone process (alternative to in-process worker)
# Use this when you want to run the worker separately from the API (e.g. Docker, scaling)
rag-worker:
	cd rag-backend && $(PYTHON) -m arq workers.arq_worker.WorkerSettings

# Start the RAG admin UI dev server (port 5173)
rag-ui:
	cd rag-frontend && npm run dev

# Start the Docusaurus docs site (port 3000)
docs:
	cd docs && npm start

# ── Docker (one-command stack) ────────────────────────────────────────────────

COMPOSE := docker compose

# Dead-simple: clone -> make quickstart. Creates .env, builds, starts the whole
# stack, waits for health, seeds a sample doc, prints the URLs. Idempotent.
quickstart:
	./scripts/quickstart.sh

# Ingest a sample document + run a sample search against the running stack.
seed:
	./scripts/seed.sh

# Native hot-reload dev: API + worker + UI together (needs `make setup` first).
dev:
	./scripts/dev.sh

# Build all images.
build:
	$(COMPOSE) build

# Start the full stack (postgres, redis, ollama, backend, worker, mcp, ui, docs).
up:
	$(COMPOSE) up -d

# Start with hot-reload from your working tree.
up-dev:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up

# Stop and remove containers (keeps volumes / data).
down:
	$(COMPOSE) down

# Tail logs for all services.
logs:
	$(COMPOSE) logs -f

# ── Quality ───────────────────────────────────────────────────────────────────

# Lint Python (ruff). Install: pip install -r requirements-dev.txt
lint:
	$(PYTHON) -m ruff check rag-backend mcp tests

# Smoke test against a running stack (make up first, or set BASE_URL).
test:
	$(PYTHON) -m pytest tests/ -v

# ── Helpers ───────────────────────────────────────────────────────────────────

# Kill any process on ports 8002, 5173, or 3000
kill:
	-lsof -ti:8002 | xargs kill 2>/dev/null
	-lsof -ti:5173 | xargs kill 2>/dev/null
	-lsof -ti:3000 | xargs kill 2>/dev/null

.PHONY: mac-setup linux-setup windows-setup setup install install-rag-ui install-docs init-db rag rag-worker mcp mcp-http mcp-connect mcp-connect-claude-cli mcp-connect-claude-desktop mcp-connect-codex rag-ui docs quickstart seed dev build up up-dev down logs lint test kill
