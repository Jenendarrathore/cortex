import hashlib
import re
import uuid
from pathlib import Path

import frontmatter
from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.chunker import chunk_by_headings
from core.embedder import embed_batch
from core.enums import IngestStatus
from core.exceptions import DocumentNotFound
from core.logging import get_logger
from core.text_utils import strip_markdown
from models.document import Document, Chunk
from schemas.document import IngestTextRequest, IngestResponse


def _generate_file_path(title: str | None) -> str:
    if title:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        return f"paste/{slug}-{uuid.uuid4().hex[:8]}"
    return f"paste/{uuid.uuid4().hex}"

logger = get_logger(__name__)


class IngestService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_documents(self, skip: int = 0, limit: int = 100) -> list[Document]:
        result = await self.db.execute(
            select(Document).order_by(Document.updated_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def ingest_text(self, req: IngestTextRequest) -> IngestResponse:
        file_hash = hashlib.sha256(req.content.encode()).hexdigest()
        file_path = req.file_path or _generate_file_path(req.title)

        result = await self.db.execute(
            select(Document).filter(Document.file_path == file_path)
        )
        existing = result.scalars().first()

        if existing and existing.file_hash == file_hash:
            return IngestResponse(
                status=IngestStatus.SKIPPED,
                reason="unchanged",
                file=file_path,
            )

        tags = req.tags or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]

        doc_date = req.date

        if existing:
            existing.file_hash = file_hash
            existing.title = req.title
            existing.author = req.author
            existing.source_url = req.source_url
            existing.category = req.category
            existing.tags = tags
            existing.doc_date = doc_date
            existing.raw_content = req.content
            await self.db.execute(
                text("UPDATE documents SET updated_at = now() WHERE id = :id"),
                {"id": existing.id},
            )
            doc = existing
            await self.db.execute(
                delete(Chunk).where(Chunk.document_id == doc.id)
            )
        else:
            doc = Document(
                file_path=file_path,
                file_hash=file_hash,
                title=req.title,
                author=req.author,
                source_url=req.source_url,
                category=req.category,
                tags=tags,
                doc_date=doc_date,
                raw_content=req.content,
            )
            self.db.add(doc)
            await self.db.flush()  # get doc.id

        chunks = chunk_by_headings(req.content)
        if chunks:
            # Strip markdown before embedding — stored content stays as original markdown
            texts = [strip_markdown(c["text"]) for c in chunks]
            embeddings = await embed_batch(texts)
            for c, emb in zip(chunks, embeddings):
                chunk_obj = Chunk(
                    document_id=doc.id,
                    content=c["text"],
                    embedding=emb,
                    chunk_index=c["chunk_index"],
                    heading=c.get("heading"),
                    token_count=c.get("token_count", 0),
                )
                self.db.add(chunk_obj)

        await self.db.commit()
        await self.db.refresh(doc)

        return IngestResponse(
            status=IngestStatus.OK,
            document_id=str(doc.id),
            file=req.file_path,
            chunks=len(chunks),
            title=req.title,
        )

    async def ingest_file(self, filename: str, raw_bytes: bytes) -> IngestResponse:
        """Parse file bytes and delegate to ingest_text. Supports .md (with frontmatter) and .txt."""
        suffix = Path(filename).suffix.lower()
        text_content = raw_bytes.decode("utf-8")

        if suffix == ".txt":
            req = IngestTextRequest(
                content=text_content,
                file_path=filename,
                title=Path(filename).stem.replace("-", " ").replace("_", " ").title(),
            )
        else:
            # .md — parse YAML frontmatter
            post = frontmatter.loads(text_content)
            meta = dict(post.metadata)
            req = IngestTextRequest(
                content=post.content,
                file_path=filename,
                title=meta.get("title"),
                author=meta.get("author"),
                category=meta.get("category"),
                tags=meta.get("tags") or [],
                date=meta.get("date").isoformat() if meta.get("date") and hasattr(meta.get("date"), "isoformat") else meta.get("date"),
                source_url=meta.get("source") or meta.get("url") or meta.get("source_url"),
            )
        return await self.ingest_text(req)

    async def get_document(self, doc_id: str) -> Document:
        result = await self.db.execute(
            select(Document)
            .options(selectinload(Document.chunks))
            .filter(Document.id == doc_id)
        )
        doc = result.scalars().first()
        if not doc:
            raise DocumentNotFound(f"Document not found: {doc_id}")
        return doc

    async def delete_document(self, doc_id: str) -> None:
        result = await self.db.execute(
            select(Document).filter(Document.id == doc_id)
        )
        doc = result.scalars().first()
        if not doc:
            raise DocumentNotFound(f"Document not found: {doc_id}")
        await self.db.delete(doc)
        await self.db.commit()
