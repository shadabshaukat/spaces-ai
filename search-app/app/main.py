from __future__ import annotations

import logging
import os
import json
import mimetypes
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, unquote

from fastapi import FastAPI, File, UploadFile, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from .auth import SessionOrBasicAuthMiddleware
from .config import settings
from .db import init_db, get_conn
from .store import (
    ensure_dirs,
    ingest_file_path,
    save_upload,
    create_par_for_object,
    delete_oci_object,
    _build_oci_config,
    oci_upload_ready,
)
from .search import semantic_search, fulltext_search, hybrid_search, rag, image_search
from .embeddings import get_model, embed_texts
from .opensearch_adapter import OpenSearchAdapter
from .session import get_current_user, sign_session, set_session_cookie_headers, clear_session_cookie_headers
from .valkey_cache import cache_status, bump_revision
from .runtime_config import (
    get_default_top_k,
    set_default_top_k,
    get_pgvector_probes,
    set_pgvector_probes,
    get_os_num_candidates,
    set_os_num_candidates,
)
from .users import create_user, authenticate_user, list_spaces, get_default_space_id, create_space, set_default_space
from .deep_research import start_conversation as dr_start, ask as dr_ask
from .deep_research_store import (
    list_conversations as dr_list_conversations,
    get_conversation_detail as dr_get_conversation_detail,
    update_conversation_title as dr_update_conversation_title,
    add_notebook_entry as dr_add_notebook_entry,
    delete_notebook_entry as dr_delete_notebook_entry,
)
from .vision_embeddings import (
    embed_image_paths,
    embed_image_texts,
    VisionModelUnavailable,
    vision_dependencies_ready,
)

logger = logging.getLogger("searchapp")
log_level = logging.DEBUG if settings.debug_logging else os.getenv("LOGLEVEL", "INFO")
logging.basicConfig(level=log_level)


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=f"{settings.app_name}", version="0.5.0")

# Allowed upload types (documents + images only)
ALLOWED_EXTS = {
    ".pdf", ".txt", ".csv", ".md", ".json", ".html", ".htm",
    ".docx", ".pptx", ".xlsx",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}


def _asset_candidate_bases() -> List[Path]:
    bases = [Path(settings.upload_dir)]
    tmp_dir = Path(settings.data_dir) / "tmp_uploads"
    if tmp_dir != bases[0]:
        bases.append(tmp_dir)
    return bases


def _resolve_asset_path(rel_path: Optional[str]) -> Optional[Path]:
    if not rel_path:
        return None
    rel = str(rel_path).lstrip("/\\")
    if not rel:
        return None
    for base in _asset_candidate_bases():
        base_resolved = base.resolve()
        candidate = (base_resolved / rel).resolve()
        try:
            candidate.relative_to(base_resolved)
        except ValueError:
            continue
        if candidate.exists():
            return candidate
    return None


