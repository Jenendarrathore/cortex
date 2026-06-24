import httpx

from core.config import settings
from core.exceptions import UpstreamError
from core.logging import get_logger

logger = get_logger(__name__)

_BATCH_SIZE = 10  # max chunks per Ollama /api/embed call — avoids OOM / timeout on large docs
_EXPECTED_DIM = 768  # must match vector(768) in schema.sql

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=settings.ollama_timeout)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _embed_request(inputs: str | list[str]) -> list[list[float]]:
    """Call Ollama /api/embed. One retry, then fail fast — a down/OOM local
    Ollama won't recover by hammering it."""
    url = f"{settings.ollama_url}/api/embed"
    payload = {"model": settings.embed_model, "input": inputs}
    client = _get_client()
    last_exc: Exception | None = None

    for attempt in range(settings.embed_max_retries + 1):
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()["embeddings"]
        except Exception as e:  # noqa: BLE001 — surfaced as a clean 503 below
            last_exc = e
            if attempt < settings.embed_max_retries:
                logger.warning("Embedding attempt %s failed, retrying: %s", attempt + 1, e)

    raise UpstreamError(f"Embedding failed via Ollama ({settings.embed_model}): {last_exc}")


def _check_dim(vec: list[float]) -> None:
    if len(vec) != _EXPECTED_DIM:
        raise UpstreamError(
            f"Expected {_EXPECTED_DIM}-dim embedding from {settings.embed_model}, got {len(vec)}. "
            "Check embed_model in config matches the vector(768) in schema.sql."
        )


async def embed(text: str) -> list[float]:
    vec = (await _embed_request(text))[0]
    _check_dim(vec)
    return vec


async def embed_batch(texts: list[str]) -> list[list[float]]:
    results: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        vecs = await _embed_request(batch)
        if vecs:
            _check_dim(vecs[0])
        results.extend(vecs)
    return results
