import base64
import uuid
from pathlib import Path

from arq import ArqRedis
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from controllers.ingest import IngestController
from models.job import IngestionJob
from schemas.document import DocumentResponse, DocumentDetail, IngestTextRequest
from schemas.job import EnqueueResponse

router = APIRouter(prefix="/documents", tags=["documents"])


def _get_arq(request: Request) -> ArqRedis:
    return request.app.state.arq


async def _enqueue(db: AsyncSession, arq: ArqRedis, kind: str, payload: dict) -> IngestionJob:
    job = IngestionJob(kind=kind, payload=payload)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await arq.enqueue_job("ingest_job", str(job.id))
    return job


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    ctrl = IngestController(db)
    return await ctrl.list_documents(skip=skip, limit=limit)


@router.post("/upload", response_model=EnqueueResponse, status_code=202, summary="Upload a .md or .txt file")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if Path(file.filename).suffix.lower() not in (".md", ".txt"):
        raise HTTPException(400, "Only .md and .txt files accepted")
    raw = await file.read()
    arq = _get_arq(request)
    job = await _enqueue(db, arq, "file", {
        "filename": file.filename,
        "content_b64": base64.b64encode(raw).decode(),
    })
    return EnqueueResponse(job_id=job.id)


@router.post("/text", response_model=EnqueueResponse, status_code=202, summary="Ingest raw markdown text")
async def ingest_text(request: Request, req: IngestTextRequest, db: AsyncSession = Depends(get_db)):
    arq = _get_arq(request)
    job = await _enqueue(db, arq, "text", req.model_dump())
    return EnqueueResponse(job_id=job.id)


@router.post("/folder", response_model=EnqueueResponse, status_code=202,
             summary="Ingest a server-side folder of .md and .txt files")
async def ingest_folder(request: Request, folder_path: str = Form(...), db: AsyncSession = Depends(get_db)):
    if not Path(folder_path).is_dir():
        raise HTTPException(400, f"Not a directory: {folder_path}")
    arq = _get_arq(request)
    job = await _enqueue(db, arq, "folder", {"folder_path": folder_path})
    return EnqueueResponse(job_id=job.id)


@router.get("/{document_id}", response_model=DocumentDetail, summary="Get document with content and chunks")
async def get_document(document_id: str, db: AsyncSession = Depends(get_db)):
    ctrl = IngestController(db)
    return await ctrl.get_document(document_id)


@router.delete("/{document_id}", summary="Delete a document and its chunks")
async def delete_document(document_id: str, db: AsyncSession = Depends(get_db)):
    ctrl = IngestController(db)
    await ctrl.delete_document(document_id)
    return {"status": "deleted", "document_id": document_id}
