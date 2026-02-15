from __future__ import annotations

from search_app_entrypoint import get_app  # noqa: F401  # ensure settings load
from search_app_entrypoint import patch_path  # type: ignore


patch_path()

from app.agentic_research import WebHit, decide_web_and_contexts  # type: ignore  # noqa: E402
from app.search import ChunkHit  # type: ignore  # noqa: E402


def _chunk(*, distance: float | None = None, document_id: int = 1, chunk_index: int = 0) -> ChunkHit:
    return ChunkHit(
        chunk_id=document_id * 1000 + chunk_index,
        document_id=document_id,
        chunk_index=chunk_index,
        content="chunk",
        distance=distance,
    )


def test_decide_web_skips_when_budget_low(monkeypatch):
    calls = {"fetch": 0}

    from app import agentic_research as ar

    def fake_fetch(self, query):
        calls["fetch"] += 1
        return []

    monkeypatch.setattr(ar.SmartResearchAgent, "_fetch_duckduckgo", fake_fetch)
    monkeypatch.setattr(ar.SmartResearchAgent, "time_remaining", lambda self: 1)

    contexts, hits, confidence, attempted = decide_web_and_contexts(
        "question",
        local_hits=[],
        local_contexts=["ctx"],
        max_seconds=0.1,
    )

    assert contexts
    assert hits == []
    assert isinstance(confidence, float)
    assert attempted is False
    # Ensure we never reached remote fetch when time budget was too low
    assert calls["fetch"] == 0


def test_decide_web_reports_attempt(monkeypatch):
    from app import agentic_research as ar

    hits = [WebHit(title="T", url="U", snippet="S")]

    def fake_fetch(self, query):
        return hits

    monkeypatch.setattr(ar.SmartResearchAgent, "_fetch_duckduckgo", fake_fetch)
    monkeypatch.setattr(ar.SmartResearchAgent, "should_consider_web", lambda self, local_hits: True)

    contexts, web_hits, confidence, attempted = decide_web_and_contexts(
        "query",
        local_hits=[_chunk(distance=0.9)],
        local_contexts=["ctx"],
        max_seconds=30,
    )

    assert attempted is True
    assert web_hits == hits
    assert any("Web result" in ctx for ctx in contexts)
    assert 0.1 <= confidence <= 1.0


def test_decide_web_confidence_improves_with_hits():
    _, _, low_conf, _ = decide_web_and_contexts(
        "q",
        local_hits=[],
        local_contexts=["ctx"],
        max_seconds=30,
    )

    _, _, high_conf, _ = decide_web_and_contexts(
        "q",
        local_hits=[_chunk(distance=0.05, document_id=i, chunk_index=i) for i in range(6)],
        local_contexts=["ctx"],
        max_seconds=30,
    )

    assert high_conf >= low_conf