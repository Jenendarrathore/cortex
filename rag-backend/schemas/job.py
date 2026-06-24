from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class JobLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    level: str
    message: str
    file: str | None = None
    created_at: datetime | None = None


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    status: str
    total: int
    processed: int
    added: int
    updated: int
    skipped: int
    errors: int
    error: str | None = None
    payload: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("payload", mode="before")
    @classmethod
    def strip_binary_content(cls, v: Any) -> Any:
        if isinstance(v, dict) and "content_b64" in v:
            return {k: ("<file content — hidden>" if k == "content_b64" else val) for k, val in v.items()}
        return v or {}


class JobDetail(JobResponse):
    logs: list[JobLogResponse] = []


class EnqueueResponse(BaseModel):
    job_id: uuid.UUID
    status: str = "queued"
