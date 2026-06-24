import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from controllers.jobs import JobController
from core.database import get_db
from schemas.job import JobDetail, JobLogResponse, JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/", response_model=list[JobResponse])
async def list_jobs(skip: int = 0, limit: int = 50, db: AsyncSession = Depends(get_db)):
    return await JobController(db).list(skip=skip, limit=limit)


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await JobController(db).get(job_id)


@router.get("/{job_id}/logs", response_model=list[JobLogResponse])
async def get_job_logs(job_id: uuid.UUID, skip: int = 0, limit: int = 500, db: AsyncSession = Depends(get_db)):
    return await JobController(db).get_logs(job_id, skip=skip, limit=limit)


@router.get("/{job_id}/stream")
async def stream_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """SSE stream of job progress. Polls until the job is done or failed."""
    ctrl = JobController(db)
    await ctrl.ensure_exists(job_id)  # surface 404 before the stream starts

    async def sse():
        async for event in ctrl.stream_events(job_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")
