import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.database import get_db
from models.job import IngestionJob, JobLog
from schemas.job import JobDetail, JobLogResponse, JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/", response_model=list[JobResponse])
async def list_jobs(skip: int = 0, limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(IngestionJob).order_by(IngestionJob.created_at.desc()).offset(skip).limit(limit)
    )
    return result.scalars().all()


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(IngestionJob)
        .options(selectinload(IngestionJob.logs))
        .filter(IngestionJob.id == job_id)
    )
    job = result.scalars().first()
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")
    return job


@router.get("/{job_id}/logs", response_model=list[JobLogResponse])
async def get_job_logs(job_id: uuid.UUID, skip: int = 0, limit: int = 500, db: AsyncSession = Depends(get_db)):
    job_result = await db.execute(select(IngestionJob).filter(IngestionJob.id == job_id))
    if not job_result.scalars().first():
        raise HTTPException(404, f"Job not found: {job_id}")
    result = await db.execute(
        select(JobLog)
        .filter(JobLog.job_id == job_id)
        .order_by(JobLog.created_at)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{job_id}/stream")
async def stream_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """SSE stream of job progress. Polls DB every second until done or failed."""
    job_check = await db.execute(select(IngestionJob).filter(IngestionJob.id == job_id))
    if not job_check.scalars().first():
        raise HTTPException(404, f"Job not found: {job_id}")

    async def _generate():
        last_log_id = None
        while True:
            row_result = await db.execute(
                text("SELECT id, kind, status, total, processed, added, updated, skipped, errors, error "
                     "FROM ingestion_jobs WHERE id = :id"),
                {"id": str(job_id)},
            )
            row = row_result.first()
            if not row:
                break

            job_dict = dict(row._mapping)
            job_dict["id"] = str(job_dict["id"])

            if last_log_id:
                log_result = await db.execute(
                    text("SELECT id, level, message, file, created_at FROM job_logs "
                         "WHERE job_id = :job_id AND created_at > "
                         "(SELECT created_at FROM job_logs WHERE id = :last_id) "
                         "ORDER BY created_at"),
                    {"job_id": str(job_id), "last_id": str(last_log_id)},
                )
            else:
                log_result = await db.execute(
                    text("SELECT id, level, message, file, created_at FROM job_logs "
                         "WHERE job_id = :job_id ORDER BY created_at"),
                    {"job_id": str(job_id)},
                )

            new_logs = []
            for lr in log_result.fetchall():
                ldict = dict(lr._mapping)
                ldict["id"] = str(ldict["id"])
                if ldict.get("created_at"):
                    ldict["created_at"] = ldict["created_at"].isoformat()
                new_logs.append(ldict)
                last_log_id = lr.id

            event = {**job_dict, "logs": new_logs}
            yield f"data: {json.dumps(event)}\n\n"

            if job_dict["status"] in ("done", "failed"):
                break

            await asyncio.sleep(1)

    return StreamingResponse(_generate(), media_type="text/event-stream")
