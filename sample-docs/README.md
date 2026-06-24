# Sample documents

A few small markdown files you can ingest to try Cortex end-to-end — hybrid
search, reranking, and the MCP tools — without supplying your own corpus.

This folder is baked into the image at `/app/sample-docs`, so you can ingest the
whole thing with one call (no mount needed):

```bash
curl -X POST http://localhost:8002/documents/folder \
  -F folder_path=/app/sample-docs
```

Or ingest a single file's text via the API / Admin UI. After ingestion, try a
search like `what is hybrid retrieval?` and you should see these documents come
back ranked.

> These are illustrative content, not project documentation. The Cortex docs
> site lives in [`docs/`](../docs).
