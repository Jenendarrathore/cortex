"""Canonical string vocabularies — the single source of truth for status / kind /
level values used across the API, worker, and persistence layers.

These mirror the CHECK constraints in db/schema.sql. If you change a value here,
change it there too (and in the frontend union types in rag-frontend/src/lib/api.ts).

StrEnum members are real `str` subclasses, so they serialize to their value in
JSON/Pydantic and compare equal to the plain string — existing string comparisons
keep working while the type checker now guards against typos.
"""
from enum import StrEnum


class JobStatus(StrEnum):
    """Lifecycle of an ingestion job. CHECK: ingestion_jobs.status."""
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# Terminal states — no further transitions; pollers/streams stop here.
TERMINAL_JOB_STATUSES: frozenset[JobStatus] = frozenset({JobStatus.DONE, JobStatus.FAILED})
# In-flight states — UI keeps polling while a job is in one of these.
ACTIVE_JOB_STATUSES: frozenset[JobStatus] = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})


class JobKind(StrEnum):
    """What an ingestion job ingests. CHECK: ingestion_jobs.kind."""
    FILE = "file"
    FOLDER = "folder"
    TEXT = "text"


class LogLevel(StrEnum):
    """Job log severity. CHECK: job_logs.level."""
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class IngestStatus(StrEnum):
    """Outcome of ingesting a single document (IngestResponse.status)."""
    OK = "ok"
    SKIPPED = "skipped"


class FileStatus(StrEnum):
    """Per-file outcome emitted during a folder ingest (progress events)."""
    ADDED = "added"
    UPDATED = "updated"
    SKIPPED = "skipped"
    ERROR = "error"
