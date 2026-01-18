from __future__ import annotations

import logging
import os
import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, File, UploadFile, Request, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from .auth import SessionOrBasicAuthMiddleware
from .config import settings
from .db import init_db, get_conn
from .store import ensure_dirs, ingest_file_path, save_upload, save_upload_stream
from .search import semantic_search, fulltext_search, hybrid_search, rag
from .embeddings import get_model, embed_texts
from .opensearch_adapter import OpenSearchAdapter
from .session import get_current_user, sign_session, set_session_cookie_headers, clear_session_cookie_headers
from .runtime_config import (
    get_default_top_k,
    set_default_top_k,
    get_pgvector_probes,
    set_pgvector_probes,
    get_os_num_candidates,
    set_os_num_candidates,
)
from .users import create_user, authenticate_user, list_spaces, ensure_default_space, get_default_space_id, create_space, set_default_space

logger = logging.getLogger("searchapp")
logging.basicConfig(level=os.getenv("LOGLEVEL", "INFO"))


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=f"{settings.app_name}", version="0.4.0")

# Protect API with session or basic auth; root UI is public (it will render login if unauthenticated)
app.add_middleware(SessionOrBasicAuthMiddleware, protect_paths=("/api", "/docs", "/openapi.json", "/redoc"))

if settings.allow_cors:
    origins = ["*"] if ("*" in settings.cors_origins) else list(settings.cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Static and templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
def on_startup():
    ensure_dirs()
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning("Database init skipped/failed: %s", e)
    # Preload embeddings model to avoid first-search latency
    try:
        get_model()
        logger.info("Embeddings model preloaded")
    except Exception as e:
        logger.exception("Failed to preload embeddings model: %s", e)
    # OpenSearch connectivity and index ensure (optional)
    try:
        if settings.search_backend == "opensearch" and settings.opensearch_host:
            adapter = OpenSearchAdapter()
            try:
                if adapter.client().ping():
                    logger.info("OpenSearch reachable at %s", adapter.host)
                else:
                    logger.warning("OpenSearch ping failed at %s", adapter.host)
            except Exception as e:
                logger.warning("OpenSearch connectivity failed: %s", e)
            try:
                adapter.ensure_index(force_recreate=False)
                logger.info("OpenSearch index ensured: %s", adapter.index)
            except Exception as e:
                logger.warning("OpenSearch ensure_index failed: %s", e)
    except Exception as e:
        logger.warning("OpenSearch init step failed: %s", e)
    logger.info("Startup complete: directories ensured and database initialized or deferred")


# UI route (minimalist, responsive search app)
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "app_name": settings.app_name})


# API routes
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/providers")
def list_providers():
    return {
        "default": settings.llm_provider,
        "supported": ["oci", "openai", "bedrock", "ollama"],
    }



@app.get("/api/ready")
def ready():
    if settings.search_backend == "opensearch":
        checks = {"extensions": False, "users": False, "spaces": False, "documents_table": False, "chunks_table": False, "tsv_index": False, "vec_index": False, "opensearch": False, "opensearch_index": False}
    else:
        checks = {"extensions": False, "users": False, "spaces": False, "documents_table": False, "chunks_table": False, "tsv_index": False, "vec_index": False, "opensearch": True, "opensearch_index": True}
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_extension WHERE extname IN ('vector','pgcrypto','citext')")
                checks["extensions"] = len(cur.fetchall()) >= 3
                for tbl, key in [("users","users"),("spaces","spaces"),("documents","documents_table"),("chunks","chunks_table")]:
                    cur.execute(f"SELECT to_regclass('public.{tbl}') IS NOT NULL")
                    checks[key] = bool(cur.fetchone()[0])
                cur.execute("SELECT to_regclass('public.idx_chunks_tsv') IS NOT NULL")
                checks["tsv_index"] = bool(cur.fetchone()[0])
                cur.execute("SELECT to_regclass('public.idx_chunks_embedding_ivfflat') IS NOT NULL")
                checks["vec_index"] = bool(cur.fetchone()[0])
        # OpenSearch checks (optional)
        try:
            if settings.search_backend == "opensearch" and settings.opensearch_host:
                adapter = OpenSearchAdapter()
                try:
                    checks["opensearch"] = bool(adapter.client().ping())
                except Exception:
                    checks["opensearch"] = False
                try:
                    checks["opensearch_index"] = bool(adapter.client().indices.exists(index=adapter.index))
                except Exception:
                    checks["opensearch_index"] = False
        except Exception:
            pass
        return {"ready": all(checks.values()), **checks}
    except Exception as e:
        return {"ready": False, "error": str(e), **checks}


