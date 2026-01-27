from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .config import settings
from .db import get_conn, set_search_runtime
from .embeddings import embed_texts
from .opensearch_adapter import OpenSearchAdapter
from .valkey_cache import get_json as cache_get, set_json as cache_set
from .runtime_config import get_pgvector_probes
import json
import os

# Mutable flags for Deep Research features (overrides Settings defaults at runtime)
DR_FLAGS = {
    "rerank_enable": getattr(settings, "dr_rerank_enable", True),
    "topic_lock": getattr(settings, "dr_topic_lock_default", False),
}

logger = logging.getLogger(__name__)


@dataclass
class ChunkHit:
    chunk_id: int
    document_id: int
    chunk_index: int
    content: str
    distance: Optional[float] = None
    rank: Optional[float] = None


def _vector_operator() -> str:
    metric = settings.pgvector_metric.lower()
    if metric == "cosine":
        return "<=>"
    if metric == "l2":
        return "<->"
    if metric == "ip":
        return "<#>"
    raise ValueError("Invalid PGVECTOR_METRIC")


def semantic_search(query: str, top_k: int = 10, probes: Optional[int] = None, *, user_id: Optional[int] = None, space_id: Optional[int] = None) -> List[ChunkHit]:
    # Cache key
    ck = f"sem:{user_id}:{space_id}:{top_k}:{query.strip().lower()}"
    cached = cache_get(ck)
    if cached:
        return [ChunkHit(**h) for h in cached]

    # If using pgvector but embeddings are not stored in DB, bail early
    if settings.search_backend != "opensearch" and not settings.db_store_embeddings:
        logger.warning("pgvector semantic search requested but DB_STORE_EMBEDDINGS=false; returning no results")
        return []

    q_emb = embed_texts([query])[0]

    if settings.search_backend == "opensearch":
        adapter = OpenSearchAdapter()
        hits = adapter.search_vector(query=query, vector=q_emb, top_k=top_k, user_id=user_id, space_id=space_id)
        out: List[ChunkHit] = []
        for h in hits:
            src = h.get("_source", {})
            did = int(src.get("doc_id"))
            cix = int(src.get("chunk_index"))
            cid = did * 1_000_000 + cix
            out.append(ChunkHit(
                chunk_id=cid,
                document_id=did,
                chunk_index=cix,
                content=src.get("text") or "",
                distance=float(h.get("_score") or 0.0),
            ))
        cache_set(ck, [vars(x) for x in out])
        return out

    # Fallback: Postgres pgvector
    from .pgvector_utils import to_vec_literal
    op = _vector_operator()
    with get_conn() as conn:
        with conn.cursor() as cur:
            eff_probes = (probes or get_pgvector_probes() or settings.pgvector_probes)
            set_search_runtime(cur, eff_probes)
            if user_id is not None:
                cur.execute(
                    f"""
                    SELECT c.id, c.document_id, c.chunk_index, c.content, (c.embedding {op} %s::vector) AS distance
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE c.embedding IS NOT NULL
                      AND d.user_id = %s
                      AND (%s IS NULL OR d.space_id = %s)
                    ORDER BY distance ASC
                    LIMIT %s
                    """,
                    (to_vec_literal(q_emb), int(user_id), space_id, space_id, top_k),
                )
            else:
                cur.execute(
                    f"""
                    SELECT id, document_id, chunk_index, content, (embedding {op} %s::vector) AS distance
                    FROM chunks
                    WHERE embedding IS NOT NULL
                    ORDER BY distance ASC
                    LIMIT %s
                    """,
                    (to_vec_literal(q_emb), top_k),
                )
            rows = cur.fetchall()
    out = [ChunkHit(chunk_id=r[0], document_id=r[1], chunk_index=r[2], content=r[3], distance=float(r[4])) for r in rows]
    cache_set(ck, [vars(x) for x in out])
    return out


