"""
MCP Tool Middleware

Intercepts every tool call before it reaches the RAG server.
Add validators/hooks to the chain; they run in registration order.

Usage:
    from mcp.middleware import tool

    @tool(mcp)
    def my_tool(query: str) -> str:
        ...

Each middleware receives (tool_name: str, kwargs: dict) and either:
  - returns None  → pass through to next middleware / tool
  - raises ToolError(msg) → call is blocked, error returned to LLM
"""

import logging
from functools import wraps
from typing import Callable

logger = logging.getLogger("mcp.middleware")


class ToolError(Exception):
    """Raise inside a middleware to block the tool call and surface the message to the LLM."""


# ---------------------------------------------------------------------------
# Middleware registry
# ---------------------------------------------------------------------------

_chain: list[Callable] = []


def register(fn: Callable) -> Callable:
    """Add a middleware function to the chain. Returns fn for use as decorator."""
    _chain.append(fn)
    return fn


def _run_chain(tool_name: str, kwargs: dict) -> None:
    """Run all registered middleware. Raises ToolError to block the call."""
    for middleware in _chain:
        middleware(tool_name, kwargs)


# ---------------------------------------------------------------------------
# Built-in middleware
# ---------------------------------------------------------------------------

@register
def _log(tool_name: str, kwargs: dict) -> None:
    logger.info("tool=%s args=%s", tool_name, {k: v for k, v in kwargs.items() if k != "content"})


@register
def _validate_query(tool_name: str, kwargs: dict) -> None:
    query = kwargs.get("query", "")
    if query and len(query.strip()) < 3:
        raise ToolError("Query too short — provide at least 3 characters.")
    if query and len(query) > 2000:
        raise ToolError("Query too long — max 2000 characters.")


@register
def _validate_top_k(tool_name: str, kwargs: dict) -> None:
    top_k = kwargs.get("top_k")
    if top_k is not None and (top_k < 1 or top_k > 20):
        raise ToolError("top_k must be between 1 and 20.")


@register
def _validate_date(tool_name: str, kwargs: dict) -> None:
    import re
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for field in ("date_from", "date_to"):
        val = kwargs.get(field)
        if val and not date_re.match(val):
            raise ToolError(f"{field} must be in YYYY-MM-DD format, got: {val!r}")


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def tool(mcp_instance):
    """
    Drop-in replacement for @mcp.tool() that runs middleware before every call.

    Usage:
        @tool(mcp)
        def retrieve(query: str, top_k: int = 5) -> str:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        import inspect
        _sig = inspect.signature(fn)

        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Bind positional + keyword args to parameter names so middleware
            # always receives a flat {name: value} dict regardless of call style.
            try:
                bound = _sig.bind(*args, **kwargs)
                bound.apply_defaults()
                all_kwargs = dict(bound.arguments)
            except TypeError:
                all_kwargs = kwargs

            try:
                _run_chain(fn.__name__, all_kwargs)
            except ToolError as e:
                return f"[blocked] {e}"
            return fn(*args, **kwargs)

        return mcp_instance.tool()(wrapper)

    return decorator
