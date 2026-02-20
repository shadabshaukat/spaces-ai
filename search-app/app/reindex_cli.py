from __future__ import annotations

import argparse
import sys
from typing import List

from .db import init_db, get_conn
from .embeddings import embed_texts
from .opensearch_adapter import OpenSearchAdapter
from .users import get_user_by_email


def _fetch_documents(uid: int, doc_id: int | None, space_id: int | None) -> List[dict]:
    docs: List[dict] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            if doc_id is not None:
                cur.execute(
                    "SELECT id, space_id, source_path, created_at FROM documents WHERE id = %s AND user_id = %s",
                    (int(doc_id), int(uid)),
                )
            elif space_id is not None:
                cur.execute(
                    "SELECT id, space_id, source_path, created_at FROM documents WHERE user_id = %s AND space_id = %s",
                    (int(uid), int(space_id)),
                )
            else:
                cur.execute(
                    "SELECT id, space_id, source_path, created_at FROM documents WHERE user_id = %s",
                    (int(uid),),
                )
            for row in cur.fetchall():
                docs.append(
                    {
                        "id": int(row[0]),
                        "space_id": (int(row[1]) if row[1] is not None else None),
                        "source_path": row[2] or "",
                        "created_at": row[3].isoformat() if row[3] else None,
                    }
                )
    return docs


def _fetch_chunks(doc_id: int) -> List[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content FROM chunks WHERE document_id = %s ORDER BY chunk_index ASC",
                (int(doc_id),),
            )
            rows = cur.fetchall()
    return [row[0] for row in rows]


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SpacesAI OpenSearch reindex CLI (per-user scope)")
    parser.add_argument("--email", required=True, help="User email to reindex")
    parser.add_argument("--doc-id", type=int, default=None, help="Specific document ID to reindex")
    parser.add_argument("--space-id", type=int, default=None, help="Specific space ID to reindex")
    parser.add_argument("--refresh", action="store_true", help="Refresh OpenSearch index after indexing")
    args = parser.parse_args(argv)

    if args.doc_id is not None and args.space_id is not None:
        print("[ERROR] Provide either --doc-id or --space-id, not both", file=sys.stderr)
        return 2

    try:
        init_db()
    except Exception as e:
        print(f"[WARN] init_db failed or skipped: {e}")

    email = args.email.strip().lower()
    user = get_user_by_email(email)
    if not user:
        print(f"[ERROR] No user found for {email}", file=sys.stderr)
        return 1
    uid = int(user.get("id") or user.get("user_id"))

    docs = _fetch_documents(uid, args.doc_id, args.space_id)
    if not docs:
        print("[WARN] No documents found for requested scope")
        return 0

    adapter = OpenSearchAdapter()
    total_chunks = 0
    for doc in docs:
        chunks = _fetch_chunks(doc["id"])
        if not chunks:
            continue
        vecs = embed_texts(chunks)
        adapter.index_chunks(
            user_id=uid,
            space_id=doc.get("space_id"),
            doc_id=doc["id"],
            chunks=chunks,
            vectors=vecs,
            file_name=None,
            source_path=doc.get("source_path"),
            file_type="",
            created_at=doc.get("created_at"),
            refresh=args.refresh,
        )
        total_chunks += len(chunks)

    print(f"[DONE] reindexed_docs={len(docs)} chunks={total_chunks} user_id={uid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())