#!/usr/bin/env bash
# Add the Cortex MCP server to Codex CLI (~/.codex/config.toml).
#
# Codex reads MCP servers from [mcp_servers.<name>] in config.toml. HTTP servers
# are reached via the `mcp-remote` stdio->HTTP bridge (same as Claude Desktop).
#
# The HTTP server must be running:  make mcp-http   (default port 8001)
#
# Usage:
#   scripts/mcp-connect-codex.sh
#   MCP_NAME=cortex MCP_URL=http://localhost:9000/mcp scripts/mcp-connect-codex.sh

set -euo pipefail

MCP_NAME="${MCP_NAME:-cortex}"
MCP_URL="${MCP_URL:-http://localhost:8001/mcp}"
CONFIG="$HOME/.codex/config.toml"

command -v npx >/dev/null 2>&1 || { echo "error: npx not found (install Node.js)"; exit 1; }

mkdir -p "$(dirname "$CONFIG")"
[[ -f "$CONFIG" ]] || touch "$CONFIG"

# Idempotent: bail if section already present
if grep -q "^\[mcp_servers\.${MCP_NAME}\]" "$CONFIG"; then
  echo "[mcp_servers.${MCP_NAME}] already in $CONFIG — skipping"
  exit 0
fi

BACKUP="$CONFIG.bak.$(date +%Y%m%d%H%M%S)"
cp "$CONFIG" "$BACKUP"
echo "backup -> $BACKUP"

cat >> "$CONFIG" <<EOF

[mcp_servers.${MCP_NAME}]
command = "npx"
args = ["-y", "mcp-remote", "${MCP_URL}"]
EOF

echo "added [mcp_servers.${MCP_NAME}] -> ${MCP_URL}"
echo "done. Restart Codex, and ensure 'make mcp-http' is running."
