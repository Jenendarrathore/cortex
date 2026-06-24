---
title: "Vector Databases Explained"
author: "Jenar"
category: "engineering"
tags: [ai, databases, embeddings, search]
date: 2025-01-15
source: https://example.com/vector-databases
---

# Vector Databases Explained

Vector databases store high-dimensional numerical representations of data called embeddings. Unlike traditional databases that match exact values, vector databases find semantically similar content using distance metrics.

## How Embeddings Work

An embedding model converts text, images, or other data into a fixed-length array of floating point numbers. Similar content produces embeddings that are geometrically close in vector space.

For example, the sentences "I love programming" and "Coding is my passion" will produce embeddings that are much closer to each other than "I love programming" and "The weather is nice today".

## Distance Metrics

The most common distance metrics used in vector search are:

- **Cosine similarity**: measures the angle between two vectors. Values range from -1 to 1, with 1 meaning identical direction.
- **Euclidean distance (L2)**: measures straight-line distance between two points in vector space.
- **Inner product**: similar to cosine but also sensitive to vector magnitude.

For normalized embeddings, cosine similarity and inner product give equivalent rankings.

## pgvector

pgvector is a PostgreSQL extension that adds vector storage and similarity search capabilities. It supports:

- Exact nearest neighbor search (brute force, always correct)
- Approximate nearest neighbor search via IVFFlat or HNSW indexes
- Multiple distance operators: `<=>` (cosine), `<->` (L2), `<#>` (inner product)

### IVFFlat vs HNSW

IVFFlat partitions vectors into clusters (lists) and searches only nearby clusters. It's faster to build but less accurate than HNSW.

HNSW builds a hierarchical graph structure and typically achieves better recall at higher query speeds, at the cost of more memory and longer build time.

For most use cases with under 1 million vectors, IVFFlat with `lists = sqrt(row_count)` is sufficient.

## Hybrid Search

Pure vector search misses exact keyword matches. A production RAG system should combine:

1. Vector similarity search for semantic understanding
2. Full-text search (BM25) for keyword precision
3. Reciprocal Rank Fusion (RRF) to merge result sets

This hybrid approach consistently outperforms either method alone on benchmarks.
