#!/usr/bin/env bash
# Cortex one-command Docker bootstrap.
#   clone -> ./scripts/quickstart.sh -> full stack up, sample data seeded, URLs printed.
# Idempotent: safe to re-run. No manual .env editing required for local use.
set -euo pipefail

cd "$(dirname "$0")/.."

cyan() { printf '\033[36m%s\033[0m\n' "$1"; }
green() { printf '\033[32m%s\033[0m\n' "$1"; }
yellow() { printf '\033[33m%s\033[0m\n' "$1"; }

SEED=1
for arg in "$@"; do
  case "$arg" in
    --no-seed) SEED=0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

# ── 1. Preconditions ──────────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker not installed. https://docs.docker.com/get-docker/" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "ERROR: Docker daemon not running. Start Docker Desktop and retry." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: 'docker compose' v2 required. Update Docker." >&2; exit 1; }

# ── 2. Env (local defaults work as-is; create .env so values are pinned) ───────
if [ ! -f .env ]; then
  cp .env.example .env
  # Pin a real local DB password instead of the change_me placeholder.
  if command -v sed >/dev/null 2>&1; then
    sed -i.bak 's/^PGPASSWORD=change_me$/PGPASSWORD=cortex_local_dev/' .env && rm -f .env.bak
  fi
  green "Created .env (local defaults; edit before any non-local deploy)."
else
  yellow ".env already exists — leaving it untouched."
fi

# Load .env so this shell knows the chosen host ports (compose reads .env itself).
set -a; . ./.env; set +a
BACKEND_PORT="${BACKEND_PORT:-8002}"

# ── 3. Build + start ──────────────────────────────────────────────────────────
cyan "Building images (first run pulls torch + sentence-transformers — can take 10-20 min)..."
docker compose up -d --build

# ── 4. Wait for backend health ────────────────────────────────────────────────
cyan "Waiting for backend health (http://localhost:${BACKEND_PORT}/health)..."
for i in $(seq 1 120); do
  if curl -fsS "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
    green "Backend healthy."
    break
  fi
  if [ "$i" -eq 120 ]; then
    echo "ERROR: backend did not become healthy in time. Check: docker compose logs backend" >&2
    exit 1
  fi
  sleep 5
done

# ── 5. Seed sample data so search works immediately ───────────────────────────
if [ "$SEED" -eq 1 ]; then
  cyan "Seeding a sample document..."
  BASE_URL="http://localhost:${BACKEND_PORT}" ./scripts/seed.sh || yellow "Seed step failed (non-fatal) — stack is still up."
fi

# ── 6. Done ───────────────────────────────────────────────────────────────────
echo
green "Cortex is up."
echo "  Admin UI  -> http://localhost:${FRONTEND_PORT:-5173}"
echo "  API docs  -> http://localhost:${BACKEND_PORT:-8002}/docs"
echo "  Docs site -> http://localhost:${DOCS_PORT:-3000}"
echo "  MCP       -> http://localhost:${MCP_HOST_PORT:-8001}/mcp"
echo
echo "Logs:  docker compose logs -f      Stop:  docker compose down"