def fulltext_search(query: str, top_k: int = 10, *, user_id: Optional[int] = None, space_id: Optional[int] = None) -> List[ChunkHit]:
    ck = f"fts:{user_id}:{space_id}:{top_k}:{query.strip().lower()}"
    cached = cache_get(ck)
    if cached:
        return [ChunkHit(**h) for h in cached]

    if settings.search_backend == "opensearch":
        adapter = OpenSearchAdapter()
        hits = adapter.search_bm25(query=query, top_k=top_k, user_id=user_id, space_id=space_id)
        out: List[ChunkHit] = []
        for h in hits:
            src = h.get("_source", {})
            did = int(src.get("doc_id"))
            cix = int(src.get("chunk_index"))
            cid = did * 1_000_000 + cix
            out.append(ChunkHit(
                chunk_id=cid,
                document_id=did,
                chunk_index=cix,
                content=src.get("text") or "",
                rank=float(h.get("_score") or 0.0),
            ))
        cache_set(ck, [vars(x) for x in out])
        return out

    # Fallback: Postgres FTS
    with get_conn() as conn:
        with conn.cursor() as cur:
            if user_id is not None:
                cur.execute(
                    f"""
                    SELECT c.id, c.document_id, c.chunk_index, c.content,
                           ts_rank_cd(c.content_tsv, plainto_tsquery(%s, %s)) AS rank
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE c.content_tsv @@ plainto_tsquery(%s, %s)
                      AND d.user_id = %s
                      AND (%s IS NULL OR d.space_id = %s)
                    ORDER BY rank DESC
                    LIMIT %s
                    """,
                    (settings.fts_config, query, settings.fts_config, query, int(user_id), space_id, space_id, top_k),
                )
            else:
                cur.execute(
                    f"""
                    SELECT id, document_id, chunk_index, content,
                           ts_rank_cd(content_tsv, plainto_tsquery(%s, %s)) AS rank
                    FROM chunks
                    WHERE content_tsv @@ plainto_tsquery(%s, %s)
                    ORDER BY rank DESC
                    LIMIT %s
                    """,
                    (settings.fts_config, query, settings.fts_config, query, top_k),
                )
            rows = cur.fetchall()
    out = [ChunkHit(chunk_id=r[0], document_id=r[1], chunk_index=r[2], content=r[3], rank=float(r[4])) for r in rows]
    cache_set(ck, [vars(x) for x in out])
    return out


def hybrid_search(query: str, top_k: int = 10, alpha: float = 0.5, *, user_id: Optional[int] = None, space_id: Optional[int] = None) -> List[ChunkHit]:
    # Note: alpha unused with RRF approach; kept for API compatibility
    sem = semantic_search(query, top_k=top_k, user_id=user_id, space_id=space_id)
    fts = fulltext_search(query, top_k=top_k, user_id=user_id, space_id=space_id)

    k = 60.0
    scores: Dict[int, float] = {}
    payload: Dict[int, ChunkHit] = {}

    for rank, hit in enumerate(sem, start=1):
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
        payload[hit.chunk_id] = hit
    for rank, hit in enumerate(fts, start=1):
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
        payload[hit.chunk_id] = payload.get(hit.chunk_id, hit)

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    out: List[ChunkHit] = [payload[cid] for cid, _ in ranked]
    return out


def rag(query: str, mode: str = "hybrid", top_k: int = 6, *, user_id: Optional[int] = None, space_id: Optional[int] = None, provider_override: Optional[str] = None) -> Tuple[str, List[ChunkHit], bool]:
    logger.info("rag: query=%r mode=%s top_k=%s provider=%s user_id=%s space_id=%s", query, mode, top_k, provider_override or settings.llm_provider, user_id, space_id)
    mode = mode.lower()
    if mode == "semantic":
        hits = semantic_search(query, top_k=top_k, user_id=user_id, space_id=space_id)
    elif mode == "fulltext":
        hits = fulltext_search(query, top_k=top_k, user_id=user_id, space_id=space_id)
    else:
        hits = hybrid_search(query, top_k=top_k, user_id=user_id, space_id=space_id)

    context = "\n\n".join(h.content for h in hits)
    logger.info("rag: context_chars=%d hits=%d", len(context), len(hits))

    # Call unified LLM
    try:
        from .llm import chat as llm_chat
        out = llm_chat(query, context, provider_override=provider_override)
    except Exception as e:
        logger.exception("LLM dispatch failed: %s", e)
        out = None

    used_llm = bool(out)
    answer = out or context
    logger.info("rag: answer_chars=%d used_llm=%s", len(answer or ''), used_llm)
    return answer, hits, used_llm