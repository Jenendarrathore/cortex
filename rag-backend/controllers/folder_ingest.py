from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from controllers.ingest import IngestController
from core.logging import get_logger
from models.document import Document

logger = get_logger(__name__)

# Async progress callback: receives one event dict per file (+ start/done).
OnEvent = Callable[[dict], Awaitable[None]]


class FolderIngestService:
    """Walk a folder of .md/.txt files and ingest each. Single implementation
    shared by the blocking /folder route and the SSE /folder-stream route — the
    only difference is whether an on_event callback is supplied."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ctrl = IngestController(db)

    @staticmethod
    def list_files(folder: Path) -> list[Path]:
        return sorted(list(folder.glob("**/*.md")) + list(folder.glob("**/*.txt")))

    async def run(self, folder_path: str, on_event: OnEvent | None = None) -> dict:
        folder = Path(folder_path)
        files = self.list_files(folder)
        stats = {"added": 0, "updated": 0, "skipped": 0, "errors": 0, "total": len(files)}

        async def emit(ev: dict) -> None:
            if on_event:
                await on_event(ev)

        await emit({"event": "start", **stats})

        for file in files:
            rel_path = str(file.relative_to(folder))
            try:
                raw = file.read_bytes()
                result_check = await self.db.execute(
                    select(Document).filter(Document.file_path == rel_path)
                )
                was_existing = result_check.scalars().first() is not None
                result = await self.ctrl.ingest_file(rel_path, raw)

                if result.status == "skipped":
                    stats["skipped"] += 1
                    status = "skipped"
                    logger.info("SKIP  %s", rel_path)
                elif was_existing:
                    stats["updated"] += 1
                    status = "updated"
                    logger.info("UPD   %s (%s chunks)", rel_path, result.chunks)
                else:
                    stats["added"] += 1
                    status = "added"
                    logger.info("ADD   %s (%s chunks)", rel_path, result.chunks)

                await emit({"event": "file", "file": rel_path, "status": status, "chunks": result.chunks, **stats})
            except Exception as e:  # noqa: BLE001 — one bad file shouldn't abort the batch
                stats["errors"] += 1
                logger.error("ERROR %s: %s", rel_path, e)
                await emit({"event": "file", "file": rel_path, "status": "error", "error": str(e), **stats})

        await emit({"event": "done", **stats})
        return stats
