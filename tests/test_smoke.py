"""Deploy-proving smoke test for Cortex.

Not unit coverage — a single round-trip against a RUNNING stack:
    health → ingest text → job completes → hybrid search returns the content.

Run against a live stack (e.g. `docker compose up -d` first):
    BASE_URL=http://localhost:8002 pytest tests/test_smoke.py -v

Env:
    BASE_URL   default http://localhost:8002
    API_KEY    sent as X-API-Key when set (must match the backend's API_KEY)
    JOB_TIMEOUT seconds to wait for ingestion (default 120)
"""
import os
import time
import uuid

import httpx
import pytest

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002").rstrip("/")
API_KEY = os.getenv("API_KEY", "")
JOB_TIMEOUT = float(os.getenv("JOB_TIMEOUT", "120"))

# Unique marker so search provably retrieves THIS document, not leftovers.
MARKER = uuid.uuid4().hex[:12]
CONTENT = (
    f"# Cortex smoke test {MARKER}\n\n"
    f"The capital of the fictional country Zembla is the city of Onhava-{MARKER}. "
    "This sentence exists only to be retrieved by the hybrid search test."
)


def _headers() -> dict:
    return {"X-API-Key": API_KEY} if API_KEY else {}


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, headers=_headers(), timeout=30.0) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "ok"


def test_ingest_then_search(client):
    # 1. enqueue ingestion of a known document
    r = client.post("/documents/text", json={"content": CONTENT, "title": f"smoke-{MARKER}"})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    # 2. wait for the worker to finish the job
    deadline = time.monotonic() + JOB_TIMEOUT
    status = None
    while time.monotonic() < deadline:
        jr = client.get(f"/jobs/{job_id}")
        assert jr.status_code == 200, jr.text
        status = jr.json()["status"]
        if status in ("done", "failed"):
            break
        time.sleep(2)
    assert status == "done", f"job ended as {status!r} (is the worker running?)"

    # 3. hybrid search must surface the unique marker (vector + FTS + rerank path)
    sr = client.post("/search", json={"query": f"capital of Zembla Onhava {MARKER}", "top_k": 5})
    assert sr.status_code == 200, sr.text
    results = sr.json()["results"]
    assert results, "search returned no results"
    joined = " ".join(str(r.get("content", "")) for r in results)
    assert MARKER in joined, "ingested marker not found in search results"