def _augment_image_payload(doc_id: int, image: Dict[str, Any], metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = dict(image)
    image_id = image.get("image_id")
    if image_id:
        payload["thumbnail_url"] = f"/api/image-assets/{image_id}/thumbnail"
    else:
        payload["thumbnail_url"] = None
    payload["file_url"] = f"/api/doc-download?doc_id={doc_id}" if doc_id else None
    if isinstance(metadata, dict):
        payload["object_url"] = metadata.get("object_url")
        payload["thumbnail_object_url"] = metadata.get("thumbnail_object_url")
    else:
        payload["object_url"] = None
        payload["thumbnail_object_url"] = None
    return payload


def _image_embedding_status_from_doc(meta: Dict[str, Any] | None, images: List[Dict[str, Any]]) -> str | None:
    if not images:
        return None
    if isinstance(meta, dict) and meta.get("image_warning"):
        return "missing"
    return "stored"


def _normalize_tags(raw: Any) -> List[str]:
    tags: List[str] = []
    if raw is None:
        return tags
    if isinstance(raw, str):
        parts = raw.split(",")
        tags = [p.strip() for p in parts if p.strip()]
    elif isinstance(raw, (list, tuple, set)):
        for item in raw:
            if item is None:
                continue
            sval = str(item).strip()
            if sval:
                tags.append(sval)
    else:
        sval = str(raw).strip()
        if sval:
            tags.append(sval)
    return tags


def _extract_tags(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                loaded = json.loads(stripped)
                if isinstance(loaded, list):
                    return _normalize_tags(loaded)
            except json.JSONDecodeError:
                pass
        return _normalize_tags(stripped)
    if isinstance(raw, (list, tuple, set)):
        tags: List[str] = []
        for item in raw:
            tags.extend(_normalize_tags(item))
        return tags
    return _normalize_tags(raw)


def _extract_query_text(raw: Any) -> str:
    """Normalize arbitrary payload values into a single string query."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, (list, tuple, set)):
        parts: List[str] = []
        for item in raw:
            txt = _extract_query_text(item)
            if txt:
                parts.append(txt)
        return " ".join(parts).strip()
    return str(raw).strip()


def _extract_vector(raw: Any) -> List[float] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        floats: List[float] = []
        for v in raw:
            try:
                floats.append(float(v))
            except (TypeError, ValueError):
                return None
        return floats
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            loaded = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        return _extract_vector(loaded)
    return None

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
    if settings.enable_image_storage:
        ready, detail = vision_dependencies_ready(preload_model=False)
        if ready:
            logger.info("Vision embeddings dependencies detected")
        else:
            logger.warning("Vision embeddings unavailable: %s", detail or "missing dependencies")
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
    cache_info = cache_status()
    status = "ok" if cache_info.get("state") in {"ready", "skipped"} else "degraded"
    return {"status": status, "cache": cache_info}


@app.get("/api/providers")
def list_providers():
    return {
        "default": settings.llm_provider,
        "supported": ["oci", "openai", "bedrock", "ollama"],
    }


@app.get("/api/upload-config")
def upload_config():
    oci_ready = None
    oci_detail = None
    if settings.storage_backend in {"oci", "both"}:
        ready, detail = oci_upload_ready()
        oci_ready = ready
        oci_detail = detail
    return {
        "max_upload_size_mb": settings.max_upload_size_mb,
        "max_upload_files": settings.max_upload_files,
        "allowed_extensions": sorted(list(ALLOWED_EXTS)),
        "storage_backend": settings.storage_backend,
        "enable_image_storage": settings.enable_image_storage,
        "oci": {
            "bucket": settings.oci_os_bucket_name,
            "upload_enabled": settings.oci_os_upload_enabled,
            "ready": oci_ready,
            "detail": oci_detail,
        },
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
    # Enforce max file count per request
    if len(files) > settings.max_upload_files:
        return JSONResponse(status_code=400, content={"error": f"too many files (max {settings.max_upload_files})"})

    results: List[Dict[str, Any]] = []
    for f in files:
        # Enforce allowed extensions and max size
        name = Path(f.filename).name
        ext = (Path(name).suffix or "").lower()
        if ext not in ALLOWED_EXTS:
            results.append({
                "filename": name,
                "title": Path(name).stem,
                "status": "error",
                "error": "unsupported file type",
            })
            continue
        # Save upload without OCI streaming to avoid auth/complexity; read bytes and save
        data = await f.read()
        max_bytes = settings.max_upload_size_mb * 1024 * 1024
        if len(data) > max_bytes:
            results.append({
                "filename": name,
                "title": Path(name).stem,
                "status": "error",
                "error": f"file too large (> {settings.max_upload_size_mb} MB)",
            })
            continue
        local_path, oci_url = save_upload(data, name, user_email=uemail)
        title = name
        title_no_ext = Path(title).stem
        logger.info("Upload stored: backend=%s local=%s oci=%s", settings.storage_backend, local_path, "yes" if oci_url else "no")
        try:
            meta = {"filename": title}
            if oci_url:
                meta["object_url"] = oci_url
            ing = ingest_file_path(local_path, user_id=uid, space_id=sid, title=title_no_ext, metadata=meta)
            result_entry: Dict[str, Any] = {
                "filename": title,
                "title": title_no_ext,
                "document_id": ing.document_id,
                "chunks": ing.num_chunks,
                "object_url": oci_url,
                "status": "ok",
            }
            if ext in IMAGE_EXTS:
                try:
                    diag = await api_image_search_diagnostics(request, doc_id=int(ing.document_id))
                    result_entry["image_diagnostics"] = diag
                except Exception:
                    logger.exception("Upload diagnostics failed for doc_id=%s", ing.document_id)
            results.append(result_entry)
            is_image = ext in IMAGE_EXTS
            if is_image:
                bump_revision("image", uid, sid)
            bump_revision("text", uid, sid)
            # Log activity
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO user_activity (user_id, activity_type, details) VALUES (%s, %s, %s)",
                            (uid, "upload", json.dumps({"filename": title, "document_id": ing.document_id, "chunks": ing.num_chunks, "space_id": sid, "image": is_image})),
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
                "doc_id": e.get("document_id"),
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


@app.post("/api/image-search")
async def api_image_search(request: Request):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user["user_id"]) if "user_id" in user else int(user.get("id"))
    content_type = request.headers.get("content-type", "")
    payload: Dict[str, Any] = {}
    reference_file: UploadFile | None = None

    logger.debug(
        "image_search request content-type=%s query-params=%s",
        content_type,
        dict(request.query_params),
    )

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        for key, value in form.multi_items():
            if isinstance(value, UploadFile):
                if key == "reference" and reference_file is None:
                    reference_file = value
                continue
            payload[key] = value
    else:
        try:
            body = await request.json()
            if isinstance(body, dict):
                payload = body
        except Exception:
            payload = {}

    logger.info(
        "image_search payload keys=%s reference=%s",
        sorted(payload.keys()),
        bool(reference_file),
    )

    sid = payload.get("space_id")
    sid = int(sid) if sid is not None else get_default_space_id(uid)

    query = _extract_query_text(payload.get("query"))
    tag_filter = _extract_tags(payload.get("tags"))
    top_k_raw = payload.get("top_k")
    try:
        top_k = int(top_k_raw) if top_k_raw is not None else min(24, int(get_default_top_k()))
    except Exception:
        top_k = min(24, int(get_default_top_k()))
    top_k = max(1, min(top_k, 100))

    vector_input = payload.get("vector")
    vector = _extract_vector(vector_input)

    logger.debug(
        "image_search normalized inputs: space_id=%s query=%r tags=%s top_k=%s vector_provided=%s",
        sid,
        query,
        tag_filter,
        top_k,
        vector is not None,
    )

    temp_file_path: str | None = None
    reference_used = False
    try:
        if reference_file is not None:
            if not reference_file.filename:
                return JSONResponse(status_code=400, content={"error": "reference filename missing"})
            suffix = Path(reference_file.filename).suffix.lower()
            if suffix and suffix not in IMAGE_EXTS:
                return JSONResponse(status_code=400, content={"error": "unsupported reference type"})
            with NamedTemporaryFile(delete=False, suffix=suffix or ".img") as tmp:
                data = await reference_file.read()
                tmp.write(data)
                temp_file_path = tmp.name
            logger.debug("image_search embedding reference file=%s size=%s", reference_file.filename, os.path.getsize(temp_file_path))
            try:
                vectors = embed_image_paths([temp_file_path])
                vector = vectors[0] if vectors else None
                reference_used = vector is not None
                logger.debug("image_search reference vector generated=%s", reference_used)
            except VisionModelUnavailable as e:
                logger.warning("Vision model unavailable for reference: %s", e)
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "vision model unavailable",
                        "detail": str(e),
                        "install_hint": "Install OpenCLIP/Torch via `uv sync --extra image` or `pip install .[image]`",
                    },
                )
            except Exception as e:
                logger.warning("Failed to embed reference image: %s", e)
                return JSONResponse(status_code=400, content={"error": "failed to process reference image", "detail": str(e)})
            finally:
                try:
                    if reference_file and reference_file.file:
                        reference_file.file.close()
                except Exception:
                    pass

        if vector is None and query:
            try:
                vecs = embed_image_texts([query])
                vector = vecs[0] if vecs else None
                logger.debug("image_search text vector generated=%s", vector is not None)
            except VisionModelUnavailable as e:
                logger.warning("Vision model unavailable: %s", e)
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "vision model unavailable",
                        "detail": str(e),
                        "install_hint": "Install OpenCLIP/Torch via `uv sync --extra image` or `pip install .[image]`",
                    },
                )
            except Exception as e:
                logger.warning("Image text embedding failed: %s", e)
                vector = None
    finally:
        if temp_file_path:
            try:
                os.remove(temp_file_path)
            except OSError:
                pass

    if vector is None and not query and not tag_filter:
        return JSONResponse(status_code=400, content={"error": "provide query, tags, or vector"})

    logger.info(
        "image_search executing: query=%r tags=%s top_k=%s has_vector=%s reference=%s",
        query,
        tag_filter,
        top_k,
        vector is not None,
        reference_used,
    )

    hits = image_search(query=query, vector=vector, top_k=top_k, user_id=uid, space_id=sid, tags=tag_filter)

    results: List[Dict[str, Any]] = []
    for idx, h in enumerate(hits, start=1):
        src = h.get("_source", h)
        results.append(
            {
                "rank": idx,
                "doc_id": src.get("doc_id"),
                "image_id": src.get("image_id"),
                "thumbnail_path": src.get("thumbnail_path"),
                "file_path": src.get("file_path"),
                "caption": src.get("caption"),
                "tags": src.get("tags", []),
                "score": h.get("_score"),
            }
        )

    doc_meta_map: Dict[int, Dict[str, Any]] = {}
    doc_ids = sorted({int(r["doc_id"]) for r in results if r.get("doc_id")})
    if doc_ids:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, COALESCE(metadata,'{}'::jsonb) FROM documents WHERE id = ANY(%s)",
                    (doc_ids,),
                )
                doc_meta_map = {int(row[0]): (row[1] or {}) for row in cur.fetchall()}

    for item in results:
        doc_id = item.get("doc_id")
        image_id = item.get("image_id")
        meta = doc_meta_map.get(int(doc_id)) if doc_id else {}
        item["thumbnail_url"] = f"/api/image-assets/{image_id}/thumbnail" if image_id else None
        if isinstance(meta, dict):
            item["thumbnail_object_url"] = meta.get("thumbnail_object_url")
            item["object_url"] = meta.get("object_url")
        else:
            item["thumbnail_object_url"] = None
            item["object_url"] = None
        item["file_url"] = f"/api/doc-download?doc_id={doc_id}" if doc_id else None

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO user_activity (user_id, activity_type, details) VALUES (%s, %s, %s)",
                    (
                        uid,
                        "image_search",
                        json.dumps({
                            "query": query,
                            "top_k": top_k,
                            "space_id": sid,
                            "tags": tag_filter,
                            "vector": bool(vector),
                            "reference": reference_used,
                        }),
                    ),
                )
    except Exception:
        pass

    return {"results": results, "count": len(results)}


@app.get("/api/image-search/config")
async def api_image_search_config(request: Request):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    backend = settings.search_backend
    storage_backend = settings.storage_backend
    use_opensearch = backend == "opensearch" and bool(settings.opensearch_host)
    return {
        "search_backend": backend,
        "storage_backend": storage_backend,
        "enable_image_storage": bool(settings.enable_image_storage),
        "image_vectors_read_from": "opensearch" if use_opensearch else "postgres",
        "image_vectors_stored_in": {
            "postgres": True,
            "opensearch": bool(settings.opensearch_host) if backend == "opensearch" else False,
        },
        "image_files_stored_in": {
            "local": storage_backend in {"local", "both"},
            "oci": storage_backend in {"oci", "both"} and settings.oci_os_upload_enabled,
        },
        "image_index": settings.image_index_name,
        "image_embed_model": settings.image_embed_model,
        "image_embed_dim": settings.image_embed_dim,
    }


@app.get("/api/image-search/diagnostics")
async def api_image_search_diagnostics(request: Request, image_id: int | None = None, doc_id: int | None = None):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    if image_id is None and doc_id is None:
        return JSONResponse(status_code=400, content={"error": "provide image_id or doc_id"})

    pg: Dict[str, Any] = {"exists": False, "embedding": False, "image_id": None, "doc_id": None}
    os_res: Dict[str, Any] = {"exists": False, "image_id": None, "doc_id": None, "error": None}
    use_opensearch = settings.search_backend == "opensearch" and bool(settings.opensearch_host)

    with get_conn() as conn:
        with conn.cursor() as cur:
            if image_id is not None:
                cur.execute(
                    """
                    SELECT ia.id, ia.document_id, ia.embedding IS NOT NULL
                    FROM image_assets ia
                    JOIN documents d ON d.id = ia.document_id
                    WHERE ia.id = %s AND d.user_id = %s
                    """,
                    (int(image_id), uid),
                )
            else:
                cur.execute(
                    """
                    SELECT ia.id, ia.document_id, ia.embedding IS NOT NULL
                    FROM image_assets ia
                    JOIN documents d ON d.id = ia.document_id
                    WHERE ia.document_id = %s AND d.user_id = %s
                    ORDER BY ia.created_at DESC
                    LIMIT 1
                    """,
                    (int(doc_id), uid),
                )
            row = cur.fetchone()
            if row:
                pg = {
                    "exists": True,
                    "embedding": bool(row[2]),
                    "image_id": int(row[0]),
                    "doc_id": int(row[1]),
                }

    if use_opensearch and pg.get("image_id") is not None:
        adapter = OpenSearchAdapter()
        try:
            res = adapter.client().get(index=settings.image_index_name, id=f"{pg['doc_id']}:{pg['image_id']}")
            os_res = {
                "exists": bool(res.get("found")),
                "image_id": pg["image_id"],
                "doc_id": pg["doc_id"],
                "error": None,
            }
        except Exception as exc:
            os_res = {
                "exists": False,
                "image_id": pg.get("image_id"),
                "doc_id": pg.get("doc_id"),
                "error": str(exc),
            }

    return {
        "postgres": pg,
        "opensearch": os_res,
        "search_backend": settings.search_backend,
        "storage_backend": settings.storage_backend,
        "image_index": settings.image_index_name,
    }


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


@app.post("/api/deep-research/start")
async def api_dr_start(request: Request, payload: Dict[str, Any] | None = None):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    sid = None
    if payload and payload.get("space_id") is not None:
        try:
            sid = int(payload.get("space_id"))
        except Exception:
            sid = None
    if sid is None:
        sid = get_default_space_id(uid)
    cid = dr_start(uid, sid)
    return {"conversation_id": cid}


@app.post("/api/deep-research/ask")
async def api_dr_ask(request: Request, payload: Dict[str, Any]):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    message = (payload or {}).get("message") or ""
    conversation_id = (payload or {}).get("conversation_id") or ""
    provider = (payload or {}).get("llm_provider") or None
    sid = payload.get("space_id")
    sid = int(sid) if sid is not None else get_default_space_id(uid)
    if not conversation_id:
        return JSONResponse(status_code=400, content={"error": "conversation_id required"})
    if not message:
        return JSONResponse(status_code=400, content={"error": "message required"})
    force_web = bool(payload.get("force_web"))
    urls = payload.get("urls")
    if isinstance(urls, str):
        urls = [urls]
    if isinstance(urls, (list, tuple)):
        urls = [str(u) for u in urls if u]
    else:
        urls = []
    try:
        out = dr_ask(
            uid,
            sid,
            conversation_id,
            message,
            provider_override=provider,
            force_web=force_web,
            urls=urls,
        )
        return out
    except Exception as e:
        logger.exception("DR ask failed: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/deep-research/conversations")
async def api_dr_conversations(request: Request, space_id: int | None = None):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    try:
        items = dr_list_conversations(uid, int(space_id) if space_id is not None else None)
        return {"conversations": items}
    except Exception as e:
        logger.exception("DR conversations list failed: %s", e)
        return JSONResponse(status_code=500, content={"error": "failed to list conversations"})


@app.get("/api/deep-research/conversations/{conversation_id}")
async def api_dr_conversation_detail(request: Request, conversation_id: str):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    try:
        detail = dr_get_conversation_detail(uid, conversation_id)
        return detail
    except PermissionError:
        return JSONResponse(status_code=404, content={"error": "conversation not found"})
    except Exception as e:
        logger.exception("DR conversation detail failed: %s", e)
        return JSONResponse(status_code=500, content={"error": "failed to load conversation"})


@app.post("/api/deep-research/conversations/{conversation_id}/title")
async def api_dr_conversation_title(request: Request, conversation_id: str, payload: Dict[str, Any]):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    title = (payload or {}).get("title")
    if not title or not str(title).strip():
        return JSONResponse(status_code=400, content={"error": "title required"})
    try:
        dr_update_conversation_title(uid, conversation_id, str(title).strip())
        return {"ok": True}
    except PermissionError:
        return JSONResponse(status_code=404, content={"error": "conversation not found"})
    except Exception as e:
        logger.exception("DR conversation title update failed: %s", e)
        return JSONResponse(status_code=500, content={"error": "failed to update title"})


@app.post("/api/deep-research/notebook/{conversation_id}")
async def api_dr_notebook_add(request: Request, conversation_id: str, payload: Dict[str, Any]):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    title = (payload or {}).get("title") or "Notebook entry"
    content = (payload or {}).get("content")
    source = (payload or {}).get("source")
    if not content or not str(content).strip():
        return JSONResponse(status_code=400, content={"error": "content required"})
    try:
        entry = dr_add_notebook_entry(uid, conversation_id, str(title).strip(), str(content).strip(), source if isinstance(source, dict) else None)
        return entry
    except PermissionError:
        return JSONResponse(status_code=404, content={"error": "conversation not found"})
    except Exception as e:
        logger.exception("DR notebook add failed: %s", e)
        return JSONResponse(status_code=500, content={"error": "failed to add entry"})


@app.delete("/api/deep-research/notebook/{entry_id}")
async def api_dr_notebook_delete(request: Request, entry_id: int):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    try:
        deleted = dr_delete_notebook_entry(uid, int(entry_id))
        if not deleted:
            return JSONResponse(status_code=404, content={"error": "entry not found"})
        return {"ok": True}
    except PermissionError:
        return JSONResponse(status_code=404, content={"error": "entry not found"})
    except Exception as e:
        logger.exception("DR notebook delete failed: %s", e)
        return JSONResponse(status_code=500, content={"error": "failed to delete entry"})


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


@app.get("/api/deep-research-config")
async def get_deep_research_config(request: Request):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return {
        "followup_autosend": bool(settings.deep_research_followup_autosend),
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

    source_path = None
    object_url = None
    destroyed_doc = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Fetch storage info first
            cur.execute("SELECT id, user_id, space_id, source_path, COALESCE(metadata,'{}'::jsonb) FROM documents WHERE id = %s AND user_id = %s", (int(doc_id), uid))
            row = cur.fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": "document not found"})
            destroyed_doc = {"id": int(row[0]), "space_id": row[2]}
            source_path = row[3] or None
            meta = row[4] or {}
            if isinstance(meta, dict):
                object_url = meta.get("object_url")
            # Delete DB row (cascades to chunks)
            cur.execute("DELETE FROM documents WHERE id = %s AND user_id = %s", (int(doc_id), uid))
            deleted = cur.rowcount

    if not deleted:
        return JSONResponse(status_code=404, content={"error": "document not found"})

    # Best-effort storage cleanup
    try:
        # Local file
        if source_path and settings.storage_backend in {"local", "both"}:
            p = Path(source_path)
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        # OCI object
        if object_url and settings.storage_backend in {"oci", "both"} and settings.oci_os_bucket_name:
            from urllib.parse import urlparse, unquote
            try:
                u = urlparse(object_url)
                parts = u.path.split("/o/")
                if len(parts) == 2:
                    object_name = unquote(parts[1])
                    delete_oci_object(object_name)
            except Exception:
                pass
    except Exception:
        pass

    # Best-effort OpenSearch cleanup (remove indexed chunks for this document)
    try:
        if settings.search_backend == "opensearch" and settings.opensearch_host:
            adapter = OpenSearchAdapter()
            try:
                adapter.delete_document(doc_id=int(doc_id), user_id=uid)
            except Exception:
                pass
    except Exception:
        pass

    if destroyed_doc:
        bump_revision("text", uid, destroyed_doc.get("space_id"))
        bump_revision("image", uid, destroyed_doc.get("space_id"))

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO user_activity (user_id, activity_type, details) VALUES (%s, %s, %s)",
                    (uid, "delete_doc", json.dumps({"doc_id": int(doc_id)})),
                )
    except Exception:
        pass

    return {"ok": True, "deleted": int(deleted)}


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


@app.get("/api/kb")
async def api_kb(request: Request, limit: int = 200, offset: int = 0, space_id: int | None = None, order: str = "desc", include_images: bool = True):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    order = order.lower()
    ord_dir = "DESC" if order != "asc" else "ASC"
    items: List[Dict[str, Any]] = []

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                base_sql = """
                    SELECT d.id, d.source_path, d.source_type, COALESCE(d.title,''), d.created_at,
                           COALESCE(d.metadata,'{{}}'::jsonb) AS metadata
                    FROM documents d
                    WHERE d.user_id = %s {space_clause}
                    ORDER BY d.created_at {order_dir}
                    LIMIT %s OFFSET %s
                """
                params: List[Any] = [uid]
                space_clause = ""
                if space_id is not None:
                    space_clause = "AND d.space_id = %s"
                    params.append(int(space_id))
                params.extend([int(limit), int(offset)])
                sql = base_sql.format(space_clause=space_clause, order_dir=ord_dir)
                cur.execute(sql, params)
                rows = cur.fetchall()

                doc_ids = [int(r[0]) for r in rows]
                chunk_counts: Dict[int, int] = {}
                meta_by_doc: Dict[int, Dict[str, Any]] = {}
                if doc_ids:
                    cur.execute(
                        "SELECT document_id, count(*) FROM chunks WHERE document_id = ANY(%s) GROUP BY document_id",
                        (doc_ids,),
                    )
                    chunk_counts = {int(r[0]): int(r[1]) for r in cur.fetchall()}
                    cur.execute(
                        "SELECT id, COALESCE(metadata,'{}'::jsonb) FROM documents WHERE id = ANY(%s)",
                        (doc_ids,),
                    )
                    meta_by_doc = {int(r[0]): (r[1] or {}) for r in cur.fetchall()}

                image_map: Dict[int, List[Dict[str, Any]]] = {}
                if include_images and doc_ids:
                    placeholders = "(" + ",".join(["%s"] * len(doc_ids)) + ")"
                    cur.execute(
                        f"""
                        SELECT document_id, id, thumbnail_path, file_path, width, height, caption, tags
                        FROM image_assets
                        WHERE document_id IN {placeholders}
                        ORDER BY created_at DESC
                        """,
                        doc_ids,
                    )
                    for row in cur.fetchall():
                        doc_key = int(row[0])
                        image_map.setdefault(doc_key, []).append(
                            {
                                "image_id": int(row[1]),
                                "thumbnail_path": row[2],
                                "file_path": row[3],
                                "width": row[4],
                                "height": row[5],
                                "caption": row[6],
                                "tags": row[7] or [],
                            }
                        )

                for r in rows:
                    sp = r[1] or ""
                    fn = sp.rsplit("/", 1)[-1] if sp else ""
                    doc_id = int(r[0])
                    metadata = meta_by_doc.get(doc_id) or {}
                    doc_images = [_augment_image_payload(doc_id, img, metadata) for img in image_map.get(doc_id, [])]
                    image_embedding_status = _image_embedding_status_from_doc(metadata, doc_images)
                    preview_url = doc_images[0].get("thumbnail_url") if doc_images else None
                    if not preview_url and isinstance(metadata, dict):
                        preview_url = metadata.get("thumbnail_object_url")
                    items.append(
                        {
                            "id": doc_id,
                            "file_name": fn,
                            "source_path": sp,
                            "source_type": r[2] or "",
                            "title": r[3] or "",
                            "created_at": (r[4].isoformat() if r[4] else None),
                            "chunk_count": chunk_counts.get(doc_id, 0),
                            "metadata": metadata,
                            "images": doc_images,
                            "image_embedding_status": image_embedding_status,
                            "thumbnail_preview_url": preview_url,
                        }
                    )
    except Exception as e:
        logger.exception("Failed to load KB: %s", e)
        return JSONResponse(status_code=500, content={"error": "failed to load knowledge base"})

    return {
        "documents": items,
        "limit": int(limit),
        "offset": int(offset),
        "space_id": (int(space_id) if space_id is not None else None),
        "order": ord_dir.lower(),
        "include_images": bool(include_images),
    }


@app.get("/api/image-assets/{image_id}/thumbnail")
async def api_image_thumbnail(request: Request, image_id: int):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ia.thumbnail_path, ia.document_id, d.user_id, COALESCE(d.metadata,'{}'::jsonb)
                FROM image_assets ia
                JOIN documents d ON d.id = ia.document_id
                WHERE ia.id = %s
                """,
                (int(image_id),),
            )
            row = cur.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "not found"})
    thumb_rel, doc_id, owner_id, metadata = row
    if int(owner_id) != uid:
        return JSONResponse(status_code=404, content={"error": "not found"})

    path = _resolve_asset_path(thumb_rel)
    if path and path.exists():
        media_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        return FileResponse(str(path), media_type=media_type)

    meta = metadata or {}
    if isinstance(meta, dict):
        remote = meta.get("thumbnail_object_url")
        if remote:
            return RedirectResponse(remote, status_code=307)

    return JSONResponse(status_code=404, content={"error": "thumbnail unavailable"})


