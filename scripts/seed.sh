#!/usr/bin/env bash
# Ingest one sample document and run a sample search, so a fresh dev sees the
# whole round-trip (ingest -> async worker -> hybrid search) working immediately.
# Targets the running stack. Override with: BASE_URL=http://host:8002 ./scripts/seed.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8002}"
API_KEY="${API_KEY:-}"
AUTH=()
[ -n "$API_KEY" ] && AUTH=(-H "X-API-Key: $API_KEY")

green() { printf '\033[32m%s\033[0m\n' "$1"; }

command -v curl >/dev/null 2>&1 || { echo "ERROR: curl required." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 required (for JSON parsing)." >&2; exit 1; }

# ── 1. Enqueue ingestion of a sample doc ──────────────────────────────────────
RESP="$(curl -fsS ${AUTH[@]+"${AUTH[@]}"} -X POST "$BASE_URL/documents/text" \
  -H 'Content-Type: application/json' \
  -d '{"title":"cortex-welcome","content":"# Welcome to Cortex\n\nCortex is a self-hosted, privacy-first RAG knowledge base. It ingests your markdown and text, then retrieves it with hybrid search: dense vector similarity plus full-text search, fused and reranked. Embeddings run locally via Ollama, so your documents never leave your machine. It also exposes retrieval over MCP for Claude Desktop and Cursor."}')"

JOB_ID="$(printf '%s' "$RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["job_id"])')"
echo "Enqueued ingestion job: $JOB_ID"

# ── 2. Poll the job until it finishes ─────────────────────────────────────────
for i in $(seq 1 60); do
  STATUS="$(curl -fsS ${AUTH[@]+"${AUTH[@]}"} "$BASE_URL/jobs/$JOB_ID" | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])')"
  case "$STATUS" in
    done|completed|success) green "Ingestion done."; break ;;
    failed|error) echo "ERROR: ingestion job failed. Check: docker compose logs worker" >&2; exit 1 ;;
  esac
  [ "$i" -eq 60 ] && { echo "ERROR: ingestion did not finish in time (worker running?)." >&2; exit 1; }
  sleep 2
done

# ── 3. Prove search returns the doc ───────────────────────────────────────────
green "Sample search ('what does cortex store?'):"
curl -fsS ${AUTH[@]+"${AUTH[@]}"} -X POST "$BASE_URL/search" \
  -H 'Content-Type: application/json' \
  -d '{"query":"what does cortex store?","top_k":3}' \
  | python3 -m json.tool
