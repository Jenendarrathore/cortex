"""Small, deliberate exception set. Map to HTTP in api/server.py.

Kept intentionally flat (~4): one base + three domain errors. Resist adding
per-cause subclasses (EmbeddingTimeoutError, etc.) — the message carries detail.
"""


class RagError(Exception):
    """Base for all domain errors. status_code drives the HTTP response."""

    status_code = 500

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class DocumentNotFound(RagError):
    status_code = 404


class JobNotFound(RagError):
    status_code = 404


class IngestError(RagError):
    status_code = 400


class UpstreamError(RagError):
    status_code = 503  # upstream dependency (Ollama / DB) unavailable or failed
