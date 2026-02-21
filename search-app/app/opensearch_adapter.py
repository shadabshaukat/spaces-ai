from __future__ import annotations

import os
import logging
from typing import Any, Dict, List, Optional

from opensearchpy import OpenSearch, helpers  # type: ignore

from .config import settings
from .runtime_config import get_os_num_candidates

logger = logging.getLogger(__name__)


class OpenSearchAdapter:
    """
    Minimal OpenSearch adapter for SpacesAI.
    - Ensures an index with knn_vector field sized to settings.embedding_dim
    - Bulk indexes chunk docs with vectors
    - Performs vector (KNN), BM25, and hybrid search
    Mapping fields:
      - doc_id (long), chunk_index (integer), text (text), file_name (keyword), source_path (keyword), file_type (keyword), user_id (long), space_id (long), created_at (date), vector (knn_vector)
    """

    def __init__(self) -> None:
        self.host: str = (os.getenv("OPENSEARCH_HOST", "http://localhost:9200") or "").rstrip("/")
        self.index: str = os.getenv("OPENSEARCH_INDEX", "spacesai_chunks")
        self.timeout: int = int(os.getenv("OPENSEARCH_TIMEOUT", "120"))
        self.max_retries: int = int(os.getenv("OPENSEARCH_MAX_RETRIES", "8"))
        self.verify_certs: bool = os.getenv("OPENSEARCH_VERIFY_CERTS", "1") != "0"
        self.user: Optional[str] = os.getenv("OPENSEARCH_USER")
        self.password: Optional[str] = os.getenv("OPENSEARCH_PASSWORD")
        self._client: Optional[OpenSearch] = None

    def client(self) -> OpenSearch:
        if self._client is None:
            kwargs: Dict[str, Any] = {
                "hosts": [self.host],
                "timeout": self.timeout,
                "max_retries": self.max_retries,
                "retry_on_timeout": True,
            }
            if self.host.startswith("https://"):
                # SSL settings
                kwargs["verify_certs"] = self.verify_certs
            if self.user and self.password:
                kwargs["http_auth"] = (self.user, self.password)
            self._client = OpenSearch(**kwargs)
        return self._client

    def ensure_index(self, force_recreate: bool = False) -> None:
        os_client = self.client()
        dim = settings.embedding_dim
        exists = os_client.indices.exists(index=self.index)
        if exists and not force_recreate:
            return
        if exists and force_recreate:
            try:
                os_client.indices.delete(index=self.index)
            except Exception as e:
                logger.warning("Failed to delete existing index %s: %s", self.index, e)
        # Build mapping for OpenSearch 2.x/3.x (lucene engine)
        mapping = {
            "settings": {
                "index": {
                    "knn": True,
                    "number_of_shards": int(os.getenv("OPENSEARCH_SHARDS", "3")),
                    "number_of_replicas": int(os.getenv("OPENSEARCH_REPLICAS", "1")),
                }
            },
            "mappings": {
                "properties": {
                    "doc_id": {"type": "long"},
                    "chunk_index": {"type": "integer"},
                    "text": {"type": "text"},
                    "file_name": {"type": "keyword"},
                    "source_path": {"type": "keyword"},
                    "file_type": {"type": "keyword"},
                    "user_id": {"type": "long"},
                    "space_id": {"type": "long"},
                    "created_at": {"type": "date"},
                    "vector": {
                        "type": "knn_vector",
                        "dimension": dim,
                        "method": {"name": "hnsw", "engine": os.getenv("OPENSEARCH_KNN_ENGINE", "lucene"), "space_type": os.getenv("OPENSEARCH_DISTANCE", "cosinesimil")},
                    },
                }
            },
        }

        try:
            os_client.indices.create(index=self.index, body=mapping)
            logger.info("Created OpenSearch index %s with dim=%s", self.index, dim)
        except Exception as e:
            if "resource_already_exists_exception" in str(e):
                logger.info("Index %s already exists", self.index)
            else:
                raise

    def ensure_image_index(self, *, force_recreate: bool = False) -> None:
        os_client = self.client()
        idx = settings.image_index_name
        dim = settings.image_embed_dim
        exists = os_client.indices.exists(index=idx)
        if exists and not force_recreate:
            return
        if exists and force_recreate:
            try:
                os_client.indices.delete(index=idx)
            except Exception as e:
                logger.warning("Failed to delete existing image index %s: %s", idx, e)
        mapping = {
            "settings": {
                "index": {
                    "knn": True,
                    "number_of_shards": settings.image_index_shards,
                    "number_of_replicas": settings.image_index_replicas,
                }
            },
            "mappings": {
                "properties": {
                    "doc_id": {"type": "long"},
                    "user_id": {"type": "long"},
                    "space_id": {"type": "long"},
                    "file_path": {"type": "keyword"},
                    "thumbnail_path": {"type": "keyword"},
                    "tags": {"type": "keyword"},
                    "caption": {"type": "text"},
                    "caption_full": {"type": "text"},
                    "ocr_text": {"type": "text"},
                    "vector": {
                        "type": "knn_vector",
                        "dimension": dim,
                        "method": {
                            "name": "hnsw",
                            "engine": os.getenv("OPENSEARCH_KNN_ENGINE", "lucene"),
                            "space_type": os.getenv("OPENSEARCH_DISTANCE", "cosinesimil"),
                        },
                    },
                }
            },
        }
        try:
            os_client.indices.create(index=idx, body=mapping)
            logger.info("Created OpenSearch image index %s with dim=%s", idx, dim)
        except Exception as e:
            if "resource_already_exists_exception" in str(e):
                logger.info("Image index %s already exists", idx)
            else:
                raise

    def index_chunks(self, *,
                     user_id: int,
                     space_id: Optional[int],
                     doc_id: int,
                     chunks: List[str],
                     vectors: List[List[float]],
                     file_name: Optional[str] = None,
                     source_path: Optional[str] = None,
                     file_type: Optional[str] = None,
                     created_at: Optional[str] = None,
                     refresh: bool = False) -> int:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors length mismatch for OpenSearch index")
        self.ensure_index()
        os_client = self.client()
        actions = []
        for i, (text, vec) in enumerate(zip(chunks, vectors)):
            doc = {
                "_op_type": "index",
                "_index": self.index,
                "_id": f"{doc_id}#{i}",
                "doc_id": doc_id,
                "chunk_index": i,
                "text": text,
                "file_name": file_name or "",
                "source_path": source_path or "",
                "file_type": file_type or "",
                "user_id": int(user_id),
                "space_id": int(space_id) if space_id is not None else None,
                "created_at": created_at,
                "vector": vec,
            }
            actions.append(doc)
        ok, errors = helpers.bulk(os_client, actions, refresh=refresh)
        if errors:
            logger.warning("OpenSearch bulk index had errors: %s", errors)
        return int(ok)

    @staticmethod
    def _normalize_vector(vec: List[float]) -> List[float]:
        """Ensure query vectors are floats (avoid stringified arrays reaching OpenSearch)."""
        out: List[float] = []
        for v in vec:
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                continue
        return out

    @staticmethod
    def _build_recency_functions() -> List[Dict[str, Any]]:
        boost = float(getattr(settings, "deep_research_recency_boost", 0.0) or 0.0)
        if boost <= 0:
            return []
        half_life_days = float(getattr(settings, "deep_research_recency_half_life_days", 30.0) or 30.0)
        scale_days = max(1.0, half_life_days)
        scale_days_int = int(round(scale_days))
        return [
            {
                "gauss": {"created_at": {"origin": "now", "scale": f"{scale_days_int}d", "decay": 0.5}},
                "weight": boost,
            }
        ]

    @staticmethod
    def _wrap_with_recency(query: Dict[str, Any]) -> Dict[str, Any]:
        functions = OpenSearchAdapter._build_recency_functions()
        if not functions:
            return query
        return {
            "function_score": {
                "query": query,
                "functions": functions,
                "boost_mode": "sum",
                "score_mode": "sum",
            }
        }

    def index_image_asset(self, *, user_id: int, space_id: Optional[int], doc_id: int, image_id: int, file_path: str, thumbnail_path: str, tags: list[str], caption: str, ocr_text: str | None, vector: Optional[List[float]], refresh: bool = False) -> None:
        self.ensure_image_index()
        if vector is None:
            logger.debug("Skipping image vector index because embedding missing (doc_id=%s image_id=%s)", doc_id, image_id)
            return
        os_client = self.client()
        doc = {
            "doc_id": doc_id,
            "image_id": image_id,
            "user_id": user_id,
            "space_id": space_id,
            "file_path": file_path,
            "thumbnail_path": thumbnail_path,
            "tags": tags,
            "caption": caption,
            "caption_full": caption,
            "ocr_text": ocr_text or "",
            "vector": vector,
        }
        os_client.index(index=settings.image_index_name, id=f"{doc_id}:{image_id}", body=doc, refresh=refresh)

    def search_images(self, *, vector: Optional[List[float]], query: Optional[str], top_k: int, user_id: Optional[int], space_id: Optional[int], tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        os_client = self.client()
        self.ensure_image_index()
        filters = self._filters(user_id, space_id)
        if tags:
            filters.append({"terms": {"tags": tags}})

        knn_part = None
        if vector is not None:
            vector = self._normalize_vector(vector)
            if not vector:
                vector = None
        if vector is not None:
            knn_part = {
                "field": "vector",
                "query_vector": vector,
                "k": int(top_k),
            }
            engine = (os.getenv("OPENSEARCH_KNN_ENGINE", "lucene") or "lucene").lower()
            if engine != "lucene":
                rc = get_os_num_candidates()
                num_cand_default = max(int(top_k) * 10, 100)
                knn_part["num_candidates"] = int(rc if rc is not None else getattr(settings, "opensearch_knn_num_candidates", num_cand_default))

        query_part: Dict[str, Any]
        if query:
            query_part = {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["caption_full^3", "caption^2", "ocr_text^2", "tags"],
                            }
                        }
                    ],
                    "filter": filters,
                }
            }
        else:
            query_part = {"bool": {"filter": filters or [], "must": [{"match_all": {}}]}}

        body: Dict[str, Any]
        if knn_part is None:
            body = {
                "size": int(top_k),
                "query": query_part,
            }
            res = os_client.search(index=settings.image_index_name, body=body)
            return res.get("hits", {}).get("hits", [])

        last_err: Optional[Exception] = None
        # Variant A: 2.x query-level knn object (vector nested under field name)
        try:
            knn_inner: Dict[str, Any] = {
                "vector": knn_part["query_vector"],
                "k": int(top_k),
            }
            if knn_part.get("num_candidates") is not None:
                knn_inner["num_candidates"] = knn_part["num_candidates"]
            knn_query = {
                "bool": {
                    "must": [{"knn": {"vector": knn_inner}}],
                    "filter": filters or [],
                }
            }
            body = {
                "size": int(top_k),
                "query": {
                    "function_score": {
                        "query": knn_query,
                        "boost_mode": "sum",
                        "score_mode": "sum",
                        "functions": [
                            {"weight": settings.image_search_vector_weight},
                            {"filter": query_part, "weight": settings.image_search_text_weight},
                        ],
                    }
                },
            }
            res = os_client.search(index=settings.image_index_name, body=body)
            return res.get("hits", {}).get("hits", [])
        except Exception as e:
            last_err = e
            logger.warning("OpenSearch image KNN (2.x nested vector) failed: %s", e)

        # OpenSearch 3.x prefers knn query clause with optional filter
        try:
            knn_query = {
                "knn": {
                    "field": "vector",
                    "query_vector": knn_part["query_vector"],
                    "k": int(top_k),
                }
            }
            if knn_part.get("num_candidates") is not None:
                knn_query["knn"]["num_candidates"] = knn_part["num_candidates"]
            if filters:
                knn_query["knn"]["filter"] = {"bool": {"filter": filters}}
            body = {
                "size": int(top_k),
                "query": {
                    "function_score": {
                        "query": knn_query,
                        "boost_mode": "sum",
                        "score_mode": "sum",
                        "functions": [
                            {"weight": settings.image_search_vector_weight},
                            {"filter": query_part, "weight": settings.image_search_text_weight},
                        ],
                    }
                },
            }
            res = os_client.search(index=settings.image_index_name, body=body)
            return res.get("hits", {}).get("hits", [])
        except Exception as e:
            last_err = e
            logger.warning("OpenSearch image KNN (3.x format) failed: %s", e)

        # Variant B: _knn_search endpoint (older clusters)
        try:
            knn_body = {
                "size": int(top_k),
                "query_vector": knn_part["query_vector"],
                "k": int(top_k),
                "filter": {"bool": {"filter": filters or []}} if filters else None,
            }
            if knn_part.get("num_candidates") is not None:
                knn_body["num_candidates"] = knn_part["num_candidates"]
            if knn_body.get("filter") is None:
                knn_body.pop("filter", None)
            res = os_client.transport.perform_request(
                "POST",
                f"/{settings.image_index_name}/_knn_search",
                body=knn_body,
            )
            hits = res.get("hits", {}).get("hits", [])
            if not query:
                return hits
            text_hits = os_client.search(index=settings.image_index_name, body={"size": int(top_k), "query": query_part}).get("hits", {}).get("hits", [])
            combined = hits + text_hits
            seen = {}
            for h in combined:
                h_id = h.get("_id") or h.get("_source", {}).get("image_id")
                if h_id not in seen:
                    seen[h_id] = h
            return list(seen.values())[: int(top_k)]
        except Exception as e:
            last_err = e
            logger.warning("OpenSearch image _knn_search failed: %s", e)

        # Variant C: final fallbacks
        engine = (os.getenv("OPENSEARCH_KNN_ENGINE", "lucene") or "lucene").lower()
        variants: List[Dict[str, Any]] = []
        body_c: Dict[str, Any] = {
            "size": int(top_k),
            "query": {
                "bool": {
                    "must": [{"knn": {"vector": {"vector": knn_part["query_vector"], "k": int(top_k)}}}],
                    "filter": filters or [],
                }
            },
        }
        if knn_part.get("num_candidates") is not None:
            body_c["query"]["bool"]["must"][0]["knn"]["vector"]["num_candidates"] = knn_part["num_candidates"]
        variants.append(body_c)
        body_a: Dict[str, Any] = {"size": int(top_k), "knn": dict(knn_part)}
        if query_part:
            body_a["query"] = query_part
        variants.append(body_a)
        body_b: Dict[str, Any] = {"size": int(top_k), "knn": [dict(knn_part)]}
        if query_part:
            body_b["query"] = query_part
        variants.append(body_b)
        if engine != "lucene":
            body_d: Dict[str, Any] = {
                "size": int(top_k),
                "query": query_part,
                "knn": knn_part,
            }
            variants.append(body_d)

        for body in variants:
            try:
                res = os_client.search(index=settings.image_index_name, body=body)
                return res.get("hits", {}).get("hits", [])
            except Exception as e:
                last_err = e
                logger.warning("OpenSearch image KNN variant failed: %s", e)
                continue
        logger.warning("OpenSearch image KNN failed for all variants (%s)", last_err)
        if last_err is not None:
            raise last_err
        return []

    def search_vector(self, *, query: str, vector: List[float], top_k: int, user_id: Optional[int], space_id: Optional[int]) -> List[Dict[str, Any]]:
        os_client = self.client()
        filters = self._filters(user_id, space_id)
        engine = (os.getenv("OPENSEARCH_KNN_ENGINE", "lucene") or "lucene").lower()
        vector = self._normalize_vector(vector)
        # Construct base KNN object
        from .config import settings as _settings
        knn_obj: Dict[str, Any] = {
            "field": "vector",
            "query_vector": vector,
            "k": int(top_k),
        }
        if engine != "lucene":
            rc = get_os_num_candidates()
            num_cand = rc if rc is not None else (_settings.opensearch_knn_num_candidates if getattr(_settings, "opensearch_knn_num_candidates", None) else max(int(top_k) * 10, 100))
            knn_obj["num_candidates"] = int(num_cand)
        # Prepare variants to handle cluster differences
        variants: List[Dict[str, Any]] = []
        # Variant A: top-level knn (Lucene style)
        body_a: Dict[str, Any] = {"size": int(top_k), "knn": dict(knn_obj)}
        if filters:
            base_query = {"bool": {"filter": filters}}
        else:
            base_query = {"match_all": {}}
        body_a["query"] = self._wrap_with_recency(base_query)
        variants.append(("top_level_knn", body_a))
        # Variant B: top-level knn as array of objects
        body_b: Dict[str, Any] = {"size": int(top_k), "knn": [dict(knn_obj)]}
        if filters:
            base_query = {"bool": {"filter": filters}}
        else:
            base_query = {"match_all": {}}
        body_b["query"] = self._wrap_with_recency(base_query)
        variants.append(("top_level_knn_array", body_b))
        # Variant C: query-level knn inside bool.must (array form)
        query_c = {
            "bool": {
                "must": [{"knn": {"field": "vector", "query_vector": vector, "k": int(top_k)}}],
                "filter": filters or []
            }
        }
        body_c: Dict[str, Any] = {
            "size": int(top_k),
            "query": self._wrap_with_recency(query_c)
        }
        variants.append(("query_level_bool_must", body_c))
        # Variant D: query-level knn (object under query)
        body_d: Dict[str, Any] = {
            "size": int(top_k),
            "query": self._wrap_with_recency({"knn": {"field": "vector", "query_vector": vector, "k": int(top_k)}})
        }
        variants.append(("query_level_knn", body_d))
        # Attempt each variant
        last_err: Optional[Exception] = None
        for tag, body in variants:
            try:
                res = os_client.search(index=self.index, body=body)
                logger.info("OpenSearch KNN variant %s succeeded", tag)
                return res.get("hits", {}).get("hits", [])
            except Exception as e:
                last_err = e
                logger.warning("OpenSearch KNN variant %s failed: %s", tag, e)
                continue
        # Fallback to BM25
        logger.warning("OpenSearch KNN search failed for all variants (%s). Falling back to BM25.", last_err)
        return self.search_bm25(query=query, top_k=top_k, user_id=user_id, space_id=space_id)

    def search_bm25(self, *, query: str, top_k: int, user_id: Optional[int], space_id: Optional[int]) -> List[Dict[str, Any]]:
        os_client = self.client()
        base_query = {
            "bool": {
                "filter": self._filters(user_id, space_id),
                "must": [{"match": {"text": query}}],
            }
        }
        body = {
            "size": top_k,
            "query": self._wrap_with_recency(base_query),
        }
        res = os_client.search(index=self.index, body=body)
        return res.get("hits", {}).get("hits", [])
    
    def delete_document(self, *, doc_id: int, user_id: Optional[int] = None) -> int:
        os_client = self.client()
        query: Dict[str, Any]
        if user_id is not None:
            query = {"bool": {"filter": [{"term": {"doc_id": int(doc_id)}}, {"term": {"user_id": int(user_id)}}]}}
        else:
            query = {"term": {"doc_id": int(doc_id)}}
        try:
            res = os_client.delete_by_query(index=self.index, body={"query": query}, refresh=True, conflicts="proceed")
            return int(res.get("deleted", 0))
        except Exception as e:
            logger.warning("OpenSearch delete_by_query failed for doc_id=%s: %s", doc_id, e)
            return 0
    
    @staticmethod
    def _filters(user_id: Optional[int], space_id: Optional[int]) -> List[Dict[str, Any]]:
        f: List[Dict[str, Any]] = []
        if user_id is not None:
            f.append({"term": {"user_id": int(user_id)}})
        if space_id is not None:
            f.append({"term": {"space_id": int(space_id)}})
        return f
