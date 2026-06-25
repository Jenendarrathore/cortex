#!/usr/bin/env bash
# Add the Cortex MCP server to Claude Desktop as an HTTP connector.
#
# Claude Desktop has no flat-file store for UI "custom connectors" — they live
# in IndexedDB/account sync. The only scriptable path is claude_desktop_config.json,
# where an HTTP server is reached via the `mcp-remote` stdio->HTTP bridge.
#
# Desktop must be RESTARTED after running this for the change to load.
# The HTTP server must be running:  make mcp-http   (default port 8001)
#
# Usage:
#   scripts/mcp-connect-desktop.sh                   # default name=cortex url=http://localhost:8001/mcp
#   MCP_NAME=cortex MCP_URL=http://localhost:9000/mcp scripts/mcp-connect-desktop.sh

set -euo pipefail

MCP_NAME="${MCP_NAME:-cortex}"
MCP_URL="${MCP_URL:-http://localhost:8001/mcp}"
CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"

command -v npx >/dev/null 2>&1 || { echo "error: npx not found (install Node.js)"; exit 1; }

# Create config if missing
if [[ ! -f "$CONFIG" ]]; then
  echo '{"mcpServers":{}}' > "$CONFIG"
fi

# Backup
BACKUP="$CONFIG.bak.$(date +%Y%m%d%H%M%S)"
cp "$CONFIG" "$BACKUP"
echo "backup -> $BACKUP"

# Merge with python (stdlib only) — preserves all other keys
python3 - "$CONFIG" "$MCP_NAME" "$MCP_URL" <<'PY'
import json, sys
config_path, name, url = sys.argv[1], sys.argv[2], sys.argv[3]
with open(config_path) as f:
    cfg = json.load(f)
cfg.setdefault("mcpServers", {})
cfg["mcpServers"][name] = {
    "command": "npx",
    "args": ["-y", "mcp-remote", url],
}
with open(config_path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
print(f"added '{name}' -> {url}")
PY

echo "done. Restart Claude Desktop, and ensure 'make mcp-http' is running."
