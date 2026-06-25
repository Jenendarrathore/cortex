#!/usr/bin/env bash
# Add the Cortex MCP server to Claude Code CLI (HTTP transport).
#
# Uses the `claude mcp` command. The HTTP server must be running:
#   make mcp-http   (default port 8001)
#
# Usage:
#   scripts/mcp-connect-claude-cli.sh
#   MCP_NAME=cortex MCP_URL=http://localhost:9000/mcp MCP_SCOPE=project scripts/mcp-connect-claude-cli.sh

set -euo pipefail

MCP_NAME="${MCP_NAME:-cortex}"
MCP_URL="${MCP_URL:-http://localhost:8001/mcp}"
MCP_SCOPE="${MCP_SCOPE:-local}"   # local | project | user

command -v claude >/dev/null 2>&1 || { echo "error: claude CLI not found"; exit 1; }

# Idempotent: remove existing entry (ignore failure), then add fresh
claude mcp remove "$MCP_NAME" >/dev/null 2>&1 || true
claude mcp add --transport http --scope "$MCP_SCOPE" "$MCP_NAME" "$MCP_URL"

echo "added '$MCP_NAME' ($MCP_SCOPE) -> $MCP_URL"
claude mcp list 2>&1 | grep "$MCP_NAME" || true
