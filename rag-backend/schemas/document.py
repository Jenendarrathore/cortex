from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_path: str
    file_hash: str
    title: str | None = None
    author: str | None = None
    source_url: str | None = None
    category: str | None = None
    tags: list[str] = []
    doc_date: date | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ChunkInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chunk_index: int
    heading: str | None = None
    content: str
    token_count: int | None = None


class DocumentDetail(DocumentResponse):
    raw_content: str | None = None
    chunks: list[ChunkInfo] = []


class IngestTextRequest(BaseModel):
    content: str
    file_path: str | None = None
    title: str | None = None
    author: str | None = None
    category: str | None = None
    tags: list[str] = []
    date: str | None = None
    source_url: str | None = None


class IngestResponse(BaseModel):
    status: str
    document_id: str | None = None
    file: str | None = None
    chunks: int | None = None
    title: str | None = None
    reason: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=100)
    rerank: bool = True
    filters: dict[str, Any] | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[dict[str, Any]]
