from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import re

import psycopg
from datetime import datetime, timedelta
from urllib.parse import quote as urlquote

from .config import settings
from .db import get_conn
from .embeddings import embed_texts
from .vision_embeddings import embed_image_paths
from .text_utils import ChunkParams, chunk_text, read_text_from_file
from .pgvector_utils import to_vec_literal
from .opensearch_adapter import OpenSearchAdapter

try:
    from PIL import Image, ImageStat
except Exception:
    Image = None
    ImageStat = None

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    document_id: int
    num_chunks: int


def ensure_dirs() -> None:
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.model_cache_dir).mkdir(parents=True, exist_ok=True)


def _sanitize_email_for_path(email: str) -> str:
    e = (email or "public").strip().lower()
    e = e.replace("@", "_at_")
    e = re.sub(r"[^a-z0-9._\-]", "_", e)
    return e or "public"


def _dated_rel(base_name: str, user_email: Optional[str]) -> Path:
    now = datetime.utcnow()
    # email/YYYY/MM/DD/HHMMSS/base_name
    email_part = _sanitize_email_for_path(user_email or "public")
    sub = Path(email_part, str(now.year), f"{now.month:02d}", f"{now.day:02d}", now.strftime("%H%M%S"))
    return sub / base_name


def _build_oci_config():
    try:
        import oci  # type: ignore
    except Exception:
        return None, None
    cfg = None
    if settings.oci_config_file:
        try:
            import oci  # type: ignore
            cfg = oci.config.from_file(settings.oci_config_file, settings.oci_config_profile)
            if settings.oci_region:
                cfg["region"] = settings.oci_region
        except Exception:
            cfg = None
    else:
        required = [settings.oci_tenancy_ocid, settings.oci_user_ocid, settings.oci_fingerprint, settings.oci_private_key_path]
        if all(required):
            cfg = {
                "tenancy": settings.oci_tenancy_ocid,
                "user": settings.oci_user_ocid,
                "fingerprint": settings.oci_fingerprint,
                "key_file": settings.oci_private_key_path,
                "pass_phrase": settings.oci_private_key_passphrase,
                "region": settings.oci_region,
            }
    return cfg, settings.oci_region


def _relative_upload_path(abs_path: str) -> Path:
    """Best-effort relative path under upload_dir for derived assets."""
    base = Path(settings.upload_dir).resolve()
    try:
        rel = Path(abs_path).resolve().relative_to(base)
    except Exception:
        rel = Path(Path(abs_path).name)
    return rel


def _tokenize_filename(name: str) -> List[str]:
    tokens = [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]
    return tokens[:8]


def _dominant_color_name(img: "Image.Image") -> str:
    if ImageStat is None:
        return "neutral"
    stat = ImageStat.Stat(img.convert("RGB"))
    r, g, b = stat.mean
    palette = {
        "red": (200, 60, 60),
        "orange": (230, 140, 60),
        "yellow": (220, 220, 80),
        "green": (80, 170, 110),
        "blue": (80, 120, 200),
        "purple": (140, 80, 180),
        "pink": (220, 120, 190),
        "brown": (150, 100, 70),
        "gray": (140, 140, 140),
    }
    best = min(palette.items(), key=lambda item: ((r - item[1][0]) ** 2 + (g - item[1][1]) ** 2 + (b - item[1][2]) ** 2))
    return best[0]


def _derive_image_tags_caption(img: "Image.Image", file_path: str, metadata: Optional[Dict[str, Any]] = None) -> Tuple[List[str], str]:
    tags: List[str] = []
    meta = metadata or {}
    width, height = img.size
    orientation = "square"
    if width > height * 1.15:
        orientation = "landscape"
    elif height > width * 1.15:
        orientation = "portrait"
    tags.append(orientation)
    ext = Path(file_path).suffix.lower().lstrip(".")
    if ext:
        tags.append(ext)
    if img.mode:
        mode = img.mode.lower()
        if "rgba" in mode:
            tags.append("transparent")
        elif mode in {"l", "la"}:
            tags.append("grayscale")
    filename_tokens = _tokenize_filename(Path(file_path).stem)
    if meta.get("filename"):
        filename_tokens.extend(_tokenize_filename(Path(meta["filename"]).stem))
    seen = set(tags)
    for tok in filename_tokens:
        if tok not in seen:
            tags.append(tok)
            seen.add(tok)
    color = _dominant_color_name(img)
    if color not in seen:
        tags.append(color)
    caption = f"{orientation.title()} image in {color} tones, {width}x{height}px"
    return tags, caption


