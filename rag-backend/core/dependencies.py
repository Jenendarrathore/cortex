"""Shared FastAPI dependencies.

Keeps framework wiring (app.state, request internals) out of route bodies so
handlers depend on injected values — easy to override in tests.
"""
from arq import ArqRedis
from fastapi import Request


def get_arq(request: Request) -> ArqRedis:
    """The ARQ pool created in the app lifespan (api/server.py)."""
    return request.app.state.arq
