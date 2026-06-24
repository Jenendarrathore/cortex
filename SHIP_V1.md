# Cortex — Sellable Self-Hosted v1 Plan

**Product:** Self-hosted, single-tenant RAG knowledge base. Customer runs the whole
stack on their own box; their data never leaves it. Plugs into Claude Desktop / Cursor
via MCP.

**Buyer:** Devs / teams who need private RAG and won't ship documents to a cloud vendor.

**Decisions (locked):**
- **Licensing: deferred.** v1 ships with no monetization gate. License code becomes
  opt-in, OFF by default. (Revisit post-v1.)
- **Ollama: bundled** in docker-compose; embed model auto-pulled on first run.
- **Single-tenant only.** No `tenant_id`, no multi-customer isolation. Out of scope.

---

## Scope

### Container architecture (the 5 requirements)

One `docker compose up` must: (1) start backend, (2) start frontend, (3) start MCP,
(4) start docs, (5) wire MCP into Claude Desktop.

**Images (3 total):**
- `cortex-py` — ONE Python image built from root `requirements.txt` (already pins
  backend + worker + mcp deps). Reused by 3 services via different commands.
  Heavy (~torch + sentence-transformers, multi-GB) — build once, layer-cache.
- `cortex-web` — node build → static, served by nginx (frontend).
- `cortex-docs` — node build (`docusaurus build`) → static, served by nginx.

**Services:**
| service   | image       | command                                   | port  |
|-----------|-------------|-------------------------------------------|-------|
| postgres  | pgvector/pgvector:pg16 | —                              | 5432  |
| redis     | redis:7     | —                                         | 6379  |
| ollama    | ollama/ollama | entrypoint pulls `nomic-embed-text`     | 11434 |
| backend   | cortex-py   | `uvicorn api.server:app --port 8002`      | 8002  |
| worker    | cortex-py   | `arq workers.arq_worker.WorkerSettings`   | —     |
| mcp       | cortex-py   | `MCP_TRANSPORT=streamable-http server.py` | 8001  |
| frontend  | cortex-web  | nginx                                     | 5173→80 |
| docs      | cortex-docs | nginx                                     | 3000  |

- worker as its own service → kills the double-drain bug (schema.sql:55) for free.
- mcp runs http (for remote clients) AND stays up so `docker exec` stdio works (req 5).
- ollama/postgres healthchecks gate `backend` start order.

**Requirement 5 — install MCP config into Claude (the wrinkle):**
A container CANNOT write the host's `claude_desktop_config.json`. So this is a
**host-side installer script** (`scripts/install-claude-mcp.sh`), NOT a container step:
- Detects OS → locates the config:
  - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
  - Linux: `~/.config/Claude/claude_desktop_config.json`
  - Windows: `%APPDATA%/Claude/claude_desktop_config.json`
- Backs up, then **merges** (does not clobber other servers) a `cortex` entry that
  talks to the running container over stdio via `docker exec`:
  ```json
  "cortex": {
    "command": "docker",
    "args": ["exec","-i","cortex-mcp","python","/app/mcp/server.py"],
    "env": {"MCP_TRANSPORT": "stdio", "RAG_SERVER_URL": "http://backend:8002"}
  }
  ```
  → No Python on the host, no path-hardcoding. Claude spawns a stdio MCP inside the
  already-running container. Restart Claude Desktop to load.
- Exposed as `make install-claude` / documented in INSTALL.md.

### P0 — blocks shipping

#### 1. One-command install (docker-compose)
The product *is* the easy deploy. Today it's a manual `make` dance across 6 processes.

Stack as compose services:
- `postgres` — pgvector image (`pgvector/pgvector:pg16`), named volume, healthcheck.
- `redis` — for arq queue.
- `ollama` — `ollama/ollama` image, named volume for models, entrypoint pulls
  `nomic-embed-text` on first run. GPU optional via profile.
- `backend` — FastAPI; `depends_on` pg+redis+ollama healthy; runs `init-db` on boot.
- `worker` — arq worker as its **own service** (not in lifespan).
  → Side effect: kills the documented double-drain bug (schema.sql:55) for free,
    because the worker is now a single dedicated process.
- `frontend` — built static assets served by nginx (or vite preview).
- `mcp` — optional service (streamable-http transport) for remote MCP; stdio stays local.

Deliverables:
- `docker-compose.yml` (prod) + `docker-compose.dev.yml` (override, hot-reload).
- `Dockerfile` for backend (+worker shares it), `Dockerfile` for frontend.
- `.env.example` already exists — extend with all compose vars.
- Delete the junk `Commands needed/` compose files (belong to a different Node project).

Acceptance: `cp .env.example .env && docker compose up` → healthy stack, no manual steps.

#### 2. Neutralize the license gate
Current [api/server.py:27] calls `validate_license` → `sys.exit(1)` when no key set.
With licensing deferred, an unconfigured box must boot.

Change:
- `license_enabled: bool = False` in config (default off).
- Lifespan skips `validate_license` + `periodic_license_check` unless enabled.
- Keep the license module intact (dead but ready) for post-v1.

Acceptance: stack boots with empty `LICENSE_KEY`, no exit.

### P1 — needed for a credible sale

#### 3. Install + operations docs
Self-hosted customer is their own ops team. Docs are part of the product.
One page (extend `docs/` Docusaurus or a root `INSTALL.md`):
- Prereqs (Docker, optional GPU).
- Configure `.env`.
- `docker compose up`.
- Ingest first document (curl + UI walkthrough).
- Point Claude Desktop at the MCP server (config snippet — adapt the absolute paths
  currently hardcoded in [mcp/server.py] docstring).
- Backup/restore the postgres volume.

#### 4. Smoke tests
Not full coverage — a deploy-proving round-trip.
- `health` returns ok.
- ingest a small text doc → job completes.
- search returns the ingested content (vector + fts + rerank path).
- Run in CI against the compose stack (or a pytest + testcontainers).

Acceptance: `make test` (or `pytest`) green on a fresh checkout.

### P2 — post-v1 / scale

- ivfflat tuning (`lists`) — only matters past ~100k chunks; revisit with real data.
- Licensing (re-open the deferred decision): hosted phone-home + offline grace,
  OR offline signed-key for air-gapped buyers.
- Per-deploy API key rotation guidance.
- Observability: expose search_logs / job_logs in the UI (data already captured).

---

## Out of scope (explicit)
- Multi-tenancy / SaaS hosting.
- OAuth2 / user accounts (single global API key is enough for single-tenant).
- Cloud embedding providers (privacy thesis = local Ollama only).

---

## Build order
1. Backend + worker Dockerfile → compose (pg, redis, ollama, backend, worker).
2. Neutralize license gate (small, do alongside #1 so the stack boots).
3. Frontend Dockerfile + nginx into compose.
4. MCP service into compose (optional profile).
5. Smoke tests against the running stack.
6. INSTALL.md / docs.
7. Delete `Commands needed/` cruft.

## Open questions
- Frontend served by nginx vs `vite preview` — nginx is the prod-correct answer; confirm.
- MCP: ship as a compose service (streamable-http) by default, or doc-only stdio for
  local Claude Desktop? Leaning: doc-only stdio for v1, http service behind a profile.
- GPU: default to CPU embeddings (works everywhere), GPU via opt-in compose profile?
