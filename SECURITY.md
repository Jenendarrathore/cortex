# Security Policy

## Reporting a vulnerability

**Do not open a public GitHub issue for security problems.**

Report privately via one of:

- GitHub **Security Advisories** — the "Report a vulnerability" button under the
  repository's **Security** tab (preferred).
- Email: **external-developers@thing7.ai** with subject `SECURITY: Cortex`.

Please include:

- A description of the issue and its impact.
- Steps to reproduce (PoC if possible).
- Affected version / commit.

We aim to acknowledge within **3 business days** and to ship a fix or mitigation
for confirmed issues as quickly as is practical. We'll credit reporters who want it.

## Scope notes

Cortex is **single-tenant, self-hosted** software. The threat model assumes the
operator controls the host. Some defaults are tuned for local use and **must** be
hardened before exposing the stack to a network:

- **`API_KEY` is optional and unset by default.** With no key, every API route is
  open. Set `API_KEY` before exposing the backend beyond localhost.
- **`CORS_ORIGINS`** defaults to the local UI. Lock it down for remote deployments.
- **Postgres / Redis / Ollama** ports are published for convenience in
  `docker-compose.yml`. Restrict or remove the published ports in production.
- **Change `PGPASSWORD`** from the example value before any non-local deploy.

## Supported versions

Pre-1.0: only the latest `main` receives security fixes.
