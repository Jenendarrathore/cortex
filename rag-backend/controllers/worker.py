"""Ingestion job processor — called by the ARQ worker."""
import base64
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from controllers.folder_ingest import FolderIngestService
from controllers.ingest import IngestController
from core.database import AsyncSessionLocal
from core.enums import FileStatus, IngestStatus, JobKind, JobStatus, LogLevel
from core.logging import get_logger
from models.job import IngestionJob, JobLog
from schemas.document import IngestTextRequest

logger = get_logger(__name__)


async def _add_log(db, job_id: uuid.UUID, level: LogLevel, message: str, file: str | None = None) -> None:
    db.add(JobLog(job_id=job_id, level=level, message=message, file=file))
    await db.flush()


async def _update_stats(db, job: IngestionJob, **kwargs: Any) -> None:
    for k, v in kwargs.items():
        setattr(job, k, v)
    await db.execute(
        text("UPDATE ingestion_jobs SET updated_at = now() WHERE id = :id"),
        {"id": job.id},
    )
    await db.flush()


async def _process_file_job(db, job: IngestionJob) -> None:
    payload = job.payload
    filename: str = payload["filename"]
    raw: bytes = base64.b64decode(payload["content_b64"])
    await _update_stats(db, job, total=1, status=JobStatus.RUNNING)
    await db.commit()
    try:
        ctrl = IngestController(db)
        result = await ctrl.ingest_file(filename, raw)
        result_data = result.model_dump(exclude_none=True)
        if result.status == IngestStatus.SKIPPED:
            await _update_stats(db, job, processed=1, skipped=1, status=JobStatus.DONE, result=result_data)
            await _add_log(db, job.id, LogLevel.INFO, f"skipped (unchanged): {filename}", file=filename)
        else:
            await _update_stats(db, job, processed=1, added=1, status=JobStatus.DONE, result=result_data)
            await _add_log(db, job.id, LogLevel.INFO, f"ingested: {filename} ({result.chunks or 0} chunks)", file=filename)
        await db.commit()
    except Exception as e:
        await _update_stats(db, job, processed=1, errors=1, status=JobStatus.FAILED, error=str(e))
        await _add_log(db, job.id, LogLevel.ERROR, f"failed: {e}", file=filename)
        await db.commit()


async def _process_text_job(db, job: IngestionJob) -> None:
    await _update_stats(db, job, total=1, status=JobStatus.RUNNING)
    await db.commit()
    try:
        req = IngestTextRequest(**job.payload)
        ctrl = IngestController(db)
        result = await ctrl.ingest_text(req)
        result_data = result.model_dump(exclude_none=True)
        if result.status == IngestStatus.SKIPPED:
            await _update_stats(db, job, processed=1, skipped=1, status=JobStatus.DONE, result=result_data)
            await _add_log(db, job.id, LogLevel.INFO, f"skipped (unchanged): {result.file}", file=result.file)
        else:
            await _update_stats(db, job, processed=1, added=1, status=JobStatus.DONE, result=result_data)
            await _add_log(db, job.id, LogLevel.INFO, f"ingested: {result.file} ({result.chunks or 0} chunks)", file=result.file)
        await db.commit()
    except Exception as e:
        await _update_stats(db, job, processed=1, errors=1, status=JobStatus.FAILED, error=str(e))
        await _add_log(db, job.id, LogLevel.ERROR, f"failed: {e}")
        await db.commit()


async def _process_folder_job(db, job: IngestionJob) -> None:
    folder_path: str = job.payload["folder_path"]
    files = FolderIngestService.list_files(Path(folder_path))
    await _update_stats(db, job, status=JobStatus.RUNNING, total=len(files))
    await db.commit()

    svc = FolderIngestService(db)

    async def on_event(ev: dict) -> None:
        if ev["event"] == "file":
            level = LogLevel.ERROR if ev["status"] == FileStatus.ERROR else LogLevel.INFO
            if ev.get("error"):
                msg = f"error: {ev.get('file', '')} — {ev['error']}"
            else:
                msg = f"{ev['status']}: {ev.get('file', '')} ({ev.get('chunks', 0)} chunks)"
            await _add_log(db, job.id, level, msg, file=ev.get("file"))
            processed = ev["added"] + ev["updated"] + ev["skipped"] + ev["errors"]
            await _update_stats(
                db, job,
                processed=processed,
                added=ev["added"],
                updated=ev["updated"],
                skipped=ev["skipped"],
                errors=ev["errors"],
            )
            await db.commit()

    try:
        stats = await svc.run(folder_path, on_event)
        await _update_stats(db, job, status=JobStatus.DONE, result=stats)
        await _add_log(
            db, job.id, LogLevel.INFO,
            f"done: {stats['added']} added, {stats['updated']} updated, "
            f"{stats['skipped']} skipped, {stats['errors']} errors",
        )
        await db.commit()
    except Exception as e:
        await _update_stats(db, job, status=JobStatus.FAILED, error=str(e))
        await _add_log(db, job.id, LogLevel.ERROR, f"folder job failed: {e}")
        await db.commit()


async def process_job(job_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(IngestionJob).filter(IngestionJob.id == job_id)
            )
            job = result.scalars().first()
            if not job:
                logger.warning("Worker: job %s not found", job_id)
                return

            logger.info("Worker: starting %s job %s", job.kind, job_id)

            if job.kind == JobKind.FILE:
                await _process_file_job(db, job)
            elif job.kind == JobKind.TEXT:
                await _process_text_job(db, job)
            elif job.kind == JobKind.FOLDER:
                await _process_folder_job(db, job)
            else:
                await _update_stats(db, job, status=JobStatus.FAILED, error=f"unknown kind: {job.kind}")
                await db.commit()

            logger.info("Worker: finished %s job %s", job.kind, job_id)
        except Exception as e:
            logger.error("Worker: unhandled error on job %s: %s", job_id, e)
            try:
                await db.rollback()
                result = await db.execute(
                    select(IngestionJob).filter(IngestionJob.id == job_id)
                )
                job = result.scalars().first()
                if job:
                    await _update_stats(db, job, status=JobStatus.FAILED, error=str(e))
                    await db.commit()
            except Exception as recovery_err:
                logger.error("Worker: failed to mark job %s as failed: %s", job_id, recovery_err)
