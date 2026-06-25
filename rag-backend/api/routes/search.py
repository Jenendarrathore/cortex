import time

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.query import QueryService, record_search_log
from schemas.document import SearchRequest, SearchResponse

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse, summary="Hybrid search with optional pre-filters")
async def search_endpoint(req: SearchRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """
    filters keys (all optional):
        tags       : list[str]  — any-match
        category   : str
        date_from  : str        — ISO date
        date_to    : str        — ISO date
    """
    ctrl = QueryService(db)
    t0 = time.perf_counter()
    results = await ctrl.search(req)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    background_tasks.add_task(
        record_search_log,
        query=req.query,
        filters=req.filters,
        result_count=len(results),
        latency_ms=latency_ms,
        top_chunk_ids=[r["id"] for r in results],
        reranked=req.rerank,
        session_id=req.session_id,
        user_query=req.user_query,
    )

    return SearchResponse(query=req.query, results=results)
