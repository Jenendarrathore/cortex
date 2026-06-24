"""Shared HTTP client for all MCP tools.

Thin wrapper over the Cortex backend HTTP API. Translates backend failures into
concise, LLM-readable messages so tools don't leak raw stack traces — in
particular it unpacks Pydantic 422 validation errors (the backend is the single
source of truth for query/top_k bounds; see mcp/middleware.py).
"""

import os
import httpx

RAG_URL = os.getenv("RAG_SERVER_URL", "http://localhost:8002")
_API_KEY = os.getenv("RAG_API_KEY", "")


class BackendError(RuntimeError):
    """Backend call failed. The message is safe to surface to the LLM."""


def _headers() -> dict:
    if _API_KEY:
        return {"X-API-Key": _API_KEY}
    return {}


def _explain(resp: httpx.Response) -> str:
    """Turn a non-2xx response into a short, readable message."""
    try:
        detail = resp.json().get("detail")
    except Exception:
        detail = (resp.text or "").strip()[:300]

    # Pydantic 422: detail is a list of {loc, msg, ...} — flatten to "field: msg".
    if isinstance(detail, list):
        parts = []
        for err in detail:
            loc = ".".join(str(x) for x in err.get("loc", []) if x != "body")
            parts.append(f"{loc or 'input'}: {err.get('msg', 'invalid')}")
        detail = "; ".join(parts)

    return f"backend {resp.status_code}: {detail or resp.reason_phrase}"


def _request(method: str, path: str, *, timeout: float, **kw):
    try:
        resp = httpx.request(method, f"{RAG_URL}{path}", headers=_headers(), timeout=timeout, **kw)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise BackendError(_explain(e.response)) from e
    except httpx.HTTPError as e:
        raise BackendError(f"cannot reach Cortex backend at {RAG_URL}: {e}") from e
    return resp.json()


def post(path: str, body: dict) -> dict:
    return _request("POST", path, json=body, timeout=60.0)


def get(path: str) -> list | dict:
    return _request("GET", path, timeout=30.0)


def delete(path: str) -> dict:
    return _request("DELETE", path, timeout=30.0)