@app.get("/api/chunks-preview")
def chunks_preview(request: Request, doc_id: int, limit: int = 20):
    # Enforce ownership
    from .session import verify_session
    tok = request.cookies.get(settings.session_cookie_name)
    user = verify_session(tok) if tok else None
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id, c.document_id, c.chunk_index, c.content_chars, LEFT(c.content, 600)
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.document_id = %s AND d.user_id = %s
                ORDER BY c.chunk_index ASC
                LIMIT %s
                """,
                (doc_id, uid, limit),
            )
            rows = cur.fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "chunk_id": int(r[0]),
            "document_id": int(r[1]),
            "chunk_index": int(r[2]),
            "content_chars": int(r[3]) if r[3] is not None else None,
            "snippet": r[4] or "",
        })
    return out


@app.get("/api/doc-summary")
def doc_summary(request: Request, doc_id: int):
    # Enforce ownership
    from .session import verify_session
    tok = request.cookies.get(settings.session_cookie_name)
    user = verify_session(tok) if tok else None
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, source_path, source_type, COALESCE(title, '') FROM documents WHERE id = %s AND user_id = %s",
                    (doc_id, uid),
                )
                doc = cur.fetchone()
                if not doc:
                    return JSONResponse(status_code=404, content={"error": "document not found"})
                cur.execute("SELECT count(*) FROM chunks WHERE document_id = %s", (doc_id,))
                cnt = int(cur.fetchone()[0])
        return {
            "document_id": int(doc[0]),
            "file_name": (doc[1] or "").rsplit("/", 1)[-1] if doc[1] else "",
            "source_path": doc[1] or "",
            "source_type": doc[2] or "",
            "title": doc[3] or "",
            "chunk_count": cnt,
        }
    except Exception as e:
        return {"error": str(e)}



@app.post("/api/upload")
async def upload(request: Request, files: List[UploadFile] = File(...), space_id: int | None = Form(None)):
    # Identify user from session
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user["user_id"]) if "user_id" in user else int(user.get("id"))
    uemail = user.get("email")
    # default space if not provided
    if space_id is None:
        sid = get_default_space_id(uid)
    else:
        sid = int(space_id)
    results: List[Dict[str, Any]] = []
    for f in files:
        # Save upload without OCI streaming to avoid auth/complexity; read bytes and save
        data = await f.read()
        local_path, oci_url = save_upload(data, Path(f.filename).name, user_email=uemail)
        title = Path(f.filename).name
        title_no_ext = Path(title).stem
        logger.info("Upload stored: backend=%s local=%s oci=%s", settings.storage_backend, local_path, "yes" if oci_url else "no")
        try:
            meta = {"filename": title}
            if oci_url:
                meta["object_url"] = oci_url
            ing = ingest_file_path(local_path, user_id=uid, space_id=sid, title=title_no_ext, metadata=meta)
            results.append({
                "filename": title,
                "title": title_no_ext,
                "document_id": ing.document_id,
                "chunks": ing.num_chunks,
                "object_url": oci_url,
                "status": "ok",
            })
            # Log activity
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO user_activity (user_id, activity_type, details) VALUES (%s, %s, %s)",
                            (uid, "upload", json.dumps({"filename": title, "document_id": ing.document_id, "chunks": ing.num_chunks, "space_id": sid})),
                        )
            except Exception:
                pass
        except Exception as e:
            results.append({
                "filename": title,
                "title": title_no_ext,
                "error": str(e),
                "status": "error",
            })
        finally:
            if settings.delete_uploaded_after_ingest:
                try:
                    os.remove(local_path)
                except Exception:
                    pass

    return {"results": results}


@app.post("/api/search")
async def api_search(request: Request, payload: Dict[str, Any]):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user["user_id"]) if "user_id" in user else int(user.get("id"))
    sid = payload.get("space_id")
    sid = int(sid) if sid is not None else get_default_space_id(uid)

    q = payload.get("query", "")
    mode = str(payload.get("mode", "hybrid")).lower()
    try:
        top_k = int(payload.get("top_k")) if payload.get("top_k") is not None else int(get_default_top_k())
    except Exception:
        top_k = int(get_default_top_k())
    provider_override = (payload.get("llm_provider") or None)
    if not q:
        return JSONResponse(status_code=400, content={"error": "query required"})

    answer: str | None = None
    used_llm: bool = False
    if mode == "semantic":
        hits = semantic_search(q, top_k=top_k, user_id=uid, space_id=sid)
    elif mode == "fulltext":
        hits = fulltext_search(q, top_k=top_k, user_id=uid, space_id=sid)
    elif mode == "rag":
        answer, hits, used_llm = rag(q, mode="hybrid", top_k=top_k, user_id=uid, space_id=sid, provider_override=provider_override)
    else:
        hits = hybrid_search(q, top_k=top_k, user_id=uid, space_id=sid)

    # Enrich with document metadata (source_path, title)
    doc_ids = sorted({h.document_id for h in hits})
    doc_info: Dict[int, Dict[str, Any]] = {}
    if doc_ids:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, source_path, source_type, COALESCE(title, ''), metadata FROM documents WHERE id = ANY(%s)", (doc_ids,)
                )
                for row in cur.fetchall():
                    # row: id, source_path, source_type, title, metadata
                    sp = row[1] or ""
                    fn = sp.rsplit("/", 1)[-1] if sp else ""
                    meta = row[4] or {}
                    object_url = None
                    if isinstance(meta, dict):
                        object_url = meta.get("object_url")
                    doc_info[int(row[0])] = {"source_path": sp, "file_name": fn, "file_type": row[2] or "", "title": row[3], "object_url": object_url}

    hits_out = []
    for h in hits:
        entry = {
            "chunk_id": h.chunk_id,
            "document_id": h.document_id,
            "chunk_index": h.chunk_index,
            "content": h.content,
            "distance": h.distance,
            "rank": h.rank,
        }
        meta = doc_info.get(h.document_id)
        if meta:
            entry["file_name"] = meta.get("file_name", "")
            entry["file_type"] = meta.get("file_type", "")
            entry["title"] = meta.get("title", "")
        hits_out.append(entry)

    out: Dict[str, Any] = {"mode": mode if mode in {"semantic", "fulltext", "rag"} else "hybrid", "hits": hits_out}
    if answer is not None:
        out["answer"] = answer
        out["used_llm"] = bool(used_llm)
        refs = []
        for e in hits_out[: min(len(hits_out), 5)]:
            refs.append({
                "file_name": e.get("file_name") or e.get("title") or "",
                "file_type": e.get("file_type") or "",
                "chunk_id": e.get("chunk_id"),
                "href": f"#chunk-{e.get('chunk_id')}",
                "url": doc_info.get(e.get("document_id", -1), {}).get("object_url") if doc_info else None,
            })
        out["references"] = refs

    # Log activity
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO user_activity (user_id, activity_type, details) VALUES (%s, %s, %s)",
                    (uid, "search", json.dumps({"query": q, "mode": mode, "top_k": top_k, "used_llm": used_llm, "space_id": sid, "hits": [h.document_id for h in hits_out[:5]]})),
                )
    except Exception:
        pass

    return out


@app.post("/api/llm-test")
async def llm_test(payload: Dict[str, Any] | None = None):
    """
    LLM connectivity test. Accepts optional { provider, question, context } and uses unified LLM.
    """
    from .llm import chat as llm_chat
    provider = (payload or {}).get("provider") if payload else None
    q = (payload or {}).get("question") if payload else None
    ctx = (payload or {}).get("context") if payload else None
    if not q:
        q = "Test connectivity. Summarize the following context in one sentence."
    if not ctx:
        ctx = "This is a test context from the /api/llm-test endpoint."
    try:
        ans = llm_chat(q, ctx, provider_override=provider)
        return {"provider": provider or settings.llm_provider, "ok": bool(ans), "answer": ans, "question": q, "context_chars": len(ctx or "")}
    except Exception as e:
        return {"provider": provider or settings.llm_provider, "ok": False, "error": str(e)}


@app.post("/api/llm-debug")
async def llm_debug(payload: Dict[str, Any] | None = None):
    """
    Diagnostic endpoint to introspect OCI GenAI response shapes.
    Returns per-path (chat, text) whether output text was extracted and the response type/fields.
    """
    q = (payload or {}).get("question") if payload else None
    ctx = (payload or {}).get("context") if payload else None
    if not q:
        q = "Test connectivity. Summarize the following context in one sentence."
    if not ctx:
        ctx = "This is a test context from the /api/llm-debug endpoint."

    provider = settings.llm_provider
    if provider != "oci":
        return {
            "provider": provider,
            "error": "llm-debug only supports provider=oci",
        }

    try:
        from .oci_llm import oci_try_chat_debug, oci_try_text_debug
        ans_chat, type_chat, fields_chat = oci_try_chat_debug(q, ctx)
        ans_text, type_text, fields_text = oci_try_text_debug(q, ctx)
        return {
            "provider": provider,
            "chat": {
                "ok": bool(ans_chat),
                "type": type_chat,
                "fields": fields_chat[:50],
            },
            "text": {
                "ok": bool(ans_text),
                "type": type_text,
                "fields": fields_text[:50],
            },
        }
    except Exception as e:
        return {"provider": provider, "error": str(e)}


@app.get("/api/llm-debug")
def llm_debug_get(q: str | None = None, ctx: str | None = None):
    """
    Diagnostic endpoint (GET) to avoid JSON body issues. Provide q and ctx as query params.
    Example: /api/llm-debug?q=Question&ctx=Context
    """
    q = q or "Test connectivity. Summarize the following context in one sentence."
    ctx = ctx or "This is a test context from the /api/llm-debug endpoint."
    provider = settings.llm_provider
    if provider != "oci":
        return {"provider": provider, "error": "llm-debug only supports provider=oci"}
    try:
        from .oci_llm import oci_try_chat_debug, oci_try_text_debug
        ans_chat, type_chat, fields_chat = oci_try_chat_debug(q, ctx)
        ans_text, type_text, fields_text = oci_try_text_debug(q, ctx)
        return {
            "provider": provider,
            "chat": {"ok": bool(ans_chat), "type": type_chat, "fields": fields_chat[:50]},
            "text": {"ok": bool(ans_text), "type": type_text, "fields": fields_text[:50]},
        }
    except Exception as e:
        return {"provider": provider, "error": str(e)}


@app.post("/api/chat")
async def api_chat(payload: Dict[str, Any]):
    """General chat entrypoint using unified LLM. Body: {question, context?, provider?}."""
    from .llm import chat as llm_chat
    q = (payload or {}).get("question") or ""
    ctx = (payload or {}).get("context") or ""
    provider = (payload or {}).get("provider") or None
    if not q:
        return JSONResponse(status_code=400, content={"error": "question required"})
    try:
        ans = llm_chat(q, ctx, provider_override=provider)
        return {"provider": provider or settings.llm_provider, "answer": ans}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/llm-config")
def llm_config():

    def _mask(ocid: str | None, keep_prefix: int = 8, keep_suffix: int = 6) -> str | None:
        if not ocid:
            return None
        if len(ocid) <= keep_prefix + keep_suffix:
            return ocid
        return ocid[:keep_prefix] + "..." + ocid[-keep_suffix:]

    return {
        "provider": settings.llm_provider,
        "oci_region": settings.oci_region,
        "oci_genai_endpoint": settings.oci_genai_endpoint,
        "compartment_id_present": bool(settings.oci_compartment_id),
        "compartment_id": _mask(settings.oci_compartment_id),
        "model_id_present": bool(settings.oci_genai_model_id),
        "model_id": _mask(settings.oci_genai_model_id, 12, 6),
        "config_file": settings.oci_config_file,
        "config_profile": settings.oci_config_profile,
    }


# Runtime search tuning (process-local; requires auth)
@app.get("/api/search-config")
async def get_search_config(request: Request):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    # Build snapshot
    return {
        "backend": settings.search_backend,
        "default_top_k": get_default_top_k(),
        "pgvector_probes": get_pgvector_probes() if get_pgvector_probes() is not None else settings.pgvector_probes,
        "opensearch": {
            "engine": os.getenv("OPENSEARCH_KNN_ENGINE", "lucene"),
            "num_candidates": get_os_num_candidates() if get_os_num_candidates() is not None else getattr(settings, "opensearch_knn_num_candidates", None),
            "distance": os.getenv("OPENSEARCH_DISTANCE", "cosinesimil"),
        },
    }


@app.post("/api/search-config")
async def set_search_config(request: Request, payload: Dict[str, Any]):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    try:
        if "default_top_k" in payload and payload["default_top_k"] is not None:
            v = int(payload["default_top_k"])
            if v < 1 or v > 1000:
                return JSONResponse(status_code=400, content={"error": "default_top_k must be between 1 and 1000"})
            set_default_top_k(v)
        if "pgvector_probes" in payload:
            pv = payload.get("pgvector_probes")
            if pv is None or pv == "":
                set_pgvector_probes(None)
            else:
                vv = int(pv)
                if vv < 1 or vv > 10000:
                    return JSONResponse(status_code=400, content={"error": "pgvector_probes must be between 1 and 10000"})
                set_pgvector_probes(vv)
        if "os_num_candidates" in payload:
            ov = payload.get("os_num_candidates")
            if ov is None or ov == "":
                set_os_num_candidates(None)
            else:
                vv = int(ov)
                if vv < 1 or vv > 1000000:
                    return JSONResponse(status_code=400, content={"error": "os_num_candidates must be between 1 and 1000000"})
                    
                set_os_num_candidates(vv)
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


# Auth & user/space endpoints
@app.post("/api/register")
async def api_register(payload: Dict[str, Any]):
    if not settings.allow_registration:
        return JSONResponse(status_code=403, content={"error": "registration disabled"})
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    if not email or not password:
        return JSONResponse(status_code=400, content={"error": "email and password required"})
    try:
        u = create_user(email, password)
        token = sign_session({"user_id": u["id"], "email": email})
        headers = set_session_cookie_headers(token)
        # also return spaces
        spaces = list_spaces(u["id"]) or []
        return JSONResponse(status_code=200, content={"user": {"id": u["id"], "email": email}, "spaces": spaces}, headers=headers)
    except Exception as e:
        msg = str(e) or ""
        low = msg.lower()
        try:
            # psycopg unique violation detection (best-effort)
            from psycopg.errors import UniqueViolation  # type: ignore
            if isinstance(e, UniqueViolation):
                return JSONResponse(status_code=409, content={"error": "email already registered"})
        except Exception:
            pass
        if "duplicate key" in low or "unique constraint" in low or "already exists" in low:
            return JSONResponse(status_code=409, content={"error": "email already registered"})
        return JSONResponse(status_code=400, content={"error": msg})


@app.post("/api/login")
async def api_login(payload: Dict[str, Any]):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    if not email or not password:
        return JSONResponse(status_code=400, content={"error": "email and password required"})
    u = authenticate_user(email, password)
    if not u:
        return JSONResponse(status_code=401, content={"error": "invalid credentials"})
    token = sign_session({"user_id": u["id"], "email": email})
    headers = set_session_cookie_headers(token)
    spaces = list_spaces(u["id"]) or []
    return JSONResponse(status_code=200, content={"user": {"id": u["id"], "email": email}, "spaces": spaces}, headers=headers)


@app.post("/api/logout")
async def api_logout():
    headers = clear_session_cookie_headers()
    return JSONResponse(status_code=200, content={"ok": True}, headers=headers)


@app.get("/api/admin/documents")
async def api_admin_list_documents(request: Request, space_id: int | None = None, limit: int = 50, offset: int = 0):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user["user_id"]) if "user_id" in user else int(user.get("id"))
    items: List[Dict[str, Any]] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            if space_id is not None:
                cur.execute(
                    """
                    SELECT d.id, d.space_id, d.source_path, d.source_type, COALESCE(d.title,''), d.created_at,
                           (SELECT count(*) FROM chunks c WHERE c.document_id = d.id) AS chunk_count
                    FROM documents d
                    WHERE d.user_id = %s AND d.space_id = %s
                    ORDER BY d.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (uid, int(space_id), int(limit), int(offset)),
                )
            else:
                cur.execute(
                    """
                    SELECT d.id, d.space_id, d.source_path, d.source_type, COALESCE(d.title,''), d.created_at,
                           (SELECT count(*) FROM chunks c WHERE c.document_id = d.id) AS chunk_count
                    FROM documents d
                    WHERE d.user_id = %s
                    ORDER BY d.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (uid, int(limit), int(offset)),
                )
            rows = cur.fetchall()
            for r in rows:
                items.append({
                    "id": int(r[0]),
                    "space_id": (int(r[1]) if r[1] is not None else None),
                    "source_path": r[2] or "",
                    "source_type": r[3] or "",
                    "title": r[4] or "",
                    "created_at": (r[5].isoformat() if r[5] else None),
                    "chunk_count": int(r[6] or 0),
                })
    return {"documents": items, "limit": int(limit), "offset": int(offset)}


@app.delete("/api/admin/documents/{doc_id}")
async def api_admin_delete_document(request: Request, doc_id: int):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user["user_id"]) if "user_id" in user else int(user.get("id"))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s AND user_id = %s", (int(doc_id), uid))
            deleted = cur.rowcount
    if deleted:
        return {"ok": True, "deleted": int(deleted)}
    return JSONResponse(status_code=404, content={"error": "document not found"})


@app.get("/api/me")
async def api_me(request: Request):
    user = await get_current_user(request)
    if not user:
        return {"user": None}
    uid = int(user["user_id"]) if "user_id" in user else int(user.get("id"))
    spaces = list_spaces(uid)
    return {"user": {"id": uid, "email": user.get("email")}, "spaces": spaces}


@app.get("/api/spaces")
async def api_spaces(request: Request):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user["user_id"]) if "user_id" in user else int(user.get("id"))
    return {"spaces": list_spaces(uid)}


@app.post("/api/spaces")
async def api_create_space(request: Request, payload: Dict[str, Any]):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user["user_id"]) if "user_id" in user else int(user.get("id"))
    name = (payload.get("name") or "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "name required"})
    sid = create_space(uid, name)
    return {"space_id": sid}


@app.post("/api/spaces/default")
async def api_set_default_space(request: Request, payload: Dict[str, Any]):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user["user_id"]) if "user_id" in user else int(user.get("id"))
    sid = int(payload.get("space_id"))
    set_default_space(uid, sid)
    return {"ok": True}


@app.post("/api/admin/reindex")
async def api_admin_reindex(request: Request, payload: Dict[str, Any]):
    """
    Reindex documents into OpenSearch. Body may include one of:
      - { "doc_id": <id> }
      - { "space_id": <id> }
      - { "all": true }
    Only documents owned by the authenticated user are processed.
    """
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user["user_id"]) if "user_id" in user else int(user.get("id"))

    doc_id = payload.get("doc_id")
    space_id = payload.get("space_id")
    scope_all = bool(payload.get("all"))

    adapter = OpenSearchAdapter()
    reindexed = 0
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if doc_id:
                    cur.execute("SELECT id, source_path, COALESCE(title,''), COALESCE(metadata,'{}'::jsonb) FROM documents WHERE id = %s AND user_id = %s", (int(doc_id), uid))
                    row = cur.fetchone()
                    if not row:
                        return JSONResponse(status_code=404, content={"error": "document not found"})
                    cur.execute("SELECT chunk_index, content FROM chunks WHERE document_id = %s ORDER BY chunk_index ASC", (int(doc_id),))
                    ch = cur.fetchall()
                    texts = [r[1] for r in ch]
                    vecs = embed_texts(texts) if texts else []
                    adapter.index_chunks(user_id=uid, space_id=None, doc_id=int(doc_id), chunks=texts, vectors=vecs, file_name=None, source_path=row[1], file_type="", refresh=True)
                    reindexed = len(texts)
                elif space_id:
                    cur.execute("SELECT id, source_path, COALESCE(title,'') FROM documents WHERE user_id = %s AND space_id = %s", (uid, int(space_id)))
                    docs = cur.fetchall()
                    for d in docs:
                        did = int(d[0])
                        cur.execute("SELECT chunk_index, content FROM chunks WHERE document_id = %s ORDER BY chunk_index ASC", (did,))
                        ch = cur.fetchall()
                        texts = [r[1] for r in ch]
                        if not texts:
                            continue
                        vecs = embed_texts(texts)
                        adapter.index_chunks(user_id=uid, space_id=int(space_id), doc_id=did, chunks=texts, vectors=vecs, file_name=None, source_path=d[1], file_type="", refresh=True)
                        reindexed += len(texts)
                elif scope_all:
                    cur.execute("SELECT id, space_id, source_path FROM documents WHERE user_id = %s", (uid,))
                    docs = cur.fetchall()
                    for d in docs:
                        did = int(d[0]); sid = d[1]
                        cur.execute("SELECT chunk_index, content FROM chunks WHERE document_id = %s ORDER BY chunk_index ASC", (did,))
                        ch = cur.fetchall()
                        texts = [r[1] for r in ch]
                        if not texts:
                            continue
                        vecs = embed_texts(texts)
                        adapter.index_chunks(user_id=uid, space_id=int(sid) if sid is not None else None, doc_id=did, chunks=texts, vectors=vecs, file_name=None, source_path=d[2], file_type="", refresh=True)
                        reindexed += len(texts)
                else:
                    return JSONResponse(status_code=400, content={"error": "provide doc_id, space_id, or all:true"})
        return {"ok": True, "reindexed_chunks": int(reindexed)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


def main():
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, workers=settings.workers, reload=False)



if __name__ == "__main__":
    main()
