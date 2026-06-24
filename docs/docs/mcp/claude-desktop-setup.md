---
sidebar_position: 3
---

# Claude Desktop MCP Setup

Cortex RAG exposes a [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server so Claude Desktop can query your local knowledge base directly from the chat interface. Once connected, Claude gains three tools: `retrieve`, `ingest_document`, and `list_knowledge_base`.

## Prerequisites

Before touching Claude Desktop, make sure the RAG backend is up and reachable:

```bash
# From the cortex/ root
make rag
```

The backend must be running at `http://localhost:8002` (or whichever host/port you configure). You can confirm it is healthy:

```bash
curl http://localhost:8002/health
```

You should get a `{"status":"ok"}` response. If you get `connection refused`, start the backend first — Claude Desktop cannot reach the MCP server without it.

---

## Locate `claude_desktop_config.json`

The config file lives in different places depending on your OS.

| OS | Path |
|----|------|
| **macOS** | `~/.claude/claude_desktop_config.json` |
| **Windows** | `%APPDATA%\Claude\claude_desktop_config.json` (e.g. `C:\Users\USERNAME\AppData\Roaming\Claude\claude_desktop_config.json`) |

If the file does not exist yet, create it (including any missing parent directories).

---

## Add the MCP Server Config

Open `claude_desktop_config.json` and add (or merge) the following block. Replace `USERNAME` with your actual system username.

### macOS

```json
{
  "mcpServers": {
    "cortex": {
      "command": "/Users/USERNAME/Documents/cortex/.cortex_venv/bin/python",
      "args": ["/Users/USERNAME/Documents/cortex/mcp/server.py"],
      "env": {
        "RAG_SERVER_URL": "http://localhost:8002",
        "RAG_API_KEY": ""
      }
    }
  }
}
```

:::tip Find your username
Run `whoami` in a terminal to print your username, then substitute it above.
:::

`RAG_API_KEY` is optional. Set it to your API key value only if you have enabled `API_KEY` in the backend's `.env` file. Leave it as an empty string (or omit it entirely) when auth is disabled.

### Windows (WSL2)

If you are running Cortex inside WSL2, the Python binary lives in the WSL filesystem. Use the `wsl` wrapper so Claude Desktop (a native Windows process) can invoke it:

```json
{
  "mcpServers": {
    "cortex": {
      "command": "wsl",
      "args": [
        "--",
        "/home/USERNAME/Documents/cortex/.cortex_venv/bin/python",
        "/home/USERNAME/Documents/cortex/mcp/server.py"
      ],
      "env": {
        "RAG_SERVER_URL": "http://localhost:8002",
        "RAG_API_KEY": ""
      }
    }
  }
}
```

:::note
The `RAG_SERVER_URL` value `http://localhost:8002` resolves to the WSL2 loopback from inside WSL. If Claude Desktop cannot reach the backend, try the WSL2 host IP (`http://172.x.x.x:8002`) instead.
:::

---

## Restart Claude Desktop

Config changes are read at startup. After saving `claude_desktop_config.json`:

1. Quit Claude Desktop completely (macOS: `Cmd+Q`; Windows: right-click the tray icon → Quit).
2. Relaunch Claude Desktop.

---

## Verify the Connection

After restarting, open a new conversation in Claude Desktop. Look for the **tools icon** (hammer icon) in the message input bar. Clicking it should show three tools registered under `cortex`:

| Tool | What it does |
|------|-------------|
| `retrieve` | Searches your knowledge base with a natural language query |
| `ingest_document` | Adds a new markdown document to the knowledge base |
| `list_knowledge_base` | Lists all ingested documents and their metadata |

You can also verify by asking Claude directly:

> "List everything in my knowledge base."

Claude will call `list_knowledge_base` and return your ingested documents.

---

## Environment Variable Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_SERVER_URL` | `http://localhost:8002` | Base URL of the RAG backend. Change this if you run the backend on a different port or host. |
| `RAG_API_KEY` | _(empty)_ | API key sent as `X-API-Key` on all requests to the backend. Only required when `API_KEY` is set in the backend's `.env`. |

Example — backend on a non-default port with auth enabled:

```json
"env": {
  "RAG_SERVER_URL": "http://localhost:9000",
  "RAG_API_KEY": "your_secret_key_here"
}
```

---

## Troubleshooting

### Tools icon is missing / no `cortex` tools

- Confirm the JSON in `claude_desktop_config.json` is valid — a trailing comma or missing brace will silently break it. Paste the file into [jsonlint.com](https://jsonlint.com) to check.
- Make sure you fully quit and relaunched Claude Desktop (not just closed the window).
- Check that the Python path points to the virtualenv interpreter, not a system Python:
  ```bash
  ls /Users/USERNAME/Documents/cortex/.cortex_venv/bin/python
  ```
  If that path does not exist, run `make setup` from the `cortex/` root to create the virtualenv.

### `connection refused` when Claude calls a tool

The MCP server itself started, but it cannot reach the RAG backend. Check:

```bash
curl http://localhost:8002/health
```

If that fails, start the backend with `make rag` and try again. If it succeeds but Claude still gets errors, double-check the `RAG_SERVER_URL` value in the config matches the actual backend address.

### `403 Forbidden` errors

The backend has `API_KEY` set but `RAG_API_KEY` is not set in the MCP config (or is set to the wrong value). Make sure the `RAG_API_KEY` in `claude_desktop_config.json` matches the `API_KEY` in `cortex/.env`.

### `ModuleNotFoundError` or `No module named ...`

The virtualenv is missing dependencies. Re-run:

```bash
make install
```

Then restart Claude Desktop.

### MCP server crashes immediately

Run the MCP server manually to see the raw error output:

```bash
RAG_SERVER_URL=http://localhost:8002 \
  /Users/USERNAME/Documents/cortex/.cortex_venv/bin/python \
  /Users/USERNAME/Documents/cortex/mcp/server.py
```

Any import errors or configuration problems will be printed to the terminal.

### Wrong Python version

Cortex requires Python 3.11+. Confirm the virtualenv was built with the right interpreter:

```bash
/Users/USERNAME/Documents/cortex/.cortex_venv/bin/python --version
```

If it reports an older version, recreate the virtualenv with the correct Python binary (`make setup`).
