#!/usr/bin/env bash
# Native hot-reload dev: runs API (reload) + ingestion worker + UI together,
# streaming all logs. Ctrl-C stops everything cleanly.
# Prereq: `make setup` (creates .cortex_venv + installs deps) and the system
# services (Postgres, Redis, Ollama) from `make mac-setup` / `make linux-setup`.
set -euo pipefail

cd "$(dirname "$0")/.."
VENV_DIR="$PWD/.cortex_venv"
PY="$VENV_DIR/bin/python"

[ -x "$PY" ] || { echo "ERROR: venv missing. Run: make setup" >&2; exit 1; }
[ -f .env ] || { cp .env.example .env; echo "Created .env from example."; }
[ -d rag-frontend/node_modules ] || { echo "ERROR: UI deps missing. Run: make install-rag-ui" >&2; exit 1; }

pids=()
cleanup() {
  echo
  echo "Stopping..."
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "Starting API (:8002), worker, UI (:5173). Ctrl-C to stop all."

( cd rag-backend && exec "$PY" -m uvicorn api.server:app --reload --port 8002 ) & pids+=($!)
( cd rag-backend && exec "$PY" -m arq workers.arq_worker.WorkerSettings ) & pids+=($!)
( cd rag-frontend && exec npm run dev ) & pids+=($!)

wait