@app.get("/api/image-assets/{image_id}")
async def api_image_asset(request: Request, image_id: int):
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ia.file_path, ia.document_id, d.user_id, COALESCE(d.metadata,'{}'::jsonb)
                FROM image_assets ia
                JOIN documents d ON d.id = ia.document_id
                WHERE ia.id = %s
                """,
                (int(image_id),),
            )
            row = cur.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "not found"})
    file_rel, doc_id, owner_id, metadata = row
    if int(owner_id) != uid:
        return JSONResponse(status_code=404, content={"error": "not found"})

    path = _resolve_asset_path(file_rel)
    if path and path.exists():
        media_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        return FileResponse(str(path), media_type=media_type)

    meta = metadata or {}
    if isinstance(meta, dict):
        remote = meta.get("object_url")
        if remote:
            return RedirectResponse(remote, status_code=307)

    return JSONResponse(status_code=404, content={"error": "image unavailable"})


@app.get("/api/doc-url")
async def api_doc_url(request: Request, doc_id: int):
    # Kept for backward compatibility; returns a direct URL (PAR/local) but may render inline in browsers
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT source_path, COALESCE(metadata,'{}'::jsonb) FROM documents WHERE id = %s AND user_id = %s", (int(doc_id), uid))
                row = cur.fetchone()
                if not row:
                    return JSONResponse(status_code=404, content={"error": "document not found"})
                meta = row[1] or {}
        from urllib.parse import urlparse, unquote
        if (settings.storage_backend in {"oci", "both"}) and settings.oci_os_bucket_name:
            obj_url = (meta.get("object_url") if isinstance(meta, dict) else None)
            if obj_url:
                u = urlparse(obj_url)
                parts = u.path.split("/o/")
                if len(parts) == 2:
                    object_name = unquote(parts[1])
                    par = create_par_for_object(object_name)
                    if par:
                        return {"url": par}
                return {"url": obj_url}
        return {"url": f"/api/download/{int(doc_id)}"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/doc-download")
async def api_doc_download(request: Request, doc_id: int):
    """Force a download response for a document: streams local files or OCI objects with attachment disposition."""
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    uid = int(user.get("user_id") or user.get("id"))
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT source_path, COALESCE(metadata,'{}'::jsonb) FROM documents WHERE id = %s AND user_id = %s", (int(doc_id), uid))
                row = cur.fetchone()
                if not row:
                    return JSONResponse(status_code=404, content={"error": "document not found"})
                source_path = row[0] or ""
                meta = row[1] or {}
        # Local download
        if settings.storage_backend in {"local", "both"} and source_path:
            p = Path(source_path)
            if not p.exists():
                return JSONResponse(status_code=404, content={"error": "file not found"})
            filename = p.name
            headers = {"Content-Disposition": f"attachment; filename=\"{filename}\""}
            return FileResponse(str(p), media_type="application/octet-stream", filename=filename, headers=headers)
        # OCI object download (proxy through server for attachment)
        if settings.storage_backend in {"oci", "both"} and settings.oci_os_bucket_name and isinstance(meta, dict):
            obj_url = meta.get("object_url")
            if obj_url:
                from urllib.parse import urlparse, unquote
                u = urlparse(obj_url)
                parts = u.path.split("/o/")
                if len(parts) == 2:
                    object_name = unquote(parts[1])
                    try:
                        cfg, _region = _build_oci_config()
                        if not cfg:
                            return JSONResponse(status_code=500, content={"error": "OCI configuration missing"})
                        import oci  # type: ignore
                        osc = oci.object_storage.ObjectStorageClient(cfg)
                        ns = osc.get_namespace().data
                        resp = osc.get_object(ns, settings.oci_os_bucket_name, object_name)
                        filename = object_name.rsplit("/", 1)[-1]
                        media_type = resp.headers.get("content-type", "application/octet-stream") if hasattr(resp, "headers") else "application/octet-stream"
                        def _iter():
                            raw = resp.data.raw
                            while True:
                                chunk = raw.read(8192)
                                if not chunk:
                                    break
                                yield chunk
                        return StreamingResponse(_iter(), media_type=media_type, headers={"Content-Disposition": f"attachment; filename=\"{filename}\""})
                    except Exception as e:
                        return JSONResponse(status_code=500, content={"error": f"OCI download failed: {e}"})
        return JSONResponse(status_code=404, content={"error": "download not available"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/download/{doc_id}")
async def api_download(request: Request, doc_id: int):
    """Serve a local file for the authenticated user. Only when storage backend includes local."""
    user = await get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    if settings.storage_backend not in {"local", "both"}:
        return JSONResponse(status_code=400, content={"error": "local storage not enabled"})
    uid = int(user.get("user_id") or user.get("id"))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT source_path FROM documents WHERE id = %s AND user_id = %s", (int(doc_id), uid))
            row = cur.fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": "document not found"})
            path = row[0] or ""
    try:
        p = Path(path)
        if not p.exists():
            return JSONResponse(status_code=404, content={"error": "file not found"})
        filename = p.name
        return FileResponse(str(p), media_type="application/octet-stream", filename=filename)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


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
                    cur.execute("SELECT id, space_id, source_path, COALESCE(title,''), COALESCE(metadata,'{}'::jsonb), created_at FROM documents WHERE id = %s AND user_id = %s", (int(doc_id), uid))
                    row = cur.fetchone()
                    if not row:
                        return JSONResponse(status_code=404, content={"error": "document not found"})
                    cur.execute("SELECT chunk_index, content FROM chunks WHERE document_id = %s ORDER BY chunk_index ASC", (int(doc_id),))
                    ch = cur.fetchall()
                    texts = [r[1] for r in ch]
                    vecs = embed_texts(texts) if texts else []
                    created_at = row[5].isoformat() if row[5] else None
                    doc_space_id = int(row[1]) if row[1] is not None else None
                    adapter.index_chunks(user_id=uid, space_id=doc_space_id, doc_id=int(doc_id), chunks=texts, vectors=vecs, file_name=None, source_path=row[2], file_type="", created_at=created_at, refresh=True)
                    reindexed = len(texts)
                elif space_id:
                    cur.execute("SELECT id, source_path, COALESCE(title,''), created_at FROM documents WHERE user_id = %s AND space_id = %s", (uid, int(space_id)))
                    docs = cur.fetchall()
                    for d in docs:
                        did = int(d[0])
                        cur.execute("SELECT chunk_index, content FROM chunks WHERE document_id = %s ORDER BY chunk_index ASC", (did,))
                        ch = cur.fetchall()
                        texts = [r[1] for r in ch]
                        if not texts:
                            continue
                        vecs = embed_texts(texts)
                        created_at = d[3].isoformat() if d[3] else None
                        adapter.index_chunks(user_id=uid, space_id=int(space_id), doc_id=did, chunks=texts, vectors=vecs, file_name=None, source_path=d[1], file_type="", created_at=created_at, refresh=True)
                        reindexed += len(texts)
                elif scope_all:
                    cur.execute("SELECT id, space_id, source_path, created_at FROM documents WHERE user_id = %s", (uid,))
                    docs = cur.fetchall()
                    for d in docs:
                        did = int(d[0])
                        sid = d[1]
                        cur.execute("SELECT chunk_index, content FROM chunks WHERE document_id = %s ORDER BY chunk_index ASC", (did,))
                        ch = cur.fetchall()
                        texts = [r[1] for r in ch]
                        if not texts:
                            continue
                        vecs = embed_texts(texts)
                        created_at = d[3].isoformat() if d[3] else None
                        adapter.index_chunks(user_id=uid, space_id=int(sid) if sid is not None else None, doc_id=did, chunks=texts, vectors=vecs, file_name=None, source_path=d[2], file_type="", created_at=created_at, refresh=True)
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