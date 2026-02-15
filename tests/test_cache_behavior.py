from __future__ import annotations

from fastapi.testclient import TestClient
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from search_app_entrypoint import get_app


def test_rag_answers_are_cached(monkeypatch):
    from app import search
    from app.search import ChunkHit

    # Stub semantic search to avoid DB/embedding dependencies
    hits = [ChunkHit(chunk_id=1, document_id=1, chunk_index=0, content="context chunk")]
    monkeypatch.setattr(search, "semantic_search", lambda *args, **kwargs: hits)

    cache_store: dict[str, dict] = {}

    def fake_cache_get(key: str):
        return cache_store.get(key)

    def fake_cache_set(key: str, value, ttl_seconds=None):
        cache_store[key] = value

    monkeypatch.setattr(search, "cache_get", fake_cache_get)
    monkeypatch.setattr(search, "cache_set", fake_cache_set)

    # Track LLM invocation count
    call_counter = {"count": 0}

    def fake_chat(question: str, context: str, provider_override=None, **_: object):
        call_counter["count"] += 1
        return f"answer-{call_counter['count']}"

    monkeypatch.setattr("app.llm.chat", fake_chat)

    ans1, _, _ = search.rag("What is SpacesAI?", mode="semantic", top_k=3, user_id=42, space_id=5, provider_override="openai")
    ans2, _, _ = search.rag("What is SpacesAI?", mode="semantic", top_k=3, user_id=42, space_id=5, provider_override="openai")

    assert ans1 == ans2 == "answer-1"
    assert call_counter["count"] == 1  # second call served from cache
    assert cache_store  # ensure something was cached


def test_health_endpoint_reports_cache_state(monkeypatch):
    from app import main as app_main

    monkeypatch.setattr(
        app_main,
        "cache_status",
        lambda: {"state": "cooldown", "expected": True, "connected": False},
    )

    client = TestClient(get_app())
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["cache"]["state"] == "cooldown"


def test_image_search_cache_invalidation(monkeypatch):
    from app import search

    cache_store: dict[str, list] = {}
    monkeypatch.setattr(search, "cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(search, "cache_set", lambda key, value: cache_store.setdefault(key, value))

    revision = {"value": 1}
    monkeypatch.setattr(search, "get_revision", lambda *_args, **_kwargs: revision["value"])

    calls = {"count": 0}

    class DummyAdapter:
        def search_images(self, **kwargs):  # type: ignore[override]
            calls["count"] += 1
            return [
                {
                    "_source": {
                        "doc_id": 9,
                        "image_id": 99,
                        "thumbnail_path": "/thumb.png",
                        "file_path": "/file.png",
                        "caption": "diagram",
                        "tags": ["policy"],
                    },
                    "_score": 1.0,
                }
            ]

    monkeypatch.setattr(search, "OpenSearchAdapter", lambda: DummyAdapter())

    args = dict(query="diagram", vector=None, top_k=5, user_id=1, space_id=2, tags=["policy"])

    res1 = search.image_search(**args)
    res2 = search.image_search(**args)
    assert res1 == res2
    assert calls["count"] == 1  # second call served from cache

    revision["value"] = 2  # simulate bump_revision after new upload/delete
    res3 = search.image_search(**args)
    assert res3 == res1
    assert calls["count"] == 2  # cache miss due to revision change