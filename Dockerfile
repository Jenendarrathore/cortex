# Cortex Python image (cortex-py).
# ONE image, reused by three services via different commands:
#   backend  → uvicorn api.server:app   (port 8002)
#   worker   → arq workers.arq_worker.WorkerSettings
#   mcp      → python mcp/server.py      (port 8001, streamable-http)
# Heavy (torch + sentence-transformers) — build once, layer-cache.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Deps first for layer caching — only re-runs when requirements.txt changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# App code.
COPY rag-backend/ ./rag-backend/
COPY mcp/ ./mcp/

# Default service = backend. Worker / mcp override command + working_dir in compose.
WORKDIR /app/rag-backend
EXPOSE 8002 8001

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD curl -fsS http://localhost:8002/health || exit 1

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8002"]
