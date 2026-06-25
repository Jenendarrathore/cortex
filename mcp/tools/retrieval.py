"""Retrieval tools — search and browse the knowledge base."""

import client          # mcp/client.py
import tools           # mcp/tools/__init__.py

_mcp  = tools._mcp
_tool = tools._tool


@_tool(_mcp)
def retrieve(
    query: str,
    top_k: int = 5,
    tags: list[str] | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user_query: str | None = None,
) -> str:
    """
    Retrieve relevant passages from the knowledge base for a given query.

    Uses hybrid search (vector + full-text) with cross-encoder re-ranking.
    Apply filters to narrow the search space before retrieval.

    Args:
        query:      The search query — rephrase the user's question into keywords if helpful.
        top_k:      Number of passages to return (default 5, max 100).
        user_query: The user's ORIGINAL, verbatim question (pass this whenever you
                    rewrote `query`, so retrieval quality can be evaluated later).
        tags:      Only search docs tagged with ANY of these e.g. ["python", "ai"].
        category:  Only search docs in this exact category e.g. "engineering".
        date_from: Only search docs dated on or after (YYYY-MM-DD).
        date_to:   Only search docs dated on or before (YYYY-MM-DD).

    Returns formatted passages ranked by relevance.
    """
    filters: dict = {}
    if tags:      filters["tags"]      = tags
    if category:  filters["category"]  = category
    if date_from: filters["date_from"] = date_from
    if date_to:   filters["date_to"]   = date_to

    result = client.post("/search", {
        "query":      query,
        "top_k":      top_k,
        "rerank":     True,
        "filters":    filters or None,
        "session_id": client.SESSION_ID,
        "user_query": user_query,
    })

    chunks = result.get("results", [])
    if not chunks:
        return "No relevant documents found."

    lines = []
    for i, c in enumerate(chunks, 1):
        score = c.get("rerank_score")
        score_str = f"  [score: {score:.3f}]" if isinstance(score, float) else ""
        lines.append(
            f"--- [{i}] {c.get('title', 'untitled')} › "
            f"{c.get('heading') or 'intro'}{score_str} ---"
        )
        lines.append(c.get("content", "").strip())
        lines.append("")

    return "\n".join(lines)


@_tool(_mcp)
def list_knowledge_base() -> str:
    """
    List all documents currently indexed in the knowledge base.

    Returns each document's title, category, tags, and date.
    Useful for understanding what knowledge is available before querying.
    """
    rows = client.get("/documents")
    if not rows:
        return "Knowledge base is empty."

    lines = []
    for r in rows:
        title = r.get("title") or r.get("file_path", "?")
        tags  = ", ".join(r.get("tags") or []) or "—"
        lines.append(
            f"• {title}"
            f"  |  category: {r.get('category') or '—'}"
            f"  |  tags: {tags}"
            f"  |  date: {r.get('doc_date') or '—'}"
            f"  |  id: {r['id']}"
        )
    return "\n".join(lines)
