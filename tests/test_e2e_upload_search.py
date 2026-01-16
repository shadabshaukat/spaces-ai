from __future__ import annotations

import io
import os
import json
import time
import pytest
from fastapi.testclient import TestClient

from search_app_entrypoint import get_app


def _env_ready() -> bool:
    # Require DB and OpenSearch to run this e2e
    if os.getenv("DATABASE_URL"):
        pass
    else:
        for k in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"):
            if not os.getenv(k):
                return False
    if not os.getenv("OPENSEARCH_HOST"):
        return False
    return True


@pytest.fixture(scope="session")
def client():
    app = get_app()
    with TestClient(app) as c:
        yield c


@pytest.mark.skipif(not _env_ready(), reason="DB/OpenSearch not configured for E2E test")
def test_e2e_upload_search_reindex(client: TestClient):
    email = "e2e_user@example.com"
    password = "P@ssw0rd!"

    # Register or ignore if exists
    r = client.post("/api/register", json={"email": email, "password": password})
    assert r.status_code in (200, 400)

    # Login
    r = client.post("/api/login", json={"email": email, "password": password})
    assert r.status_code == 200

    # Upload a small text file
    fbytes = b"Hello SpacesAI. This is a tiny test document for E2E."
    files = {"files": ("e2e.txt", io.BytesIO(fbytes), "text/plain")}
    r = client.post("/api/upload", files=files)
    assert r.status_code == 200
    js = r.json()
    assert "results" in js and len(js["results"]) >= 1
    doc_id = js["results"][0].get("document_id")
    assert doc_id is not None

    # Allow small delay for OS dual-write visibility
    time.sleep(1.5)

    # Search (semantic)
    r = client.post("/api/search", json={"query": "tiny test document", "mode": "semantic", "top_k": 5})
    assert r.status_code == 200
    js = r.json()
    assert "hits" in js

    # Reindex admin call (doc scope)
    r = client.post("/api/admin/reindex", json={"doc_id": doc_id})
    assert r.status_code == 200

    # Search again (BM25)
    r = client.post("/api/search", json={"query": "SpacesAI", "mode": "fulltext", "top_k": 5})
    assert r.status_code == 200
    js = r.json()
    assert "hits" in js
