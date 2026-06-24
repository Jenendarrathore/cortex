"""ARQ worker — task definitions and WorkerSettings.

Run as a standalone process:
    make rag-worker
    # or directly:
    cd rag-backend && python -m arq workers.arq_worker.WorkerSettings
"""
import uuid

from arq.connections import ArqRedis, RedisSettings
from sqlalchemy import text

from services.worker import process_job
from core.config import settings
from core.database import AsyncSessionLocal
from core.enums import JobStatus
from core.logging import get_logger

logger = get_logger(__name__)


async def startup(ctx: dict) -> None:
    """Re-queue any jobs stuck in 'running' from a prior crash."""
    arq: ArqRedis = ctx["redis"]
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                text(
                    "UPDATE ingestion_jobs SET status=:queued, updated_at=now() "
                    "WHERE status=:running RETURNING id"
                ),
                {"queued": JobStatus.QUEUED.value, "running": JobStatus.RUNNING.value},
            )
            rows = result.fetchall()
            await db.commit()
            if rows:
                logger.info("Crash recovery: re-queuing %d orphaned job(s)", len(rows))
                for row in rows:
                    await arq.enqueue_job("ingest_job", str(row[0]))
        except Exception as e:
            logger.warning("Crash recovery failed: %s", e)


async def ingest_job(ctx: dict, job_id: str) -> dict:
    """ARQ task: process one ingestion job by DB id."""
    logger.info("ARQ: starting job %s", job_id)
    await process_job(uuid.UUID(job_id))
    logger.info("ARQ: finished job %s", job_id)
    return {"job_id": job_id}


class WorkerSettings:
    functions = [ingest_job]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 600  # 10 min hard limit per job
    keep_result = 3600  # keep ARQ result in Redis for 1h
