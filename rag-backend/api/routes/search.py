import time

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal, get_db
from controllers.query import QueryController
from schemas.document import SearchRequest, SearchResponse

router = APIRouter(tags=["search"])


async def _log_search(
    query: str,
    filters: dict | None,
    result_count: int,
    latency_ms: int,
    top_chunk_ids: list[str],
    reranked: bool,
) -> None:
    """Write search telemetry after the response. Runs in a BackgroundTask."""
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                text("""
                    INSERT INTO search_logs (query, filters, result_count, latency_ms, top_chunk_ids, reranked)
                    VALUES (:query, CAST(:filters AS jsonb), :result_count, :latency_ms,
                            CAST(:chunk_ids AS uuid[]), :reranked)
                """),
                {
                    "query": query,
                    "filters": __import__("json").dumps(filters) if filters else "null",
                    "result_count": result_count,
                    "latency_ms": latency_ms,
                    "chunk_ids": "{" + ",".join(top_chunk_ids) + "}" if top_chunk_ids else "{}",
                    "reranked": reranked,
                },
            )
            await db.commit()
        except Exception:
            pass  # telemetry failure must never affect the caller


@router.post("/search", response_model=SearchResponse, summary="Hybrid search with optional pre-filters")
async def search_endpoint(req: SearchRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """
    filters keys (all optional):
        tags       : list[str]  — any-match
        category   : str
        date_from  : str        — ISO date
        date_to    : str        — ISO date
    """
    ctrl = QueryController(db)
    t0 = time.perf_counter()
    results = await ctrl.search(req)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    background_tasks.add_task(
        _log_search,
        query=req.query,
        filters=req.filters,
        result_count=len(results),
        latency_ms=latency_ms,
        top_chunk_ids=[r["id"] for r in results],
        reranked=req.rerank,
    )

    return SearchResponse(query=req.query, results=results)
