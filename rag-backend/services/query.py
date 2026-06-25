import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from core.embedder import embed
from core.reranker import rerank_async
from core.config import settings
from core.logging import get_logger
from core.text_utils import strip_markdown
from schemas.document import SearchRequest

logger = get_logger(__name__)


async def record_search_log(
    query: str,
    filters: dict | None,
    result_count: int,
    latency_ms: int,
    top_chunk_ids: list[str],
    reranked: bool,
    session_id: str | None = None,
    user_query: str | None = None,
) -> None:
    """Persist search telemetry. Runs post-response in a BackgroundTask, on its
    own session. A failure here must never affect the caller — but it is logged,
    not silently swallowed."""
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                text("""
                    INSERT INTO search_logs (session_id, query, user_query, filters, result_count, latency_ms, top_chunk_ids, reranked)
                    VALUES (CAST(:session_id AS uuid), :query, :user_query, CAST(:filters AS jsonb), :result_count, :latency_ms,
                            CAST(:chunk_ids AS uuid[]), :reranked)
                """),
                {
                    "session_id": session_id,
                    "query": query,
                    "user_query": user_query,
                    "filters": json.dumps(filters) if filters else "null",
                    "result_count": result_count,
                    "latency_ms": latency_ms,
                    "chunk_ids": "{" + ",".join(top_chunk_ids) + "}" if top_chunk_ids else "{}",
                    "reranked": reranked,
                },
            )
            await db.commit()
        except Exception as e:
            logger.warning("search telemetry write failed: %s", e)


class QueryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _build_filter(self, filters: dict | None) -> tuple[str, dict]:
        """Returns (WHERE clause string, named params dict)."""
        if not filters:
            return "", {}

        clauses = []
        params = {}

        if filters.get("tags"):
            clauses.append("d.tags && :tags")
            params["tags"] = filters["tags"]
        if filters.get("category"):
            clauses.append("d.category = :category")
            params["category"] = filters["category"]
        if filters.get("date_from"):
            clauses.append("d.doc_date >= :date_from")
            params["date_from"] = filters["date_from"]
        if filters.get("date_to"):
            clauses.append("d.doc_date <= :date_to")
            params["date_to"] = filters["date_to"]

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where_sql, params

    async def _vector_search(self, embedding: list[float], where_sql: str, where_params: dict) -> list:
        sql = text(f"""
            SELECT c.id, c.content, c.heading, c.document_id,
                   1 - (c.embedding <=> CAST(:embedding AS vector)) AS score
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            {where_sql}
            ORDER BY c.embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """)
        params = {"embedding": str(embedding), "limit": settings.vector_search_limit}
        params.update(where_params)
        result = await self.db.execute(sql, params)
        return result.fetchall()

    async def _fts_search(self, query_text: str, where_sql: str, where_params: dict) -> list:
        fts_where = (
            where_sql + " AND c.fts @@ plainto_tsquery('english', :query_text)"
            if where_sql
            else "WHERE c.fts @@ plainto_tsquery('english', :query_text)"
        )
        sql = text(f"""
            SELECT c.id, c.content, c.heading, c.document_id,
                   ts_rank(c.fts, plainto_tsquery('english', :query_text)) AS score
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            {fts_where}
            ORDER BY score DESC
            LIMIT :limit
        """)
        params = {"query_text": query_text, "limit": settings.fts_search_limit}
        params.update(where_params)
        result = await self.db.execute(sql, params)
        return result.fetchall()

    @staticmethod
    def _reciprocal_rank_fusion(vector_rows: list, fts_rows: list, k: int = 60) -> list[str]:
        scores: dict[str, float] = {}
        for rank, row in enumerate(vector_rows):
            cid = str(row.id)
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        for rank, row in enumerate(fts_rows):
            cid = str(row.id)
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        return [cid for cid, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]

    async def _fetch_candidates(self, chunk_ids: list[str]) -> list[dict]:
        sql = text("""
            SELECT c.id, c.content, c.heading, c.document_id,
                   d.title, d.tags, d.category, d.source_url, d.file_path
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.id = ANY(CAST(:ids AS uuid[]))
        """)
        result = await self.db.execute(sql, {"ids": chunk_ids})
        rows = result.fetchall()
        candidates = [dict(r._mapping) for r in rows]

        # Preserve RRF order
        id_order = {cid: i for i, cid in enumerate(chunk_ids)}
        candidates.sort(key=lambda r: id_order.get(str(r["id"]), 999))

        for c in candidates:
            c["id"] = str(c["id"])
            c["document_id"] = str(c["document_id"])
            if c.get("tags"):
                c["tags"] = list(c["tags"])
        return candidates

    async def search(self, req: SearchRequest) -> list[dict]:
        where_sql, where_params = self._build_filter(req.filters)
        embedding = await embed(strip_markdown(req.query))

        vec_rows, fts_rows = (
            await self._vector_search(embedding, where_sql, where_params),
            await self._fts_search(req.query, where_sql, where_params),
        )

        merged_ids = self._reciprocal_rank_fusion(vec_rows, fts_rows)
        top_ids = merged_ids[:settings.rerank_top_n]
        if not top_ids:
            return []

        candidates = await self._fetch_candidates(top_ids)
        if req.rerank and candidates:
            return await rerank_async(req.query, candidates, req.top_k)
        return candidates[:req.top_k]
