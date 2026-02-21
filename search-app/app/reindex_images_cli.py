from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from .config import settings
from .db import get_conn, init_db
from .store import _process_image_asset


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-embed and re-caption image assets (batch).")
    parser.add_argument("--user-id", type=int, help="Only reindex this user id")
    parser.add_argument("--space-id", type=int, help="Only reindex this space id")
    parser.add_argument("--limit", type=int, default=5000, help="Max images to process")
    parser.add_argument("--offset", type=int, default=0, help="Offset into image_assets table")
    parser.add_argument("--reset", action="store_true", help="Delete existing image_assets rows first")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be processed")
    return parser.parse_args()


def _resolve_abs_path(rel_path: str) -> Optional[Path]:
    if not rel_path:
        return None
    rel = rel_path.lstrip("/\\")
    base = Path(settings.upload_dir).resolve()
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate if candidate.exists() else None


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args()
    init_db()

    where = []
    params: list[object] = []
    if args.user_id is not None:
        where.append("d.user_id = %s")
        params.append(int(args.user_id))
    if args.space_id is not None:
        where.append("d.space_id = %s")
        params.append(int(args.space_id))

    clause = ("WHERE " + " AND ".join(where)) if where else ""

    with get_conn() as conn:
        with conn.cursor() as cur:
            if args.reset:
                cur.execute(
                    f"""
                    DELETE FROM image_assets ia
                    USING documents d
                    WHERE ia.document_id = d.id
                    {clause}
                    """,
                    params,
                )
                deleted = cur.rowcount
                print(f"[INFO] Deleted {deleted} image_assets rows")

            cur.execute(
                f"""
                SELECT d.id, d.user_id, d.space_id, d.source_path, COALESCE(d.metadata,'{{}}'::jsonb)
                FROM documents d
                WHERE d.source_type = 'image'
                {clause}
                ORDER BY d.created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [int(args.limit), int(args.offset)],
            )
            docs = cur.fetchall()

        if args.dry_run:
            print(json.dumps({"documents": len(docs), "reset": args.reset}, indent=2))
            return 0

        ok = 0
        fail = 0
        for doc_id, user_id, space_id, source_path, metadata in docs:
            abs_path = _resolve_abs_path(source_path or "")
            if not abs_path:
                print(f"[WARN] Missing file for doc_id={doc_id}: {source_path}")
                fail += 1
                continue
            try:
                updates = _process_image_asset(
                    conn,
                    doc_id=int(doc_id),
                    user_id=int(user_id),
                    space_id=int(space_id) if space_id is not None else None,
                    file_path=str(abs_path),
                    metadata=metadata if isinstance(metadata, dict) else {},
                )
                if updates:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE documents SET metadata = %s WHERE id = %s",
                        (json.dumps({**(metadata or {}), **updates}), int(doc_id)),
                    )
                ok += 1
                if ok % 50 == 0:
                    print(f"[INFO] processed={ok} fail={fail}")
            except Exception as exc:
                print(f"[ERROR] doc_id={doc_id} failed: {exc}")
                fail += 1
        print(f"[DONE] processed={ok} failed={fail}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())