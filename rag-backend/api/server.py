import asyncio
from contextlib import asynccontextmanager

import httpx
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import documents, search as search_routes
from api.routes import jobs as jobs_routes
from core.auth import require_api_key
from core.config import settings
from core.database import init_db
from core.embedder import close_client
from core.exceptions import RagError
from core.license import periodic_license_check, validate_license
from core.logging import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # License gate — OFF by default (settings.license_enabled). The open-source
    # build skips it entirely and boots with no key. Opt in only if you run a
    # license server. License code below stays intact but dormant.
    if settings.license_enabled:
        # Exits process if invalid or expired.
        await validate_license(settings.license_key, settings.license_server_url)
        asyncio.create_task(
            periodic_license_check(
                settings.license_key,
                settings.license_server_url,
                settings.license_check_interval_hours,
            )
        )

    # Apply DB schema idempotently.
    try:
        await init_db()
        logger.info("Schema applied (db/schema.sql)")
    except Exception as e:
        if "permission denied" in str(e).lower():
            logger.warning("Schema not applied (DB user lacks DDL rights): %s — run `make init-db` as an admin", e)
        else:
            logger.error("Schema init failed: %s", e)
            raise

    # Ollama health check — warn only, never block startup.
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_url}/api/tags")
        if resp.status_code == 200:
            logger.info("Ollama reachable at %s", settings.ollama_url)
        else:
            logger.warning("Ollama returned %s — embeddings may fail", resp.status_code)
    except Exception as e:
        logger.warning("Ollama not reachable at %s: %s — start Ollama before ingesting", settings.ollama_url, e)

    # ARQ Redis pool — used only for enqueueing jobs (worker runs separately via make rag-worker)
    arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    app.state.arq = arq_pool
    logger.info("ARQ pool connected to %s", settings.redis_url)

    yield

    await arq_pool.aclose()
    await close_client()


app = FastAPI(
    title="Cortex RAG Backend",
    version="2.0.0",
    dependencies=[Depends(require_api_key)],
    lifespan=lifespan,
)

_origins = ["*"] if settings.cors_origins.strip() == "*" else [
    o.strip() for o in settings.cors_origins.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RagError)
async def rag_error_handler(request: Request, exc: RagError):
    if exc.status_code >= 500:
        logger.error("%s: %s", type(exc).__name__, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": type(exc).__name__, "detail": exc.detail},
    )


app.include_router(documents.router)
app.include_router(search_routes.router)
app.include_router(jobs_routes.router)


@app.get("/health")
def health():
    return {"status": "ok"}
