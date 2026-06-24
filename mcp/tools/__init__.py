"""
Tool registry — holds the shared FastMCP instance and middleware-wrapped decorator.

server.py sets _mcp before importing tool modules, so every tool registers
against the same FastMCP instance without circular imports.
"""

from __future__ import annotations

# Populated by server.py before tool modules are imported
_mcp = None
_tool = None  # middleware.tool decorator, bound to _mcp
