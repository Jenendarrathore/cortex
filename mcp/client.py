"""Shared HTTP client for all MCP tools."""

import os
import httpx

RAG_URL = os.getenv("RAG_SERVER_URL", "http://localhost:8002")
_API_KEY = os.getenv("RAG_API_KEY", "")


def _headers() -> dict:
    if _API_KEY:
        return {"X-API-Key": _API_KEY}
    return {}


def post(path: str, body: dict) -> dict:
    resp = httpx.post(f"{RAG_URL}{path}", json=body, headers=_headers(), timeout=60.0)
    resp.raise_for_status()
    return resp.json()


def get(path: str) -> list | dict:
    resp = httpx.get(f"{RAG_URL}{path}", headers=_headers(), timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def delete(path: str) -> dict:
    resp = httpx.delete(f"{RAG_URL}{path}", headers=_headers(), timeout=30.0)
    resp.raise_for_status()
    return resp.json()
