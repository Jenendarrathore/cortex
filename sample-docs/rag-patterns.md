---
title: "Production RAG Patterns"
author: "Jenar"
category: "ai"
tags: [ai, rag, llm, retrieval, embeddings]
date: 2025-05-20
source: https://example.com/rag-patterns
---

# Production RAG Patterns

Retrieval Augmented Generation (RAG) grounds LLM responses in retrieved documents, reducing hallucinations and enabling knowledge-base-specific answers.

## Chunking Strategy

How you split documents dramatically impacts retrieval quality.

### Heading-based chunking

For structured documents (markdown, HTML), split on semantic boundaries like headings. This preserves context and avoids cutting mid-thought.

Each chunk should:
- Start with its section heading for context
- Be between 100 and 500 tokens
- Overlap at boundaries to avoid losing context at split points

### Fixed-size chunking

Split every N tokens with an overlap. Simple to implement but ignores document structure. Works well for unstructured prose.

## Retrieval

### Embedding quality matters

The embedding model is the most critical component. A better embedding model improves every query. For free options:

- `nomic-embed-text`: excellent quality, 768 dimensions, runs via Ollama
- `mxbai-embed-large`: very high quality, 1024 dimensions
- `bge-m3`: multilingual, strong performance

### Hybrid search is mandatory

Pure vector search fails on:
- Proper nouns, codes, version numbers, abbreviations
- Queries where exact keyword match is critical

Combine vector search with BM25 full-text search and merge with Reciprocal Rank Fusion (RRF). This is now the industry standard.

## Re-ranking

After retrieval, use a cross-encoder to re-score the top-N candidates. Cross-encoders are slower but significantly more accurate than bi-encoders (embedding models).

Good free cross-encoders:
- `cross-encoder/ms-marco-MiniLM-L-6-v2`: fast, strong performance
- `BAAI/bge-reranker-base`: competitive alternative

Typical pipeline: embed → retrieve top-50 → re-rank → return top-5.

## Pre-filtering

Filter before vector search to reduce the search space and improve relevance:

```python
filters = {
    "category": "engineering",
    "tags": ["python"],
    "date_from": "2024-01-01",
}
```

Metadata filters use SQL WHERE clauses and run on indexed columns before the vector scan, making them very fast.

## Contextual Retrieval

Prepend a short context summary to each chunk before embedding. This helps the model understand where the chunk fits in the larger document.

Example:
```
This chunk is from "Production RAG Patterns", section "Re-ranking".
It describes how to use cross-encoder models to improve retrieval accuracy.

[original chunk content follows...]
```

This technique reduces retrieval failures significantly.
