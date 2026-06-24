"""Job controller — all DB access for ingestion jobs and their logs.

Keeps the HTTP routes (api/routes/jobs.py, documents.py) thin: they translate
requests/responses, this owns the queries and the SSE progress stream.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import AsyncIterator

from arq import ArqRedis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.enums import JobKind, TERMINAL_JOB_STATUSES
from core.exceptions import JobNotFound
from models.job import IngestionJob, JobLog


class JobController:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def enqueue(self, arq: ArqRedis, kind: JobKind, payload: dict) -> IngestionJob:
        job = IngestionJob(kind=kind, payload=payload)
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        await arq.enqueue_job("ingest_job", str(job.id))
        return job

    async def list(self, skip: int = 0, limit: int = 50) -> list[IngestionJob]:
        result = await self.db.execute(
            select(IngestionJob).order_by(IngestionJob.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def get(self, job_id: uuid.UUID) -> IngestionJob:
        result = await self.db.execute(
            select(IngestionJob)
            .options(selectinload(IngestionJob.logs))
            .filter(IngestionJob.id == job_id)
        )
        job = result.scalars().first()
        if not job:
            raise JobNotFound(f"Job not found: {job_id}")
        return job

    async def ensure_exists(self, job_id: uuid.UUID) -> None:
        result = await self.db.execute(select(IngestionJob.id).filter(IngestionJob.id == job_id))
        if not result.first():
            raise JobNotFound(f"Job not found: {job_id}")

    async def get_logs(self, job_id: uuid.UUID, skip: int = 0, limit: int = 500) -> list[JobLog]:
        await self.ensure_exists(job_id)
        result = await self.db.execute(
            select(JobLog)
            .filter(JobLog.job_id == job_id)
            .order_by(JobLog.created_at)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def stream_events(self, job_id: uuid.UUID) -> AsyncIterator[dict]:
        """Poll the job once a second, yielding a snapshot (job fields + any new
        logs since the last yield) until the job reaches a terminal status.

        Caller should `ensure_exists()` first so a missing job surfaces as 404
        before the streaming response starts.
        """
        last_log_id = None
        while True:
            row = (await self.db.execute(
                text("SELECT id, kind, status, total, processed, added, updated, skipped, errors, error "
                     "FROM ingestion_jobs WHERE id = :id"),
                {"id": str(job_id)},
            )).first()
            if not row:
                break

            job_dict = dict(row._mapping)
            job_dict["id"] = str(job_dict["id"])

            if last_log_id:
                log_result = await self.db.execute(
                    text("SELECT id, level, message, file, created_at FROM job_logs "
                         "WHERE job_id = :job_id AND created_at > "
                         "(SELECT created_at FROM job_logs WHERE id = :last_id) "
                         "ORDER BY created_at"),
                    {"job_id": str(job_id), "last_id": str(last_log_id)},
                )
            else:
                log_result = await self.db.execute(
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

            yield {**job_dict, "logs": new_logs}

            if job_dict["status"] in TERMINAL_JOB_STATUSES:
                break

            await asyncio.sleep(1)
