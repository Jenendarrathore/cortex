"""
Cortex RAG — MCP Server

Entry point only. Tool logic lives in mcp/tools/.
Middleware lives in mcp/middleware.py. HTTP client in mcp/client.py.

Run (stdio transport):
    /Users/jenendarsingh/Documents/cortex/.cortex_venv/bin/python \
        /Users/jenendarsingh/Documents/cortex/mcp/server.py

Claude Desktop config (~/.claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "cortex": {
          "command": "/Users/jenendarsingh/Documents/cortex/.cortex_venv/bin/python",
          "args":    ["/Users/jenendarsingh/Documents/cortex/mcp/server.py"],
          "env":     { "RAG_SERVER_URL": "http://localhost:8002" }
        }
      }
    }

IMPORTANT: run as a script (python mcp/server.py), NOT as a module (python -m mcp.server).
When run as a script, Python adds mcp/ to sys.path[0], so internal sibling
imports (tools, middleware, client) resolve without conflicting with the
installed `mcp` package.

Adding new tools:
    1. Create mcp/tools/<domain>.py with @_tool(_mcp) decorated functions
    2. Import the module below under "Tool modules"
"""

import os
import sys

# mcp/ dir → sibling imports (tools, middleware, client)
# cortex/ root → rag/ package imports
_MCP_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT    = os.path.dirname(_MCP_DIR)
sys.path.insert(0, _MCP_DIR)
sys.path.insert(0, _ROOT)

# installed mcp package — resolved from site-packages (not local mcp/ dir
# since mcp/ has no __init__.py and regular packages beat namespace packages)
from mcp.server.fastmcp import FastMCP  # type: ignore[import]

import tools as tool_registry   # mcp/tools/
import middleware                # mcp/middleware.py

# ---------------------------------------------------------------------------
# Bootstrap — wire shared instances before tool modules are imported
# ---------------------------------------------------------------------------

_mcp = FastMCP(
    "cortex",
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("MCP_PORT", "8001")),
)

tool_registry._mcp  = _mcp
tool_registry._tool = middleware.tool

# ---------------------------------------------------------------------------
# Tool modules — imported for side-effects (registers @_tool decorated fns)
# Add new tool files here; order determines registration order.
# ---------------------------------------------------------------------------

import importlib

_TOOL_MODULES = [
    "tools.retrieval",   # retrieve, list_knowledge_base
    "tools.ingestion",   # ingest_document
]

for _m in _TOOL_MODULES:
    importlib.import_module(_m)

# ---------------------------------------------------------------------------
# Entry point
#
# MCP_TRANSPORT = stdio            → local clients (Claude Desktop, Cursor)
# MCP_TRANSPORT = streamable-http  → remote/multi-client over HTTP
#
# Examples:
#   MCP_TRANSPORT=stdio             python mcp/server.py
#   MCP_TRANSPORT=streamable-http   MCP_PORT=8001 python mcp/server.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")

    if transport == "streamable-http":
        print(
            f"MCP server → streamable-http  "
            f"http://{os.getenv('MCP_HOST','0.0.0.0')}:{os.getenv('MCP_PORT','8001')}/mcp",
            flush=True,
        )
    _mcp.run(transport=transport)
