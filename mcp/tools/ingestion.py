"""Ingestion tools — add documents to the knowledge base via MCP."""

import client          # mcp/client.py
import tools           # mcp/tools/__init__.py

_mcp  = tools._mcp
_tool = tools._tool


@_tool(_mcp)
def ingest_document(
    content: str,
    file_path: str,
    title: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    author: str | None = None,
    date: str | None = None,
    source_url: str | None = None,
) -> str:
    """
    Add or update a markdown document in the knowledge base.

    Args:
        content:    Markdown text to ingest (may include YAML frontmatter).
        file_path:  Unique identifier for this document e.g. "guides/setup.md".
        title:      Human-readable title.
        category:   Category for pre-filtering e.g. "engineering".
        tags:       List of tags e.g. ["python", "setup"].
        author:     Author name.
        date:       Publication date (YYYY-MM-DD).
        source_url: Original URL or source reference.

    Returns status with document_id and number of chunks created.
    """
    result = client.post("/documents/text", {
        "content":    content,
        "file_path":  file_path,
        "title":      title,
        "category":   category,
        "tags":       tags or [],
        "author":     author,
        "date":       date,
        "source_url": source_url,
    })

    if result.get("status") == "skipped":
        return f"Document unchanged, skipped: {file_path}"

    return (
        f"Ingested: {file_path}\n"
        f"document_id: {result.get('document_id')}\n"
        f"chunks: {result.get('chunks')}"
    )