def _upload_to_oci(bucket_name: str, object_name: str, data: bytes, expire_seconds: int = 3600) -> Optional[str]:
    try:
        import oci  # type: ignore

        cfg, region = _build_oci_config()
        if not cfg:
            return None

        osc = oci.object_storage.ObjectStorageClient(cfg)
        ns = osc.get_namespace().data

        # Build details; ensure we set object_name and expiry
        details = oci.object_storage.models.CreatePreauthenticatedRequestDetails(
            name=f"kb-{int(datetime.utcnow().timestamp())}",
            bucket_listing_action=None,
            access_type="ObjectRead",
            time_expires=(datetime.utcnow() + timedelta(seconds=int(expire_seconds)))
        )
        # set attribute defensively to avoid SDK mismatches
        try:
            setattr(details, "object_name", object_name)
        except Exception:
            pass

        resp = osc.create_preauthenticated_request(
            namespace_name=ns,
            bucket_name=bucket_name,
            create_preauthenticated_request_details=details,
        )
        par = resp.data

        # upload the bytes
        osc.put_object(ns, bucket_name, object_name, data)

        # access_uri typically like: /p/{PAR_ID}/n/{ns}/b/{bucket}/o/{object_name}
        region = (cfg.get("region") or region or "").strip()
        base = f"https://objectstorage.{region}.oraclecloud.com" if region else "https://objectstorage.oraclecloud.com"
        return base + getattr(par, "access_uri", "")
    except Exception as e:
        logger.warning("Failed to create PAR for object %s: %s", object_name, e)
        return None


def create_par_for_object(object_name: str, expire_seconds: int = 900) -> Optional[str]:
    if not object_name or not settings.oci_os_bucket_name or not settings.oci_os_upload_enabled:
        return None
    try:
        import oci  # type: ignore

        cfg, region = _build_oci_config()
        if not cfg:
            return None

        osc = oci.object_storage.ObjectStorageClient(cfg)
        ns = osc.get_namespace().data
        details = oci.object_storage.models.CreatePreauthenticatedRequestDetails(
            name=f"kb-par-{int(datetime.utcnow().timestamp())}",
            bucket_listing_action=None,
            object_name=object_name,
            access_type="ObjectRead",
            time_expires=(datetime.utcnow() + timedelta(seconds=int(expire_seconds))),
        )
        resp = osc.create_preauthenticated_request(
            namespace_name=ns,
            bucket_name=settings.oci_os_bucket_name,
            create_preauthenticated_request_details=details,
        )
        region = (cfg.get("region") or region or "").strip()
        base = f"https://objectstorage.{region}.oraclecloud.com" if region else "https://objectstorage.oraclecloud.com"
        return base + getattr(resp.data, "access_uri", "")
    except Exception as e:
        logger.warning("Failed to create PAR for object %s: %s", object_name, e)
        return None


def delete_oci_object(object_name: str) -> bool:
    if not object_name or not settings.oci_os_bucket_name:
        return False
    try:
        import oci  # type: ignore

        cfg, _region = _build_oci_config()
        if not cfg:
            return False

        osc = oci.object_storage.ObjectStorageClient(cfg)
        ns = osc.get_namespace().data
        osc.delete_object(ns, settings.oci_os_bucket_name, object_name)
        return True
    except Exception as e:
        logger.warning("Failed to delete OCI object %s: %s", object_name, e)
        return False


