from __future__ import annotations

import os
import json
import pytest
from fastapi.testclient import TestClient

# Import the FastAPI app
from search_app_entrypoint import get_app  # helper to avoid heavy imports


def _db_config_present() -> bool:
    if os.getenv("DATABASE_URL"):
        return True
    req = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    return all(os.getenv(k) for k in req)


@pytest.fixture(scope="session")
def client():
    # Build app lazily to ensure environment is already loaded
    app = get_app()
    with TestClient(app) as c:
        yield c


def test_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_providers_list(client: TestClient):
    r = client.get("/api/providers")
    # This endpoint requires no auth
    assert r.status_code == 200
    js = r.json()
    assert "supported" in js and isinstance(js["supported"], list)


def test_image_search_requires_auth(client: TestClient):
    r = client.post("/api/image-search", json={"query": "policy diagram"})
    assert r.status_code == 401


@pytest.mark.skipif(not _db_config_present(), reason="DB not configured for integration test")
def test_register_login_me_flow(client: TestClient):
    # Register
    email = "smoke_user@example.com"
    password = "P@ssw0rd!"
    r = client.post("/api/register", json={"email": email, "password": password})
    assert r.status_code in (200, 400)  # 400 if user exists; acceptable for smoke

    # Login
    r = client.post("/api/login", json={"email": email, "password": password})
    assert r.status_code == 200

    # Me
    r = client.get("/api/me")
    assert r.status_code == 200
    js = r.json()
    assert js.get("user", {}).get("email") == email


@pytest.mark.skipif(not _db_config_present(), reason="DB not configured for integration test")
def test_llm_test_default(client: TestClient):
    # Public LLM test endpoint
    r = client.post("/api/llm-test", json={"question": "Hello?", "context": "A short context."})
    assert r.status_code == 200
    js = r.json()
    assert "ok" in js


@pytest.mark.skipif(not _db_config_present(), reason="DB not configured for integration test")
def test_image_search_happy_path(client: TestClient):
    email = "image_user@example.com"
    password = "Secure123!"
    client.post("/api/register", json={"email": email, "password": password})
    client.post("/api/login", json={"email": email, "password": password})

    payload = {"query": "diagram", "top_k": 1}
    r = client.post("/api/image-search", json=payload)
    # When backend isn’t fully wired (no images ingested), expect either 200 (empty results) or 400 if query missing.
    assert r.status_code in (200, 400, 404)
    if r.status_code == 200:
        body = r.json()
        assert "results" in body
