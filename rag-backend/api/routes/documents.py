import base64
from pathlib import Path

from arq import ArqRedis
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.dependencies import get_arq
from core.enums import JobKind
from services.ingest import IngestService
from services.jobs import JobService
from schemas.document import DocumentResponse, DocumentDetail, IngestTextRequest
from schemas.job import EnqueueResponse

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    ctrl = IngestService(db)
    return await ctrl.list_documents(skip=skip, limit=limit)


@router.post("/upload", response_model=EnqueueResponse, status_code=202, summary="Upload a .md or .txt file")
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    arq: ArqRedis = Depends(get_arq),
):
    if Path(file.filename).suffix.lower() not in (".md", ".txt"):
        raise HTTPException(400, "Only .md and .txt files accepted")
    raw = await file.read()
    job = await JobService(db).enqueue(arq, JobKind.FILE, {
        "filename": file.filename,
        "content_b64": base64.b64encode(raw).decode(),
    })
    return EnqueueResponse(job_id=job.id)


@router.post("/text", response_model=EnqueueResponse, status_code=202, summary="Ingest raw markdown text")
async def ingest_text(req: IngestTextRequest, db: AsyncSession = Depends(get_db), arq: ArqRedis = Depends(get_arq)):
    job = await JobService(db).enqueue(arq, JobKind.TEXT, req.model_dump())
    return EnqueueResponse(job_id=job.id)


@router.post("/folder", response_model=EnqueueResponse, status_code=202,
             summary="Ingest a server-side folder of .md and .txt files")
async def ingest_folder(
    folder_path: str = Form(...),
    db: AsyncSession = Depends(get_db),
    arq: ArqRedis = Depends(get_arq),
):
    if not Path(folder_path).is_dir():
        raise HTTPException(400, f"Not a directory: {folder_path}")
    job = await JobService(db).enqueue(arq, JobKind.FOLDER, {"folder_path": folder_path})
    return EnqueueResponse(job_id=job.id)


@router.get("/{document_id}", response_model=DocumentDetail, summary="Get document with content and chunks")
async def get_document(document_id: str, db: AsyncSession = Depends(get_db)):
    ctrl = IngestService(db)
    return await ctrl.get_document(document_id)


@router.delete("/{document_id}", summary="Delete a document and its chunks")
async def delete_document(document_id: str, db: AsyncSession = Depends(get_db)):
    ctrl = IngestService(db)
    await ctrl.delete_document(document_id)
    return {"status": "deleted", "document_id": document_id}