def save_upload(file_bytes: bytes, filename: str, user_email: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """Save upload respecting storage backend selection and user partitioning.
    Object/local path: <email>/YYYY/MM/DD/HHMMSS/<filename>
    Returns (local_path_for_ingest, oci_object_url_or_None).
    """
    ensure_dirs()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise ValueError(f"File too large (> {settings.max_upload_size_mb} MB)")

    persist_local = settings.storage_backend in {"local", "both"}

    base_name = Path(filename).name.replace("..", ".")
    dated_rel = _dated_rel(base_name, user_email)

    # Choose base dir: persistent uploads vs temp area
    if persist_local:
        base_dir = Path(settings.upload_dir)
    else:
        base_dir = Path(settings.data_dir) / "tmp_uploads"
    target = base_dir / dated_rel
    target.parent.mkdir(parents=True, exist_ok=True)

    with open(target, "wb") as f:
        f.write(file_bytes)

    oci_url: Optional[str] = None
    if settings.storage_backend in {"oci", "both"} and settings.oci_os_bucket_name and settings.oci_os_upload_enabled:
        obj_name = str(dated_rel).replace("\\", "/")
        oci_url = _upload_to_oci(settings.oci_os_bucket_name, obj_name, file_bytes)

    return str(target), oci_url


def save_upload_stream(fileobj, filename: str, user_email: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """Stream upload without loading whole file in memory.
    Object/local path: <email>/YYYY/MM/DD/HHMMSS/<filename>
    Returns (local_path_for_ingest, oci_object_url_or_None).
    """
    import shutil

    ensure_dirs()
    persist_local = settings.storage_backend in {"local", "both"}

    base_name = Path(filename).name.replace("..", ".")
    dated_rel = _dated_rel(base_name, user_email)

    base_dir = Path(settings.upload_dir) if persist_local else (Path(settings.data_dir) / "tmp_uploads")
    target = base_dir / dated_rel
    target.parent.mkdir(parents=True, exist_ok=True)

    oci_url: Optional[str] = None

    # If using OCI, stream the file object to Object Storage first (then rewind for local copy)
    if settings.storage_backend in {"oci", "both"} and settings.oci_os_bucket_name and settings.oci_os_upload_enabled:
        try:
            import oci  # type: ignore
            cfg, region = _build_oci_config()
            if cfg:
                osc = oci.object_storage.ObjectStorageClient(cfg)
                ns = osc.get_namespace().data
                upload_manager = oci.object_storage.UploadManager(osc, allow_parallel_uploads=True)
                # Rewind stream to start
                try:
                    fileobj.seek(0)
                except Exception:
                    pass
                object_name = str(dated_rel).replace("\\", "/")
                upload_manager.upload_stream(ns, settings.oci_os_bucket_name, object_name, fileobj)
                region = (cfg.get("region") or region or "").strip()
                base = f"https://objectstorage.{region}.oraclecloud.com" if region else "https://objectstorage.oraclecloud.com"
                oci_url = f"{base}/n/{urlquote(ns)}/b/{urlquote(settings.oci_os_bucket_name)}/o/{urlquote(object_name)}"
                logger.info("OCI streaming upload complete: bucket=%s object=%s url=%s", settings.oci_os_bucket_name, object_name, oci_url)
            else:
                logger.warning("OCI streaming upload skipped: missing OCI config")
        except Exception as e:
            logger.exception("OCI streaming upload failed: %s", e)

    # Rewind and copy to local target for ingestion
    try:
        fileobj.seek(0)
    except Exception:
        pass
    with open(target, "wb") as out:
        shutil.copyfileobj(fileobj, out)

    return str(target), oci_url


def insert_document(conn: psycopg.Connection, user_id: int, space_id: Optional[int], source_path: str, source_type: str, title: Optional[str] = None, metadata: Optional[dict] = None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO documents (user_id, space_id, source_path, source_type, title, metadata) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (user_id, space_id, source_path, source_type, title, json.dumps(metadata or {})),
        )
        doc_id = cur.fetchone()[0]
    return int(doc_id)


def insert_chunks(conn: psycopg.Connection, document_id: int, chunks: Sequence[str], embeddings: Sequence[Sequence[float]]) -> int:
    if len(chunks) != len(embeddings):
        raise ValueError("Chunks and embeddings length mismatch")
    with conn.cursor() as cur:
        if settings.db_store_embeddings:
            rows = []
            for i, (content, emb) in enumerate(zip(chunks, embeddings)):
                rows.append((document_id, i, content, len(content), settings.embedding_model_name, to_vec_literal(emb)))
            cur.executemany(
                """
                INSERT INTO chunks (document_id, chunk_index, content, content_chars, embedding_model, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::vector)
                """,
                rows,
            )
            return len(rows)
        else:
            rows = []
            for i, content in enumerate(chunks):
                rows.append((document_id, i, content, len(content), settings.embedding_model_name))
            cur.executemany(
                """
                INSERT INTO chunks (document_id, chunk_index, content, content_chars, embedding_model, embedding)
                VALUES (%s, %s, %s, %s, %s, NULL)
                """,
                rows,
            )
            return len(rows)


def _update_document_metadata(conn: psycopg.Connection, doc_id: int, metadata: Dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE documents SET metadata = %s WHERE id = %s",
            (json.dumps(metadata), doc_id),
        )


def ingest_file_path(file_path: str, user_id: int, space_id: Optional[int] = None, title: Optional[str] = None, metadata: Optional[dict] = None, chunk_params: Optional[ChunkParams] = None) -> IngestResult:
    text, source_type = read_text_from_file(file_path)
    cp = chunk_params or ChunkParams(settings.chunk_size, settings.chunk_overlap)
    chunks = chunk_text(text, cp)
    if not chunks:
        raise ValueError("No textual content extracted from file")
    embeddings = embed_texts(chunks)

    doc_metadata: Dict[str, Any] = dict(metadata or {})

    with get_conn() as conn:
        doc_id = insert_document(conn, user_id, space_id, file_path, source_type, title=title, metadata=doc_metadata)
        insert_chunks(conn, doc_id, chunks, embeddings)

        if settings.enable_image_storage and source_type == "image" and Image is not None:
            try:
                img_meta_updates = _process_image_asset(conn, doc_id, user_id, space_id, file_path, doc_metadata)
                if img_meta_updates:
                    doc_metadata.update(img_meta_updates)
                    _update_document_metadata(conn, doc_id, doc_metadata)
            except Exception as e:
                logger.warning("Image asset processing failed for doc_id=%s: %s", doc_id, e)

    try:
        if settings.search_backend == "opensearch" and settings.opensearch_dual_write:
            adapter = OpenSearchAdapter()
            adapter.index_chunks(
                user_id=user_id,
                space_id=space_id,
                doc_id=doc_id,
                chunks=chunks,
                vectors=embeddings,
                file_name=Path(file_path).name,
                source_path=file_path,
                file_type=source_type,
            )
            logger.info("OpenSearch indexed doc_id=%s chunks=%s", doc_id, len(chunks))
            if settings.enable_image_storage and source_type == "image":
                try:
                    adapter.ensure_image_index()
                except Exception as e:
                    logger.warning("Image index ensure failed: %s", e)
    except Exception as e:
        logger.warning("OpenSearch dual-write failed for doc_id=%s: %s", doc_id, e)


def _process_image_asset(
    conn: psycopg.Connection,
    doc_id: int,
    user_id: int,
    space_id: Optional[int],
    file_path: str,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    if Image is None:
        raise RuntimeError("Pillow not available for image metadata")
    with Image.open(file_path) as img:
        width, height = img.size
        rgb_img = img.convert("RGB")
    thumb_dir = Path(settings.upload_dir) / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(file_path).stem
    thumb_path = thumb_dir / f"{stem}_thumb.jpg"
    thumb_img = rgb_img.copy()
    thumb_img.thumbnail((512, 512))
    thumb_img.save(thumb_path, format="JPEG", quality=80)

    rel_file = str(_relative_upload_path(file_path))
    rel_thumb = str(_relative_upload_path(str(thumb_path)))

    tags, caption = _derive_image_tags_caption(thumb_img, file_path, metadata)

    emb = embed_image_paths([file_path])
    vec = emb[0] if emb else None

    oci_object = metadata.get("object_url")
    oci_thumb_url = None
    if oci_object and settings.storage_backend in {"oci", "both"} and settings.oci_os_bucket_name:
        try:
            from urllib.parse import urlparse, unquote

            u = urlparse(oci_object)
            parts = u.path.split("/o/")
            if len(parts) == 2:
                object_name = unquote(parts[1])
                thumb_object = str(Path(object_name).with_name(Path(object_name).stem + "_thumb.jpg"))
                # Upload thumbnail bytes
                with open(thumb_path, "rb") as tbytes:
                    data = tbytes.read()
                oci_thumb_url = _upload_to_oci(settings.oci_os_bucket_name, thumb_object, data)
                if oci_thumb_url:
                    metadata["thumbnail_object_url"] = oci_thumb_url
        except Exception as e:
            logger.warning("Failed to mirror thumbnail to OCI: %s", e)

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO image_assets (document_id, user_id, space_id, file_path, thumbnail_path, width, height, tags, caption, embedding, embedding_model)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s) RETURNING id
        """,
        (
            doc_id,
            user_id,
            space_id,
            rel_file,
            rel_thumb,
            width,
            height,
            json.dumps(tags),
            caption,
            to_vec_literal(vec) if vec else None,
            settings.image_embed_model,
        ),
    )
    image_id = cur.fetchone()[0]
    try:
        adapter = OpenSearchAdapter()
        adapter.index_image_asset(
            user_id=user_id,
            space_id=space_id,
            doc_id=doc_id,
            image_id=image_id,
            file_path=rel_file,
            thumbnail_path=rel_thumb,
            tags=tags,
            caption=caption,
            vector=vec,
        )
    except Exception as e:
        logger.warning("Failed to index image asset %s in OpenSearch: %s", image_id, e)

    meta_updates: Dict[str, Any] = {
        "thumbnail_path": rel_thumb,
        "thumbnail_object_url": oci_thumb_url,
        "image_tags": tags,
        "image_caption": caption,
        "image_width": width,
        "image_height": height,
    }
    return meta_updates
