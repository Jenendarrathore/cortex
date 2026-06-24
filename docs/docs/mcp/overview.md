---
sidebar_position: 1
---

# MCP Overview

## What is MCP?

The **Model Context Protocol (MCP)** is an open standard that gives AI assistants like Claude a structured way to call external tools. Instead of Claude being limited to what it knows from training, MCP lets it reach out to running processes on your machine — querying databases, reading files, calling APIs — and use the results in its response.

Think of it as a plugin system built into Claude Desktop itself. You define a server that exposes named tools with typed inputs and outputs. Claude decides when a tool is relevant to what you asked, calls it, and incorporates the result. No browser extension, no custom UI wiring, no prompt engineering to simulate tool calls — it is a first-class part of the protocol.

---

## How Cortex MCP fits in

```
Claude Desktop
     │
     │  stdio (spawns as subprocess)
     ▼
mcp/server.py          ← MCP server (Python, stdio transport)
     │
     │  HTTP (localhost)
     ▼
rag-backend (:8000)    ← FastAPI service (all business logic)
     │
     ▼
PostgreSQL + pgvector  ← vector store + full-text search
```

Claude Desktop spawns `mcp/server.py` as a child process when it starts. The two communicate over **stdio** using the MCP protocol — Claude sends tool-call requests as JSON, the server responds with results, all over standard input/output. No network port is opened for the MCP layer itself.

`mcp/server.py` is intentionally thin. It registers the available tools (their names, descriptions, and input schemas), but contains no retrieval or ingestion logic. Every tool call is forwarded as an HTTP request to the `rag-backend` running on `localhost:8000`. The backend does the actual work: embedding, searching, reranking, and writing to PostgreSQL.

This separation means:

- The backend can be developed, tested, and called independently (e.g., from the admin UI or curl) without touching the MCP layer.
- Adding a new tool is a matter of writing a thin wrapper in `mcp/tools/` that calls an existing backend endpoint.
- If Claude Desktop or the MCP protocol changes, only `mcp/` needs to be updated — the backend stays stable.

---

## Transport: stdio

Claude Desktop uses the **stdio transport**: it launches the MCP server as a subprocess and reads/writes JSON-RPC messages over the process's stdin/stdout. This means:

- No TCP port needs to be open for MCP communication.
- The server lifetime is tied to Claude Desktop — it starts when Claude starts, exits when Claude exits.
- The `RAG_SERVER_URL` environment variable tells the MCP server where the `rag-backend` is listening (default `http://localhost:8000`). You set this in the Claude Desktop config.

---

## Why MCP instead of a plugin?

Claude Desktop does not have a browser-extension-style plugin system. MCP is the intended integration point — it is built into the application. Using MCP means:

- **No separate UI** — Claude calls your tools automatically when the question warrants it. You ask a question in the normal chat interface and Claude decides whether to query your knowledge base.
- **Tool descriptions drive behavior** — each tool has a natural-language description that Claude uses to decide when to call it. If the description is accurate, Claude routes queries correctly without any prompt engineering on your part.
- **Type-safe inputs** — tool inputs are defined as JSON Schema. Claude constructs valid arguments and the MCP server validates them before forwarding the call.
- **Works offline** — because the MCP server and backend both run locally, the integration works without an internet connection (aside from the initial model download for Ollama and the cross-encoder).

---

## Claude Desktop configuration

Add the following to `~/.claude/claude_desktop_config.json` (create the file if it does not exist):

```json
{
  "mcpServers": {
    "cortex": {
      "command": "/path/to/cortex/.cortex_venv/bin/python",
      "args": ["/path/to/cortex/mcp/server.py"],
      "env": {
        "RAG_SERVER_URL": "http://localhost:8000"
      }
    }
  }
}
```

Replace `/path/to/cortex` with the absolute path to your local clone. The `command` must point to the Python interpreter inside the project's virtual environment (`.cortex_venv`) so that the MCP SDK and other dependencies are available.

After saving the config, restart Claude Desktop. The `cortex` server will appear in the tools panel, and the three tools below will be available in every conversation.

---

## Available tools

The MCP server exposes three tools. Claude calls these automatically — you do not invoke them manually.

| Tool | Description |
|---|---|
| `retrieve` | Runs the full hybrid search pipeline (vector + FTS + RRF + reranker) and returns the most relevant chunks from your knowledge base. |
| `ingest_document` | Adds a new document to the knowledge base. Splits it into chunks, embeds them, and stores everything in PostgreSQL. |
| `list_knowledge_base` | Returns the list of all ingested documents with their metadata (title, author, category, tags, date). |

### `retrieve`

```
retrieve(
  query: str,
  top_k?: int,          # default 5
  tags?: list[str],
  category?: str,
  date_from?: str,      # ISO date, e.g. "2024-01-01"
  date_to?: str
)
```

The main query tool. Embeds `query` with `nomic-embed-text`, runs vector and full-text search in parallel, merges results with Reciprocal Rank Fusion, reranks the top candidates with `cross-encoder/ms-marco-MiniLM-L-6-v2`, and returns `top_k` ranked chunks with their parent document metadata.

Filters narrow the search to documents matching specific tags, category, or date range before the ANN scan runs, so they have no performance penalty.

### `ingest_document`

```
ingest_document(
  content: str,
  file_path: str,
  title?: str,
  category?: str,
  tags?: list[str],
  author?: str,
  date?: str,           # ISO date
  source_url?: str
)
```

Ingests a markdown document directly from Claude. `content` is the raw markdown text; `file_path` is used as the unique identifier (deduplicated by hash — re-ingesting the same content is a no-op). Metadata fields are all optional.

### `list_knowledge_base`

```
list_knowledge_base()
```

No arguments. Returns all documents currently in the knowledge base with their id, title, author, category, tags, date, and creation timestamp. Useful when you want Claude to reason about what is available before deciding how to search.

---

## MCP server internals

```
mcp/
├── server.py       # entry point; registers tools and starts the stdio listener
├── client.py       # thin HTTP client wrapping requests to rag-backend
├── middleware.py   # shared request/response handling
└── tools/
    ├── ingestion.py   # @tool: ingest_document → POST /documents/text
    └── retrieval.py   # @tool: retrieve → POST /search
                       # @tool: list_knowledge_base → GET /documents/
```

`server.py` imports the tool definitions from `tools/`, registers them with the MCP Python SDK, and enters the stdio event loop. Each tool function in `tools/` validates its arguments, calls `client.py` with the appropriate endpoint and payload, and returns the response as a string or structured object that Claude can read.

`client.py` holds the `RAG_SERVER_URL` base URL (read from the environment variable set in the Claude Desktop config) and exposes simple `get`, `post`, and `delete` helpers used by the tool implementations.

---

## Starting the MCP server manually

The MCP server is normally started by Claude Desktop. For debugging you can run it directly:

```bash
make mcp
```

Which is equivalent to:

```bash
RAG_SERVER_URL=http://localhost:8000 .cortex_venv/bin/python mcp/server.py
```

When run in a terminal it will block waiting for MCP JSON-RPC input on stdin. This is useful for verifying the process starts cleanly and that it can reach the backend, but normal interaction happens through Claude Desktop.

The `rag-backend` must be running (`make rag`) before any tool calls are made, since the MCP server forwards all requests to it over HTTP.

---

## Detailed tool documentation

Full parameter descriptions, example inputs and outputs, and error handling notes are in [Tools reference](./tools.md).
