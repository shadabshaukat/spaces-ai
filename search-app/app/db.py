from __future__ import annotations

import contextlib
import logging
from typing import Optional

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Settings, build_database_url, settings

logger = logging.getLogger(__name__)

_pool: Optional[ConnectionPool] = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        dsn = build_database_url(settings)
        _pool = ConnectionPool(
            conninfo=dsn,
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
            kwargs={"autocommit": True},
        )
        logger.info("Initialized PostgreSQL connection pool (min=%s, max=%s)", settings.db_pool_min_size, settings.db_pool_max_size)
    return _pool


@contextlib.contextmanager
def get_conn():
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


@contextlib.contextmanager
def get_cursor(row_factory=dict_row):
    with get_conn() as conn:
        with conn.cursor(row_factory=row_factory) as cur:
            yield cur


def init_db(s: Settings = settings) -> None:
    """
    Initialize database: create extensions, tables, and indexes if they do not exist.
    Uses settings.embedding_dim, pgvector metric/lists configuration, and FTS config.
    """
    dim = s.embedding_dim
    metric = s.pgvector_metric.lower()
    if metric not in {"cosine", "l2", "ip"}:
        raise ValueError("PGVECTOR_METRIC must be one of: cosine, l2, ip")
    opclass = {
        "cosine": "vector_cosine_ops",
        "l2": "vector_l2_ops",
        "ip": "vector_ip_ops",
    }[metric]

    with get_conn() as conn:
        # Ensure extensions
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            cur.execute("CREATE EXTENSION IF NOT EXISTS citext")

        # Create tables
        with conn.cursor() as cur:
            # Core domain tables
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    email CITEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    last_login_at TIMESTAMPTZ
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS spaces (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    is_default BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(user_id, name)
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    space_id BIGINT REFERENCES spaces(id) ON DELETE SET NULL,
                    source_path TEXT,
                    source_type TEXT NOT NULL,
                    title TEXT,
                    metadata JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT now()
                );
                """
            )

            # Backfill columns for pre-existing deployments
            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id BIGINT")
            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS space_id BIGINT")

            cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_user_space ON documents(user_id, space_id, created_at DESC)")

            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    id BIGSERIAL PRIMARY KEY,
                    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    chunk_index INT NOT NULL,
                    content TEXT NOT NULL,
                    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('{s.fts_config}', content)) STORED,
                    content_chars INT,
                    embedding vector({dim}),
                    embedding_model TEXT,
                    created_at TIMESTAMPTZ DEFAULT now()
                );
                """
            )

            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_doc_chunk ON chunks(document_id, chunk_index);
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING GIN (content_tsv);
                """
            )

            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_chunks_embedding_ivfflat
                ON chunks USING ivfflat (embedding {opclass})
                WITH (lists = {s.pgvector_lists});
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_activity (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    activity_type TEXT NOT NULL,
                    details JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT now()
                );
                """
            )

            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_activity_user_time ON user_activity(user_id, created_at DESC)")

            # Image assets table (stores metadata + pgvector embeddings if enabled)
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS image_assets (
                    id BIGSERIAL PRIMARY KEY,
                    document_id BIGINT REFERENCES documents(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    space_id BIGINT REFERENCES spaces(id) ON DELETE SET NULL,
                    file_path TEXT,
                    thumbnail_path TEXT,
                    width INT,
                    height INT,
                    tags JSONB DEFAULT '[]'::jsonb,
                    caption TEXT,
                    embedding vector({settings.image_embed_dim}),
                    embedding_model TEXT,
                    created_at TIMESTAMPTZ DEFAULT now()
                );
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_image_assets_user_space ON image_assets(user_id, space_id, created_at DESC);
                """
            )

            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_image_assets_embedding_ivfflat
                ON image_assets USING ivfflat (embedding {opclass})
                WITH (lists = {s.pgvector_lists});
                """
            )

            # Structured tables extracted from documents
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS document_tables (
                    id BIGSERIAL PRIMARY KEY,
                    document_id BIGINT REFERENCES documents(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    space_id BIGINT REFERENCES spaces(id) ON DELETE SET NULL,
                    table_index INT,
                    schema_json JSONB DEFAULT '[]'::jsonb,
                    rows_json JSONB DEFAULT '[]'::jsonb,
                    summary TEXT,
                    created_at TIMESTAMPTZ DEFAULT now()
                );
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_document_tables_user_space ON document_tables(user_id, space_id, created_at DESC);
                """
            )

            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS conversation_external_docs (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    space_id BIGINT REFERENCES spaces(id) ON DELETE SET NULL,
                    conversation_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    parent_url TEXT,
                    depth INT DEFAULT 0,
                    chunk_index INT NOT NULL,
                    title TEXT,
                    content TEXT NOT NULL,
                    snippet TEXT,
                    content_hash TEXT,
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    embedding vector({dim}),
                    created_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ DEFAULT now()
                );
                """
            )

            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_conv_ext_docs_dedup
                ON conversation_external_docs(user_id, conversation_id, url, chunk_index);
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conv_ext_docs_user_space
                ON conversation_external_docs(user_id, space_id, conversation_id, created_at DESC);
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conv_ext_docs_hash
                ON conversation_external_docs(content_hash);
                """
            )

            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_conv_ext_docs_embedding_ivfflat
                ON conversation_external_docs USING ivfflat (embedding {opclass})
                WITH (lists = {s.pgvector_lists});
                """
            )

        logger.info("Database initialized with vector dim=%s, metric=%s, lists=%s", dim, metric, s.pgvector_lists)


def set_search_runtime(cur: psycopg.Cursor, probes: int):
    # SET LOCAL cannot use bind parameters for the value; interpolate safely as a literal
    from psycopg import sql
    cur.execute(sql.SQL("SET LOCAL ivfflat.probes = {}" ).format(sql.Literal(int(probes))))
