# Changelog

All notable changes to Cortex are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- One-command Docker deployment: `docker compose up` brings up postgres, redis,
  ollama (with auto model pull), backend, worker, MCP, admin UI, and docs.
- Dev override (`docker-compose.dev.yml`) with hot-reload for backend/worker/mcp.
- Deploy-proving smoke test (`tests/test_smoke.py`) — health → ingest → search.
- GitHub Actions CI: python + frontend lint, image build, live-stack smoke test.
- Open-source project files: AGPL-3.0 LICENSE, README, CONTRIBUTING, SECURITY,
  CODE_OF_CONDUCT, issue/PR templates, CODEOWNERS, `.editorconfig`, ruff config.

### Changed
- License gate is now **off by default** (`LICENSE_ENABLED=false`). The
  open-source build boots with no license key. License code remains intact but
  dormant for optional future use.

[Unreleased]: https://github.com/your-org/cortex/commits/main
