from __future__ import annotations

import hashlib
import logging
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .config import settings
from .db import get_conn, set_search_runtime
from .embeddings import embed_texts
from .pgvector_utils import to_vec_literal
from .opensearch_adapter import OpenSearchAdapter
from .valkey_cache import get_json as cache_get, set_json as cache_set, get_revision
from .runtime_config import get_pgvector_probes

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
    rev = get_revision("text", user_id, space_id)
    ck = f"sem:{rev}:{user_id}:{space_id}:{top_k}:{query.strip().lower()}"
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
            score = float(h.get("_score") or 0.0)
            # OpenSearch _score is similarity; map to a distance-like metric for heuristics.
            distance = 1.0 - max(0.0, min(score, 1.0)) if score > 0 else 1.0
            out.append(ChunkHit(
                chunk_id=cid,
                document_id=did,
                chunk_index=cix,
                content=src.get("text") or "",
                distance=distance,
                rank=score,
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
    rev = get_revision("text", user_id, space_id)
    ck = f"fts:{rev}:{user_id}:{space_id}:{top_k}:{query.strip().lower()}"
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
                    """
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
                    """
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


def _rag_cache_key(query: str, *, user_id: Optional[int], space_id: Optional[int], provider: str, mode: str, top_k: int, hits: List[ChunkHit], context: str) -> str:
    hasher = hashlib.sha256()
    hasher.update(query.strip().lower().encode("utf-8"))
    hasher.update(b"|")
    chunk_fingerprint = ":".join(f"{h.document_id}-{h.chunk_index}" for h in hits)
    hasher.update(chunk_fingerprint.encode("utf-8"))
    hasher.update(b"|")
    hasher.update(context.encode("utf-8"))
    digest = hasher.hexdigest()
    return f"rag:{provider}:{mode}:{user_id}:{space_id}:{top_k}:{digest}"


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

    provider = (provider_override or settings.llm_provider or "none").lower()
    cache_key = _rag_cache_key(query, user_id=user_id, space_id=space_id, provider=provider, mode=mode, top_k=top_k, hits=hits, context=context)
    cached_ans = cache_get(cache_key)
    if cached_ans and "answer" in cached_ans:
        logger.debug("rag: cache hit for provider=%s user_id=%s space_id=%s", provider, user_id, space_id)
        return cached_ans["answer"], hits, bool(cached_ans.get("used_llm", True))

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

    if settings.llm_cache_ttl_seconds > 0:
        cache_set(
            cache_key,
            {"answer": answer, "used_llm": used_llm},
            ttl_seconds=settings.llm_cache_ttl_seconds,
        )

    return answer, hits, used_llm


def image_search(query: Optional[str], vector: Optional[List[float]], top_k: int, *, user_id: Optional[int], space_id: Optional[int], tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    rev = get_revision("image", user_id, space_id)
    key_parts = [
        "img",
        str(rev),
        str(user_id),
        str(space_id),
        str(top_k),
        (query or "").strip().lower(),
        ",".join(sorted(tags)) if tags else "",
        "vec" if vector is not None else "novec",
    ]
    ck = ":".join(key_parts)
    cached = cache_get(ck)
    if cached:
        return cached

    hits: List[Dict[str, Any]] = []
    use_opensearch = settings.search_backend == "opensearch" and bool(settings.opensearch_host)
    if settings.search_backend == "opensearch":
        adapter = OpenSearchAdapter()
        try:
            hits = adapter.search_images(vector=vector, query=query, top_k=top_k, user_id=user_id, space_id=space_id, tags=tags)
        except Exception as exc:
            logger.warning("OpenSearch image search failed (%s); falling back to Postgres", exc)
            hits = _image_search_postgres(vector=vector, query=query, top_k=top_k, user_id=user_id, space_id=space_id, tags=tags)
    else:
        hits = _image_search_postgres(vector=vector, query=query, top_k=top_k, user_id=user_id, space_id=space_id, tags=tags)

    cache_set(ck, hits)
    return hits


def _image_search_postgres(*, vector: Optional[List[float]], query: Optional[str], top_k: int, user_id: Optional[int], space_id: Optional[int], tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    if not settings.enable_image_storage:
        return []

    if vector is not None:
        vector = [float(v) for v in vector if isinstance(v, (int, float))]
        if not vector:
            vector = None

    where = []
    filter_params: List[Any] = []
    if user_id is not None:
        where.append("ia.user_id = %s")
        filter_params.append(int(user_id))
    if space_id is not None:
        where.append("ia.space_id = %s")
        filter_params.append(int(space_id))
    if tags:
        where.append("ia.tags @> %s::jsonb")
        filter_params.append(json.dumps(tags))
    if query and vector is None:
        where.append("(ia.caption ILIKE %s OR COALESCE(d.metadata->>'image_ocr_text','') ILIKE %s)")
        filter_params.extend([f"%{query}%", f"%{query}%"])
    if vector is not None:
        where.append("ia.embedding IS NOT NULL")

    order_clause = "ia.created_at DESC"
    distance_expr = "NULL::double precision AS distance"
    vector_param = None
    if vector is not None:
        distance_expr = f"(ia.embedding {_vector_operator()} %s::vector) AS distance"
        vector_param = to_vec_literal(vector)

    rank_expr = "0.0::double precision AS text_rank"
    rank_params: List[Any] = []
    if query:
        rank_expr = (
            "ts_rank_cd("
            "to_tsvector('simple', COALESCE(ia.caption,'') || ' ' || COALESCE(d.metadata->>'image_ocr_text','')),
            "
            "plainto_tsquery('simple', %s)"
            ") AS text_rank"
        )
        rank_params.append(query)

    sql = [
        "SELECT ia.id, ia.document_id, ia.file_path, ia.thumbnail_path, ia.caption, ia.tags, ia.width, ia.height, ia.created_at,",
        distance_expr + ",",
        rank_expr,
        "FROM image_assets ia",
        "JOIN documents d ON d.id = ia.document_id",
    ]
    if where:
        sql.append("WHERE " + " AND ".join(where))
    params: List[Any] = []
    if vector_param is not None:
        params.append(vector_param)
    params.extend(rank_params)
    params.extend(filter_params)

    if vector_param is not None or query:
        order_clause = "text_rank DESC"
        if vector_param is not None and query:
            order_clause = "(COALESCE(text_rank, 0) * %s + (1.0 / (1.0 + COALESCE(distance, 0))) * %s) DESC"
            params.extend([settings.image_search_text_weight, settings.image_search_vector_weight])
        elif vector_param is not None:
            order_clause = "distance ASC"
    sql.append(f"ORDER BY {order_clause} LIMIT %s")
    params.append(int(top_k))

    query_str = "\n".join(sql)
    results: List[Dict[str, Any]] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query_str, params)
            rows = cur.fetchall()
    for row in rows:
        image_id, doc_id, file_path, thumb_path, caption, tags_raw, width, height, created_at, distance, text_rank = row
        parsed_tags: List[str]
        if isinstance(tags_raw, list):
            parsed_tags = tags_raw
        else:
            try:
                parsed_tags = json.loads(tags_raw) if tags_raw else []
            except Exception:
                parsed_tags = []
        src = {
            "doc_id": doc_id,
            "image_id": image_id,
            "file_path": file_path,
            "thumbnail_path": thumb_path,
            "caption": caption,
            "tags": parsed_tags,
            "width": width,
            "height": height,
            "created_at": created_at.isoformat() if created_at else None,
        }
        entry: Dict[str, Any] = {"_source": src}
        vec_score = None
        if distance is not None:
            try:
                dist_val = float(distance)
                vec_score = 1.0 / (1.0 + max(dist_val, 0.0))
            except Exception:
                vec_score = None
        try:
            txt_score = float(text_rank or 0.0)
        except Exception:
            txt_score = 0.0
        if vec_score is None and txt_score == 0.0:
            entry["_score"] = None
        else:
            entry["_score"] = (settings.image_search_vector_weight * (vec_score or 0.0)) + (settings.image_search_text_weight * txt_score)
        results.append(entry)
    return results