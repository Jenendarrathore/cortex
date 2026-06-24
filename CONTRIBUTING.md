# Contributing to Cortex

Thanks for helping build Cortex — a self-hosted, privacy-first RAG knowledge base.
This guide gets you from clone to green tests.

## Ground rules

- Be respectful — see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- By contributing you agree your work is licensed under the project's
  [AGPL-3.0](LICENSE).
- Found a security issue? **Do not** open a public issue — see [SECURITY.md](SECURITY.md).

## Dev setup

Fastest path is Docker — the whole stack in one command:

```bash
cp .env.example .env          # set PGPASSWORD
make up-dev                   # hot-reload backend/worker/mcp from your tree
```

Bare-metal (no Docker) is driven by the Makefile:

```bash
make mac-setup    # or: make linux-setup  /  make windows-setup
make setup        # venv + python + frontend + docs deps
cp .env.example .env
make rag          # API        :8002
make rag-worker   # ingest worker
make rag-ui       # admin UI    :5173
```

## Project layout

| Path             | What                                                       |
|------------------|------------------------------------------------------------|
| `rag-backend/`   | FastAPI API, ingestion worker, retrieval (vector + FTS + rerank) |
| `mcp/`           | MCP server exposing retrieval/ingestion tools to Claude/Cursor |
| `rag-frontend/`  | React + Vite admin UI                                       |
| `docs/`          | Docusaurus documentation site                              |
| `tests/`         | Smoke test (deploy-proving round-trip)                      |

## Before you open a PR

```bash
make lint                     # ruff (python) — also: cd rag-frontend && npm run lint
make up && make test          # start the stack, run the smoke round-trip
```

CI runs the same checks (`.github/workflows/ci.yml`): python lint, frontend lint,
image build, and a full ingest→search smoke test against the live stack. Keep it green.

## PR checklist

- [ ] Focused change with a clear description (the *why*, not just the *what*).
- [ ] `make lint` passes.
- [ ] `make test` passes against the running stack.
- [ ] Docs updated if behavior, config, or API changed.
- [ ] No secrets, no `.env`, no large binaries committed.

## Commit style

Conventional Commits encouraged: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
Keep the subject under ~50 chars; explain *why* in the body when it isn't obvious.
