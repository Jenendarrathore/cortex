import time

import anyio
from sentence_transformers import CrossEncoder

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

_model = None


def _get_model() -> CrossEncoder:
    """Lazy singleton. Logs load time on first use (no eager warmup — a large
    model would slow startup; measure here before deciding to warm)."""
    global _model
    if _model is None:
        t0 = time.perf_counter()
        _model = CrossEncoder(settings.rerank_model)
        logger.info("Reranker loaded (%s) in %.2fs", settings.rerank_model, time.perf_counter() - t0)
    return _model


def rerank(query: str, candidates: list[dict], top_n: int) -> list[dict]:
    """candidates: list of dicts with at least 'content'. Returns top_n by score."""
    if not candidates:
        return []
    model = _get_model()
    pairs = [(query, c["content"]) for c in candidates]
    scores = model.predict(pairs)
    ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
    return [{"rerank_score": float(s), **c} for s, c in ranked[:top_n]]


async def rerank_async(query: str, candidates: list[dict], top_n: int) -> list[dict]:
    """Run the CPU-bound (torch) reranker in a worker thread so it never blocks
    the event loop."""
    return await anyio.to_thread.run_sync(rerank, query, candidates, top_n)
