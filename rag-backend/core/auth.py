from fastapi import Header, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from core.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(x_api_key: str | None = Security(_api_key_header)) -> None:
    """FastAPI dependency — enforces X-API-Key when RAG_API_KEY / api_key is configured."""
    if not settings.api_key:
        return  # auth disabled
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
